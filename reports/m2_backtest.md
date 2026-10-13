# M2 backtest: completed-bar breakout against historical SIP quotes

**Dataset:** `reports/datasets/m2_sip_20260603_20261009/` (90 trading days; see `reports/m2_data_readiness.md`). The committed outputs are the aggregate `backtest_summary_in_sample.json` and `backtest_summary_out_of_sample.json`. Per-trade rows and raw quotes are derived from licensed data and stay local under `backtest/` and `cache/backtest_quotes/`.
**Code:** `7f89c17` for both runs · **API:** Alpaca historical market data only: 1,608 quote requests in-sample and 906 out-of-sample, plus earlier cache warm-up · **Orders placed:** 0. There is no live or paper order path anywhere in the code.
**Samples:** in-sample is 59 trading days, 2026-06-03 to 2026-08-26 (3,159 signals). One embargo day (2026-08-27) is excluded. Out-of-sample is 30 trading days, 2026-08-28 to 2026-10-09 (1,488 signals).

## Result

**The strategy has no edge on this data.** Every configuration has negative average R, both in-sample and out-of-sample. Even the idealized upper bound (no latency, mid-price fills, unlimited size, no fees) is about −0.04 R in-sample and −0.06 R out-of-sample, and its confidence interval includes zero. Realistic execution makes it clearly negative.

| Metric (base case, frozen 50 bps cap) | In-sample | Out-of-sample |
|---|---:|---:|
| Trades | 236 | 117 |
| Win rate | 27.5% | 29.1% |
| Average R | −0.232 (95% CI −0.42 to −0.03) | −0.183 (95% CI −0.43 to +0.08) |
| Net expectancy per trade | −$3.49 | −$2.74 |
| Net P&L | −$822.70 | −$320.68 |
| Max drawdown | $847.42 (28% of $3,000) | $425.98 (14%) |
| Fill rate, all signals evaluated by the execution model | 25.5% | 26.8% |
| Fill rate, orders actually sent (signal-time rejections excluded) | 92.5% (236 of 255) | 95.1% (117 of 123) |

The out-of-sample result is consistent with in-sample. It is not evidence of profitability, and with 117 trades its confidence interval is wide.

## Method

- **Signal:** a candidate-gated SIP session-high breakout, using the M1 scanner unchanged:
  - price $1–$20;
  - change vs the previous close ≥ 10% premarket, ≥ 5% after hours;
  - session volume ≥ 100k;
  - breakout-bar volume ≥ 2× the mean of the previous five completed bars.

  The signal becomes available when its 1-minute bar completes (`*_signal_available_utc`). Nothing earlier is used.
- **Entry:** a marketable buy limit at the signal-time ask + 20 bps.
  - The quote at signal time must be fresh (≤ 3 s old), executable (ask > bid) and within the spread cap.
  - The order arrives after latency. It fills only on fresh executable quotes, up to the displayed ask size.
  - Any unfilled remainder expires after 10 s.
  - A candle touching a price never counts as a fill.
- **Exit:** stop at −3%, target at +2R (+6%), or a 15-minute time stop, flat 2 minutes before the session ends.
  - Exits trigger only on fresh executable bids.
  - They sell at the bid after latency, up to the displayed bid size per quote, until filled.
- **Risk** (docs/DESIGN.md section 5):
  - $3,000 account, $15 risk per trade, maximum notional 25%;
  - one position at a time, 5 entries per day;
  - $45 daily loss limit, pause after 3 consecutive losses;
  - no new entries in the last 10 minutes of a session.
- **Costs:** the spread (fills at the touch), SEC fee $27.80 per $1M sold, FINRA TAF $0.000166 per share sold (maximum $8.30), and zero commission.
  - These fee rates are constants in code; check them against current published rates.
  - Fees total $4–11 per run, small next to spread costs.
- **Fixed settings:** strategy and risk settings (`StrategyConfig`, `RiskConfig`) were fixed before any run. Only the spread cap was compared, on in-sample data.

### Execution scenarios

