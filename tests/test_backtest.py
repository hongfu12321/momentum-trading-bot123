import math
from datetime import date, datetime, timedelta, timezone

import pytest

from momentum_bot.backtest import (
    EXIT_SLACK, SCENARIOS, Attempt, Quote, RiskConfig, Signal, StrategyConfig, Trade, run_backtest, signals_from_breakouts, simulate_signal,
    summarize,
)

DAY = date(2024, 3, 8)
BAR = datetime(2024, 3, 8, 10, 0, tzinfo=timezone.utc)  # 05:00 ET premarket
AVAIL = BAR + timedelta(minutes=1)
BASE = SCENARIOS["base"]


def sig(symbol: str = "MOMO", bar: datetime = BAR) -> Signal:
    return Signal(symbol, DAY, "premarket", "in_sample", bar, bar + timedelta(minutes=1), 5.0)


def qt(sec: float, bid: float, ask: float, size: int = 10_000, base: datetime = AVAIL) -> Quote:
    return Quote(base + timedelta(seconds=sec), bid, ask, size, size)


def run(quotes: list[Quote], hold: list[Quote] | None = None, cfg=BASE, s: Signal | None = None):  # noqa: ANN001, ANN201
    return simulate_signal(s or sig(), quotes, lambda: hold or [], cfg, StrategyConfig(), RiskConfig())


def test_signal_cannot_be_available_before_its_bar_completes() -> None:
    with pytest.raises(ValueError, match="completes"):
        Signal("X", DAY, "premarket", "in_sample", BAR, BAR + timedelta(seconds=30), 5.0)


def test_entry_never_fills_before_bar_completion_plus_latency() -> None:
    quotes = [qt(-50, 5.00, 5.01), qt(-1, 5.00, 5.01), qt(0.2, 5.00, 5.01)]  # -50s is inside the trigger bar
    t = run(quotes, hold=[qt(60, 5.32, 5.33)])  # target = 5.01 * 1.06
    assert isinstance(t, Trade)
    first_fill = datetime.fromisoformat(t.entry_first_fill_utc)
    assert first_fill >= AVAIL + BASE.latency and first_fill == AVAIL + BASE.latency
    assert t.entry_price == 5.01 and t.exit_reason == "target" and t.exit_price == 5.32
    stress = run(quotes, hold=[qt(60, 5.32, 5.33)], cfg=SCENARIOS["stress"])
    assert datetime.fromisoformat(stress.entry_first_fill_utc) >= AVAIL + timedelta(seconds=2)
    assert stress.entry_price > 5.01 and stress.exit_price < 5.32  # adverse slippage both ways


def test_stale_quotes_never_fill() -> None:
    assert run([qt(-5, 5.00, 5.01)]).reason == "at_signal_stale_quote"  # 5s old at signal time
    late = run([qt(-2.8, 5.00, 5.01)])  # fresh at the signal (2.8s) but 3.3s old when the order arrives
    assert isinstance(late, Attempt) and late.reason == "timeout_stale_quote"
    refreshed = run([qt(-2.8, 5.00, 5.01), qt(4, 5.00, 5.01)], hold=[qt(60, 5.0, 5.01)])
    assert isinstance(refreshed, Trade) and refreshed.seconds_to_fill == 4


def test_locked_and_crossed_quotes_never_fill_or_trigger_exits() -> None:
    assert run([qt(-1, 5.00, 5.00)]).reason == "at_signal_locked_quote"
    assert run([qt(-1, 5.01, 5.00)]).reason == "at_signal_crossed_quote"
    assert run([qt(-1, 0, 5.00)]).reason == "at_signal_one_sided_quote"
    after = run([qt(-1, 5.00, 5.01), qt(0.4, 5.01, 5.01), qt(0.6, 5.02, 5.01)])  # only locked/crossed after arrival
    assert after.reason in ("timeout_locked_quote", "timeout_crossed_quote")
    # A crossed quote far below the stop is ignored; the exit happens on time at the next executable bid.
    t = run([qt(-1, 5.00, 5.01)], hold=[qt(60, 4.00, 3.90), qt(15 * 60 + 1, 5.00, 5.01)])
    assert isinstance(t, Trade) and t.exit_reason == "time" and t.exit_price == 5.00


