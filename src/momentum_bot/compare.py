"""SIP-vs-IEX comparison: coverage, volume, highs/lows, scanner candidates and breakout signals.

The scanner and breakout rules are research hypotheses from docs/DESIGN.md section 4, used here
only to measure how feed choice changes what would be discovered. They are not a strategy.
"""

from __future__ import annotations

from collections import defaultdict
from collections.abc import Iterable, Mapping
from dataclasses import asdict, dataclass
from datetime import date, datetime
from statistics import fmean

from .data.coverage import missing_intervals
from .data.market_calendar import AFTERHOURS, PREMARKET, REGULAR, SessionWindow
from .data.normalize import BAR_LENGTH, SessionBar
from .data.provider import Bar

Key = tuple[str, date, str]  # symbol, trading_date, session


@dataclass(frozen=True, slots=True)
class ScanParams:
    min_price: float = 1.0
    max_price: float = 20.0
    premarket_min_change: float = 0.10
    afterhours_min_change: float = 0.05
    min_session_volume: int = 100_000
    breakout_volume_multiple: float = 2.0
    breakout_lookback: int = 5
    # The first after-hours 1m SIP bar carries the closing auction and late regular-session prints
    # (tens of times normal volume); count it as zero volume for after-hours gating and breakouts.
    exclude_closing_auction_bar: bool = True


@dataclass(frozen=True, slots=True)
class Event:
    kind: str  # "candidate" (first bar meeting scan rules) or "breakout"
    feed: str
    symbol: str
    trading_date: date
    session: str
    bar_start_utc: datetime
    observed_at_utc: datetime  # bar close: the earliest time the completed bar is known
    price: float
    change_vs_ref: float | None
    cumulative_volume: int
    candidate_gate: bool  # scan rules held at this bar

    def __post_init__(self) -> None:
        if self.observed_at_utc < self.bar_start_utc + BAR_LENGTH:
            raise ValueError("an event cannot be observed before its bar completes")

    def row(self) -> dict[str, object]:
        return asdict(self)


def group_bars(bars: Iterable[SessionBar]) -> dict[str, dict[Key, list[Bar]]]:
    out: dict[str, dict[Key, list[Bar]]] = defaultdict(lambda: defaultdict(list))
    for sb in bars:
        out[sb.bar.feed][(sb.bar.symbol, sb.trading_date, sb.session)].append(sb.bar)
    for per_feed in out.values():
        for rows in per_feed.values():
            rows.sort(key=lambda b: b.timestamp_utc)
    return out


def regular_closes(grouped: Mapping[Key, list[Bar]]) -> dict[tuple[str, date], float]:
    """Last regular-session 1m close per (symbol, date), from the same feed.

    This approximates, but is not, the official closing-auction price.
    """
    return {(sym, d): rows[-1].close for (sym, d, s), rows in grouped.items() if s == REGULAR and rows}


def reference_close(
    symbol: str, d: date, session: str, closes: Mapping[tuple[str, date], float], prev_day: Mapping[date, date]
) -> float | None:
    if session == PREMARKET:
        return closes.get((symbol, prev_day[d]))
    return closes.get((symbol, d))


def scan_session(
    feed: str, key: Key, bars: list[Bar], ref_close: float | None, params: ScanParams,
    session_start: datetime | None = None,
) -> tuple[Event | None, list[Event]]:
    symbol, d, session = key
    skip_auction = params.exclude_closing_auction_bar and session == AFTERHOURS and session_start is not None
    vols = [0 if skip_auction and b.timestamp_utc == session_start else b.volume for b in bars]
    min_change = params.premarket_min_change if session == PREMARKET else params.afterhours_min_change
    candidate: Event | None = None
    breakouts: list[Event] = []
    cum_vol = 0
    session_high = float("-inf")
    for i, bar in enumerate(bars):
        cum_vol += vols[i]
        change = bar.close / ref_close - 1 if ref_close else None
        in_band = params.min_price <= bar.close <= params.max_price
        gate = in_band and change is not None and change >= min_change and cum_vol >= params.min_session_volume

        def event(kind: str) -> Event:
            return Event(kind, feed, symbol, d, session, bar.timestamp_utc, bar.timestamp_utc + BAR_LENGTH,
                         bar.close, change, cum_vol, gate)

        if gate and candidate is None:
            candidate = event("candidate")
        if i >= params.breakout_lookback and in_band:
            mean_vol = fmean(vols[i - params.breakout_lookback : i])
            if bar.close > session_high and vols[i] >= params.breakout_volume_multiple * mean_vol > 0:
                breakouts.append(event("breakout"))
        session_high = max(session_high, bar.high)
    return candidate, breakouts


def _bps(a: float, b: float) -> float:
    return (a - b) / b * 10_000 if b else 0.0


