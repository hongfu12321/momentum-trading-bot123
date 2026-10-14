# M1-B extended-hours dataset report (generated)

**Status:** `complete` · **Trading days:** 90 (2026-06-03 to 2026-10-09) · **API requests this run:** 0 (cached fetches reused: 361) · **Orders placed:** 0  
**Code:** `2172bfd` · **Created:** 2026-10-13T21:37:11.148580+00:00 · **Data as of:** 2026-10-13T21:21:11.148580+00:00  
**Bars:** 1Min SIP and IEX, adjustment=raw · **Reference close:** SIP 1Day bar close (regular-session official close), split-adjusted on ex-dates

## Universe

Nasdaq Trader directory snapshot (file time 1013202614:01, sha256 `ae134a6076a8`/`7e5b17573c27`) plus corporate actions ['2026-06-02', '2026-10-13']: {'cash_mergers': 198, 'forward_splits': 83, 'name_changes': 242, 'reverse_splits': 456, 'stock_mergers': 72, 'worthless_removals': 114}.

Alpaca paper `/v2/assets` snapshot (read-only): {'active': 14387, 'inactive': 19170}.

Symbols by origin: {'current_listing': 5897, 'delisted': 326, 'renamed_to': 94, 'alpaca_otc': 975, 'alpaca_inactive': 16062}; renames handled in window: 95; symbol-days hidden as duplicate series: 62.

**Profitability:** not evaluated: no transaction costs, spreads or non-fills are modelled yet.

## Extended-hours coverage and discovery

| metric | premarket | afterhours |
|---|---:|---:|
| sessions analysed | 90 | 90 |
| mean eligible symbols / session | 3,416 | 3,471 |
| SIP 1m bars | 4,056,277 | 3,028,505 |
| IEX 1m bars | 76,513 | 14,352 |
| IEX volume share of SIP | 0.1% | 0.1% |
| SIP scanner candidates | 2,309 | 1,878 |
| IEX candidates matching SIP | 148 | 18 |
| IEX-only candidates | 0 | 0 |
| IEX candidate recall of SIP | 6.4% | 1.0% |
| SIP candidate-gated breakouts | 2,350 | 2,334 |
| IEX recall of gated breakouts (same minute) | 1.4% | 0.2% |
| SIP ungated breakouts (price band only) | 21,513 | 14,180 |
| SIP candidates not in today's listing | 69 | 68 |
|   of which by origin | alpaca_otc 13, renamed_to 56 | alpaca_otc 14, delisted 2, renamed_to 52 |
| SIP candidates on split ex-dates | 8 | 0 |
| median SIP post-trigger minute coverage | 96.6% | 78.9% |
| median IEX post-trigger minute coverage | 1.0% | 0.0% |
| median longest SIP gap after trigger (min) | 1 | 4 |

Split ex-dates checked: 316; candidate decisions changed by split adjustment: 10.

## Chronological split

Out-of-sample fraction 0.33, embargo 1 trading day(s). Choose parameters on in-sample days only; report out-of-sample once.

| sample | days | dates | PM SIP candidates | AH SIP candidates | PM gated breakouts | AH gated breakouts |
|---|---:|---|---:|---:|---:|---:|
| in_sample | 59 | 2026-06-03 to 2026-08-26 | 1,652 | 1,281 | 1,622 | 1,537 |
| embargo | 1 | 2026-08-27 to 2026-08-27 | 26 | 21 | 23 | 14 |
| out_of_sample | 30 | 2026-08-28 to 2026-10-09 | 631 | 576 | 705 | 783 |

## Files

`manifest.json`, `eligibility.csv`, `coverage_buckets.csv.gz` (30-min ET buckets), `candidate_detail.csv`, `candidate_matches.csv`, `breakout_matches.csv`, `candidates.csv.gz`, `split_checks.csv`, `split_candidate_changes.csv`, `universe.csv.gz`, `fetch_log.csv.gz`, `inputs/` (directory and corporate-action snapshots), `cache/` (raw bars; reruns reuse it).
