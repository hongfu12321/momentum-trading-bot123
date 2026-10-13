"""Read-only symbol reference lookup on Alpaca's PAPER trading host.

Scope is deliberately tiny: one HTTP method (GET) and one path (/v2/assets) on
paper-api.alpaca.markets. There is no code path to orders, positions or account endpoints, and
live hosts and live-looking keys are refused.
"""

from __future__ import annotations

import os
from typing import Literal

from .alpaca_historical import AlpacaHttp, HttpGet, urllib_get
from .provider import AuthenticationError

PAPER_TRADING_URL = "https://paper-api.alpaca.markets"
PAPER_HOSTS = frozenset({"paper-api.alpaca.markets"})
ASSETS_PATH = "/v2/assets"


class AlpacaPaperAssets:
    def __init__(self, key_id: str, secret_key: str, *, http_get: HttpGet = urllib_get, **http_kwargs: object) -> None:
        if key_id.startswith("AK"):  # Alpaca live keys start with AK, paper keys with PK
            raise AuthenticationError("refusing a live-trading API key; use Alpaca PAPER credentials")
        self._http = AlpacaHttp(key_id, secret_key, base_url=PAPER_TRADING_URL, allowed_hosts=PAPER_HOSTS,
                                http_get=http_get, **http_kwargs)  # type: ignore[arg-type]

    @classmethod
    def from_env(cls, **kwargs: object) -> AlpacaPaperAssets:
        return cls(os.environ.get("APCA_API_KEY_ID", ""), os.environ.get("APCA_API_SECRET_KEY", ""), **kwargs)  # type: ignore[arg-type]

    @property
    def request_count(self) -> int:
        return self._http.request_count

    def list_assets(self, status: Literal["active", "inactive"]) -> list[dict]:
        payload = self._http.get_json(ASSETS_PATH, {"status": status, "asset_class": "us_equity"}, f"assets_{status}")
        if not isinstance(payload, list):
            raise ValueError(f"unexpected /v2/assets payload type {type(payload).__name__}")
        return payload
