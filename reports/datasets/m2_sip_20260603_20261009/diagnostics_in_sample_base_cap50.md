# Trade diagnostics: in_sample, base_cap50 (generated)

Signals 3,159 · trades 236 · code `ca2b4a7` · no orders placed. Buckets with fewer than 30 trades are marked *inconclusive*. Patterns here are hypotheses, not validated edges.

## Overall

| n | win rate | avg R | median R | profit factor | 95% CI avg R |
|---:|---:|---:|---:|---:|---|
| 236 | 27.5% | -0.232 | -1.032 | 0.71 | [-0.42, -0.03] |

Realized P&L $-822.70; marked (incomplete exits) $0.00; gross $-814.41; fees $8.29; half-spread cost paid $625.71.

## Signal outcomes and reason codes

| outcome | reason | n |
|---|---|---:|
| skipped | daily_entry_limit | 931 |
| skipped | daily_loss_limit | 707 |
| rejected | at_signal_spread_above_cap | 604 |
| skipped | loss_streak_pause | 532 |
| skipped | position_open | 59 |
| rejected | at_signal_no_quote | 54 |
| unfilled | timeout_spread_above_cap | 14 |
| rejected | at_signal_locked_quote | 12 |
| unfilled | timeout_price_above_limit | 5 |
| skipped | after_entry_cutoff | 5 |

Outcome totals: completed 234, partial 2, rejected 670, skipped 2234, unfilled 19.

Quote replay: 925 of 925 evaluated signals and 236 of 236 trades had cached quotes; missing data is left empty.

## Execution

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| seconds_to_fill | 0.50 | 0.50 | 1.87 | 1.04 |
| entry_slippage_bps | -48.78 | 0.00 | 0.00 | -19.93 |
| exit_slippage_bps | -101.35 | 0.00 | 63.16 | -7.74 |
| spread_cost_r | 0.09 | 0.15 | 0.27 | 0.18 |
| holding_seconds | 3.66 | 33.62 | 620.45 | 150.13 |
| signal_spread_bps_evaluated | 29.59 | 70.67 | 194.86 | 97.45 |
| signal_quote_age_s_evaluated | 0.01 | 0.10 | 0.64 | 0.26 |

Partial fills 2; incomplete exits 0; exit reasons {'stop': 155, 'target': 60, 'time': 21}.

## Trade lifecycle (post-entry diagnostics)

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| mfe_r | -0.13 | 0.65 | 2.06 | 0.84 |
| mae_r | -1.13 | -1.02 | -0.30 | -0.87 |
| seconds_to_mfe | 0.01 | 9.42 | 127.03 | 58.11 |
| seconds_to_mae | 0.74 | 14.20 | 297.88 | 92.63 |
| stops_mfe_r | -0.15 | 0.14 | 1.40 | 0.44 |
| bid move after 1m (R) | -2.61 | -0.26 | 2.39 | -0.19 |
| bid move after 3m (R) | -4.10 | -0.64 | 2.63 | -0.68 |
| bid move after 5m (R) | -4.99 | -0.71 | 3.35 | -0.59 |
| bid move after 10m (R) | -6.20 | -0.98 | 3.71 | -0.89 |
| bid move after 15m (R) | -7.51 | -1.08 | 3.89 | -1.24 |

Reached +0.5R before -0.5R: 39.7% of 232 trades that reached either. Stops 155: 34 had first been +1R or better, 106 stopped within 60 s; near-target reversals (MFE >= 80% of target, no target exit): 8.

## Breakdowns by entry-time-known features

### session

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| premarket | 214 | 29.0% | -0.190 | -1.024 | 0.76 | [-0.39, +0.03] |  |
| afterhours | 22 | 13.6% | -0.642 | -1.062 | 0.30 | [-1.05, -0.14] | *inconclusive* |

### hour_et

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 4 | 78 | 29.5% | -0.206 | -1.034 | 0.74 | [-0.53, +0.14] |  |
| 5 | 40 | 30.0% | -0.242 | -1.032 | 0.68 | [-0.65, +0.19] |  |
| 6 | 25 | 28.0% | -0.074 | -1.059 | 0.92 | [-0.90, +0.92] | *inconclusive* |
| 7 | 44 | 25.0% | -0.290 | -1.007 | 0.63 | [-0.66, +0.13] |  |
| 8 | 21 | 38.1% | 0.183 | -0.719 | 1.31 | [-0.46, +0.88] | *inconclusive* |
| 9 | 6 | 16.7% | -0.691 | -1.063 | 0.36 | [-1.52, +0.63] | *inconclusive* |
| 16 | 13 | 23.1% | -0.344 | -1.036 | 0.57 | [-0.98, +0.41] | *inconclusive* |
| 17 | 5 | 0.0% | -1.091 | -1.098 | 0.00 | [-1.22, -0.95] | *inconclusive* |
| 18 | 3 | 0.0% | -0.882 | -1.020 | 0.00 | [-1.05, -0.57] | *inconclusive* |
| 19 | 1 | 0.0% | -1.553 | -1.553 | 0.00 | — | *inconclusive* |

### price

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 2–5 | 144 | 27.1% | -0.260 | -1.050 | 0.68 | [-0.50, -0.02] |  |
| 5–10 | 67 | 29.9% | -0.173 | -1.012 | 0.77 | [-0.52, +0.19] |  |
| 10–20 | 25 | 24.0% | -0.230 | -0.888 | 0.70 | [-0.87, +0.67] | *inconclusive* |

