"""Write an M1 run as reproducible CSV + JSON files and a human-readable Markdown report."""

from __future__ import annotations

import csv
import json
from pathlib import Path

from .pipeline import M1Result

BLOCKED_NOTE = (
    "SIP data was **not** obtained. IEX data has **not** been substituted for SIP; no SIP-vs-IEX "
    "comparison is reported. IEX-only rows in bars.csv are labelled feed=iex."
)


def _write_csv(path: Path, rows: list[dict[str, object]]) -> None:
    with path.open("w", newline="", encoding="utf-8") as fh:
        if not rows:
            return  # empty file: nothing of this kind occurred in the run
        writer = csv.DictWriter(fh, fieldnames=list(rows[0].keys()), lineterminator="\n")
        writer.writeheader()
        writer.writerows(rows)


def _pct(x: object) -> str:
    return f"{x * 100:.2f}%" if isinstance(x, (int, float)) else "n/a"


def render_markdown(result: M1Result) -> str:
    m = result.manifest
    s = m["summary"]
    assert isinstance(s, dict)
    lines = [
        "# M1 SIP vs IEX historical data report",
        "",
        f"**Status:** `{result.status}`  ",
        f"**Feed status:** {', '.join(f'{k}=`{v}`' for k, v in m['feed_status'].items())}  ",  # type: ignore[union-attr]
        f"**Symbols:** {', '.join(m['symbols'])}  ",  # type: ignore[arg-type]
        f"**Dates:** {m['start_date']} to {m['end_date']} (trading days: {len(m['trading_days'])}, compared: {len(m['compared_days'])})  ",  # type: ignore[arg-type]
        f"**Bars:** 1Min, adjustment=`{m['adjustment']}`, sessions {m['sessions']['premarket']} and {m['sessions']['afterhours']}  ",  # type: ignore[index]
        f"**Created:** {m['created_at_utc']} (data as of {m['as_of_utc']}), code `{m['code_sha']}`, orders placed: {m['orders_placed']}",
        "",
    ]
    if "entitlement_blocked" in result.status or result.status == "auth_failed":
        lines += ["## Blocked", "", BLOCKED_NOTE if m["feed_status"]["sip"] != "ok" else  # type: ignore[index]
                  "IEX data was not obtained; no comparison is reported.", ""]
    failures = m["failures"]
    assert isinstance(failures, list)
    if failures:
        lines += ["## Request failures", "", "| feed | date | status | HTTP | error |", "|---|---|---|---|---|"]
        lines += [f"| {f['feed']} | {f['trading_date']} | {f['status']} | {f['http_status']} | {str(f['error']).replace('|', '/')} |" for f in failures]
        lines.append("")
    if m["compared_days"]:
        lines += ["## Coverage and volume (matched symbols and days)", "",
                  "| session | symbol-sessions | expected min | SIP bar min | IEX bar min | IEX-only min | SIP volume | IEX volume | IEX share |",
                  "|---|---:|---:|---:|---:|---:|---:|---:|---:|"]
        for name, t in s["sessions"].items():
            lines.append(f"| {name} | {t['symbol_sessions']} | {t['expected_minutes']} | {t['sip_bar_minutes']} | "
                         f"{t['iex_bar_minutes']} | {t['iex_only_minutes']} | {t['sip_volume']} | {t['iex_volume']} | "
                         f"{_pct(t['iex_volume_share'])} |")
        lines += ["", "Per symbol-session highs/lows and matched-bar OHLC differences are in `session_comparison.csv`.", "",
                  "## Scanner candidates and breakout signals", "",
                  "| event | both | SIP only (IEX missed) | IEX only | IEX recall of SIP |", "|---|---:|---:|---:|---:|"]
        for label, key in (("candidates", "candidates"), ("breakouts (price band only)", "breakouts"),
                           ("breakouts (candidate-gated)", "gated_breakouts")):
            c = s[key]
            lines.append(f"| {label} | {c['both']} | {c['sip_only']} | {c['iex_only']} | {_pct(c['iex_recall_of_sip'])} |")
        lines.append("")
    lines += ["## Data quality", "", f"Bars kept by feed: {s['bars_by_feed']}. Dropped: {s['dropped_bars'] or 'none'}.", "",
              "## Limitations", ""]
    lines += [f"- {x}" for x in m["limitations"]]  # type: ignore[union-attr]
    lines += ["", "## Files", "", "`manifest.json`, `fetch_log.csv`, `bars.csv`, `session_comparison.csv`, "
              "`missing_intervals.csv`, `candidates.csv`, `candidate_matches.csv`, `breakouts.csv`, `breakout_matches.csv`.", ""]
    return "\n".join(lines)


def write_outputs(result: M1Result, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(result.manifest, indent=2, default=str) + "\n", encoding="utf-8")
    for name, rows in result.tables.items():
        _write_csv(out_dir / f"{name}.csv", rows)
    report = out_dir / "report.md"
    report.write_text(render_markdown(result), encoding="utf-8")
    return report
