"""Minimal quote-aware backtest of the initial breakout strategy (docs/DESIGN.md M2 and section 6).

Simulation only. There is no broker client here and nothing in this module can place or change an
order. Entries and exits are simulated against historical SIP NBBO quotes:

- A signal is known only when its 1-minute trigger bar completes (``Signal.available_utc``). A
  simulated order reaches the market at ``available_utc + latency``; no fill can happen earlier.
- Orders fill only against fresh (age <= max_quote_age_s), executable (ask > bid) quotes. Locked,
  crossed, one-sided and stale quotes never fill. Entries also require spread <= cap.
- Buys are marketable limits at the signal-time ask plus an offset, capped at the displayed ask
  size per quote; whatever is unfilled when the entry timeout ends expires (a non-fill or
  partial fill). Exits sell at the bid, up to the displayed bid size per quote, until filled.
- Costs: the spread (fills at the touch), adverse slippage in the stress case, SEC and FINRA TAF
  fees on sells. Alpaca equity commissions are zero.

Results are not evidence of live fill quality. Queue position, hidden liquidity, odd lots, halts and
venue-specific extended-hours rules are not modelled.
"""

from __future__ import annotations

import bisect
import csv
import gzip
import json
import math
import random
from collections import Counter
from collections.abc import Callable, Iterable, Mapping
from dataclasses import asdict, dataclass, field, replace
from datetime import date, datetime, timedelta
from pathlib import Path
from statistics import fmean, median

from .data.market_calendar import session_windows
from .data.normalize import BAR_LENGTH
from .quotes import EXECUTABLE, MAX_QUOTE_AGE_S, SPREAD_CAP_BPS, QuoteSource, clean_quotes, quote_state, spread_bps
from .split import EMBARGO

ENTRY_SPAN = timedelta(seconds=30)  # first quote fetch after a signal; latency + entry timeout must fit in it
EXIT_SLACK = timedelta(minutes=2)  # quotes kept after the exit deadline so the exit order can fill
SEC_FEE_PER_DOLLAR = 27.80e-6  # Section 31 fee on sale proceeds; verify the current SEC rate
TAF_PER_SHARE, TAF_MAX = 0.000166, 8.30  # FINRA trading activity fee on shares sold; verify current rates


@dataclass(frozen=True, slots=True)
class Signal:
    symbol: str
    trading_date: date
    session: str
    sample: str
    bar_start_utc: datetime
    available_utc: datetime  # trigger bar completion: the earliest time the signal is known
    price: float  # trigger bar close

    def __post_init__(self) -> None:
        if self.available_utc < self.bar_start_utc + BAR_LENGTH:
            raise ValueError("a signal cannot be available before its trigger bar completes")


@dataclass(frozen=True, slots=True)
class Quote:
    t: datetime
    bid: float
    ask: float
    bid_size: int
    ask_size: int

    @property
    def state(self) -> str:
        return quote_state(self.bid, self.ask)

    @property
    def spread_bps(self) -> float:
        return spread_bps(self.bid, self.ask)

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2


def parse_quote(row: Mapping[str, object]) -> Quote:
    """Alpaca v2 quote row; sizes are in shares."""
    return Quote(datetime.fromisoformat(str(row["t"])), float(row.get("bp") or 0), float(row.get("ap") or 0),  # type: ignore[arg-type]
                 int(row.get("bs") or 0), int(row.get("as") or 0))  # type: ignore[call-overload]


@dataclass(frozen=True, slots=True)
class ExecConfig:
    name: str
    latency: timedelta = timedelta(milliseconds=500)
    max_quote_age_s: float | None = MAX_QUOTE_AGE_S  # None ignores quote age (idealized reference only)
    spread_cap_bps: float | None = SPREAD_CAP_BPS  # entry-only; exits must get out regardless of spread
    entry_timeout: timedelta = timedelta(seconds=10)
    limit_offset_bps: float = 20.0  # buy limit = signal-time ask * (1 + offset)
    size_share: float | None = 1.0  # share of displayed size available to us; None = unlimited
    price: str = "touch"  # "touch": buy at ask, sell at bid; "mid": idealized reference
    adverse_bps: float = 0.0
    fees: bool = True

    def __post_init__(self) -> None:
        if self.latency + self.entry_timeout > ENTRY_SPAN:
            raise ValueError("latency + entry_timeout must fit in ENTRY_SPAN")


SCENARIOS: dict[str, ExecConfig] = {
    # Upper-bound reference: no latency, mid fills, unlimited size, no cap, no fees. Not achievable.
    "idealized": ExecConfig("idealized", latency=timedelta(0), max_quote_age_s=None, spread_cap_bps=None,
                            size_share=None, price="mid", fees=False),
    "base": ExecConfig("base"),
    "stress": ExecConfig("stress", latency=timedelta(seconds=2), size_share=0.5, adverse_bps=10.0),
}


