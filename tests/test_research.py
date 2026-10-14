import csv
import gzip
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta

import pytest
from conftest import et

from momentum_bot import research as rs
from momentum_bot.backtest import Attempt, BacktestResult, Trade
from momentum_bot.compare import ScanParams
from momentum_bot.data.market_calendar import session_windows
from momentum_bot.data.provider import Bar
from momentum_bot.dataset import _write_bars

DAY = date(2024, 3, 8)
W = session_windows(DAY)


def ob(sym: str, hhmm: str, o: float, h: float, low: float, c: float, v: int, d: date = DAY) -> Bar:
    return Bar(sym, "sip", et(d, hhmm), o, h, low, c, v)


def flat(sym: str, hhmm: str, c: float, v: int) -> Bar:
    return ob(sym, hhmm, c, c, c, c, v)


def flag_bars(sym: str = "FLG") -> list[Bar]:
    """Two quiet bars, a 3-bar +6% flagpole, a 3-bar flag (42% pullback, lower volume), a breakout."""
    return [ob(sym, "04:00", 2.00, 2.01, 2.00, 2.00, 20_000), ob(sym, "04:01", 2.00, 2.01, 1.99, 2.00, 20_000),
            ob(sym, "04:02", 2.00, 2.04, 2.00, 2.04, 50_000), ob(sym, "04:03", 2.04, 2.08, 2.03, 2.08, 50_000),
            ob(sym, "04:04", 2.08, 2.12, 2.07, 2.11, 50_000), ob(sym, "04:05", 2.11, 2.11, 2.08, 2.09, 10_000),
            ob(sym, "04:06", 2.09, 2.10, 2.07, 2.08, 10_000), ob(sym, "04:07", 2.08, 2.10, 2.07, 2.09, 10_000),
            ob(sym, "04:08", 2.09, 2.16, 2.09, 2.15, 30_000)]


# ---------- Top 5 ----------

def test_top5_ranking_uses_only_completed_bars_and_records_changes() -> None:
    pm = W["premarket"]
    refs = {s: 1.0 for s in "ABCDEFGH"}
    bars = {s: [flat(s, "04:00", px, 200_000)] for s, px in zip("ABCDEF", (1.5, 1.4, 1.3, 1.2, 1.1, 1.05))}
    bars["G"] = [flat("G", "04:00", 1.6, 50_000), flat("G", "04:01", 1.6, 60_000)]  # volume floor reached at 04:01
    bars["B"].append(flat("B", "04:02", 21.0, 1_000))  # leaves the $1-$20 band
    bars["H"] = [flat("H", "03:59", 9.0, 900_000), flat("H", "04:05", 1.3, 300_000)]  # 03:59 is outside the session
    rank = rs.rank_session(pm, bars, refs)
    at = lambda hhmm: [r["symbol"] for r in rank.snapshots if r["bar_start_utc"] == et(DAY, hhmm).isoformat()]  # noqa: E731
    assert at("04:00") == ["A", "B", "C", "D", "E"]  # G below the volume floor, F sixth
    assert at("04:01") == ["G", "A", "B", "C", "D"]  # the 04:01 bar counts only from the 04:01 snapshot on
    assert at("04:02") == ["G", "A", "C", "D", "E"]  # B at $21 is out of the band
    assert at("04:04") == at("04:02")  # H's pre-session bar is ignored; its 04:05 bar is not seen yet
    assert at("04:05") == ["G", "A", "C", "H", "D"]  # tie at +30%: C before H by symbol
    first = next(r for r in rank.snapshots if r["bar_start_utc"] == et(DAY, "04:00").isoformat())
    assert first["available_utc"] == et(DAY, "04:01").isoformat()  # known when the bar completes, not before
    ev = {(r["symbol"], r["event"], r["bar_start_utc"][11:16]): r for r in rank.changes}
    assert ev[("E", "exit", "09:01")]["reason"] == "displaced"
    assert ev[("B", "exit", "09:02")]["reason"] == "left_price_band"
    assert ev[("E", "enter", "09:02")]["rank"] == 5
    assert ("A", "rank_change", "09:01") in ev
    assert rank.coverage["minutes_with_fewer_than_5_ranked"] == pm.minutes - 6  # from 04:06 the 04:00 closes are stale
    assert rank.coverage["minutes_without_any_bar"] == pm.minutes - 4


