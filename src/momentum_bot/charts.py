"""Annotated 1-minute candlestick charts of the symbols that entered the Top 5 in one session.

Every annotation comes from a recorded event: Top 5 snapshots and membership changes, Bull Flag
candidates, strategy decisions and simulated fills written by m2-research and m2-diagnostics.
Nothing is interpolated: minutes without a cached bar stay empty on the chart.

``load_session`` and ``chart_events`` need only the standard library. ``figure`` and
``export_session`` need Plotly (``pip install -e ".[viewer]"``). Exported HTML embeds licensed
market data: keep it local, never commit or publish it.
"""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path

from .backtest import StrategyConfig
from .data.market_calendar import ET, session_windows
from .data.provider import Bar
from .research import SCENARIO, STRATEGIES, STRATEGY_LABELS, load_session_bars, read_table

FAILED = ("rejected", "unfilled", "skipped", "filtered")


@dataclass(slots=True)
class SessionData:
    trading_date: str
    session: str
    strategy: str
    bars: dict[str, list[Bar]]  # symbols with a signal, a trade, a scanner candidate or a Top 5 entry
    snapshots: list[dict[str, str]] = field(default_factory=list)
    changes: list[dict[str, str]] = field(default_factory=list)
    flags: list[dict[str, str]] = field(default_factory=list)
    decisions: list[dict[str, str]] = field(default_factory=list)
    trades: list[dict[str, str]] = field(default_factory=list)
    signals: list[dict[str, str]] = field(default_factory=list)  # PR #5 signal ledger rows (entry-time features)
    candidates: list[dict[str, str]] = field(default_factory=list)  # scanner candidates (first bar passing the gates)
    coverage: dict[str, str] = field(default_factory=dict)
    research: bool = False  # show exploratory Top 5 / Bull Flag layers; off for the baseline replay
    sample: str = ""

    @property
    def members(self) -> list[str]:
        """Symbols that entered the cached-universe Top 5, in order of first entry."""
        first: dict[str, str] = {}
        for r in self.snapshots:
            first.setdefault(r["symbol"], r["bar_start_utc"])
        return sorted(first, key=lambda s: (first[s], s))

    @property
    def signal_symbols(self) -> list[str]:
        """Symbols with a strategy decision this session, in order of their first signal."""
        first: dict[str, str] = {}
        for r in sorted(self.decisions, key=lambda r: r["signal_available_utc"]):
            first.setdefault(r["symbol"], r["signal_available_utc"])
        return list(first)

    @property
    def chart_symbols(self) -> list[str]:
        """Every symbol with a chart: signals first, then Top 5 entrants, then remaining scanner candidates."""
        out = dict.fromkeys(self.signal_symbols + self.members + [r["symbol"] for r in self.candidates])
        return [s for s in out if s in self.bars]


def _research_dir(dataset: Path) -> Path:
    return dataset / "research" / "in_sample"


def ledger_dir(dataset: Path, strategy: str, sample: str = "in_sample") -> Path:
    sub = Path(sample) / SCENARIO if strategy == "hos" else Path(sample) / strategy / SCENARIO
    return dataset / "diagnostics" / sub


BASELINE_SAMPLES = ("in_sample", "out_of_sample")  # research variants exist for in_sample only


def _baseline_decisions(signals: list[dict[str, str]]) -> list[dict[str, str]]:
    """Baseline decisions straight from the PR #5 signal ledger: every scanner signal and its outcome."""
    return [{"strategy": "hos", "trigger": "hos_breakout", "symbol": r["symbol"], "trading_date": r["trading_date"],
             "session": r["session"], "signal_bar_start_utc": r["signal_bar_start_utc"],
             "signal_available_utc": r["signal_available_utc"], "top5_rank": "", "outcome": r["outcome"],
             "reason": r["reason"]} for r in signals]


def group_by_session(rows: list[dict[str, str]]) -> dict[tuple[str, str], list[dict[str, str]]]:
    out: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in rows:
        out[(r["trading_date"], r["session"])].append(r)
    return dict(out)