@dataclass(frozen=True, slots=True)
class StrategyConfig:
    """Untuned research hypotheses, fixed before any backtest was run."""

    stop_pct: float = 0.03
    target_r: float = 2.0
    max_hold: timedelta = timedelta(minutes=15)
    entry_cutoff_before_close: timedelta = timedelta(minutes=10)  # 09:20 and 19:50 ET on normal days
    flatten_before_close: timedelta = timedelta(minutes=2)


@dataclass(frozen=True, slots=True)
class RiskConfig:
    account_usd: float = 3_000.0
    risk_per_trade_usd: float = 15.0
    max_notional_frac: float = 0.25
    daily_loss_limit_usd: float = 45.0
    max_entries_per_day: int = 5
    max_consecutive_losses: int = 3


@dataclass(slots=True)
class Trade:
    symbol: str
    trading_date: str
    session: str
    sample: str
    scenario: str
    signal_bar_start_utc: str
    signal_available_utc: str
    signal_price: float
    signal_spread_bps: float
    requested_qty: int
    qty: int
    entry_first_fill_utc: str
    entry_price: float
    seconds_to_fill: float
    exit_reason: str
    exit_trigger_utc: str
    exit_last_fill_utc: str
    exit_price: float
    exit_complete: bool
    gross_usd: float
    fees_usd: float
    net_usd: float
    r_multiple: float


@dataclass(slots=True)
class Attempt:
    symbol: str
    trading_date: str
    session: str
    sample: str
    scenario: str
    signal_available_utc: str
    outcome: str  # filled | partial | non_fill | skipped
    reason: str = ""


class QuoteStore:
    """SIP quotes for a signal, fetched in two stages and cached locally (licensed data, git-ignored)."""

    def __init__(self, source: QuoteSource, cache_dir: Path) -> None:
        self.source, self.cache_dir = source, cache_dir
        cache_dir.mkdir(parents=True, exist_ok=True)

    def get(self, sig: Signal, start: datetime, end: datetime) -> list[Quote]:
        if end <= start:
            return []
        path = self.cache_dir / f"{sig.symbol}_{start:%Y%m%dT%H%M%S}_{end:%H%M%S}.jsonl.gz"
        if path.is_file():
            with gzip.open(path, "rt", encoding="utf-8") as fh:
                rows = [json.loads(line) for line in fh]
        else:
            rows = list(self.source.iter_quotes(sig.symbol, "sip", start, end))
            tmp = path.with_suffix(".tmp")
            with gzip.open(tmp, "wt", encoding="utf-8") as fh:
                fh.writelines(json.dumps(r, sort_keys=True) + "\n" for r in rows)
            tmp.replace(path)
        return [parse_quote(r) for r in clean_quotes(rows, start, end)]


def quote_stages(sig: Signal, strat: StrategyConfig) -> tuple[tuple[datetime, datetime], tuple[datetime, datetime]]:
    """(entry window, holding window). The entry window starts one max quote age before the signal so
    the quote prevailing at signal time is known; nothing after a decision time is used for it."""
    close = session_windows(sig.trading_date)[sig.session].end_utc
    split = sig.available_utc + ENTRY_SPAN
    end = min(split + strat.max_hold + EXIT_SLACK, close)
    return (sig.available_utc - timedelta(seconds=MAX_QUOTE_AGE_S), min(split, close)), (min(split, close), end)


def _rejection(q: Quote | None, at: datetime, cfg: ExecConfig, *, check_spread: bool) -> str | None:
    if q is None:
        return "no_quote"
    if cfg.max_quote_age_s is not None and (at - q.t).total_seconds() > cfg.max_quote_age_s:
        return "stale_quote"
    if q.state != EXECUTABLE:
        return f"{q.state}_quote"
    if check_spread and cfg.spread_cap_bps is not None and q.spread_bps > cfg.spread_cap_bps:
        return "spread_above_cap"
    return None


def _price(q: Quote, side: str, cfg: ExecConfig) -> float:
    base = q.mid if cfg.price == "mid" else (q.ask if side == "buy" else q.bid)
    return base * (1 + cfg.adverse_bps / 10_000) if side == "buy" else base * (1 - cfg.adverse_bps / 10_000)


def _prevailing(quotes: list[Quote], times: list[datetime], t: datetime) -> Quote | None:
    i = bisect.bisect_right(times, t) - 1
    return quotes[i] if i >= 0 else None


