"""Historical replay of the baseline strategy: validated local ledgers, annotated 1-minute SIP charts.

Every annotation comes from a recorded row: scanner candidates (m1-dataset), signal outcomes and
simulated fills (m2-backtest, m2-diagnostics). Nothing is interpolated: minutes without a cached
bar stay empty on the chart. Before anything is shown, each sample's ledgers are checked against
the provenance that m2-diagnostics recorded (``validate_sample``); a sample whose files changed
since then is refused, never shown stale.

``ReplayTables``, ``chart_events`` and ``daily_summary`` need only the standard library. ``figure``
and ``export_session`` need Plotly (``pip install -e ".[viewer]"``). Exported HTML embeds licensed
market data: keep it local, never commit or publish it.
"""

from __future__ import annotations

import csv
import gzip
import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta
from pathlib import Path

from .backtest import EXIT_SLACK, StrategyConfig
from .data.market_calendar import ET, session_windows
from .data.normalize import normalize
from .data.provider import Bar
from .dataset import _read_bars
from .diagnostics import hash_check

SCENARIO = "base_cap50"  # the frozen configuration from reports/m2_backtest.md
SAMPLES = ("in_sample", "out_of_sample")
SESSIONS = ("premarket", "afterhours")
FAILED = ("rejected", "unfilled", "skipped")

# Ledger columns the viewer reads; a ledger without them predates the corrected PR #4 / PR #5 schema.
SIGNAL_COLUMNS = ("symbol", "trading_date", "session", "sample", "signal_bar_start_utc", "signal_available_utc",
                  "outcome", "reason", "quotes_cached", "signal_quote_state")
TRADE_COLUMNS = ("symbol", "trading_date", "session", "sample", "signal_bar_start_utc", "signal_available_utc",
                 "entry_first_fill_utc", "entry_price", "filled_qty", "fill", "exit_trigger_utc", "exit_last_fill_utc",
                 "exit_reason", "exit_complete", "exit_qty", "remaining_qty", "exit_price", "net_usd", "realized_usd",
                 "mark_price", "marked_usd", "r_multiple")


# ---------- local files ----------

def read_table(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="", encoding="utf-8") as fh:  # type: ignore[operator]
        return list(csv.DictReader(fh))


def read_json(path: Path) -> dict:
    return json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {}


def ledger_dir(dataset: Path, sample: str) -> Path:
    return dataset / "diagnostics" / sample / SCENARIO


def session_bar_file(dataset: Path, d: str, session: str) -> Path | None:
    found = sorted((dataset / "cache" / "sip").glob(f"{d}_{session}_*.csv.gz"))
    return found[0] if len(found) == 1 else None


def load_session_bars(dataset: Path, d: str, session: str, as_of: datetime) -> dict[str, list[Bar]] | None:
    """Completed, in-session SIP 1-minute bars from the dataset cache, grouped by symbol. None if missing."""
    path = session_bar_file(dataset, d, session)
    if path is None:
        return None
    day = date.fromisoformat(d)
    sbars, _ = normalize(_read_bars(path, "sip"), {day: session_windows(day)}, as_of_utc=as_of)
    out: dict[str, list[Bar]] = defaultdict(list)
    for sb in sbars:
        if sb.session == session:
            out[sb.bar.symbol].append(sb.bar)
    return dict(out)


def _f(x: str | None) -> float | None:
    """Numeric field of a ledger row; empty and nan mean unknown."""
    v = float(x) if x not in (None, "") else None
    return v if v == v else None


# ---------- provenance: refuse stale or mismatched ledgers ----------

@dataclass(slots=True)
class SampleCheck:
    sample: str
    status: str  # ok | absent (no ledgers: nothing to show) | mismatch (refused)
    problems: list[str] = field(default_factory=list)
    notes: list[str] = field(default_factory=list)
    diagnostics: dict = field(default_factory=dict)


