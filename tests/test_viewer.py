"""Historical replay viewer: provenance and integrity checks, accounting, chart markers, missing data, the app.

Deterministic and offline. ``replay_dataset`` runs the real PR #4 engine on scripted SIP quotes and the
real PR #5 diagnostics CLI for both samples, the way m2-backtest and m2-diagnostics write them:

- in-sample, 2024-03-08 (EST): A full fill, stop exit; F rejected at signal (its quote file later deleted,
  so diagnostics see missing quotes); C after hours, partial entry fill, target exit.
- in-sample, 2024-03-11 (EDT, first trading day after the DST change): B exit sells nothing (incomplete);
  E after hours, exit sells 10 of 49 shares (incomplete, partial sale).
- in-sample, 2024-03-12: bars and a scanner candidate but no signal; no after-hours bar file.
- out-of-sample, 2024-03-14: H target exit; J skipped (position open). 2024-03-15: bars, no signal.
"""

import csv
import gzip
import hashlib
import json
import shutil
from datetime import date, datetime, timedelta

import pytest
from conftest import et
from test_diagnostics import _edit_csv

from momentum_bot import charts, cli
from momentum_bot import diagnostics as dg
from momentum_bot.backtest import (
    SCENARIOS, QuoteStore, RiskConfig, StrategyConfig, config_record, run_backtest, signals_from_breakouts, summarize,
    with_spread_caps, write_rows,
)
from momentum_bot.data.provider import Bar
from momentum_bot.dataset import _write_bars

D1, D2, D3, D4, D5 = (date(2024, 3, d) for d in (8, 11, 12, 14, 15))
IN, OOS = "in_sample", "out_of_sample"


def flat(sym: str, d: date, hhmm: str, c: float, v: int) -> Bar:
    return Bar(sym, "sip", et(d, hhmm), c, c, c, c, v)


def _q(t: datetime, bid: float, ask: float, bs: int = 1000, as_: int = 1000) -> dict:
    return {"t": t.isoformat().replace("+00:00", "Z"), "bp": bid, "ap": ask, "bs": bs, "as": as_}


# symbol -> (trading date, session, trigger bar HH:MM ET, sample, scripted quotes relative to signal availability)
PLAN = {
    "A": (D1, "premarket", "05:00", IN, lambda a: [_q(a - timedelta(seconds=1), 9.99, 10.0),
                                                   _q(a + timedelta(seconds=20), 9.60, 9.62)]),
    "F": (D1, "premarket", "06:00", IN, lambda a: [_q(a - timedelta(seconds=1), 9.0, 10.0)]),  # 1,000 bps spread
    "C": (D1, "afterhours", "17:00", IN, lambda a: [_q(a - timedelta(seconds=1), 9.99, 10.0, as_=20),  # 20 of 49 shares
                                                    _q(a + timedelta(seconds=60), 10.70, 10.72)]),
    "B": (D2, "premarket", "05:00", IN, lambda a: [_q(a - timedelta(seconds=1), 9.99, 10.0)]),  # nothing after the fill
    "E": (D2, "afterhours", "17:00", IN, lambda a: [_q(a - timedelta(seconds=1), 9.99, 10.0),
                                                    _q(a + timedelta(seconds=30), 9.60, 9.62, bs=10)]),
    "H": (D4, "premarket", "05:00", OOS, lambda a: [_q(a - timedelta(seconds=1), 9.99, 10.0),
                                                    _q(a + timedelta(seconds=60), 10.70, 10.72)]),
    "J": (D4, "premarket", "05:00", OOS, lambda a: [_q(a - timedelta(seconds=1), 9.99, 10.0)]),  # H is open: skipped
}
BARS = {  # (date, session) -> bars written to the SIP cache; trigger candles close at the signal price 10.0
    (D1, "premarket"): [flat("A", D1, f"04:{m}", 9.8, 2000) for m in range(55, 60)] + [flat("A", D1, "05:00", 10.0, 9000)]
    + [flat("F", D1, "05:59", 9.7, 3000), flat("F", D1, "06:00", 10.0, 8000)],
    (D1, "afterhours"): [flat("C", D1, "16:59", 9.9, 1000), flat("C", D1, "17:00", 10.0, 7000)],
    (D2, "premarket"): [flat("B", D2, "05:00", 10.0, 5000)],
    (D2, "afterhours"): [flat("E", D2, "17:00", 10.0, 5000), flat("E", D2, "17:01", 9.6, 4000)],
    (D3, "premarket"): [flat("K", D3, "06:30", 3.0, 150_000)],
    (D4, "premarket"): [flat("H", D4, "05:00", 10.0, 6000), flat("J", D4, "05:00", 10.0, 6000)],
    (D5, "premarket"): [flat("Z", D5, "07:00", 2.0, 1000)],
}
DAYS = ["2024-03-08", "2024-03-11", "2024-03-12", "2024-03-13", "2024-03-14", "2024-03-15"]


