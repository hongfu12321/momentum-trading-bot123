"""M2 trade diagnostics: why the backtested breakout strategy wins or loses.

Reads the backtest ledgers (trades.csv / attempts.csv) and the cached SIP quotes they used, and adds
per-signal and per-trade diagnostics. It never fetches market data: a missing cache file makes the
affected fields empty, never estimated. It never changes the strategy or its frozen configuration.

Feature groups are kept apart on purpose:
- ENTRY_FEATURES are known at the signal's decision time (scanner inputs and the signal-time quote).
- POST_ENTRY fields (excursions, forward moves, slippage) use quotes after entry. They explain
  outcomes and must never be used as entry filters without a new, separately tested hypothesis.
"""

from __future__ import annotations

import bisect
import csv
import hashlib
import json
from collections import Counter
from collections.abc import Callable, Iterable, Iterator, Mapping
from dataclasses import fields
from datetime import datetime, timedelta
from pathlib import Path
from statistics import fmean, median

from .backtest import (
    SCENARIOS, Attempt, BacktestResult, ExecConfig, Quote, QuoteStore, RiskConfig, Signal, StrategyConfig, Trade,
    _bootstrap_ci, config_record, quote_stages, signals_from_breakouts, with_spread_caps,
)
from .backtest import summarize as summarize_backtest
from .data.market_calendar import ET
from .data.provider import ProviderError
from .quotes import EXECUTABLE

MIN_BUCKET_N = 30  # buckets with fewer completed trades are labelled inconclusive
FORWARD_MINUTES = (1, 3, 5, 10, 15)
FAVORABLE_R = 0.5  # "moved in our favor first": +0.5R reached before -0.5R
NEAR_TARGET_SHARE = 0.8  # "approached target": MFE >= 80% of the target distance
FAST_REVERSAL_S = 60.0
ENTRY_FEATURES = ("session", "hour_et", "price", "change_pct", "session_volume", "volume_ratio",
                  "breakout_strength_bps", "signal_spread_bps", "signal_quote_age_s")
POST_ENTRY = ("seconds_to_fill", "fill", "entry_slippage_bps", "exit_slippage_bps")


class CacheMiss(ProviderError):
    pass


class CacheOnlySource:
    """A quote source that refuses to fetch: diagnostics replay only what the backtest cached."""

    request_count = 0
    bytes_received = 0

    def iter_quotes(self, symbol: str, feed: str, start: datetime, end: datetime) -> Iterator[dict]:
        raise CacheMiss(f"no cached quotes for {symbol} {start.isoformat()}")


# ---------- pure calculations ----------

def prevailing(quotes: list[Quote], t: datetime, *, executable: bool = False) -> Quote | None:
    """Latest quote with timestamp <= t (optionally the latest executable one)."""
    i = bisect.bisect_right([q.t for q in quotes], t) - 1
    while i >= 0 and executable and quotes[i].state != EXECUTABLE:
        i -= 1
    return quotes[i] if i >= 0 else None


def excursions(quotes: list[Quote], entry: float, risk: float, start: datetime, end: datetime) -> dict[str, object]:
    """MFE/MAE in R from executable bids (what the position could be sold at) within [start, end]."""
    marks = [(q.t, (q.bid - entry) / risk) for q in quotes if start <= q.t <= end and q.state == EXECUTABLE]
    if not marks or risk <= 0:
        return {"mfe_r": None, "mae_r": None, "seconds_to_mfe": None, "seconds_to_mae": None, "favorable_first": None}
    t_mfe, mfe = max(marks, key=lambda m: (m[1], -m[0].timestamp()))
    t_mae, mae = min(marks, key=lambda m: (m[1], m[0].timestamp()))
    up = next((t for t, r in marks if r >= FAVORABLE_R), None)
    down = next((t for t, r in marks if r <= -FAVORABLE_R), None)
    first = None if up is None and down is None else (down is None or (up is not None and up < down))
    return {"mfe_r": mfe, "mae_r": mae, "seconds_to_mfe": (t_mfe - start).total_seconds(),
            "seconds_to_mae": (t_mae - start).total_seconds(), "favorable_first": first}


def forward_moves(quotes: list[Quote], entry: float, risk: float, t0: datetime, data_end: datetime,
                  minutes: Iterable[int] = FORWARD_MINUTES) -> dict[str, float | None]:
    """Bid move in R at t0 + k minutes, from the prevailing executable quote; None past the fetched data."""
    out: dict[str, float | None] = {}
    for k in minutes:
        t = t0 + timedelta(minutes=k)
        q = prevailing(quotes, t, executable=True) if t <= data_end else None
        out[f"move_{k}m_r"] = (q.bid - entry) / risk if q and risk > 0 else None
    return out


def outcome(attempt: Mapping[str, str], trade: Mapping[str, str] | None) -> str:
    if attempt["outcome"] == "skipped":
        return "skipped"
    if attempt["outcome"] == "non_fill":
        return "unfilled" if attempt["reason"].startswith("timeout_") else "rejected"
    if trade is None:
        return "unknown"
    if trade["exit_complete"] != "True":
        return "incomplete_exit"
    return "partial" if int(trade["qty"]) < int(trade["requested_qty"]) else "completed"


def bucket_of(value: float | None, edges: list[float], fmt: Callable[[float], str] = lambda x: f"{x:g}") -> str:
    """Half-open buckets [e_i, e_i+1); values below the first edge or missing are labelled explicitly."""
    if value is None or value != value:
        return "unknown"
    if value < edges[0]:
        return f"< {fmt(edges[0])}"
    for lo, hi in zip(edges, edges[1:]):
        if value < hi:
            return f"{fmt(lo)}–{fmt(hi)}"
    return f">= {fmt(edges[-1])}"


def stats(rs: list[float]) -> dict[str, object]:
    wins, losses = [r for r in rs if r > 0], [r for r in rs if r <= 0]
    return {
        "n": len(rs),
        "win_rate": len(wins) / len(rs) if rs else None,
        "avg_r": fmean(rs) if rs else None,
        "median_r": median(rs) if rs else None,
        "profit_factor": sum(wins) / -sum(losses) if losses and sum(losses) < 0 else None,
        "avg_r_ci95": _bootstrap_ci(rs),
        "inconclusive": len(rs) < MIN_BUCKET_N,
    }


