"""Bull Flag intrabar breakout: an isolated research strategy, fixed before any backtest of it was run.

Specification: docs/research/bull_flag_intrabar_spec.md. Summary:

- Setup (causal): when a 1-minute SIP bar j completes, the bars up to j are checked for a flagpole
  followed by a consolidation ending at j (the Bull Flag rules of bullflag.FlagParams, without the
  breakout rules). The reference candle is the consolidation bar with the highest high (the latest
  one on ties). The setup becomes known at bar j's end and stays armed for ``arm_bars`` minutes.
- Setup ID = symbol | trading date | session | reference bar start. A reference candle can produce
  one entry at most; later evaluations that pick the same reference candle are the same setup.
- Trigger: the first moment after the setup is known that the market is above the reference High.
  With cached NBBO quotes covering the whole setup, that is the first fresh executable quote whose
  Bid exceeds the reference High (a proxy: a quote is not a print). Otherwise it is the first bar
  whose High exceeds it, an explicitly labelled 1-minute OHLC approximation.
- Entry: buy at the Ask after the existing latency, limited to 20 bps above the trigger Ask, within
  the displayed size, with the existing 50 bps spread cap and 10 s timeout. OHLC approximation:
  max(bar open, reference High) plus a predeclared cost. Never a fill at the reference High itself.
- Stop: the reference candle's Low, frozen at entry. Triggered by a fresh executable Bid at or below
  it; sold at the Bid after latency with partial fills; unsold shares are recorded.
- Red-candle exit: the first completed bar with Close < Open whose whole interval starts at or after
  the entry fill. It is known at the bar's end; the sell uses the first eligible quote after latency.
  A stop seen before that bar completes takes priority.
- Safety exits: ``max_hold`` after entry and the session flatten time (not profit targets).
- One position at a time and the existing daily limits; a setup that triggers while a position is
  open is consumed, so a still-true breakout condition never re-enters later.

No trade prints are cached, so no entry here has reliable trade-level sequencing. This module reads
the dataset and the quote cache and never writes to either; it makes no network requests.
"""

from __future__ import annotations

import bisect
import gzip
import hashlib
import json
import math
from collections import Counter, defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass, field
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from statistics import fmean, median

from .backtest import (
    EXIT_SLACK, SCENARIOS, ExecConfig, Quote, RiskConfig, _execute, _fees, _prevailing, _rejection, parse_quote,
)
from .bullflag import FlagParams, session_volumes
from .data.market_calendar import EXTENDED_SESSIONS, SessionWindow, session_windows
from .data.normalize import BAR_LENGTH
from .data.provider import AuthenticationError, Bar, EntitlementError, ProviderError
from .quotes import EXECUTABLE, MAX_QUOTE_AGE_S, clean_quotes

_UTC = timezone.utc
STRATEGIES = ("bf_intrabar", "top5_bf_intrabar")
LABELS = {"bf_intrabar": "Bull Flag intrabar (no Top 5 filter)",
          "top5_bf_intrabar": "Bull Flag intrabar, Top 5 (cached universe) at the setup bar"}


@dataclass(frozen=True, slots=True)
class IntrabarParams:
    """Fixed before any performance test. Not tuned; one primary configuration."""

    flag: FlagParams = FlagParams()
    arm_bars: int = 3  # a setup can trigger during the 3 minutes after it becomes known
    max_hold: timedelta = timedelta(minutes=15)  # safety constraint, not a profit target
    entry_cutoff_before_close: timedelta = timedelta(minutes=10)
    flatten_before_close: timedelta = timedelta(minutes=2)
    limit_offset_bps: float = 20.0
    ohlc_cost_bps: float = 25.0  # per side, OHLC approximation only (half the 50 bps spread cap)
    ohlc_volume_share: float = 0.10  # OHLC approximation: at most 10% of the trigger bar's volume


STRESS_OHLC_COST_BPS = 50.0  # predeclared stress: double the per-side OHLC cost


# ---------- setups (completed bars only) ----------

