import json
import re
from datetime import date, datetime, timezone
from pathlib import Path

import pytest

from conftest import DAY, NOW, FakeProvider, scenario
from momentum_bot.pipeline import run_m1
from momentum_bot.report import write_outputs


def test_full_comparison(provider: FakeProvider, tmp_path: Path) -> None:
    result = run_m1(provider, ["test"], DAY, DAY, now_utc=NOW)
    assert result.status == "complete"
    assert result.manifest["orders_placed"] == 0
    assert {r.feed for r in provider.requests} == {"sip", "iex"}
    assert all(r.adjustment == "raw" for r in provider.requests)

    pm = next(r for r in result.tables["session_comparison"] if r["session"] == "premarket")
    assert (pm["expected_minutes"], pm["sip_bar_minutes"], pm["iex_bar_minutes"], pm["iex_only_minutes"]) == (330, 7, 6, 0)
    assert (pm["sip_volume"], pm["iex_volume"]) == (110_000, 3_000)
    assert pm["session_high_diff_bps"] == pytest.approx((2.44 - 2.45) / 2.45 * 10_000)
    assert pm["matched_iex_high_above_sip"] == 0

    summary = result.manifest["summary"]
    assert summary["candidates"] == {"both": 0, "sip_only": 1, "iex_only": 0, "sip_total": 1, "iex_recall_of_sip": 0.0}
    assert summary["breakouts"]["both"] == 1  # same 04:06 breakout bar on both feeds
    assert summary["gated_breakouts"]["sip_only"] == 1  # IEX volume never passes the 100k gate

    sip_missing = [r for r in result.tables["missing_intervals"] if r["feed"] == "sip" and r["session"] == "premarket"]
    assert sip_missing == [{
        "symbol": "TEST", "feed": "sip", "trading_date": "2024-03-08", "session": "premarket",
        "missing_start_utc": "2024-03-08T09:07:00+00:00", "missing_end_utc": "2024-03-08T14:30:00+00:00", "minutes": 323,
    }]

    report = write_outputs(result, tmp_path)
    assert "`complete`" in report.read_text(encoding="utf-8")
    assert json.loads((tmp_path / "manifest.json").read_text())["status"] == "complete"
    assert (tmp_path / "bars.csv").read_text().splitlines()[0].startswith("symbol,feed,timestamp_utc,timestamp_et")


def test_outputs_are_deterministic(tmp_path: Path) -> None:
    for name in ("a", "b"):
        write_outputs(run_m1(FakeProvider(scenario()), ["TEST"], DAY, DAY, now_utc=NOW), tmp_path / name)
    for f in (tmp_path / "a").iterdir():
        assert f.read_bytes() == (tmp_path / "b" / f.name).read_bytes(), f.name


def test_sip_entitlement_block_is_reported_and_never_substituted(tmp_path: Path) -> None:
    provider = FakeProvider(scenario(), blocked_feeds=frozenset({"sip"}))
    result = run_m1(provider, ["TEST"], DAY, DAY, now_utc=NOW)
    assert result.status == "sip_entitlement_blocked"
    assert result.manifest["feed_status"] == {"sip": "entitlement_blocked", "iex": "ok"}
    assert sum(r.feed == "sip" for r in provider.requests) == 1  # stops after the first refusal
    assert result.tables["session_comparison"] == [] and result.tables["candidate_matches"] == []
    assert {r["feed"] for r in result.tables["bars"]} == {"iex"}
    failures = result.manifest["failures"]
    assert failures[0]["status"] == "entitlement_blocked" and failures[0]["http_status"] == 403
    assert failures[1]["status"] == "skipped"
    text = write_outputs(result, tmp_path).read_text(encoding="utf-8")
    assert "has **not** been substituted" in text and "subscription does not permit" in text


def test_rejects_dates_inside_delay_window() -> None:
    too_soon = datetime(2024, 3, 9, 1, 5, tzinfo=timezone.utc)  # 20:05 ET on DAY
    with pytest.raises(ValueError, match="delay window"):
        run_m1(FakeProvider([]), ["TEST"], DAY, DAY, now_utc=too_soon)


def test_no_trading_days() -> None:
    with pytest.raises(ValueError, match="no trading days"):
        run_m1(FakeProvider([]), ["TEST"], date(2024, 3, 9), date(2024, 3, 10), now_utc=NOW)


def test_source_has_no_order_or_trading_endpoints() -> None:
    src = Path(__file__).parents[1] / "src"
    files = {p.name: p.read_text(encoding="utf-8").lower() for p in src.rglob("*.py")}
    text = "\n".join(files.values())
    for forbidden in ("/v2/orders", "/v2/positions", "/v2/account", "submit_order", "cancel", "https://api.alpaca.markets",
                      'method="post"', 'method="delete"', 'method="patch"', 'method="put"'):
        assert forbidden not in text, forbidden
    # The paper trading host appears only in the read-only assets module, which exposes only /v2/assets.
    assert [n for n, t in files.items() if "paper-api.alpaca.markets" in t] == ["alpaca_assets.py"]
    assert set(re.findall(r"/v2/\w+", files["alpaca_assets.py"])) == {"/v2/assets"}


def test_closing_auction_bar_volume_excluded_from_afterhours_gate() -> None:
    from conftest import bar
    from momentum_bot.compare import ScanParams, scan_session
    from momentum_bot.data.market_calendar import session_windows

    start = session_windows(DAY)["afterhours"].start_utc
    rows = [bar("sip", DAY, "16:00", 2.00, 2.00, 5_000_000), bar("sip", DAY, "16:01", 2.20, 2.20, 1_000)]
    key = ("TEST", DAY, "afterhours")
    assert scan_session("sip", key, rows, 2.00, ScanParams(), start)[0] is None
    assert scan_session("sip", key, rows, 2.00, ScanParams(exclude_closing_auction_bar=False), start)[0] is not None