@dataclass(slots=True)
class ReplayTables:
    """Everything the viewer shows, read once from local outputs and grouped by (date, session).

    The baseline needs only the PR #5 ledgers (both samples). Research tables (Top 5, Bull Flag, variant
    ledgers) are optional and in-sample only. Bars load lazily per session."""

    manifest: dict[str, object]
    signals: dict[str, dict[tuple[str, str], list[dict[str, str]]]]
    trades: dict[str, dict[tuple[str, str], list[dict[str, str]]]]
    decisions: dict[str, dict[tuple[str, str], list[dict[str, str]]]]
    candidates: dict[tuple[str, str], list[dict[str, str]]]
    snapshots: dict[tuple[str, str], list[dict[str, str]]] = field(default_factory=dict)
    changes: dict[tuple[str, str], list[dict[str, str]]] = field(default_factory=dict)
    flags: dict[tuple[str, str], list[dict[str, str]]] = field(default_factory=dict)
    coverage: dict[tuple[str, str], dict[str, str]] = field(default_factory=dict)

    @property
    def as_of(self) -> datetime:
        return datetime.fromisoformat(str(self.manifest["as_of_utc"]))

    @property
    def has_research(self) -> bool:
        return bool(self.snapshots)

    def sample_of(self, d: str) -> str:
        for name in ("in_sample", "embargo", "out_of_sample"):
            blk = self.manifest["chronological_split"][name]  # type: ignore[index]
            if blk["first"] <= d <= blk["last"]:
                return name
        return "outside dataset"

    def dates(self, research: bool = False) -> list[str]:
        """Trading dates with baseline ledgers (or research outputs), oldest first."""
        keys = self.snapshots if research else self.signals.get("hos", {})
        return sorted({d for d, _ in keys})

    @classmethod
    def load(cls, dataset: Path) -> ReplayTables:
        manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
        signals: dict[str, dict] = {}
        trades: dict[str, dict] = {}
        for k in STRATEGIES:
            sig_rows: list[dict[str, str]] = []
            trade_rows: list[dict[str, str]] = []
            for smp in BASELINE_SAMPLES if k == "hos" else ("in_sample",):
                path = ledger_dir(dataset, k, smp)
                if (path / "signal_ledger.csv").is_file():
                    sig_rows += read_table(path / "signal_ledger.csv")
                if (path / "trade_ledger.csv").is_file():
                    trade_rows += read_table(path / "trade_ledger.csv")
            signals[k], trades[k] = group_by_session(sig_rows), group_by_session(trade_rows)
        if not signals["hos"]:
            raise FileNotFoundError(f"{dataset / 'diagnostics'} has no baseline signal ledgers; run m2-diagnostics first")
        base = _research_dir(dataset)
        dec = read_table(base / "decisions.csv.gz") if (base / "decisions.csv.gz").is_file() else []
        decisions = {"hos": {k: _baseline_decisions(v) for k, v in signals["hos"].items()}}
        for k in STRATEGIES[1:]:
            decisions[k] = group_by_session([r for r in dec if r["strategy"] == k])
        cand = [{**r, "bar_start_utc": datetime.fromisoformat(r["bar_start_utc"]).isoformat(),
                 "observed_at_utc": datetime.fromisoformat(r["observed_at_utc"]).isoformat()}
                for r in read_table(dataset / "candidates.csv.gz") if r["feed"] == "sip"] \
            if (dataset / "candidates.csv.gz").is_file() else []
        out = cls(manifest, signals, trades, decisions, group_by_session(cand))
        if (base / "top5_snapshots.csv.gz").is_file():
            out.snapshots = group_by_session(read_table(base / "top5_snapshots.csv.gz"))
            out.changes = group_by_session(read_table(base / "top5_changes.csv.gz"))
            out.flags = group_by_session(read_table(base / "bullflag_candidates.csv.gz"))
            out.coverage = {(r["trading_date"], r["session"]): r for r in read_table(base / "top5_coverage.csv")}
        return out

    def session(self, dataset: Path, d: str, session: str, strategy: str = "hos", research: bool = False) -> SessionData:
        """One session's data; bars are read from the SIP cache only now. Raises FileNotFoundError if absent."""
        if strategy != "hos" and not research:
            raise ValueError("research strategies need research=True")
        key = (d, session)
        snaps = self.snapshots.get(key, []) if research else []
        decisions = self.decisions.get(strategy, {}).get(key, [])
        trades = self.trades.get(strategy, {}).get(key, [])
        cands = self.candidates.get(key, [])
        wanted = {r["symbol"] for r in (*snaps, *decisions, *trades, *cands)}
        bars = load_session_bars(dataset, d, session, self.as_of)
        if bars is None:
            raise FileNotFoundError(f"no cached SIP bars for {d} {session}")
        return SessionData(d, session, strategy, {s: bars.get(s, []) for s in wanted}, snaps,
                           self.changes.get(key, []) if research else [], self.flags.get(key, []) if research else [],
                           decisions, trades, self.signals.get(strategy, {}).get(key, []), cands,
                           self.coverage.get(key, {}), research, self.sample_of(d))


