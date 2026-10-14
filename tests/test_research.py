import csv
import gzip
import json
from dataclasses import asdict
from datetime import date, datetime, timedelta

import pytest
from conftest import et

from momentum_bot import charts
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
    assert rank.coverage["minutes_with_fewer_than_5_ranked"] == 0
    assert rank.coverage["minutes_without_any_bar"] == pm.minutes - 4


def test_top5_excludes_after_hours_closing_auction_volume() -> None:
    ah = W["afterhours"]
    bars = {"X": [flat("X", "16:00", 2.0, 5_000_000), flat("X", "16:01", 2.0, 150_000)]}
    rank = rs.rank_session(ah, bars, {"X": 1.0})
    assert [r["bar_start_utc"][11:16] for r in rank.snapshots][0] == "21:01"  # auction volume ignored at 16:00


# ---------- Bull Flag ----------

def test_bull_flag_detected_with_logged_geometry() -> None:
    res = rs.detect_flags(flag_bars(), W["premarket"])
    q = [r for r in res if r["qualified"]]
    assert len(q) == 1
    f = q[0]
    assert (f["pole_bars"], f["flag_bars"], f["reason"]) == (3, 3, "qualified")
    assert f["pole_start_utc"] == et(DAY, "04:02").isoformat() and f["pole_end_utc"] == et(DAY, "04:04").isoformat()
    assert f["flag_start_utc"] == et(DAY, "04:05").isoformat() and f["flag_end_utc"] == et(DAY, "04:07").isoformat()
    assert f["resistance"] == f["flag_high"] == 2.11 and f["flag_low"] == 2.07
    assert f["pullback_share"] == pytest.approx((2.12 - 2.07) / 0.12)
    assert f["breakout_volume_ratio"] == pytest.approx(3.0)
    assert f["available_utc"] == et(DAY, "04:09").isoformat()
    assert all(f[f"rule_{k}"] for k in rs.FLAG_RULES)
    assert {r["reason"] for r in res if not r["qualified"]} == {"insufficient_history"}


def test_bull_flag_has_no_lookahead() -> None:
    bars = flag_bars()
    future = [ob("FLG", "04:09", 2.15, 2.15, 1.50, 1.55, 900_000), ob("FLG", "04:10", 1.55, 3.0, 1.5, 2.9, 900_000)]
    now = rs.detect_flags(bars, W["premarket"])
    later = rs.detect_flags(bars + future, W["premarket"])
    assert later[: len(now)] == now  # appending future candles never changes an earlier decision
    assert rs.evaluate_flag(bars, rs.session_volumes(bars, W["premarket"])) == now[-1]


ONE = rs.FlagParams(pole_min_bars=3, pole_max_bars=3, flag_min_bars=3, flag_max_bars=3)


@pytest.mark.parametrize(("change", "reason"), [
    ({5: (2.11, 2.11, 2.04, 2.05)}, "failed_pullback"),  # flag low 2.04: 67% of the pole given back
    ({8: (2.09, 2.16, 2.09, 2.10)}, "failed_breakout_close"),  # closes below 2.11 resistance
    ({5: (2.11, 2.13, 2.08, 2.09)}, "failed_consolidation"),  # flag makes a new high above the pole
])
def test_bull_flag_rule_failures(change: dict, reason: str) -> None:
    bars = flag_bars()
    for i, (o, h, low, c) in change.items():
        b = bars[i]
        bars[i] = Bar(b.symbol, b.feed, b.timestamp_utc, o, h, low, c, b.volume)
    r = rs.evaluate_flag(bars, rs.session_volumes(bars, W["premarket"]), ONE)
    assert not r["qualified"] and r["reason"] == reason and r[f"rule_{reason[7:]}"] is False


def test_bull_flag_volume_rules_and_missing_minutes() -> None:
    bars = flag_bars()
    low_vol = bars[:-1] + [Bar("FLG", "sip", bars[-1].timestamp_utc, 2.09, 2.16, 2.09, 2.15, 12_000)]
    assert rs.evaluate_flag(low_vol, rs.session_volumes(low_vol, W["premarket"]), ONE)["reason"] == "failed_breakout_volume"
    heavy_flag = bars[:5] + [Bar("FLG", "sip", b.timestamp_utc, b.open, b.high, b.low, b.close, 60_000) for b in bars[5:8]] \
        + bars[8:]
    r = rs.evaluate_flag(heavy_flag, rs.session_volumes(heavy_flag, W["premarket"]), ONE)
    assert r["reason"] == "failed_volume_contraction"
    gap = bars[:6] + bars[7:]  # 04:06 has no bar: the pattern spans a missing minute
    r = rs.evaluate_flag(gap, rs.session_volumes(gap, W["premarket"]), ONE)
    assert r["reason"] == "failed_complete_bars" and not r["qualified"]


