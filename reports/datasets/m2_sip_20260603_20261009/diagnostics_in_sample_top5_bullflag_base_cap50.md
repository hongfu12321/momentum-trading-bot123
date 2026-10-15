# Trade diagnostics: in_sample, top5_bullflag/base_cap50 (generated)

Signals 875 · entries 189 · no orders placed. Buckets with fewer than 30 trades are marked *inconclusive*. Patterns here are hypotheses, not validated edges.

## Overall

| n | win rate | avg R | median R | profit factor | 95% CI avg R |
|---:|---:|---:|---:|---:|---|
| 189 | 28.6% | -0.212 | -1.020 | 0.72 | [-0.42, -0.02] |

Entries 189; completed trades 189; incomplete exits 0 (0 shares unsold, 0 without a mark). R statistics, win rate, profit factor and the breakdowns use completed trades only.

Realized P&L (shares sold) $-603.60; marked unsold shares (incomplete exits, not realized) $0.00; gross $-597.00; fees $6.60; half-spread cost paid $451.11.

## Signal outcomes and reason codes

| outcome | reason | n |
|---|---|---:|
| rejected | at_signal_spread_above_cap | 355 |
| skipped | daily_loss_limit | 92 |
| skipped | daily_entry_limit | 70 |
| skipped | loss_streak_pause | 57 |
| skipped | position_open | 35 |
| rejected | at_signal_no_quote | 27 |
| skipped | after_entry_cutoff | 21 |
| rejected | at_signal_locked_quote | 16 |
| unfilled | timeout_price_above_limit | 8 |
| unfilled | timeout_spread_above_cap | 5 |

Outcome totals: completed 188, partial 1, rejected 398, skipped 275, unfilled 13.

Quote replay: 600 of 600 evaluated signals and 189 of 189 trades had cached quotes; missing data is left empty.

## Execution

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| seconds_to_fill | 0.50 | 0.50 | 0.93 | 0.75 |
| entry_slippage_bps | -42.11 | 0.00 | 0.00 | -11.56 |
| exit_slippage_bps | -91.03 | 0.00 | 43.67 | -9.91 |
| spread_cost_r | 0.08 | 0.14 | 0.27 | 0.16 |
| holding_seconds | 12.21 | 81.51 | 695.09 | 198.94 |
| signal_spread_bps_evaluated | 26.08 | 63.90 | 114.03 | 70.43 |
| signal_quote_age_s_evaluated | 0.01 | 0.17 | 1.07 | 0.39 |

Partial fills 1; incomplete exits 0; exit reasons {'target': 50, 'stop': 127, 'time': 11, 'session_end': 1}.

## Trade lifecycle (post-entry diagnostics)

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| mfe_r | -0.11 | 0.61 | 2.06 | 0.89 |
| mae_r | -1.11 | -1.02 | -0.41 | -0.89 |
| seconds_to_mfe | 0.13 | 21.49 | 221.56 | 82.79 |
| seconds_to_mae | 1.62 | 50.23 | 388.94 | 129.47 |
| stops_mfe_r | -0.13 | 0.22 | 1.28 | 0.41 |
| bid move after 1m (R) | -1.32 | -0.22 | 1.61 | -0.03 |
| bid move after 3m (R) | -1.93 | -0.42 | 2.19 | -0.11 |
| bid move after 5m (R) | -3.10 | -0.57 | 2.34 | -0.30 |
| bid move after 10m (R) | -3.85 | -0.99 | 2.66 | -0.72 |
| bid move after 15m (R) | -4.75 | -1.04 | 2.84 | -0.89 |

Reached +0.5R before -0.5R: 38.6% of 189 trades that reached either. Stops 127: 22 had first been +1R or better, 56 stopped within 60 s; near-target reversals (MFE >= 80% of target, no target exit): 12.

## Breakdowns by entry-time-known features

### session

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| premarket | 140 | 29.3% | -0.168 | -1.014 | 0.77 | [-0.38, +0.07] |  |
| afterhours | 49 | 26.5% | -0.340 | -1.040 | 0.59 | [-0.69, +0.05] |  |

### hour_et

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 4 | 25 | 24.0% | -0.442 | -0.956 | 0.48 | [-0.90, +0.05] | *inconclusive* |
| 5 | 27 | 29.6% | -0.207 | -1.018 | 0.73 | [-0.70, +0.34] | *inconclusive* |
| 6 | 24 | 33.3% | 0.040 | -1.029 | 1.06 | [-0.61, +0.69] | *inconclusive* |
| 7 | 22 | 22.7% | -0.362 | -1.030 | 0.56 | [-0.88, +0.22] | *inconclusive* |
| 8 | 27 | 37.0% | 0.110 | -0.894 | 1.19 | [-0.42, +0.66] | *inconclusive* |
| 9 | 15 | 26.7% | -0.185 | -1.026 | 0.74 | [-0.81, +0.55] | *inconclusive* |
| 16 | 17 | 29.4% | -0.321 | -1.031 | 0.60 | [-0.94, +0.33] | *inconclusive* |
| 17 | 17 | 35.3% | -0.020 | -1.038 | 0.97 | [-0.68, +0.70] | *inconclusive* |
| 18 | 13 | 15.4% | -0.678 | -1.083 | 0.30 | [-1.16, +0.01] | *inconclusive* |
| 19 | 2 | 0.0% | -1.025 | -1.025 | 0.00 | [-1.14, -0.90] | *inconclusive* |