def _f(x: str | None) -> float | None:
    """Numeric field of a ledger row; empty and nan mean unknown."""
    v = float(x) if x not in (None, "") else None
    return v if v == v else None


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


def chart_events(data: SessionData, symbol: str, *, include_failed_flags: bool = False,
                 strat: StrategyConfig = StrategyConfig()) -> list[dict[str, object]]:
    """Annotations for one symbol, each copied from a recorded row (time, price, label, source)."""
    bars = data.bars.get(symbol, [])
    ev: list[dict[str, object]] = []
    for r in data.changes:  # empty unless research layers are on
        if r["symbol"] != symbol:
            continue
        label = {"enter": f"Top 5 (cached universe) enter #{r['rank']}",
                 "exit": f"Top 5 (cached universe) exit (was #{r['prev_rank']}, {r.get('reason')})",
                 "rank_change": f"Top 5 (cached universe) #{r['prev_rank']} → #{r['rank']}"}[r["event"]]
        label += f" · known {et_time(r['available_utc'])}"
        ev.append({"kind": f"top5_{r['event']}", "t": r["available_utc"], "price": _bar_close_at(bars, r["bar_start_utc"]),
                   "label": label, "rank": _f(r["rank"])})
    for r in data.flags:
        if r["symbol"] != symbol or (r["qualified"] != "True" and not include_failed_flags):
            continue
        if r["qualified"] == "True":
            ev.append({"kind": "flagpole", "t": r["pole_start_utc"], "t_end": r["pole_end_utc"],
                       "price": _f(r["pole_base"]), "price_end": _f(r["pole_top"]),
                       "label": f"flagpole +{float(r['pole_gain_pct']):.1f}% ({r['pole_bars']} bars)"})
            ev.append({"kind": "flag", "t": r["flag_start_utc"], "t_end": r["flag_end_utc"],
                       "price": _f(r["flag_low"]), "price_end": _f(r["flag_high"]),
                       "label": f"flag {r['flag_bars']} bars, pullback {float(r['pullback_share']) * 100:.0f}%"})
            ev.append({"kind": "flag_resistance", "t": r["flag_start_utc"], "t_end": r["breakout_bar_start_utc"],
                       "price": _f(r["resistance"]), "label": f"resistance {float(r['resistance']):.4g}"})
        ev.append({"kind": "flag_breakout" if r["qualified"] == "True" else "flag_failed",
                   "t": r["breakout_bar_start_utc"], "price": _f(r["breakout_price"]),
                   "label": f"Bull Flag breakout bar {et_time(r['breakout_bar_start_utc'])[:5]} closed "
                            f"{float(r['breakout_price']):.4f} ({r['reason']}, Top 5 #{r['top5_rank'] or '–'}); "
                            f"known {et_time(r['available_utc'])}"})
    for r in data.candidates:
        if r["symbol"] == symbol:
            ev.append({"kind": "scanner_candidate", "t": r["bar_start_utc"], "price": _f(r["price"]),
                       "label": f"scanner candidate: bar {et_time(r['bar_start_utc'])[:5]} closed {float(r['price']):.4f}, "
                                f"change {float(r['change_vs_ref']) * 100:+.1f}%, session volume "
                                f"{int(r['cumulative_volume']):,}; known {et_time(r['observed_at_utc'])}"})
    ledger = {(r["symbol"], r["signal_available_utc"]): r for r in data.signals}
    for r in data.decisions:
        if r["symbol"] != symbol:
            continue
        outcome = r["outcome"]
        led = ledger.get((r["symbol"], r["signal_available_utc"]), {})
        price = _f(led.get("price")) or _bar_close_at(bars, r["signal_bar_start_utc"])
        quote = (f"; signal quote {led.get('signal_quote_state') or 'none'}"
                 + (f", spread {float(led['signal_spread_bps']):.1f} bps" if _f(led.get("signal_spread_bps")) is not None else "")
                 + (f", age {float(led['signal_quote_age_s']):.2f} s" if _f(led.get("signal_quote_age_s")) is not None else "")
                 ) if led and outcome != "skipped" else ""
        # candle_close_confirmation: the trigger bar must close before the signal exists
        ev.append({"kind": f"signal_{'failed' if outcome in FAILED else 'filled'}", "t": r["signal_bar_start_utc"],
                   "price": price, "outcome": outcome, "reason": r["reason"],
                   "label": f"{r['trigger']}: {outcome} ({r['reason']}) · trigger bar {et_time(r['signal_bar_start_utc'])[:5]} "
                            f"closed {price:.4f}" if price is not None else f"{r['trigger']}: {outcome} ({r['reason']})"})
        rank = f" · Top 5 (cached universe) #{r['top5_rank'] or '–'}" if data.research else ""
        ev[-1]["label"] = f"{ev[-1]['label']}; signal known {et_time(r['signal_available_utc'])}{quote}{rank}"
    for r in data.trades:
        if r["symbol"] != symbol:
            continue
        entry = float(r["entry_price"])
        ev.append({"kind": "entry_fill", "t": r["entry_first_fill_utc"], "price": entry,
                   "label": f"entry {r['filled_qty']} sh @ {entry:.4f} ({r['fill']}) at {et_time(r['entry_first_fill_utc'], True)}"})
        sold, left = int(r.get("exit_qty") or r["filled_qty"]), int(r.get("remaining_qty") or 0)
        if sold and _f(r["exit_price"]) is not None:  # nothing is drawn for shares that never sold
            result = f"{float(r['r_multiple']):+.2f}R" if _f(r["r_multiple"]) is not None else "incomplete exit, no R"
            ev.append({"kind": "exit_fill", "t": r["exit_last_fill_utc"], "price": float(r["exit_price"]),
                       "label": f"exit {r['exit_reason']} {sold} sh @ {float(r['exit_price']):.4f} at "
                                f"{et_time(r['exit_last_fill_utc'], True)}, {result}"})
        if left:
            mark = _f(r.get("mark_price"))
            ev.append({"kind": "unsold_remainder", "t": r.get("mark_utc") or r["exit_last_fill_utc"], "price": mark,
                       "label": f"incomplete exit: {left} shares unsold at window end {et_time(r.get('mark_utc') or r['exit_last_fill_utc'])}, "
                                + (f"marked {mark:.4g} (not realized)" if mark is not None else "no bid to mark")})
        for kind, px in (("stop", entry * (1 - strat.stop_pct)), ("target", entry * (1 + strat.stop_pct * strat.target_r))):
            ev.append({"kind": kind, "t": r["entry_first_fill_utc"], "t_end": r["exit_trigger_utc"], "price": px,
                       "label": f"{kind} {px:.4f} (from {et_time(r['entry_first_fill_utc'])} to exit trigger "
                                f"{et_time(r['exit_trigger_utc'])})"})
    ev.sort(key=lambda e: (str(e["t"]), str(e["kind"])))
    return ev


