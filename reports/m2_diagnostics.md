# M2 trade diagnostics: why the breakout strategy loses

**Scope:** the frozen base-case configuration (`base_cap50`) from `reports/m2_backtest.md`. The strategy, risk settings and the 50 bps cap are unchanged. The diagnostics replay only the SIP quotes the backtest cached: 0 network requests and 0 orders. All 925 evaluated in-sample signals, all 436 evaluated out-of-sample signals and all 353 trades had cached quotes, so no field was estimated.
**Generated aggregates:** `reports/datasets/m2_sip_20260603_20261009/diagnostics_{in_sample,out_of_sample}_base_cap50.{md,json}`. Field definitions: `docs/m2_diagnostics.md`. Per-trade ledgers, failure-case lists and the interactive dashboard stay local (git-ignored).
**Integrity:** every hypothesis below comes from in-sample data. Out-of-sample figures are shown only to check whether a *descriptive* observation repeats. No filter or parameter was chosen from them. Every hypothesis needs pre-registration and a test on trading days after 2026-10-09.

## Five findings

### Confirmed observations (hold in-sample and out-of-sample)

**1. Spread cost explains most of the loss; before spreads the signal is roughly break-even.** The half-spreads paid at entry and exit cost $626 in-sample, against a net loss of $823 (76%). Out-of-sample they cost $250 against $321 (78%). Per trade that is 0.18 R in-sample and 0.14 R out-of-sample. Adding it back leaves −0.05 R and −0.04 R, consistent with the idealized mid-price run (−0.04 R and −0.06 R). The signal has no gross edge to pay for an extended-hours spread.

**2. Price drifts down after the signal.** The median executable bid relative to the entry price falls steadily:

| minutes after entry | 1 | 3 | 5 | 10 | 15 |
|---|---:|---:|---:|---:|---:|
| in-sample median (R) | −0.26 | −0.64 | −0.71 | −0.98 | −1.08 |
| out-of-sample median (R) | −0.32 | −0.33 | −0.41 | −0.66 | −0.89 |

About 0.15 R of the 1-minute figure is the entry spread, because the move is measured from the ask paid to the bid. The rest is a fade: on average, these completed-bar breakouts have already peaked by the time an order can reach the market. Only 40% (in-sample) and 35% (out-of-sample) of trades reached +0.5 R before −0.5 R. About 30% never showed a bid above the entry price at all.

**3. Most stop-outs happen within a minute, and stops fill beyond −1 R.**
- **Speed:** 106 of 155 in-sample stops (68%) and 49 of 79 out-of-sample (62%) came within 60 s of entry.
- **Median time:** a stopped trade's median holding time is 21 s in-sample and 48 s out-of-sample.
- **Fill depth:** stops average −1.17 R and −1.11 R rather than −1.00 R, because the bid gaps through the stop level in thin extended-hours books.

**4. The win rate is far below break-even, and giving back winners is not the main problem.** Winners average +2.05 R and losers −1.10 R, so break-even needs about a 35% win rate. Observed: 27.5% in-sample and 29.1% out-of-sample. Only 34 of 155 in-sample stops (22%) and 7 of 79 out-of-sample (9%) had first been +1 R or better. Near-target reversals (at least 80% of the target reached without a target exit) were rare: 8 and 3. A different exit would not fix trades that never move in our favour.

### Exploratory hypotheses (in-sample only; not validated)

**5. The loss may be smaller for the most extreme movers and when the breakout bar's volume is only modestly elevated.** None of these differences is significant; every confidence interval overlaps the others and includes zero or near-zero.

| entry-time feature (in-sample) | bucket | n | average R | 95% CI |
|---|---|---:|---:|---|
| change vs reference | ≥ 100% | 60 | +0.07 | [−0.37, +0.58] |
| change vs reference | 20–50% | 73 | −0.40 | [−0.71, −0.07] |
| session volume | ≥ 3M shares | 86 | about 0 | about [−0.5, +0.5] |
| session volume | 1M–3M | 65 | −0.48 | [−0.76, −0.16] |
| breakout bar volume ratio | 2–3× | 87 | −0.09 | [−0.38, +0.22] |
| breakout bar volume ratio | 3–5× | 72 | −0.39 | [−0.73, −0.00] |

A post-entry diagnostic, which cannot be used as an entry filter, points the same way as finding 2. Trades whose ask had already fallen between the signal and the fill averaged −0.41 R (n = 73), against −0.16 R when the ask held (n = 153). This is consistent with adverse selection: fills come easiest when the move is already reversing. After-hours (22 trades in-sample) and individual hour-of-day buckets are too small to read.

## What this suggests for the next hypothesis (for review, not implemented)

The data points to a timing and cost problem, not an exit-tuning problem. Entering at the ask after a completed 1-minute breakout pays a large spread to buy the top of a move that typically fades. Any next hypothesis should be pre-registered and tested on unseen days, and must state in advance how it handles the spread. Examples include a pullback entry with a passive limit, a separate rule for extreme movers, or no extended-hours trading.

## Reproduce

```bash
momentum-bot m1-dataset --start 2026-06-03 --end 2026-10-09 --out-dir reports/datasets/m2_sip_20260603_20261009   # cache-only rebuild
momentum-bot m2-backtest --dataset reports/datasets/m2_sip_20260603_20261009 --sample in_sample --spread-caps 50,100,150,200
momentum-bot m2-backtest --dataset reports/datasets/m2_sip_20260603_20261009 --sample out_of_sample --spread-caps 50 --confirm-out-of-sample
momentum-bot m2-diagnostics --dataset reports/datasets/m2_sip_20260603_20261009 --sample in_sample --scenario base_cap50
momentum-bot m2-diagnostics --dataset reports/datasets/m2_sip_20260603_20261009 --sample out_of_sample --scenario base_cap50 --confirm-out-of-sample
```

The interactive dashboard is written to `reports/datasets/m2_sip_20260603_20261009/diagnostics/<sample>/base_cap50/dashboard.html`. Open it locally in a browser; it makes no network requests.
