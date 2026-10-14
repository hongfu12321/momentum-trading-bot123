from datetime import datetime, timedelta, timezone

import pytest

from momentum_bot import diagnostics as dg
from momentum_bot.backtest import Quote, QuoteStore, StrategyConfig
from momentum_bot.compare import ScanParams, scan_session

T0 = datetime(2024, 3, 8, 10, 1, tzinfo=timezone.utc)


def qt(sec: float, bid: float, ask: float) -> Quote:
    return Quote(T0 + timedelta(seconds=sec), bid, ask, 100, 100)


def test_excursions_use_executable_bids_inside_the_trade_only() -> None:
    # entry 10.00, risk 0.30 (3%): +0.6R at 10s, a crossed print far above, -1R at 40s, a later quote after exit
    quotes = [qt(-5, 12.0, 12.1), qt(10, 10.18, 10.19), qt(20, 11.0, 10.9), qt(40, 9.70, 9.71), qt(90, 13.0, 13.1)]
    ex = dg.excursions(quotes, 10.0, 0.30, T0, T0 + timedelta(seconds=60))
    assert ex["mfe_r"] == pytest.approx(0.6) and ex["mae_r"] == pytest.approx(-1.0)
    assert (ex["seconds_to_mfe"], ex["seconds_to_mae"]) == (10, 40)
    assert ex["favorable_first"] is True
    down_first = dg.excursions([qt(5, 9.8, 9.81), qt(9, 10.2, 10.21)], 10.0, 0.30, T0, T0 + timedelta(seconds=60))
    assert down_first["favorable_first"] is False
    flat = dg.excursions([qt(5, 10.0, 10.01)], 10.0, 0.30, T0, T0 + timedelta(seconds=60))
    assert flat["favorable_first"] is None
    assert dg.excursions([], 10.0, 0.30, T0, T0)["mfe_r"] is None  # no quotes: empty, never estimated


def test_forward_moves_use_prevailing_executable_quote_and_stop_at_data_end() -> None:
    quotes = [qt(30, 10.3, 10.31), qt(170, 10.6, 10.5), qt(175, 9.7, 9.71)]  # 170s is crossed: ignored
    moves = dg.forward_moves(quotes, 10.0, 0.30, T0, T0 + timedelta(minutes=4))
    assert moves["move_1m_r"] == pytest.approx(1.0)
    assert moves["move_3m_r"] == pytest.approx(-1.0)
    assert moves["move_5m_r"] is None and moves["move_15m_r"] is None  # beyond the fetched quotes


def test_outcome_codes() -> None:
    t = {"exit_complete": "True", "qty": "10", "requested_qty": "10"}
    assert dg.outcome({"outcome": "skipped", "reason": "position_open"}, None) == "skipped"
    assert dg.outcome({"outcome": "non_fill", "reason": "at_signal_spread_above_cap"}, None) == "rejected"
    assert dg.outcome({"outcome": "non_fill", "reason": "timeout_stale_quote"}, None) == "unfilled"
    assert dg.outcome({"outcome": "filled", "reason": ""}, t) == "completed"
    assert dg.outcome({"outcome": "partial", "reason": ""}, {**t, "qty": "4"}) == "partial"
    assert dg.outcome({"outcome": "filled", "reason": ""}, {**t, "exit_complete": "False"}) == "incomplete_exit"


def test_buckets_stats_and_small_sample_flag() -> None:
    edges = [1, 2, 5]
    assert [dg.bucket_of(v, edges) for v in (0.5, 1, 1.99, 2, 7, None)] == ["< 1", "1–2", "1–2", "2–5", ">= 5", "unknown"]
    trades = [{"price": 1.5, "r_multiple": r} for r in (1.0, -1.0, -1.0)] + [{"price": 3.0, "r_multiple": 2.0}] * 31
    rows = dg.breakdown(trades, "price", edges)
    assert [r["bucket"] for r in rows] == ["1–2", "2–5"]
    small, big = rows
    assert small["n"] == 3 and small["inconclusive"] and small["win_rate"] == pytest.approx(1 / 3)
    assert small["avg_r"] == pytest.approx(-1 / 3) and small["median_r"] == -1.0 and small["profit_factor"] == 0.5
    assert not big["inconclusive"] and big["profit_factor"] is None  # no losses