def _execute(quotes: list[Quote], times: list[datetime], side: str, qty: int, arrive: datetime,
             until: datetime | None, cfg: ExecConfig, limit: float | None, *, check_spread: bool,
             ) -> tuple[list[tuple[datetime, float, int]], Counter[str]]:
    """Walk the quote stream from order arrival; fills never happen before ``arrive``."""
    i = bisect.bisect_right(times, arrive) - 1
    points = ([(arrive, quotes[i])] if i >= 0 else []) + [(q.t, q) for q in quotes[i + 1:]]
    fills: list[tuple[datetime, float, int]] = []
    misses: Counter[str] = Counter()
    left = qty
    for at, q in points:
        if until is not None and at > until:
            break
        reason = _rejection(q, at, cfg, check_spread=check_spread)
        px = _price(q, side, cfg)
        if reason is None and side == "buy" and limit is not None and px > limit:
            reason = "price_above_limit"
        if reason:
            misses[reason] += 1
            continue
        shown = q.ask_size if side == "buy" else q.bid_size
        n = left if cfg.size_share is None else min(left, int(shown * cfg.size_share))
        if n <= 0:
            misses["no_displayed_size"] += 1
            continue
        assert at >= arrive
        fills.append((at, px, n))
        left -= n
        if left == 0:
            break
    return fills, misses


def _fees(sold_usd: float, shares: int, cfg: ExecConfig) -> float:
    if not cfg.fees:
        return 0.0
    return sold_usd * SEC_FEE_PER_DOLLAR + min(shares * TAF_PER_SHARE, TAF_MAX)


def simulate_signal(sig: Signal, quotes_entry: list[Quote], hold: Callable[[], list[Quote]], cfg: ExecConfig,
                    strat: StrategyConfig, risk: RiskConfig) -> Trade | Attempt:
    """One signal end to end. ``hold`` lazily loads the holding-window quotes, only after a fill."""
    base = dict(symbol=sig.symbol, trading_date=sig.trading_date.isoformat(), session=sig.session,
                sample=sig.sample, scenario=cfg.name, signal_available_utc=sig.available_utc.isoformat())
    close = session_windows(sig.trading_date)[sig.session].end_utc
    if sig.available_utc > close - strat.entry_cutoff_before_close:
        return Attempt(**base, outcome="skipped", reason="after_entry_cutoff")
    times = [q.t for q in quotes_entry]
    q0 = _prevailing(quotes_entry, times, sig.available_utc)
    reason = _rejection(q0, sig.available_utc, cfg, check_spread=True)
    if reason or q0 is None:
        return Attempt(**base, outcome="non_fill", reason=f"at_signal_{reason}")
    limit = q0.ask * (1 + cfg.limit_offset_bps / 10_000)
    qty = math.floor(min(risk.risk_per_trade_usd / (limit * strat.stop_pct),
                         risk.account_usd * risk.max_notional_frac / limit))
    if qty < 1:
        return Attempt(**base, outcome="non_fill", reason="size_below_one_share")
    arrive = sig.available_utc + cfg.latency
    buys, misses = _execute(quotes_entry, times, "buy", qty, arrive, arrive + cfg.entry_timeout, cfg, limit,
                            check_spread=True)
    if not buys:
        top = misses.most_common(1)[0][0] if misses else "no_quote"
        return Attempt(**base, outcome="non_fill", reason=f"timeout_{top}")
    filled = sum(n for _, _, n in buys)
    entry = sum(px * n for _, px, n in buys) / filled
    first_fill, last_fill = buys[0][0], buys[-1][0]

    quotes = quotes_entry + hold()
    times = [q.t for q in quotes]
    stop, target = entry * (1 - strat.stop_pct), entry * (1 + strat.stop_pct * strat.target_r)
    deadline = min(first_fill + strat.max_hold, close - strat.flatten_before_close)
    trigger, why = deadline, "time" if first_fill + strat.max_hold <= close - strat.flatten_before_close else "session_end"
    for q in quotes[bisect.bisect_right(times, last_fill):]:
        if q.t >= deadline:
            break
        if _rejection(q, q.t, cfg, check_spread=False) is None:  # only fresh executable quotes trigger exits
            if q.bid <= stop:
                trigger, why = q.t, "stop"
                break
            if q.bid >= target:
                trigger, why = q.t, "target"
                break
    sells, _ = _execute(quotes, times, "sell", filled, trigger + cfg.latency, None, cfg, None, check_spread=False)
    sold = sum(n for _, _, n in sells)
    proceeds = sum(px * n for _, px, n in sells)
    complete = sold == filled
    if not complete:  # missed exit: mark the remainder at the last executable bid known, else at the stop
        last = [q for q in quotes if q.state == EXECUTABLE]
        mark = _price(last[-1], "sell", cfg) if last else stop
        proceeds += mark * (filled - sold)
    exit_px = proceeds / filled
    fees = _fees(proceeds, filled, cfg)
    gross = proceeds - entry * filled
    return Trade(sig.symbol, sig.trading_date.isoformat(), sig.session, sig.sample, cfg.name,
                 sig.bar_start_utc.isoformat(), sig.available_utc.isoformat(), sig.price, q0.spread_bps, qty, filled,
                 first_fill.isoformat(), entry, (first_fill - sig.available_utc).total_seconds(), why,
                 trigger.isoformat(), (sells[-1][0] if sells else trigger).isoformat(), exit_px, complete,
                 gross, fees, gross - fees, (gross - fees) / (entry * strat.stop_pct * filled))


