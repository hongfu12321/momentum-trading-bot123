# M2 trade diagnostics: usage and data dictionary

`m2-diagnostics` explains a finished `m2-backtest` run. It reads the run's `attempts.csv` and `trades.csv`, the dataset's `breakout_matches.csv` and the SIP quotes the backtest cached. It makes **no network requests**: a missing cached quote file leaves the affected fields empty and is never estimated. It does not change the strategy, the risk settings or the frozen 50 bps configuration.

```bash
momentum-bot m2-diagnostics --dataset reports/datasets/m2_sip_20260603_20261009 --sample in_sample --scenario base_cap50
# report-only view of the hold-out (never use it to choose filters or parameters):
momentum-bot m2-diagnostics --dataset reports/datasets/m2_sip_20260603_20261009 --sample out_of_sample --scenario base_cap50 --confirm-out-of-sample
```

| output | contents | committed? |
|---|---|---|
| `diagnostics_<sample>_<scenario>.md` | generated aggregate report: outcomes, reason codes, execution, lifecycle and bucket tables | yes (aggregate only) |
| `diagnostics_<sample>_<scenario>.json` | the same aggregates, machine-readable | yes (aggregate only) |
| `diagnostics/<sample>/<scenario>/signal_ledger.csv` | one row per signal | **no**: per-symbol, licensed-data derived |
| `diagnostics/<sample>/<scenario>/trade_ledger.csv` | one row per filled trade | **no** |
| `diagnostics/<sample>/<scenario>/failure_cases.md` | worst/best 20, fast reversals, stop-outs after favourable moves, near-target reversals, with quote-file references | **no** |
| `diagnostics/<sample>/<scenario>/dashboard.html` | standalone interactive dashboard (filters by session, exit reason and hour; charts). It embeds per-trade rows and makes no external requests | **no**; never publish it |

To replay a case, open the files named in `quote_files` under `cache/backtest_quotes/`. Each is gzip JSON lines of raw Alpaca SIP quotes.

## Research-integrity rules built in

- **Entry-time features** come from the trigger bar and earlier data, plus the quote prevailing at signal time. Only these may motivate a future entry filter. Post-entry fields explain outcomes and must not be used as filters.
- In-sample and out-of-sample are processed and reported separately. The out-of-sample view needs an explicit flag and is for reporting only.
- Buckets with fewer than 30 trades are marked *inconclusive*. Every pattern is a hypothesis until it is pre-registered and tested on data that has not been looked at (after 2026-10-09).

## Signal ledger (one row per signal)

| column | group | definition |
|---|---|---|
| `symbol`, `trading_date`, `sample`, `scenario` | id | Signal identity, chronological sample, and the backtest scenario (e.g. `base_cap50`). |
| `signal_bar_start_utc` | entry-time | Start of the 1-minute trigger bar. |
| `signal_available_utc` | entry-time | Trigger bar start + 1 minute: the earliest time the signal is known. |
| `session` | entry-time | `premarket` (04:00–09:30 ET) or `afterhours` (16:00–20:00 ET). |
| `hour_et` | entry-time | Hour (America/New_York) of `signal_available_utc`. |
| `price` | entry-time | Trigger bar close (raw, unadjusted). |
| `change_pct` | entry-time | Trigger close / reference close − 1, in %. The reference is the previous regular close for premarket and the same day's regular close for after hours, split-adjusted on ex-dates. |
| `session_volume` | entry-time | Cumulative session SIP volume through the trigger bar. The after-hours closing-auction bar counts as 0. |
| `volume_ratio` | entry-time | Trigger bar volume / mean volume of the previous 5 completed bars. |
| `breakout_strength_bps` | entry-time | (trigger close / highest high of the earlier bars in the session − 1) × 10,000. |
| `signal_bid`, `signal_ask` | entry-time | The quote prevailing at `signal_available_utc` (latest quote with t ≤ that time). Empty when the signal was skipped (no quotes fetched) or no quote existed. |
| `signal_spread_bps` | entry-time | (ask − bid) / mid × 10,000. Only for executable quotes (ask > bid); empty otherwise. |
| `signal_quote_age_s` | entry-time | `signal_available_utc` − quote time, in seconds. |
| `signal_quote_state` | entry-time | `executable`, `locked`, `crossed` or `one_sided`. |
| `latency_s` | scenario | The scenario's simulated order latency. |
| `outcome` | result | `skipped` (a risk or portfolio rule blocked evaluation), `rejected` (refused at signal time), `unfilled` (sent but nothing filled before the 10 s timeout), `partial` (some shares filled, exit complete), `completed` (full fill, exit complete), or `incomplete_exit` (the exit could not sell everything within the data; the remainder is marked). |
| `reason` | result | Reason code. Skipped: `position_open`, `daily_entry_limit`, `daily_loss_limit`, `loss_streak_pause`, `after_entry_cutoff`. Rejected: `at_signal_<cause>`. Unfilled: `timeout_<most common cause>`, where cause is one of `spread_above_cap`, `stale_quote`, `locked_quote`, `crossed_quote`, `one_sided_quote`, `no_quote`, `price_above_limit`, `no_displayed_size`. Filled trades show `filled`. |
| `quotes_cached` | data | True when the cached entry-window quotes were found. Empty for skipped signals. |

