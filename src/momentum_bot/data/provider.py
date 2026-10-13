"""Provider-neutral market-data types. Alpaca specifics live in alpaca_historical.py."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

Feed = Literal["sip", "iex"]


@dataclass(frozen=True, slots=True)
class Bar:
    symbol: str
    feed: str
    timestamp_utc: datetime  # bar start, timezone-aware UTC
    open: float
    high: float
    low: float
    close: float
    volume: int
    trade_count: int | None = None
    vwap: float | None = None


@dataclass(frozen=True, slots=True)
class BarsRequest:
    symbols: tuple[str, ...]
    feed: Feed
    start_utc: datetime
    end_utc: datetime
    timeframe: str = "1Min"
    adjustment: str = "raw"


class ProviderError(Exception):
    def __init__(self, message: str, *, status: int | None = None, feed: str | None = None) -> None:
        super().__init__(message)
        self.status = status
        self.feed = feed


class AuthenticationError(ProviderError):
    """Credentials missing or rejected."""


class EntitlementError(ProviderError):
    """The account's subscription does not permit the requested feed or time range."""


class BarsProvider(Protocol):
    name: str

    def get_bars(self, request: BarsRequest) -> list[Bar]: ...