def find_setup(hist: list[Bar], vols: list[int], p: FlagParams = FlagParams()) -> dict[str, object] | None:
    """A Bull Flag whose consolidation ends at the LAST bar of ``hist``. Reads nothing beyond it.
    The shortest valid consolidation wins, then the shortest flagpole (deterministic)."""
    j = len(hist) - 1
    for c in range(p.flag_min_bars, p.flag_max_bars + 1):
        for n in range(p.pole_min_bars, p.pole_max_bars + 1):
            s = j + 1 - c - n
            if s < 0:
                break
            pole, flag = hist[s : j + 1 - c], hist[j + 1 - c : j + 1]
            if hist[j].timestamp_utc - pole[0].timestamp_utc != (c + n - 1) * BAR_LENGTH:
                continue  # a missing minute inside the pattern: never filled
            base, top = pole[0].low, pole[-1].high
            if not (base > 0 and top / base - 1 >= p.pole_min_gain and top >= max(x.high for x in pole)):
                continue
            flag_high, flag_low = max(x.high for x in flag), min(x.low for x in flag)
            if flag_high > top or (top - flag_low) / (top - base) > p.max_pullback:
                continue
            if not fmean(vols[j + 1 - c : j + 1]) < fmean(vols[s : j + 1 - c]):
                continue
            ref = max(flag, key=lambda b: (b.high, b.timestamp_utc))
            if ref.high <= ref.low:
                continue  # no structural risk
            return {"pole_start_utc": pole[0].timestamp_utc.isoformat(), "pole_bars": n, "flag_bars": c,
                    "pole_base": base, "pole_top": top, "ref_bar_start_utc": ref.timestamp_utc.isoformat(),
                    "ref_high": ref.high, "ref_low": ref.low}
    return None


@dataclass(slots=True)
class Setup:
    setup_id: str
    symbol: str
    trading_date: str
    session: str
    setup_bar_start_utc: datetime
    known_utc: datetime  # setup bar end
    expires_utc: datetime
    level: float  # reference High: the breakout trigger
    stop: float  # reference Low: the structural stop
    detail: dict[str, object]
    top5_rank: int | None = None


def detect_setups(symbol: str, bars: list[Bar], window: SessionWindow, p: IntrabarParams = IntrabarParams(),
                  gate: Mapping[str, bool] | None = None) -> list[Setup]:
    """Every distinct setup of one symbol-session, in time order. ``gate`` (bar start iso -> bool)
    keeps only setups whose setup bar passes the scanner gate. Duplicate reference candles collapse
    into the first setup that chose them."""
    vols = session_volumes(bars, window, p.flag.exclude_closing_auction_bar)
    seen: set[str] = set()
    out: list[Setup] = []
    for j in range(len(bars)):
        t = bars[j].timestamp_utc
        if gate is not None and not gate.get(t.isoformat(), False):
            continue
        f = find_setup(bars[: j + 1], vols[: j + 1], p.flag)
        if f is None:
            continue
        sid = f"{symbol}|{window.trading_date.isoformat()}|{window.name}|{f['ref_bar_start_utc']}"
        if sid in seen:
            continue
        seen.add(sid)
        known = t + BAR_LENGTH
        out.append(Setup(sid, symbol, window.trading_date.isoformat(), window.name, t, known,
                         min(known + p.arm_bars * BAR_LENGTH, window.end_utc), float(f["ref_high"]),
                         float(f["ref_low"]), f))
    return out


# ---------- quote cache (read only) ----------

