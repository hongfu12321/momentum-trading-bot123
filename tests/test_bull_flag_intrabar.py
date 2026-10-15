from dataclasses import replace
from datetime import date, timedelta

from conftest import et

from momentum_bot import bullflag_intrabar as bi
from momentum_bot.backtest import SCENARIOS, Quote, RiskConfig, StrategyConfig
from momentum_bot.data.market_calendar import session_windows
from momentum_bot.data.provider import Bar

DAY = date(2024, 3, 8)
PM = session_windows(DAY)["premarket"]
BASE = SCENARIOS["base"]
P = bi.IntrabarParams()


def ob(hhmm: str, o: float, h: float, low: float, c: float, v: int, sym: str = "FLG") -> Bar:
    return Bar(sym, "sip", et(DAY, hhmm), o, h, low, c, v)


def at(hhmm: str, s: float = 0.0):  # noqa: ANN201
    """ET time on DAY; "HH:MM" or "HH:MM:SS"."""
    if hhmm.count(":") == 2:
        hhmm, sec = hhmm.rsplit(":", 1)
        s += int(sec)
    return et(DAY, hhmm) + timedelta(seconds=s)


def pattern(start: str = "04:00", sym: str = "FLG") -> list[Bar]:
    """Candles 1-9: two quiet bars, a 3-bar flagpole (3-5), a flag (6-8) whose highest high is candle 7,
    and candle 9, which trades above candle 7's High."""
    h, m = map(int, start.split(":"))
    t = lambda i: f"{h + (m + i) // 60:02d}:{(m + i) % 60:02d}"  # noqa: E731
    rows = [(2.00, 2.01, 2.00, 2.00, 20_000), (2.00, 2.01, 1.99, 2.00, 20_000),
            (2.00, 2.04, 2.00, 2.04, 50_000), (2.04, 2.08, 2.03, 2.08, 50_000), (2.08, 2.12, 2.07, 2.11, 50_000),
            (2.11, 2.11, 2.08, 2.09, 10_000), (2.09, 2.115, 2.07, 2.10, 10_000), (2.10, 2.11, 2.08, 2.09, 10_000),
            (2.09, 2.16, 2.09, 2.15, 30_000)]
    return [ob(t(i), *r, sym=sym) for i, r in enumerate(rows)]


def q(t, bid: float, ask: float, bs: int = 5_000, asz: int = 5_000) -> Quote:  # noqa: ANN001
    return Quote(t, bid, ask, bs, asz)


def setup_of(bars: list[Bar]) -> bi.Setup:
    """The first setup (candle 7 as reference); later bars may legitimately form further setups."""
    return bi.detect_setups("FLG", bars, PM)[0]


def flow(start: str, end: str, bid: float, ask: float, step_s: int = 5, **kw: int) -> list[Quote]:
    t, stop, out = at(start), at(end), []
    while t < stop:
        out.append(q(t, bid, ask, **kw))
        t += timedelta(seconds=step_s)
    return out


# ---------- setups ----------

def test_reference_candle_is_the_flags_highest_high_and_known_after_it_completes() -> None:
    s = setup_of(pattern())
    assert s.detail["ref_bar_start_utc"] == at("04:06").isoformat()  # candle 7, not a fixed index
    assert (s.level, s.stop) == (2.115, 2.07)
    assert s.known_utc == at("04:07")  # the setup bar (candle 7) has completed
    assert s.expires_utc == at("04:10")


def test_duplicate_evaluations_of_the_same_reference_candle_are_one_setup() -> None:
    sets = bi.detect_setups("FLG", pattern(), PM)
    assert [x.setup_id for x in sets] == [f"FLG|{DAY}|premarket|{at('04:06').isoformat()}"]


def test_missing_sip_bar_inside_the_pattern_is_never_filled() -> None:
    bars = [b for b in pattern() if b.timestamp_utc != at("04:04")]
    assert bi.detect_setups("FLG", bars, PM) == []


def test_no_look_ahead_future_bars_do_not_change_setups_or_the_trigger() -> None:
    full = pattern()
    early = bi.detect_setups("FLG", full[:8], PM)  # up to candle 8 only
    later = bi.detect_setups("FLG", full, PM)
    assert [x.setup_id for x in early] == [x.setup_id for x in later[:1]]
    changed = full[:8] + [ob("04:08", 2.09, 2.30, 1.50, 1.60, 900_000)]  # a different candle 9
    t1, _, _ = bi.first_trigger(later[0], full, None)
    t2, _, _ = bi.first_trigger(bi.detect_setups("FLG", changed, PM)[0], changed, None)
    assert t1 == t2 == at("04:08")