@dataclass(slots=True)
class _Day:
    entries: int = 0
    net: float = 0.0
    losses_in_row: int = 0


@dataclass(slots=True)
class BacktestResult:
    scenario: str
    trades: list[Trade] = field(default_factory=list)
    attempts: list[Attempt] = field(default_factory=list)


def run_backtest(signals: Iterable[Signal], store: QuoteStore, cfg: ExecConfig, strat: StrategyConfig = StrategyConfig(),
                 risk: RiskConfig = RiskConfig()) -> BacktestResult:
    """Chronological portfolio loop: one position at a time, daily entry/loss limits, loss-streak pause."""
    out = BacktestResult(cfg.name)
    days: dict[date, _Day] = {}
    busy_until: datetime | None = None
    for sig in sorted(signals, key=lambda s: (s.available_utc, s.symbol)):
        day = days.setdefault(sig.trading_date, _Day())
        base = dict(symbol=sig.symbol, trading_date=sig.trading_date.isoformat(), session=sig.session,
                    sample=sig.sample, scenario=cfg.name, signal_available_utc=sig.available_utc.isoformat())
        skip = ("position_open" if busy_until and sig.available_utc < busy_until else
                "daily_entry_limit" if day.entries >= risk.max_entries_per_day else
                "daily_loss_limit" if day.net <= -risk.daily_loss_limit_usd else
                "loss_streak_pause" if day.losses_in_row >= risk.max_consecutive_losses else None)
        if skip:
            out.attempts.append(Attempt(**base, outcome="skipped", reason=skip))
            continue
        (e0, e1), (h0, h1) = quote_stages(sig, strat)
        res = simulate_signal(sig, store.get(sig, e0, e1), lambda: store.get(sig, h0, h1), cfg, strat, risk)
        if isinstance(res, Attempt):
            out.attempts.append(res)
            continue
        out.trades.append(res)
        out.attempts.append(Attempt(**base, outcome="filled" if res.qty == res.requested_qty else "partial"))
        busy_until = datetime.fromisoformat(res.exit_last_fill_utc)
        day.entries += 1
        day.net += res.net_usd
        day.losses_in_row = day.losses_in_row + 1 if res.net_usd < 0 else 0
    return out


def signals_from_breakouts(rows: Iterable[Mapping[str, str]], samples: set[str]) -> list[Signal]:
    """The initial strategy: candidate-gated SIP completed-bar session-high breakouts (dataset output)."""
    out = []
    for r in rows:
        if not r.get("sip_bar_start_utc") or r.get("sip_candidate_gate") != "True" or r["sample"] not in samples:
            continue
        start = datetime.fromisoformat(r["sip_bar_start_utc"])
        available = datetime.fromisoformat(r["sip_signal_available_utc"]) if r.get("sip_signal_available_utc") \
            else start + BAR_LENGTH
        out.append(Signal(r["symbol"], date.fromisoformat(r["trading_date"]), r["session"], r["sample"], start,
                          available, float(r.get("sip_price") or "nan")))
    return out


MIN_TRADES_FOR_SELECTION = 30


def with_spread_caps(scenarios: Iterable[ExecConfig], caps: Iterable[float]) -> list[ExecConfig]:
    """One variant per spread cap for each capped scenario; the uncapped idealized reference runs once."""
    caps = list(caps)
    out: list[ExecConfig] = []
    for c in scenarios:
        out += [c] if c.spread_cap_bps is None else [replace(c, name=f"{c.name}_cap{cap:g}", spread_cap_bps=cap)
                                                     for cap in caps]
    return out