def breakdown(trades: list[Mapping[str, object]], key: str, edges: list[float] | None = None,
              order: list[str] | None = None) -> list[dict[str, object]]:
    groups: dict[str, list[float]] = {}
    for t in trades:
        v = t.get(key)
        label = bucket_of(v, edges) if edges else ("unknown" if v is None else str(v))  # type: ignore[arg-type]
        if t.get("r_multiple") is not None:  # incomplete exits have no R
            groups.setdefault(label, []).append(float(t["r_multiple"]))  # type: ignore[arg-type]

    def sort_key(label: str) -> tuple:
        if order and label in order:
            return (0, order.index(label), "")
        if edges and label != "unknown":
            first = label.replace("< ", "").replace(">= ", "").split("–")[0]
            return (1, float(first) + (1e-9 if label.startswith(">=") else 0) - (1e-9 if label.startswith("<") else 0), "")
        return (2, 0.0, label)

    return [{"bucket": b, **stats(groups[b])} for b in sorted(groups, key=sort_key)]


def _q(values: list[float]) -> dict[str, float | None]:
    v = sorted(values)
    if not v:
        return {"n": 0, "p10": None, "median": None, "p90": None, "mean": None}
    return {"n": len(v), "p10": v[int(0.1 * (len(v) - 1))], "median": median(v), "p90": v[int(0.9 * (len(v) - 1))],
            "mean": fmean(v)}


# ---------- assembling ledgers ----------

def _f(x: object) -> float | None:
    try:
        v = float(x)  # type: ignore[arg-type]
    except (TypeError, ValueError):
        return None
    return v if v == v else None


def signal_features(row: Mapping[str, str], sig: Signal) -> dict[str, object]:
    """Entry-time-known scanner inputs. Every field uses only the trigger bar and earlier data."""
    change, prior_high = _f(row.get("sip_change_vs_ref")), _f(row.get("sip_prior_session_high"))
    return {
        "session": sig.session,
        "hour_et": sig.available_utc.astimezone(ET).hour,
        "price": sig.price,
        "change_pct": change * 100 if change is not None else None,
        "session_volume": _f(row.get("sip_session_volume")),
        "volume_ratio": _f(row.get("sip_volume_ratio")),
        "breakout_strength_bps": (sig.price / prior_high - 1) * 1e4 if prior_high else None,
    }


def build_ledgers(breakout_rows: Iterable[Mapping[str, str]], attempts: list[dict[str, str]],
                  trades: list[dict[str, str]], store: QuoteStore, sample: str, scenario: str,
                  strat: StrategyConfig = StrategyConfig()) -> tuple[list[dict[str, object]], list[dict[str, object]]]:
    cfg = SCENARIOS[scenario.split("_cap")[0]]
    rows = list(breakout_rows)
    by_key: dict[tuple[str, datetime], tuple[Signal, Mapping[str, str]]] = {}
    for sig, row in zip(signals_from_breakouts(rows, {sample}),
                        (r for r in rows if r.get("sip_bar_start_utc") and r.get("sip_candidate_gate") == "True"
                         and r["sample"] == sample)):
        by_key[(sig.symbol, sig.available_utc)] = (sig, row)
    trade_by_key = {(t["symbol"], datetime.fromisoformat(t["signal_available_utc"])): t for t in trades}
    signals_out: list[dict[str, object]] = []
    trades_out: list[dict[str, object]] = []
    for a in attempts:
        key = (a["symbol"], datetime.fromisoformat(a["signal_available_utc"]))
        sig, row = by_key[key]
        trade = trade_by_key.get(key) if a["outcome"] in ("filled", "partial") else None
        rec: dict[str, object] = {
            "symbol": sig.symbol, "trading_date": sig.trading_date.isoformat(), "sample": sample, "scenario": scenario,
            "signal_bar_start_utc": sig.bar_start_utc.isoformat(), "signal_available_utc": sig.available_utc.isoformat(),
            **signal_features(row, sig), "outcome": outcome(a, trade), "reason": a["reason"] or "filled",
            "latency_s": cfg.latency.total_seconds(),
            "signal_bid": None, "signal_ask": None, "signal_spread_bps": None, "signal_quote_age_s": None,
            "signal_quote_state": None, "quotes_cached": None,
        }
        (e0, e1), (h0, h1) = quote_stages(sig, strat)
        entry_q: list[Quote] | None = None
        if a["outcome"] != "skipped":  # skipped signals were never evaluated, so no quotes were fetched for them
            try:
                entry_q = store.get(sig, e0, e1)
                rec["quotes_cached"] = True
            except CacheMiss:
                rec["quotes_cached"] = False
        if entry_q is not None:
            q0 = prevailing(entry_q, sig.available_utc)
            if q0:
                rec.update(signal_bid=q0.bid, signal_ask=q0.ask, signal_quote_state=q0.state,
                           signal_quote_age_s=(sig.available_utc - q0.t).total_seconds(),
                           signal_spread_bps=q0.spread_bps if q0.state == EXECUTABLE else None)
        signals_out.append(rec)
        if trade is None:
            continue
        try:
            quotes = (entry_q or []) + store.get(sig, h0, h1)
            cached = entry_q is not None
        except CacheMiss:
            quotes, cached = entry_q or [], False
        trades_out.append(diagnose_trade(rec, trade, quotes, cached, h1, strat,
                                         [str(store.path(sig, e0, e1).name), str(store.path(sig, h0, h1).name)]))
    return signals_out, trades_out


