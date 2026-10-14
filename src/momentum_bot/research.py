"""M2 research: point-in-time Top 5 gainers within the cached universe, and two strategy variants.

Exploratory hypotheses, evaluated on in-sample days only. The baseline breakout strategy, its risk
settings, execution model and frozen 50 bps configuration are reused unchanged; the variants only
change which completed-bar signals reach the existing backtester.

Point-in-time rules:
- The ranking snapshot of the bar starting at t uses only bars that started at or before t. It is
  known at t + 1 minute, the same moment a signal on that bar becomes available.
- A symbol's price is its last completed-bar close. Its change is measured against the reference
  close the dataset already used (previous official close for premarket, same day's official
  close after hours, split-adjusted on ex-dates).
- Freshness: missing SIP bars are never filled. A minute without a bar means no trades were
  reported, so the symbol keeps its last close only while that close is at most
  ``max_staleness_minutes`` old; after that it is dropped from the ranking (``stale``) until it
  trades again. Every snapshot row records the age of its price, and every session counts the
  exclusions. The limit is a fixed policy chosen before any result was looked at, not a tuned value.
- The Bull Flag detector (bullflag.py) evaluated at bar i reads bars[: i + 1] only.

Coverage limit: the dataset fetched bars only for symbols whose reference close was low enough to
reach the scanner's price band (about $18.2 premarket, $19.0 after hours). The ranking is therefore
the Top 5 of that sub-$20 universe, not the market-wide top-gainers list.
"""

from __future__ import annotations

import csv
import gzip
import json
from collections import Counter, defaultdict
from collections.abc import Callable, Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime
from pathlib import Path
from statistics import fmean

from .backtest import (
    SCENARIOS, BacktestResult, QuoteStore, RiskConfig, StrategyConfig, run_backtest, signals_from_breakouts, summarize,
    with_spread_caps, write_rows,
)
from .compare import ScanParams
from .data.market_calendar import AFTERHOURS, EXTENDED_SESSIONS, PREMARKET, SessionWindow, session_windows
from .data.normalize import BAR_LENGTH, normalize
from .data.provider import Bar
from .bullflag import FlagParams, detect_flags, flag_params_record, session_volumes
from .dataset import _read_bars
from .split import IN_SAMPLE

STRATEGIES = ("hos", "top5_hos", "top5_bullflag")
# "Top 5" is ranked within the dataset's cached sub-$20 universe, never the market-wide gainers list.
STRATEGY_LABELS = {"hos": "Original HOS Breakout", "top5_hos": "Top 5 (cached universe) HOS Breakout",
                   "top5_bullflag": "Top 5 (cached universe) + Bull Flag Breakout"}
SCENARIO = "base_cap50"  # the frozen configuration from reports/m2_backtest.md
UNIVERSE = "cached_eligible_sub20"  # recorded on every ranking row: never the market-wide top-gainers list


# ---------- point-in-time Top 5 ----------

@dataclass(frozen=True, slots=True)
class RankParams:
    size: int = 5
    min_price: float = 1.0  # the scanner's price band and volume floor define who may be ranked
    max_price: float = 20.0
    min_session_volume: int = 100_000
    exclude_closing_auction_bar: bool = True
    max_staleness_minutes: int = 5  # a price older than this is stale and never ranked

    @classmethod
    def from_scan(cls, p: ScanParams, size: int = 5) -> RankParams:
        return cls(size, p.min_price, p.max_price, p.min_session_volume, p.exclude_closing_auction_bar)

    def is_fresh(self, last_bar: datetime, t: datetime) -> bool:
        return (t - last_bar) / BAR_LENGTH <= self.max_staleness_minutes


@dataclass(slots=True)
class Ranking:
    snapshots: list[dict[str, object]]  # one row per (bar, rank)
    changes: list[dict[str, object]]  # enter / exit / rank_change events
    coverage: dict[str, object]