def test_breakout_rows_carry_only_entry_time_features() -> None:
    from conftest import bar
    from momentum_bot.data.market_calendar import session_windows

    day = session_windows(datetime(2024, 3, 8).date())["premarket"].trading_date
    rows = [bar("sip", day, f"05:0{i}", 2.0 + 0.01 * i, 2.0 + 0.01 * i, 20_000) for i in range(6)]
    rows.append(bar("sip", day, "05:06", 2.20, 2.20, 100_000))
    _, brk = scan_session("sip", ("X", day, "premarket"), rows, 1.80, ScanParams())
    e = brk[-1]
    assert e.volume_ratio == pytest.approx(100_000 / 20_000)
    assert e.prior_session_high == pytest.approx(max(b.high for b in rows[:-1]))  # earlier bars only



def test_cache_only_store_never_fetches(tmp_path) -> None:  # noqa: ANN001
    from momentum_bot.backtest import Signal

    sig = Signal("X", T0.date(), "premarket", "in_sample", T0 - timedelta(minutes=1), T0, 5.0)
    store = QuoteStore(dg.CacheOnlySource(), tmp_path)  # type: ignore[arg-type]
    with pytest.raises(dg.CacheMiss):
        store.get(sig, T0, T0 + timedelta(seconds=30))
    assert not any(tmp_path.iterdir())


def test_diagnose_trade_flags_and_missing_quotes() -> None:
    strat = StrategyConfig()
    rec = {"signal_bid": 9.99, "signal_ask": 10.0, "session": "premarket"}
    t = {"entry_price": "10.0", "qty": "50", "requested_qty": "50", "entry_first_fill_utc": T0.isoformat(),
         "exit_trigger_utc": (T0 + timedelta(seconds=50)).isoformat(),
         "exit_last_fill_utc": (T0 + timedelta(seconds=50.5)).isoformat(), "exit_reason": "stop",
         "exit_complete": "True", "seconds_to_fill": "0.5", "exit_price": "9.69", "net_usd": "-15.6",
         "gross_usd": "-15.5", "fees_usd": "0.1", "r_multiple": "-1.04", "exit_qty": "50", "remaining_qty": "0",
         "realized_net_usd": "-15.6", "mark_utc": "", "mark_price": "nan", "unrealized_usd": "0.0"}
    quotes = [qt(0, 9.99, 10.0), qt(20, 10.32, 10.33), qt(50, 9.69, 9.71)]
    d = dg.diagnose_trade(rec, t, quotes, True, T0 + timedelta(minutes=17), strat, ["a.jsonl.gz", "b.jsonl.gz"])
    assert d["stopped_after_1r_favorable"] and d["fast_reversal"] and not d["near_target_reversal"]
    assert d["exit_slippage_bps"] == pytest.approx(0.0) and d["entry_slippage_bps"] == pytest.approx(0.0)
    assert d["spread_cost_usd"] == pytest.approx((0.005 + 0.01) * 50)
    assert d["realized_usd"] == -15.6 and d["marked_usd"] is None
    missing = dg.diagnose_trade(rec, t, [], False, T0, strat, [])
    assert missing["mfe_r"] is None and missing["move_1m_r"] is None and missing["quote_files"] == ""
    assert missing["exit_slippage_bps"] is None  # unknown, not assumed zero