| scenario | latency | quote age | spread cap | size available | fill price | adverse slippage | fees |
|---|---:|---:|---|---|---|---:|---|
| idealized (upper-bound reference; not achievable) | 0 s | ignored | none | unlimited | mid | 0 | none |
| base (quote-aware) | 0.5 s | ≤ 3 s | grid | 100% of displayed | ask / bid | 0 | yes |
| stress (conservative) | 2 s | ≤ 3 s | grid | 50% of displayed | ask / bid | 10 bps each side | yes |

## Spread-cap selection (in-sample only)

The selection rule was set in code before the run (`select_spread_cap`). It picks the highest base-case average R among caps with at least 30 trades; ties go to the tighter cap.
- **Which caps qualified:** all four (228–236 trades each).
- **Selected cap:** **50 bps**, the least negative at −0.232 R.

The 50 bps cap was then frozen, and out-of-sample was run once with it. Nothing was retuned afterwards.

Wider caps fill more signals but do not add trades, because the daily limits bind. Instead they swap tight-spread entries for wide-spread ones, and average R falls at each step: −0.23, −0.36, −0.37, −0.38 R in the base case.

## Results

### In-sample, all configurations

| configuration | trades | orders simulated | fill rate | win rate | average R | 95% CI of average R | net expectancy / trade | net P&L | max drawdown | profit factor |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| idealized | 243 | 259 | 93.8% | 27.6% | −0.038 | [−0.21, +0.13] | −$0.56 | −$135.44 | $538.16 | 0.94 |
| base, 50 bps (selected) | 236 | 925 | 25.5% | 27.5% | −0.232 | [−0.42, −0.03] | −$3.49 | −$822.70 | $847.42 | 0.70 |
| base, 100 bps | 228 | 374 | 61.0% | 25.0% | −0.355 | [−0.54, −0.16] | −$5.34 | −$1,216.72 | $1,218.00 | 0.58 |
| base, 150 bps | 229 | 313 | 73.2% | 24.5% | −0.370 | [−0.55, −0.18] | −$5.56 | −$1,273.84 | $1,273.84 | 0.56 |
| base, 200 bps | 229 | 289 | 79.2% | 25.3% | −0.383 | [−0.56, −0.20] | −$5.75 | −$1,315.87 | $1,315.87 | 0.55 |
| stress, 50 bps | 223 | 967 | 23.1% | 26.9% | −0.329 | [−0.54, −0.11] | −$4.93 | −$1,098.94 | $1,147.84 | 0.62 |
| stress, 100 bps | 218 | 414 | 52.7% | 22.5% | −0.617 | [−0.80, −0.42] | −$9.04 | −$1,971.09 | $1,971.09 | 0.39 |
| stress, 150 bps | 218 | 342 | 63.7% | 23.4% | −0.571 | [−0.76, −0.37] | −$8.37 | −$1,824.93 | $1,824.93 | 0.43 |
| stress, 200 bps | 217 | 310 | 70.0% | 24.0% | −0.592 | [−0.79, −0.39] | −$8.69 | −$1,884.92 | $1,884.92 | 0.43 |

### Out-of-sample, frozen configuration (one run)

| configuration | trades | orders simulated | fill rate | win rate | average R | 95% CI of average R | net expectancy / trade | net P&L | max drawdown | profit factor |
|---|---:|---:|---:|---:|---:|---|---:|---:|---:|---:|
| idealized | 122 | 131 | 93.1% | 27.9% | −0.055 | [−0.29, +0.20] | −$0.82 | −$99.56 | $333.11 | 0.92 |
| base, 50 bps | 117 | 436 | 26.8% | 29.1% | −0.183 | [−0.43, +0.08] | −$2.74 | −$320.68 | $425.98 | 0.76 |
| stress, 50 bps | 118 | 479 | 24.6% | 28.0% | −0.370 | [−0.60, −0.11] | −$5.50 | −$648.45 | $721.19 | 0.57 |

