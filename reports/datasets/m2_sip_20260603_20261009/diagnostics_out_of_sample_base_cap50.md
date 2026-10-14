# Trade diagnostics: out_of_sample, base_cap50 (generated)

Signals 1,488 · trades 117 · code `d5bdb66` · no orders placed. Buckets with fewer than 30 trades are marked *inconclusive*. Patterns here are hypotheses, not validated edges.

## Overall

| n | win rate | avg R | median R | profit factor | 95% CI avg R |
|---:|---:|---:|---:|---:|---|
| 116 | 29.3% | -0.186 | -1.028 | 0.76 | [-0.43, +0.08] |

Entries 117; completed trades 116; incomplete exits 1 (45 shares unsold, 0 without a mark). R statistics, win rate, profit factor and the breakdowns use completed trades only.

Realized P&L (shares sold) $-321.54; marked unsold shares (incomplete exits, not realized) $0.00; gross $-317.46; fees $4.08; half-spread cost paid $249.54.

## Signal outcomes and reason codes

| outcome | reason | n |
|---|---|---:|
| skipped | daily_loss_limit | 433 |
| skipped | daily_entry_limit | 376 |
| rejected | at_signal_spread_above_cap | 282 |
| skipped | loss_streak_pause | 153 |
| skipped | position_open | 76 |
| rejected | at_signal_no_quote | 28 |
| rejected | at_signal_locked_quote | 9 |
| skipped | after_entry_cutoff | 8 |
| unfilled | timeout_spread_above_cap | 4 |
| unfilled | timeout_price_above_limit | 2 |

Outcome totals: completed 116, incomplete_exit 1, rejected 319, skipped 1046, unfilled 6.

Quote replay: 442 of 442 evaluated signals and 117 of 117 trades had cached quotes; missing data is left empty.

## Execution

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| seconds_to_fill | 0.50 | 0.50 | 1.67 | 0.89 |
| entry_slippage_bps | -44.64 | 0.00 | 0.00 | -15.23 |
| exit_slippage_bps | -73.80 | 0.00 | 63.97 | -7.79 |
| spread_cost_r | 0.07 | 0.13 | 0.23 | 0.14 |
| holding_seconds | 8.54 | 60.93 | 651.50 | 171.65 |
| signal_spread_bps_evaluated | 25.87 | 68.73 | 149.41 | 81.17 |
| signal_quote_age_s_evaluated | 0.01 | 0.11 | 0.68 | 0.27 |

Partial fills 0; incomplete exits 1; exit reasons {'stop': 79, 'target': 31, 'time': 7}.

## Trade lifecycle (post-entry diagnostics)

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| mfe_r | -0.12 | 0.47 | 2.06 | 0.81 |
| mae_r | -1.12 | -1.02 | -0.34 | -0.87 |
| seconds_to_mfe | 0.02 | 9.60 | 277.26 | 86.18 |
| seconds_to_mae | 1.86 | 36.02 | 251.58 | 96.49 |
| stops_mfe_r | -0.13 | 0.14 | 0.94 | 0.30 |
| bid move after 1m (R) | -1.82 | -0.29 | 1.24 | -0.31 |
| bid move after 3m (R) | -2.68 | -0.33 | 1.92 | -0.31 |
| bid move after 5m (R) | -2.93 | -0.36 | 2.18 | -0.22 |
| bid move after 10m (R) | -4.05 | -0.66 | 3.23 | -0.39 |
| bid move after 15m (R) | -4.87 | -0.89 | 3.35 | -0.46 |

Reached +0.5R before -0.5R: 36.2% of 116 trades that reached either. Stops 79: 8 had first been +1R or better, 48 stopped within 60 s; near-target reversals (MFE >= 80% of target, no target exit): 4.

## Breakdowns by entry-time-known features

### session

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| premarket | 103 | 28.2% | -0.241 | -1.037 | 0.69 | [-0.50, +0.02] |  |
| afterhours | 13 | 38.5% | 0.254 | -0.804 | 1.46 | [-0.54, +1.08] | *inconclusive* |

### hour_et

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 4 | 32 | 34.4% | -0.052 | -0.959 | 0.93 | [-0.54, +0.44] |  |
| 5 | 17 | 41.2% | 0.221 | -1.018 | 1.33 | [-0.55, +1.02] | *inconclusive* |
| 6 | 18 | 27.8% | -0.255 | -1.043 | 0.68 | [-0.80, +0.39] | *inconclusive* |
| 7 | 22 | 22.7% | -0.535 | -1.112 | 0.41 | [-1.04, +0.04] | *inconclusive* |
| 8 | 11 | 0.0% | -1.063 | -1.062 | 0.00 | [-1.12, -1.01] | *inconclusive* |
| 9 | 3 | 33.3% | 0.375 | -0.384 | 1.84 | [-0.95, +2.46] | *inconclusive* |
| 16 | 9 | 44.4% | 0.340 | -0.804 | 1.62 | [-0.66, +1.33] | *inconclusive* |
| 17 | 1 | 0.0% | -1.160 | -1.160 | 0.00 | — | *inconclusive* |
| 18 | 3 | 33.3% | 0.466 | -0.105 | 2.33 | [-0.95, +2.45] | *inconclusive* |

### price

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 2–5 | 71 | 29.6% | -0.133 | -1.027 | 0.82 | [-0.46, +0.21] |  |
| 5–10 | 32 | 28.1% | -0.417 | -1.053 | 0.50 | [-0.85, +0.05] |  |
| 10–20 | 13 | 30.8% | 0.095 | -1.014 | 1.15 | [-0.72, +0.98] | *inconclusive* |