def test_spread_cap_partial_fills_and_costs() -> None:
    wide = [qt(-1, 5.00, 5.06)]  # 119 bps
    assert run(wide).reason == "at_signal_spread_above_cap"
    assert isinstance(run(wide, hold=[qt(60, 5.0, 5.06)], cfg=SCENARIOS["idealized"]), Trade)
    # 99 shares = min($15 / (limit * 3%), $750 / limit) at limit 5.01 * 1.002; 100 are displayed.
    t = run([qt(-1, 5.00, 5.01, size=100)], hold=[qt(60, 4.80, 4.81)])
    assert (t.requested_qty, t.qty) == (99, 99)
    assert t.exit_reason == "stop" and t.net_usd < t.gross_usd < 0
    assert t.fees_usd == pytest.approx(t.exit_price * t.qty * 27.80e-6 + t.qty * 0.000166)
    partial = run([qt(-1, 5.00, 5.01, size=50)], hold=[qt(60, 4.80, 4.81)])
    assert partial.qty == 50 < partial.requested_qty  # the unfilled remainder expires at the entry timeout


class FakeStore:
    def __init__(self, quotes: dict[str, list[Quote]]) -> None:
        self.quotes, self.calls = quotes, 0

    def get(self, s: Signal, start: datetime, end: datetime) -> list[Quote]:
        self.calls += 1
        return [q for q in self.quotes.get(s.symbol, []) if start <= q.t < end]


def test_portfolio_loop_one_position_and_daily_limits() -> None:
    b2 = BAR + timedelta(minutes=5)
    store = FakeStore({
        "AAA": [qt(-1, 5.00, 5.01), qt(10 * 60, 4.80, 4.81)],  # stopped out at +10 min
        "BBB": [qt(-1, 5.00, 5.01, base=b2 + timedelta(minutes=1))],  # signal while AAA is still open
    })
    res = run_backtest([sig("BBB", b2), sig("AAA")], store, BASE)
    assert [t.symbol for t in res.trades] == ["AAA"]
    assert {(a.symbol, a.outcome, a.reason) for a in res.attempts} == {("AAA", "filled", ""),
                                                                      ("BBB", "skipped", "position_open")}
    summary = summarize(res)
    assert summary["premarket"]["trades"] == 1 and summary["all"]["skipped"] == {"position_open": 1}

    many = {f"S{i}": [qt(-1, 5.00, 5.01, base=BAR + timedelta(minutes=20 * i + 1)),
                      qt(60, 4.80, 4.81, base=BAR + timedelta(minutes=20 * i + 1))] for i in range(6)}
    signals = [sig(s, BAR + timedelta(minutes=20 * i)) for i, s in enumerate(many)]
    res = run_backtest(signals, FakeStore(many), BASE, risk=RiskConfig(daily_loss_limit_usd=1e9))
    assert len(res.trades) == 3 and [a.reason for a in res.attempts[3:]] == ["loss_streak_pause"] * 3
    res = run_backtest(signals, FakeStore(many), BASE)  # each stop loses about $21: the $45 limit binds first
    assert len(res.trades) == 3 and res.attempts[-1].reason == "daily_loss_limit"


def test_signals_from_breakouts_uses_signal_available_time_and_sample_filter() -> None:
    rows = [{"symbol": "A", "trading_date": "2024-03-08", "session": "premarket", "sample": "in_sample",
             "sip_bar_start_utc": BAR.isoformat(), "sip_signal_available_utc": AVAIL.isoformat(),
             "sip_candidate_gate": "True", "sip_price": "5.0"},
            {"symbol": "B", "trading_date": "2024-03-08", "session": "premarket", "sample": "out_of_sample",
             "sip_bar_start_utc": BAR.isoformat(), "sip_candidate_gate": "True", "sip_price": "5.0"},
            {"symbol": "C", "trading_date": "2024-03-08", "session": "premarket", "sample": "in_sample",
             "sip_bar_start_utc": "", "sip_candidate_gate": "", "sip_price": ""}]
    out = signals_from_breakouts(rows, {"in_sample"})
    assert [(s.symbol, s.available_utc) for s in out] == [("A", AVAIL)]
    assert signals_from_breakouts(rows, {"out_of_sample"})[0].available_utc == AVAIL  # derived from bar start


def test_cli_requires_explicit_confirmation_for_out_of_sample(tmp_path, capsys) -> None:  # noqa: ANN001
    from momentum_bot.cli import EXIT_USAGE, main

    (tmp_path / "breakout_matches.csv").write_text("kind\n", encoding="utf-8")
    assert main(["m2-backtest", "--dataset", str(tmp_path), "--sample", "out_of_sample"]) == EXIT_USAGE
    assert "--confirm-out-of-sample" in capsys.readouterr().err


class RawSource:
    def __init__(self, rows: list[dict]) -> None:
        self.rows, self.request_count, self.bytes_received = rows, 0, 0

    def iter_quotes(self, symbol, feed, start, end):  # noqa: ANN001, ANN201
        self.request_count += 1
        yield from self.rows