def replay_dataset(tmp_path):  # noqa: ANN001, ANN201
    """Write the dataset, run the real engine per sample, then m2-diagnostics via the CLI. Returns {sample: result}."""
    rows, script = [], {}
    for sym, (d, session, hhmm, sample, quotes) in PLAN.items():
        bar = et(d, hhmm)
        avail = bar + timedelta(minutes=1)
        script[sym] = quotes(avail)
        rows.append({"kind": "breakout", "symbol": sym, "trading_date": d.isoformat(), "session": session, "sample": sample,
                     "sip_bar_start_utc": bar.isoformat(), "sip_signal_available_utc": avail.isoformat(), "sip_price": "10.0",
                     "sip_change_vs_ref": "0.5", "sip_session_volume": "500000", "sip_volume_ratio": "3",
                     "sip_prior_session_high": "9.9", "sip_candidate_gate": "True"})
    with (tmp_path / "breakout_matches.csv").open("w", newline="", encoding="utf-8") as fh:
        w = csv.DictWriter(fh, fieldnames=list(rows[0]), lineterminator="\n")
        w.writeheader()
        w.writerows(rows)
    for (d, session), bars in BARS.items():
        _write_bars(tmp_path / "cache" / "sip" / f"{d}_{session}_{hashlib.sha256(f'{d}{session}'.encode()).hexdigest()[:12]}.csv.gz", bars)
    with gzip.open(tmp_path / "candidates.csv.gz", "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh, lineterminator="\n")
        w.writerow(["feed", "symbol", "trading_date", "session", "bar_start_utc", "observed_at_utc", "price",
                    "change_vs_ref", "cumulative_volume"])
        w.writerow(["sip", "A", "2024-03-08", "premarket", et(D1, "04:58").isoformat(), et(D1, "04:59").isoformat(),
                    "9.8", "0.5", "120000"])
        w.writerow(["iex", "A", "2024-03-08", "premarket", et(D1, "04:58").isoformat(), et(D1, "04:59").isoformat(),
                    "9.8", "0.5", "1000"])
        w.writerow(["sip", "K", "2024-03-12", "premarket", et(D3, "06:30").isoformat(), et(D3, "06:31").isoformat(),
                    "3.0", "0.2", "150000"])
    (tmp_path / "manifest.json").write_text(json.dumps({
        "created_at_utc": "2024-03-16T00:00:00+00:00", "as_of_utc": "2024-03-16T00:00:00+00:00", "code_sha": "test",
        "start_date": DAYS[0], "end_date": DAYS[-1], "trading_days": DAYS, "inputs": {"nasdaqlisted_sha256": "ab" * 32},
        "chronological_split": {"in_sample": {"first": "2024-03-08", "last": "2024-03-12"},
                                "embargo": {"first": "2024-03-13", "last": "2024-03-13"},
                                "out_of_sample": {"first": "2024-03-14", "last": "2024-03-15"}}}, indent=1), encoding="utf-8")

    class Scripted:
        request_count = bytes_received = 0

        def iter_quotes(self, symbol, feed, start, end):  # noqa: ANN001, ANN201
            return iter(script[symbol])

    (cfg,) = with_spread_caps([SCENARIOS["base"]], [50])
    out = {}
    for sample in (IN, OOS):
        res = run_backtest(signals_from_breakouts(rows, {sample}),
                           QuoteStore(Scripted(), tmp_path / "cache" / "backtest_quotes"), cfg)  # type: ignore[arg-type]
        bt = tmp_path / "backtest" / sample / "base_cap50"
        write_rows(bt / "trades.csv", res.trades)
        write_rows(bt / "attempts.csv", res.attempts)
        (tmp_path / f"backtest_summary_{sample}.json").write_text(json.dumps(
            {"sample": sample, "code_sha": "run1", "created_at_utc": "2024-03-16T01:00:00+00:00",
             "signals": sum(1 for r in rows if r["sample"] == sample),
             "config": config_record(StrategyConfig(), RiskConfig(), [cfg]), "results": {cfg.name: summarize(res)}},
            indent=1, default=str), encoding="utf-8")
        out[sample] = res
    for f in (tmp_path / "cache" / "backtest_quotes").glob("F_*"):
        f.unlink()  # F's quotes are gone by the diagnostics run: its quote fields stay empty, never estimated
    assert cli.main(["m2-diagnostics", "--dataset", str(tmp_path)]) == cli.EXIT_OK
    assert cli.main(["m2-diagnostics", "--dataset", str(tmp_path), "--sample", OOS, "--confirm-out-of-sample"]) == cli.EXIT_OK
    return out


@pytest.fixture
def ds(tmp_path):  # noqa: ANN001, ANN201
    return tmp_path, replay_dataset(tmp_path)


def _ledger(p, sample=IN):  # noqa: ANN001, ANN202
    return p / "diagnostics" / sample / "base_cap50"


def _trade(res, sym):  # noqa: ANN001, ANN202
    return next(t for t in res.trades if t.symbol == sym)


# ---------- the fixture covers what it claims ----------

def test_fixture_exercises_partial_fills_incomplete_exits_and_missing_quotes(ds) -> None:  # noqa: ANN001
    _, res = ds
    a, c, b, e, h = (_trade(res[IN if s != "H" else OOS], s) for s in "ACBEH")
    assert (a.exit_reason, a.exit_complete) == ("stop", True)
    assert (c.qty, c.requested_qty, c.exit_reason, c.exit_complete) == (20, 49, "target", True)  # partial entry
    assert (b.exit_qty, b.remaining_qty, b.exit_complete) == (0, 49, False)  # exit sold nothing
    assert (e.exit_qty, e.remaining_qty, e.exit_complete) == (10, 39, False)  # exit sold part
    assert (h.exit_reason, h.exit_complete) == ("target", True)
    assert {(x.symbol, x.outcome, x.reason) for x in res[OOS].attempts} >= {("J", "skipped", "position_open")}
    assert any(x.symbol == "F" and x.reason == "at_signal_spread_above_cap" for x in res[IN].attempts)


# ---------- validated loading and accounting ----------

def test_every_trading_day_of_both_samples_is_selectable(ds) -> None:  # noqa: ANN001
    p, _ = ds
    t = charts.ReplayTables.load(p)
    assert t.checks[IN].status == t.checks[OOS].status == "ok"
    assert t.checks[IN].problems == t.checks[OOS].problems == t.checks[IN].warnings == []
    assert t.dates() == ["2024-03-08", "2024-03-11", "2024-03-12", "2024-03-14", "2024-03-15"]  # no embargo day
    assert [t.sample_of(d) for d in t.dates()] == [IN, IN, IN, OOS, OOS]


def test_daily_and_sample_totals_reconcile_with_the_backtest(ds) -> None:  # noqa: ANN001
    p, res = ds
    t = charts.ReplayTables.load(p)
    b, e = _trade(res[IN], "B"), _trade(res[IN], "E")
    d2 = charts.daily_summary(t, "2024-03-11")
    assert (d2["entries"], d2["completed_trades"], d2["incomplete_exits"], d2["net_usd_completed"]) == (2, 0, 2, 0)
    assert d2["realized_usd_incomplete"] == pytest.approx(b.realized_net_usd + e.realized_net_usd)  # E sold 10 shares
    assert d2["marked_usd_incomplete"] == pytest.approx(b.unrealized_usd + e.unrealized_usd)
    assert charts.daily_summary(t, "2024-03-12")["signals"] == 0  # a day without signals: zeros
    for sample in (IN, OOS):
        days = [d for d in t.dates() if t.sample_of(d) == sample]
        s = summarize(res[sample])["all"]
        tot = {k: sum(charts.daily_summary(t, d)[k] for d in days)
               for k in ("signals", "entries", "completed_trades", "incomplete_exits", "net_usd_completed",
                         "realized_usd_incomplete", "marked_usd_known")}
        assert (tot["signals"], tot["entries"], tot["completed_trades"], tot["incomplete_exits"]) == \
            (s["signals"], s["entries"], s["trades"], s["incomplete_exits"]["count"])
        assert tot["net_usd_completed"] == pytest.approx(s["net_usd"])
        assert tot["realized_usd_incomplete"] == pytest.approx(s["incomplete_exits"]["realized_net_usd"])
        assert tot["marked_usd_known"] == pytest.approx(s["incomplete_exits"]["unrealized_mark_usd"])


def test_audit_reconciles_every_total_and_chart_marker(ds) -> None:  # noqa: ANN001
    p, _ = ds
    rep = charts.audit(p)
    assert rep["mismatch_count"] == 0, rep["mismatches"]
    m = rep["markers"]
    assert (m["signals"], m["trigger_candles"], m["entry_fill"], m["stop"], m["target"]) == (7, 7, 5, 5, 5)
    assert (m["exit_fill"], m["unsold_remainder"]) == (4, 2)  # B sold nothing; E's remainder is marked
    assert rep["sessions"] == {"loaded": 7, "without_signals": 2, "without_trades": 2, "without_bar_file": 3}
    for sample in (IN, OOS):
        r = rep["samples"][sample]
        assert r["viewer_ledgers"] == pytest.approx(r["summary"])
        assert r["pr4_trades_csv"] == pytest.approx({k: r["summary"][k] for k in r["pr4_trades_csv"]})


def test_audit_catches_a_chart_that_disagrees_with_the_backtest(ds, monkeypatch) -> None:  # noqa: ANN001
    p, _ = ds
    real = charts.chart_events
    monkeypatch.setattr(charts, "chart_events", lambda data, sym, strat=StrategyConfig(): [
        {**e, "price": e["price"] + 0.01} if e["kind"] == "entry_fill" else e for e in real(data, sym, strat)])
    rep = charts.audit(p)
    assert rep["mismatch_count"] >= 5 and all("entry_fill marker" in x for x in rep["mismatches"][:5])


def test_viewer_check_cli(ds, capsys) -> None:  # noqa: ANN001
    p, _ = ds
    assert cli.main(["m2-viewer-check", "--dataset", str(p)]) == cli.EXIT_OK
    out = capsys.readouterr().out
    assert "mismatches: 0" in out and "in_sample: 3 dates; signals 5, entries 4, completed 2, incomplete 2" in out
    assert json.loads((p / "viewer_check.json").read_text(encoding="utf-8"))["mismatch_count"] == 0
    _edit_csv(_ledger(p) / "trade_ledger.csv", lambda r: ([{**x, "entry_price": "10.5"} for x in r], list(r[0])))
    assert cli.main(["m2-viewer-check", "--dataset", str(p)]) == cli.EXIT_OK  # in-sample refused, OOS still audited
    assert "in_sample: mismatch" in capsys.readouterr().out


# ---------- provenance and integrity: stale or mismatched data is refused ----------

def _crlf(path) -> None:  # noqa: ANN001
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))