Fill rate counting only orders actually sent (signal-time rejections excluded):
- **Base:** 92.5% in-sample and 95.1% out-of-sample.
- **Stress:** 83.5% in-sample and 88.7% out-of-sample.
- **Idealized:** 100%.

The 95% confidence intervals are bootstrap intervals over trades (seed 0, 2,000 resamples). Drawdown is measured on cumulative net P&L in trade order.

### By session

| sample | configuration | session | trades | fill rate | win rate | average R | net P&L | max drawdown |
|---|---|---|---:|---:|---:|---:|---:|---:|
| in-sample | idealized | premarket | 243 | 93.8% | 27.6% | −0.038 | −$135.44 | $538.16 |
| in-sample | idealized | after hours | 0 | — | — | — | $0.00 | $0.00 |
| in-sample | base, 50 bps | premarket | 214 | 26.6% | 29.0% | −0.190 | −$612.94 | $637.66 |
| in-sample | base, 50 bps | after hours | 22 | 18.5% | 13.6% | −0.642 | −$209.76 | $209.76 |
| in-sample | stress, 50 bps | premarket | 202 | 24.1% | 28.2% | −0.296 | −$895.29 | $944.19 |
| in-sample | stress, 50 bps | after hours | 21 | 16.2% | 14.3% | −0.653 | −$203.65 | $203.65 |
| out-of-sample | idealized | premarket | 122 | 93.1% | 27.9% | −0.055 | −$99.56 | $333.11 |
| out-of-sample | idealized | after hours | 0 | — | — | — | $0.00 | $0.00 |
| out-of-sample | base, 50 bps | premarket | 105 | 28.2% | 27.6% | −0.247 | −$386.65 | $453.14 |
| out-of-sample | base, 50 bps | after hours | 12 | 18.8% | 41.7% | +0.369 | $65.98 | $47.99 |
| out-of-sample | stress, 50 bps | premarket | 104 | 26.7% | 27.9% | −0.372 | −$576.24 | $643.70 |
| out-of-sample | stress, 50 bps | after hours | 14 | 15.6% | 28.6% | −0.350 | −$72.21 | $118.80 |

The positive after-hours base result out-of-sample comes from 12 trades. Its interval spans −0.46 to +1.28 R, so it means nothing on its own (see "After hours is barely tested").

### Rejected and unfilled signals

| sample | configuration | signals | skipped (risk/portfolio rules) | non-fills | non-fill reasons | skip reasons |
|---|---|---:|---:|---:|---|---|
| in-sample | idealized | 3,159 | 2,900 | 16 | no quote at signal 11, locked at signal 5 | daily entry limit 1,481, loss-streak pause 1,330, daily loss limit 63, position open 26 |
| in-sample | base, 50 bps | 3,159 | 2,234 | 689 | spread above cap at signal 604, no quote at signal 54, spread above cap until timeout 14, locked at signal 12, price above limit until timeout 5 | daily entry limit 931, daily loss limit 707, loss-streak pause 532, position open 59, after entry cutoff 5 |
| in-sample | base, 100 bps | 3,159 | 2,785 | 146 | spread above cap at signal 103, no quote 19, price above limit 11, locked 7, spread above cap until timeout 6 | daily loss limit 1,068, daily entry limit 1,062, loss-streak pause 627, position open 28 |
| in-sample | base, 150 bps | 3,159 | 2,846 | 84 | spread above cap at signal 52, no quote 13, price above limit 12, locked 6, spread above cap until timeout 1 | daily entry limit 1,149, daily loss limit 1,085, loss-streak pause 583, position open 29 |
| in-sample | base, 200 bps | 3,159 | 2,870 | 60 | spread above cap at signal 32, price above limit 12, no quote 11, locked 5 | daily loss limit 1,347, daily entry limit 1,112, loss-streak pause 386, position open 25 |
| in-sample | stress, 50 bps | 3,159 | 2,192 | 744 | spread above cap at signal 634, no quote 53, spread above cap until timeout 26, price above limit 18, locked 13 | daily loss limit 881, daily entry limit 717, loss-streak pause 525, position open 59, after entry cutoff 10 |
| in-sample | stress, 100 bps | 3,159 | 2,745 | 196 | spread above cap at signal 119, price above limit 36, no quote 21, spread above cap until timeout 14, locked 6 | daily loss limit 1,309, daily entry limit 801, loss-streak pause 599, position open 34, after entry cutoff 2 |
| in-sample | stress, 150 bps | 3,159 | 2,817 | 124 | spread above cap at signal 60, price above limit 38, no quote 15, spread above cap until timeout 6, locked 5 | daily loss limit 1,381, daily entry limit 977, loss-streak pause 427, position open 32 |
| in-sample | stress, 200 bps | 3,159 | 2,849 | 93 | spread above cap at signal 35, price above limit 35, no quote 14, locked 5, spread above cap until timeout 4 | daily loss limit 1,498, daily entry limit 993, loss-streak pause 332, position open 26 |
| out-of-sample | idealized | 1,488 | 1,357 | 9 | locked at signal 5, no quote at signal 4 | daily entry limit 714, loss-streak pause 564, daily loss limit 50, position open 29 |
| out-of-sample | base, 50 bps | 1,488 | 1,052 | 319 | spread above cap at signal 274, no quote 31, locked 8, spread above cap until timeout 4, price above limit 2 | daily loss limit 433, daily entry limit 418, loss-streak pause 153, position open 40, after entry cutoff 8 |
| out-of-sample | stress, 50 bps | 1,488 | 1,009 | 361 | spread above cap at signal 303, no quote 36, spread above cap until timeout 8, locked 7, price above limit 7 | daily loss limit 485, daily entry limit 476, position open 40, after entry cutoff 8 |