### change_pct

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 5–10 | 2 | 100.0% | 2.157 | 2.157 | — | [+1.86, +2.45] | *inconclusive* |
| 10–20 | 20 | 25.0% | -0.305 | -1.063 | 0.64 | [-0.93, +0.40] | *inconclusive* |
| 20–50 | 59 | 28.8% | -0.232 | -1.045 | 0.70 | [-0.58, +0.12] |  |
| 50–100 | 17 | 29.4% | -0.200 | -1.037 | 0.73 | [-0.81, +0.49] | *inconclusive* |
| >= 100 | 18 | 27.8% | -0.149 | -0.981 | 0.80 | [-0.73, +0.54] | *inconclusive* |

### session_volume

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 100000–300000 | 10 | 30.0% | -0.427 | -1.209 | 0.58 | [-1.38, +0.64] | *inconclusive* |
| 300000–1e+06 | 27 | 37.0% | 0.067 | -0.898 | 1.11 | [-0.47, +0.63] | *inconclusive* |
| 1e+06–3e+06 | 30 | 20.0% | -0.381 | -1.032 | 0.54 | [-0.82, +0.09] |  |
| 3e+06–1e+07 | 29 | 31.0% | -0.176 | -1.070 | 0.78 | [-0.70, +0.37] | *inconclusive* |
| >= 1e+07 | 20 | 30.0% | -0.127 | -0.961 | 0.81 | [-0.67, +0.45] | *inconclusive* |

### volume_ratio

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 2–3 | 45 | 28.9% | -0.237 | -1.035 | 0.69 | [-0.63, +0.20] |  |
| 3–5 | 35 | 37.1% | 0.126 | -0.898 | 1.21 | [-0.32, +0.64] |  |
| 5–10 | 20 | 25.0% | -0.316 | -1.091 | 0.64 | [-0.87, +0.35] | *inconclusive* |
| 10–20 | 14 | 21.4% | -0.529 | -1.083 | 0.45 | [-1.21, +0.25] | *inconclusive* |
| >= 20 | 2 | 0.0% | -0.765 | -0.765 | 0.00 | [-1.04, -0.49] | *inconclusive* |

### breakout_strength_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–25 | 6 | 16.7% | -0.496 | -1.089 | 0.41 | [-1.14, +0.56] | *inconclusive* |
| 25–50 | 6 | 0.0% | -0.832 | -0.982 | 0.00 | [-1.04, -0.51] | *inconclusive* |
| 50–100 | 14 | 35.7% | -0.112 | -0.974 | 0.84 | [-0.79, +0.67] | *inconclusive* |
| 100–200 | 21 | 52.4% | 0.450 | 0.187 | 1.95 | [-0.19, +1.08] | *inconclusive* |
| 200–500 | 41 | 22.0% | -0.451 | -1.046 | 0.50 | [-0.84, -0.01] |  |
| >= 500 | 28 | 28.6% | -0.106 | -1.025 | 0.86 | [-0.65, +0.49] | *inconclusive* |

### signal_spread_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–10 | 2 | 0.0% | -0.623 | -0.623 | 0.00 | [-1.18, -0.06] | *inconclusive* |
| 10–20 | 21 | 33.3% | -0.228 | -1.104 | 0.70 | [-0.79, +0.37] | *inconclusive* |
| 20–35 | 42 | 28.6% | -0.150 | -1.023 | 0.80 | [-0.58, +0.30] |  |
| 35–50 | 51 | 29.4% | -0.180 | -1.012 | 0.76 | [-0.57, +0.21] |  |

### signal_quote_age_s

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–0.5 | 102 | 26.5% | -0.276 | -1.043 | 0.66 | [-0.55, +0.00] |  |
| 0.5–1 | 9 | 33.3% | 0.175 | -0.105 | 1.36 | [-0.64, +1.07] | *inconclusive* |
| 1–2 | 3 | 100.0% | 1.429 | 2.027 | — | [+0.21, +2.04] | *inconclusive* |
| 2–3 | 2 | 50.0% | 0.398 | 0.398 | 1.74 | [-1.07, +1.86] | *inconclusive* |

## Breakdowns by post-entry execution features (diagnostic only; not entry filters)

### seconds_to_fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0.5–1 | 99 | 29.3% | -0.212 | -1.030 | 0.72 | [-0.48, +0.06] |  |
| 1–2 | 7 | 28.6% | -0.066 | -1.027 | 0.90 | [-0.98, +0.92] | *inconclusive* |
| 2–5 | 6 | 33.3% | 0.088 | -0.881 | 1.13 | [-1.04, +1.29] | *inconclusive* |
| >= 5 | 4 | 25.0% | -0.141 | -1.083 | 0.83 | [-1.12, +1.78] | *inconclusive* |

### fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| full | 116 | 29.3% | -0.186 | -1.028 | 0.76 | [-0.43, +0.08] |  |

### entry_slippage_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| < -1 | 36 | 30.6% | -0.102 | -1.023 | 0.86 | [-0.56, +0.42] |  |
| 0–1 | 71 | 31.0% | -0.156 | -1.012 | 0.79 | [-0.47, +0.19] |  |
| 5–10 | 1 | 0.0% | -1.035 | -1.035 | 0.00 | — | *inconclusive* |
| 10–25 | 8 | 12.5% | -0.719 | -1.092 | 0.25 | [-1.13, +0.05] | *inconclusive* |