def diagnose_trade(sig_rec: Mapping[str, object], t: Mapping[str, str], quotes: list[Quote], cached: bool,
                   data_end: datetime, strat: StrategyConfig, quote_files: list[str]) -> dict[str, object]:
    entry, qty, requested = float(t["entry_price"]), int(t["qty"]), int(t["requested_qty"])
    risk = entry * strat.stop_pct
    t_fill = datetime.fromisoformat(t["entry_first_fill_utc"])
    t_exit = datetime.fromisoformat(t["exit_trigger_utc"])
    # Corrected model (PR #4): exit_price is nan when nothing sold; net_usd and r_multiple are empty for
    # incomplete exits, whose unsold remainder is marked separately and never counted as realized.
    complete = t["exit_complete"] == "True"
    exit_px, net, r_mult, mark = (_f(t.get(k)) for k in ("exit_price", "net_usd", "r_multiple", "mark_price"))
    gross, fees, realized = (float(t[k]) for k in ("gross_usd", "fees_usd", "realized_net_usd"))
    ask0, bid0 = sig_rec.get("signal_ask"), sig_rec.get("signal_bid")
    qx = prevailing(quotes, t_exit, executable=True) if cached else None
    half_entry = (float(ask0) - float(bid0)) / 2 if ask0 and bid0 else None  # type: ignore[arg-type]
    half_exit = (qx.ask - qx.bid) / 2 if qx else None
    out: dict[str, object] = {
        **sig_rec,
        "requested_qty": requested, "filled_qty": qty, "fill": "partial" if qty < requested else "full",
        "entry_first_fill_utc": t["entry_first_fill_utc"], "exit_trigger_utc": t["exit_trigger_utc"],
        "exit_last_fill_utc": t["exit_last_fill_utc"], "exit_reason": t["exit_reason"],
        "exit_complete": complete,
        "exit_qty": int(t["exit_qty"]), "remaining_qty": int(t["remaining_qty"]),
        "seconds_to_fill": float(t["seconds_to_fill"]),
        "holding_seconds": (datetime.fromisoformat(t["exit_last_fill_utc"]) - t_fill).total_seconds(),
        "entry_price": entry, "exit_price": exit_px,
        "entry_slippage_bps": (entry / float(ask0) - 1) * 1e4 if ask0 else None,  # type: ignore[arg-type]
        "exit_trigger_bid": qx.bid if qx else None,
        "exit_slippage_bps": (exit_px / qx.bid - 1) * 1e4 if qx and exit_px is not None else None,
        # A round-trip spread cost exists only when the position was fully sold.
        "spread_cost_usd": (half_entry + half_exit) * qty if complete and half_entry is not None and half_exit is not None
        else None,
        "spread_cost_r": (half_entry + half_exit) / risk if complete and half_entry is not None and half_exit is not None
        else None,
        "gross_usd": gross, "fees_usd": fees,
        "net_usd": net if complete else None,
        "realized_usd": realized,  # sold shares only, for complete and incomplete exits alike
        "mark_price": None if complete else mark,
        "marked_usd": None if complete else _f(t.get("unrealized_usd")) if mark is not None else None,
        "r_multiple": r_mult if complete else None,
        "quote_files": ";".join(quote_files) if cached else "",
    }
    out.update(excursions(quotes if cached else [], entry, risk, t_fill, t_exit))
    out.update(forward_moves(quotes if cached else [], entry, risk, t_fill, data_end))
    mfe = out["mfe_r"]
    out["stopped_after_1r_favorable"] = (t["exit_reason"] == "stop" and mfe is not None and float(mfe) >= 1.0)  # type: ignore[arg-type]
    out["near_target_reversal"] = (t["exit_reason"] != "target" and mfe is not None
                                   and float(mfe) >= NEAR_TARGET_SHARE * strat.target_r)  # type: ignore[arg-type]
    out["fast_reversal"] = t["exit_reason"] == "stop" and out["holding_seconds"] <= FAST_REVERSAL_S  # type: ignore[operator]
    return out


# ---------- summaries ----------

BUCKETS: dict[str, tuple[list[float] | None, list[str] | None]] = {
    "session": (None, ["premarket", "afterhours"]),
    "hour_et": (None, [str(h) for h in range(4, 20)]),
    "price": ([1, 2, 5, 10, 20], None),
    "change_pct": ([5, 10, 20, 50, 100], None),
    "session_volume": ([1e5, 3e5, 1e6, 3e6, 1e7], None),
    "volume_ratio": ([2, 3, 5, 10, 20], None),
    "breakout_strength_bps": ([0, 25, 50, 100, 200, 500], None),
    "signal_spread_bps": ([0, 10, 20, 35, 50], None),
    "signal_quote_age_s": ([0, 0.5, 1, 2, 3], None),
    "seconds_to_fill": ([0, 0.5, 1, 2, 5], None),
    "fill": (None, ["full", "partial"]),
    "entry_slippage_bps": ([-1, 0, 1, 5, 10, 25], None),
}


def summarize(signals: list[dict[str, object]], trades: list[dict[str, object]], sample: str,
              scenario: str) -> dict[str, object]:
    def fq(key: str, rows: list[dict[str, object]] = trades) -> dict[str, float | None]:
        return _q([float(r[key]) for r in rows if r.get(key) is not None])  # type: ignore[arg-type]

    completed = [t for t in trades if t["r_multiple"] is not None]  # incomplete exits are reported, not scored
    stops = [t for t in completed if t["exit_reason"] == "stop"]
    by_outcome = Counter(str(s["outcome"]) for s in signals)
    reasons = Counter((str(s["outcome"]), str(s["reason"])) for s in signals if s["outcome"] in ("skipped", "rejected", "unfilled"))
    evaluated = [s for s in signals if s["outcome"] != "skipped"]
    return {
        "sample": sample, "scenario": scenario,
        "signals": len(signals), "trades": len(trades),
        "outcomes": dict(by_outcome),
        "reason_codes": [{"outcome": o, "reason": r, "n": n} for (o, r), n in reasons.most_common()],
        "quote_cache": {"evaluated_signals": len(evaluated),
                        "evaluated_with_cached_quotes": sum(1 for s in evaluated if s["quotes_cached"]),
                        "trades_with_cached_quotes": sum(1 for t in trades if t["quote_files"])},
        "entries": len(trades), "completed_trades": len(completed),
        "overall": stats([float(t["r_multiple"]) for t in completed]),  # type: ignore[arg-type]
        "pnl": {"realized_usd": sum(float(t["realized_usd"]) for t in trades if t["realized_usd"] is not None),  # type: ignore[arg-type]
                "marked_usd": sum(float(t["marked_usd"]) for t in trades if t["marked_usd"] is not None),  # type: ignore[arg-type]
                "gross_usd": sum(float(t["gross_usd"]) for t in trades),  # type: ignore[arg-type]
                "fees_usd": sum(float(t["fees_usd"]) for t in trades),  # type: ignore[arg-type]
                "spread_cost_usd": sum(float(t["spread_cost_usd"]) for t in trades if t["spread_cost_usd"] is not None)},  # type: ignore[arg-type]
        "execution": {k: fq(k) for k in ("seconds_to_fill", "entry_slippage_bps", "exit_slippage_bps", "spread_cost_r",
                                         "holding_seconds")} | {
            "signal_spread_bps_evaluated": fq("signal_spread_bps", evaluated),
            "signal_quote_age_s_evaluated": fq("signal_quote_age_s", evaluated),
            "partial_fills": sum(1 for t in trades if t["fill"] == "partial"),
            "incomplete_exits": sum(1 for t in trades if not t["exit_complete"]),
            "incomplete_exit_shares_unsold": sum(int(t["remaining_qty"]) for t in trades if not t["exit_complete"]),  # type: ignore[call-overload]
            "incomplete_exits_unmarked": sum(1 for t in trades if not t["exit_complete"] and t["marked_usd"] is None),
            "exit_reasons": dict(Counter(str(t["exit_reason"]) for t in trades)),
        },
        "lifecycle": {
            "mfe_r": fq("mfe_r"), "mae_r": fq("mae_r"),
            "seconds_to_mfe": fq("seconds_to_mfe"), "seconds_to_mae": fq("seconds_to_mae"),
            "favorable_first_share": _share(trades, "favorable_first"),
            "forward_moves_r": {f"{k}m": fq(f"move_{k}m_r") for k in FORWARD_MINUTES},
            "stops": len(stops),
            "stopped_after_1r_favorable": sum(1 for t in completed if t["stopped_after_1r_favorable"]),
            "near_target_reversals": sum(1 for t in completed if t["near_target_reversal"]),
            "fast_reversals_le_60s": sum(1 for t in completed if t["fast_reversal"]),
            "stops_mfe_r": fq("mfe_r", stops),
        },
        "breakdowns_entry_time": {k: breakdown(completed, k, *BUCKETS[k]) for k in ENTRY_FEATURES},
        "breakdowns_post_entry": {k: breakdown(completed, k, *BUCKETS[k]) for k in POST_ENTRY if k in BUCKETS},
        "min_bucket_n": MIN_BUCKET_N,
    }


