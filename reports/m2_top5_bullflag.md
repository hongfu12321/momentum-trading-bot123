# M2 exploratory variants: Top 5 (cached universe) and Bull Flag (in-sample only)

**Status: exploratory hypotheses, not validated edges.** Same 59 in-sample days (118 sessions, 2026-06-03 to 08-26), corrected PR #4 execution model, unchanged risk limits, frozen `base_cap50`. Out-of-sample data was not used, and the code refuses it. Simulation only; 0 orders. "Top 5" means ranked within the dataset's cached sub-$20 universe (5-minute freshness policy), not the market-wide gainers list. Generated tables: `reports/datasets/m2_sip_20260603_20261009/research_comparison_in_sample.md` (regenerated at `9174d2c`, cache-only). Method: `docs/m2_top5_research.md`. For the separate intrabar Bull Flag strategy, see `reports/research_program/bull_flag_intrabar_report.md`.

| strategy | signals | trades | fill rate | win rate | avg R (95% CI) | net $ | profit factor | max drawdown $ |
|---|---:|---:|---:|---:|---|---:|---:|---:|
| Original HOS Breakout | 3,159 | 236 | 25.5% | 27.5% | −0.24 [−0.43, −0.04] | −847 | 0.70 | 871 |
| Top 5 (cached universe) HOS Breakout | 2,148 | 240 | 26.6% | 27.5% | −0.22 [−0.42, −0.02] | −807 | 0.72 | 834 |
| Top 5 + Bull Flag Breakout | 875 | not backtested: quotes for 850 of 875 signals are not cached | | | | | | |
| Bull Flag Breakout (no Top 5 filter) | 1,140 | not backtested: quotes for 1,112 of 1,140 signals are not cached | | | | | | |

The baseline rerun reproduced the frozen PR #4 ledgers byte for byte, and Top 5 HOS reproduced its earlier result exactly. A cache-only run never backtests a variant on part of its signals, so both Bull Flag variants are blocked until their quotes are available. That would need either the Mac dataset copy that held them, or an approved download.

**Historical, superseded figures:** an earlier run (`f6aa8cc`, PR #6, before the freshness policy, with quotes downloaded at the time) gave Top 5 + Bull Flag 875 signals, 189 trades, 31.5% fill rate, 28.6% win rate, −0.21 R [−0.42, −0.02], −$604, profit factor 0.72, max drawdown $688. `diagnostics_in_sample_top5_bullflag_base_cap50.{json,md}` come from that run. They are kept as history and are not reproducible from the current local data.

## What the data supports (from the earlier runs)

1. **Neither variant fixes the loss.** All three lose about 0.2 R per trade, and the confidence intervals almost coincide. The lower net loss of the Bull Flag variant comes mostly from taking fewer trades, not from a better trade.
2. **The Top 5 filter barely filters.** 68% of the baseline's breakouts already come from a symbol in the Top 5 at that minute. The daily entry and loss limits, not the signal supply, decide which trades are taken.
3. **Execution is not the source of the differences.** Every signal evaluated by both the baseline and a variant got an identical outcome: 690 of 690 for Top 5 HOS and 28 of 28 for Bull Flag. The baseline rerun reproduced the PR #4 ledgers byte for byte. P&L differences come only from which signals are taken.
4. **The shared daily risk budget shifts the session mix.** Fewer premarket signals leave budget for after hours. After-hours trades rise from 22 (baseline) to 41 and 49, and after hours remains the worst session (−0.34 to −0.64 R). Session-level comparisons are therefore path-dependent.

## Hypotheses only (in-sample, not significant)

- Top 5 HOS premarket: −0.13 R (198 trades) against the baseline's −0.19 R (214); the CIs overlap.
- Bull Flag after hours: 26.5% win rate and −0.34 R (49 trades) against −0.64 R for Top 5 HOS (41); the CIs overlap and the samples are small.
- Bull Flag signals fill more often (31.5% against 25.5%), which may reflect calmer quotes after a consolidation.

Any of these needs pre-registration and a test on trading days after 2026-10-09.

## Limitations

- **Universe:** the Top 5 is rebuilt only from symbols the dataset fetched bars for (reference close below about $18.2 premarket, $19.0 after hours) in the $1–$20 band with ≥ 100k session volume. It is not the market-wide top-gainers list. 109 of 33,630 minutes had fewer than 5 ranked symbols.
- **Survivorship:** survivorship and the other PR #4 execution assumptions apply unchanged.
- **Detector:** the Bull Flag detector is the initial, untuned rule set. 46,523 of 123,778 attempts failed only on missing minutes inside the pattern, a sign of thin trading among Top 5 names.
