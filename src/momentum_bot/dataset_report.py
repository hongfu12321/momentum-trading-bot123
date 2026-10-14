"""Write an M1-B dataset run: gzip CSV tables, manifest.json and a generated Markdown report."""

from __future__ import annotations

import csv
import gzip
import json
from pathlib import Path

from .dataset import DatasetResult

LARGE_TABLES = frozenset({"candidates", "universe", "coverage_buckets", "fetch_log", "references"})


def _write(path: Path, rows: list[dict[str, object]]) -> None:
    fields: list[str] = []
    for r in rows:  # union of keys, first-seen order (dropped_bars rows vary)
        fields += [k for k in r if k not in fields]
    opener = gzip.open if path.suffix == ".gz" else open
    with opener(path, "wt", newline="", encoding="utf-8") as fh:  # type: ignore[operator]
        if fields:
            w = csv.DictWriter(fh, fieldnames=fields, lineterminator="\n")
            w.writeheader()
            w.writerows(rows)


def _pct(x: object) -> str:
    return f"{x * 100:.1f}%" if isinstance(x, (int, float)) else "n/a"


def _num(x: object) -> str:
    return f"{x:,.0f}" if isinstance(x, (int, float)) else "n/a"


def render(result: DatasetResult) -> str:
    m = result.manifest
    s = m["summary"]
    inp = m["inputs"]
    assert isinstance(s, dict) and isinstance(inp, dict)
    days = m["trading_days"]
    assert isinstance(days, list)
    L = [
        "# M1-B extended-hours dataset report (generated)",
        "",
        f"**Status:** `{result.status}` · **Trading days:** {len(days)} ({days[0]} to {days[-1]}) · "
        f"**API requests this run:** {m['api_requests_this_run']} (cached fetches reused: {m['cached_fetches_reused']}) · **Orders placed:** {m['orders_placed']}  ",
        f"**Code:** `{m['code_sha']}` · **Created:** {m['created_at_utc']} · **Data as of:** {m['as_of_utc']}  ",
        f"**Bars:** 1Min SIP and IEX, adjustment=raw · **Reference close:** {m['reference_close']}",
        "",
        "## Universe",
        "",
        f"Nasdaq Trader directory snapshot (file time {inp.get('nasdaqlisted_file_creation_time')}, "
        f"sha256 `{str(inp.get('nasdaqlisted_sha256'))[:12]}`/`{str(inp.get('otherlisted_sha256'))[:12]}`) plus "
        f"corporate actions {inp.get('corporate_actions_range')}: {inp.get('corporate_actions_counts')}.",
        "",
        f"Alpaca paper `/v2/assets` snapshot (read-only): {inp.get('alpaca_assets_counts', 'not used')}.",
        "",
        f"Symbols by origin: {s['universe_by_origin']}; renames handled in window: {s['renames_in_window']}; "
        f"symbol-days hidden as duplicate series: {len(result.tables.get('duplicate_series', []))}.",
        "",
        f"**Profitability:** {m.get('profitability', 'not evaluated')}.",
        "",
    ]
    if m["failed_sessions"]:
        L += ["**Failed or skipped sessions:** " + ", ".join(map(str, m["failed_sessions"])), ""]  # type: ignore[arg-type]
    L += ["## Extended-hours coverage and discovery", "",
          "| metric | premarket | afterhours |", "|---|---:|---:|"]
    pm, ah = s.get("premarket", {}), s.get("afterhours", {})
    rows = [
        ("sessions analysed", lambda x: _num(x.get("days"))),
        ("mean eligible symbols / session", lambda x: _num(x.get("mean_eligible_symbols"))),
        ("SIP 1m bars", lambda x: _num(x.get("sip_bars"))),
        ("IEX 1m bars", lambda x: _num(x.get("iex_bars"))),
        ("IEX volume share of SIP", lambda x: _pct(x.get("iex_volume_share"))),
        ("SIP scanner candidates", lambda x: _num(x["candidates"]["sip_total"]) if x else "n/a"),
        ("IEX candidates matching SIP", lambda x: _num(x["candidates"]["both"]) if x else "n/a"),
        ("IEX-only candidates", lambda x: _num(x["candidates"]["iex_only"]) if x else "n/a"),
        ("IEX candidate recall of SIP", lambda x: _pct(x["candidates"]["iex_recall_of_sip"]) if x else "n/a"),
        ("SIP candidate-gated breakouts", lambda x: _num(x["gated_breakouts"]["sip_total"]) if x else "n/a"),
        ("IEX recall of gated breakouts (same minute)", lambda x: _pct(x["gated_breakouts"]["iex_recall_of_sip"]) if x else "n/a"),
        ("SIP ungated breakouts (price band only)", lambda x: _num(x.get("ungated_breakouts_sip"))),
        ("SIP candidates not in today's listing", lambda x: _num(x.get("sip_candidates_non_current_origin"))),
        ("  of which by origin", lambda x: ", ".join(f"{k} {v}" for k, v in sorted(x.get("sip_candidates_by_origin", {}).items())
                                                     if k != "current_listing") or "none"),
        ("SIP candidates on split ex-dates", lambda x: _num(x.get("sip_candidates_split_adjusted"))),
        ("median SIP post-trigger minute coverage", lambda x: _pct(x["sip_candidate_post_trigger_sip_coverage"]["median"]) if x else "n/a"),
        ("median IEX post-trigger minute coverage", lambda x: _pct(x["sip_candidate_post_trigger_iex_coverage"]["median"]) if x else "n/a"),
        ("median longest SIP gap after trigger (min)", lambda x: _num(x["sip_candidate_post_trigger_max_gap_minutes"]["median"]) if x else "n/a"),
    ]
    L += [f"| {name} | {fn(pm)} | {fn(ah)} |" for name, fn in rows]
    L += ["", f"Split ex-dates checked: {len(result.tables.get('split_checks', []))}; candidate decisions changed by "
          f"split adjustment: {len(result.tables.get('split_candidate_changes', []))}.", ""]
    split = m.get("chronological_split")
    if isinstance(split, dict):
        L += ["## Chronological split", "",
              f"Out-of-sample fraction {split['oos_fraction']:.2f}, embargo {split['embargo_days']} trading day(s). "
              "Choose parameters on in-sample days only; report out-of-sample once.", "",
              "| sample | days | dates | PM SIP candidates | AH SIP candidates | PM gated breakouts | AH gated breakouts |",
              "|---|---:|---|---:|---:|---:|---:|"]
        for name in ("in_sample", "embargo", "out_of_sample"):
            blk = split[name]
            per = [s.get(sess, {}).get("by_sample", {}).get(name, {}) for sess in ("premarket", "afterhours")]
            cells = [_num(p.get(k, {}).get("sip_total")) for k in ("candidates",) for p in per]
            cells += [_num(p.get(k, {}).get("sip_total")) for k in ("gated_breakouts",) for p in per]
            L.append(f"| {name} | {blk['days']} | {blk['first']} to {blk['last']} | " + " | ".join(cells) + " |")
        L.append("")
    L += ["## Files", "",
          "`manifest.json`, `eligibility.csv`, `coverage_buckets.csv.gz` (30-min ET buckets), `candidate_detail.csv`, "
          "`candidate_matches.csv`, `breakout_matches.csv`, `candidates.csv.gz`, `split_checks.csv`, "
          "`split_candidate_changes.csv`, `universe.csv.gz`, `fetch_log.csv.gz`, `references.csv.gz` (reference close per eligible symbol and session), `inputs/` (directory and "
          "corporate-action snapshots), `cache/` (raw bars; reruns reuse it).", ""]
    return "\n".join(L)


def write_dataset(result: DatasetResult, out_dir: Path) -> Path:
    out_dir.mkdir(parents=True, exist_ok=True)
    (out_dir / "manifest.json").write_text(json.dumps(result.manifest, indent=2, default=str) + "\n", encoding="utf-8")
    for name, rows in result.tables.items():
        _write(out_dir / (f"{name}.csv.gz" if name in LARGE_TABLES else f"{name}.csv"), rows)
    report = out_dir / "report.md"
    report.write_text(render(result), encoding="utf-8")
    return report
