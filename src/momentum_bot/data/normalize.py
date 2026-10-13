"""Attach ET trading date and session to raw bars; keep only completed, in-session bars."""

from __future__ import annotations

from collections import Counter
from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from datetime import date, datetime, timedelta

from .market_calendar import ET, SessionWindow
from .provider import Bar

BAR_LENGTH = timedelta(minutes=1)


@dataclass(frozen=True, slots=True)
class SessionBar:
    bar: Bar
    trading_date: date
    session: str


def normalize(
    bars: Iterable[Bar],
    windows_by_date: Mapping[date, Mapping[str, SessionWindow]],
    *,
    as_of_utc: datetime,
) -> tuple[list[SessionBar], Counter[str]]:
    """Return session-labelled bars sorted by (feed, symbol, time) plus counts of dropped bars by reason."""
    dropped: Counter[str] = Counter()
    seen: set[tuple[str, str, datetime]] = set()
    out: list[SessionBar] = []
    for bar in bars:
        key = (bar.feed, bar.symbol, bar.timestamp_utc)
        if key in seen:
            dropped["duplicate"] += 1
            continue
        seen.add(key)
        if bar.timestamp_utc + BAR_LENGTH > as_of_utc:
            dropped["incomplete"] += 1
            continue
        d = bar.timestamp_utc.astimezone(ET).date()
        session = next(
            (w.name for w in windows_by_date.get(d, {}).values() if w.contains(bar.timestamp_utc)), None
        )
        if session is None:
            dropped["out_of_session"] += 1
            continue
        out.append(SessionBar(bar, d, session))
    out.sort(key=lambda sb: (sb.bar.feed, sb.bar.symbol, sb.bar.timestamp_utc))
    return out, dropped
