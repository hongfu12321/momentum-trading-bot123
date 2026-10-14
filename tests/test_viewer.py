"""Historical replay viewer: provenance checks, P&L reconciliation, chart timestamps, missing data.

Deterministic and offline: a scripted run of the real PR #4 engine and PR #5 diagnostics on two days,
2024-03-08 (EST, UTC-5) and 2024-03-11 (EDT, UTC-4, the first trading day after the DST change).
"""

import csv
import gzip
import hashlib
import json
from datetime import date, datetime, timedelta

import pytest
from conftest import et
from test_diagnostics import _edit_csv, _scripted_run

from momentum_bot import charts, cli
from momentum_bot import diagnostics as dg
from momentum_bot.data.provider import Bar
from momentum_bot.dataset import _write_bars

D1, D2 = date(2024, 3, 8), date(2024, 3, 11)
IN = "in_sample"


def flat(sym: str, d: date, hhmm: str, c: float, v: int) -> Bar:
    return Bar(sym, "sip", et(d, hhmm), c, c, c, c, v)


def replay_dataset(tmp_path):  # noqa: ANN001, ANN201
    """Scripted backtest (A: stop exit on D1; B: an exit that sells nothing on D2), then m2-diagnostics via the CLI."""
    res, engine = _scripted_run(tmp_path)
    m = json.loads((tmp_path / "manifest.json").read_text(encoding="utf-8"))
    m.update(as_of_utc="2024-03-12T00:00:00+00:00", start_date=D1.isoformat(), end_date="2024-03-14",
             trading_days=["2024-03-08", "2024-03-11", "2024-03-12", "2024-03-13", "2024-03-14"],
             chronological_split={"in_sample": {"first": "2024-03-08", "last": "2024-03-11"},
                                  "embargo": {"first": "2024-03-12", "last": "2024-03-12"},
                                  "out_of_sample": {"first": "2024-03-13", "last": "2024-03-14"}})
    (tmp_path / "manifest.json").write_text(json.dumps(m), encoding="utf-8")
    assert cli.main(["m2-diagnostics", "--dataset", str(tmp_path)]) == cli.EXIT_OK
    _write_bars(tmp_path / "cache" / "sip" / "2024-03-08_premarket_x.csv.gz",
                [flat("A", D1, f"04:{m:02d}", 10.0, 1000) for m in range(55, 60)] + [flat("A", D1, "05:00", 10.0, 5000)])
    _write_bars(tmp_path / "cache" / "sip" / "2024-03-11_premarket_x.csv.gz", [flat("B", D2, "05:00", 10.0, 5000)])
    return res, engine


# ---------- validated loading and P&L reconciliation ----------

def test_replay_loads_only_validated_samples_and_reconciles_pnl(tmp_path) -> None:  # noqa: ANN001
    res, engine = replay_dataset(tmp_path)
    t = charts.ReplayTables.load(tmp_path)
    assert t.checks[IN].status == "ok" and t.checks[IN].problems == [] and t.checks[IN].notes == []
    assert t.checks["out_of_sample"].status == "absent"  # no ledgers: reported, not shown
    assert t.dates() == ["2024-03-08", "2024-03-11"]  # latest last: the viewer's default
    assert (t.sample_of("2024-03-08"), t.sample_of("2024-03-12"), t.sample_of("2024-03-13")) == \
        (IN, "embargo", "out_of_sample")
    a, b = (next(x for x in res.trades if x.symbol == s) for s in ("A", "B"))
    day1, day2 = (charts.daily_summary(t, d) for d in t.dates())
    assert (day1["signals"], day1["entries"], day1["completed_trades"], day1["incomplete_exits"]) == (1, 1, 1, 0)
    assert day1["net_usd_completed"] == pytest.approx(a.net_usd)
    assert (day2["entries"], day2["completed_trades"], day2["incomplete_exits"]) == (1, 0, 1)
    assert day2["net_usd_completed"] == 0  # the incomplete exit is never added to net P&L
    assert day2["realized_usd_incomplete"] == pytest.approx(b.realized_net_usd)
    assert day2["marked_usd_incomplete"] == pytest.approx(b.unrealized_usd)
    # The days add up to the backtest summary the ledgers explain.
    days = [day1, day2]
    assert sum(x["entries"] for x in days) == engine["entries"]
    assert sum(x["completed_trades"] for x in days) == engine["trades"]
    assert sum(x["incomplete_exits"] for x in days) == engine["incomplete_exits"]["count"]
    assert sum(x["net_usd_completed"] for x in days) == pytest.approx(engine["net_usd"])
    assert sum(x["marked_usd_incomplete"] or 0 for x in days) == pytest.approx(engine["incomplete_exits"]["unrealized_mark_usd"])
    empty = charts.daily_summary(t, "2024-03-12")  # embargo day: zeros, no error
    assert (empty["signals"], empty["entries"], empty["net_usd_completed"], empty["marked_usd_incomplete"]) == (0, 0, 0, 0)