def _share(rows: list[dict[str, object]], key: str) -> dict[str, object]:
    known = [r[key] for r in rows if r.get(key) is not None]
    return {"n": len(known), "share_true": sum(1 for v in known if v) / len(known) if known else None}


def failure_cases(trades: list[dict[str, object]], n: int = 20) -> dict[str, list[dict[str, object]]]:
    """Per-trade example lists (licensed-data derived: local only)."""
    ranked = sorted((t for t in trades if t["exit_complete"]), key=lambda t: float(t["r_multiple"]))  # type: ignore[arg-type]
    return {
        "worst": ranked[:n], "best": ranked[::-1][:n],
        "fast_reversals": [t for t in trades if t["fast_reversal"]],
        "stopped_after_1r_favorable": [t for t in trades if t["stopped_after_1r_favorable"]],
        "near_target_reversals": [t for t in trades if t["near_target_reversal"]],
    }


# ---------- outputs ----------

def write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", newline="", encoding="utf-8") as fh:
        if rows:
            w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(rows)


def _fmt(x: object, nd: int = 2) -> str:
    if x is None:
        return "—"
    if isinstance(x, bool):
        return "yes" if x else "no"
    if isinstance(x, float):
        return f"{x:.{nd}f}"
    return str(x)


def render_report(summary: Mapping[str, object]) -> str:
    """Aggregate-only Markdown (no symbols or per-trade prices); safe to commit."""
    s: dict = dict(summary)
    lines = [f"# Trade diagnostics: {s['sample']}, {s['scenario']} (generated)", "",
             f"Signals {s['signals']:,} · entries {s['trades']:,} · no orders placed. Buckets with fewer than "
             f"{s['min_bucket_n']} trades are marked *inconclusive*. Patterns here are hypotheses, not validated edges.", ""]
    pv = s.get("provenance")
    if pv:
        ds, br = pv["dataset"], pv["backtest_run"]
        lines += ["## Provenance", "",
                  f"- **Generated by code** `{s.get('code_sha', '?')}` at {s.get('created_at_utc', '?')}. This is the commit "
                  "that produced this file; later commits that do not rerun `m2-diagnostics` leave it unchanged, so it "
                  "can be older than the repository HEAD.",
                  f"- **Dataset** `{ds['path']}`: manifest sha256 `{ds['manifest_sha256'][:16]}…` (built "
                  f"{ds['manifest_created_at_utc']}), breakout_matches.csv sha256 `{ds['breakout_matches_sha256'][:16]}…`.",
                  f"- **Backtest run** `{br['summary_file']}` from code `{br['code_sha']}` at {br['created_at_utc']} "
                  f"(sha256 `{br['summary_sha256'][:16]}…`); trades.csv `{br['trades_sha256'][:16]}…` ({br['trades_rows']} "
                  f"rows), attempts.csv `{br['attempts_sha256'][:16]}…` ({br['attempts_rows']} rows). The ledgers were "
                  "checked to reproduce the summary's results exactly.",
                  f"- **Configuration** (as recorded by the backtest run): scenario `{json.dumps(pv['configuration']['scenario'])}`; "
                  f"strategy `{json.dumps(pv['configuration']['strategy'])}`.",
                  "- **Fields in the current code that the backtest run did not record:** "
                  + (", ".join(f"`{x}`" for x in pv["current_code_fields_not_recorded_by_backtest_run"]) or "none") + ".",
                  ""]
    o = s["overall"]
    lines += ["## Overall", "", "| n | win rate | avg R | median R | profit factor | 95% CI avg R |", "|---:|---:|---:|---:|---:|---|",
              f"| {o['n']} | {_fmt(o['win_rate'] and o['win_rate'] * 100, 1)}% | {_fmt(o['avg_r'], 3)} | {_fmt(o['median_r'], 3)} | "
              f"{_fmt(o['profit_factor'])} | {_ci(o['avg_r_ci95'])} |", ""]
    p = s["pnl"]
    ex = s["execution"]
    lines += [f"Entries {s['entries']}; completed trades {s['completed_trades']}; incomplete exits "
              f"{ex['incomplete_exits']} ({ex['incomplete_exit_shares_unsold']} shares unsold, "
              f"{ex['incomplete_exits_unmarked']} without a mark). R statistics, win rate, profit factor and the "
              "breakdowns use completed trades only.", ""]
    lines += [f"Realized P&L (shares sold) ${p['realized_usd']:,.2f}; marked unsold shares (incomplete exits, not realized) "
              f"${p['marked_usd']:,.2f}; "
              f"gross ${p['gross_usd']:,.2f}; fees ${p['fees_usd']:,.2f}; half-spread cost paid ${p['spread_cost_usd']:,.2f}.", ""]
    lines += ["## Signal outcomes and reason codes", "", "| outcome | reason | n |", "|---|---|---:|"]
    lines += [f"| {r['outcome']} | {r['reason']} | {r['n']} |" for r in s["reason_codes"]]
    lines += ["", "Outcome totals: " + ", ".join(f"{k} {v}" for k, v in sorted(s["outcomes"].items())) + ".", ""]
    qc = s["quote_cache"]
    lines += [f"Quote replay: {qc['evaluated_with_cached_quotes']} of {qc['evaluated_signals']} evaluated signals and "
              f"{qc['trades_with_cached_quotes']} of {s['trades']} trades had cached quotes; missing data is left empty.", ""]
    lines += ["## Execution", "", "| metric | p10 | median | p90 | mean |", "|---|---:|---:|---:|---:|"]
    for k, v in s["execution"].items():
        if isinstance(v, dict) and "median" in v:
            lines.append(f"| {k} | {_fmt(v['p10'])} | {_fmt(v['median'])} | {_fmt(v['p90'])} | {_fmt(v['mean'])} |")
    e = s["execution"]
    lines += ["", f"Partial fills {e['partial_fills']}; incomplete exits {e['incomplete_exits']}; exit reasons {e['exit_reasons']}.", ""]
    lc = s["lifecycle"]
    lines += ["## Trade lifecycle (post-entry diagnostics)", "", "| metric | p10 | median | p90 | mean |", "|---|---:|---:|---:|---:|"]
    for k in ("mfe_r", "mae_r", "seconds_to_mfe", "seconds_to_mae", "stops_mfe_r"):
        v = lc[k]
        lines.append(f"| {k} | {_fmt(v['p10'])} | {_fmt(v['median'])} | {_fmt(v['p90'])} | {_fmt(v['mean'])} |")
    for k, v in lc["forward_moves_r"].items():
        lines.append(f"| bid move after {k} (R) | {_fmt(v['p10'])} | {_fmt(v['median'])} | {_fmt(v['p90'])} | {_fmt(v['mean'])} |")
    ff = lc["favorable_first_share"]
    lines += ["", f"Reached +{FAVORABLE_R}R before -{FAVORABLE_R}R: {_fmt(ff['share_true'] and ff['share_true'] * 100, 1)}% of {ff['n']} trades "
              f"that reached either. Stops {lc['stops']}: {lc['stopped_after_1r_favorable']} had first been +1R or better, "
              f"{lc['fast_reversals_le_60s']} stopped within {FAST_REVERSAL_S:.0f} s; near-target reversals "
              f"(MFE >= {NEAR_TARGET_SHARE:.0%} of target, no target exit): {lc['near_target_reversals']}.", ""]
    for title, group in (("Breakdowns by entry-time-known features", "breakdowns_entry_time"),
                         ("Breakdowns by post-entry execution features (diagnostic only; not entry filters)", "breakdowns_post_entry")):
        lines += [f"## {title}", ""]
        for k, rows in s[group].items():
            lines += [f"### {k}", "", "| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |",
                      "|---|---:|---:|---:|---:|---:|---|---|"]
            lines += [f"| {r['bucket']} | {r['n']} | {_fmt(r['win_rate'] and r['win_rate'] * 100, 1)}% | {_fmt(r['avg_r'], 3)} | "
                      f"{_fmt(r['median_r'], 3)} | {_fmt(r['profit_factor'])} | {_ci(r['avg_r_ci95'])} | "
                      f"{'*inconclusive*' if r['inconclusive'] else ''} |" for r in rows]
            lines.append("")
    return "\n".join(lines) + "\n"