def validate_sample(dataset: Path, sample: str, manifest: Mapping[str, object] | None = None) -> SampleCheck:
    """Check one sample's PR #5 ledgers before display.

    The ledgers must still match the provenance m2-diagnostics recorded: the same manifest,
    breakout_matches.csv, backtest summary and PR #4 trades/attempts files (hashed with
    ``diagnostics.HASH_POLICY``), the current ledger schema, the recorded row counts, and the
    backtest summary's completed-trade count, net P&L and incomplete exits."""
    led = ledger_dir(dataset, sample)
    if not (led / "signal_ledger.csv").is_file():
        return SampleCheck(sample, "absent", notes=[f"no diagnostics ledgers in {led}"])
    chk = SampleCheck(sample, "ok")
    p = chk.problems
    diag = read_json(dataset / f"diagnostics_{sample}_{SCENARIO}.json")
    chk.diagnostics = diag
    pv = diag.get("provenance")
    if not pv:
        p.append(f"diagnostics_{sample}_{SCENARIO}.json with a provenance record is missing; rerun m2-diagnostics")
        chk.status = "mismatch"
        return chk
    if (diag.get("sample"), diag.get("scenario")) != (sample, SCENARIO):
        p.append(f"diagnostics file describes {diag.get('sample')}/{diag.get('scenario')}, not {sample}/{SCENARIO}")
    policy = pv.get("hash_policy")
    bt = dataset / "backtest" / sample / SCENARIO
    for label, path, recorded in (
            ("manifest.json", dataset / "manifest.json", pv["dataset"]["manifest_sha256"]),
            ("breakout_matches.csv", dataset / "breakout_matches.csv", pv["dataset"]["breakout_matches_sha256"]),
            (f"backtest_summary_{sample}.json", dataset / f"backtest_summary_{sample}.json",
             pv["backtest_run"]["summary_sha256"]),
            ("trades.csv", bt / "trades.csv", pv["backtest_run"]["trades_sha256"]),
            ("attempts.csv", bt / "attempts.csv", pv["backtest_run"]["attempts_sha256"])):
        state = hash_check(path, recorded, policy)
        if state == "missing":
            p.append(f"{label} is missing ({path})")
        elif state == "mismatch":
            p.append(f"{label} changed since the diagnostics were generated (sha256 differs from the recorded "
                     f"{str(recorded)[:12]}…); rerun m2-backtest and m2-diagnostics")
        elif state == "legacy_crlf":
            chk.notes.append(f"{label} matched its recorded hash with Windows CRLF line endings (recorded before "
                             "the canonical LF hashing policy)")
    signals, trades = read_table(led / "signal_ledger.csv"), read_table(led / "trade_ledger.csv") \
        if (led / "trade_ledger.csv").is_file() else []
    for name, rows, want in (("signal_ledger.csv", signals, SIGNAL_COLUMNS), ("trade_ledger.csv", trades, TRADE_COLUMNS)):
        header = set(rows[0]) if rows else set(want)
        if not set(want) <= header:
            p.append(f"{name} lacks {sorted(set(want) - header)}: it predates the current ledger schema; "
                     "rerun m2-diagnostics")
    run = pv["backtest_run"]
    if not (len(signals) == diag.get("signals") == run.get("attempts_rows")):
        p.append(f"signal_ledger.csv has {len(signals)} rows; the diagnostics recorded {diag.get('signals')} "
                 f"signals from {run.get('attempts_rows')} attempts")
    if not (len(trades) == diag.get("trades") == run.get("trades_rows")):
        p.append(f"trade_ledger.csv has {len(trades)} rows; the diagnostics recorded {diag.get('trades')} trades "
                 f"from {run.get('trades_rows')} backtest trades")
    if {r.get("sample") for r in (*signals, *trades)} - {sample}:
        p.append(f"ledgers contain rows of another sample than {sample}")
    blk = (manifest or read_json(dataset / "manifest.json")).get("chronological_split", {}).get(sample)  # type: ignore[union-attr]
    if blk and any(not blk["first"] <= r["trading_date"] <= blk["last"] for r in (*signals, *trades)):
        p.append(f"ledger dates fall outside the manifest's {sample} range {blk['first']}..{blk['last']}")
    if not p:  # P&L reconciliation against the backtest run the ledgers claim to explain
        res = read_json(dataset / f"backtest_summary_{sample}.json").get("results", {}).get(SCENARIO, {}).get("all")
        if not res:
            p.append(f"backtest_summary_{sample}.json has no {SCENARIO} result")
        else:
            done = [t for t in trades if _f(t["r_multiple"]) is not None]
            net = sum(float(t["net_usd"]) for t in done)
            open_ = len(trades) - len(done)
            if (len(trades), len(done), open_) != (res["entries"], res["trades"], res["incomplete_exits"]["count"]) \
                    or abs(net - res["net_usd"]) > 1e-6:
                p.append(f"ledgers do not reconcile with backtest_summary_{sample}.json: {len(trades)} entries, "
                         f"{len(done)} completed, {open_} incomplete, net ${net:.2f} against {res['entries']}, "
                         f"{res['trades']}, {res['incomplete_exits']['count']}, ${res['net_usd']:.2f}")
    chk.status = "mismatch" if p else "ok"
    return chk


