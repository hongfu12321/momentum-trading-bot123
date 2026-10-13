import json
import urllib.parse
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

from momentum_bot import quotes
from momentum_bot.data.alpaca_assets import AlpacaPaperAssets
from momentum_bot.data.alpaca_historical import HttpResponse
from momentum_bot.data.provider import AuthenticationError, EntitlementError
from momentum_bot.dataset import DatasetConfig, build_dataset
from momentum_bot.split import chronological_split
from test_dataset import D6, D7, D8, NOW, FakeAlpaca, daily, fetch_text

T0 = datetime(2024, 3, 8, 9, 0, tzinfo=timezone.utc)


def test_chronological_split_holds_out_latest_days_with_embargo() -> None:
    days = [date(2024, 1, 2) + timedelta(days=i) for i in range(90)]
    s = chronological_split(days, oos_fraction=1 / 3, embargo_days=1)
    assert (len(s.in_sample), len(s.embargo), len(s.out_of_sample)) == (59, 1, 30)
    assert max(s.in_sample) < s.embargo[0] < min(s.out_of_sample)
    assert s.sample_of(days[-1]) == "out_of_sample" and s.sample_of(days[0]) == "in_sample"
    with pytest.raises(ValueError):
        chronological_split(days[:2], embargo_days=1)


def test_paper_assets_reader_is_read_only_and_paper_only() -> None:
    seen: list[str] = []

    def http(url, headers):  # noqa: ANN001, ANN202
        seen.append(url)
        return HttpResponse(200, json.dumps([{"symbol": "ZOMB", "status": "inactive"}]).encode())

    reader = AlpacaPaperAssets("PKTEST", "s", http_get=http, sleep=lambda s: None, clock=lambda: 0.0)
    assert reader.list_assets("inactive") == [{"symbol": "ZOMB", "status": "inactive"}]
    url = urllib.parse.urlparse(seen[0])
    assert (url.hostname, url.path) == ("paper-api.alpaca.markets", "/v2/assets")
    assert urllib.parse.parse_qs(url.query) == {"status": ["inactive"], "asset_class": ["us_equity"]}
    with pytest.raises(AuthenticationError, match="live"):
        AlpacaPaperAssets("AKLIVEKEY", "s")
    assert not hasattr(reader, "get_bars") and not any("order" in n for n in dir(reader))


class FakeAssets:
    def list_assets(self, status: str) -> list[dict]:
        rows = [
            {"symbol": "ZOMB", "name": "Zombie Corp Common Stock", "exchange": "NASDAQ", "status": "inactive"},
            {"symbol": "COPY", "name": "Copy Corp Common Stock", "exchange": "NYSE", "status": "inactive"},
            {"symbol": "OTCX", "name": "Otc Co", "exchange": "OTC", "status": "active"},
            {"symbol": "LEVX", "name": "Direxion Daily Leveraged ETF", "exchange": "ARCA", "status": "inactive"},
            {"symbol": "GAP", "name": "Gap Corp", "exchange": "NASDAQ", "status": "active"},
        ]
        return [r for r in rows if r["status"] == status]


def test_dataset_adds_alpaca_inactive_symbols_and_drops_duplicate_series(tmp_path: Path) -> None:
    fake = FakeAlpaca()
    fake.daily += [daily("ZOMB", D6, 1.5), daily("COPY", D6, 2.0)]  # COPY repeats GAP's D6 bar exactly
    result = build_dataset(fake, DatasetConfig(D7, D8, embargo_days=0), tmp_path, now_utc=NOW,
                           fetch_text=fetch_text, assets_reader=FakeAssets())
    origins = {r["symbol"]: r["origin"] for r in result.tables["universe"]}
    assert origins["ZOMB"] == "alpaca_inactive:NASDAQ" and origins["OTCX"] == "alpaca_otc"
    assert "LEVX" not in origins and origins["GAP"] == "current_listing"
    pm7 = next(r for r in result.tables["eligibility"] if r["trading_date"] == "2024-03-07" and r["session"] == "premarket")
    assert pm7["eligible"] == 5 and pm7["eligible_alpaca_inactive"] == 1  # DEAD, GAP, OLD, SPL + ZOMB
    assert pm7["duplicate_series_hidden"] == 1 and pm7["sample"] == "in_sample"
    assert result.tables["duplicate_series"][0] == {"trading_date": "2024-03-07", "detected_on": "2024-03-06",
                                                    "kept": "GAP", "dropped": "COPY"}
    split = result.manifest["chronological_split"]
    assert split["in_sample"]["days"] == 1 and split["out_of_sample"]["first"] == D8.isoformat()
    assert "not evaluated" in result.manifest["profitability"]
    for r in result.tables["candidate_detail"]:
        assert (datetime.fromisoformat(r["trigger_signal_available_utc"])
                == datetime.fromisoformat(r["trigger_bar_start_utc"]) + timedelta(minutes=1))
    for r in result.tables["breakout_matches"]:
        assert datetime.fromisoformat(r["sip_signal_available_utc"]) > datetime.fromisoformat(r["sip_bar_start_utc"])
    assert json.loads((tmp_path / "inputs" / "alpaca_assets.json").read_text())["assets"]


def q(sec: float, bid: float, ask: float) -> dict:
    return {"t": (T0 + timedelta(seconds=sec)).strftime("%Y-%m-%dT%H:%M:%S.%f") + "123Z", "bp": bid, "ap": ask}