# ---------- signal sets, multiple signals, missing data ----------

def _hos_row(sym: str, hhmm: str) -> dict[str, str]:
    t = et(DAY, hhmm)
    return {"kind": "breakout", "symbol": sym, "trading_date": DAY.isoformat(), "session": "premarket",
            "sip_bar_start_utc": t.isoformat(), "sip_signal_available_utc": (t + timedelta(minutes=1)).isoformat(),
            "sip_price": "2.0", "sip_change_vs_ref": "1.0", "sip_session_volume": "200000", "sip_volume_ratio": "3",
            "sip_prior_session_high": "1.9", "sip_candidate_gate": "True", "sample": "in_sample"}


def test_research_session_filters_and_keeps_multiple_signals_per_symbol() -> None:
    first = flag_bars()
    second = [ob("FLG", f"04:{m:02d}", b.open + 0.2, b.high + 0.2, b.low + 0.2, b.close + 0.2, b.volume)
              for m, b in zip(range(20, 29), flag_bars())]  # the same pattern again, 20 minutes later
    bars = {"FLG": first + second, "OUT": [flat("OUT", "04:00", 1.02, 500_000)]}
    res = rs.research_session(W["premarket"], bars, {"FLG": 1.0, "OUT": 1.0},
                              [_hos_row("FLG", "04:08"), _hos_row("OUT", "04:00")], "in_sample", ScanParams(),
                              rs.FlagParams())
    assert [r["symbol"] for r in res.signals["hos"]] == ["FLG", "OUT"]  # baseline unchanged
    assert [r["symbol"] for r in res.signals["top5_hos"]] == ["FLG", "OUT"]  # only 2 ranked: both are Top 5
    flags = res.signals["top5_bullflag"]
    assert [r["sip_bar_start_utc"][11:16] for r in flags] == ["09:08", "09:28"]  # two signals, one symbol
    assert all(r["sip_candidate_gate"] is True and r["top5_rank"] == 1 for r in flags)
    from momentum_bot.backtest import signals_from_breakouts

    sigs = signals_from_breakouts([{k: str(v) for k, v in r.items()} for r in flags], {"in_sample"})
    assert [s.available_utc for s in sigs] == [et(DAY, "04:09"), et(DAY, "04:29")]


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
    assert out["signals"]["top5_bullflag"] == 0  # the breakout candle had not completed by as_of
    complete = rs.build(_mini_dataset(tmp_path, et(DAY, "05:00")), log=lambda _: None)
    assert complete["signals"] == {"hos": 1, "top5_hos": 1, "top5_bullflag": 1}


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
    out = rs._consistency({"hos": base, "top5_hos": var, "top5_bullflag": var})
    assert out["top5_hos"] == {"common_evaluated_signals": 1, "identical_outcomes": 1}  # skipped B is not common
    unsold = BacktestResult("base_cap50", [_trade("A", "t1", 2.0, sold=0)], base.attempts[:1])
    out = rs._consistency({"hos": unsold, "top5_hos": unsold, "top5_bullflag": var})
    assert out["top5_hos"]["identical_outcomes"] == 1  # a nan exit price (nothing sold) still compares equal
    assert out["top5_bullflag"]["identical_outcomes"] == 0


# ---------- chart annotations ----------