def _ledger(p):  # noqa: ANN001, ANN202
    return p / "diagnostics" / IN / "base_cap50"


@pytest.mark.parametrize(("break_it", "message"), [
    (lambda p: _edit_csv(p / "backtest/in_sample/base_cap50/trades.csv",
                         lambda r: ([{**x, "fees_usd": "0.5"} for x in r], list(r[0]))), "trades.csv changed"),
    (lambda p: (p / "manifest.json").write_text(
        (p / "manifest.json").read_text(encoding="utf-8").replace("2024-03-14", "2024-03-15"), encoding="utf-8"),
     "manifest.json changed"),
    (lambda p: _edit_csv(p / "breakout_matches.csv", lambda r: ([{**x, "sip_price": "11.0"} for x in r], list(r[0]))),
     "breakout_matches.csv changed"),
    (lambda p: (p / "backtest/in_sample/base_cap50/attempts.csv").unlink(), "attempts.csv is missing"),
    (lambda p: (p / "diagnostics_in_sample_base_cap50.json").unlink(), "provenance record is missing"),
    (lambda p: _edit_csv(_ledger(p) / "trade_ledger.csv",  # a ledger written before the corrected exit model
                         lambda r: ([{k: v for k, v in x.items() if k != "remaining_qty"} for x in r],
                                    [k for k in r[0] if k != "remaining_qty"])), "predates the current ledger schema"),
    (lambda p: _edit_csv(_ledger(p) / "signal_ledger.csv", lambda r: (r[:1], list(r[0]))),
     "signal_ledger.csv has 1 rows"),
    (lambda p: _edit_csv(_ledger(p) / "trade_ledger.csv",
                         lambda r: ([{**x, "net_usd": "5.0"} if x["net_usd"] else x for x in r], list(r[0]))),
     "do not reconcile"),
    (lambda p: _edit_csv(_ledger(p) / "trade_ledger.csv",  # an incomplete exit shown as completed
                         lambda r: ([{**x, "r_multiple": "0.0", "net_usd": "0.0"} for x in r], list(r[0]))),
     "do not reconcile"),
])
def test_stale_or_mismatched_ledgers_are_refused(tmp_path, break_it, message) -> None:  # noqa: ANN001
    replay_dataset(tmp_path)
    break_it(tmp_path)
    chk = charts.validate_sample(tmp_path, IN)
    assert chk.status == "mismatch" and any(message in x for x in chk.problems), chk.problems
    with pytest.raises(charts.ReplayDataError, match=message):  # nothing is shown from it
        charts.ReplayTables.load(tmp_path)


def test_a_refused_sample_does_not_hide_a_valid_one(tmp_path) -> None:  # noqa: ANN001
    import shutil

    replay_dataset(tmp_path)
    oos = tmp_path / "diagnostics" / "out_of_sample" / "base_cap50"
    shutil.copytree(_ledger(tmp_path), oos)  # ledgers with no provenance record of their own
    t = charts.ReplayTables.load(tmp_path)
    assert t.checks["out_of_sample"].status == "mismatch" and t.checks[IN].status == "ok"
    assert t.dates() == ["2024-03-08", "2024-03-11"]  # only validated rows are loaded


# ---------- canonical hashing (Windows CRLF vs LF) ----------

