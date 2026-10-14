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


def _scripted_run(tmp_path):  # noqa: ANN001, ANN202
    """A tiny dataset plus a real run of the corrected PR #4 engine, written the way m1-dataset and m2-backtest
    write it: one stop exit (A) and one exit that sells nothing (B)."""
    import csv
    import json

    from conftest import et

    from momentum_bot.backtest import (
        RiskConfig, config_record, run_backtest, signals_from_breakouts, summarize, with_spread_caps, write_rows,
    )

    d1, d2 = datetime(2024, 3, 8).date(), datetime(2024, 3, 11).date()
    a0, b0 = et(d1, "05:01"), et(d2, "05:01")  # signal availability (bar 05:00 completed)
    q = lambda t, bid, ask: {"t": t.isoformat().replace("+00:00", "Z"), "bp": bid, "ap": ask, "bs": 1000, "as": 1000}  # noqa: E731
    script = {"A": [q(a0 - timedelta(seconds=1), 9.99, 10.0), q(a0 + timedelta(seconds=20), 9.60, 9.62)],  # stop hit
              "B": [q(b0 - timedelta(seconds=1), 9.99, 10.0)]}  # no quote after the fill: the exit cannot sell

    class Scripted:
        request_count = bytes_received = 0

        def iter_quotes(self, symbol, feed, start, end):  # noqa: ANN001, ANN201
            return iter(script[symbol])

    rows = [{"kind": "breakout", "symbol": s, "trading_date": d.isoformat(), "session": "premarket", "sample": "in_sample",
             "sip_bar_start_utc": (t - timedelta(minutes=1)).isoformat(), "sip_signal_available_utc": t.isoformat(),
             "sip_price": "10.0", "sip_change_vs_ref": "0.5", "sip_session_volume": "500000", "sip_volume_ratio": "3",
             "sip_prior_session_high": "9.9", "sip_candidate_gate": "True"} for s, d, t in (("A", d1, a0), ("B", d2, b0))]
    with (tmp_path / "breakout_matches.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]))
        w.writeheader()
        w.writerows(rows)
    (tmp_path / "manifest.json").write_text(json.dumps({"created_at_utc": "2024-03-12T00:00:00+00:00", "code_sha": "test",
                                                        "inputs": {"nasdaqlisted_sha256": "ab" * 32}}), encoding="utf-8")
    (cfg,) = with_spread_caps([dg.SCENARIOS["base"]], [50])
    res = run_backtest(signals_from_breakouts(rows, {"in_sample"}), QuoteStore(Scripted(), tmp_path / "cache" / "backtest_quotes"), cfg)  # type: ignore[arg-type]
    bt = tmp_path / "backtest" / "in_sample" / "base_cap50"
    write_rows(bt / "trades.csv", res.trades)
    write_rows(bt / "attempts.csv", res.attempts)
    summary = {"sample": "in_sample", "code_sha": "run1", "created_at_utc": "2024-03-12T01:00:00+00:00", "signals": 2,
               "config": config_record(StrategyConfig(), RiskConfig(), [cfg]), "results": {cfg.name: summarize(res)}}
    (tmp_path / "backtest_summary_in_sample.json").write_text(json.dumps(summary, default=str), encoding="utf-8")
    return res, summarize(res)["all"]


def test_engine_to_dashboard_reconciliation_with_an_incomplete_exit(tmp_path) -> None:  # noqa: ANN001
    """End to end on the corrected PR #4 engine: backtest summary, trade ledger, diagnostics aggregates and the
    dashboard's embedded rows must agree, with the incomplete exit kept out of net P&L and R."""
    import csv
    import json
    import math
    import re

    res, engine = _scripted_run(tmp_path)
    done, open_ = (next(t for t in res.trades if t.symbol == s) for s in ("A", "B"))
    assert done.exit_complete and not open_.exit_complete and open_.exit_qty == 0 and open_.net_usd is None
    assert dg.validate_inputs(tmp_path, "in_sample", "base_cap50")["backtest_run"]["ledgers_reproduce_summary"]

    s = dg.run(tmp_path, "in_sample", "base_cap50")  # cache only from here on
    ledger = list(csv.DictReader((tmp_path / "diagnostics" / "in_sample" / "base_cap50" / "trade_ledger.csv").open(encoding="utf-8")))
    assert (s["entries"], s["completed_trades"], engine["entries"], engine["trades"]) == (2, 1, 2, 1)
    assert s["overall"]["avg_r"] == pytest.approx(engine["expectancy_r"]) == pytest.approx(done.r_multiple)
    assert s["overall"]["win_rate"] == engine["win_rate"]
    assert s["pnl"]["realized_usd"] == pytest.approx(engine["net_usd"] + engine["incomplete_exits"]["realized_net_usd"])
    assert s["pnl"]["marked_usd"] == pytest.approx(engine["incomplete_exits"]["unrealized_mark_usd"]) == pytest.approx(
        (9.99 - open_.entry_price) * open_.remaining_qty)
    assert s["execution"]["incomplete_exits"] == engine["incomplete_exits"]["count"] == 1
    row_b = next(r for r in ledger if r["symbol"] == "B")
    assert (row_b["net_usd"], row_b["r_multiple"], row_b["exit_price"], row_b["spread_cost_usd"]) == ("", "", "", "")
    assert row_b["outcome"] == "incomplete_exit" and row_b["remaining_qty"] == str(open_.remaining_qty)
    html = (tmp_path / "diagnostics" / "in_sample" / "base_cap50" / "dashboard.html").read_text(encoding="utf-8")
    data = json.loads(re.search(r"const D=(.*?);\n", html).group(1))  # type: ignore[union-attr]
    completed = [t for t in data["trades"] if t["r_multiple"] is not None]  # the dashboard's own KPI filter
    assert len(data["trades"]) == 2 and len(completed) == 1
    assert sum(t["net_usd"] for t in completed) == pytest.approx(engine["net_usd"])
    assert [t["marked_usd"] for t in data["trades"] if t["r_multiple"] is None] == [pytest.approx(s["pnl"]["marked_usd"])]
    assert not any(isinstance(v, float) and math.isnan(v) for t in data["trades"] for v in t.values())


def _edit_csv(path, fn) -> None:  # noqa: ANN001
    import csv

    with path.open(newline="", encoding="utf-8") as fh:
        rows = list(csv.DictReader(fh))
    rows, header = fn(rows)
    with path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=header, lineterminator="\n")
        w.writeheader()
        w.writerows(rows)


