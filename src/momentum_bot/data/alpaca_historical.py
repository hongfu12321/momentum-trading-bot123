"""Alpaca historical stock-bars adapter (market-data API only; no trading endpoints)."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.parse
import urllib.request
from collections.abc import Callable, Mapping
from dataclasses import dataclass, field
from datetime import datetime, timezone

from .provider import AuthenticationError, Bar, BarsRequest, EntitlementError, ProviderError

DATA_BASE_URL = "https://data.alpaca.markets"
ALLOWED_DATA_HOSTS = frozenset({"data.alpaca.markets", "data.sandbox.alpaca.markets"})
BARS_PATH = "/v2/stocks/bars"
PAGE_LIMIT = 10000
RETRYABLE_STATUSES = frozenset({0, 429, 500, 502, 503, 504})


@dataclass(frozen=True, slots=True)
class HttpResponse:
    status: int  # 0 means a transport error (no HTTP response)
    body: bytes
    headers: Mapping[str, str] = field(default_factory=dict)


HttpGet = Callable[[str, Mapping[str, str]], HttpResponse]


def urllib_get(url: str, headers: Mapping[str, str], timeout: float = 30.0) -> HttpResponse:
    request = urllib.request.Request(url, headers=dict(headers), method="GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as resp:
            return HttpResponse(resp.status, resp.read(), dict(resp.headers))
    except urllib.error.HTTPError as exc:
        return HttpResponse(exc.code, exc.read() or b"", dict(exc.headers or {}))
    except (urllib.error.URLError, TimeoutError, ConnectionError) as exc:
        return HttpResponse(0, json.dumps({"message": f"transport error: {exc}"}).encode())


def _error_message(body: bytes) -> str:
    try:
        payload = json.loads(body)
        if isinstance(payload, dict) and "message" in payload:
            return str(payload["message"])
    except (ValueError, UnicodeDecodeError):
        pass
    return body.decode("utf-8", "replace")[:500]


def _iso_z(ts: datetime) -> str:
    return ts.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


class AlpacaHistoricalProvider:
    name = "alpaca"

    def __init__(
        self,
        key_id: str,
        secret_key: str,
        *,
        http_get: HttpGet = urllib_get,
        base_url: str = DATA_BASE_URL,
        max_retries: int = 4,
        min_interval_s: float = 0.35,  # stays under the Basic plan's 200 requests/minute
        sleep: Callable[[float], None] = time.sleep,
        clock: Callable[[], float] = time.monotonic,
    ) -> None:
        host = urllib.parse.urlparse(base_url).hostname
        if host not in ALLOWED_DATA_HOSTS:
            raise ValueError(f"refusing non-market-data host {host!r}; allowed: {sorted(ALLOWED_DATA_HOSTS)}")
        if not key_id or not secret_key:
            raise AuthenticationError("APCA_API_KEY_ID and APCA_API_SECRET_KEY must be set")
        self._headers = {"APCA-API-KEY-ID": key_id, "APCA-API-SECRET-KEY": secret_key, "Accept": "application/json"}
        self._http_get = http_get
        self._base_url = base_url.rstrip("/")
        self._max_retries = max_retries
        self._min_interval_s = min_interval_s
        self._sleep = sleep
        self._clock = clock
        self._last_request: float | None = None
        self.request_count = 0

    @classmethod
    def from_env(cls, **kwargs: object) -> AlpacaHistoricalProvider:
        return cls(os.environ.get("APCA_API_KEY_ID", ""), os.environ.get("APCA_API_SECRET_KEY", ""), **kwargs)  # type: ignore[arg-type]

    def get_bars(self, request: BarsRequest) -> list[Bar]:
        params: dict[str, str] = {
            "symbols": ",".join(request.symbols),
            "timeframe": request.timeframe,
            "start": _iso_z(request.start_utc),
            "end": _iso_z(request.end_utc),
            "feed": request.feed,  # always explicit; never let the API choose a default feed
            "adjustment": request.adjustment,
            "limit": str(PAGE_LIMIT),
            "sort": "asc",
        }
        bars: list[Bar] = []
        while True:
            payload = self._get_json(f"{self._base_url}{BARS_PATH}?{urllib.parse.urlencode(params)}", request.feed)
            for symbol, rows in (payload.get("bars") or {}).items():
                for row in rows:
                    bars.append(
                        Bar(
                            symbol=symbol,
                            feed=request.feed,
                            timestamp_utc=datetime.fromisoformat(row["t"]).astimezone(timezone.utc),
                            open=float(row["o"]),
                            high=float(row["h"]),
                            low=float(row["l"]),
                            close=float(row["c"]),
                            volume=int(row["v"]),
                            trade_count=row.get("n"),
                            vwap=row.get("vw"),
                        )
                    )
            token = payload.get("next_page_token")
            if not token:
                return bars
            params["page_token"] = token

    def _get_json(self, url: str, feed: str) -> dict:
        for attempt in range(self._max_retries + 1):
            self._throttle()
            resp = self._http_get(url, self._headers)
            self.request_count += 1
            if resp.status == 200:
                return json.loads(resp.body)
            message = _error_message(resp.body)
            if resp.status == 401:
                raise AuthenticationError(f"Alpaca rejected credentials: {message}", status=401, feed=feed)
            if resp.status == 403 or "subscription does not permit" in message.lower():
                raise EntitlementError(
                    f"{feed.upper()} not permitted for this account: {message}", status=resp.status, feed=feed
                )
            if resp.status in RETRYABLE_STATUSES and attempt < self._max_retries:
                retry_after = resp.headers.get("Retry-After") or resp.headers.get("retry-after")
                self._sleep(float(retry_after) if retry_after and retry_after.isdigit() else 2.0**attempt)
                continue
            raise ProviderError(
                f"Alpaca bars request failed (HTTP {resp.status}): {message}", status=resp.status, feed=feed
            )
        raise AssertionError("unreachable")

    def _throttle(self) -> None:
        now = self._clock()
        if self._last_request is not None:
            wait = self._min_interval_s - (now - self._last_request)
            if wait > 0:
                self._sleep(wait)
                now += wait
        self._last_request = now