def _first_bar_file(p, d="2024-03-08", s="premarket"):  # noqa: ANN001, ANN202
    return next((p / "cache" / "sip").glob(f"{d}_{s}_*.csv.gz"))


def _edit_json(path, fn) -> None:  # noqa: ANN001
    d = json.loads(path.read_text(encoding="utf-8"))
    fn(d)
    path.write_text(json.dumps(d, indent=1), encoding="utf-8")


CORRUPTIONS = {
    "manifest edited": (lambda p: _edit_json(p / "manifest.json", lambda d: d.update(code_sha="other")), "manifest.json changed"),
    "breakout signals edited": (lambda p: _edit_csv(p / "breakout_matches.csv", lambda r: (
        [{**x, "sip_price": "11.0"} if x["symbol"] == "A" else x for x in r], list(r[0]))), "breakout_matches.csv changed"),
    "backtest trades edited": (lambda p: _edit_csv(p / "backtest/in_sample/base_cap50/trades.csv", lambda r: (
        [{**x, "fees_usd": "0.5"} for x in r], list(r[0]))), "trades.csv changed"),
    "backtest attempts edited": (lambda p: _edit_csv(p / "backtest/in_sample/base_cap50/attempts.csv", lambda r: (
        r[:-1], list(r[0]))), "attempts.csv changed"),
    "backtest summary edited": (lambda p: _edit_json(p / "backtest_summary_in_sample.json",
                                                     lambda d: d.update(code_sha="x")), "backtest_summary_in_sample.json changed"),
    "trade ledger edited (price only, totals intact)": (lambda p: _edit_csv(_ledger(p) / "trade_ledger.csv", lambda r: (
        [{**x, "entry_price": "10.5"} if x["symbol"] == "A" else x for x in r], list(r[0]))), "trade_ledger.csv changed"),
    "signal ledger edited": (lambda p: _edit_csv(_ledger(p) / "signal_ledger.csv", lambda r: (
        [{**x, "outcome": "completed"} for x in r], list(r[0]))), "signal_ledger.csv changed"),
    "ledgers from another sample": (lambda p: [shutil.copy(_ledger(p, OOS) / f, _ledger(p) / f) for f in
                                               ("signal_ledger.csv", "trade_ledger.csv")], "changed"),
    "diagnostics for another scenario": (lambda p: _edit_json(p / "diagnostics_in_sample_base_cap50.json",
                                                              lambda d: d.update(scenario="stress_cap50")), "describes in_sample/stress_cap50"),
    "provenance missing": (lambda p: _edit_json(p / "diagnostics_in_sample_base_cap50.json",
                                                lambda d: d.pop("provenance")), "provenance record is missing"),
    "attempts file missing": (lambda p: (p / "backtest/in_sample/base_cap50/attempts.csv").unlink(), "attempts.csv is missing"),
    "trade ledger missing": (lambda p: (_ledger(p) / "trade_ledger.csv").unlink(), "trade_ledger.csv is missing"),
    "old ledger schema": (lambda p: _edit_csv(_ledger(p) / "trade_ledger.csv", lambda r: (
        [{k: v for k, v in x.items() if k != "remaining_qty"} for x in r], [k for k in r[0] if k != "remaining_qty"])),
                          "predates the current ledger schema"),
    "SIP bars edited": (lambda p: _write_bars(_first_bar_file(p), [flat("A", D1, "05:00", 12.0, 9000)]), "differs"),
    "SIP bars replaced by another file": (lambda p: _first_bar_file(p).rename(_first_bar_file(p).with_name(
        "2024-03-08_premarket_000000000000.csv.gz")), "not in the provenance record"),
    "scanner candidates edited": (lambda p: (p / "candidates.csv.gz").write_bytes(gzip.compress(b"feed\n")),
                                  "candidates.csv.gz changed"),
}


