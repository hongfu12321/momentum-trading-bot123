from datetime import date, datetime, timedelta, timezone

import pytest

from momentum_bot.backtest import (
    SCENARIOS, Attempt, Quote, RiskConfig, Signal, StrategyConfig, Trade, run_backtest, signals_from_breakouts, simulate_signal,
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
