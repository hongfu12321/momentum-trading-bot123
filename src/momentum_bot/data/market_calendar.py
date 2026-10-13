"""NYSE trading calendar and extended-hours session windows (America/New_York, stored as UTC).

The holiday table is static and deliberately bounded: dates outside COVERED_YEARS raise
instead of being guessed. Extend the tables from the official NYSE holiday schedule.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from zoneinfo import ZoneInfo

ET = ZoneInfo("America/New_York")
COVERED_YEARS = range(2023, 2027)

HOLIDAYS = frozenset(
    date.fromisoformat(d)
    for d in (
        "2023-01-02", "2023-01-16", "2023-02-20", "2023-04-07", "2023-05-29", "2023-06-19",
        "2023-07-04", "2023-09-04", "2023-11-23", "2023-12-25",
        "2024-01-01", "2024-01-15", "2024-02-19", "2024-03-29", "2024-05-27", "2024-06-19",
        "2024-07-04", "2024-09-02", "2024-11-28", "2024-12-25",
        "2025-01-01", "2025-01-09", "2025-01-20", "2025-02-17", "2025-04-18", "2025-05-26",
        "2025-06-19", "2025-07-04", "2025-09-01", "2025-11-27", "2025-12-25",
        "2026-01-01", "2026-01-19", "2026-02-16", "2026-04-03", "2026-05-25", "2026-06-19",
        "2026-07-03", "2026-09-07", "2026-11-26", "2026-12-25",
    )
)
# 13:00 ET regular close. Post-market on these days is modelled as 13:00-17:00 ET.
EARLY_CLOSES = frozenset(
    date.fromisoformat(d)
    for d in (
        "2023-07-03", "2023-11-24",
        "2024-07-03", "2024-11-29", "2024-12-24",
        "2025-07-03", "2025-11-28", "2025-12-24",
        "2026-11-27", "2026-12-24",
    )
)

PREMARKET, REGULAR, AFTERHOURS = "premarket", "regular", "afterhours"
EXTENDED_SESSIONS = (PREMARKET, AFTERHOURS)


class CalendarCoverageError(ValueError):
    pass


@dataclass(frozen=True, slots=True)
class SessionWindow:
    name: str
    trading_date: date
    start_utc: datetime  # inclusive
    end_utc: datetime  # exclusive

    @property
    def minutes(self) -> int:
        return int((self.end_utc - self.start_utc).total_seconds() // 60)

    def contains(self, ts_utc: datetime) -> bool:
        return self.start_utc <= ts_utc < self.end_utc


def _check(d: date) -> None:
    if d.year not in COVERED_YEARS:
        raise CalendarCoverageError(
            f"{d} outside calendar coverage {COVERED_YEARS.start}-{COVERED_YEARS.stop - 1}"
        )


def is_trading_day(d: date) -> bool:
    _check(d)
    return d.weekday() < 5 and d not in HOLIDAYS


def trading_days(start: date, end: date) -> list[date]:
    days, d = [], start
    while d <= end:
        if is_trading_day(d):
            days.append(d)
        d += timedelta(days=1)
    return days


def previous_trading_day(d: date) -> date:
    d -= timedelta(days=1)
    while not is_trading_day(d):
        d -= timedelta(days=1)
    return d


def _utc(d: date, t: time) -> datetime:
    return datetime.combine(d, t, tzinfo=ET).astimezone(timezone.utc)


def session_windows(d: date) -> dict[str, SessionWindow]:
    if not is_trading_day(d):
        return {}
    close = time(13) if d in EARLY_CLOSES else time(16)
    ah_end = time(17) if d in EARLY_CLOSES else time(20)
    return {
        PREMARKET: SessionWindow(PREMARKET, d, _utc(d, time(4)), _utc(d, time(9, 30))),
        REGULAR: SessionWindow(REGULAR, d, _utc(d, time(9, 30)), _utc(d, close)),
        AFTERHOURS: SessionWindow(AFTERHOURS, d, _utc(d, close), _utc(d, ah_end)),
    }