class QuoteIndex:
    """Which time ranges of which symbols the local quote caches hold. Never fetches, never writes."""

    def __init__(self, *cache_dirs: Path) -> None:
        self.files: dict[str, list[tuple[datetime, datetime, Path]]] = defaultdict(list)
        self._memo: dict[tuple[str, datetime, datetime], list[Quote]] = {}  # decoded windows; see forget()
        self._rows: dict[Path, tuple[list[tuple[datetime, tuple, Quote]], list[datetime]]] = {}  # parsed files
        found = [f for d in cache_dirs if d.is_dir() for f in d.glob("*.jsonl.gz")]
        for f in sorted(found):
            try:
                sym, start, end = f.name[: -len(".jsonl.gz")].rsplit("_", 2)
                a = datetime.strptime(start, "%Y%m%dT%H%M%S").replace(tzinfo=_UTC)
                b = datetime.combine(a.date(), datetime.strptime(end, "%H%M%S").time(), _UTC)
            except ValueError:
                continue
            if b <= a:  # the name holds only the end's time of day: a window ending at or past midnight UTC
                b += timedelta(days=1)
            if b > a:
                self.files[sym].append((a, b, f))

    def covers(self, symbol: str, start: datetime, end: datetime) -> bool:
        t = start
        for a, b, _ in sorted(self.files.get(symbol, [])):
            if a <= t < b:
                t = b
            if t >= end:
                return True
        return t >= end

    def load(self, symbol: str, start: datetime, end: datetime) -> list[Quote]:
        """Decoded once and reused: the trigger check and every variant and scenario read the same window."""
        key = (symbol, start, end)
        if key not in self._memo:
            self._memo[key] = self._read(symbol, start, end)
        return self._memo[key]

    def forget(self) -> None:
        """Release decoded windows (the runner calls this after each trading day)."""
        self._memo.clear()
        self._rows.clear()

    def _parsed(self, f: Path) -> tuple[list[tuple[datetime, tuple, Quote]], list[datetime]]:
        """A file's quotes, parsed once and stably sorted by time (file order kept at equal times)."""
        if f not in self._rows:
            with gzip.open(f, "rt", encoding="utf-8") as fh:
                raw = [json.loads(line) for line in fh]
            items = [(t, (t, r.get("bp"), r.get("ap"), r.get("bs"), r.get("as")), parse_quote(r))
                     for r in raw for t in (datetime.fromisoformat(str(r["t"])),)]
            items.sort(key=lambda x: x[0])
            self._rows[f] = (items, [x[0] for x in items])
        return self._rows[f]

    def _read(self, symbol: str, start: datetime, end: datetime) -> list[Quote]:
        """Same result as quotes.clean_quotes over the overlapping files: quotes in [start, end), exact
        duplicate rows removed (first file wins), stably sorted by time."""
        seen: set[tuple] = set()
        out: list[tuple[datetime, Quote]] = []
        for a, b, f in self.files.get(symbol, []):
            if a < end and b > start:
                items, times = self._parsed(f)
                for t, key, q in items[bisect.bisect_left(times, start) : bisect.bisect_left(times, end)]:
                    if key not in seen:
                        seen.add(key)
                        out.append((t, q))
        out.sort(key=lambda x: x[0])
        return [q for _, q in out]



# ---------- one setup end to end ----------

@dataclass(slots=True)
class Result:
    setup_id: str
    symbol: str
    trading_date: str
    session: str
    mode: str  # nbbo_proxy | ohlc_approx | none
    sequencing: str  # proxy | approximate | uncertain
    outcome: str  # traded | non_fill | no_trigger | invalidated | rejected
    reason: str = ""
    trigger_utc: str = ""
    entry_first_fill_utc: str = ""
    entry_price: float = math.nan
    stop: float = math.nan
    qty: int = 0
    exit_reason: str = ""
    exit_trigger_utc: str = ""
    exit_last_fill_utc: str = ""
    exit_qty: int = 0
    remaining_qty: int = 0
    exit_price: float = math.nan
    exit_complete: bool = False
    net_usd: float | None = None
    realized_net_usd: float = 0.0
    r_multiple: float | None = None
    initial_risk_per_share: float = math.nan
    busy_until_utc: str = ""
    notes: list[str] = field(default_factory=list)


def _trigger_bar(bars: list[Bar], s: Setup) -> tuple[int | None, str]:
    """Index of the first bar after the setup is known whose High exceeds the level; or why none."""
    for k, b in enumerate(bars):
        if b.timestamp_utc < s.known_utc:
            continue
        if b.timestamp_utc >= s.expires_utc:
            return None, "expired"
        if b.high > s.level:
            return k, ""
        if b.close < s.stop:
            return None, "closed_below_reference_low"
    return None, "expired"


def _quote_window(s: Setup, close: datetime, p: IntrabarParams) -> tuple[datetime, datetime]:
    return s.known_utc - timedelta(seconds=MAX_QUOTE_AGE_S), min(s.expires_utc + p.max_hold + EXIT_SLACK, close)


def first_trigger(s: Setup, bars: list[Bar], quotes: list[Quote] | None) -> tuple[datetime | None, str, int | None]:
    """When the setup could first have triggered: (time, why-not, OHLC trigger bar index)."""
    k, why = _trigger_bar(bars, s)
    if quotes is None:
        return (bars[k].timestamp_utc if k is not None else None), why, k
    # a completed bar closing below the reference Low voids the setup from its end on
    void_at = next((b.timestamp_utc + BAR_LENGTH for b in bars
                   if s.known_utc <= b.timestamp_utc < s.expires_utc and b.close < s.stop), None)
    for q in quotes:
        if q.t < s.known_utc:
            continue
        if void_at is not None and q.t >= void_at:
            return None, "closed_below_reference_low", k
        if q.t >= s.expires_utc:
            break
        if q.state == EXECUTABLE and q.bid > s.level:
            return q.t, "", k
    return None, "expired", k