### price

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 2–5 | 115 | 24.3% | -0.341 | -1.034 | 0.58 | [-0.58, -0.09] |  |
| 5–10 | 56 | 33.9% | -0.063 | -1.021 | 0.91 | [-0.43, +0.34] |  |
| 10–20 | 18 | 38.9% | 0.144 | -0.777 | 1.23 | [-0.51, +0.83] | *inconclusive* |

### change_pct

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 5–10 | 2 | 50.0% | -0.296 | -0.296 | 0.42 | [-1.03, +0.44] | *inconclusive* |
| 10–20 | 9 | 22.2% | -0.333 | -0.915 | 0.57 | [-1.08, +0.60] | *inconclusive* |
| 20–50 | 46 | 23.9% | -0.391 | -1.034 | 0.51 | [-0.73, -0.02] |  |
| 50–100 | 61 | 27.9% | -0.235 | -1.034 | 0.70 | [-0.58, +0.11] |  |
| >= 100 | 71 | 32.4% | -0.060 | -1.014 | 0.92 | [-0.40, +0.30] |  |

### session_volume

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 100000–300000 | 3 | 0.0% | -0.974 | -1.072 | 0.00 | [-1.50, -0.35] | *inconclusive* |
| 300000–1e+06 | 4 | 25.0% | -0.116 | -0.657 | 0.82 | [-1.10, +1.41] | *inconclusive* |
| 1e+06–3e+06 | 25 | 40.0% | 0.062 | -0.957 | 1.10 | [-0.47, +0.64] | *inconclusive* |
| 3e+06–1e+07 | 72 | 25.0% | -0.365 | -1.048 | 0.56 | [-0.65, -0.07] |  |
| >= 1e+07 | 85 | 29.4% | -0.142 | -1.014 | 0.81 | [-0.44, +0.19] |  |

### volume_ratio

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| < 2 | 98 | 27.6% | -0.242 | -1.028 | 0.69 | [-0.51, +0.04] |  |
| 2–3 | 64 | 35.9% | -0.000 | -0.956 | 1.00 | [-0.35, +0.35] |  |
| 3–5 | 17 | 11.8% | -0.728 | -1.037 | 0.24 | [-1.11, -0.20] | *inconclusive* |
| 5–10 | 10 | 20.0% | -0.397 | -1.004 | 0.49 | [-1.02, +0.44] | *inconclusive* |

### breakout_strength_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| < 0 | 135 | 23.7% | -0.369 | -1.028 | 0.54 | [-0.58, -0.15] |  |
| 0–25 | 1 | 0.0% | -1.042 | -1.042 | 0.00 | — | *inconclusive* |
| 25–50 | 1 | 0.0% | -1.120 | -1.120 | 0.00 | — | *inconclusive* |
| 50–100 | 6 | 16.7% | -0.582 | -1.065 | 0.37 | [-1.15, +0.48] | *inconclusive* |
| 100–200 | 11 | 45.5% | 0.323 | -0.557 | 1.59 | [-0.53, +1.17] | *inconclusive* |
| 200–500 | 18 | 38.9% | 0.100 | -0.917 | 1.15 | [-0.56, +0.80] | *inconclusive* |
| >= 500 | 17 | 52.9% | 0.586 | 1.556 | 2.03 | [-0.26, +1.46] | *inconclusive* |

### signal_spread_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 10–20 | 23 | 43.5% | 0.184 | -1.014 | 1.31 | [-0.44, +0.87] | *inconclusive* |
| 20–35 | 81 | 28.4% | -0.157 | -1.009 | 0.78 | [-0.44, +0.14] |  |
| 35–50 | 85 | 24.7% | -0.372 | -1.054 | 0.56 | [-0.66, -0.08] |  |

### signal_quote_age_s

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–0.5 | 151 | 31.1% | -0.104 | -1.020 | 0.86 | [-0.34, +0.12] |  |
| 0.5–1 | 24 | 29.2% | -0.489 | -1.034 | 0.38 | [-0.90, -0.01] | *inconclusive* |
| 1–2 | 12 | 0.0% | -0.850 | -1.041 | 0.00 | [-1.07, -0.61] | *inconclusive* |
| 2–3 | 2 | 0.0% | -1.245 | -1.245 | 0.00 | [-1.49, -1.00] | *inconclusive* |

## Breakdowns by post-entry execution features (diagnostic only; not entry filters)

### seconds_to_fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0.5–1 | 170 | 29.4% | -0.188 | -1.021 | 0.75 | [-0.40, +0.03] |  |
| 1–2 | 10 | 0.0% | -1.036 | -1.029 | 0.00 | [-1.29, -0.82] | *inconclusive* |
| 2–5 | 6 | 50.0% | 0.383 | 0.378 | 1.63 | [-0.80, +1.53] | *inconclusive* |
| >= 5 | 3 | 33.3% | -0.049 | -0.974 | 0.93 | [-1.11, +1.94] | *inconclusive* |

### fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| full | 188 | 28.2% | -0.224 | -1.021 | 0.71 | [-0.43, -0.03] |  |
| partial | 1 | 100.0% | 1.939 | 1.939 | — | — | *inconclusive* |

### entry_slippage_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| < -1 | 48 | 33.3% | -0.023 | -1.018 | 0.97 | [-0.45, +0.42] |  |
| -1–0 | 2 | 50.0% | 0.476 | 0.476 | 1.85 | [-1.12, +2.08] | *inconclusive* |
| 0–1 | 131 | 26.0% | -0.310 | -1.027 | 0.61 | [-0.52, -0.08] |  |
| 10–25 | 8 | 37.5% | 0.087 | -0.851 | 1.14 | [-0.87, +1.14] | *inconclusive* |