"Orders simulated" counts every signal the execution model evaluated, including those rejected at signal time. "Skipped" signals were never evaluated, because a risk or portfolio rule blocked them first.

### Fills and exits

| sample | configuration | partial fills | median entry spread (bps) | median seconds to fill | median entry vs trigger close (bps) | fees | exits (stop / target / time) | incomplete exits |
|---|---|---:|---:|---:|---:|---:|---|---:|
| in-sample | idealized | 0 | 66.2 | 0.0 | 0.0 | $0.00 | 173 / 64 / 6 | 0 |
| in-sample | base, 50 bps | 2 | 34.8 | 0.5 | 0.4 | $8.29 | 155 / 60 / 21 | 0 |
| in-sample | base, 100 bps | 2 | 53.1 | 0.5 | 1.2 | $10.79 | 163 / 54 / 11 | 0 |
| in-sample | base, 150 bps | 2 | 59.7 | 0.5 | 1.9 | $10.70 | 166 / 52 / 11 | 0 |
| in-sample | base, 200 bps | 2 | 61.2 | 0.5 | 8.2 | $10.63 | 169 / 53 / 7 | 0 |
| in-sample | stress, 50 bps | 3 | 34.9 | 2.0 | 10.0 | $7.73 | 145 / 55 / 23 | 0 |
| in-sample | stress, 100 bps | 4 | 52.6 | 2.0 | 10.0 | $10.09 | 163 / 43 / 12 | 0 |
| in-sample | stress, 150 bps | 4 | 60.0 | 2.0 | 10.0 | $10.07 | 163 / 44 / 11 | 0 |
| in-sample | stress, 200 bps | 5 | 63.4 | 2.0 | 10.0 | $9.93 | 164 / 46 / 7 | 0 |
| out-of-sample | idealized | 0 | 59.9 | 0.0 | −1.0 | $0.00 | 86 / 31 / 5 | 0 |
| out-of-sample | base, 50 bps | 0 | 33.5 | 0.5 | 9.4 | $4.10 | 79 / 31 / 7 | 1 |
| out-of-sample | stress, 50 bps | 0 | 33.9 | 2.0 | 10.0 | $4.19 | 81 / 29 / 8 | 1 |

