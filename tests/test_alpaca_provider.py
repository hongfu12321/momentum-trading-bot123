import json
import urllib.parse
from datetime import datetime, timezone
from pathlib import Path

import pytest

from momentum_bot.data.alpaca_historical import AlpacaHistoricalProvider, HttpResponse
from momentum_bot.data.provider import AuthenticationError, BarsRequest, EntitlementError, ProviderError

FIXTURES = Path(__file__).parent / "fixtures"
REQ = BarsRequest(("SOUN",), "sip", datetime(2024, 3, 8, 9, tzinfo=timezone.utc), datetime(2024, 3, 9, 1, tzinfo=timezone.utc))


class Script:
    def __init__(self, *responses: HttpResponse) -> None:
        self.responses = list(responses)
        self.urls: list[str] = []

    def __call__(self, url, headers):  # noqa: ANN001, ANN204
        self.urls.append(url)
        return self.responses.pop(0)


def ok(name: str) -> HttpResponse:
    return HttpResponse(200, (FIXTURES / name).read_bytes())


def make(script: Script) -> AlpacaHistoricalProvider:
    return AlpacaHistoricalProvider("k", "s", http_get=script, sleep=lambda s: None, clock=lambda: 0.0)


def test_paginates_and_sends_explicit_feed_and_raw_adjustment() -> None:
    script = Script(ok("alpaca_bars_page1.json"), ok("alpaca_bars_page2.json"))
    bars = make(script).get_bars(REQ)
    assert [b.timestamp_utc.isoformat() for b in bars] == [
        "2024-03-08T09:00:00+00:00", "2024-03-08T09:01:00+00:00", "2024-03-08T09:02:00+00:00"
    ]
    assert bars[0].feed == "sip" and bars[0].volume == 1200 and bars[0].trade_count == 9
    first = urllib.parse.parse_qs(urllib.parse.urlparse(script.urls[0]).query)
    assert first["feed"] == ["sip"] and first["adjustment"] == ["raw"] and first["timeframe"] == ["1Min"]
    assert first["start"] == ["2024-03-08T09:00:00Z"]
    assert "page_token" in urllib.parse.parse_qs(urllib.parse.urlparse(script.urls[1]).query)
    assert script.urls[0].startswith("https://data.alpaca.markets/v2/stocks/bars?")


def test_403_is_explicit_entitlement_error() -> None:
    body = json.dumps({"message": "subscription does not permit querying recent SIP data"}).encode()
    with pytest.raises(EntitlementError, match="SIP not permitted"):
        make(Script(HttpResponse(403, body))).get_bars(REQ)


def test_401_is_authentication_error() -> None:
    with pytest.raises(AuthenticationError):
        make(Script(HttpResponse(401, b'{"message":"unauthorized."}'))).get_bars(REQ)


def test_retries_rate_limit_then_succeeds_and_gives_up_eventually() -> None:
    script = Script(HttpResponse(429, b"{}", {"Retry-After": "1"}), ok("alpaca_bars_page2.json"))
    assert len(make(script).get_bars(REQ)) == 1
    failing = Script(*[HttpResponse(503, b"{}")] * 5)
    with pytest.raises(ProviderError, match="HTTP 503"):
        make(failing).get_bars(REQ)


def test_refuses_trading_hosts() -> None:
    for url in ("https://api.alpaca.markets", "https://paper-api.alpaca.markets"):
        with pytest.raises(ValueError):
            AlpacaHistoricalProvider("k", "s", base_url=url)


def test_missing_credentials() -> None:
    with pytest.raises(AuthenticationError):
        AlpacaHistoricalProvider("", "")
