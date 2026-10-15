# Trade diagnostics: in_sample, bullflag/base_cap50 (generated)

Signals 1,140 · entries 195 · no orders placed. Buckets with fewer than 30 trades are marked *inconclusive*. Patterns here are hypotheses, not validated edges.

## Overall

| n | win rate | avg R | median R | profit factor | 95% CI avg R |
|---:|---:|---:|---:|---:|---|
| 195 | 25.6% | -0.303 | -1.026 | 0.62 | [-0.48, -0.11] |

Entries 195; completed trades 195; incomplete exits 0 (0 shares unsold, 0 without a mark). R statistics, win rate, profit factor and the breakdowns use completed trades only.

Realized P&L (shares sold) $-885.70; marked unsold shares (incomplete exits, not realized) $0.00; gross $-878.84; fees $6.86; half-spread cost paid $481.37.

## Signal outcomes and reason codes

| outcome | reason | n |
|---|---|---:|
| rejected | at_signal_spread_above_cap | 438 |
| skipped | daily_loss_limit | 130 |
| skipped | loss_streak_pause | 114 |
| skipped | daily_entry_limit | 92 |
| rejected | at_signal_no_quote | 58 |
| skipped | position_open | 46 |
| skipped | after_entry_cutoff | 34 |
| rejected | at_signal_locked_quote | 18 |
| unfilled | timeout_price_above_limit | 7 |
| unfilled | timeout_spread_above_cap | 7 |
| unfilled | timeout_stale_quote | 1 |

Outcome totals: completed 193, partial 2, rejected 514, skipped 416, unfilled 15.

Quote replay: 724 of 724 evaluated signals and 195 of 195 trades had cached quotes; missing data is left empty.

## Execution

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| seconds_to_fill | 0.50 | 0.50 | 1.03 | 0.77 |
| entry_slippage_bps | -42.11 | 0.00 | 0.00 | -11.58 |
| exit_slippage_bps | -79.05 | 0.00 | 42.19 | -10.34 |
| spread_cost_r | 0.08 | 0.14 | 0.27 | 0.17 |
| holding_seconds | 12.21 | 88.03 | 719.82 | 222.74 |
| signal_spread_bps_evaluated | 26.35 | 65.90 | 134.23 | 77.49 |
| signal_quote_age_s_evaluated | 0.02 | 0.21 | 1.39 | 0.47 |

Partial fills 2; incomplete exits 0; exit reasons {'target': 45, 'stop': 133, 'time': 15, 'session_end': 2}.

## Trade lifecycle (post-entry diagnostics)

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| mfe_r | -0.11 | 0.57 | 2.06 | 0.84 |
| mae_r | -1.12 | -1.02 | -0.41 | -0.90 |
| seconds_to_mfe | 0.16 | 20.25 | 221.56 | 80.35 |
| seconds_to_mae | 2.18 | 54.54 | 497.41 | 147.64 |
| stops_mfe_r | -0.13 | 0.29 | 1.28 | 0.42 |
| bid move after 1m (R) | -1.37 | -0.20 | 1.39 | -0.06 |
| bid move after 3m (R) | -1.95 | -0.47 | 2.13 | -0.20 |
| bid move after 5m (R) | -3.10 | -0.60 | 2.24 | -0.36 |
| bid move after 10m (R) | -3.75 | -0.93 | 2.27 | -0.75 |
| bid move after 15m (R) | -4.64 | -1.03 | 2.66 | -0.95 |

Reached +0.5R before -0.5R: 37.9% of 195 trades that reached either. Stops 133: 24 had first been +1R or better, 58 stopped within 60 s; near-target reversals (MFE >= 80% of target, no target exit): 13.

## Breakdowns by entry-time-known features

### session

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| premarket | 151 | 27.2% | -0.237 | -1.018 | 0.69 | [-0.44, -0.01] |  |
| afterhours | 44 | 20.5% | -0.530 | -1.057 | 0.40 | [-0.86, -0.17] |  |

### hour_et

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 4 | 27 | 25.9% | -0.373 | -0.956 | 0.55 | [-0.83, +0.15] | *inconclusive* |
| 5 | 28 | 28.6% | -0.244 | -1.019 | 0.69 | [-0.73, +0.33] | *inconclusive* |
| 6 | 26 | 30.8% | -0.054 | -1.029 | 0.93 | [-0.63, +0.57] | *inconclusive* |
| 7 | 26 | 19.2% | -0.480 | -1.015 | 0.42 | [-0.88, -0.02] | *inconclusive* |
| 8 | 32 | 31.2% | -0.108 | -0.919 | 0.84 | [-0.58, +0.39] |  |
| 9 | 12 | 25.0% | -0.130 | -1.019 | 0.80 | [-0.81, +0.64] | *inconclusive* |
| 16 | 15 | 26.7% | -0.431 | -1.031 | 0.49 | [-1.06, +0.24] | *inconclusive* |
| 17 | 17 | 17.6% | -0.607 | -1.084 | 0.36 | [-1.15, +0.01] | *inconclusive* |
| 18 | 10 | 20.0% | -0.450 | -1.049 | 0.45 | [-1.08, +0.36] | *inconclusive* |
| 19 | 2 | 0.0% | -1.025 | -1.025 | 0.00 | [-1.14, -0.90] | *inconclusive* |

### price

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 2–5 | 121 | 21.5% | -0.442 | -1.037 | 0.48 | [-0.66, -0.22] |  |
| 5–10 | 55 | 30.9% | -0.129 | -1.020 | 0.82 | [-0.50, +0.24] |  |
| 10–20 | 19 | 36.8% | 0.078 | -1.020 | 1.12 | [-0.58, +0.74] | *inconclusive* |