def simulate_nbbo(s: Setup, t_trig: datetime, bars: list[Bar], quotes: list[Quote], cfg: ExecConfig,
                  p: IntrabarParams, risk: RiskConfig) -> Result:
    """Quote-driven proxy: entry at the Ask after latency, stop and exits on fresh executable Bids."""
    close = session_windows(date.fromisoformat(s.trading_date))[s.session].end_utc
    r = Result(s.setup_id, s.symbol, s.trading_date, s.session, "nbbo_proxy", "proxy", "rejected",
               trigger_utc=t_trig.isoformat(), stop=s.stop)
    times = [q.t for q in quotes]
    q0 = _prevailing(quotes, times, t_trig)
    bad = _rejection(q0, t_trig, cfg, check_spread=True)
    if bad or q0 is None:
        r.outcome, r.reason = "non_fill", f"at_trigger_{bad}"
        return r
    limit = q0.ask * (1 + p.limit_offset_bps / 10_000)
    if limit - s.stop <= 0:
        r.reason = "nonpositive_initial_risk"
        return r
    qty = math.floor(min(risk.risk_per_trade_usd / (limit - s.stop), risk.account_usd * risk.max_notional_frac / limit))
    if qty < 1:
        r.reason = "size_below_one_share"
        return r
    arrive = t_trig + cfg.latency
    buys, misses = _execute(quotes, times, "buy", qty, arrive, arrive + cfg.entry_timeout, cfg, limit, check_spread=True)
    if not buys:
        r.outcome, r.reason = "non_fill", f"timeout_{misses.most_common(1)[0][0] if misses else 'no_quote'}"
        return r
    filled = sum(n for _, _, n in buys)
    entry = sum(px * n for _, px, n in buys) / filled
    first, last = buys[0][0], buys[-1][0]
    if entry - s.stop <= 0:
        r.notes.append("entry_at_or_below_stop")
    # exit triggers: stop on a fresh executable Bid; red candle at its completion; safety deadlines
    red = next((b.timestamp_utc + BAR_LENGTH for b in bars
                if b.timestamp_utc >= first and b.close < b.open), None)
    deadline = min(first + p.max_hold, close - p.flatten_before_close)
    trig, why = deadline, "max_hold" if first + p.max_hold <= close - p.flatten_before_close else "session_end"
    if red is not None and red < trig:
        trig, why = red, "red_candle"
    for q in quotes[bisect.bisect_right(times, last):]:
        if q.t > trig or (q.t == trig and why != "red_candle"):
            break
        if _rejection(q, q.t, cfg, check_spread=False) is None and q.bid <= s.stop:
            trig, why = q.t, "stop"  # at equal times the stop takes priority over the red candle
            break
    if any(q.t == last and q.state == EXECUTABLE and q.bid <= s.stop for q in quotes):
        r.sequencing = "uncertain"  # a stop-level Bid shares the fill's timestamp: their order is unknown
        r.notes.append("stop_quote_at_entry_timestamp")
    until = min(trig + EXIT_SLACK, close)
    sells, _ = _execute(quotes, times, "sell", filled, trig + cfg.latency, until, cfg, None, check_spread=False)
    return _book(r, entry, filled, qty, first, why, trig, sells, until, s, cfg)