def test_top5_excludes_after_hours_closing_auction_volume() -> None:
    ah = W["afterhours"]
    bars = {"X": [flat("X", "16:00", 2.0, 5_000_000), flat("X", "16:01", 2.0, 150_000)]}
    rank = rs.rank_session(ah, bars, {"X": 1.0})
    assert [r["bar_start_utc"][11:16] for r in rank.snapshots][0] == "21:01"  # auction volume ignored at 16:00


def test_top5_never_ranks_stale_prices() -> None:
    pm = W["premarket"]
    bars = {s: [flat(s, "04:00", 3.0, 200_000)] for s in "ABCDE"}  # +200%, then no more trades
    bars["LIVE"] = [flat("LIVE", f"04:{m:02d}", 1.1, 200_000) for m in range(10)]  # +10%, trades every minute
    rank = rs.rank_session(pm, bars, {s: 1.0 for s in bars})
    at = lambda hhmm: [r["symbol"] for r in rank.snapshots if r["bar_start_utc"] == et(DAY, hhmm).isoformat()]  # noqa: E731
    assert at("04:05") == ["A", "B", "C", "D", "E"]  # 5 minutes old: still fresh
    assert at("04:06") == ["LIVE"]  # 6 minutes old: stale, never carried forward
    old = next(r for r in rank.snapshots if r["bar_start_utc"] == et(DAY, "04:05").isoformat())
    assert old["minutes_since_trade"] == 5 and old["universe"] == rs.UNIVERSE
    exits = {r["symbol"]: r["reason"] for r in rank.changes if r["event"] == "exit"}
    assert exits == {**{s: "stale" for s in "ABCDE"}, "LIVE": "stale"}  # LIVE too, once its 04:09 close ages out
    assert rank.coverage["stale_exclusion_symbol_minutes"] == 5 * (pm.minutes - 6) + (pm.minutes - 15)
    assert rank.coverage["max_staleness_minutes"] == 5


# ---------- signal sets, multiple signals, missing data ----------

def _hos_row(sym: str, hhmm: str) -> dict[str, str]:
    t = et(DAY, hhmm)
    return {"kind": "breakout", "symbol": sym, "trading_date": DAY.isoformat(), "session": "premarket",
            "sip_bar_start_utc": t.isoformat(), "sip_signal_available_utc": (t + timedelta(minutes=1)).isoformat(),
            "sip_price": "2.0", "sip_change_vs_ref": "1.0", "sip_session_volume": "200000", "sip_volume_ratio": "3",
            "sip_prior_session_high": "1.9", "sip_candidate_gate": "True", "sample": "in_sample"}


def test_research_session_filters_by_point_in_time_rank() -> None:
    bars = {"FLG": flag_bars(), "OUT": [flat("OUT", "04:00", 1.02, 500_000)]}
    # five stronger gainers (+200%) trading every minute, so their prices stay fresh through 04:08
    bars.update({s: [flat(s, f"04:0{m}", 3.0, 200_000) for m in range(9)] for s in "ABCDE"})
    res = rs.research_session(W["premarket"], bars, {s: 1.0 for s in [*bars]},
                              [_hos_row("FLG", "04:08"), _hos_row("OUT", "04:00")], "in_sample", ScanParams())
    assert [r["symbol"] for r in res.signals["hos"]] == ["FLG", "OUT"]  # baseline unchanged
    assert res.signals["top5_hos"] == []  # neither was in the Top 5 at its trigger bar
    assert [(r["symbol"], r["reason"]) for r in res.filtered] == [("FLG", "not_in_top5"), ("OUT", "not_in_top5")]
    alone = rs.research_session(W["premarket"], {k: bars[k] for k in ("FLG", "OUT")}, {"FLG": 1.0, "OUT": 1.0},
                                [_hos_row("FLG", "04:08"), _hos_row("OUT", "04:00")], "in_sample", ScanParams())
    assert [(r["symbol"], r["top5_rank"]) for r in alone.signals["top5_hos"]] == [("FLG", 1), ("OUT", 1)]  # OUT led at 04:00
    from momentum_bot.backtest import signals_from_breakouts

    sigs = signals_from_breakouts([{k: str(v) for k, v in r.items()} for r in alone.signals["top5_hos"]], {"in_sample"})
    assert [s.available_utc for s in sigs] == [et(DAY, "04:09"), et(DAY, "04:01")]  # unchanged signal times