def test_incomplete_exit_has_no_net_or_r_and_is_kept_out_of_r_stats() -> None:
    strat = StrategyConfig()
    rec = {"signal_bid": 9.99, "signal_ask": 10.0, "session": "premarket", "hour_et": 5, "outcome": "incomplete_exit",
           "reason": "filled", "quotes_cached": True}
    t = {"entry_price": "10.0", "qty": "50", "requested_qty": "50", "entry_first_fill_utc": T0.isoformat(),
         "exit_trigger_utc": (T0 + timedelta(seconds=50)).isoformat(),
         "exit_last_fill_utc": (T0 + timedelta(seconds=170)).isoformat(), "exit_reason": "time",
         "exit_complete": "False", "seconds_to_fill": "0.5", "exit_price": "nan", "net_usd": "", "r_multiple": "",
         "gross_usd": "0.0", "fees_usd": "0.0", "exit_qty": "0", "remaining_qty": "50", "realized_net_usd": "0.0",
         "mark_utc": (T0 + timedelta(seconds=170)).isoformat(), "mark_price": "9.9", "unrealized_usd": "-5.0"}
    d = dg.diagnose_trade(rec, t, [qt(0, 9.99, 10.0), qt(50, 9.9, 9.95)], True, T0 + timedelta(minutes=17), strat, [])
    assert d["net_usd"] is None and d["r_multiple"] is None and d["exit_price"] is None
    assert d["exit_slippage_bps"] is None and d["spread_cost_usd"] is None  # nothing sold: no exit cost to report
    assert (d["realized_usd"], d["marked_usd"], d["remaining_qty"]) == (0.0, -5.0, 50)
    unmarked = dg.diagnose_trade(rec, {**t, "mark_price": "nan", "unrealized_usd": "0.0"}, [], False, T0, strat, [])
    assert unmarked["marked_usd"] is None  # never shown as a zero mark
    done = {**d, "outcome": "completed", "exit_complete": True, "r_multiple": -1.0, "net_usd": -15.0, "marked_usd": None,
            "realized_usd": -15.0, "remaining_qty": 0, "spread_cost_usd": 1.0, "quote_files": "a"}
    s = dg.summarize([rec, {**rec, "outcome": "completed"}], [d, done], "in_sample", "base_cap50")
    assert (s["entries"], s["completed_trades"], s["overall"]["n"]) == (2, 1, 1)
    assert s["execution"]["incomplete_exits"] == 1 and s["execution"]["incomplete_exit_shares_unsold"] == 50
    assert s["pnl"]["marked_usd"] == -5.0 and s["pnl"]["realized_usd"] == -15.0
    assert all(b["n"] == 1 for b in s["breakdowns_entry_time"]["session"])
    assert "Entries 2; completed trades 1; incomplete exits 1" in dg.render_report(s)


def test_report_and_dashboard_are_self_contained(tmp_path) -> None:  # noqa: ANN001
    rec = {"session": "premarket", "hour_et": 5, "outcome": "completed", "reason": "filled", "quotes_cached": True}
    trade = {**rec, "r_multiple": -1.0, "exit_reason": "stop", "fill": "full", "net_usd": -15.0, "realized_usd": -15.0,
             "marked_usd": None, "gross_usd": -14.9, "fees_usd": 0.1, "spread_cost_usd": 1.0, "exit_complete": True,
             "quote_files": "a", "mfe_r": 0.2, "mae_r": -1.0, "favorable_first": None, "stopped_after_1r_favorable": False,
             "near_target_reversal": False, "fast_reversal": True}
    summary = dg.summarize([rec, {**rec, "outcome": "skipped", "reason": "position_open"}], [trade], "in_sample", "base_cap50")
    text = dg.render_report(summary)
    assert "inconclusive" in text and "hypotheses" in text and "skipped | position_open | 1" in text
    dg.write_dashboard(tmp_path / "d.html", [rec], [trade], "in_sample", "base_cap50")
    html = (tmp_path / "d.html").read_text(encoding="utf-8")
    assert "<script src" not in html and "http" not in html.replace("http://www.w3.org/2000/svg", "")