def simulate_ohlc(s: Setup, k: int, bars: list[Bar], cfg: ExecConfig, p: IntrabarParams, risk: RiskConfig,
                  cost_bps: float) -> Result:
    """1-minute OHLC approximation. Labelled as such; no intrabar order is known."""
    close = session_windows(date.fromisoformat(s.trading_date))[s.session].end_utc
    b = bars[k]
    r = Result(s.setup_id, s.symbol, s.trading_date, s.session, "ohlc_approx", "approximate", "rejected",
               trigger_utc=b.timestamp_utc.isoformat(), stop=s.stop)
    up, down = 1 + cost_bps / 10_000, 1 - cost_bps / 10_000
    entry = max(b.open, s.level) * up  # never the reference High itself
    if entry - s.stop <= 0:
        r.reason = "nonpositive_initial_risk"
        return r
    qty = math.floor(min(risk.risk_per_trade_usd / (entry - s.stop), risk.account_usd * risk.max_notional_frac / entry,
                         p.ohlc_volume_share * b.volume))
    if qty < 1:
        r.reason = "size_below_one_share"
        return r
    first = b.timestamp_utc  # the fill time inside the trigger minute is unknown
    deadline = min(first + p.max_hold, close - p.flatten_before_close)
    why, trig, px, at = "", deadline, math.nan, deadline
    if b.low <= s.stop:  # same minute as the entry: the order of the two is unknown; assume the worst
        r.sequencing = "uncertain"
        r.notes.append("same_minute_entry_and_stop")
        why, trig, px, at = "stop", b.timestamp_utc, s.stop * down, b.timestamp_utc + BAR_LENGTH
    else:
        prev_t = b.timestamp_utc
        pending_red: datetime | None = None
        for m in bars[k + 1 :]:
            if m.timestamp_utc - prev_t > BAR_LENGTH:
                r.notes.append("missing_bars_while_held")
            prev_t = m.timestamp_utc
            if pending_red is not None:  # the next available bar after a red candle: sell at its open
                why, trig, px, at = "red_candle", pending_red, m.open * down, m.timestamp_utc
                break
            if m.timestamp_utc >= deadline:
                why = "max_hold" if first + p.max_hold <= close - p.flatten_before_close else "session_end"
                trig, px, at = deadline, m.open * down, m.timestamp_utc
                break
            if m.low <= s.stop:  # gap below the stop: the open, not the stop
                why, trig, px, at = "stop", m.timestamp_utc, min(m.open, s.stop) * down, m.timestamp_utc
                break
            if m.close < m.open:
                pending_red = m.timestamp_utc + BAR_LENGTH
        if not why:
            why = "red_candle" if pending_red is not None else (
                "max_hold" if first + p.max_hold <= close - p.flatten_before_close else "session_end")
            trig = pending_red or deadline
    if math.isnan(px):  # no later bar to price the exit: never invented, the shares stay unsold
        r.notes.append("no_bar_to_price_exit")
        return _book(r, entry, qty, qty, first, why, trig, [], close, s, cfg)
    return _book(r, entry, qty, qty, first, why, trig, [(at, px, qty)], at, s, cfg)


def _book(r: Result, entry: float, filled: int, requested: int, first: datetime, why: str, trig: datetime,
          sells: list[tuple[datetime, float, int]], until: datetime, s: Setup, cfg: ExecConfig) -> Result:
    sold = sum(n for _, _, n in sells)
    proceeds = sum(px * n for _, px, n in sells)
    net = proceeds - entry * sold - _fees(proceeds, sold, cfg)
    r.outcome = "traded"
    r.entry_first_fill_utc, r.entry_price, r.qty = first.isoformat(), entry, filled
    r.exit_reason, r.exit_trigger_utc = why, trig.isoformat()
    r.exit_last_fill_utc = (sells[-1][0] if sells else until).isoformat()
    r.exit_qty, r.remaining_qty, r.exit_complete = sold, filled - sold, sold == filled
    r.exit_price = proceeds / sold if sold else math.nan
    r.realized_net_usd = net
    r.initial_risk_per_share = entry - s.stop
    if r.exit_complete:
        r.net_usd = net
        r.r_multiple = net / ((entry - s.stop) * filled) if entry - s.stop > 0 else None
        r.busy_until_utc = r.exit_last_fill_utc
    else:
        r.busy_until_utc = session_windows(date.fromisoformat(s.trading_date))[s.session].end_utc.isoformat()
    if filled < requested:
        r.notes.append("partial_entry")
    return r


# ---------- portfolio ----------

@dataclass(slots=True)
class _Day:
    entries: int = 0
    net: float = 0.0
    losses_in_row: int = 0


