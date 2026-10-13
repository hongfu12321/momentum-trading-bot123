"""Deterministic synthetic bars for offline tests (no credentials, no network)."""

from __future__ import annotations

from datetime import date, datetime, time, timezone

import pytest

from momentum_bot.data.market_calendar import ET
from momentum_bot.data.provider import Bar, BarsRequest, EntitlementError

PREV, DAY = date(2024, 3, 7), date(2024, 3, 8)
NOW = datetime(2024, 3, 9, 12, tzinfo=timezone.utc)


def et(d: date, hhmm: str) -> datetime:
    h, m = map(int, hhmm.split(":"))
    return datetime.combine(d, time(h, m), tzinfo=ET).astimezone(timezone.utc)


def bar(feed: str, d: date, hhmm: str, close: float, high: float, volume: int, symbol: str = "TEST") -> Bar:
    return Bar(symbol, feed, et(d, hhmm), close, high, close - 0.01, close, volume)


def scenario() -> list[Bar]:
    """SIP sees a premarket gap with 110k cumulative volume; IEX sees ~3% of it and misses 04:02."""
    bars = [bar("sip", PREV, "15:59", 2.00, 2.00, 1000), bar("iex", PREV, "15:59", 2.00, 2.00, 50)]
    for minute in ("04:00", "04:01", "04:02", "04:03", "04:04", "04:05"):
        bars.append(bar("sip", DAY, minute, 2.05, 2.06, 10_000))
        if minute != "04:02":
            bars.append(bar("iex", DAY, minute, 2.05, 2.06, 300))
    bars.append(bar("sip", DAY, "04:06", 2.40, 2.45, 50_000))
    bars.append(bar("iex", DAY, "04:06", 2.40, 2.44, 1_500))
    return bars


class FakeProvider:
    name = "fake"

    def __init__(self, bars: list[Bar], blocked_feeds: frozenset[str] = frozenset()) -> None:
        self.bars = bars
        self.blocked = blocked_feeds
        self.requests: list[BarsRequest] = []

    def get_bars(self, request: BarsRequest) -> list[Bar]:
        self.requests.append(request)
        if request.feed in self.blocked:
            raise EntitlementError("subscription does not permit querying recent SIP data", status=403, feed=request.feed)
        return [
            b for b in self.bars
            if b.feed == request.feed and b.symbol in request.symbols
            and request.start_utc <= b.timestamp_utc <= request.end_utc
        ]


@pytest.fixture
def provider() -> FakeProvider:
    return FakeProvider(scenario())
