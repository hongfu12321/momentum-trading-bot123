# Strategy comparison: in_sample, base_cap50 (generated)

"Top 5" is ranked within the dataset's cached eligible sub-$20 universe, not the market-wide top-gainers list.

Status: **exploratory hypotheses (in-sample only); not validated**. Simulated fills against cached historical SIP quotes; 0 orders. Every variant uses the unchanged execution model, risk limits and frozen 50 bps cap.
Win rate, average R, net P&L and profit factor use completed trades only. Incomplete exits (unsold shares when the 2-minute exit window ended) are counted as entries and reported apart, never as P&L.


Sessions: 118 of 118 with cached bars (missing: none).

## all

| strategy | signals | orders sent | entries | completed trades | incomplete exits | fill rate | win rate | avg R | 95% CI | net $ | profit factor | max drawdown $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| Original HOS Breakout | 3159 | 925 | 236 | 236 | 0 | 25.5% | 27.5% | -0.24 | [-0.43, -0.04] | -847.12 | 0.70 | 871.48 |
| Top 5 (cached universe) HOS Breakout | 2148 | 901 | 240 | 240 | 0 | 26.6% | 27.5% | -0.22 | [-0.42, -0.02] | -807.24 | 0.72 | 834.08 |
| Top 5 (cached universe) + Bull Flag Breakout | 875 | not backtested: quotes for 850 of 875 signals are not cached (cache-only run) | | | | | | | | | | |
| Bull Flag Breakout (no Top 5 filter) | 1140 | not backtested: quotes for 1112 of 1140 signals are not cached (cache-only run) | | | | | | | | | | |

## premarket

| strategy | signals | orders sent | entries | completed trades | incomplete exits | fill rate | win rate | avg R | 95% CI | net $ | profit factor | max drawdown $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| Original HOS Breakout | 1622 | 806 | 214 | 214 | 0 | 26.6% | 29.0% | -0.19 | [-0.39, 0.03] | -637.36 | 0.74 | 661.72 |
| Top 5 (cached universe) HOS Breakout | 1013 | 687 | 198 | 198 | 0 | 28.8% | 30.3% | -0.13 | [-0.35, 0.08] | -402.81 | 0.83 | 548.24 |
| Top 5 (cached universe) + Bull Flag Breakout | 875 | not backtested: quotes for 850 of 875 signals are not cached (cache-only run) | | | | | | | | | | |
| Bull Flag Breakout (no Top 5 filter) | 1140 | not backtested: quotes for 1112 of 1140 signals are not cached (cache-only run) | | | | | | | | | | |

## afterhours

| strategy | signals | orders sent | entries | completed trades | incomplete exits | fill rate | win rate | avg R | 95% CI | net $ | profit factor | max drawdown $ |
|---|---:|---:|---:|---:|---:|---:|---:|---:|---|---:|---:|---:|
| Original HOS Breakout | 1537 | 119 | 22 | 22 | 0 | 18.5% | 13.6% | -0.64 | [-1.05, -0.14] | -209.75 | 0.30 | 209.75 |
| Top 5 (cached universe) HOS Breakout | 1135 | 214 | 42 | 42 | 0 | 19.6% | 14.3% | -0.65 | [-0.98, -0.27] | -404.43 | 0.32 | 413.09 |
| Top 5 (cached universe) + Bull Flag Breakout | 875 | not backtested: quotes for 850 of 875 signals are not cached (cache-only run) | | | | | | | | | | |
| Bull Flag Breakout (no Top 5 filter) | 1140 | not backtested: quotes for 1112 of 1140 signals are not cached (cache-only run) | | | | | | | | | | |

## Portfolio skips (shared daily risk budget)

| strategy | skipped, by reason |
|---|---|
| Original HOS Breakout | after_entry_cutoff 5, daily_entry_limit 931, daily_loss_limit 786, loss_streak_pause 453, position_open 59 |
| Top 5 (cached universe) HOS Breakout | after_entry_cutoff 4, daily_entry_limit 587, daily_loss_limit 296, loss_streak_pause 334, position_open 26 |

## Execution-model isolation

The per-signal simulation is shared, so a signal evaluated by both the baseline and a variant must get the same outcome. Differences in P&L then come only from which signals are taken (the filter and the path-dependent daily limits), not from execution.

| variant | signals evaluated by both | identical outcomes |
|---|---:|---:|
| Top 5 (cached universe) HOS Breakout | 690 | 690 |

## Top 5 reconstruction

Ranked universe = symbols the dataset fetched bars for (reference close below about $18.2 premarket / $19.0 after hours), filtered to the $1-$20 scan band and 100k session volume. Symbols outside it are absent, so this is not the market-wide top-gainers list.

Mean eligible symbols per session 3,436, with at least one bar 2,457. Minutes with fewer than 5 ranked symbols: 109 of 33630. Mean distinct Top 5 members per session: 25.3.

Freshness: missing bars are never filled; a price older than 5 minutes is stale and not ranked (737692 symbol-minutes excluded).

## Bull Flag detector

Parameters: `{"pole_min_gain": 0.05, "pole_min_bars": 3, "pole_max_bars": 10, "flag_min_bars": 2, "flag_max_bars": 8, "max_pullback": 0.5, "breakout_volume_multiple": 1.5, "exclude_closing_auction_bar": true}`.

Breakout attempts evaluated on Top 5 members: 126651; qualified flags: 1435; qualified while in the Top 5 and passing the scanner gate: 875.

| first failed rule | attempts |
|---|---:|
| failed_flagpole | 57893 |
| failed_complete_bars | 48562 |
| failed_pullback | 7938 |
| failed_consolidation | 5024 |
| insufficient_history | 3790 |
| qualified | 1435 |
| failed_breakout_close | 1053 |
| failed_breakout_volume | 613 |
| failed_volume_contraction | 343 |