def _iso(t: datetime) -> str:
    return t.isoformat()


def rank_session(window: SessionWindow, bars_by_symbol: Mapping[str, list[Bar]], refs: Mapping[str, float],
                 params: RankParams = RankParams()) -> Ranking:
    """Rank the eligible universe after every 1-minute bar of the session, using only completed bars."""
    by_t: dict[datetime, list[Bar]] = defaultdict(list)
    for sym, rows in bars_by_symbol.items():
        if refs.get(sym, 0) > 0:
            for b in rows:
                if window.contains(b.timestamp_utc):
                    by_t[b.timestamp_utc].append(b)
    skip_auction = params.exclude_closing_auction_bar and window.name == AFTERHOURS
    last: dict[str, tuple[float, datetime]] = {}
    vol: Counter[str] = Counter()
    volume_ok: set[str] = set()  # session volume only grows, so membership here is permanent
    snaps: list[dict[str, object]] = []
    changes: list[dict[str, object]] = []
    prev: dict[str, int] = {}
    members: set[str] = set()
    no_bar = short = stale_total = 0
    t = window.start_utc
    base = {"trading_date": window.trading_date.isoformat(), "session": window.name}
    while t < window.end_utc:
        rows = by_t.get(t, [])
        no_bar += not rows
        for b in rows:
            last[b.symbol] = (b.close, t)
            if not (skip_auction and t == window.start_utc):
                vol[b.symbol] += b.volume
            if vol[b.symbol] >= params.min_session_volume:
                volume_ok.add(b.symbol)
        fresh = {s for s in volume_ok if params.is_fresh(last[s][1], t)}
        stale_total += len(volume_ok) - len(fresh)
        ranked = sorted(((last[s][0] / refs[s] - 1, s) for s in fresh
                         if params.min_price <= last[s][0] <= params.max_price), key=lambda x: (-x[0], x[1]))
        top = ranked[: params.size]
        short += len(top) < params.size
        at = {"bar_start_utc": _iso(t), "available_utc": _iso(t + BAR_LENGTH)}
        cur = {s: i + 1 for i, (_, s) in enumerate(top)}
        for i, (chg, s) in enumerate(top):
            snaps.append({**base, **at, "rank": i + 1, "symbol": s, "change_pct": chg * 100, "price": last[s][0],
                          "session_volume": vol[s], "minutes_since_trade": int((t - last[s][1]) / BAR_LENGTH),
                          "ranked_symbols": len(ranked), "stale_excluded": len(volume_ok) - len(fresh),
                          "universe": UNIVERSE})
        change_of = {s: c * 100 for c, s in top}
        for s in sorted(cur.keys() - prev.keys()):
            changes.append({**base, **at, "symbol": s, "event": "enter", "rank": cur[s], "prev_rank": None,
                            "change_pct": change_of[s]})
        for s in sorted(prev.keys() - cur.keys()):
            price = last[s][0]
            why = ("stale" if s not in fresh else
                   "left_price_band" if not params.min_price <= price <= params.max_price else "displaced")
            changes.append({**base, **at, "symbol": s, "event": "exit", "rank": None, "prev_rank": prev[s],
                            "change_pct": (price / refs[s] - 1) * 100, "reason": why})
        for s in sorted(cur.keys() & prev.keys()):
            if cur[s] != prev[s]:
                changes.append({**base, **at, "symbol": s, "event": "rank_change", "rank": cur[s],
                                "prev_rank": prev[s], "change_pct": change_of[s]})
        members |= cur.keys()
        prev = cur
        t += BAR_LENGTH
    coverage = {**base, "minutes": window.minutes, "eligible_symbols": sum(1 for v in refs.values() if v > 0),
                "symbols_with_bars": len(last), "minutes_without_any_bar": no_bar,
                f"minutes_with_fewer_than_{params.size}_ranked": short, "distinct_top_members": len(members),
                "stale_exclusion_symbol_minutes": stale_total, "max_staleness_minutes": params.max_staleness_minutes,
                "universe": UNIVERSE, "bars_file": "found"}
    return Ranking(snaps, changes, coverage)