def test_session_boundaries_expire_setups_and_respect_the_entry_cutoff() -> None:
    late = pattern("09:15")  # candle 9 at 09:23, after the 09:20 entry cutoff
    s = bi.detect_setups("FLG", late, PM)[0]
    assert s.expires_utc <= PM.end_utc
    (r,) = [x for x in bi.run_portfolio([s], {("FLG", str(DAY), "premarket"): late}, None, BASE)
            if x.outcome != "no_trigger"]
    assert (r.outcome, r.reason) == ("skipped", "after_entry_cutoff")


# ---------- trigger and entry ----------

def test_breakout_during_candle_9_using_candle_7_as_reference_from_quotes() -> None:
    bars = pattern()
    s = setup_of(bars)
    quotes = flow("04:06:58", "04:08", 2.10, 2.11) + [q(at("04:08", 20), 2.12, 2.125)] + flow("04:08:25", "04:30", 2.13, 2.135)
    t, _, k = bi.first_trigger(s, bars, quotes)
    assert t == at("04:08", 20) and bars[k].timestamp_utc == at("04:08")  # inside candle 9, before it closes
    r = bi.simulate_nbbo(s, t, bars, quotes, BASE, P, RiskConfig())
    assert r.outcome == "traded" and r.mode == "nbbo_proxy" and r.sequencing == "proxy"
    assert r.entry_first_fill_utc >= (t + BASE.latency).isoformat()  # entry timing: never before arrival
    assert r.entry_price == 2.125 and r.entry_price > s.level  # the Ask prevailing on arrival, never the level


def test_touching_the_reference_high_is_not_a_breakout() -> None:
    bars = pattern()[:8] + [ob("04:08", 2.09, 2.115, 2.09, 2.10, 30_000)]  # High equals candle 7's High
    s = setup_of(bars)
    quotes = flow("04:06:58", "04:12", 2.115, 2.12)  # Bid at the level, never above it
    assert bi.first_trigger(s, bars, None)[0] is None
    assert bi.first_trigger(s, bars, quotes)[0] is None


def test_stale_or_crossed_quotes_neither_trigger_nor_stop() -> None:
    bars = pattern()
    s = setup_of(bars)
    crossed = [q(at("04:08", 10), 2.20, 2.15)]  # Bid above Ask: not executable
    assert bi.first_trigger(s, bars, flow("04:06:58", "04:08", 2.10, 2.11) + crossed)[0] is None
    quotes = (flow("04:06:58", "04:08", 2.10, 2.11) + [q(at("04:08", 20), 2.12, 2.125)]
              + flow("04:08:25", "04:09", 2.13, 2.135) + [q(at("04:09", 1), 2.00, 1.90)]  # crossed, below the stop
              + flow("04:09:05", "04:30", 2.13, 2.135))
    r = bi.simulate_nbbo(s, at("04:08", 20), bars, quotes, BASE, P, RiskConfig())
    assert r.exit_reason != "stop"


# ---------- stop ----------

def _entered(after: list[Quote], bars: list[Bar] | None = None) -> tuple[bi.Setup, bi.Result]:
    bars = bars or pattern()
    s = setup_of(bars)
    quotes = flow("04:06:58", "04:08", 2.10, 2.11) + [q(at("04:08", 20), 2.12, 2.125)] + after
    return s, bi.simulate_nbbo(s, at("04:08", 20), bars, quotes, BASE, P, RiskConfig())


def test_stop_at_the_reference_low_sells_at_the_bid_after_latency() -> None:
    s, r = _entered(flow("04:08:25", "04:08:40", 2.13, 2.135) + [q(at("04:08", 40), 2.07, 2.08)]
                    + flow("04:08:41", "04:20", 2.06, 2.07))
    assert s.stop == 2.07 and r.exit_reason == "stop"
    assert r.exit_trigger_utc == at("04:08", 40).isoformat()  # stop timing: the first Bid at or below 2.07
    assert r.exit_last_fill_utc >= (at("04:08", 40) + BASE.latency).isoformat()  # sell timing
    assert r.exit_price == 2.07  # the prevailing Bid at order arrival, not the stop by assumption


def test_gap_through_the_stop_fills_at_the_executable_bid() -> None:
    _, r = _entered(flow("04:08:25", "04:08:40", 2.13, 2.135) + flow("04:08:40", "04:20", 1.95, 1.96))
    assert r.exit_reason == "stop" and r.exit_price == 1.95 and r.r_multiple < -1


