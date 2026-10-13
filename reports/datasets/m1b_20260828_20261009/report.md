# M1-B extended-hours dataset report (generated)

**Status:** `complete` · **Trading days:** 30 (2026-08-28 to 2026-10-09) · **API requests:** 611 · **Orders placed:** 0  
**Code:** `e13dbb5-dirty` · **Created:** 2026-10-13T16:43:18.424988+00:00 · **Data as of:** 2026-10-13T16:27:18.424988+00:00  
**Bars:** 1Min SIP and IEX, adjustment=raw · **Reference close:** SIP 1Day bar close (regular-session official close), split-adjusted on ex-dates

## Universe

Nasdaq Trader directory snapshot (file time 1013202612:11, sha256 `ae20ca73e1b9`/`fb08aa6d0c84`) plus corporate actions ['2026-08-27', '2026-10-13']: {'cash_mergers': 52, 'forward_splits': 28, 'name_changes': 85, 'reverse_splits': 179, 'stock_mergers': 27, 'worthless_removals': 41}.

Symbols by origin: {'current_listing': 5897, 'delisted': 88, 'renamed_to': 30}; renames handled in window: 31.

## Extended-hours coverage and discovery

| metric | premarket | afterhours |
|---|---:|---:|
| sessions analysed | 30 | 30 |
| mean eligible symbols / session | 3,381 | 3,439 |
| SIP 1m bars | 1,269,181 | 944,819 |
| IEX 1m bars | 22,864 | 4,759 |
| IEX volume share of SIP | 0.2% | 0.0% |
| SIP scanner candidates | 630 | 721 |
| IEX candidates matching SIP | 45 | 10 |
| IEX-only candidates | 0 | 0 |
| IEX candidate recall of SIP | 7.1% | 1.4% |
| SIP candidate-gated breakouts | 703 | 815 |
| IEX recall of gated breakouts (same minute) | 2.0% | 0.5% |
| SIP ungated breakouts (price band only) | 6,987 | 3,916 |
| SIP candidates from delisted/renamed symbols | 9 | 16 |
| SIP candidates on split ex-dates | 4 | 0 |
| median SIP post-trigger minute coverage | 97.9% | 67.0% |
| median IEX post-trigger minute coverage | 1.5% | 0.0% |
| median longest SIP gap after trigger (min) | 1 | 6 |

Split ex-dates checked: 88; candidate decisions changed by split adjustment: 3.

## Files

`manifest.json`, `eligibility.csv`, `coverage_buckets.csv.gz` (30-min ET buckets), `candidate_detail.csv`, `candidate_matches.csv`, `breakout_matches.csv`, `candidates.csv.gz`, `split_checks.csv`, `split_candidate_changes.csv`, `universe.csv.gz`, `fetch_log.csv.gz`, `inputs/` (directory and corporate-action snapshots), `cache/` (raw bars; reruns reuse it).