def rank_lookup(snapshots: Iterable[Mapping[str, object]]) -> dict[tuple[str, str], int]:
    """(symbol, bar_start_utc) -> rank, for the snapshot taken when that bar completed."""
    return {(str(r["symbol"]), str(r["bar_start_utc"])): int(r["rank"]) for r in snapshots}  # type: ignore[call-overload]


def bar_context(bars: list[Bar], ref: float, window: SessionWindow, scan: ScanParams) -> dict[str, dict[str, object]]:
    """Scanner state at each bar (keyed by bar start), from that bar and earlier ones only."""
    vols = session_volumes(bars, window, scan.exclude_closing_auction_bar)
    min_change = scan.premarket_min_change if window.name == PREMARKET else scan.afterhours_min_change
    out: dict[str, dict[str, object]] = {}
    cum, high = 0, float("-inf")
    for i, b in enumerate(bars):
        cum += vols[i]
        change = b.close / ref - 1
        prior = vols[max(0, i - scan.breakout_lookback) : i]
        out[_iso(b.timestamp_utc)] = {
            "change_vs_ref": change, "session_volume": cum,
            "volume_ratio": vols[i] / fmean(prior) if len(prior) == scan.breakout_lookback and fmean(prior) > 0 else None,
            "prior_session_high": high if i else None,
            "candidate_gate": scan.min_price <= b.close <= scan.max_price and change >= min_change
            and cum >= scan.min_session_volume,
        }
        high = max(high, b.high)
    return out


# ---------- local data access ----------

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


def load_references(dataset: Path) -> dict[tuple[str, str], dict[str, float]]:
    out: dict[tuple[str, str], dict[str, float]] = defaultdict(dict)
    with gzip.open(dataset / "references.csv.gz", "rt", newline="", encoding="utf-8") as fh:
        for r in csv.DictReader(fh):
            out[(r["trading_date"], r["session"])][r["symbol"]] = float(r["reference_close"])
    return dict(out)


def read_table(path: Path) -> list[dict[str, str]]:
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "rt", newline="", encoding="utf-8") as fh:  # type: ignore[operator]
        return list(csv.DictReader(fh))