# ---------- replay tables ----------

def group_by_session(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    out: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        out[(r["trading_date"], r["session"])].append(r)
    return dict(out)


class ReplayDataError(ValueError):
    """No sample has ledgers that can be shown."""


@dataclass(slots=True)
class SessionData:
    trading_date: str
    session: str
    bars: dict[str, list[Bar]]  # symbols with a signal, a trade or a scanner candidate
    signals: list[dict[str, str]] = field(default_factory=list)  # PR #5 signal ledger rows (entry-time features)
    trades: list[dict[str, str]] = field(default_factory=list)  # PR #5 trade ledger rows
    candidates: list[dict[str, str]] = field(default_factory=list)  # scanner candidates (first bar passing the gates)
    sample: str = ""

    @property
    def signal_symbols(self) -> list[str]:
        """Symbols with a signal this session, in order of their first signal."""
        first: dict[str, str] = {}
        for r in sorted(self.signals, key=lambda r: r["signal_available_utc"]):
            first.setdefault(r["symbol"], r["signal_available_utc"])
        return list(first)

    @property
    def chart_symbols(self) -> list[str]:
        """Every symbol with a chart: signals first, then the remaining scanner candidates."""
        out = dict.fromkeys(self.signal_symbols + [r["symbol"] for r in self.candidates])
        return [s for s in out if s in self.bars]


@dataclass(slots=True)
class ReplayTables:
    """Everything the viewer shows, read once from validated local outputs and grouped by (date, session).
    Only samples whose ledgers pass ``validate_sample`` are loaded; bars load lazily per session."""

    manifest: dict[str, object]
    checks: dict[str, SampleCheck]
    signals: dict[tuple[str, str], list[dict[str, str]]]
    trades: dict[tuple[str, str], list[dict[str, str]]]
    candidates: dict[tuple[str, str], list[dict[str, str]]]

    @property
    def as_of(self) -> datetime:
        return datetime.fromisoformat(str(self.manifest["as_of_utc"]))

    def sample_of(self, d: str) -> str:
        for name in ("in_sample", "embargo", "out_of_sample"):
            blk = self.manifest["chronological_split"].get(name)  # type: ignore[union-attr]
            if blk and blk["first"] <= d <= blk["last"]:
                return name
        return "outside dataset"

    def dates(self) -> list[str]:
        """Trading dates with validated ledgers, oldest first."""
        return sorted({d for d, _ in self.signals})

    @classmethod
    def load(cls, dataset: Path) -> ReplayTables:
        manifest = read_json(dataset / "manifest.json")
        if not manifest:
            raise ReplayDataError(f"{dataset / 'manifest.json'} not found; is this a dataset folder?")
        checks = {s: validate_sample(dataset, s, manifest) for s in SAMPLES}
        ok = [s for s, c in checks.items() if c.status == "ok"]
        if not ok:
            raise ReplayDataError("no sample can be shown: " + "; ".join(
                f"{s}: {', '.join(c.problems or c.notes)}" for s, c in checks.items())
                + ". Run m2-backtest and m2-diagnostics on this dataset")
        sig: list[dict[str, str]] = []
        trd: list[dict[str, str]] = []
        for s in ok:
            sig += read_table(ledger_dir(dataset, s) / "signal_ledger.csv")
            if (ledger_dir(dataset, s) / "trade_ledger.csv").is_file():
                trd += read_table(ledger_dir(dataset, s) / "trade_ledger.csv")
        dates = {r["trading_date"] for r in sig}
        cand = [{**r, "bar_start_utc": datetime.fromisoformat(r["bar_start_utc"]).isoformat(),
                 "observed_at_utc": datetime.fromisoformat(r["observed_at_utc"]).isoformat()}
                for r in read_table(dataset / "candidates.csv.gz") if r["feed"] == "sip" and r["trading_date"] in dates] \
            if (dataset / "candidates.csv.gz").is_file() else []
        return cls(manifest, checks, group_by_session(sig), group_by_session(trd), group_by_session(cand))

    def session(self, dataset: Path, d: str, session: str) -> SessionData:
        """One session's data; bars are read from the SIP cache only now. Raises FileNotFoundError if absent."""
        key = (d, session)
        signals, trades, cands = self.signals.get(key, []), self.trades.get(key, []), self.candidates.get(key, [])
        bars = load_session_bars(dataset, d, session, self.as_of)
        if bars is None:
            raise FileNotFoundError(f"no cached SIP bars for {d} {session}")
        wanted = {r["symbol"] for r in (*signals, *trades, *cands)}
        return SessionData(d, session, {s: bars.get(s, []) for s in wanted}, signals, trades, cands, self.sample_of(d))


# ---------- annotations ----------

def et_time(t: object, ms: bool = False) -> str:
    """Exact America/New_York clock time of a UTC ISO timestamp, for tooltips."""
    x = datetime.fromisoformat(str(t)).astimezone(ET)
    return x.strftime("%H:%M:%S") + (f".{x.microsecond // 1000:03d}" if ms else "") + " ET"


def _bar_close_at(bars: list[Bar], t: str) -> float | None:
    """Close of the latest bar starting at or before t (the price known then); None before the first bar."""
    ts = datetime.fromisoformat(t)
    px = None
    for b in bars:
        if b.timestamp_utc > ts:
            break
        px = b.close
    return px


def exit_window_end(trade: Mapping[str, str]) -> datetime:
    """When an exit order stops working and unsold shares are marked: trigger + EXIT_SLACK, at most the
    session close (backtest.simulate_signal). The PR #5 trade ledger does not store it."""
    close = session_windows(date.fromisoformat(trade["trading_date"]))[trade["session"]].end_utc
    return min(datetime.fromisoformat(trade["exit_trigger_utc"]) + EXIT_SLACK, close)


def chart_events(data: SessionData, symbol: str, strat: StrategyConfig = StrategyConfig()) -> list[dict[str, object]]:
    """Annotations for one symbol, each copied from a recorded row (time, price, label)."""
    bars = data.bars.get(symbol, [])
    ev: list[dict[str, object]] = []
    for r in data.candidates:
        if r["symbol"] == symbol:
            ev.append({"kind": "scanner_candidate", "t": r["bar_start_utc"], "price": _f(r["price"]),
                       "label": f"scanner candidate: bar {et_time(r['bar_start_utc'])[:5]} closed {float(r['price']):.4f}, "
                                f"change {float(r['change_vs_ref']) * 100:+.1f}%, session volume "
                                f"{int(r['cumulative_volume']):,}; known {et_time(r['observed_at_utc'])}"})
    for r in data.signals:
        if r["symbol"] != symbol:
            continue
        outcome = r["outcome"]
        price = _f(r.get("price")) or _bar_close_at(bars, r["signal_bar_start_utc"])
        quote = (f"; signal quote {r.get('signal_quote_state') or 'none'}"
                 + (f", spread {float(r['signal_spread_bps']):.1f} bps" if _f(r.get("signal_spread_bps")) is not None else "")
                 + (f", age {float(r['signal_quote_age_s']):.2f} s" if _f(r.get("signal_quote_age_s")) is not None else "")
                 ) if outcome != "skipped" else ""
        # candle_close_confirmation: the trigger bar must close before the signal exists
        label = (f"hos_breakout: {outcome} ({r['reason']}) · trigger bar {et_time(r['signal_bar_start_utc'])[:5]} "
                 f"closed {price:.4f}" if price is not None else f"hos_breakout: {outcome} ({r['reason']})")
        ev.append({"kind": f"signal_{'failed' if outcome in FAILED else 'filled'}", "t": r["signal_bar_start_utc"],
                   "price": price, "outcome": outcome, "reason": r["reason"],
                   "label": f"{label}; signal known {et_time(r['signal_available_utc'])}{quote}"})
    for r in data.trades:
        if r["symbol"] != symbol:
            continue
        entry = float(r["entry_price"])
        ev.append({"kind": "entry_fill", "t": r["entry_first_fill_utc"], "price": entry,
                   "label": f"entry {r['filled_qty']} sh @ {entry:.4f} ({r['fill']}) at {et_time(r['entry_first_fill_utc'], True)}"})
        sold, left = int(r["exit_qty"]), int(r["remaining_qty"])
        if sold and _f(r["exit_price"]) is not None:  # nothing is drawn for shares that never sold
            result = f"{float(r['r_multiple']):+.2f}R" if _f(r["r_multiple"]) is not None else "incomplete exit, no R"
            ev.append({"kind": "exit_fill", "t": r["exit_last_fill_utc"], "price": float(r["exit_price"]),
                       "label": f"exit {r['exit_reason']} {sold} sh @ {float(r['exit_price']):.4f} at "
                                f"{et_time(r['exit_last_fill_utc'], True)}, {result}"})
        if left:
            mark = _f(r.get("mark_price"))
            at = r.get("mark_utc") or exit_window_end(r).isoformat()
            ev.append({"kind": "unsold_remainder", "t": at, "price": mark,
                       "label": f"incomplete exit: {left} shares unsold at window end {et_time(at)}, "
                                + (f"marked {mark:.4g} (not realized)" if mark is not None else "no bid to mark")})
        for kind, px in (("stop", entry * (1 - strat.stop_pct)), ("target", entry * (1 + strat.stop_pct * strat.target_r))):
            ev.append({"kind": kind, "t": r["entry_first_fill_utc"], "t_end": r["exit_trigger_utc"], "price": px,
                       "label": f"{kind} {px:.4f} (from {et_time(r['entry_first_fill_utc'])} to exit trigger "
                                f"{et_time(r['exit_trigger_utc'])})"})
    ev.sort(key=lambda e: (str(e["t"]), str(e["kind"])))
    return ev


STYLE = {  # kind -> (marker symbol, color)
    "signal_failed": ("x", "#d62728"), "signal_filled": ("circle-open", "#1f77b4"),
    "entry_fill": ("triangle-right", "#2ca02c"), "scanner_candidate": ("hexagon-open", "#17becf"),
    "exit_fill": ("square", "#000000"), "unsold_remainder": ("square-open", "#d62728"),
}


def et_naive(t: object) -> datetime:
    """UTC ISO timestamp or datetime -> naive US Eastern wall time, the chart's x-axis."""
    return datetime.fromisoformat(str(t)).astimezone(ET).replace(tzinfo=None)


def figure(data: SessionData, symbol: str, focus: tuple[str, str] | None = None):  # noqa: ANN201 - plotly Figure
    """Interactive candlestick + volume chart. ``focus`` = (start, end) UTC ISO for a zoomed view."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    bars = data.bars.get(symbol, [])
    w = session_windows(date.fromisoformat(data.trading_date))[data.session]
    fig = make_subplots(rows=2, cols=1, shared_xaxes=True, row_heights=[0.72, 0.28], vertical_spacing=0.03)
    x = [et_naive(b.timestamp_utc) for b in bars]
    hover = [f"bar {et_time(b.timestamp_utc)[:5]}–{et_time(b.timestamp_utc + timedelta(minutes=1))[:5]} ET "
             f"(known at its close)<br>O {b.open:.4f} H {b.high:.4f} L {b.low:.4f} C {b.close:.4f}<br>V {b.volume:,}"
             for b in bars]
    fig.add_trace(go.Candlestick(x=x, open=[b.open for b in bars], high=[b.high for b in bars],
                                 low=[b.low for b in bars], close=[b.close for b in bars], name="1m SIP",
                                 text=hover, hoverinfo="text",
                                 increasing_line_color="#26a69a", decreasing_line_color="#ef5350"), row=1, col=1)
    fig.add_trace(go.Bar(x=x, y=[b.volume for b in bars], name="volume", marker_color="#90a4ae",
                         text=[f"{et_time(b.timestamp_utc)[:5]} ET volume {b.volume:,}" for b in bars],
                         hoverinfo="text", textposition="none"), row=2, col=1)
    events = chart_events(data, symbol)
    for e in events:
        if e["kind"] in ("stop", "target"):
            fig.add_shape(type="line", x0=et_naive(e["t"]), x1=et_naive(e["t_end"]) + timedelta(minutes=1),
                          y0=e["price"], y1=e["price"],
                          line=dict(color="#d62728" if e["kind"] == "stop" else "#2ca02c", width=1.5, dash="dot"),
                          row=1, col=1)
    for kind, (sym, color) in STYLE.items():
        pts = [e for e in events if e["kind"] == kind and e.get("price") is not None]
        if pts:
            fig.add_trace(go.Scatter(x=[et_naive(e["t"]) for e in pts], y=[e["price"] for e in pts], mode="markers",
                                     name=kind.replace("_", " "), text=[e["label"] for e in pts], hoverinfo="text",
                                     marker=dict(symbol=sym, size=11, color=color, line=dict(width=1.5, color=color))),
                          row=1, col=1)
    title = (f"{symbol} · {data.trading_date} {data.session} · Original HOS Breakout · "
             f"{len(bars)} of {w.minutes} minutes have a bar (empty minutes = no trades or no data; never filled in)<br>"
             "<sup>Historical replay, not live. candle_close_confirmation: a signal exists only after its trigger "
             "candle closes; simulated orders arrive after that close plus latency. Times are US Eastern (ET).</sup>")
    fig.update_layout(title=dict(text=title, font_size=13), height=640, xaxis_rangeslider_visible=False,
                      hovermode="closest", legend=dict(orientation="h", y=-0.1), margin=dict(l=50, r=20, t=50, b=40))
    fig.update_yaxes(title_text="price", row=1, col=1)
    fig.update_yaxes(title_text="volume", row=2, col=1)
    fig.update_xaxes(title_text="time (US Eastern, ET)", row=2, col=1)
    if focus:
        t0, t1 = (datetime.fromisoformat(t) for t in focus)
        fig.update_xaxes(range=[et_naive(t0), et_naive(t1)])
        inside = [b for b in bars if t0 <= b.timestamp_utc <= t1]
        if inside:  # plotly scales y to all data; rescale to the focused window
            prices = [float(e["price"]) for e in events if e.get("price") is not None  # type: ignore[arg-type]
                      and t0 <= datetime.fromisoformat(str(e["t"])) <= t1]
            lo, hi = min([b.low for b in inside] + prices), max([b.high for b in inside] + prices)
            pad = (hi - lo) * 0.08 or hi * 0.01
            fig.update_yaxes(range=[lo - pad, hi + pad], row=1, col=1)
            fig.update_yaxes(range=[0, max(b.volume for b in inside) * 1.1], row=2, col=1)
    else:
        fig.update_xaxes(range=[et_naive(w.start_utc), et_naive(w.end_utc)])
    return fig


def export_session(dataset: Path, d: str, session: str, tables: ReplayTables | None = None) -> Path:
    """One standalone HTML file with the chart of every symbol with a signal or scanner candidate (Plotly inlined once)."""
    tables = tables or ReplayTables.load(dataset)
    if d not in tables.dates():
        raise ValueError(f"no validated ledgers for {d}; dates available: {tables.dates()[0]}..{tables.dates()[-1]}")
    data = tables.session(dataset, d, session)
    parts = [figure(data, sym).to_html(full_html=False, include_plotlyjs="inline" if i == 0 else False)
             for i, sym in enumerate(data.chart_symbols)]
    if not parts:
        parts = ["<p>No stock had a signal or met the scanner rules in this session.</p>"]
    path = dataset / "charts" / f"{d}_{session}_hos.html"  # local, git-ignored like the rest of the dataset folder
    path.parent.mkdir(parents=True, exist_ok=True)
    head = (f"<!doctype html><html><head><meta charset='utf-8'><title>{d} {session} replay charts</title></head>"
            f"<body style='font-family:sans-serif;margin:16px'><h2>{d} {session} · Original HOS Breakout "
            f"({SCENARIO})</h2><p>Historical replay, not live: simulated fills from cached historical SIP data; no "
            "orders. Local only: contains licensed market data.</p>")
    path.write_text(head + "\n".join(parts) + "</body></html>", encoding="utf-8")
    return path


# ---------- summaries and warnings ----------

def daily_summary(tables: ReplayTables, d: str, session: str | None = None) -> dict[str, object]:
    """Counts and simulated P&L for one date (optionally one session), straight from the ledgers.

    Net P&L covers completed exits only; an incomplete exit's realized part and its unrealized mark are
    reported apart and never added to it. A missing mark stays unknown (None), not zero."""
    keys = [(d, s) for s in ((session,) if session else SESSIONS)]
    sig = [r for k in keys for r in tables.signals.get(k, [])]
    trades = [r for k in keys for r in tables.trades.get(k, [])]
    done = [t for t in trades if _f(t["r_multiple"]) is not None]
    open_ = [t for t in trades if _f(t["r_multiple"]) is None]
    unmarked = sum(1 for t in open_ if _f(t.get("marked_usd")) is None)
    return {"signals": len(sig), "evaluated": sum(1 for r in sig if r["outcome"] != "skipped"),
            "entries": len(trades), "completed_trades": len(done), "incomplete_exits": len(open_),
            "net_usd_completed": sum(float(t["net_usd"]) for t in done),
            "realized_usd_incomplete": sum(float(t["realized_usd"]) for t in open_),
            "marked_usd_incomplete": None if unmarked else sum(float(t["marked_usd"]) for t in open_),
            "unmarked_incomplete_exits": unmarked,
            "outcomes": dict(sorted(Counter(r["outcome"] for r in sig).items()))}


def session_warnings(data: SessionData) -> list[str]:
    """Missing or incomplete data in a session, stated plainly (nothing is filled in)."""
    w = session_windows(date.fromisoformat(data.trading_date))[data.session]
    out = []
    no_quotes = [r for r in data.signals if r.get("quotes_cached") == "False"]
    if no_quotes:
        out.append(f"{len(no_quotes)} evaluated signal(s) have no cached quotes: their spread and quote fields are empty, "
                   "not estimated.")
    no_quote_at_signal = [r for r in data.signals if r["outcome"] != "skipped" and r.get("quotes_cached") == "True"
                          and r.get("signal_quote_state") in ("", None)]
    if no_quote_at_signal:
        out.append(f"{len(no_quote_at_signal)} evaluated signal(s) had no quote at or before the signal time.")
    open_ = [t for t in data.trades if _f(t["r_multiple"]) is None]
    if open_:
        out.append(f"{len(open_)} incomplete exit(s): shares were still unsold when the 2-minute exit window ended; "
                   "they are excluded from net P&L and R.")
    no_bars = sorted(s for s in data.signal_symbols if not data.bars.get(s))
    if no_bars:
        out.append(f"No cached bars for {', '.join(no_bars)} in this session: their charts are empty, not invented.")
    thin = sorted(s for s in data.signal_symbols if 0 < len(data.bars.get(s, [])) < w.minutes / 2)
    if thin:
        out.append(f"Sparse bars (fewer than half the session's {w.minutes} minutes traded): {', '.join(thin)}. "
                   "Empty minutes are shown as gaps.")
    return out