def test_stop_seen_before_the_red_candle_completes_takes_priority() -> None:
    bars = pattern() + [ob("04:09", 2.15, 2.16, 2.05, 2.06, 30_000)]  # red, completes at 04:10
    _, r = _entered(flow("04:08:25", "04:09:30", 2.13, 2.135) + flow("04:09:30", "04:20", 2.06, 2.07), bars)
    assert r.exit_reason == "stop" and r.exit_trigger_utc == at("04:09", 30).isoformat()


# ---------- red candle ----------

def test_first_fully_completed_red_candle_after_entry_triggers_the_exit() -> None:
    bars = pattern() + [ob("04:09", 2.15, 2.18, 2.14, 2.17, 20_000), ob("04:10", 2.17, 2.17, 2.12, 2.13, 20_000)]
    _, r = _entered(flow("04:08:25", "04:20", 2.13, 2.135), bars)
    assert r.exit_reason == "red_candle"
    assert r.exit_trigger_utc == at("04:11").isoformat()  # known when the 04:10 candle completes
    assert r.exit_last_fill_utc >= (at("04:11") + BASE.latency).isoformat()


def test_red_entry_minute_candle_is_not_eligible() -> None:
    bars = pattern()[:8] + [ob("04:08", 2.11, 2.16, 2.09, 2.10, 30_000),  # red candle 9 holds the entry fill
                            ob("04:09", 2.10, 2.14, 2.10, 2.13, 20_000), ob("04:10", 2.13, 2.13, 2.11, 2.12, 20_000)]
    _, r = _entered(flow("04:08:25", "04:20", 2.13, 2.135), bars)
    assert r.exit_reason == "red_candle" and r.exit_trigger_utc == at("04:11").isoformat()


def test_no_red_candle_holds_until_the_session_flatten_time() -> None:
    bars = pattern("09:05") + [ob(f"09:{m}", 2.15, 2.17, 2.15, 2.16, 20_000) for m in range(14, 30)]
    s = setup_of(bars)
    t, _, k = bi.first_trigger(s, bars, None)
    r = bi.simulate_ohlc(s, k, bars, BASE, replace(P, max_hold=timedelta(hours=1)), RiskConfig(), P.ohlc_cost_bps)
    assert t == at("09:13") and r.exit_reason == "session_end" and r.exit_trigger_utc == at("09:28").isoformat()
    assert r.mode == "ohlc_approx" and r.sequencing == "approximate"


# ---------- liquidity, ambiguity ----------

def test_sparse_liquidity_gives_partial_entries_and_recorded_unsold_shares() -> None:
    bars = pattern()
    s = setup_of(bars)
    quotes = (flow("04:06:58", "04:08", 2.10, 2.11) + [q(at("04:08", 20), 2.12, 2.125, asz=100)]
              + flow("04:08:21", "04:08:40", 2.13, 2.135, asz=100, bs=100)
              + flow("04:08:40", "04:30", 2.06, 2.07, bs=0))  # stop with no displayed Bid size
    r = bi.simulate_nbbo(s, at("04:08", 20), bars, quotes, BASE, P, RiskConfig())
    assert r.qty == 100 and "partial_entry" in r.notes
    assert r.exit_reason == "stop" and not r.exit_complete and r.remaining_qty == 100 and r.net_usd is None


def test_same_minute_entry_and_stop_is_labelled_uncertain() -> None:
    bars = pattern()[:8] + [ob("04:08", 2.09, 2.16, 2.05, 2.10, 30_000)]  # breaks out and trades below 2.07
    s = setup_of(bars)
    r = bi.simulate_ohlc(s, 8, bars, BASE, P, RiskConfig(), P.ohlc_cost_bps)
    assert r.sequencing == "uncertain" and r.exit_reason == "stop" and "same_minute_entry_and_stop" in r.notes


def test_nonpositive_initial_risk_is_rejected() -> None:
    bars = pattern()
    s = replace(setup_of(bars), stop=9.0)
    r = bi.simulate_ohlc(s, 8, bars, BASE, P, RiskConfig(), P.ohlc_cost_bps)
    assert (r.outcome, r.reason) == ("rejected", "nonpositive_initial_risk")


# ---------- portfolio ----------

def _two_patterns() -> tuple[list[Bar], list[bi.Setup]]:
    first = pattern("04:00")
    gap = [ob(f"04:{m:02d}", 2.15, 2.16, 2.10, 2.12, 20_000) for m in range(9, 12)]  # a red candle at 04:09
    second = [replace(b, open=b.open + 0.2, high=b.high + 0.2, low=b.low + 0.2, close=b.close + 0.2)
              for b in pattern("04:12")]
    bars = first + gap + second
    refs = {at("04:06").isoformat(), at("04:18").isoformat()}  # candle 7 of each pattern
    return bars, [x for x in bi.detect_setups("FLG", bars, PM) if x.detail["ref_bar_start_utc"] in refs]