### change_pct

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 5–10 | 3 | 33.3% | -0.733 | -1.027 | 0.17 | [-1.61, +0.44] | *inconclusive* |
| 10–20 | 19 | 15.8% | -0.630 | -1.037 | 0.28 | [-1.04, -0.09] | *inconclusive* |
| 20–50 | 55 | 23.6% | -0.367 | -1.022 | 0.53 | [-0.69, -0.01] |  |
| 50–100 | 53 | 26.4% | -0.265 | -1.040 | 0.66 | [-0.62, +0.11] |  |
| >= 100 | 65 | 29.2% | -0.165 | -1.020 | 0.79 | [-0.50, +0.20] |  |

### session_volume

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 100000–300000 | 5 | 0.0% | -1.016 | -1.072 | 0.00 | [-1.33, -0.64] | *inconclusive* |
| 300000–1e+06 | 6 | 33.3% | 0.010 | -0.657 | 1.01 | [-1.18, +1.20] | *inconclusive* |
| 1e+06–3e+06 | 32 | 25.0% | -0.400 | -1.036 | 0.52 | [-0.85, +0.07] |  |
| 3e+06–1e+07 | 72 | 25.0% | -0.353 | -1.048 | 0.57 | [-0.65, -0.05] |  |
| >= 1e+07 | 80 | 27.5% | -0.198 | -1.014 | 0.73 | [-0.49, +0.12] |  |

### volume_ratio

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| < 2 | 101 | 22.8% | -0.384 | -1.038 | 0.54 | [-0.63, -0.11] |  |
| 2–3 | 63 | 33.3% | -0.061 | -0.956 | 0.91 | [-0.40, +0.29] |  |
| 3–5 | 21 | 19.0% | -0.597 | -1.037 | 0.35 | [-1.07, -0.08] | *inconclusive* |
| 5–10 | 9 | 22.2% | -0.327 | -0.974 | 0.57 | [-1.02, +0.59] | *inconclusive* |
| 10–20 | 1 | 0.0% | -1.009 | -1.009 | 0.00 | — | *inconclusive* |

### breakout_strength_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| < 0 | 143 | 23.1% | -0.380 | -1.026 | 0.52 | [-0.58, -0.16] |  |
| 0–25 | 2 | 0.0% | -1.160 | -1.160 | 0.00 | [-1.28, -1.04] | *inconclusive* |
| 25–50 | 1 | 0.0% | -1.324 | -1.324 | 0.00 | — | *inconclusive* |
| 50–100 | 7 | 14.3% | -0.735 | -1.110 | 0.29 | [-1.31, +0.24] | *inconclusive* |
| 100–200 | 11 | 27.3% | -0.264 | -1.009 | 0.67 | [-1.02, +0.61] | *inconclusive* |
| 200–500 | 15 | 33.3% | -0.049 | -0.921 | 0.93 | [-0.71, +0.75] | *inconclusive* |
| >= 500 | 16 | 50.0% | 0.474 | 0.511 | 1.78 | [-0.41, +1.32] | *inconclusive* |

### signal_spread_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 10–20 | 27 | 33.3% | -0.077 | -1.027 | 0.89 | [-0.62, +0.51] | *inconclusive* |
| 20–35 | 77 | 28.6% | -0.148 | -1.006 | 0.80 | [-0.45, +0.17] |  |
| 35–50 | 91 | 20.9% | -0.502 | -1.054 | 0.43 | [-0.75, -0.24] |  |

### signal_quote_age_s

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–0.5 | 148 | 29.1% | -0.179 | -1.020 | 0.77 | [-0.40, +0.04] |  |
| 0.5–1 | 30 | 23.3% | -0.562 | -1.029 | 0.30 | [-0.89, -0.17] |  |
| 1–2 | 14 | 0.0% | -0.931 | -1.082 | 0.00 | [-1.14, -0.69] | *inconclusive* |
| 2–3 | 3 | 0.0% | -0.923 | -1.002 | 0.00 | [-1.49, -0.28] | *inconclusive* |

## Breakdowns by post-entry execution features (diagnostic only; not entry filters)

### seconds_to_fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0.5–1 | 174 | 25.9% | -0.290 | -1.026 | 0.63 | [-0.48, -0.10] |  |
| 1–2 | 11 | 9.1% | -0.873 | -1.002 | 0.07 | [-1.20, -0.47] | *inconclusive* |
| 2–5 | 7 | 42.9% | 0.152 | -1.028 | 1.22 | [-0.89, +1.20] | *inconclusive* |
| >= 5 | 3 | 33.3% | -0.049 | -0.974 | 0.93 | [-1.11, +1.94] | *inconclusive* |

### fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| full | 193 | 25.4% | -0.310 | -1.026 | 0.61 | [-0.50, -0.12] |  |
| partial | 2 | 50.0% | 0.355 | 0.355 | 1.58 | [-1.23, +1.94] | *inconclusive* |

### entry_slippage_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| < -1 | 47 | 36.2% | 0.062 | -1.014 | 1.09 | [-0.38, +0.48] |  |
| -1–0 | 2 | 50.0% | 0.476 | 0.476 | 1.85 | [-1.12, +2.08] | *inconclusive* |
| 0–1 | 139 | 21.6% | -0.445 | -1.029 | 0.47 | [-0.65, -0.24] |  |
| 10–25 | 7 | 28.6% | -0.162 | -1.020 | 0.77 | [-1.01, +0.78] | *inconclusive* |