About two-thirds of trades hit the 3% stop. Spread alone costs roughly 0.1–0.2 R per trade at 35 bps, measured against a 300 bps stop.

## Quote coverage

- **Quote availability:** historical SIP quotes were present at signal time for 94% of evaluated in-sample signals and 93% out-of-sample. A missing quote within the 3 s before the signal (5.8% in-sample, 54 of 925; 7.1% out-of-sample, 31 of 436, base at 50 bps) is recorded as a non-fill. A fill is never synthesized from bars.
- **Locked quotes:** a locked quote at signal time (1.3% and 1.8%) is a non-fill.
- **Wide spreads:** this is the main rejection. At the 50 bps cap, 65% of evaluated in-sample signals and 63% out-of-sample were refused at signal time for spread above the cap.
- **Incomplete exits:** none in-sample. Out-of-sample there was 1 in base and 1 in stress, the same trade. It reached its time exit with no fresh quote left in the fetched data, so it was marked at the last executable bid (−$0.02 and −$1.01).

Quote coverage is therefore not what limits the result. The wide spreads are.

## After hours is barely tested

The daily limits are shared across the whole trading day, and premarket comes first. The 5 entries, the $45 loss limit or the 3-loss pause are usually used up before 16:00 ET.
- **In-sample, base at 50 bps:** 1,409 of 1,537 after-hours signals were skipped for this reason, leaving 22 after-hours trades.
- **Idealized:** no after-hours trades at all, because its higher premarket fill rate uses up the limits sooner.

After-hours results (12–22 trades) are too few to judge. The engine follows the design's risk policy as written. Evaluating after hours separately would need a separate risk budget, which is a decision for review.

## Assumptions that may overstate execution quality

1. **Displayed size is fully ours.** Every quote update offers its whole displayed size to us. Consecutive updates at the same price can re-offer the same shares, and there are no competing orders.
2. **Short latency.** The base case acts 0.5 s after the bar ends. A live system must first receive the bar, which arrives after the minute closes. It must then scan thousands of symbols and route the order. The stress case's 2 s is probably closer to reality.
3. **Stops fill at the bid prevailing when the order arrives.** In fast drops, a real stop can fill well below the bid it triggered on, and the bid-size limit only partly captures this.
4. **No halts, venue-specific extended-hours rules or broker rejections.** Alpaca is assumed to accept extended-hours limit orders from 04:00 ET.
5. **Survivorship bias** in the universe (see the data readiness report) most likely leans optimistic.
6. **Out-of-sample contamination.** The out-of-sample block was inspected for data quality in M1-B. The quote probe's spread statistics, which framed the cap grid, included 19 out-of-sample windows. No strategy parameter was fitted on out-of-sample trades.

Assumptions that understate execution quality: no price improvement, no hidden or midpoint liquidity, odd lots ignored (the SIP NBBO is round lots), and locked quotes never fill.

## Reproduce

```bash
momentum-bot m1-dataset --start 2026-06-03 --end 2026-10-09 --out-dir reports/datasets/m2_sip_20260603_20261009
momentum-bot m2-backtest --dataset reports/datasets/m2_sip_20260603_20261009 --sample in_sample --spread-caps 50,100,150,200
# frozen configuration, run once:
momentum-bot m2-backtest --dataset reports/datasets/m2_sip_20260603_20261009 --sample out_of_sample --spread-caps 50 --confirm-out-of-sample
```

Reruns reuse the local quote cache. A fresh clone needs about 2,500 quote requests, roughly 45 minutes.

## Recommendation

Do not promote this setup to paper trading as a strategy. Its best realistic configuration loses about 0.2 R per trade after spreads, and the idealized ceiling is about zero. The M3 paper infrastructure can still be built and tested for plumbing, but running it with this strategy should be expected to lose money. Decisions for review:

1. Accept that the initial breakout hypothesis failed on this data, and choose and pre-register the next one.
2. Decide whether after hours gets its own risk budget so it can be evaluated on its own.
3. Reserve trading days after 2026-10-09 as an untouched hold-out for the next hypothesis.