def _session_data() -> charts.SessionData:
    bars = flag_bars()
    s = lambda hhmm: et(DAY, hhmm).isoformat()  # noqa: E731
    flag = {k: str(v) for k, v in rs.detect_flags(bars, W["premarket"])[-1].items()}
    flag.update(symbol="FLG", top5_rank="1")
    trades = [{"symbol": "FLG", "signal_bar_start_utc": s(f"04:0{m}"), "entry_first_fill_utc": s(f"04:0{m + 1}"),
               "entry_price": "2.16", "filled_qty": "10", "fill": "full", "exit_last_fill_utc": s(f"04:0{m + 2}"),
               "exit_trigger_utc": s(f"04:0{m + 2}"), "exit_price": "2.09", "exit_reason": "stop", "r_multiple": "-1.08",
               "exit_qty": "10", "remaining_qty": "0", "mark_price": "", "mark_utc": ""}
              for m in (2, 6)]  # two trades on one symbol
    decisions = [{"symbol": "FLG", "signal_bar_start_utc": s("04:03"), "trigger": "bull_flag", "outcome": "rejected",
                  "reason": "at_signal_spread_above_cap", "top5_rank": "2", "signal_available_utc": s("04:04")}]
    changes = [{"symbol": "FLG", "event": "enter", "rank": "2", "prev_rank": "", "bar_start_utc": s("04:01"),
                "available_utc": s("04:02")}]
    snaps = [{"symbol": "FLG", "bar_start_utc": s("04:01"), "rank": "2"}]
    return charts.SessionData(DAY.isoformat(), "premarket", "top5_bullflag", {"FLG": bars}, snaps, changes, [flag],
                              decisions, trades, research=True)


def test_chart_annotations_match_recorded_events() -> None:
    data = _session_data()
    ev = charts.chart_events(data, "FLG")
    kinds = [e["kind"] for e in ev]
    assert kinds.count("entry_fill") == 2 and kinds.count("exit_fill") == 2 and kinds.count("stop") == 2
    enter = next(e for e in ev if e["kind"] == "top5_enter")
    assert enter["t"] == et(DAY, "04:02").isoformat() and enter["price"] == 2.00  # 04:01 close, known at 04:02
    rej = next(e for e in ev if e["kind"] == "signal_failed")
    assert rej["reason"] == "at_signal_spread_above_cap" and rej["price"] == 2.08
    pole = next(e for e in ev if e["kind"] == "flagpole")
    assert (pole["t"], pole["price"], pole["price_end"]) == (et(DAY, "04:02").isoformat(), 2.00, 2.12)
    stop = next(e for e in ev if e["kind"] == "stop")
    assert stop["price"] == pytest.approx(2.16 * 0.97)
    assert next(e for e in ev if e["kind"] == "flag_breakout")["t"] == et(DAY, "04:08").isoformat()
    assert charts.rank_series(data, "FLG")[1][:3] == [None, 2, None]


def test_chart_figure_renders_every_marker() -> None:
    pytest.importorskip("plotly")
    data = _session_data()
    fig = charts.figure(data, "FLG")
    names = {t.name for t in fig.data}
    assert {"1m SIP", "volume", "Top 5 rank (cached universe)", "entry fill", "exit fill", "signal failed", "flag breakout",
            "top5 enter"} <= names
    rects = [s for s in fig.layout.shapes if s.type == "rect"]
    assert len(rects) == 2  # flagpole and flag regions
    focused = charts.figure(data, "FLG", (et(DAY, "04:00").isoformat(), et(DAY, "04:10").isoformat()))
    assert focused.layout.xaxis.range is not None


def test_chart_marks_incomplete_exit_without_inventing_a_fill() -> None:
    data = _session_data()
    t = et(DAY, "04:06").isoformat()
    data.trades[1].update(exit_qty="0", remaining_qty="10", exit_price="nan", r_multiple="", net_usd="",
                          mark_price="2.05", mark_utc=t, exit_last_fill_utc=t)
    ev = charts.chart_events(data, "FLG")
    assert [e["kind"] for e in ev].count("exit_fill") == 1  # only the trade that actually sold
    unsold = next(e for e in ev if e["kind"] == "unsold_remainder")
    assert (unsold["t"], unsold["price"]) == (t, 2.05) and "not realized" in str(unsold["label"])
    data.trades[1]["mark_price"] = "nan"
    assert "no bid to mark" in str(next(e for e in charts.chart_events(data, "FLG") if e["kind"] == "unsold_remainder")["label"])


# ---------- baseline historical replay (no research outputs) ----------

