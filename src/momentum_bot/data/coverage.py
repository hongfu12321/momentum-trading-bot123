"""Minute-level coverage and missing-interval detection for a session window."""

from __future__ import annotations

from collections.abc import Iterable
from datetime import datetime, timedelta

from .market_calendar import SessionWindow

MINUTE = timedelta(minutes=1)


def expected_minutes(window: SessionWindow) -> list[datetime]:
    return [window.start_utc + i * MINUTE for i in range(window.minutes)]


def missing_intervals(window: SessionWindow, present: Iterable[datetime]) -> list[tuple[datetime, datetime]]:
    """Contiguous [start, end) runs of minutes in the window with no bar.

    A missing 1m bar usually means no eligible trades printed on that feed, not a data error.
    """
    have = set(present)
    runs: list[tuple[datetime, datetime]] = []
    start: datetime | None = None
    for minute in expected_minutes(window):
        if minute in have:
            if start is not None:
                runs.append((start, minute))
                start = None
        elif start is None:
            start = minute
    if start is not None:
        runs.append((start, window.end_utc))
    return runs