def write_table(path: Path, rows: list[dict[str, object]]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    fields: dict[str, None] = {}
    for r in rows:
        fields.update(dict.fromkeys(r))
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", newline="", encoding="utf-8") as fh:  # type: ignore[operator]
        w = csv.DictWriter(fh, fieldnames=list(fields), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


# ---------- signal sets ----------

def _signal_row(sym: str, d: str, session: str, sample: str, bar_start: str, available: str, price: float,
                ctx: Mapping[str, object], **extra: object) -> dict[str, object]:
    """A row in the breakout_matches.csv schema, so the existing backtester and diagnostics read it as is."""
    return {"kind": "breakout", "symbol": sym, "trading_date": d, "session": session, "match": "sip_only",
            "sip_bar_start_utc": bar_start, "sip_signal_available_utc": available, "sip_price": price,
            "sip_change_vs_ref": ctx["change_vs_ref"], "sip_session_volume": ctx["session_volume"],
            "sip_volume_ratio": ctx["volume_ratio"], "sip_prior_session_high": ctx["prior_session_high"],
            "sip_candidate_gate": ctx["candidate_gate"], "sample": sample, **extra}


@dataclass(slots=True)
class SessionResearch:
    ranking: Ranking
    flags: list[dict[str, object]]
    signals: dict[str, list[dict[str, object]]]  # strategy -> signal rows
    filtered: list[dict[str, object]]  # signals a variant did not pass to the backtester, with the reason


def research_session(window: SessionWindow, bars: Mapping[str, list[Bar]], refs: Mapping[str, float],
                     hos_rows: list[Mapping[str, str]], sample: str, scan: ScanParams,
                     flag_params: FlagParams = FlagParams()) -> SessionResearch:
    d, session = window.trading_date.isoformat(), window.name
    ranking = rank_session(window, bars, refs, RankParams.from_scan(scan))
    rank = rank_lookup(ranking.snapshots)
    members = sorted({str(r["symbol"]) for r in ranking.snapshots})
    signals: dict[str, list[dict[str, object]]] = {k: [] for k in STRATEGIES}
    filtered: list[dict[str, object]] = []
    for r in hos_rows:  # the baseline's candidate-gated session-high breakouts, unchanged
        signals["hos"].append(dict(r))
        k = rank.get((r["symbol"], r["sip_bar_start_utc"]))
        if k is None:
            filtered.append({"strategy": "top5_hos", "trigger": "hos_breakout", "symbol": r["symbol"],
                             "trading_date": d, "session": session, "signal_bar_start_utc": r["sip_bar_start_utc"],
                             "signal_available_utc": r["sip_signal_available_utc"], "top5_rank": None,
                             "outcome": "filtered", "reason": "not_in_top5"})
        else:
            signals["top5_hos"].append({**r, "top5_rank": k})
    flags: list[dict[str, object]] = []
    for sym in members:
        rows = bars.get(sym, [])
        ctx = bar_context(rows, refs[sym], window, scan)
        for f in detect_flags(rows, window, flag_params):
            t = str(f["breakout_bar_start_utc"])
            k = rank.get((sym, t))
            c = ctx[t]
            rec = {"symbol": sym, "trading_date": d, "session": session, "sample": sample, **f, "top5_rank": k,
                   "candidate_gate": c["candidate_gate"], "change_pct": float(c["change_vs_ref"]) * 100}  # type: ignore[arg-type]
            flags.append(rec)
            why = (str(f["reason"]) if not f["qualified"] else "not_in_top5" if k is None
                   else "candidate_gate_failed" if not c["candidate_gate"] else None)
            if why is None:
                signals["top5_bullflag"].append(_signal_row(sym, d, session, sample, t, str(f["available_utc"]),
                                                            float(f["breakout_price"]), c, top5_rank=k))  # type: ignore[arg-type]
            elif f["qualified"] or k is not None:  # flag attempts of a current Top 5 member, or qualified flags
                filtered.append({"strategy": "top5_bullflag", "trigger": "bull_flag", "symbol": sym, "trading_date": d,
                                 "session": session, "signal_bar_start_utc": t,
                                 "signal_available_utc": f["available_utc"], "top5_rank": k,
                                 "outcome": "filtered", "reason": why})
    return SessionResearch(ranking, flags, signals, filtered)


# ---------- pipeline ----------

def sample_days(manifest: Mapping[str, object], sample: str) -> list[str]:
    blk = manifest["chronological_split"][sample]  # type: ignore[index]
    return [d for d in manifest["trading_days"] if blk["first"] <= d <= blk["last"]]  # type: ignore[union-attr, index]


def build(dataset: Path, sample: str = IN_SAMPLE, log: Callable[[str], None] = print) -> dict[str, object]:
    """Rankings, flags and signal sets for every session of the sample, from local data only."""
    if sample != IN_SAMPLE:
        raise ValueError("the Top 5 and Bull Flag variants are exploratory: in-sample only; "
                         "validate on fresh trading days after the dataset end, never on the inspected hold-out")
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    as_of = datetime.fromisoformat(manifest["as_of_utc"])
    scan = ScanParams(**manifest["scan_params"])
    refs = load_references(dataset)
    hos: dict[tuple[str, str], list[dict[str, str]]] = defaultdict(list)
    for r in read_table(dataset / "breakout_matches.csv"):
        if r.get("sip_bar_start_utc") and r.get("sip_candidate_gate") == "True" and r["sample"] == sample:
            hos[(r["trading_date"], r["session"])].append(r)
    out = dataset / "research" / sample  # symbol-level, licensed-data derived: local and git-ignored
    tables: dict[str, list[dict[str, object]]] = defaultdict(list)
    signals: dict[str, list[dict[str, object]]] = {k: [] for k in STRATEGIES}
    for d in sample_days(manifest, sample):
        windows = session_windows(date.fromisoformat(d))
        for session in EXTENDED_SESSIONS:
            bars = load_session_bars(dataset, d, session, as_of)
            if bars is None:  # never invent a ranking: the session is excluded from every strategy
                tables["coverage"].append({"trading_date": d, "session": session, "bars_file": "missing"})
                log(f"{d} {session}: no cached bars, excluded")
                continue
            res = research_session(windows[session], bars, refs.get((d, session), {}), hos[(d, session)], sample, scan)
            tables["top5_snapshots"] += res.ranking.snapshots
            tables["top5_changes"] += res.ranking.changes
            tables["coverage"].append(res.ranking.coverage)
            tables["bullflag_candidates"] += res.flags
            tables["filtered"] += res.filtered
            for k in STRATEGIES:
                signals[k] += res.signals[k]
        log(f"{d}: " + ", ".join(f"{k} {len(v)}" for k, v in signals.items()))
    for name in ("top5_snapshots", "top5_changes", "bullflag_candidates", "filtered"):
        write_table(out / f"{name}.csv.gz", tables[name])
    write_table(out / "top5_coverage.csv", tables["coverage"])
    for k in STRATEGIES:
        write_table(out / f"signals_{k}.csv", signals[k])
    return {"sessions": len(tables["coverage"]),
            "sessions_missing_bars": sum(1 for r in tables["coverage"] if r["bars_file"] == "missing"),
            "signals": {k: len(v) for k, v in signals.items()}}


def variant_provenance(dataset: Path, sample: str, strategy: str) -> dict[str, object]:
    """Where a variant's diagnostics come from. Variants have no backtest_summary file: their ledgers are written
    by the same m2-research run, right after the baseline rerun reproduced the PR #4 ledgers byte for byte."""
    from .backtest import RiskConfig, config_record
    from .diagnostics import sha256_of

    bt = backtest_paths(dataset, sample, strategy)
    (cfg,) = with_spread_caps([SCENARIOS["base"]], [50])
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    return {"dataset": {"path": dataset.as_posix(), "manifest_sha256": sha256_of(dataset / "manifest.json"),
                        "manifest_created_at_utc": manifest.get("created_at_utc"),
                        "breakout_matches_sha256": sha256_of(dataset / "breakout_matches.csv"),
                        "references_sha256": sha256_of(dataset / "references.csv.gz")},
            "backtest_run": {"source": "m2-research, same invocation", "baseline_reproduced_pr4_ledgers": True,
                             "signals_sha256": sha256_of(dataset / "research" / sample / f"signals_{strategy}.csv"),
                             "trades_sha256": sha256_of(bt / "trades.csv"), "attempts_sha256": sha256_of(bt / "attempts.csv")},
            "configuration": config_record(StrategyConfig(), RiskConfig(), [cfg])}


def backtest_paths(dataset: Path, sample: str, strategy: str) -> Path:
    """The baseline keeps the PR #4 location; variants get their own folder."""
    sub = Path(sample) / SCENARIO if strategy == "hos" else Path(sample) / strategy / SCENARIO
    return dataset / "backtest" / sub


def run_backtests(dataset: Path, store: QuoteStore, cache_only: QuoteStore, sample: str = IN_SAMPLE,
                  strat: StrategyConfig = StrategyConfig(), risk: RiskConfig = RiskConfig(),
                  ) -> dict[str, BacktestResult]:
    """All three strategies with the frozen base 50 bps execution model. The baseline is rerun from
    cache only and must reproduce the committed PR #4 ledgers exactly."""
    if sample != IN_SAMPLE:
        raise ValueError("variants are in-sample only")
    (cfg,) = with_spread_caps([SCENARIOS["base"]], [50])
    assert cfg.name == SCENARIO
    out: dict[str, BacktestResult] = {}
    for k in STRATEGIES:
        rows = read_table(dataset / "research" / sample / f"signals_{k}.csv")
        res = run_backtest(signals_from_breakouts(rows, {sample}), cache_only if k == "hos" else store, cfg, strat, risk)
        path = backtest_paths(dataset, sample, k)
        if k == "hos":
            fresh = path.parent / f".rerun_{SCENARIO}"
            write_rows(fresh / "trades.csv", res.trades)
            write_rows(fresh / "attempts.csv", res.attempts)
            for name in ("trades.csv", "attempts.csv"):
                if (fresh / name).read_bytes() != (path / name).read_bytes():
                    raise RuntimeError(f"baseline rerun does not reproduce {path / name}; execution model changed?")
        else:
            write_rows(path / "trades.csv", res.trades)
            write_rows(path / "attempts.csv", res.attempts)
        out[k] = res
    return out


def _consistency(results: Mapping[str, BacktestResult]) -> dict[str, object]:
    """Signals evaluated (not skipped) by both the baseline and a variant must get identical outcomes:
    the per-signal execution model is shared, so differences come only from which signals are taken."""
    def evaluated(res: BacktestResult) -> dict[tuple[str, str], tuple]:
        # exit_price is nan when nothing sold (nan != nan), so compare sold shares and realized P&L instead
        trades = {(t.symbol, t.signal_available_utc): (t.entry_price, t.qty, t.exit_qty, t.exit_reason,
                                                       t.realized_net_usd, t.exit_complete)
                  for t in res.trades}
        return {(a.symbol, a.signal_available_utc): (a.outcome, a.reason, trades.get((a.symbol, a.signal_available_utc)))
                for a in res.attempts if a.outcome != "skipped"}

    base = evaluated(results["hos"])
    out: dict[str, object] = {}
    for k in STRATEGIES[1:]:
        other = evaluated(results[k])
        common = base.keys() & other.keys()
        out[k] = {"common_evaluated_signals": len(common),
                  "identical_outcomes": sum(1 for x in common if base[x] == other[x])}
    return out


def compare(dataset: Path, results: Mapping[str, BacktestResult], sample: str = IN_SAMPLE) -> dict[str, object]:
    """Aggregate, symbol-free comparison of the three strategies on the same sessions."""
    base = dataset / "research" / sample
    coverage = read_table(base / "top5_coverage.csv")
    flags = read_table(base / "bullflag_candidates.csv.gz")
    filtered = read_table(base / "filtered.csv.gz")
    found = [r for r in coverage if r["bars_file"] == "found"]
    short_key = next((k for k in found[0] if k.startswith("minutes_with_fewer")), "") if found else ""
    strategies = {}
    for k in STRATEGIES:
        s = summarize(results[k])
        signals = read_table(base / f"signals_{k}.csv")
        strategies[k] = {"label": STRATEGY_LABELS[k], "signals_to_backtest": len(signals),
                         "filtered_before_backtest": dict(Counter(r["reason"] for r in filtered if r["strategy"] == k)),
                         "results": s}
    return {
        "sample": sample, "scenario": SCENARIO, "orders_placed": 0,
        "status": "exploratory hypotheses (in-sample only); not validated",
        "sessions": {"total": len(coverage), "with_bars": len(found),
                     "missing_bars": [f"{r['trading_date']} {r['session']}" for r in coverage if r["bars_file"] != "found"]},
        "top5": {
            "universe": UNIVERSE,
            "universe_limit": "Ranked universe = symbols the dataset fetched bars for (reference close below about "
                              "$18.2 premarket / $19.0 after hours), filtered to the $1-$20 scan band and 100k session "
                              "volume. Symbols outside it are absent, so this is not the market-wide top-gainers list.",
            "mean_eligible_symbols": fmean(int(r["eligible_symbols"]) for r in found) if found else None,
            "mean_symbols_with_bars": fmean(int(r["symbols_with_bars"]) for r in found) if found else None,
            "minutes": sum(int(r["minutes"]) for r in found),
            "minutes_with_fewer_than_5_ranked": sum(int(r[short_key]) for r in found) if short_key else None,
            "mean_distinct_members_per_session": fmean(int(r["distinct_top_members"]) for r in found) if found else None,
            "max_staleness_minutes": RankParams().max_staleness_minutes,
            "stale_exclusion_symbol_minutes": sum(int(r["stale_exclusion_symbol_minutes"]) for r in found),
        },
        "bull_flag": {"params": flag_params_record(), "attempts_evaluated": len(flags),
                      "qualified": sum(1 for r in flags if r["qualified"] == "True"),
                      "qualified_in_top5_and_gated": len(read_table(base / "signals_top5_bullflag.csv")),
                      "first_failed_rule": dict(Counter(r["reason"] for r in flags).most_common())},
        "strategies": strategies,
        "execution_consistency": _consistency(results),
    }


def decisions(dataset: Path, sample: str = IN_SAMPLE) -> list[dict[str, object]]:
    """Every strategy decision in time order: filter-stage removals plus the backtester's outcome for
    each signal it received (from the diagnostics signal ledgers)."""
    base = dataset / "research" / sample
    rows: list[dict[str, object]] = [dict(r) for r in read_table(base / "filtered.csv.gz")]
    for k in STRATEGIES:
        sub = Path(sample) / SCENARIO if k == "hos" else Path(sample) / k / SCENARIO
        ledger = dataset / "diagnostics" / sub / "signal_ledger.csv"
        if not ledger.is_file():
            continue
        ranks = {(r["symbol"], r["sip_bar_start_utc"]): r.get("top5_rank") for r in read_table(base / f"signals_{k}.csv")}
        for r in read_table(ledger):
            rows.append({"strategy": k, "trigger": "bull_flag" if k == "top5_bullflag" else "hos_breakout",
                         "symbol": r["symbol"], "trading_date": r["trading_date"], "session": r["session"],
                         "signal_bar_start_utc": r["signal_bar_start_utc"],
                         "signal_available_utc": r["signal_available_utc"],
                         "top5_rank": ranks.get((r["symbol"], r["signal_bar_start_utc"])) or None,
                         "outcome": r["outcome"], "reason": r["reason"]})
    rows.sort(key=lambda r: (str(r["signal_available_utc"]), str(r["symbol"]), str(r["strategy"])))
    return rows


def _f(x: object, nd: int = 2) -> str:
    return "–" if x is None else f"{x:,.{nd}f}" if isinstance(x, float) else str(x)


def _pct(x: object) -> str:
    return "–" if x is None else f"{float(x) * 100:.1f}%"  # type: ignore[arg-type]


def render_comparison(c: Mapping[str, object]) -> str:
    """Generated aggregate report (no symbols, no per-trade rows)."""
    st: Mapping[str, Mapping] = c["strategies"]  # type: ignore[assignment]
    t5: Mapping[str, object] = c["top5"]  # type: ignore[assignment]
    bf: Mapping[str, object] = c["bull_flag"]  # type: ignore[assignment]
    ses: Mapping[str, object] = c["sessions"]  # type: ignore[assignment]
    L = [f"# Strategy comparison: {c['sample']}, {c['scenario']} (generated)", "",
         "\"Top 5\" is ranked within the dataset's cached eligible sub-$20 universe, not the market-wide "
         "top-gainers list.", "",
         f"Status: **{c['status']}**. Simulated fills against cached historical SIP quotes; 0 orders. "
         "Every variant uses the unchanged execution model, risk limits and frozen 50 bps cap.", "",
         f"Sessions: {ses['with_bars']} of {ses['total']} with cached bars "
         f"(missing: {', '.join(ses['missing_bars']) or 'none'}).", ""]  # type: ignore[arg-type]
    for session in ("all", "premarket", "afterhours"):
        L += [f"## {session}", "", "| strategy | signals | orders sent | entries | completed trades | incomplete exits | "
              "fill rate | win rate | avg R | 95% CI | net $ | profit factor | max drawdown $ |",
              "|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|"]
        for v in st.values():
            r = v["results"][session]
            ci = r["expectancy_r_ci95_bootstrap"]
            ie = r["incomplete_exits"]
            unsold = f" ({ie['shares_unsold']} sh unsold)" if ie["count"] else ""
            L.append(f"| {v['label']} | {r['signals']} | {r['orders_simulated']} | {r['entries']} | {r['trades']} | "
                     f"{ie['count']}{unsold} | "
                     f"{_pct(r['fill_rate'])} | {_pct(r['win_rate'])} | {_f(r['expectancy_r'])} | "
                     f"{f'[{ci[0]:.2f}, {ci[1]:.2f}]' if ci else '–'} | {_f(r['net_usd'])} | "
                     f"{_f(r['profit_factor'])} | {_f(r['max_drawdown_usd'])} |")
        L.append("")
    L += ["## Portfolio skips (shared daily risk budget)", "", "| strategy | skipped, by reason |", "|---|---|"]
    for v in st.values():
        L.append(f"| {v['label']} | {', '.join(f'{k} {n}' for k, n in sorted(v['results']['all']['skipped'].items()))} |")
    L += ["", "## Execution-model isolation", "",
          "The per-signal simulation is shared, so a signal evaluated by both the baseline and a variant must get "
          "the same outcome. Differences in P&L then come only from which signals are taken (the filter and the "
          "path-dependent daily limits), not from execution.", "",
          "| variant | signals evaluated by both | identical outcomes |", "|---|---:|---:|"]
    for k, v in c["execution_consistency"].items():  # type: ignore[union-attr]
        L.append(f"| {STRATEGY_LABELS[k]} | {v['common_evaluated_signals']} | {v['identical_outcomes']} |")
    L += ["", "## Top 5 reconstruction", "", str(t5["universe_limit"]), "",
          f"Mean eligible symbols per session {_f(t5['mean_eligible_symbols'], 0)}, with at least one bar "
          f"{_f(t5['mean_symbols_with_bars'], 0)}. Minutes with fewer than 5 ranked symbols: "
          f"{t5['minutes_with_fewer_than_5_ranked']} of {t5['minutes']}. Mean distinct Top 5 members per session: "
          f"{_f(t5['mean_distinct_members_per_session'], 1)}.", "",
          f"Freshness: missing bars are never filled; a price older than {t5['max_staleness_minutes']} minutes is "
          f"stale and not ranked ({t5['stale_exclusion_symbol_minutes']} symbol-minutes excluded).", "",
          "## Bull Flag detector", "", f"Parameters: `{json.dumps(bf['params'])}`.", "",
          f"Breakout attempts evaluated on Top 5 members: {bf['attempts_evaluated']}; qualified flags: {bf['qualified']}; "
          f"qualified while in the Top 5 and passing the scanner gate: {bf['qualified_in_top5_and_gated']}.", "",
          "| first failed rule | attempts |", "|---|---:|"]
    L[5:5] = ["Win rate, average R, net P&L and profit factor use completed trades only. Incomplete exits (unsold "
              "shares when the 2-minute exit window ended) are counted as entries and reported apart, never as P&L.", ""]
    L += [f"| {k} | {n} |" for k, n in bf["first_failed_rule"].items()]  # type: ignore[union-attr]
    return "\n".join(L) + "\n"

