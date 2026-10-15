"""Bull Flag detector and the Top 5 + Bull Flag signal set (exploratory research, in-sample only)."""

import pytest
from conftest import et
from test_research import DAY, W, _hos_row, flag_bars, flat, ob

from momentum_bot import bullflag as bf
from momentum_bot import research as rs
from momentum_bot.compare import ScanParams
from momentum_bot.data.provider import Bar

# ---------- Bull Flag ----------

def test_bull_flag_detected_with_logged_geometry() -> None:
    res = bf.detect_flags(flag_bars(), W["premarket"])
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
    assert all(f[f"rule_{k}"] for k in bf.FLAG_RULES)
    assert {r["reason"] for r in res if not r["qualified"]} == {"insufficient_history"}


def test_bull_flag_has_no_lookahead() -> None:
    bars = flag_bars()
    future = [ob("FLG", "04:09", 2.15, 2.15, 1.50, 1.55, 900_000), ob("FLG", "04:10", 1.55, 3.0, 1.5, 2.9, 900_000)]
    now = bf.detect_flags(bars, W["premarket"])
    later = bf.detect_flags(bars + future, W["premarket"])
    assert later[: len(now)] == now  # appending future candles never changes an earlier decision
    assert bf.evaluate_flag(bars, bf.session_volumes(bars, W["premarket"])) == now[-1]


ONE = bf.FlagParams(pole_min_bars=3, pole_max_bars=3, flag_min_bars=3, flag_max_bars=3)


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
    r = bf.evaluate_flag(bars, bf.session_volumes(bars, W["premarket"]), ONE)
    assert not r["qualified"] and r["reason"] == reason and r[f"rule_{reason[7:]}"] is False


def test_bull_flag_volume_rules_and_missing_minutes() -> None:
    bars = flag_bars()
    low_vol = bars[:-1] + [Bar("FLG", "sip", bars[-1].timestamp_utc, 2.09, 2.16, 2.09, 2.15, 12_000)]
    assert bf.evaluate_flag(low_vol, bf.session_volumes(low_vol, W["premarket"]), ONE)["reason"] == "failed_breakout_volume"
    heavy_flag = bars[:5] + [Bar("FLG", "sip", b.timestamp_utc, b.open, b.high, b.low, b.close, 60_000) for b in bars[5:8]] \
        + bars[8:]
    r = bf.evaluate_flag(heavy_flag, bf.session_volumes(heavy_flag, W["premarket"]), ONE)
    assert r["reason"] == "failed_volume_contraction"
    gap = bars[:6] + bars[7:]  # 04:06 has no bar: the pattern spans a missing minute
    r = bf.evaluate_flag(gap, bf.session_volumes(gap, W["premarket"]), ONE)
    assert r["reason"] == "failed_complete_bars" and not r["qualified"]


# ---------- signal sets ----------

def test_research_session_filters_and_keeps_multiple_signals_per_symbol() -> None:
    first = flag_bars()
    second = [ob("FLG", f"04:{m:02d}", b.open + 0.2, b.high + 0.2, b.low + 0.2, b.close + 0.2, b.volume)
              for m, b in zip(range(20, 29), flag_bars())]  # the same pattern again, 20 minutes later
    bars = {"FLG": first + second, "OUT": [flat("OUT", "04:00", 1.02, 500_000)]}
    res = rs.research_session(W["premarket"], bars, {"FLG": 1.0, "OUT": 1.0},
                              [_hos_row("FLG", "04:08"), _hos_row("OUT", "04:00")], "in_sample", ScanParams(),
                              bf.FlagParams())
    assert [r["symbol"] for r in res.signals["hos"]] == ["FLG", "OUT"]  # baseline unchanged
    assert [r["symbol"] for r in res.signals["top5_hos"]] == ["FLG", "OUT"]  # only 2 ranked: both are Top 5
    flags = res.signals["top5_bullflag"]
    assert [r["sip_bar_start_utc"][11:16] for r in flags] == ["09:08", "09:28"]  # two signals, one symbol
    assert all(r["sip_candidate_gate"] is True and r["top5_rank"] == 1 for r in flags)
    from momentum_bot.backtest import signals_from_breakouts

    sigs = signals_from_breakouts([{k: str(v) for k, v in r.items()} for r in flags], {"in_sample"})
    assert [s.available_utc for s in sigs] == [et(DAY, "04:09"), et(DAY, "04:29")]