def test_quote_store_sorts_dedupes_clips_and_caches(tmp_path) -> None:  # noqa: ANN001
    from momentum_bot.backtest import QuoteStore

    def raw(sec: float, bid: float) -> dict:
        t = AVAIL + timedelta(seconds=sec)
        return {"t": t.strftime("%Y-%m-%dT%H:%M:%S.%f") + "001Z", "bp": bid, "ap": bid + 0.01, "bs": 100, "as": 100}

    src = RawSource([raw(5, 5.02), raw(1, 5.00), raw(1, 5.00), raw(-10, 4.0), raw(40, 6.0)])
    store = QuoteStore(src, tmp_path)
    got = store.get(sig(), AVAIL - timedelta(seconds=3), AVAIL + timedelta(seconds=30))
    assert [(q.t - AVAIL).total_seconds() for q in got] == [1.0, 5.0]
    assert store.get(sig(), AVAIL - timedelta(seconds=3), AVAIL + timedelta(seconds=30)) == got
    assert src.request_count == 1  # second read comes from the local cache


def test_spread_cap_variants_and_in_sample_selection_rule() -> None:
    from momentum_bot.backtest import select_spread_cap, with_spread_caps

    names = [c.name for c in with_spread_caps(SCENARIOS.values(), [50, 100])]
    assert names == ["idealized", "base_cap50", "base_cap100", "stress_cap50", "stress_cap100"]
    res = {"base_cap50": {"all": {"trades": 10, "expectancy_r": 0.9}},  # too few trades to be chosen
           "base_cap100": {"all": {"trades": 40, "expectancy_r": -0.1}},
           "base_cap150": {"all": {"trades": 60, "expectancy_r": -0.1}}}
    assert select_spread_cap(res, [50, 100, 150])["selected_spread_cap_bps"] == 100  # tie goes to the tighter cap
    assert select_spread_cap({}, [50])["selected_spread_cap_bps"] is None


# --- Regression: incomplete exits are never reported as realized P&L --------------------------------

def bq(sec: float, bid: float, bid_size: int, base: datetime = AVAIL) -> Quote:
    return Quote(base + timedelta(seconds=sec), bid, bid + 0.01, bid_size, 10_000)


ENTRY = [qt(-1, 5.00, 5.01, size=100)]  # 99 shares at 5.01


def test_partial_exit_separates_realized_from_marked_value() -> None:
    # Stop at +60s with 40 shares bid; repeated identical bids add no liquidity, so 59 shares stay unsold.
    t = run(ENTRY, hold=[bq(60, 4.80, 40), bq(61, 4.80, 40), bq(62, 4.80, 40)])
    assert isinstance(t, Trade) and t.exit_reason == "stop"
    assert (t.qty, t.exit_qty, t.remaining_qty, t.exit_complete) == (99, 40, 59, False)
    assert t.exit_price == 4.80
    assert t.gross_usd == pytest.approx((4.80 - 5.01) * 40)
    assert t.fees_usd == pytest.approx(4.80 * 40 * 27.80e-6 + 40 * 0.000166)  # sold shares only
    assert t.realized_net_usd == pytest.approx(t.gross_usd - t.fees_usd)
    assert t.mark_price == 4.80 and t.unrealized_usd == pytest.approx((4.80 - 5.01) * 59)
    assert t.net_usd is None and t.r_multiple is None  # cannot be mistaken for a completed trade


def test_no_exit_liquidity_sells_nothing() -> None:
    t = run(ENTRY, hold=[bq(60, 4.80, 0)])
    assert (t.exit_qty, t.remaining_qty, t.exit_complete) == (0, 99, False)
    assert math.isnan(t.exit_price) and t.gross_usd == 0 and t.fees_usd == 0 and t.realized_net_usd == 0
    trigger = datetime.fromisoformat(t.exit_trigger_utc)
    assert t.exit_last_fill_utc == t.mark_utc == (trigger + EXIT_SLACK).isoformat()
    assert t.unrealized_usd == pytest.approx((4.80 - 5.01) * 99) and t.net_usd is None


def test_exit_window_end_is_inclusive_and_later_quotes_are_never_used() -> None:
    end = 60 + EXIT_SLACK.total_seconds()  # stop triggers at +60s; the exit window ends 2 minutes later
    at_end = run(ENTRY, hold=[bq(60, 4.80, 40), bq(end, 4.70, 100)])
    assert at_end.exit_complete and at_end.exit_qty == 99 and at_end.net_usd is not None
    after = run(ENTRY, hold=[bq(60, 4.80, 40), bq(end + 0.001, 4.90, 10_000)])
    assert not after.exit_complete and after.exit_qty == 40
    assert after.mark_price == 4.80  # the 4.90 bid after the valuation deadline is ignored