def _replay_dataset(tmp_path):  # noqa: ANN001, ANN202
    from test_diagnostics import _scripted_run

    from momentum_bot import diagnostics as dg

    res, _ = _scripted_run(tmp_path)  # A on 2024-03-08 (stop exit), B on 2024-03-11 (exit sells nothing)
    dg.run(tmp_path, "in_sample", "base_cap50")
    m = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    m.update(as_of_utc="2024-03-12T00:00:00+00:00", start_date="2024-03-08", end_date="2024-03-11",
             trading_days=["2024-03-08", "2024-03-11"],
             chronological_split={"in_sample": {"first": "2024-03-08", "last": "2024-03-08"},
                                  "embargo": {"first": "2024-03-09", "last": "2024-03-09"},
                                  "out_of_sample": {"first": "2024-03-11", "last": "2024-03-11"}})
    (tmp_path / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    _write_bars(tmp_path / "cache" / "sip" / "2024-03-08_premarket_x.csv.gz",
                [flat("A", f"04:{m:02d}", 10.0, 1000) for m in range(55, 60)] + [flat("A", "05:00", 10.0, 5000)])
    return res


def test_baseline_replay_loads_without_research_and_summarizes_each_day(tmp_path) -> None:  # noqa: ANN001
    res = _replay_dataset(tmp_path)
    t = charts.ReplayTables.load(tmp_path)
    assert not t.has_research and t.dates() == ["2024-03-08", "2024-03-11"]  # latest last: the viewer's default
    assert (t.sample_of("2024-03-08"), t.sample_of("2024-03-11"), t.sample_of("2024-03-09")) == \
        ("in_sample", "out_of_sample", "embargo")
    a, b = (next(x for x in res.trades if x.symbol == s) for s in ("A", "B"))
    day1 = charts.daily_summary(t, "2024-03-08")
    assert (day1["signals"], day1["entries"], day1["completed_trades"], day1["incomplete_exits"]) == (1, 1, 1, 0)
    assert day1["net_usd_completed"] == pytest.approx(a.net_usd)
    day2 = charts.daily_summary(t, "2024-03-11")
    assert (day2["entries"], day2["completed_trades"], day2["incomplete_exits"]) == (1, 0, 1)
    assert day2["net_usd_completed"] == 0  # the incomplete exit is never added to net P&L
    assert day2["marked_usd_incomplete"] == pytest.approx(b.unrealized_usd)
    assert charts.daily_summary(t, "2024-03-12")["signals"] == 0  # empty day: zeros, no error


def test_baseline_chart_has_exact_et_tooltips_and_no_research_layers(tmp_path) -> None:  # noqa: ANN001
    _replay_dataset(tmp_path)
    t = charts.ReplayTables.load(tmp_path)
    data = t.session(tmp_path, "2024-03-08", "premarket")
    assert data.chart_symbols == ["A"] and not data.research and data.sample == "in_sample"
    ev = charts.chart_events(data, "A")
    assert not any(str(e["kind"]).startswith(("top5_", "flag")) for e in ev)
    sig = next(e for e in ev if e["kind"] == "signal_filled")
    assert "trigger bar 05:00 closed 10.0000" in str(sig["label"]) and "signal known 05:01:00 ET" in str(sig["label"])
    assert "Top 5" not in str(sig["label"])
    entry = next(e for e in ev if e["kind"] == "entry_fill")
    assert "at 05:01:00.500 ET" in str(entry["label"])  # after the trigger candle closed, plus 0.5 s latency
    assert charts.session_warnings(data) == ["Sparse bars (fewer than half the session's 330 minutes traded): A. "
                                             "Empty minutes are shown as gaps."]
    with pytest.raises(FileNotFoundError):  # no cached bars for that session: nothing invented
        t.session(tmp_path, "2024-03-11", "premarket")
    with pytest.raises(ValueError):
        t.session(tmp_path, "2024-03-08", "premarket", "top5_hos")
    pytest.importorskip("plotly")
    fig = charts.figure(data, "A")
    assert "Top 5 rank (cached universe)" not in {tr.name for tr in fig.data}
    assert "US Eastern" in fig.layout.xaxis2.title.text and "not live" in fig.layout.title.text


def test_session_warnings_flag_missing_quotes_and_incomplete_exits() -> None:
    data = charts.SessionData("2024-03-08", "premarket", "hos", {}, trades=[{"r_multiple": "", "symbol": "B"}],
                              signals=[{"outcome": "rejected", "quotes_cached": "False", "symbol": "B"}])
    w = charts.session_warnings(data)
    assert any("no cached quotes" in x for x in w) and any("incomplete exit" in x for x in w)