def test_validation_records_provenance(tmp_path) -> None:  # noqa: ANN001
    _scripted_run(tmp_path)
    pv = dg.validate_inputs(tmp_path, "in_sample", "base_cap50")
    assert pv["backtest_run"]["code_sha"] == "run1" and pv["backtest_run"]["trades_rows"] == 2
    assert pv["backtest_run"]["trades_sha256"] == dg.sha256_of(tmp_path / "backtest/in_sample/base_cap50/trades.csv")
    assert pv["dataset"]["input_sha256"] == {"nasdaqlisted_sha256": "ab" * 32}
    assert pv["configuration"]["scenario"]["spread_cap_bps"] == 50.0
    assert pv["current_code_fields_not_recorded_by_backtest_run"] == []
    s = {"sample": "in_sample", "scenario": "base_cap50", "signals": 2, "trades": 2, "min_bucket_n": 30, "code_sha": "gen1",
         "provenance": pv, **{k: v for k, v in dg.summarize([], [], "in_sample", "base_cap50").items()
                               if k not in ("signals", "trades")}}
    text = dg.render_report(s)
    assert "Generated by code** `gen1`" in text and "can be older than the repository HEAD" in text
    assert "from code `run1`" in text


@pytest.mark.parametrize(("break_it", "message"), [
    (lambda p: (p / "backtest_summary_in_sample.json").unlink(), "missing required inputs"),
    (lambda p: _edit_csv(p / "backtest/in_sample/base_cap50/trades.csv",
                         lambda r: ([{**x, "realized_net_usd": "1.0"} for x in r], list(r[0]))), "do not reproduce"),
    (lambda p: _edit_csv(p / "backtest/in_sample/base_cap50/trades.csv",  # a pre-fix ledger without exit_qty
                         lambda r: ([{k: v for k, v in x.items() if k != "exit_qty"} for x in r],
                                    [k for k in r[0] if k != "exit_qty"])), "columns do not match the current execution model"),
    (lambda p: _edit_csv(p / "backtest/in_sample/base_cap50/attempts.csv",
                         lambda r: ([{**x, "scenario": "stress_cap50"} for x in r[:1]] + r[1:], list(r[0]))),
     "rows from other runs"),
    (lambda p: _edit_csv(p / "backtest/in_sample/base_cap50/trades.csv", lambda r: (r[:1], list(r[0]))),
     "do not pair one to one"),
    (lambda p: _edit_csv(p / "breakout_matches.csv", lambda r: (r[:1], list(r[0]))), "the dataset changed"),
])
def test_validation_rejects_stale_or_mixed_inputs(tmp_path, break_it, message) -> None:  # noqa: ANN001
    _scripted_run(tmp_path)
    break_it(tmp_path)
    with pytest.raises(dg.InputMismatch, match=message):
        dg.validate_inputs(tmp_path, "in_sample", "base_cap50")


def test_validation_rejects_a_configuration_change(tmp_path) -> None:  # noqa: ANN001
    _scripted_run(tmp_path)
    with pytest.raises(dg.InputMismatch, match="strategy.stop_pct: backtest run used 0.03, current code has 0.04"):
        dg.validate_inputs(tmp_path, "in_sample", "base_cap50", StrategyConfig(stop_pct=0.04))
    import shutil

    shutil.copytree(tmp_path / "backtest/in_sample/base_cap50", tmp_path / "backtest/in_sample/base_cap100")
    with pytest.raises(dg.InputMismatch, match="no scenario 'base_cap100'"):  # ledgers from a run the summary lacks
        dg.validate_inputs(tmp_path, "in_sample", "base_cap100")


def test_missing_quotes_stay_optional(tmp_path) -> None:  # noqa: ANN001
    import shutil

    _scripted_run(tmp_path)
    shutil.rmtree(tmp_path / "cache" / "backtest_quotes")
    dg.validate_inputs(tmp_path, "in_sample", "base_cap50")  # quotes are not a required input
    s = dg.run(tmp_path, "in_sample", "base_cap50")
    assert s["quote_cache"]["evaluated_with_cached_quotes"] == 0 and s["lifecycle"]["mfe_r"]["n"] == 0  # empty, not invented


def test_cli_refuses_inconsistent_inputs(tmp_path, capsys) -> None:  # noqa: ANN001
    from momentum_bot import cli

    _scripted_run(tmp_path)
    _edit_csv(tmp_path / "backtest/in_sample/base_cap50/trades.csv", lambda r: (r[:1], list(r[0])))
    assert cli.main(["m2-diagnostics", "--dataset", str(tmp_path)]) == cli.EXIT_USAGE
    assert "do not pair one to one" in capsys.readouterr().err
    assert not (tmp_path / "diagnostics_in_sample_base_cap50.json").exists()  # nothing written from bad inputs