def test_time_exit_boundary_and_session_end_valuation() -> None:
    # A stop-level bid exactly at the holding deadline does not trigger a stop; the time exit sells into it.
    t = run(ENTRY, hold=[bq(15 * 60 + 0.5, 4.00, 10_000)])
    assert t.exit_reason == "time" and t.exit_price == 4.00 and t.exit_complete
    # Near the close the exit window ends at the session close (14:30 UTC); nothing after it is used.
    late = BAR.replace(hour=14, minute=15)
    s, a = sig(bar=late), late + timedelta(minutes=1)
    close = datetime(2024, 3, 8, 14, 30, tzinfo=timezone.utc)
    t = run([qt(-1, 5.00, 5.01, size=100, base=a)], s=s,
            hold=[bq(11 * 60, 5.00, 0, base=a), Quote(close + timedelta(seconds=1), 5.5, 5.51, 10_000, 10_000)])
    assert t.exit_reason == "session_end" and t.exit_qty == 0
    assert t.mark_utc == close.isoformat() and t.mark_price == 5.00


def test_incomplete_exit_holds_position_for_the_session_and_is_summarized_apart() -> None:
    b2 = BAR + timedelta(minutes=30)  # after AAA's exit window, but AAA still holds shares
    store = FakeStore({"AAA": ENTRY + [bq(60, 4.80, 40)],
                       "BBB": [qt(-1, 5.00, 5.01, base=b2 + timedelta(minutes=1))]})
    res = run_backtest([sig("AAA"), sig("BBB", b2)], store, BASE)
    assert [a.reason for a in res.attempts if a.symbol == "BBB"] == ["position_open"]
    s = summarize(res)["all"]
    assert (s["entries"], s["trades"], s["net_usd"], s["expectancy_r"]) == (1, 0, 0, None)
    inc = s["incomplete_exits"]
    assert (inc["count"], inc["shares_unsold"], inc["unmarked"]) == (1, 59, 0)
    assert inc["unrealized_mark_usd"] == pytest.approx((4.80 - 5.01) * 59)


# --- Regression: displayed NBBO size is consumed, never re-used ------------------------------------

def test_repeated_identical_quotes_do_not_refill() -> None:
    t = run([qt(-1, 5.00, 5.01, size=30), qt(1, 5.00, 5.01, size=30), qt(2, 5.00, 5.01, size=30)],
            hold=[qt(60, 5.32, 5.33)])
    assert (t.requested_qty, t.qty) == (99, 30)  # previously 90: the same 30 shares counted three times


def test_quote_size_changes_and_price_levels() -> None:
    quotes = [qt(-1, 5.00, 5.01, size=30),
              qt(1, 5.00, 5.01, size=50),   # +20 shown at the same price: replenishment evidence
              qt(2, 5.00, 5.01, size=20),   # shrank: nothing new
              qt(3, 5.01, 5.02, size=30),   # new price level, inside the 5.02002 limit
              qt(4, 5.00, 5.01, size=50)]   # back to 5.01: its 50 were already taken
    t = run(quotes, hold=[qt(60, 5.32, 5.33)])
    assert t.qty == 80 and t.entry_price == pytest.approx((5.01 * 50 + 5.02 * 30) / 80)


def test_size_share_caps_cumulative_take_per_level() -> None:
    stress = SCENARIOS["stress"]  # 2 s latency, half of displayed size
    quotes = [qt(1.5, 5.00, 5.01, size=100), qt(2.5, 5.00, 5.01, size=100), qt(3, 5.00, 5.01, size=100)]
    t = run([qt(-1, 5.00, 5.01, size=100)] + quotes, hold=[qt(60, 5.40, 5.41)], cfg=stress)
    assert t.qty == 50


def test_entry_timeout_is_inclusive_and_later_liquidity_is_not_used() -> None:
    expiry = BASE.latency.total_seconds() + BASE.entry_timeout.total_seconds()
    at = run([qt(-1, 5.00, 5.01, size=30), qt(expiry, 5.00, 5.01, size=1_000)], hold=[qt(60, 5.32, 5.33)])
    assert at.qty == 99
    late = run([qt(-1, 5.00, 5.01, size=30), qt(expiry + 0.001, 5.00, 5.01, size=1_000)],
               hold=[qt(60, 5.32, 5.33)])
    assert late.qty == 30  # the remainder expired; a partial fill