def _mini_dataset(tmp_path, as_of: datetime, with_afterhours: bool = False):  # noqa: ANN001, ANN202
    scan = ScanParams()
    (tmp_path / "manifest.json").write_text(json.dumps({
        "as_of_utc": as_of.isoformat(), "scan_params": asdict(scan), "trading_days": [DAY.isoformat()],
        "chronological_split": {"in_sample": {"first": DAY.isoformat(), "last": DAY.isoformat()}}}), encoding="utf-8")
    with gzip.open(tmp_path / "references.csv.gz", "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["symbol", "trading_date", "session", "reference_close", "split_adjusted"])
        for s in ("premarket", "afterhours"):
            w.writerow(["FLG", DAY.isoformat(), s, "1.0", "False"])
    with (tmp_path / "breakout_matches.csv").open("w", newline="", encoding="utf-8") as fh:
        row = _hos_row("FLG", "04:08")
        w = csv.DictWriter(fh, fieldnames=list(row))
        w.writeheader()
        w.writerow(row)
    _write_bars(tmp_path / "cache" / "sip" / f"{DAY}_premarket_abc.csv.gz", flag_bars())
    if with_afterhours:
        _write_bars(tmp_path / "cache" / "sip" / f"{DAY}_afterhours_abc.csv.gz", [])
    return tmp_path


def test_build_marks_missing_sessions_and_drops_incomplete_bars(tmp_path) -> None:  # noqa: ANN001
    ds = _mini_dataset(tmp_path, et(DAY, "04:08") + timedelta(seconds=30))  # the 04:08 breakout bar is incomplete
    out = rs.build(ds, log=lambda _: None)
    assert out["sessions_missing_bars"] == 1  # no after-hours bar file: excluded, never invented
    cov = rs.read_table(ds / "research" / "in_sample" / "top5_coverage.csv")
    assert {(r["session"], r["bars_file"]) for r in cov} == {("premarket", "found"), ("afterhours", "missing")}
    snaps = rs.read_table(ds / "research" / "in_sample" / "top5_snapshots.csv.gz")
    assert "2.15" not in {r["price"] for r in snaps}  # the incomplete 04:08 candle never reaches a ranking
    assert out["signals"] == {"hos": 1, "top5_hos": 1}  # ranked on the 04:07 close: the 04:08 bar was incomplete
    complete = rs.build(_mini_dataset(tmp_path, et(DAY, "05:00")), log=lambda _: None)
    assert complete["signals"] == {"hos": 1, "top5_hos": 1}


def test_variants_refuse_the_out_of_sample_block(tmp_path) -> None:  # noqa: ANN001
    with pytest.raises(ValueError, match="in-sample only"):
        rs.build(tmp_path, "out_of_sample")


def _trade(sym: str, avail: str, entry: float, sold: int = 10) -> Trade:
    done = sold == 10
    return Trade(sym, DAY.isoformat(), "premarket", "in_sample", "base_cap50", avail, avail, 2.0, 20.0, 10, 10, avail,
                 entry, 0.5, "stop", avail, avail, sold, 10 - sold, entry * 0.97 if sold else float("nan"), done,
                 -0.3 if sold else 0.0, 0.0, -0.3 if sold else 0.0, "" if done else avail,
                 float("nan") if done else entry * 0.95, 0.0 if done else -1.0, -0.3 if done else None,
                 -1.0 if done else None)


def test_execution_consistency_compares_common_signals() -> None:
    base = BacktestResult("base_cap50", [_trade("A", "t1", 2.0)],
                          [Attempt("A", "d", "premarket", "in_sample", "base_cap50", "t1", "filled"),
                           Attempt("B", "d", "premarket", "in_sample", "base_cap50", "t2", "skipped", "position_open")])
    var = BacktestResult("base_cap50", [_trade("A", "t1", 2.0)],
                         [Attempt("A", "d", "premarket", "in_sample", "base_cap50", "t1", "filled"),
                          Attempt("B", "d", "premarket", "in_sample", "base_cap50", "t2", "non_fill", "at_signal_x")])
    out = rs._consistency({"hos": base, "top5_hos": var})
    assert out["top5_hos"] == {"common_evaluated_signals": 1, "identical_outcomes": 1}  # skipped B is not common
    unsold = BacktestResult("base_cap50", [_trade("A", "t1", 2.0, sold=0)], base.attempts[:1])
    assert rs._consistency({"hos": unsold, "top5_hos": unsold})["top5_hos"]["identical_outcomes"] == 1  # nan exit price
    assert rs._consistency({"hos": unsold, "top5_hos": var})["top5_hos"]["identical_outcomes"] == 0