SHARED = {"manifest edited", "breakout signals edited", "scanner candidates edited"}


@pytest.mark.parametrize("case", sorted(CORRUPTIONS))
def test_corrupted_inputs_are_refused(ds, case) -> None:  # noqa: ANN001
    p, _ = ds
    break_it, message = CORRUPTIONS[case]
    break_it(p)
    chk = charts.validate_sample(p, IN)
    assert chk.status == "mismatch" and any(message in x for x in chk.problems), chk.problems
    if case in SHARED:  # both samples depend on it: nothing at all is shown
        with pytest.raises(charts.ReplayDataError, match=message):
            charts.ReplayTables.load(p)
    else:  # the other sample stays usable; this one shows nothing
        t = charts.ReplayTables.load(p)
        assert t.checks[IN].status == "mismatch" and all(t.sample_of(d) == OOS for d in t.dates())


def test_inconsistent_counts_and_pnl_are_refused_even_without_ledger_hashes(ds) -> None:  # noqa: ANN001
    """Legacy records (no ledger hashes) fall back to reconciliation and the PR #4 cross-check."""
    p, _ = ds
    _edit_json(p / "diagnostics_in_sample_base_cap50.json", lambda d: d.pop("ledgers_sha256"))
    assert charts.validate_sample(p, IN).status == "ok"
    assert any("not hash-covered" in w for w in charts.validate_sample(p, IN).warnings)
    for edit, message in (
            (lambda r: ([{**x, "net_usd": "5.0"} if x["net_usd"] else x for x in r], list(r[0])), "do not reconcile"),
            (lambda r: ([{**x, "r_multiple": "0.0", "net_usd": "0.0"} for x in r], list(r[0])), "do not reconcile"),
            (lambda r: ([{**x, "entry_price": "10.5"} if x["symbol"] == "A" else x for x in r], list(r[0])),
             "entry_price='10.5' but the PR #4 trades.csv has entry_price='10.0'"),
            (lambda r: ([{**x, "exit_last_fill_utc": x["entry_first_fill_utc"]} if x["symbol"] == "A" else x for x in r],
                        list(r[0])), "exit_last_fill_utc")):
        replay = p / "_orig.csv"
        shutil.copy(_ledger(p) / "trade_ledger.csv", replay)
        _edit_csv(_ledger(p) / "trade_ledger.csv", edit)
        chk = charts.validate_sample(p, IN)
        assert chk.status == "mismatch" and any(message in x for x in chk.problems), chk.problems
        shutil.move(replay, _ledger(p) / "trade_ledger.csv")