def run_portfolio(setups: Iterable[Setup], bars: Mapping[tuple[str, str, str], list[Bar]], index: QuoteIndex | None,
                  cfg: ExecConfig, p: IntrabarParams = IntrabarParams(), risk: RiskConfig = RiskConfig(),
                  ohlc_cost_bps: float | None = None) -> list[Result]:
    """Chronological: one position at a time, the existing daily limits, a setup consumed once.
    Quotes are read when needed and not kept: only trigger times are held for all setups."""
    cost = p.ohlc_cost_bps if ohlc_cost_bps is None else ohlc_cost_bps
    events: list[tuple[datetime, str, Setup, tuple[datetime, datetime] | None, int | None, str]] = []
    out: list[Result] = []
    for s in setups:
        key = (s.symbol, s.trading_date, s.session)
        close = session_windows(date.fromisoformat(s.trading_date))[s.session].end_utc
        a, b = _quote_window(s, close, p)
        covered = index is not None and index.covers(s.symbol, a, b)
        quotes = index.load(s.symbol, a, b) if covered else None  # type: ignore[union-attr]
        t, why, k = first_trigger(s, bars[key], quotes)
        del quotes
        if t is None:
            out.append(Result(s.setup_id, s.symbol, s.trading_date, s.session,
                              "nbbo_proxy" if covered else "ohlc_approx",
                              "proxy" if covered else "approximate",
                              "invalidated" if why == "closed_below_reference_low" else "no_trigger", why))
            continue
        events.append((t, s.setup_id, s, (a, b) if covered else None, k, "nbbo_proxy" if covered else "ohlc_approx"))
    days: dict[str, _Day] = defaultdict(_Day)
    busy: datetime | None = None
    for t, _, s, span, k, mode in sorted(events, key=lambda e: (e[0], e[1])):
        day = days[s.trading_date]
        close = session_windows(date.fromisoformat(s.trading_date))[s.session].end_utc
        skip = ("after_entry_cutoff" if t > close - p.entry_cutoff_before_close else
                "position_open" if busy and t < busy else  # consumed: never re-armed after the exit
                "daily_entry_limit" if day.entries >= risk.max_entries_per_day else
                "daily_loss_limit" if day.net <= -risk.daily_loss_limit_usd else
                "loss_streak_pause" if day.losses_in_row >= risk.max_consecutive_losses else None)
        if skip:
            out.append(Result(s.setup_id, s.symbol, s.trading_date, s.session, mode,
                              "proxy" if mode == "nbbo_proxy" else "approximate", "skipped", skip, t.isoformat()))
            continue
        bs = bars[(s.symbol, s.trading_date, s.session)]
        res = (simulate_nbbo(s, t, bs, index.load(s.symbol, *span), cfg, p, risk)  # type: ignore[union-attr]
               if span is not None
               else simulate_ohlc(s, k, bs, cfg, p, risk, cost))  # type: ignore[arg-type]
        out.append(res)
        if res.outcome != "traded":
            continue
        busy = datetime.fromisoformat(res.busy_until_utc)
        pnl = res.realized_net_usd if res.exit_complete else -res.entry_price * res.remaining_qty
        day.entries += 1
        day.net += pnl
        day.losses_in_row = day.losses_in_row + 1 if pnl < 0 else 0
    return out


# ---------- summary ----------

def _drawdown(pnls: list[float]) -> float:
    peak = cum = dd = 0.0
    for x in pnls:
        cum += x
        peak = max(peak, cum)
        dd = max(dd, peak - cum)
    return dd


def summarize(results: list[Result], setups: int) -> dict[str, object]:
    traded = [r for r in results if r.outcome == "traded"]
    done = sorted((r for r in traded if r.exit_complete), key=lambda r: r.entry_first_fill_utc)
    pnl = [float(r.net_usd) for r in done]  # type: ignore[arg-type]
    rs = [r.r_multiple for r in done if r.r_multiple is not None]
    wins, losses = [x for x in pnl if x > 0], [x for x in pnl if x <= 0]
    per_day: dict[tuple[str, str], int] = Counter((r.symbol, r.trading_date) for r in traded)
    return {
        "setups_detected": setups,
        "breakout_signals": sum(1 for r in results if r.outcome not in ("no_trigger", "invalidated")),
        "no_trigger": sum(1 for r in results if r.outcome == "no_trigger"),
        "invalidated_before_trigger": sum(1 for r in results if r.outcome == "invalidated"),
        "skipped": dict(Counter(r.reason for r in results if r.outcome == "skipped")),
        "rejected": dict(Counter(r.reason for r in results if r.outcome == "rejected")),
        "non_fill": dict(Counter(r.reason for r in results if r.outcome == "non_fill")),
        "entries": len(traded),
        "completed_trades": len(done),
        "incomplete_exits": sum(1 for r in traded if not r.exit_complete),
        "same_symbol_reentries": sum(n - 1 for n in per_day.values() if n > 1),
        "by_mode": dict(Counter(r.mode for r in traded)),
        "sequencing": dict(Counter(r.sequencing for r in traded)),
        "reliable_sequencing_trades": 0,  # no trade prints are cached
        "exit_reasons": dict(Counter(r.exit_reason for r in traded)),
        "win_rate": len(wins) / len(pnl) if pnl else None,
        "avg_winner_usd": fmean(wins) if wins else None,
        "avg_loser_usd": fmean(losses) if losses else None,
        "mean_r": fmean(rs) if rs else None,
        "median_r": median(rs) if rs else None,
        "net_usd": sum(pnl),
        "max_drawdown_usd": _drawdown(pnl),
        "profit_factor": sum(wins) / -sum(losses) if losses and sum(losses) < 0 else None,
        "notes": dict(Counter(n for r in traded for n in r.notes)),
    }