def _ci(c: object) -> str:
    return "—" if not c else f"[{c[0]:+.2f}, {c[1]:+.2f}]"  # type: ignore[index]


def render_cases(cases: Mapping[str, list[dict[str, object]]]) -> str:
    """Local-only example lists with replayable quote references (cache file names and timestamps)."""
    cols = ("symbol", "trading_date", "session", "signal_available_utc", "entry_first_fill_utc", "exit_trigger_utc",
            "exit_reason", "entry_price", "exit_price", "r_multiple", "mfe_r", "mae_r", "seconds_to_mfe", "quote_files")
    out = ["# Failure-case examples (local only: per-trade, licensed-data derived)", "",
           "Replay a case by reading the listed files in `cache/backtest_quotes/` (gzip JSON lines of SIP quotes).", ""]
    for name, rows in cases.items():
        out += [f"## {name} ({len(rows)})", "", "| " + " | ".join(cols) + " |", "|" + "---|" * len(cols)]
        out += ["| " + " | ".join(_fmt(r.get(c), 3) for c in cols) + " |" for r in rows[:50]]
        out.append("")
    return "\n".join(out)


DASHBOARD = """<!doctype html>
<html lang="en"><head><meta charset="utf-8"><meta name="viewport" content="width=device-width,initial-scale=1">
<title>Trade Diagnostics</title>
<style>
:root{--bg:#fff;--fg:#1d2433;--muted:#5d6678;--line:#d8dce4;--accent:#2f6fd0;--pos:#1f8a4c;--neg:#c23b3b;--card:#f6f7f9}
@media (prefers-color-scheme:dark){:root{--bg:#14171c;--fg:#e6e9ef;--muted:#9aa3b2;--line:#2c323b;--accent:#6ea2ff;--pos:#4cc27f;--neg:#ff6b6b;--card:#1c2027}}
body{background:var(--bg);color:var(--fg);font:14px/1.45 system-ui,sans-serif;margin:0;padding:16px;max-width:1200px;margin-inline:auto}
h1{font-size:20px;margin:0 0 4px}p{color:var(--muted);margin:0 0 12px}
.f{display:flex;flex-wrap:wrap;gap:8px;margin:12px 0}.f label{display:flex;flex-direction:column;font-size:12px;color:var(--muted)}
select{background:var(--card);color:var(--fg);border:1px solid var(--line);border-radius:6px;padding:4px 6px}
.k{display:grid;grid-template-columns:repeat(auto-fit,minmax(130px,1fr));gap:8px;margin:8px 0 16px}
.k div{background:var(--card);border-radius:8px;padding:8px}.k b{display:block;font-size:18px}
.g{display:grid;grid-template-columns:repeat(auto-fit,minmax(340px,1fr));gap:16px}.c{background:var(--card);border-radius:8px;padding:8px}
.c h2{font-size:14px;margin:0 0 6px}svg{width:100%;height:220px;display:block}
table{border-collapse:collapse;width:100%;font-size:12px}td,th{border-bottom:1px solid var(--line);padding:3px 6px;text-align:right}
td:first-child,th:first-child{text-align:left}.w{overflow-x:auto}
</style></head><body>
<h1>Trade diagnostics</h1><p id="sub"></p>
<div class="f">
<label>Session<select id="session"><option value="">all</option><option>premarket</option><option>afterhours</option></select></label>
<label>Exit reason<select id="exit"><option value="">all</option><option>stop</option><option>target</option><option>time</option><option>session_end</option></select></label>
<label>Hour (ET)<select id="hour"><option value="">all</option></select></label>
<label>Group bars by<select id="dim"></select></label>
</div>
<div class="k" id="kpi"></div>
<div class="g">
<div class="c"><h2>R multiple distribution</h2><svg id="hist"></svg></div>
<div class="c"><h2>Average R by <span id="dimname"></span> (n in label)</h2><svg id="bars"></svg></div>
<div class="c"><h2>MFE vs MAE (R)</h2><svg id="scatter"></svg></div>
<div class="c"><h2>Cumulative net P&amp;L (USD, trade order)</h2><svg id="equity"></svg></div>
<div class="c"><h2>Median bid move after entry (R)</h2><svg id="fwd"></svg></div>
<div class="c"><h2>Signal outcomes</h2><div class="w"><table id="outcomes"></table></div></div>
</div>
<script>
const D=__DATA__;
const css=n=>getComputedStyle(document.documentElement).getPropertyValue(n).trim();
const DIMS=["session","hour_et","price","change_pct","volume_ratio","breakout_strength_bps","signal_spread_bps","seconds_to_fill","fill"];
const EDGES={price:[1,2,5,10,20],change_pct:[5,10,20,50,100],volume_ratio:[2,3,5,10,20],breakout_strength_bps:[0,25,50,100,200,500],signal_spread_bps:[0,10,20,35,50],seconds_to_fill:[0,0.5,1,2,5]};
const $=id=>document.getElementById(id);
DIMS.forEach(d=>$("dim").add(new Option(d,d)));
for(let h=4;h<20;h++)$("hour").add(new Option(h,h));
$("sub").textContent=`${D.sample} · ${D.scenario} · ${D.trades.length} entries · ${D.signals.length} signals · simulation only, no orders. Small groups are noisy; patterns are hypotheses.`;
function bucket(v,e){if(v===null||v===undefined||v==="")return"unknown";if(!e)return String(v);if(v<e[0])return"<"+e[0];for(let i=0;i<e.length-1;i++)if(v<e[i+1])return e[i]+"–"+e[i+1];return">="+e[e.length-1]}
function filt(rows){const s=$("session").value,x=$("exit").value,h=$("hour").value;return rows.filter(r=>(!s||r.session===s)&&(!x||r.exit_reason===x)&&(!h||String(r.hour_et)===h))}
function svg(el,w,h){el.setAttribute("viewBox",`0 0 ${w} ${h}`);el.innerHTML="";return el}
function add(el,tag,a,txt){const n=document.createElementNS("http://www.w3.org/2000/svg",tag);for(const k in a)n.setAttribute(k,a[k]);if(txt!==undefined)n.textContent=txt;el.appendChild(n);return n}
function axis(el,x0,x1,y,lab){add(el,"line",{x1:x0,x2:x1,y1:y,y2:y,stroke:css("--line")});if(lab)add(el,"text",{x:x0,y:y+14,fill:css("--muted"),"font-size":10},lab)}
const med=a=>{const v=a.filter(x=>x!==null).sort((p,q)=>p-q);return v.length?v[Math.floor((v.length-1)/2)]:null};
const mean=a=>a.length?a.reduce((p,q)=>p+q,0)/a.length:null;
function draw(){
 const A=filt(D.trades),T=A.filter(t=>t.r_multiple!==null),I=A.filter(t=>t.r_multiple===null),R=T.map(t=>t.r_multiple),W=R.filter(r=>r>0),L=R.filter(r=>r<=0);
 const pf=L.length&&L.reduce((a,b)=>a+b,0)<0?W.reduce((a,b)=>a+b,0)/-L.reduce((a,b)=>a+b,0):null;
 const k=[["entries",A.length],["completed",T.length],["incomplete exits",I.length+(I.length?` (marked ${I.reduce((a,t)=>a+(t.marked_usd||0),0).toFixed(2)}${I.some(t=>t.marked_usd===null)?", some unmarked":""})`:"")],["win rate",R.length?(100*W.length/R.length).toFixed(1)+"%":"—"],["avg R",R.length?mean(R).toFixed(3):"—"],["median R",R.length?med(R).toFixed(3):"—"],["profit factor",pf?pf.toFixed(2):"—"],["net USD (completed)",T.reduce((a,t)=>a+t.net_usd,0).toFixed(2)],["small sample",T.length<30?"yes":"no"]];
 $("kpi").innerHTML=k.map(([a,b])=>`<div>${a}<b>${b}</b></div>`).join("");
 // histogram
 let el=svg($("hist"),360,220);const bins=[];for(let b=-1.5;b<2.5;b+=0.25)bins.push([b,0]);R.forEach(r=>{let i=Math.min(bins.length-1,Math.max(0,Math.floor((r+1.5)/0.25)));bins[i][1]++});
 const mx=Math.max(1,...bins.map(b=>b[1]));bins.forEach((b,i)=>{const h=180*b[1]/mx;add(el,"rect",{x:20+i*20,y:190-h,width:18,height:h,fill:b[0]<0?css("--neg"):css("--pos")})});axis(el,20,340,190,"-1.5R … +2.5R (0.25R bins)");
 // bars
 const dim=$("dim").value;$("dimname").textContent=dim;const g={};T.forEach(t=>{const b=bucket(t[dim],EDGES[dim]);(g[b]=g[b]||[]).push(t.r_multiple)});
 const keys=Object.keys(g).sort((a,b)=>parseFloat(a.replace(/[<>=]/g,""))-parseFloat(b.replace(/[<>=]/g,""))||a.localeCompare(b));
 el=svg($("bars"),360,220);const vals=keys.map(k=>mean(g[k])),am=Math.max(0.1,...vals.map(Math.abs));const bw=Math.min(40,320/Math.max(1,keys.length));
 keys.forEach((kk,i)=>{const v=vals[i],h=80*Math.abs(v)/am,x=30+i*bw;add(el,"rect",{x,y:v>=0?100-h:100,width:bw-4,height:h,fill:v>=0?css("--pos"):css("--neg"),opacity:g[kk].length<30?0.45:1});add(el,"text",{x:x+bw/2,y:186,fill:css("--muted"),"font-size":9,"text-anchor":"end",transform:`rotate(-35 ${x+bw/2} 186)`},`${kk} (${g[kk].length})`)});axis(el,25,350,100);
 // scatter
 el=svg($("scatter"),360,220);const sx=v=>30+(v+1.5)/4*320,sy=v=>200-(v+1.5)/4*190;axis(el,30,350,sy(0),"MAE (x) vs MFE (y), clipped to -1.5…2.5R");
 T.forEach(t=>{if(t.mfe_r===null||t.mae_r===null)return;add(el,"circle",{cx:sx(Math.max(-1.5,Math.min(2.5,t.mae_r))),cy:sy(Math.max(-1.5,Math.min(2.5,t.mfe_r))),r:2.5,fill:t.r_multiple>0?css("--pos"):css("--neg"),opacity:0.7})});
 // equity
 el=svg($("equity"),360,220);let c=0;const eq=T.map(t=>c+=t.net_usd);const lo=Math.min(0,...eq),hi=Math.max(0,...eq),sc=v=>200-(v-lo)/((hi-lo)||1)*180;
 add(el,"polyline",{points:eq.map((v,i)=>`${20+i*330/Math.max(1,eq.length-1)},${sc(v)}`).join(" "),fill:"none",stroke:css("--accent"),"stroke-width":1.5});axis(el,20,350,sc(0),`range ${lo.toFixed(0)} … ${hi.toFixed(0)} USD`);
 // forward moves
 el=svg($("fwd"),360,220);const ks=[1,3,5,10,15],m=ks.map(k=>med(T.map(t=>t["move_"+k+"m_r"]))),fm=Math.max(0.1,...m.map(v=>Math.abs(v||0)));
 ks.forEach((k,i)=>{const v=m[i]||0,h=80*Math.abs(v)/fm,x=40+i*60;add(el,"rect",{x,y:v>=0?100-h:100,width:40,height:h,fill:v>=0?css("--pos"):css("--neg")});add(el,"text",{x,y:212,fill:css("--muted"),"font-size":10},`${k}m: ${m[i]===null?"—":m[i].toFixed(2)}`)});axis(el,30,350,100);
 // outcomes
 const S=D.signals.filter(r=>(!$("session").value||r.session===$("session").value)&&(!$("hour").value||String(r.hour_et)===$("hour").value));const oc={};S.forEach(s=>{const kk=s.outcome+" · "+s.reason;oc[kk]=(oc[kk]||0)+1});
 $("outcomes").innerHTML="<tr><th>outcome · reason</th><th>n</th></tr>"+Object.entries(oc).sort((a,b)=>b[1]-a[1]).map(([a,b])=>`<tr><td>${a}</td><td>${b}</td></tr>`).join("");
}
["session","exit","hour","dim"].forEach(id=>$(id).addEventListener("change",draw));draw();
</script></body></html>
"""


