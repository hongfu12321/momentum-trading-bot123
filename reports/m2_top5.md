# M2 exploratory variant: Top 5 within the cached sub-$20 universe (in-sample only)

**Status: exploratory hypothesis, not a validated edge.** Both strategies run on the same 59 in-sample days (118 sessions, 2026-06-03 to 08-26) with the corrected PR #4 execution model, unchanged risk limits and the frozen `base_cap50` configuration. The out-of-sample block was not used, and the code refuses it. Simulation only; 0 orders. Neither strategy had an incomplete exit. "Top 5" means ranked within the dataset's cached sub-$20 universe, not the market-wide gainers list. Generated tables: `reports/datasets/m2_sip_20260603_20261009/research_comparison_in_sample.md`. Method: `docs/m2_top5_research.md`.

| strategy | signals | trades | fill rate | win rate | avg R (95% CI) | net $ | profit factor | max drawdown $ |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| Original HOS Breakout | 3,159 | 236 | 25.5% | 27.5% | −0.24 [−0.43, −0.04] | −847 | 0.70 | 871 |
| Top 5 (cached universe) HOS Breakout | 2,148 | 240 | 26.6% | 27.5% | −0.22 [−0.42, −0.02] | −807 | 0.72 | 834 |

These figures come from the `75ea4b3` run (2026-10-14), which applies the 5-minute freshness policy: stale prices are never ranked. Without it (the earlier `f6aa8cc` run), the Top 5 variant had 2,141 signals, 239 trades and −$791; the conclusions below are unchanged. The baseline rerun reproduced the frozen PR #4 ledgers byte for byte. Quotes for variant signals the baseline had skipped were downloaded for this run (285 historical SIP quote requests, 0 orders).

## What the data supports

1. **The variant does not fix the loss.** Both lose about 0.2 R per trade, and the confidence intervals almost coincide.
2. **The Top 5 filter barely filters.** 68% of the baseline's breakouts already come from a symbol in the Top 5 at that minute. The daily entry and loss limits, not the signal supply, decide which trades are taken.
3. **Execution is not the source of the differences.** Every signal evaluated by both strategies got an identical outcome (690 of 690). The baseline rerun reproduced the PR #4 ledgers byte for byte. P&L differences come only from which signals are taken.
4. **The shared daily risk budget shifts the session mix.** Fewer premarket signals leave budget for after hours: after-hours trades rise from 22 (baseline) to 42, and after hours remains the worst session. Session-level comparisons are therefore path-dependent.

## Hypotheses only (in-sample, not significant)

- Top 5 HOS premarket: −0.13 R (198 trades) against the baseline's −0.19 R (214); the CIs overlap.

Any such difference needs pre-registration and a test on trading days after 2026-10-09.

## Limitations

- **Universe:** the Top 5 is rebuilt only from symbols the dataset fetched bars for (reference close below about $18.2 premarket, $19.0 after hours) in the $1–$20 band with ≥ 100k session volume. It is not the market-wide top-gainers list. 109 of 33,630 minutes had fewer than 5 ranked symbols.
- **Freshness:** missing bars are never filled; a price older than 5 minutes is not ranked (737,692 symbol-minutes excluded). The limit is a fixed policy, not tuned.
- **Survivorship:** survivorship and the other PR #4 execution assumptions apply unchanged.
