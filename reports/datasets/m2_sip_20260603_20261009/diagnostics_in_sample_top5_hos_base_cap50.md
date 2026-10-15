# Trade diagnostics: in_sample, top5_hos/base_cap50 (generated)

Signals 2,148 · entries 240 · no orders placed. Buckets with fewer than 30 trades are marked *inconclusive*. Patterns here are hypotheses, not validated edges.

## Overall

| n | win rate | avg R | median R | profit factor | 95% CI avg R |
|---:|---:|---:|---:|---:|---|
| 240 | 27.5% | -0.224 | -1.034 | 0.72 | [-0.42, -0.02] |

Entries 240; completed trades 240; incomplete exits 0 (0 shares unsold, 0 without a mark). R statistics, win rate, profit factor and the breakdowns use completed trades only.

Realized P&L (shares sold) $-807.24; marked unsold shares (incomplete exits, not realized) $0.00; gross $-798.80; fees $8.44; half-spread cost paid $649.26.

## Signal outcomes and reason codes

| outcome | reason | n |
|---|---|---:|
| rejected | at_signal_spread_above_cap | 597 |
| skipped | daily_entry_limit | 587 |
| skipped | loss_streak_pause | 334 |
| skipped | daily_loss_limit | 296 |
| rejected | at_signal_no_quote | 31 |
| skipped | position_open | 26 |
| unfilled | timeout_spread_above_cap | 15 |
| rejected | at_signal_locked_quote | 12 |
| unfilled | timeout_price_above_limit | 6 |
| skipped | after_entry_cutoff | 4 |

Outcome totals: completed 238, partial 2, rejected 640, skipped 1247, unfilled 21.

Quote replay: 901 of 901 evaluated signals and 240 of 240 trades had cached quotes; missing data is left empty.

## Execution

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| seconds_to_fill | 0.50 | 0.50 | 2.43 | 1.03 |
| entry_slippage_bps | -67.95 | 0.00 | 0.00 | -19.58 |
| exit_slippage_bps | -116.28 | 0.00 | 70.42 | -6.43 |
| spread_cost_r | 0.09 | 0.15 | 0.29 | 0.18 |
| holding_seconds | 3.66 | 28.49 | 226.56 | 102.90 |
| signal_spread_bps_evaluated | 28.34 | 68.53 | 194.17 | 94.64 |
| signal_quote_age_s_evaluated | 0.01 | 0.08 | 0.53 | 0.21 |

Partial fills 2; incomplete exits 0; exit reasons {'stop': 166, 'target': 64, 'time': 10}.

## Trade lifecycle (post-entry diagnostics)

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| mfe_r | -0.13 | 0.65 | 2.08 | 0.85 |
| mae_r | -1.14 | -1.02 | -0.31 | -0.89 |
| seconds_to_mfe | 0.01 | 7.94 | 134.08 | 55.29 |
| seconds_to_mae | 0.83 | 13.55 | 166.79 | 65.40 |
| stops_mfe_r | -0.14 | 0.11 | 1.26 | 0.40 |
| bid move after 1m (R) | -2.74 | -0.45 | 2.44 | -0.16 |
| bid move after 3m (R) | -4.64 | -0.93 | 2.71 | -0.71 |
| bid move after 5m (R) | -5.30 | -0.81 | 3.76 | -0.62 |
| bid move after 10m (R) | -6.64 | -1.08 | 3.81 | -0.94 |
| bid move after 15m (R) | -7.84 | -1.62 | 4.19 | -1.37 |

Reached +0.5R before -0.5R: 39.2% of 240 trades that reached either. Stops 166: 33 had first been +1R or better, 120 stopped within 60 s; near-target reversals (MFE >= 80% of target, no target exit): 6.

## Breakdowns by entry-time-known features

### session

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| premarket | 198 | 30.3% | -0.134 | -1.027 | 0.83 | [-0.35, +0.08] |  |
| afterhours | 42 | 14.3% | -0.648 | -1.100 | 0.32 | [-0.98, -0.27] |  |

### hour_et

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 4 | 73 | 27.4% | -0.252 | -1.032 | 0.69 | [-0.58, +0.09] |  |
| 5 | 35 | 31.4% | -0.189 | -1.035 | 0.76 | [-0.65, +0.30] |  |
| 6 | 21 | 33.3% | 0.139 | -0.982 | 1.16 | [-0.82, +1.26] | *inconclusive* |
| 7 | 36 | 25.0% | -0.256 | -0.980 | 0.68 | [-0.69, +0.21] |  |
| 8 | 27 | 37.0% | 0.071 | -1.032 | 1.10 | [-0.51, +0.69] | *inconclusive* |
| 9 | 6 | 50.0% | 0.481 | 0.471 | 1.76 | [-0.89, +1.77] | *inconclusive* |
| 16 | 25 | 16.0% | -0.518 | -1.017 | 0.39 | [-0.93, -0.05] | *inconclusive* |
| 17 | 12 | 16.7% | -0.603 | -1.142 | 0.38 | [-1.22, +0.26] | *inconclusive* |
| 18 | 5 | 0.0% | -1.408 | -1.340 | 0.00 | [-1.68, -1.14] | *inconclusive* |

### price

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 1–2 | 1 | 0.0% | -1.085 | -1.085 | 0.00 | — | *inconclusive* |
| 2–5 | 143 | 27.3% | -0.266 | -1.055 | 0.69 | [-0.50, -0.04] |  |
| 5–10 | 73 | 31.5% | -0.130 | -1.012 | 0.83 | [-0.47, +0.22] |  |
| 10–20 | 23 | 17.4% | -0.221 | -0.933 | 0.72 | [-0.89, +0.76] | *inconclusive* |

