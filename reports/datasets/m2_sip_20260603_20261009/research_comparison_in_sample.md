# Strategy comparison: in_sample, base_cap50 (generated)

Status: **exploratory hypotheses (in-sample only); not validated**. Simulated fills against cached historical SIP quotes; 0 orders. Every variant uses the unchanged execution model, risk limits and frozen 50 bps cap.
Win rate, average R, net P&L and profit factor use completed trades only. Incomplete exits (unsold shares when the 2-minute exit window ended) are counted as entries and reported apart, never as P&L.


Sessions: 118 of 118 with cached bars (missing: none).

## all

| strategy | signals | orders sent | entries | completed trades | incomplete exits | fill rate | win rate | avg R | 95% CI | net $ | profit factor | max drawdown $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| Original HOS Breakout | 3159 | 925 | 236 | 236 | 0 | 25.5% | 27.5% | -0.24 | [-0.43, -0.04] | -847.12 | 0.70 | 871.48 |
| Top 5 (cached universe) HOS Breakout | 2141 | 900 | 239 | 239 | 0 | 26.6% | 27.6% | -0.22 | [-0.42, -0.02] | -790.57 | 0.73 | 828.07 |
| Top 5 (cached universe) + Bull Flag Breakout | 875 | 600 | 189 | 189 | 0 | 31.5% | 28.6% | -0.21 | [-0.42, -0.02] | -603.60 | 0.72 | 688.25 |

## premarket

| strategy | signals | orders sent | entries | completed trades | incomplete exits | fill rate | win rate | avg R | 95% CI | net $ | profit factor | max drawdown $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| Original HOS Breakout | 1622 | 806 | 214 | 214 | 0 | 26.6% | 29.0% | -0.19 | [-0.39, 0.03] | -637.36 | 0.74 | 661.72 |
| Top 5 (cached universe) HOS Breakout | 1013 | 687 | 198 | 198 | 0 | 28.8% | 30.3% | -0.13 | [-0.35, 0.08] | -402.81 | 0.83 | 548.24 |
| Top 5 (cached universe) + Bull Flag Breakout | 500 | 407 | 140 | 140 | 0 | 34.4% | 29.3% | -0.17 | [-0.38, 0.07] | -354.68 | 0.77 | 439.86 |

## afterhours

| strategy | signals | orders sent | entries | completed trades | incomplete exits | fill rate | win rate | avg R | 95% CI | net $ | profit factor | max drawdown $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| Original HOS Breakout | 1537 | 119 | 22 | 22 | 0 | 18.5% | 13.6% | -0.64 | [-1.05, -0.14] | -209.75 | 0.30 | 209.75 |
| Top 5 (cached universe) HOS Breakout | 1128 | 213 | 41 | 41 | 0 | 19.2% | 14.6% | -0.64 | [-0.97, -0.25] | -387.76 | 0.33 | 396.43 |
| Top 5 (cached universe) + Bull Flag Breakout | 375 | 193 | 49 | 49 | 0 | 25.4% | 26.5% | -0.34 | [-0.69, 0.05] | -248.92 | 0.59 | 277.24 |

## Portfolio skips (shared daily risk budget)

| strategy | skipped, by reason |
|---|---|
| Original HOS Breakout | after_entry_cutoff 5, daily_entry_limit 931, daily_loss_limit 786, loss_streak_pause 453, position_open 59 |
| Top 5 (cached universe) HOS Breakout | after_entry_cutoff 4, daily_entry_limit 585, daily_loss_limit 292, loss_streak_pause 334, position_open 26 |
| Top 5 (cached universe) + Bull Flag Breakout | after_entry_cutoff 21, daily_entry_limit 70, daily_loss_limit 92, loss_streak_pause 57, position_open 35 |

## Execution-model isolation

The per-signal simulation is shared, so a signal evaluated by both the baseline and a variant must get the same outcome. Differences in P&L then come only from which signals are taken (the filter and the path-dependent daily limits), not from execution.

| variant | signals evaluated by both | identical outcomes |
|---|---:|---:|
| Top 5 (cached universe) HOS Breakout | 690 | 690 |
| Top 5 (cached universe) + Bull Flag Breakout | 28 | 28 |

## Top 5 reconstruction

Ranked universe = symbols the dataset fetched bars for (reference close below about $18.2 premarket / $19.0 after hours), filtered to the $1-$20 scan band and 100k session volume. Symbols outside it are absent, so this is not the market-wide top-gainers list.

Mean eligible symbols per session 3,436, with at least one bar 2,457. Minutes with fewer than 5 ranked symbols: 109 of 33630. Mean distinct Top 5 members per session: 24.5.

## Bull Flag detector

Parameters: `{"pole_min_gain": 0.05, "pole_min_bars": 3, "pole_max_bars": 10, "flag_min_bars": 2, "flag_max_bars": 8, "max_pullback": 0.5, "breakout_volume_multiple": 1.5, "exclude_closing_auction_bar": true}`.

Breakout attempts evaluated on Top 5 members: 123778; qualified flags: 1431; qualified while in the Top 5 and passing the scanner gate: 875.

| first failed rule | attempts |
|---|---:|
| failed_flagpole | 57207 |
| failed_complete_bars | 46523 |
| failed_pullback | 7917 |
| failed_consolidation | 5021 |
| insufficient_history | 3678 |
| qualified | 1431 |
| failed_breakout_close | 1047 |
| failed_breakout_volume | 611 |
| failed_volume_contraction | 343 |