def test_summarize_quotes_excludes_locked_crossed_from_spread_eligibility() -> None:
    rows = [q(0, 10.0, 10.1), q(30, 10.0, 10.0), q(60, 10.2, 10.1), q(90, 0, 10.1), q(150, 9.9, 10.1)]
    s = quotes.summarize_quotes(rows, T0, T0 + timedelta(minutes=3), max_quote_age_s=60)
    assert (s["quotes"], s["executable"], s["locked"], s["crossed"], s["one_sided"]) == (5, 2, 1, 1, 1)
    assert s["minutes"] == 3 and s["minutes_with_quote"] == 3
    assert s["max_gap_seconds"] == 60
    assert s["median_spread_bps"] == pytest.approx((0.1 / 10.05 + 0.2 / 10.0) / 2 * 10_000)  # executable only
    # Every quote stays fresh (age cap 60s); only the two executable 30s spans count for spread.
    assert s["fresh_quote_time_share"] == pytest.approx(1.0)
    assert s["executable_time_share"] == pytest.approx(60 / 180)
    assert s["time_weighted_spread_bps"] == pytest.approx((0.1 / 10.05 * 1e4 + 0.2 / 10.0 * 1e4) / 2)
    assert s["time_share_within_spread_cap"] == 0  # the locked 0 bps span is not executable


def test_summarize_quotes_stops_counting_stale_quotes_after_max_age() -> None:
    rows = [q(0, 10.0, 10.02), q(20, 10.0, 10.5)]  # 20 bps (inside the cap), then 488 bps
    s = quotes.summarize_quotes(rows, T0, T0 + timedelta(seconds=60))  # default max age 3s
    assert s["fresh_quote_time_share"] == pytest.approx(6 / 60)
    assert s["executable_time_share"] == pytest.approx(6 / 60)
    assert s["time_share_within_spread_cap"] == pytest.approx(3 / 60)  # not 20/60: the 20 bps quote goes stale
    assert s["time_weighted_spread_bps"] == pytest.approx((0.02 / 10.01 + 0.5 / 10.25) / 2 * 1e4)
    late = quotes.summarize_quotes([q(30, 10.0, 10.02)], T0, T0 + timedelta(seconds=60))
    assert late["fresh_quote_time_share"] == pytest.approx(3 / 60)  # no quote counted before the first one


def test_quote_state_classification() -> None:
    assert [quotes.quote_state(b, a) for b, a in ((1, 1.01), (1, 1), (1.01, 1), (0, 1), (1, 0))] == [
        "executable", "locked", "crossed", "one_sided", "one_sided"]


class FakeQuotes:
    def __init__(self, blocked: bool = False) -> None:
        self.request_count = 0
        self.bytes_received = 0
        self.blocked = blocked

    def iter_quotes(self, symbol, feed, start, end):  # noqa: ANN001, ANN201
        self.request_count += 1
        if self.blocked:
            raise EntitlementError("subscription does not permit querying recent SIP data", status=403, feed=feed)
        assert feed == "sip"
        self.bytes_received += 300
        yield q(1, 2.0, 2.02)
        yield q(61, 2.0, 2.04)


def cand(symbol: str, session: str, trigger: str) -> dict[str, str]:
    return {"symbol": symbol, "trading_date": "2024-03-08", "session": session, "sip_candidate": "True",
            "trigger_bar_start_utc": trigger, "sample": "out_of_sample"}


def test_probe_samples_deterministically_caches_and_reports_blocking(tmp_path: Path) -> None:
    rows = [cand(f"S{i}", "premarket", T0.isoformat()) for i in range(10)]
    rows += [cand(f"A{i}", "afterhours", "2024-03-09T00:45:00+00:00") for i in range(10)]
    picked = quotes.sample_candidates(rows, 4, seed=1)
    assert picked == quotes.sample_candidates(rows, 4, seed=1) and len(picked) == 4
    src = FakeQuotes()
    stats = quotes.probe(src, picked, 30, tmp_path)
    ah = next(s for s in stats if s.session == "afterhours")
    assert ah.window_end_utc == "2024-03-09T01:00:00+00:00"  # clipped at 20:00 ET
    assert (ah.trigger_bar_start_utc, ah.window_start_utc) == ("2024-03-09T00:45:00+00:00", "2024-03-09T00:46:00+00:00")
    assert all(s.status == "ok" and s.quotes == 2 for s in stats)
    again = quotes.probe(src, picked, 30, tmp_path)
    assert {s.status for s in again} == {"cached"} and src.request_count == 4
    summary = quotes.summarize_probe(again, total_candidates=100, minutes=30)  # cached windows keep their cost
    assert summary["extrapolation_to_all_candidates"]["estimated_quotes"] == 200
    assert summary["extrapolation_to_all_candidates"]["estimated_requests"] == 100

    blocked = quotes.probe(FakeQuotes(blocked=True), picked, 30, tmp_path / "b")
    assert [s.status for s in blocked] == ["entitlement_blocked", "skipped", "skipped", "skipped"]


def test_signals_become_available_only_when_the_trigger_bar_completes() -> None:
    from momentum_bot.compare import Event

    row = {"trigger_bar_start_utc": T0.isoformat()}
    assert quotes.signal_available_utc(row) == T0 + timedelta(minutes=1)
    explicit = {**row, "trigger_signal_available_utc": (T0 + timedelta(minutes=1)).isoformat()}
    assert quotes.signal_available_utc(explicit) == T0 + timedelta(minutes=1)
    with pytest.raises(ValueError, match="completes"):
        Event("breakout", "sip", "X", T0.date(), "premarket", T0, T0 + timedelta(seconds=59), 2.0, 0.2, 1, True)