def test_bar_cache_is_checked_again_when_a_session_loads(ds) -> None:  # noqa: ANN001
    p, _ = ds
    t = charts.ReplayTables.load(p)  # validated, then the cache changes underneath the running viewer
    _write_bars(_first_bar_file(p), [flat("A", D1, "05:00", 12.0, 9000)])
    with pytest.raises(charts.BarCacheError, match="differ from the diagnostics provenance"):
        t.session(p, "2024-03-08", "premarket")
    shutil.copy(_first_bar_file(p, "2024-03-11"), p / "cache" / "sip" / "2024-03-11_premarket_ffffffffffff.csv.gz")
    with pytest.raises(charts.BarCacheError, match="2 cached SIP bar files"):  # ambiguous: never guessed
        t.session(p, "2024-03-11", "premarket")


def test_legacy_record_without_bar_hashes_warns_instead_of_hiding(ds) -> None:  # noqa: ANN001
    p, _ = ds
    _edit_json(p / "diagnostics_in_sample_base_cap50.json", lambda d: d["provenance"]["dataset"].pop("sip_bars_sha256"))
    chk = charts.validate_sample(p, IN)
    assert chk.status == "ok" and any("SIP bar cache and scanner candidates are not covered" in w for w in chk.warnings)


# ---------- canonical hashing (Windows CRLF vs LF) ----------