def rank_series(data: SessionData, symbol: str) -> tuple[list[datetime], list[int | None]]:
    """Rank after every bar of the session (None while outside the Top 5), from the snapshots."""
    w = session_windows(datetime.fromisoformat(data.trading_date).date())[data.session]
    by_t = {r["bar_start_utc"]: int(r["rank"]) for r in data.snapshots if r["symbol"] == symbol}
    xs: list[datetime] = []
    ys: list[int | None] = []
    t = w.start_utc
    while t < w.end_utc:
        xs.append(t + timedelta(minutes=1))
        ys.append(by_t.get(t.isoformat()))
        t += timedelta(minutes=1)
    return xs, ys


STYLE = {  # kind -> (marker symbol, color)
    "top5_enter": ("triangle-up", "#1b9e77"), "top5_exit": ("triangle-down", "#d95f02"),
    "top5_rank_change": ("diamond-open", "#7570b3"), "flag_breakout": ("star", "#e6ab02"),
    "flag_failed": ("x-thin-open", "#999999"), "signal_failed": ("x", "#d62728"),
    "signal_filled": ("circle-open", "#1f77b4"), "entry_fill": ("triangle-right", "#2ca02c"),
    "scanner_candidate": ("hexagon-open", "#17becf"),
    "exit_fill": ("square", "#000000"), "unsold_remainder": ("square-open", "#d62728"),
}