def sha256_files(paths: Iterable[Path]) -> str:
    h = hashlib.sha256()
    for f in sorted(paths):
        h.update(f.as_posix().encode())
        h.update(hashlib.sha256(f.read_bytes()).digest())
    return h.hexdigest()


def result_rows(results: list[Result]) -> list[dict[str, object]]:
    return [{**asdict(r), "notes": ";".join(r.notes)} for r in results]


def scenarios() -> dict[str, tuple[ExecConfig, float]]:
    """Primary and predeclared stress execution assumptions: (NBBO config, OHLC cost per side in bps)."""
    return {"base": (SCENARIOS["base"], IntrabarParams().ohlc_cost_bps),
            "stress": (SCENARIOS["stress"], STRESS_OHLC_COST_BPS)}


# ---------- in-sample research run (read-only inputs, separate output folder) ----------

def _inputs(dataset: Path, days: set[str]) -> list[Path]:
    sip = [f for f in (dataset / "cache" / "sip").glob("*_*_*.csv.gz") if f.name[:10] in days]
    return [dataset / "manifest.json", dataset / "references.csv.gz", dataset / "breakout_matches.csv",
            *sorted(sip), *sorted((dataset / "cache" / "backtest_quotes").glob("*.jsonl.gz"))]


def fetch_missing(setups: Iterable[Setup], bars_by: Mapping[tuple[str, str, str], list[Bar]], index: QuoteIndex,
                  cache: Path, source: object, p: IntrabarParams = IntrabarParams()) -> dict[str, int]:
    """Download SIP quotes for setups that broke out on 1-minute bars but lack quote coverage, into
    ``cache`` (a research cache outside the dataset). A setup whose bars never exceed the reference
    High cannot trigger on quotes either, so it needs none."""
    cache.mkdir(parents=True, exist_ok=True)
    done = failed = 0
    for st in setups:
        close = session_windows(date.fromisoformat(st.trading_date))[st.session].end_utc
        a, b = _quote_window(st, close, p)
        if index.covers(st.symbol, a, b) or first_trigger(st, bars_by[(st.symbol, st.trading_date, st.session)],
                                                          None)[0] is None:
            continue
        path = cache / f"{st.symbol}_{a:%Y%m%dT%H%M%S}_{b:%H%M%S}.jsonl.gz"
        try:
            rows = list(source.iter_quotes(st.symbol, "sip", a, b))  # type: ignore[attr-defined]
        except (EntitlementError, AuthenticationError):
            raise  # never silently replace SIP: stop the run
        except ProviderError:  # recorded, never filled in; the setup stays OHLC-approximated
            failed += 1
            continue
        tmp = path.with_suffix(".tmp")
        with gzip.open(tmp, "wt", encoding="utf-8") as fh:
            fh.writelines(json.dumps(r, sort_keys=True) + "\n" for r in rows)
        tmp.replace(path)
        index.files[st.symbol].append((a, b, path))
        done += 1
    return {"windows_fetched": done, "windows_failed": failed}