def test_text_hashes_ignore_line_endings_and_binary_hashes_do_not(tmp_path) -> None:  # noqa: ANN001
    lf, crlf = tmp_path / "a.json", tmp_path / "b.json"
    lf.write_bytes(b'{\n "x": 1\n}\n')
    crlf.write_bytes(b'{\r\n "x": 1\r\n}\r\n')
    assert dg.sha256_of(lf) == dg.sha256_of(crlf) == hashlib.sha256(lf.read_bytes()).hexdigest()
    raw_crlf = hashlib.sha256(crlf.read_bytes()).hexdigest()  # what a pre-policy Windows run recorded
    assert dg.hash_check(lf, raw_crlf, None) == "legacy_crlf"  # legacy record: accepted and reported
    assert dg.hash_check(lf, raw_crlf, dg.HASH_POLICY) == "mismatch"  # new records are canonical only
    assert dg.hash_check(lf, "0" * 64, None) == "mismatch" and dg.hash_check(tmp_path / "no.json", "x", None) == "missing"
    gz = tmp_path / "c.csv.gz"
    gz.write_bytes(b"\r\n")
    assert dg.sha256_of(gz) == hashlib.sha256(b"\r\n").hexdigest()  # binary: raw bytes


def test_windows_line_endings_do_not_break_validation(ds) -> None:  # noqa: ANN001
    p, _ = ds
    for f in ("manifest.json", "breakout_matches.csv", "backtest_summary_in_sample.json",
              "backtest/in_sample/base_cap50/trades.csv", "backtest/in_sample/base_cap50/attempts.csv",
              "diagnostics/in_sample/base_cap50/signal_ledger.csv", "diagnostics/in_sample/base_cap50/trade_ledger.csv"):
        _crlf(p / f)  # a Windows checkout or a Windows write of every text input
    chk = charts.validate_sample(p, IN)
    assert chk.status == "ok" and chk.notes == [] and chk.problems == []


def test_legacy_crlf_records_are_accepted_with_a_note(ds) -> None:  # noqa: ANN001
    p, _ = ds
    path = p / "diagnostics_in_sample_base_cap50.json"
    crlf = (p / "breakout_matches.csv").read_bytes().replace(b"\n", b"\r\n")

    def legacy(d: dict) -> None:  # recorded before the policy existed, on Windows
        del d["provenance"]["hash_policy"]
        d["provenance"]["dataset"]["breakout_matches_sha256"] = hashlib.sha256(crlf).hexdigest()
    _edit_json(path, legacy)
    chk = charts.validate_sample(p, IN)
    assert chk.status == "ok" and chk.notes == [
        "breakout_matches.csv matched its recorded hash with Windows CRLF line endings (recorded before the canonical "
        "LF hashing policy)"]


# ---------- chart timestamps (US Eastern, DST) and markers ----------

def test_chart_timestamps_are_exact_us_eastern_across_dst(ds) -> None:  # noqa: ANN001
    p, res = ds
    t = charts.ReplayTables.load(p)
    for d, sym, utc_offset in ((D1, "A", 5), (D2, "B", 4)):  # EST, then EDT after 2024-03-10
        data = t.session(p, d.isoformat(), "premarket")
        sig = next(r for r in data.signals if r["symbol"] == sym)
        assert datetime.fromisoformat(sig["signal_bar_start_utc"]).hour == 5 + utc_offset  # 05:00 ET in UTC
        ev = charts.chart_events(data, sym)
        signal = next(e for e in ev if str(e["kind"]).startswith("signal_"))
        assert signal["t"] == sig["signal_bar_start_utc"]  # drawn on the trigger candle
        assert "trigger bar 05:00 closed 10.0000" in str(signal["label"]) and "signal known 05:01:00 ET" in str(signal["label"])
        entry = next(e for e in ev if e["kind"] == "entry_fill")
        assert "at 05:01:00.500 ET" in str(entry["label"])  # after the trigger candle closed, plus 0.5 s latency
        assert charts.et_naive(entry["t"]) == datetime(d.year, d.month, d.day, 5, 1, 0, 500_000)
    e = _trade(res[IN], "E")
    data = t.session(p, "2024-03-11", "afterhours")
    unsold = next(x for x in charts.chart_events(data, "E") if x["kind"] == "unsold_remainder")
    assert unsold["t"] == e.mark_utc and unsold["price"] == pytest.approx(e.mark_price)  # window end, not the last sale
    assert "39 shares unsold" in str(unsold["label"]) and "not realized" in str(unsold["label"])
    assert [x["kind"] for x in charts.chart_events(data, "E")].count("exit_fill") == 1  # the 10 shares that sold