def compare_session(window: SessionWindow, symbol: str, sip: list[Bar], iex: list[Bar]) -> dict[str, object]:
    sip_by_t = {b.timestamp_utc: b for b in sip}
    iex_by_t = {b.timestamp_utc: b for b in iex}
    both = sorted(sip_by_t.keys() & iex_by_t.keys())
    sip_vol = sum(b.volume for b in sip)
    iex_vol = sum(b.volume for b in iex)
    matched_sip_vol = sum(sip_by_t[t].volume for t in both)
    matched_iex_vol = sum(iex_by_t[t].volume for t in both)
    sip_high = max((b.high for b in sip), default=None)
    iex_high = max((b.high for b in iex), default=None)
    sip_low = min((b.low for b in sip), default=None)
    iex_low = min((b.low for b in iex), default=None)
    pairs = [(sip_by_t[t], iex_by_t[t]) for t in both]
    return {
        "symbol": symbol,
        "trading_date": window.trading_date.isoformat(),
        "session": window.name,
        "expected_minutes": window.minutes,
        "sip_bar_minutes": len(sip_by_t),
        "iex_bar_minutes": len(iex_by_t),
        "both_minutes": len(both),
        "sip_only_minutes": len(sip_by_t.keys() - iex_by_t.keys()),
        "iex_only_minutes": len(iex_by_t.keys() - sip_by_t.keys()),  # unexpected: IEX trades are part of SIP
        "sip_volume": sip_vol,
        "iex_volume": iex_vol,
        "iex_volume_share": iex_vol / sip_vol if sip_vol else None,
        "matched_minute_iex_volume_share": matched_iex_vol / matched_sip_vol if matched_sip_vol else None,
        "sip_session_high": sip_high,
        "iex_session_high": iex_high,
        "session_high_diff_bps": _bps(iex_high, sip_high) if sip_high and iex_high else None,
        "sip_session_low": sip_low,
        "iex_session_low": iex_low,
        "session_low_diff_bps": _bps(iex_low, sip_low) if sip_low and iex_low else None,
        "matched_mean_abs_high_diff_bps": fmean(abs(_bps(i.high, s.high)) for s, i in pairs) if pairs else None,
        "matched_mean_abs_low_diff_bps": fmean(abs(_bps(i.low, s.low)) for s, i in pairs) if pairs else None,
        "matched_mean_abs_close_diff_bps": fmean(abs(_bps(i.close, s.close)) for s, i in pairs) if pairs else None,
        "matched_iex_high_above_sip": sum(1 for s, i in pairs if i.high > s.high),
        "matched_iex_low_below_sip": sum(1 for s, i in pairs if i.low < s.low),
    }


def missing_interval_rows(window: SessionWindow, symbol: str, feed: str, bars: list[Bar]) -> list[dict[str, object]]:
    return [
        {
            "symbol": symbol,
            "feed": feed,
            "trading_date": window.trading_date.isoformat(),
            "session": window.name,
            "missing_start_utc": start.isoformat(),
            "missing_end_utc": end.isoformat(),
            "minutes": int((end - start).total_seconds() // 60),
        }
        for start, end in missing_intervals(window, (b.timestamp_utc for b in bars))
    ]


def match_events(sip: list[Event], iex: list[Event], *, by_minute: bool) -> list[dict[str, object]]:
    """Pair events across feeds. Candidates match per session; breakouts match on the same bar minute."""

    def key(e: Event) -> tuple:
        base = (e.symbol, e.trading_date, e.session)
        return (*base, e.bar_start_utc) if by_minute else base

    s_map = {key(e): e for e in sip}
    i_map = {key(e): e for e in iex}
    rows: list[dict[str, object]] = []
    for k in sorted(s_map.keys() | i_map.keys()):
        s, i = s_map.get(k), i_map.get(k)
        ref = s or i
        assert ref is not None
        status = "both" if s and i else ("sip_only" if s else "iex_only")
        lag = (i.bar_start_utc - s.bar_start_utc).total_seconds() / 60 if s and i else None
        rows.append({
            "kind": ref.kind,
            "symbol": ref.symbol,
            "trading_date": ref.trading_date.isoformat(),
            "session": ref.session,
            "match": status,
            "sip_bar_start_utc": s.bar_start_utc.isoformat() if s else None,
            "iex_bar_start_utc": i.bar_start_utc.isoformat() if i else None,
            "sip_signal_available_utc": s.observed_at_utc.isoformat() if s else None,
            "iex_signal_available_utc": i.observed_at_utc.isoformat() if i else None,
            "sip_price": s.price if s else None,
            "iex_lag_minutes": lag,
            "sip_candidate_gate": s.candidate_gate if s else None,
            "iex_candidate_gate": i.candidate_gate if i else None,
        })
    return rows


def summarize_matches(rows: list[dict[str, object]]) -> dict[str, object]:
    counts = {m: sum(1 for r in rows if r["match"] == m) for m in ("both", "sip_only", "iex_only")}
    sip_total = counts["both"] + counts["sip_only"]
    return {**counts, "sip_total": sip_total, "iex_recall_of_sip": counts["both"] / sip_total if sip_total else None}