def _et(t: object) -> datetime:
    return datetime.fromisoformat(str(t)).astimezone(ET).replace(tzinfo=None)


def figure(data: SessionData, symbol: str, focus: tuple[str, str] | None = None, *,
           include_failed_flags: bool = False):  # noqa: ANN201 - plotly Figure
    """Interactive candlestick + volume + Top 5 rank chart. ``focus`` = (start, end) UTC ISO for a zoomed view."""
    import plotly.graph_objects as go
    from plotly.subplots import make_subplots

    bars = data.bars.get(symbol, [])
    w = session_windows(datetime.fromisoformat(data.trading_date).date())[data.session]
    rows = 3 if data.research else 2
    fig = make_subplots(rows=rows, cols=1, shared_xaxes=True,
                        row_heights=[0.62, 0.2, 0.18] if data.research else [0.72, 0.28], vertical_spacing=0.03)
    x = [_et(b.timestamp_utc) for b in bars]
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
    rx, ry = rank_series(data, symbol) if data.research else ([], [])
    if data.research:
        fig.add_trace(go.Scatter(x=[_et(t) for t in rx], y=ry, mode="lines", line_shape="hv", name="Top 5 rank (cached universe)",
                             line_color="#7570b3", connectgaps=False), row=3, col=1)
    events = chart_events(data, symbol, include_failed_flags=include_failed_flags)
    for e in events:
        kind = str(e["kind"])
        if kind in ("flagpole", "flag"):
            fig.add_shape(type="rect", x0=_et(e["t"]), x1=_et(e["t_end"]) + timedelta(minutes=1), y0=e["price"],
                          y1=e["price_end"], line_width=0, opacity=0.18, layer="below",
                          fillcolor="#2ca02c" if kind == "flagpole" else "#ff7f0e", row=1, col=1)
        elif kind in ("flag_resistance", "stop", "target"):
            color = {"flag_resistance": "#ff7f0e", "stop": "#d62728", "target": "#2ca02c"}[kind]
            fig.add_shape(type="line", x0=_et(e["t"]), x1=_et(e["t_end"]) + timedelta(minutes=1), y0=e["price"],
                          y1=e["price"], line=dict(color=color, width=1.5, dash="dot"), row=1, col=1)
    for kind, (sym, color) in STYLE.items():
        pts = [e for e in events if e["kind"] == kind and e.get("price") is not None]
        if pts:
            fig.add_trace(go.Scatter(x=[_et(e["t"]) for e in pts], y=[e["price"] for e in pts], mode="markers",
                                     name=kind.replace("_", " "), text=[e["label"] for e in pts], hoverinfo="text",
                                     marker=dict(symbol=sym, size=11, color=color, line=dict(width=1.5, color=color))),
                          row=1, col=1)
    have = len(bars)
    title = (f"{symbol} · {data.trading_date} {data.session} · {STRATEGY_LABELS[data.strategy]} · "
             f"{have} of {w.minutes} minutes have a bar (empty minutes = no trades or no data; never filled in)<br>"
             "<sup>Historical replay, not live. candle_close_confirmation: a signal exists only after its trigger "
             "candle closes; simulated orders arrive after that close plus latency. Times are US Eastern (ET)."
             + (" Top 5 = cached sub-$20 universe, not market-wide." if data.research else "") + "</sup>")
    fig.update_layout(title=dict(text=title, font_size=13), height=720, xaxis_rangeslider_visible=False,
                      hovermode="closest", legend=dict(orientation="h", y=-0.08), margin=dict(l=50, r=20, t=50, b=40))
    fig.update_yaxes(title_text="price", row=1, col=1)
    fig.update_yaxes(title_text="volume", row=2, col=1)
    if data.research:
        fig.update_yaxes(title_text="Top 5*", range=[5.5, 0.5], dtick=1, row=3, col=1)
    fig.update_xaxes(title_text="time (US Eastern, ET)", row=rows, col=1)
    if focus:
        t0, t1 = (datetime.fromisoformat(t) for t in focus)
        fig.update_xaxes(range=[_et(t0), _et(t1)])
        inside = [b for b in bars if t0 <= b.timestamp_utc <= t1]
        if inside:  # plotly scales y to all data; rescale to the focused window
            lo = min([b.low for b in inside] + [float(e["price"]) for e in events if e.get("price") is not None  # type: ignore[arg-type]
                                                 and t0 <= datetime.fromisoformat(str(e["t"])) <= t1])
            hi = max([b.high for b in inside] + [float(e["price"]) for e in events if e.get("price") is not None  # type: ignore[arg-type]
                                                  and t0 <= datetime.fromisoformat(str(e["t"])) <= t1])
            pad = (hi - lo) * 0.08 or hi * 0.01
            fig.update_yaxes(range=[lo - pad, hi + pad], row=1, col=1)
            fig.update_yaxes(range=[0, max(b.volume for b in inside) * 1.1], row=2, col=1)
    else:
        fig.update_xaxes(range=[_et(w.start_utc), _et(w.end_utc)])
    return fig