### change_pct

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 5–10 | 7 | 28.6% | 0.038 | -0.574 | 1.07 | [-0.84, +1.18] | *inconclusive* |
| 10–20 | 44 | 25.0% | -0.324 | -0.858 | 0.54 | [-0.66, +0.03] |  |
| 20–50 | 73 | 23.3% | -0.397 | -1.075 | 0.55 | [-0.71, -0.07] |  |
| 50–100 | 52 | 26.9% | -0.307 | -1.039 | 0.64 | [-0.69, +0.10] |  |
| >= 100 | 60 | 35.0% | 0.070 | -1.033 | 1.09 | [-0.37, +0.58] |  |

### session_volume

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 100000–300000 | 28 | 28.6% | -0.266 | -1.050 | 0.67 | [-0.80, +0.30] | *inconclusive* |
| 300000–1e+06 | 57 | 28.1% | -0.257 | -1.059 | 0.68 | [-0.64, +0.14] |  |
| 1e+06–3e+06 | 65 | 20.0% | -0.481 | -1.035 | 0.43 | [-0.76, -0.16] |  |
| 3e+06–1e+07 | 51 | 31.4% | -0.027 | -0.982 | 0.96 | [-0.48, +0.53] |  |
| >= 1e+07 | 35 | 34.3% | -0.001 | -1.022 | 1.00 | [-0.54, +0.56] |  |

### volume_ratio

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 2–3 | 87 | 34.5% | -0.092 | -1.012 | 0.87 | [-0.38, +0.22] |  |
| 3–5 | 72 | 20.8% | -0.393 | -1.052 | 0.55 | [-0.73, -0.00] |  |
| 5–10 | 42 | 26.2% | -0.153 | -0.937 | 0.80 | [-0.58, +0.33] |  |
| 10–20 | 22 | 22.7% | -0.361 | -1.091 | 0.58 | [-0.91, +0.23] | *inconclusive* |
| >= 20 | 13 | 30.8% | -0.319 | -1.067 | 0.66 | [-1.14, +0.59] | *inconclusive* |

### breakout_strength_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–25 | 6 | 16.7% | -0.715 | -0.800 | 0.00 | [-1.01, -0.37] | *inconclusive* |
| 25–50 | 15 | 26.7% | 0.156 | -0.574 | 1.24 | [-0.78, +1.61] | *inconclusive* |
| 50–100 | 23 | 17.4% | -0.570 | -1.050 | 0.25 | [-0.93, -0.14] | *inconclusive* |
| 100–200 | 42 | 33.3% | -0.057 | -0.943 | 0.92 | [-0.46, +0.39] |  |
| 200–500 | 60 | 18.3% | -0.564 | -1.072 | 0.40 | [-0.87, -0.24] |  |
| >= 500 | 90 | 34.4% | -0.039 | -1.036 | 0.95 | [-0.38, +0.31] |  |

### signal_spread_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–10 | 2 | 0.0% | -0.839 | -0.839 | 0.00 | [-1.19, -0.49] | *inconclusive* |
| 10–20 | 30 | 20.0% | -0.302 | -1.010 | 0.60 | [-0.75, +0.21] |  |
| 20–35 | 88 | 31.8% | -0.127 | -1.009 | 0.83 | [-0.45, +0.22] |  |
| 35–50 | 116 | 26.7% | -0.284 | -1.048 | 0.66 | [-0.56, +0.02] |  |

### signal_quote_age_s

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–0.5 | 197 | 27.9% | -0.221 | -1.049 | 0.73 | [-0.44, -0.00] |  |
| 0.5–1 | 22 | 27.3% | -0.160 | -0.743 | 0.75 | [-0.66, +0.37] | *inconclusive* |
| 1–2 | 8 | 37.5% | -0.312 | -0.505 | 0.49 | [-1.02, +0.58] | *inconclusive* |
| 2–3 | 9 | 11.1% | -0.576 | -0.550 | 0.03 | [-0.91, -0.24] | *inconclusive* |

## Breakdowns by post-entry execution features (diagnostic only; not entry filters)

### seconds_to_fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0.5–1 | 204 | 27.9% | -0.207 | -1.020 | 0.73 | [-0.41, +0.01] |  |
| 1–2 | 8 | 25.0% | -0.201 | -1.019 | 0.77 | [-1.25, +1.03] | *inconclusive* |
| 2–5 | 11 | 27.3% | -0.276 | -1.079 | 0.67 | [-1.11, +0.62] | *inconclusive* |
| >= 5 | 13 | 23.1% | -0.610 | -1.160 | 0.38 | [-1.25, +0.15] | *inconclusive* |

### fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| full | 234 | 27.4% | -0.237 | -1.032 | 0.70 | [-0.44, -0.04] |  |
| partial | 2 | 50.0% | 0.306 | 0.306 | 1.47 | [-1.30, +1.91] | *inconclusive* |

### entry_slippage_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| < -1 | 73 | 20.5% | -0.406 | -1.047 | 0.56 | [-0.77, +0.03] |  |
| -1–0 | 1 | 100.0% | 2.076 | 2.076 | — | — | *inconclusive* |
| 0–1 | 153 | 30.1% | -0.157 | -1.012 | 0.79 | [-0.38, +0.06] |  |
| 5–10 | 1 | 0.0% | -1.086 | -1.086 | 0.00 | — | *inconclusive* |
| 10–25 | 8 | 37.5% | -0.273 | -1.122 | 0.64 | [-1.09, +0.68] | *inconclusive* |