def write_dashboard(path: Path, signals: list[dict[str, object]], trades: list[dict[str, object]], sample: str,
                    scenario: str) -> None:
    """Standalone HTML (no external requests). Embeds per-trade rows: local only, never commit or publish."""
    keep_s = ("session", "hour_et", "outcome", "reason")
    keep_t = ("session", "hour_et", "price", "change_pct", "volume_ratio", "breakout_strength_bps", "signal_spread_bps",
              "seconds_to_fill", "fill", "exit_reason", "r_multiple", "net_usd", "marked_usd", "mfe_r", "mae_r",
              *(f"move_{k}m_r" for k in FORWARD_MINUTES))
    data = {"sample": sample, "scenario": scenario,
            "signals": [{k: s.get(k) for k in keep_s} for s in signals],
            "trades": [{k: t.get(k) for k in keep_t} for t in trades]}
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(DASHBOARD.replace("__DATA__", json.dumps(data, default=str).replace("</", "<\\/")), encoding="utf-8")


def load_csv(path: Path) -> list[dict[str, str]]:
    with path.open(newline="", encoding="utf-8") as fh:
        return list(csv.DictReader(fh))


def run(dataset: Path, sample: str, scenario: str) -> dict[str, object]:
    """Build ledgers, summary and local outputs for one sample and scenario. Cache-only; no network."""
    bt = dataset / "backtest" / sample / scenario
    store = QuoteStore(CacheOnlySource(), dataset / "cache" / "backtest_quotes")  # type: ignore[arg-type]
    signals, trades = build_ledgers(load_csv(dataset / "breakout_matches.csv"), load_csv(bt / "attempts.csv"),
                                    load_csv(bt / "trades.csv"), store, sample, scenario)
    out = dataset / "diagnostics" / sample / scenario  # per-signal/per-trade outputs: local, git-ignored
    write_csv(out / "signal_ledger.csv", signals)
    write_csv(out / "trade_ledger.csv", trades)
    (out / "failure_cases.md").write_text(render_cases(failure_cases(trades)), encoding="utf-8")
    write_dashboard(out / "dashboard.html", signals, trades, sample, scenario)
    return summarize(signals, trades, sample, scenario)