def export_session(dataset: Path, d: str, session: str, strategy: str = "hos",
                   tables: ReplayTables | None = None) -> Path:
    """One standalone HTML file with every Top 5 member's chart for the session (Plotly inlined once)."""
    tables = tables or ReplayTables.load(dataset)
    research = strategy != "hos"
    if research and (d, session) not in tables.snapshots:
        raise ValueError(f"no research outputs for {d} {session} (research variants cover in-sample days only)")
    data = tables.session(dataset, d, session, strategy, research)
    parts = []
    for i, sym in enumerate(data.chart_symbols):
        parts.append(figure(data, sym).to_html(full_html=False, include_plotlyjs="inline" if i == 0 else False))
    path = _research_dir(dataset) / "charts" / f"{d}_{session}_{strategy}.html"
    path.parent.mkdir(parents=True, exist_ok=True)
    head = (f"<!doctype html><html><head><meta charset='utf-8'><title>{d} {session} Top 5 charts</title></head>"
            f"<body style='font-family:sans-serif;margin:16px'><h2>{d} {session} · {STRATEGY_LABELS[strategy]}</h2>"
            "<p>Simulated research output from cached historical SIP data; no orders. Local only: contains licensed "
            "market data. Top 5 is ranked within the cached sub-$20 universe, not market-wide.</p>")
    path.write_text(head + "\n".join(parts) + "</body></html>", encoding="utf-8")
    return path


def trade_focus(trade: Mapping[str, str], before_min: int = 15, after_min: int = 20) -> tuple[str, str]:
    t0 = datetime.fromisoformat(trade["signal_bar_start_utc"]) - timedelta(minutes=before_min)
    t1 = datetime.fromisoformat(trade["exit_last_fill_utc"]) + timedelta(minutes=after_min)
    return t0.isoformat(), t1.isoformat()


SESSIONS = ("premarket", "afterhours")


def daily_summary(tables: ReplayTables, d: str, strategy: str = "hos", session: str | None = None) -> dict[str, object]:
    """Counts and simulated P&L for one date (optionally one session), straight from the ledgers.

    Net P&L covers completed exits only; an incomplete exit's realized part and its unrealized mark are
    reported apart and never added to it. A missing mark stays unknown (None), not zero."""
    keys = [(d, s) for s in ((session,) if session else SESSIONS)]
    sig = [r for k in keys for r in tables.signals.get(strategy, {}).get(k, [])]
    trades = [r for k in keys for r in tables.trades.get(strategy, {}).get(k, [])]
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
    w = session_windows(datetime.fromisoformat(data.trading_date).date())[data.session]
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
    thin = sorted(s for s in data.signal_symbols if len(data.bars.get(s, [])) < w.minutes / 2)
    if thin:
        out.append(f"Sparse bars (fewer than half the session's {w.minutes} minutes traded): {', '.join(thin)}. "
                   "Empty minutes are shown as gaps.")
    return out
