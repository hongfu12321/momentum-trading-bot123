from datetime import date, datetime, time, timezone
from pathlib import Path

from conftest import bar
from momentum_bot.data.market_calendar import ET
from momentum_bot.data.provider import Bar, BarsRequest
from momentum_bot.dataset import DatasetConfig, build_dataset
from momentum_bot.dataset_report import write_dataset
from test_universe_provenance import ACTIONS, NASDAQ, OTHER

D6, D7, D8 = date(2024, 3, 6), date(2024, 3, 7), date(2024, 3, 8)
NOW = datetime(2024, 3, 9, 12, tzinfo=timezone.utc)


def daily(symbol: str, d: date, close: float) -> Bar:
    return Bar(symbol, "sip", datetime.combine(d, time(), tzinfo=ET).astimezone(timezone.utc), close, close, close, close, 1000)


def intraday() -> list[Bar]:
    bars = []
    for m in ("04:00", "04:01", "04:02", "04:03", "04:04", "04:05"):  # GAP: +20% on 110k SIP volume
        bars += [bar("sip", D8, m, 2.05, 2.06, 10_000, "GAP"), bar("iex", D8, m, 2.05, 2.06, 300, "GAP")]
    bars += [bar("sip", D8, "04:06", 2.40, 2.45, 50_000, "GAP"), bar("iex", D8, "04:06", 2.40, 2.44, 1500, "GAP")]
    bars += [bar("sip", D8, "05:00", 5.10, 5.10, 200_000, "SPL")]  # post 1:10 reverse split; +2% vs adjusted ref
    bars += [bar("sip", D7, "04:30", 3.00, 3.00, 500, "OLD"), bar("sip", D7, "04:30", 3.00, 3.00, 500, "NEW")]
    return bars


class FakeAlpaca:
    name = "fake"

    def __init__(self) -> None:
        self.request_count = 0
        self.bar_requests: list[BarsRequest] = []
        self.ca_calls = 0
        self.daily = [daily("GAP", D6, 2.0), daily("GAP", D7, 2.0), daily("SPL", D6, 0.5), daily("SPL", D7, 0.5),
                      daily("OLD", D6, 3.0), daily("NEW", D6, 3.0), daily("NEW", D7, 3.0), daily("DEAD", D6, 9.0),
                      daily("BRK.B", D6, 400.0), daily("BRK.B", D7, 400.0)]
        self.minute = intraday()

    def get_bars(self, req: BarsRequest) -> list[Bar]:
        self.request_count += 1
        self.bar_requests.append(req)
        src = self.daily if req.timeframe == "1Day" else [b for b in self.minute if b.feed == req.feed]
        return [b for b in src if b.symbol in req.symbols and req.start_utc <= b.timestamp_utc <= req.end_utc]

    def get_corporate_actions(self, types: str, start: date, end: date) -> dict:
        self.ca_calls += 1
        return ACTIONS


def fetch_text(url: str) -> str:
    return NASDAQ if "nasdaqlisted" in url else OTHER


def test_dataset_point_in_time_rules_and_reproducible_cache(tmp_path: Path) -> None:
    fake = FakeAlpaca()
    result = build_dataset(fake, DatasetConfig(D7, D8), tmp_path, now_utc=NOW, fetch_text=fetch_text, code_sha="t")
    assert result.status == "complete" and result.manifest["orders_placed"] == 0

    elig = {(r["trading_date"], r["session"]): r for r in result.tables["eligibility"]}
    # BRK.B ($400) can never reach the $20 cap; DEAD only trades before its merger; OLD before rename, NEW after.
    assert elig[("2024-03-07", "premarket")]["eligible"] == 4  # DEAD, GAP, OLD, SPL
    assert elig[("2024-03-07", "premarket")]["eligible_delisted"] == 1
    assert elig[("2024-03-08", "premarket")]["eligible"] == 3  # GAP, NEW, SPL
    assert elig[("2024-03-08", "premarket")]["split_adjusted_refs"] == 1
    d7_pm = next(r for r in fake.bar_requests if r.timeframe == "1Min" and r.start_utc.date() == D7)
    assert "NEW" not in d7_pm.symbols and "OLD" in d7_pm.symbols

    detail = result.tables["candidate_detail"]
    assert [(r["symbol"], r["sip_candidate"], r["iex_candidate"]) for r in detail] == [("GAP", True, False)]
    assert detail[0]["sip_post_trigger_minutes"] == 324 and detail[0]["sip_post_trigger_bar_minutes"] == 1
    assert result.tables["split_candidate_changes"] == [{
        "symbol": "SPL", "trading_date": "2024-03-08", "session": "premarket",
        "candidate_without_adjustment": True, "candidate_with_adjustment": False,
    }]
    s = result.manifest["summary"]["premarket"]
    assert s["candidates"]["sip_total"] == 1 and s["candidates"]["iex_recall_of_sip"] == 0.0

    report = write_dataset(result, tmp_path)
    assert "IEX candidate recall of SIP | 0.0%" in report.read_text(encoding="utf-8")

    # Rerun on the same folder: saved inputs and bar cache are reused; no new API calls, same results.
    again = FakeAlpaca()
    rerun = build_dataset(again, DatasetConfig(D7, D8), tmp_path, now_utc=NOW, fetch_text=lambda u: "", code_sha="t")
    assert again.request_count == 0 and again.ca_calls == 0
    for name in ("eligibility", "candidate_detail", "candidate_matches", "coverage_buckets", "split_checks"):
        assert rerun.tables[name] == result.tables[name], name


def test_sip_block_aborts_with_explicit_status(tmp_path: Path) -> None:
    from momentum_bot.data.provider import EntitlementError

    class Blocked(FakeAlpaca):
        def get_bars(self, req: BarsRequest) -> list[Bar]:
            raise EntitlementError("subscription does not permit querying recent SIP data", status=403, feed=req.feed)

    result = build_dataset(Blocked(), DatasetConfig(D7, D8), tmp_path, now_utc=NOW, fetch_text=fetch_text)
    assert result.status == "sip_entitlement_blocked"
    assert result.tables["candidate_detail"] == [] and result.tables["fetch_log"][0]["http_status"] == 403