def _to_crlf(path) -> None:  # noqa: ANN001
    path.write_bytes(path.read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n"))


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


def test_windows_line_endings_do_not_break_validation(tmp_path) -> None:  # noqa: ANN001
    replay_dataset(tmp_path)
    for f in ("manifest.json", "breakout_matches.csv", "backtest_summary_in_sample.json",
              "backtest/in_sample/base_cap50/trades.csv", "backtest/in_sample/base_cap50/attempts.csv"):
        _to_crlf(tmp_path / f)  # a Windows checkout or a Windows write
    chk = charts.validate_sample(tmp_path, IN)
    assert chk.status == "ok" and chk.notes == []


def test_legacy_crlf_records_are_accepted_with_a_note(tmp_path) -> None:  # noqa: ANN001
    replay_dataset(tmp_path)
    path = tmp_path / "diagnostics_in_sample_base_cap50.json"
    diag = json.loads(path.read_text(encoding="utf-8"))
    del diag["provenance"]["hash_policy"]  # recorded before the policy existed, on Windows:
    crlf = (tmp_path / "breakout_matches.csv").read_bytes().replace(b"\r\n", b"\n").replace(b"\n", b"\r\n")
    diag["provenance"]["dataset"]["breakout_matches_sha256"] = hashlib.sha256(crlf).hexdigest()
    path.write_text(json.dumps(diag), encoding="utf-8")
    chk = charts.validate_sample(tmp_path, IN)
    assert chk.status == "ok" and chk.notes == [
        "breakout_matches.csv matched its recorded hash with Windows CRLF line endings (recorded before the canonical LF "
        "hashing policy)"]


# ---------- chart timestamps (US Eastern, DST) ----------

def test_chart_timestamps_are_exact_us_eastern_across_dst(tmp_path) -> None:  # noqa: ANN001
    replay_dataset(tmp_path)
    t = charts.ReplayTables.load(tmp_path)
    for d, utc_offset in ((D1, 5), (D2, 4)):  # EST, then EDT after 2024-03-10
        data = t.session(tmp_path, d.isoformat(), "premarket")
        sym = data.chart_symbols[0]
        sig = next(r for r in data.signals if r["symbol"] == sym)
        assert datetime.fromisoformat(sig["signal_bar_start_utc"]).hour == 5 + utc_offset  # 05:00 ET in UTC
        ev = charts.chart_events(data, sym)
        signal = next(e for e in ev if e["kind"].startswith("signal_"))
        assert signal["t"] == sig["signal_bar_start_utc"]  # drawn on the trigger bar
        assert "trigger bar 05:00 closed 10.0000" in str(signal["label"]) and "signal known 05:01:00 ET" in str(signal["label"])
        entry = next(e for e in ev if e["kind"] == "entry_fill")
        assert "at 05:01:00.500 ET" in str(entry["label"])  # after the trigger candle closed, plus 0.5 s latency
        assert charts.et_naive(entry["t"]) == datetime.combine(d, datetime.min.time()).replace(hour=5, minute=1, microsecond=500_000)
        assert charts.et_naive(data.bars[sym][-1].timestamp_utc).strftime("%H:%M") == "05:00"
    b = next(r for r in t.trades[("2024-03-11", "premarket")] if r["symbol"] == "B")
    unsold = next(e for e in charts.chart_events(t.session(tmp_path, "2024-03-11", "premarket"), "B")
                  if e["kind"] == "unsold_remainder")
    assert unsold["t"] == (datetime.fromisoformat(b["exit_trigger_utc"]) + timedelta(minutes=2)).isoformat()
    assert "not realized" in str(unsold["label"])
    assert not any(e["kind"] == "exit_fill" for e in charts.chart_events(t.session(tmp_path, "2024-03-11", "premarket"), "B"))


def test_chart_figure_axes_and_markers(tmp_path) -> None:  # noqa: ANN001
    pytest.importorskip("plotly")
    replay_dataset(tmp_path)
    t = charts.ReplayTables.load(tmp_path)
    for d in ("2024-03-08", "2024-03-11"):
        data = t.session(tmp_path, d, "premarket")
        fig = charts.figure(data, data.chart_symbols[0])
        names = {tr.name for tr in fig.data}
        assert {"1m SIP", "volume", "entry fill", "signal filled"} <= names
        assert not any("Top 5" in str(n) or "flag" in str(n) for n in names)  # baseline only
        assert [str(x)[11:16] for x in fig.layout.xaxis.range] == ["04:00", "09:30"]  # ET session window, both DST states
        assert "US Eastern" in fig.layout.xaxis2.title.text and "not live" in fig.layout.title.text
        candle = fig.data[0]
        assert str(candle.x[-1])[11:16] == "05:00"


# ---------- missing data and empty states ----------

def test_missing_bars_and_warnings_are_explicit(tmp_path) -> None:  # noqa: ANN001
    replay_dataset(tmp_path)
    t = charts.ReplayTables.load(tmp_path)
    with pytest.raises(FileNotFoundError):  # no cached bars for that session: nothing invented
        t.session(tmp_path, "2024-03-08", "afterhours")
    a = t.session(tmp_path, "2024-03-08", "premarket")
    assert a.chart_symbols == ["A"] and a.sample == IN
    assert charts.session_warnings(a) == ["Sparse bars (fewer than half the session's 330 minutes traded): A. "
                                          "Empty minutes are shown as gaps."]
    b = t.session(tmp_path, "2024-03-11", "premarket")
    assert any("incomplete exit" in w for w in charts.session_warnings(b))
    (tmp_path / "cache" / "sip" / "2024-03-11_premarket_x.csv.gz").unlink()
    _write_bars(tmp_path / "cache" / "sip" / "2024-03-11_premarket_x.csv.gz", [flat("Z", D2, "05:00", 1.0, 1)])
    b = t.session(tmp_path, "2024-03-11", "premarket")  # bars exist for the session, none for the signal's stock
    assert b.bars["B"] == [] and any("No cached bars for B" in w for w in charts.session_warnings(b))
    data = charts.SessionData("2024-03-08", "premarket", {}, signals=[{"outcome": "rejected", "quotes_cached": "False",
                                                                     "symbol": "C", "signal_available_utc": "x"}])
    assert any("no cached quotes" in w for w in charts.session_warnings(data))


def test_export_session_and_cli_refuse_unvalidated_data(tmp_path, capsys) -> None:  # noqa: ANN001
    pytest.importorskip("plotly")
    replay_dataset(tmp_path)
    path = charts.export_session(tmp_path, "2024-03-08", "premarket")
    html = path.read_text(encoding="utf-8")
    assert path.parent == tmp_path / "charts" and "Historical replay, not live" in html and "plotly" in html.lower()
    assert "Top 5" not in html
    with pytest.raises(ValueError, match="no validated ledgers"):
        charts.export_session(tmp_path, "2024-03-13", "premarket")
    _edit_csv(tmp_path / "backtest/in_sample/base_cap50/trades.csv", lambda r: (r, list(r[0])[::-1]))  # same rows, new bytes
    assert cli.main(["m2-chart", "--dataset", str(tmp_path), "--date", "2024-03-08"]) == cli.EXIT_USAGE
    assert "trades.csv changed" in capsys.readouterr().err


def test_candidates_are_shown_from_the_dataset(tmp_path) -> None:  # noqa: ANN001
    replay_dataset(tmp_path)
    with gzip.open(tmp_path / "candidates.csv.gz", "wt", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["feed", "symbol", "trading_date", "session", "bar_start_utc", "observed_at_utc", "price",
                    "change_vs_ref", "cumulative_volume"])
        w.writerow(["sip", "A", "2024-03-08", "premarket", et(D1, "04:58").isoformat(), et(D1, "04:59").isoformat(),
                    "10.0", "0.5", "120000"])
        w.writerow(["iex", "A", "2024-03-08", "premarket", et(D1, "04:58").isoformat(), et(D1, "04:59").isoformat(),
                    "10.0", "0.5", "1000"])
    t = charts.ReplayTables.load(tmp_path)
    data = t.session(tmp_path, "2024-03-08", "premarket")
    cand = [e for e in charts.chart_events(data, "A") if e["kind"] == "scanner_candidate"]
    assert len(cand) == 1 and "known 04:59:00 ET" in str(cand[0]["label"])  # SIP only


# ---------- the Streamlit app itself (offline) ----------

def _app(tmp_path, monkeypatch):  # noqa: ANN001, ANN202
    pytest.importorskip("streamlit")
    from pathlib import Path

    from streamlit.testing.v1 import AppTest

    monkeypatch.setattr("sys.argv", ["viewer.py", "--dataset", str(tmp_path)])
    return AppTest.from_file(str(Path(charts.__file__).with_name("viewer.py")), default_timeout=60).run()


def test_viewer_app_runs_on_validated_data(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    replay_dataset(tmp_path)
    at = _app(tmp_path, monkeypatch)
    assert not at.exception
    assert "HISTORICAL REPLAY — NOT LIVE" in at.markdown[0].value
    assert at.selectbox(key="date").value == "2024-03-11"  # latest historical date by default
    assert {m.label: m.value for m in at.metric}["Incomplete exits"] == "1"
    assert any("out_of_sample: no diagnostics ledgers" in i.value for i in at.info)
    at.selectbox(key="date").set_value("2024-03-08").run()
    assert not at.exception and {m.label: m.value for m in at.metric}["Completed trades"] == "1"


def test_viewer_app_refuses_mismatched_data(tmp_path, monkeypatch) -> None:  # noqa: ANN001
    replay_dataset(tmp_path)
    _edit_csv(tmp_path / "backtest/in_sample/base_cap50/trades.csv",
              lambda r: ([{**x, "fees_usd": "0.5"} for x in r], list(r[0])))
    at = _app(tmp_path, monkeypatch)
    assert not at.exception and "Cannot show this dataset" in at.error[0].value and "trades.csv changed" in at.error[0].value
    assert not at.metric  # nothing from the stale ledgers is displayed