def select_spread_cap(results: Mapping[str, Mapping[str, Mapping[str, object]]], caps: Iterable[float]) -> dict[str, object]:
    """Pre-registered in-sample rule: the base-case cap with the highest expectancy in R among caps with
    at least MIN_TRADES_FOR_SELECTION trades; ties go to the tighter cap."""
    rows = [(cap, results[f"base_cap{cap:g}"]["all"]) for cap in sorted(caps) if f"base_cap{cap:g}" in results]
    ok = [(cap, r) for cap, r in rows if int(r["trades"]) >= MIN_TRADES_FOR_SELECTION]  # type: ignore[call-overload]
    best = max(ok, key=lambda x: (float(x[1]["expectancy_r"]), -x[0]), default=None)  # type: ignore[arg-type]
    return {"rule": f"max base-case expectancy_r, >= {MIN_TRADES_FOR_SELECTION} trades, ties to tighter cap",
            "selected_spread_cap_bps": best[0] if best else None}


def _bootstrap_ci(values: list[float], seed: int = 0, n: int = 2000) -> tuple[float, float] | None:
    if len(values) < 2:
        return None
    rng = random.Random(seed)
    means = sorted(fmean(rng.choices(values, k=len(values))) for _ in range(n))
    return means[int(0.025 * n)], means[int(0.975 * n) - 1]


def summarize(result: BacktestResult) -> dict[str, object]:
    out: dict[str, object] = {}
    for session in ("premarket", "afterhours", "all"):
        tr = [t for t in result.trades if session in ("all", t.session)]
        at = [a for a in result.attempts if session in ("all", a.session)]
        tried = [a for a in at if a.outcome != "skipped"]
        nets = [t.net_usd for t in tr]
        wins, losses = [x for x in nets if x > 0], [x for x in nets if x <= 0]
        equity = peak = drawdown = 0.0
        for x in nets:
            equity += x
            peak = max(peak, equity)
            drawdown = max(drawdown, peak - equity)
        out[session] = {
            "signals": len(at),
            "skipped": dict(Counter(a.reason for a in at if a.outcome == "skipped")),
            "orders_simulated": len(tried),
            "non_fills": dict(Counter(a.reason for a in tried if a.outcome == "non_fill")),
            "fill_rate": len(tr) / len(tried) if tried else None,
            "partial_fills": sum(1 for a in tried if a.outcome == "partial"),
            "median_seconds_to_fill": median(t.seconds_to_fill for t in tr) if tr else None,
            "median_entry_spread_bps": median(t.signal_spread_bps for t in tr) if tr else None,
            "median_entry_vs_signal_close_bps": median((t.entry_price / t.signal_price - 1) * 1e4 for t in tr
                                                       if t.signal_price == t.signal_price) if tr else None,
            "trades": len(tr),
            "win_rate": len(wins) / len(tr) if tr else None,
            "gross_usd": sum(t.gross_usd for t in tr),
            "fees_usd": sum(t.fees_usd for t in tr),
            "net_usd": sum(nets),
            "expectancy_usd": fmean(nets) if tr else None,
            "expectancy_r": fmean(t.r_multiple for t in tr) if tr else None,
            "expectancy_r_ci95_bootstrap": _bootstrap_ci([t.r_multiple for t in tr]),
            "profit_factor": sum(wins) / -sum(losses) if losses and sum(losses) < 0 else None,
            "avg_win_usd": fmean(wins) if wins else None,
            "avg_loss_usd": fmean(losses) if losses else None,
            "max_drawdown_usd": drawdown,
            "exit_reasons": dict(Counter(t.exit_reason for t in tr)),
            "incomplete_exits": sum(1 for t in tr if not t.exit_complete),
        }
    return out


def write_rows(path: Path, rows: list[object]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    dicts = [asdict(r) for r in rows]  # type: ignore[call-overload]
    with path.open("w", newline="", encoding="utf-8") as fh:
        if dicts:
            w = csv.DictWriter(fh, fieldnames=list(dicts[0]), lineterminator="\n")
            w.writeheader()
            w.writerows(dicts)


def config_record(strat: StrategyConfig, risk: RiskConfig, scenarios: Iterable[ExecConfig]) -> dict[str, object]:
    def plain(obj: object) -> dict[str, object]:
        return {k: (v.total_seconds() if isinstance(v, timedelta) else v) for k, v in asdict(obj).items()}  # type: ignore[call-overload]

    return {"strategy": plain(strat), "risk": plain(risk), "scenarios": {c.name: plain(c) for c in scenarios},
            "fees": {"sec_fee_per_dollar_sold": SEC_FEE_PER_DOLLAR, "taf_per_share_sold": TAF_PER_SHARE,
                     "taf_max": TAF_MAX, "commission": 0.0},
            "excluded_samples": [EMBARGO]}