def test_chart_figure_axes_and_no_invented_candles(ds) -> None:  # noqa: ANN001
    pytest.importorskip("plotly")
    p, _ = ds
    t = charts.ReplayTables.load(p)
    for d, s in (("2024-03-08", "premarket"), ("2024-03-11", "premarket"), ("2024-03-08", "afterhours")):
        data = t.session(p, d, s)
        sym = data.chart_symbols[0]
        fig = charts.figure(data, sym)
        names = {tr.name for tr in fig.data}
        assert {"1m SIP", "volume", "entry fill"} <= names
        assert not any("Top 5" in str(n) or "flag" in str(n) for n in names)  # baseline only
        window = ["04:00", "09:30"] if s == "premarket" else ["16:00", "20:00"]
        assert [str(x)[11:16] for x in fig.layout.xaxis.range] == window  # ET session window in EST and EDT
        assert "US Eastern" in fig.layout.xaxis2.title.text and "not live" in fig.layout.title.text
        assert len(fig.data[0].x) == len(data.bars[sym])  # one candle per cached bar: gaps stay gaps


# ---------- missing data and empty states ----------

def test_missing_data_is_explicit(ds) -> None:  # noqa: ANN001
    p, _ = ds
    t = charts.ReplayTables.load(p)
    with pytest.raises(FileNotFoundError):  # no after-hours bar file on 2024-03-12: nothing invented
        t.session(p, "2024-03-12", "afterhours")
    quiet = t.session(p, "2024-03-12", "premarket")  # bars and a scanner candidate, no signal
    assert quiet.signals == [] and quiet.chart_symbols == ["K"] and charts.session_warnings(quiet) == []
    f = t.session(p, "2024-03-08", "premarket")
    assert any("1 evaluated signal(s) have no cached quotes" in w for w in charts.session_warnings(f))
    assert next(r for r in f.signals if r["symbol"] == "F")["signal_spread_bps"] == ""  # empty, not estimated
    assert any("incomplete exit" in w for w in charts.session_warnings(t.session(p, "2024-03-11", "afterhours")))
    (p / "cache" / "sip" / "2024-03-11_premarket_x.csv.gz").unlink(missing_ok=True)
    data = charts.SessionData("2024-03-11", "premarket", {"B": []}, signals=[{"symbol": "B", "outcome": "rejected",
                                                                             "signal_available_utc": "x"}])
    assert any("No cached bars for B" in w for w in charts.session_warnings(data))


def test_export_matches_the_displayed_chart_and_refuses_unvalidated_dates(ds, capsys) -> None:  # noqa: ANN001
    pytest.importorskip("plotly")
    p, _ = ds
    t = charts.ReplayTables.load(p)
    path = charts.export_session(p, "2024-03-08", "premarket", t)
    html = path.read_text(encoding="utf-8")
    assert path.parent == p / "charts" and "Historical replay, not live" in html and "Top 5" not in html
    data = t.session(p, "2024-03-08", "premarket")
    for sym in data.chart_symbols:  # each displayed figure is embedded as is
        fig = charts.figure(data, sym)
        assert json.dumps(fig.layout.title.text.split("<br>")[0])[1:-1] in html
        for e in charts.chart_events(data, sym):
            if e.get("price") is not None and e["kind"] in charts.STYLE:
                assert json.dumps(e["label"])[1:-1] in html
    empty = charts.export_session(p, "2024-03-12", "premarket", t).read_text(encoding="utf-8")
    assert json.dumps("K ·")[1:-1] in empty  # a session with a candidate but no signal still exports its chart
    with pytest.raises(ValueError, match="no validated ledgers"):
        charts.export_session(p, "2024-03-13", "premarket", t)  # embargo day
    _edit_csv(p / "backtest/in_sample/base_cap50/trades.csv", lambda r: (r, list(r[0])[::-1]))  # same rows, new bytes
    assert cli.main(["m2-chart", "--dataset", str(p), "--date", "2024-03-08"]) == cli.EXIT_USAGE
    assert "no validated ledgers" in capsys.readouterr().err


# ---------- the Streamlit app itself (offline, no network, no backtest) ----------