### change_pct

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 5–10 | 6 | 33.3% | 0.202 | -0.397 | 1.43 | [-0.81, +1.31] | *inconclusive* |
| 10–20 | 26 | 7.7% | -0.801 | -1.063 | 0.16 | [-1.08, -0.41] | *inconclusive* |
| 20–50 | 76 | 25.0% | -0.360 | -1.078 | 0.58 | [-0.67, -0.03] |  |
| 50–100 | 59 | 25.4% | -0.347 | -1.045 | 0.60 | [-0.72, +0.04] |  |
| >= 100 | 73 | 38.4% | 0.188 | -1.001 | 1.27 | [-0.21, +0.64] |  |

### session_volume

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 100000–300000 | 22 | 13.6% | -0.727 | -1.130 | 0.28 | [-1.16, -0.18] | *inconclusive* |
| 300000–1e+06 | 49 | 26.5% | -0.310 | -1.072 | 0.63 | [-0.69, +0.13] |  |
| 1e+06–3e+06 | 63 | 20.6% | -0.468 | -1.045 | 0.47 | [-0.77, -0.12] |  |
| 3e+06–1e+07 | 54 | 31.5% | -0.028 | -1.009 | 0.96 | [-0.51, +0.50] |  |
| >= 1e+07 | 52 | 38.5% | 0.162 | -0.929 | 1.24 | [-0.29, +0.59] |  |

### volume_ratio

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 2–3 | 96 | 34.4% | -0.040 | -1.011 | 0.94 | [-0.35, +0.28] |  |
| 3–5 | 69 | 21.7% | -0.370 | -1.055 | 0.58 | [-0.72, +0.05] |  |
| 5–10 | 44 | 25.0% | -0.223 | -1.030 | 0.73 | [-0.67, +0.25] |  |
| 10–20 | 19 | 21.1% | -0.432 | -1.086 | 0.51 | [-1.00, +0.25] | *inconclusive* |
| >= 20 | 12 | 25.0% | -0.524 | -1.155 | 0.49 | [-1.30, +0.39] | *inconclusive* |

### breakout_strength_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–25 | 3 | 0.0% | -0.909 | -1.038 | 0.00 | [-1.20, -0.49] | *inconclusive* |
| 25–50 | 10 | 40.0% | 0.675 | -1.013 | 1.97 | [-0.87, +2.60] | *inconclusive* |
| 50–100 | 26 | 7.7% | -0.829 | -1.082 | 0.08 | [-1.07, -0.54] | *inconclusive* |
| 100–200 | 36 | 33.3% | -0.087 | -1.009 | 0.88 | [-0.53, +0.39] |  |
| 200–500 | 72 | 25.0% | -0.328 | -1.041 | 0.62 | [-0.66, +0.01] |  |
| >= 500 | 93 | 32.3% | -0.101 | -1.030 | 0.87 | [-0.40, +0.22] |  |

### signal_spread_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–10 | 2 | 0.0% | -0.839 | -0.839 | 0.00 | [-1.19, -0.49] | *inconclusive* |
| 10–20 | 34 | 26.5% | -0.169 | -1.010 | 0.77 | [-0.61, +0.32] |  |
| 20–35 | 87 | 31.0% | -0.111 | -1.006 | 0.86 | [-0.43, +0.22] |  |
| 35–50 | 117 | 25.6% | -0.313 | -1.050 | 0.64 | [-0.59, +0.01] |  |

### signal_quote_age_s

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–0.5 | 211 | 29.4% | -0.172 | -1.032 | 0.79 | [-0.40, +0.05] |  |
| 0.5–1 | 16 | 25.0% | -0.356 | -1.024 | 0.53 | [-0.90, +0.26] | *inconclusive* |
| 1–2 | 9 | 0.0% | -0.940 | -1.038 | 0.00 | [-1.28, -0.59] | *inconclusive* |
| 2–3 | 4 | 0.0% | -0.790 | -0.775 | 0.00 | [-1.27, -0.31] | *inconclusive* |

## Breakdowns by post-entry execution features (diagnostic only; not entry filters)

### seconds_to_fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0.5–1 | 206 | 27.7% | -0.204 | -1.031 | 0.74 | [-0.40, +0.02] |  |
| 1–2 | 9 | 33.3% | 0.135 | -0.888 | 1.18 | [-1.06, +1.40] | *inconclusive* |
| 2–5 | 12 | 25.0% | -0.390 | -1.092 | 0.57 | [-1.17, +0.46] | *inconclusive* |
| >= 5 | 13 | 23.1% | -0.626 | -1.210 | 0.37 | [-1.27, +0.14] | *inconclusive* |

### fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| full | 238 | 27.3% | -0.228 | -1.034 | 0.72 | [-0.42, -0.03] |  |
| partial | 2 | 50.0% | 0.306 | 0.306 | 1.47 | [-1.30, +1.91] | *inconclusive* |

### entry_slippage_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| < -1 | 82 | 19.5% | -0.449 | -1.043 | 0.53 | [-0.80, -0.05] |  |
| -1–0 | 3 | 33.3% | 0.142 | -0.818 | 1.26 | [-0.83, +2.08] | *inconclusive* |
| 0–1 | 143 | 30.8% | -0.120 | -1.022 | 0.84 | [-0.36, +0.12] |  |
| 5–10 | 1 | 0.0% | -1.086 | -1.086 | 0.00 | — | *inconclusive* |
| 10–25 | 11 | 45.5% | 0.075 | -0.810 | 1.12 | [-0.71, +0.94] | *inconclusive* |

