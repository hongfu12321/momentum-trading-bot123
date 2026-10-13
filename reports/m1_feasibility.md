# M1 feasibility report: extended-hours data, universe and candidate discovery

**Dataset:** `reports/datasets/m1b_20260828_20261009/`. Only the generated `report.md`, `manifest.json` and count-only `eligibility.csv` are committed; per-symbol tables, raw bars and input snapshots are licensed data and stay local.
**Window:** 30 trading days, 2026-08-28 to 2026-10-09; premarket 04:00–09:30 ET and after-hours 16:00–20:00 ET
**Code:** `aa17b19` · **API:** Alpaca market data only (611 requests on the first build, 0 on cached reruns) · **Orders placed:** 0
**Reproduce:** `momentum-bot m1-dataset --start 2026-08-28 --end 2026-10-09 --out-dir reports/datasets/m1b_20260828_20261009`

## Recommendation

**M2 backtesting can begin, on SIP data only, with three conditions:**

1. **Extend the dataset to at least 60–90 trading days before drawing any conclusions.** The design's risk policy (one position at a time, at most 5 entries a day) caps 30 days at about 150 trades, below the 200–300 target, and leaves nothing for out-of-sample testing. Extending is cheap: a 30-day build took 25 minutes and 36 MB of cache.
2. **Make historical quotes the first M2 task.** M1 is bars-only. The execution simulator needs spreads and quote age, and SIP quote access and volume have not been tested.
3. **Carry the residual survivorship bias as a stated limitation,** or approve one read-only reference-data source to close it (see "Decisions needed").

Do not use IEX for any part of this strategy. In extended hours it is too sparse for discovery, signals or fill modelling.

## Findings

### 1. Extended-hours SIP coverage is good in premarket and adequate after hours

| | premarket | after-hours |
|---|---:|---:|
| Eligible symbols per session (mean) | 3,381 | 3,439 |
| SIP 1m bars (30 days) | 1,269,181 | 944,819 |
| SIP minute coverage after a candidate triggers (median) | 97.9% | 79.0% |
| Longest gap after trigger (median minutes) | 1 | 4 |

Candidates trade almost every minute once they trigger in premarket. After hours, coverage thins after 18:00 ET; gaps of several minutes are normal, which matters for exits and stop modelling in M2. Activity is concentrated at 04:00–04:30 and 07:00–09:30 ET (`coverage_buckets.csv.gz`).

**Data defect found and fixed: the first after-hours bar is contaminated.** The 16:00 SIP bar carries the closing auction and late-reported regular-session prints: 5.1 billion shares across 10 sampled days, about 39 times the 16:01 bar. Counted as after-hours volume, it met the 100k volume gate for nearly every symbol and inflated after-hours candidates from 574 to 721. The scanner now counts that bar as zero volume for after-hours gating and breakout volume (`ScanParams.exclude_closing_auction_bar`). This is a bar-level approximation; doing it exactly needs trade-level condition codes.

### 2. IEX cannot substitute for SIP in extended hours

| | premarket | after-hours |
|---|---:|---:|
| IEX volume share of SIP (closing-auction bar excluded) | 0.2% | 0.1% |
| SIP scanner candidates | 630 | 574 |
| IEX recall of SIP candidates | 7.1% (45) | 1.7% (10) |
| IEX recall of candidate-gated breakouts, same minute | 2.0% | 0.5% |
| IEX post-trigger minute coverage (median) | 1.5% | 0.0% |
| IEX-only candidates | 0 | 0 |

For comparison, the M1-A one-day sample showed a 0.06% IEX premarket volume share. IEX never found a candidate that SIP missed, which is consistent with IEX trades being a subset of SIP.

### 3. Scanner discovery yields a usable but small sample per 30 days

- **Candidates per day:** 12–34 in premarket (630 total, 387 distinct symbols) and 12–28 after hours (574 total), using the design's section 4 rules. Every day had candidates.
- **Breakouts:** candidate-gated breakouts on SIP were 703 in premarket across 332 symbol-sessions, and 781 after hours across 335.
- **Trade cap:** the 5-entries-per-day limit (both sessions combined) caps tradable entries at about 150 per 30 days. One-position-at-a-time and price filters will reduce that further.
- **These are research-hypothesis rules, not a validated strategy.** Nothing here measures profitability.

### 4. Point-in-time universe: what works and what doesn't

How the universe is built (`src/momentum_bot/universe.py`):

1. Start from a dated Nasdaq Trader listing snapshot, keeping common-stock-like issues: no ETFs, test issues, warrants, rights, units, preferreds or notes. That gave 5,897 symbols.
2. Add back symbols that left during the window, from Alpaca corporate actions: 88 symbols delisted by merger or worthless removal, and 30 pre-rename symbols.
3. On each date, a symbol is eligible only if its prior official close (from the SIP daily bar) exists and could still qualify under the scan's price cap and minimum change. That gave about 3,400 eligible symbols per session.

| Check | Result |
|---|---|
| Delisted symbols still have Alpaca bars | Yes (verified on SPLK, HZNP, SGEN, PXD), so add-backs work |
| Candidates from the 88 merger/removal add-backs | 0. Acquisition targets rarely gap ≥10% in extended hours. |
| Renamed symbols | Alpaca serves the whole history under the *new* symbol. Using both names would double-count, so each date uses exactly one (old before the rename date, new on/after). 31 renames handled; 24 candidates came from pre-rename symbols. |
| Daily bar as reference close | Daily OHLC is regular-session only (high equals regular-session high, not the after-hours high), so it is known before the session it serves |
| Reverse/forward splits (raw prices) | 86 of 86 ex-dates with data showed the expected raw price jump. Adjusting the reference close on the ex-date removed 3 false premarket gap candidates (FTFT, RETO, GCDT). |

**Residual survivorship bias (not measured):** symbols delisted for exchange-compliance reasons or moved to OTC have no corporate-action record, so they are missing. That is exactly the low-priced, distressed group most likely to gap. The window ends 4 days before the snapshot, which limits but does not remove the effect. Security-type classification also uses today's names.

## Other limitations

- Unadjusted (raw) bars, with only the split adjustment described above. Dividends are ignored, which is immaterial for intraday gaps.
- The holiday table covers 2023–2026 only; other dates are rejected rather than guessed.
- No float, news, halt or quote data. Note that LULD halts do not apply in extended hours, but trading pauses and sparse prints do.
- Thirty days is one market regime; no seasonality or regime split is possible yet.
- Alpaca's bar-construction rules (which trade conditions are included) affect volume and high/low and cannot be inspected from bars.

## Decisions needed

1. **Dataset length for M2:** I recommend 90 trading days (about 60 in-sample and 30 out-of-sample). The calendar already covers 2026, but the table must be extended for dates before 2023.
2. **Closing the compliance-delisting gap:** options are (a) accept and disclose it, or (b) allow one read-only GET to Alpaca's asset list including inactive symbols (`/v2/assets?status=inactive`). Option (b) means touching the paper trading API host, which M1's rules currently forbid, so it needs your explicit approval.
3. ~~Whether to commit the input snapshots~~: resolved. Licensed snapshots and per-symbol tables stay local.