# ---------- input validation and provenance ----------

class InputMismatch(ValueError):
    """The dataset, backtest summary and ledgers do not belong together; diagnostics refuse to run."""


def sha256_of(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _typed(cls: type, row: Mapping[str, str]) -> object:
    """A Trade or Attempt from its CSV row, using the dataclass field types."""
    conv: dict[str, Callable[[str], object]] = {"str": str, "int": int, "float": float, "bool": lambda v: v == "True",
                                                "float | None": lambda v: None if v == "" else float(v)}
    return cls(**{f.name: conv[str(f.type)](row[f.name]) for f in fields(cls)})


def _scenario_config(name: str) -> ExecConfig:
    base, _, cap = name.partition("_cap")
    return with_spread_caps([SCENARIOS[base]], [float(cap)])[0] if cap else SCENARIOS[name]


def validate_inputs(dataset: Path, sample: str, scenario: str, strat: StrategyConfig = StrategyConfig(),
                    risk: RiskConfig = RiskConfig()) -> dict[str, object]:
    """Check that the ledgers are the run the backtest summary describes, on this dataset, with the current
    execution model and configuration. Returns the provenance record; raises InputMismatch otherwise.

    Cached quotes are not checked: they stay optional, and a missing file leaves diagnostic fields empty."""
    bt = dataset / "backtest" / sample / scenario
    paths = {"manifest": dataset / "manifest.json", "breakout_matches": dataset / "breakout_matches.csv",
             "backtest_summary": dataset / f"backtest_summary_{sample}.json",
             "trades": bt / "trades.csv", "attempts": bt / "attempts.csv"}
    missing = [f"{k} ({v})" for k, v in paths.items() if not v.is_file()]
    if missing:
        raise InputMismatch("missing required inputs: " + ", ".join(missing) + "; run m1-dataset and m2-backtest first")
    summary = json.loads(paths["backtest_summary"].read_text(encoding="utf-8"))
    manifest = json.loads(paths["manifest"].read_text(encoding="utf-8"))
    problems: list[str] = []
    if summary.get("sample") != sample:
        problems.append(f"backtest summary is for sample {summary.get('sample')!r}, not {sample!r}")
    if scenario not in summary.get("results", {}):
        problems.append(f"backtest summary has no scenario {scenario!r}; the ledgers are from a different m2-backtest run")
    trades, attempts = load_csv(paths["trades"]), load_csv(paths["attempts"])
    for name, cls in (("trades", Trade), ("attempts", Attempt)):
        with paths[name].open(newline="", encoding="utf-8") as fh:
            header = next(csv.reader(fh), [])
        want = [f.name for f in fields(cls)]
        if header != want:
            problems.append(f"{name}.csv columns do not match the current execution model (missing "
                            f"{sorted(set(want) - set(header))}, unexpected {sorted(set(header) - set(want))}); "
                            "rerun m2-backtest")
    labels = {(r.get("sample"), r.get("scenario")) for r in (*trades, *attempts)} - {(sample, scenario)}
    if labels:
        problems.append(f"ledgers contain rows from other runs: {sorted(map(str, labels))}")
    filled = {(a["symbol"], a["signal_available_utc"]) for a in attempts if a.get("outcome") in ("filled", "partial")}
    traded = [(t["symbol"], t["signal_available_utc"]) for t in trades]
    if set(traded) != filled or len(traded) != len(filled):
        problems.append(f"trades.csv ({len(traded)} rows) and attempts.csv ({len(filled)} filled) do not pair one to one")
    signals = {(s.symbol, s.available_utc.isoformat())
               for s in signals_from_breakouts(load_csv(paths["breakout_matches"]), {sample})}
    tried = {(a["symbol"], a["signal_available_utc"]) for a in attempts}
    if len(signals) != summary.get("signals") or tried != signals:
        problems.append(f"dataset has {len(signals)} {sample} signals but the backtest run recorded "
                        f"{summary.get('signals')} ({len(attempts)} attempts); the dataset changed since the backtest")
    recorded = summary.get("config", {})
    current = config_record(strat, risk, [_scenario_config(scenario)])
    not_recorded: list[str] = []
    for part, rec, cur in (("strategy", recorded.get("strategy", {}), current["strategy"]),
                           ("risk", recorded.get("risk", {}), current["risk"]),
                           ("fees", recorded.get("fees", {}), current["fees"]),
                           ("scenario", recorded.get("scenarios", {}).get(scenario, {}),
                            current["scenarios"][scenario])):  # type: ignore[index]
        for k in sorted(set(rec) | set(cur)):  # type: ignore[arg-type]
            if k not in rec:
                not_recorded.append(f"{part}.{k}")
            elif rec[k] != cur.get(k):  # type: ignore[union-attr]
                problems.append(f"{part}.{k}: backtest run used {rec[k]!r}, current code has {cur.get(k)!r}")  # type: ignore[union-attr]
    if not problems:
        result = BacktestResult(scenario, [_typed(Trade, r) for r in trades],  # type: ignore[misc]
                                [_typed(Attempt, r) for r in attempts])  # type: ignore[misc]
        if json.loads(json.dumps(summarize_backtest(result), default=str)) != summary["results"][scenario]:
            problems.append(f"trades.csv and attempts.csv do not reproduce the {paths['backtest_summary'].name} results "
                            f"for {scenario}; they come from a different or edited backtest run")
    if problems:
        raise InputMismatch("diagnostics inputs are inconsistent:\n- " + "\n- ".join(problems))
    return {
        "dataset": {"path": dataset.as_posix(), "manifest_sha256": sha256_of(paths["manifest"]),
                    "manifest_created_at_utc": manifest.get("created_at_utc"),
                    "manifest_code_sha": manifest.get("code_sha"),
                    "breakout_matches_sha256": sha256_of(paths["breakout_matches"]),
                    "input_sha256": {k: v for k, v in manifest.get("inputs", {}).items() if k.endswith("sha256")}},
        "backtest_run": {"summary_file": paths["backtest_summary"].name,
                         "summary_sha256": sha256_of(paths["backtest_summary"]),
                         "code_sha": summary.get("code_sha"), "created_at_utc": summary.get("created_at_utc"),
                         "trades_sha256": sha256_of(paths["trades"]), "attempts_sha256": sha256_of(paths["attempts"]),
                         "trades_rows": len(trades), "attempts_rows": len(attempts),
                         "ledgers_reproduce_summary": True},
        "configuration": {"strategy": recorded.get("strategy"), "risk": recorded.get("risk"),
                          "fees": recorded.get("fees"), "scenario": recorded.get("scenarios", {}).get(scenario)},
        "current_code_fields_not_recorded_by_backtest_run": not_recorded,
    }