@pytest.fixture
def no_network_no_backtest(monkeypatch):  # noqa: ANN001, ANN201
    import socket

    from momentum_bot import backtest

    def refuse(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("the viewer attempted a network connection")

    def no_backtest(*a, **k):  # noqa: ANN002, ANN003, ANN202
        raise AssertionError("the viewer ran a backtest")
    monkeypatch.setattr(socket.socket, "connect", refuse)
    monkeypatch.setattr(socket, "create_connection", refuse)
    monkeypatch.setattr(backtest, "run_backtest", no_backtest)
    monkeypatch.setattr(backtest, "simulate_signal", no_backtest)


def _app(p, monkeypatch):  # noqa: ANN001, ANN202
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr("sys.argv", ["viewer.py", "--dataset", str(p)])
    return AppTest.from_file(str(Path(charts.__file__).with_name("viewer.py")), default_timeout=60).run()


def _metrics(at):  # noqa: ANN001, ANN202
    return {m.label: m.value for m in at.metric}


def test_viewer_app_switches_dates_sessions_and_stocks(ds, monkeypatch, no_network_no_backtest) -> None:  # noqa: ANN001
    p, _ = ds
    at = _app(p, monkeypatch)
    assert not at.exception
    assert "HISTORICAL REPLAY — NOT LIVE" in at.markdown[0].value
    assert at.selectbox(key="date").options == ["2024-03-08 (in-sample)", "2024-03-11 (in-sample)",
                                                 "2024-03-12 (in-sample)", "2024-03-14 (out-of-sample)",
                                                 "2024-03-15 (out-of-sample)"]
    assert at.selectbox(key="date").value == "2024-03-15"  # latest historical date by default
    assert _metrics(at)["Signals"] == "0" and any("No scanner signals" in i.value for i in at.info)
    for d, session, expect in (("2024-03-08", "premarket", {"Entries": "2", "Completed trades": "2"}),
                               ("2024-03-11", "afterhours", {"Incomplete exits": "2", "Unrealized mark (incomplete)": None}),
                               ("2024-03-14", "premarket", {"Completed trades": "1"}),
                               ("2024-03-12", "afterhours", {"Signals": "0"})):
        at.selectbox(key="date").set_value(d)
        at.radio(key="session").set_value(session)
        at.run()
        assert not at.exception, (d, session)
        got = _metrics(at)
        assert all(v is None or got[k] == v for k, v in expect.items()), (d, session, got)
    assert any("No cached SIP bars for 2024-03-12 afterhours" in w.value for w in at.warning)
    at.selectbox(key="date").set_value("2024-03-08").run()
    at.radio(key="session").set_value("premarket").run()
    assert at.selectbox(key="symbol").options == ["A", "F"]
    at.selectbox(key="symbol").set_value("F").run()
    assert not at.exception and any("no cached quotes" in w.value for w in at.warning)
    at.button[0].click().run()  # export this session's charts
    assert not at.exception and any("charts" in s.value for s in at.success)
    assert (p / "charts" / "2024-03-08_premarket_hos.html").is_file()
    caption = " ".join(c.value for c in at.caption)
    assert "input hashes verified now (sha256-text-lf-v1)" in caption


def test_viewer_app_refuses_mismatched_data_and_never_shows_it_stale(ds, monkeypatch, no_network_no_backtest) -> None:  # noqa: ANN001
    p, _ = ds
    at = _app(p, monkeypatch)
    at.selectbox(key="date").set_value("2024-03-08").run()
    assert _metrics(at)["Entries"] == "2"
    _edit_csv(p / "backtest/in_sample/base_cap50/trades.csv",  # edited while the app is open
              lambda r: ([{**x, "fees_usd": "0.5"} for x in r], list(r[0])))
    at.run()
    assert not at.exception
    assert any("in_sample is not shown" in e.value and "trades.csv changed" in e.value for e in at.error)
    assert at.selectbox(key="date").value == "2024-03-15" and "2024-03-08 (in-sample)" not in at.selectbox(key="date").options
    for sample in (IN, OOS):
        _edit_json(p / f"diagnostics_{sample}_base_cap50.json", lambda d: d.pop("provenance"))
    at.run()
    assert "Cannot show this dataset" in at.error[0].value and not at.metric  # nothing from stale ledgers


def test_viewer_app_refuses_edited_bars_of_the_open_session(ds, monkeypatch, no_network_no_backtest) -> None:  # noqa: ANN001
    p, _ = ds
    at = _app(p, monkeypatch)
    at.selectbox(key="date").set_value("2024-03-08").run()
    at.radio(key="session").set_value("premarket").run()
    _write_bars(_first_bar_file(p), [flat("A", D1, "05:00", 12.0, 9000)])
    at.run()
    assert any("in_sample is not shown" in e.value and "SIP bar file" in e.value for e in at.error)  # re-validated
    assert "2024-03-08 (in-sample)" not in at.selectbox(key="date").options