def test_new_setups_allow_same_symbol_reentry_but_one_position_at_a_time() -> None:
    bars, sets = _two_patterns()
    assert len(sets) == 2 and sets[0].setup_id != sets[1].setup_id
    res = bi.run_portfolio(sets, {("FLG", str(DAY), "premarket"): bars}, None, BASE)
    traded = [r for r in res if r.outcome == "traded"]
    assert len(traded) == 2 and traded[0].exit_last_fill_utc <= traded[1].trigger_utc
    assert bi.summarize(res, len(sets))["same_symbol_reentries"] == 1


def test_a_setup_that_triggers_while_a_position_is_open_is_consumed() -> None:
    bars = pattern()
    s = setup_of(bars)
    twin = replace(s, setup_id=s.setup_id + "#other-symbol-view")
    res = bi.run_portfolio([s, twin], {("FLG", str(DAY), "premarket"): bars}, None, BASE)
    assert sorted((r.outcome, r.reason) for r in res) == [("skipped", "position_open"), ("traded", "")]


def test_existing_daily_entry_limit_applies() -> None:
    bars, sets = _two_patterns()
    res = bi.run_portfolio(sets, {("FLG", str(DAY), "premarket"): bars}, None, BASE,
                           risk=replace(RiskConfig(), max_entries_per_day=1))
    assert [(r.outcome, r.reason) for r in res if r.outcome != "traded"] == [("skipped", "daily_entry_limit")]


def test_frozen_baseline_configuration_is_untouched() -> None:
    assert StrategyConfig() == StrategyConfig(entry_trigger="candle_close_confirmation", stop_pct=0.03, target_r=2.0,
                                              max_hold=timedelta(minutes=15))
    assert (BASE.latency, BASE.spread_cap_bps, BASE.entry_timeout) == (timedelta(milliseconds=500), 50.0,
                                                                        timedelta(seconds=10))
    assert RiskConfig() == RiskConfig(3_000.0, 15.0, 0.25, 45.0, 5, 3)


def test_fetch_missing_downloads_only_uncovered_triggered_setups_into_a_separate_cache(tmp_path) -> None:  # noqa: ANN001
    bars = pattern() + [ob(f"04:{m:02d}", 2.15, 2.17, 2.14, 2.16, 20_000) for m in range(9, 40)]
    sets = bi.detect_setups("FLG", bars, PM)
    quiet = replace(sets[0], setup_id="never-triggers", level=99.0)

    class Source:
        request_count = 0

        def iter_quotes(self, symbol, feed, start, end):  # noqa: ANN001, ANN201
            self.request_count += 1
            return [{"t": (start + timedelta(seconds=1)).isoformat(), "bp": 2.12, "ap": 2.13, "bs": 100, "as": 100}]

    src, cache = Source(), tmp_path / "research_quotes"
    index = bi.QuoteIndex(tmp_path / "dataset_cache")  # empty dataset cache, never written to
    out = bi.fetch_missing([sets[0], quiet], {("FLG", str(DAY), "premarket"): bars}, index, cache, src)
    assert out == {"windows_fetched": 1, "windows_failed": 0} and src.request_count == 1
    assert not (tmp_path / "dataset_cache").exists() and len(list(cache.glob("*.jsonl.gz"))) == 1
    again = bi.fetch_missing([sets[0]], {("FLG", str(DAY), "premarket"): bars}, bi.QuoteIndex(cache), cache, src)
    assert again["windows_fetched"] == 0 and src.request_count == 1  # covered now: no second request


def test_untriggered_setups_are_reported_not_dropped() -> None:
    bars = pattern()[:8] + [ob("04:08", 2.09, 2.11, 2.09, 2.10, 30_000)]  # never above candle 7's High
    res = bi.run_portfolio(bi.detect_setups("FLG", bars, PM), {("FLG", str(DAY), "premarket"): bars}, None, BASE)
    assert res and {(r.outcome, r.mode) for r in res} == {("no_trigger", "ohlc_approx")}


def test_quote_index_reads_windows_that_end_at_midnight_utc(tmp_path) -> None:  # noqa: ANN001
    import gzip

    (tmp_path / "AH_20260612T234157_000000.jsonl.gz").write_bytes(gzip.compress(b""))  # after hours: 19:41 to 20:00 ET
    qi = bi.QuoteIndex(tmp_path)
    start = et(date(2026, 6, 12), "19:41") + timedelta(seconds=57)
    assert qi.covers("AH", start, et(date(2026, 6, 12), "20:00"))