## Trade ledger (one row per filled trade; adds to the signal columns)

| column | group | definition |
|---|---|---|
| `requested_qty`, `filled_qty`, `fill` | execution | Shares wanted (risk sizing), shares bought, and `full` or `partial`. |
| `entry_first_fill_utc` | execution | First simulated buy fill. It is never earlier than signal availability + latency. |
| `seconds_to_fill` | execution | First fill time − `signal_available_utc`. |
| `entry_price` | execution | Volume-weighted buy price. |
| `entry_slippage_bps` | execution | (entry price / signal-time ask − 1) × 10,000. Positive means paid more than the ask seen at signal time. Negative means the ask fell before the order arrived. |
| `exit_reason` | execution | `stop` (bid ≤ entry × 0.97), `target` (bid ≥ entry × 1.06), `time` (15 minutes after entry) or `session_end` (2 minutes before close). |
| `exit_trigger_utc`, `exit_last_fill_utc` | execution | When the exit was decided, and when its last share was sold. |
| `exit_trigger_bid` | execution | Bid of the executable quote prevailing at the exit trigger. |
| `exit_price` | execution | Volume-weighted sell price, including any marked remainder. |
| `exit_slippage_bps` | execution | (exit price / exit trigger bid − 1) × 10,000. Negative means sold below the bid seen at the trigger. |
| `holding_seconds` | execution | Last exit fill − first entry fill. |
| `spread_cost_usd` | cost | (half the spread of the signal-time quote + half the spread of the exit-trigger quote) × shares. This is the spread paid versus mid-price fills. |
| `spread_cost_r` | cost | The same cost per share, divided by the planned risk per share (entry × 3%). |
| `gross_usd`, `fees_usd`, `net_usd` | P&L | Proceeds − cost; SEC and FINRA TAF fees; gross − fees. |
| `realized_usd` | P&L | `net_usd` when the exit completed, else empty. |
| `marked_usd` | P&L | `net_usd` of an incomplete exit, whose remainder was marked at the last executable bid. These are kept apart from realized P&L. |
| `r_multiple` | P&L | `net_usd` / (entry price × 3% × filled shares). |
| `mfe_r`, `mae_r` | post-entry | Maximum favourable and adverse excursion: the max and min of (bid − entry price) / risk per share over executable quotes from the first entry fill to the exit trigger. Bid-based, so the entry spread is already included at t = 0. |
| `seconds_to_mfe`, `seconds_to_mae` | post-entry | Seconds from the first entry fill to the first time the MFE (or MAE) was reached. |
| `favorable_first` | post-entry | True if the bid reached +0.5R before −0.5R, False if −0.5R came first, empty if neither happened. |
| `move_{1,3,5,10,15}m_r` | post-entry | (bid of the latest executable quote at entry fill + k minutes − entry price) / risk, measured even after the trade exited. Empty past the fetched quotes (they end 17.5 minutes after the signal, or at the session close). |
| `stopped_after_1r_favorable` | post-entry | Stop exit with MFE ≥ +1R. |
| `near_target_reversal` | post-entry | Non-target exit with MFE ≥ 80% of the 2R target (1.6R). |
| `fast_reversal` | post-entry | Stop exit with holding time ≤ 60 s. |
| `quote_files` | replay | The two cached quote files (entry window; holding window) used for this trade. |

## Aggregate metrics

| metric | definition |
|---|---|
| `n` | Trades in the group. |
| win rate | Share of trades with `r_multiple` > 0. |
| avg R, median R | Mean and median of `r_multiple`. |
| profit factor | Sum of positive R / −sum of non-positive R. This is R-based, so it can differ slightly from the USD-based figure in the backtest summary. It is empty when there are no losses. |
| 95% CI avg R | Bootstrap percentile interval of the mean R (2,000 resamples, seed 0). It is only a rough guide for small groups. |
| inconclusive | n < 30. |
| p10 / median / p90 / mean | Distribution of a ledger column over the rows where it is known. |
| bucket edges | Half-open `[lo, hi)`. `< x` and `>= x` are open ends; `unknown` means the value is missing. |