def run_research(dataset: Path, out_dir: Path, sample: str = "in_sample", log=print,  # noqa: ANN001
                 quote_cache: Path | None = None, source: object | None = None,
                 sessions: tuple[str, ...] = EXTENDED_SESSIONS) -> dict[str, object]:
    """Detect setups on every in-sample session and backtest both variants under the base and the
    predeclared stress assumptions. Reads the dataset and its quote cache, never writing to either.
    ``quote_cache`` is an extra, research-only quote cache outside the dataset; with ``source`` the
    missing setup windows are downloaded into it first."""
    from . import research

    if sample != research.IN_SAMPLE:
        raise ValueError("the Bull Flag intrabar strategy is exploratory: in-sample only")
    manifest = json.loads((dataset / "manifest.json").read_text(encoding="utf-8"))
    days = research.sample_days(manifest, sample)
    before = sha256_files(_inputs(dataset, set(days)))
    as_of = datetime.fromisoformat(manifest["as_of_utc"])
    scan = research.ScanParams(**manifest["scan_params"])
    refs = research.load_references(dataset)
    index = QuoteIndex(dataset / "cache" / "backtest_quotes", *([quote_cache] if quote_cache else []))
    p = IntrabarParams()
    fetched = {"windows_fetched": 0, "windows_failed": 0}
    if not set(sessions) <= set(EXTENDED_SESSIONS):
        raise ValueError(f"sessions must be among {EXTENDED_SESSIONS}")
    missing: list[str] = []
    results: dict[tuple[str, str], list[Result]] = defaultdict(list)
    counts: Counter[str] = Counter()
    covered: Counter[str] = Counter()
    setup_rows: list[dict[str, object]] = []
    for d in days:  # one trading day at a time: its bars and quotes are released before the next day
        windows = session_windows(date.fromisoformat(d))
        setups: list[Setup] = []
        bars_by: dict[tuple[str, str, str], list[Bar]] = {}
        for session in sessions:  # a session left out is neither detected, fetched nor traded
            bars = research.load_session_bars(dataset, d, session, as_of)
            if bars is None:
                missing.append(f"{d} {session}")
                continue
            r = refs.get((d, session), {})
            w = windows[session]
            rank = research.rank_lookup(research.rank_session(w, bars, r, research.RankParams.from_scan(scan)).snapshots)
            for sym in sorted(x for x in bars if r.get(x, 0) > 0):
                ctx = research.bar_context(bars[sym], r[sym], w, scan)
                found = detect_setups(sym, bars[sym], w, p, gate={t: bool(c["candidate_gate"]) for t, c in ctx.items()})
                for st in found:
                    st.top5_rank = rank.get((sym, st.setup_bar_start_utc.isoformat()))
                if found:
                    bars_by[(sym, d, session)] = bars[sym]
                    setups += found
            del bars
        if source is not None and quote_cache is not None:
            got = fetch_missing(setups, bars_by, index, quote_cache, source, p)
            fetched = {k: fetched[k] + got[k] for k in fetched}
        cover = {st.setup_id: index.covers(st.symbol, *_quote_window(st, windows[st.session].end_utc, p))
                 for st in setups}
        # positions are flat by each session's end, so per-day portfolios equal one run over all days
        for k, sts in {"bf_intrabar": setups, "top5_bf_intrabar": [x for x in setups if x.top5_rank is not None]}.items():
            counts[k] += len(sts)
            covered[k] += sum(cover[x.setup_id] for x in sts)
            for name, (cfg, cost) in scenarios().items():
                results[(k, name)] += run_portfolio(sts, bars_by, index, cfg, p, ohlc_cost_bps=cost)
        setup_rows += [{"setup_id": x.setup_id, "symbol": x.symbol, "trading_date": x.trading_date,
                        "session": x.session, "known_utc": x.known_utc.isoformat(),
                        "expires_utc": x.expires_utc.isoformat(), "level": x.level, "stop": x.stop,
                        "top5_rank": x.top5_rank, "nbbo_covered": cover[x.setup_id], **x.detail} for x in setups]
        index.forget()
        log(f"{d}: {counts['bf_intrabar']} setups so far; quotes {fetched}")
    out_dir.mkdir(parents=True, exist_ok=True)
    summary: dict[str, object] = {}
    for k in STRATEGIES:
        entry: dict[str, object] = {"label": LABELS[k], "quote_coverage": {"setups": counts[k],
                                                                           "nbbo_covered": covered[k]}}
        for name in scenarios():
            res = results[(k, name)]
            entry[name] = summarize(res, counts[k])
            research.write_table(out_dir / f"{k}_{name}_results.csv", result_rows(res))  # type: ignore[arg-type]
        summary[k] = entry
    research.write_table(out_dir / "setups.csv.gz", setup_rows)
    after = sha256_files(_inputs(dataset, set(days)))
    return {"sample": sample, "days": len(days), "sessions": list(sessions), "sessions_missing_bars": missing, "orders_placed": 0,
            "network_requests": getattr(source, "request_count", 0), "research_quote_cache": fetched,
            "trade_prints_cached": False,
            "params": {k: (str(v) if isinstance(v, timedelta) else v) for k, v in asdict(p).items()},
            "stress": {"nbbo": "latency 2 s, 50% of displayed size, 10 bps adverse",
                       "ohlc_cost_bps_per_side": STRESS_OHLC_COST_BPS},
            "inputs_sha256_before": before, "inputs_sha256_after": after, "inputs_unchanged": before == after,
            "strategies": summary}


__all__ = ["EXTENDED_SESSIONS", "IntrabarParams", "run_research", "LABELS", "QuoteIndex", "Result", "STRATEGIES", "Setup",
           "detect_setups", "find_setup", "first_trigger", "run_portfolio", "scenarios", "sha256_files",
           "simulate_nbbo", "simulate_ohlc", "summarize"]
