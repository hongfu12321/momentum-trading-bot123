# Trade diagnostics: out_of_sample, base_cap50 (generated)

Signals 1,488 · trades 117 · code `ca2b4a7` · no orders placed. Buckets with fewer than 30 trades are marked *inconclusive*. Patterns here are hypotheses, not validated edges.

## Overall

| n | win rate | avg R | median R | profit factor | 95% CI avg R |
|---:|---:|---:|---:|---:|---|
| 117 | 29.1% | -0.183 | -1.030 | 0.76 | [-0.43, +0.08] |

Realized P&L $-320.65; marked (incomplete exits) $-0.02; gross $-316.58; fees $4.10; half-spread cost paid $249.63.

## Signal outcomes and reason codes

| outcome | reason | n |
|---|---|---:|
| skipped | daily_loss_limit | 433 |
| skipped | daily_entry_limit | 418 |
| rejected | at_signal_spread_above_cap | 274 |
| skipped | loss_streak_pause | 153 |
| skipped | position_open | 40 |
| rejected | at_signal_no_quote | 31 |
| rejected | at_signal_locked_quote | 8 |
| skipped | after_entry_cutoff | 8 |
| unfilled | timeout_spread_above_cap | 4 |
| unfilled | timeout_price_above_limit | 2 |

Outcome totals: completed 116, incomplete_exit 1, rejected 313, skipped 1052, unfilled 6.

Quote replay: 436 of 436 evaluated signals and 117 of 117 trades had cached quotes; missing data is left empty.

## Execution

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| seconds_to_fill | 0.50 | 0.50 | 1.67 | 0.89 |
| entry_slippage_bps | -44.64 | 0.00 | 0.00 | -15.44 |
| exit_slippage_bps | -73.80 | 0.00 | 63.97 | -7.19 |
| spread_cost_r | 0.07 | 0.12 | 0.23 | 0.14 |
| holding_seconds | 8.54 | 57.98 | 651.50 | 166.70 |
| signal_spread_bps_evaluated | 25.37 | 68.26 | 144.58 | 80.05 |
| signal_quote_age_s_evaluated | 0.01 | 0.11 | 0.68 | 0.27 |

Partial fills 0; incomplete exits 1; exit reasons {'stop': 79, 'target': 31, 'time': 7}.

## Trade lifecycle (post-entry diagnostics)

| metric | p10 | median | p90 | mean |
|---|---:|---:|---:|---:|
| mfe_r | -0.12 | 0.46 | 2.06 | 0.80 |
| mae_r | -1.12 | -1.02 | -0.34 | -0.87 |
| seconds_to_mfe | 0.02 | 9.60 | 277.26 | 85.86 |
| seconds_to_mae | 1.86 | 36.02 | 238.84 | 92.75 |
| stops_mfe_r | -0.14 | 0.15 | 0.93 | 0.28 |
| bid move after 1m (R) | -1.82 | -0.32 | 1.24 | -0.32 |
| bid move after 3m (R) | -2.68 | -0.33 | 1.92 | -0.30 |
| bid move after 5m (R) | -2.93 | -0.41 | 2.18 | -0.23 |
| bid move after 10m (R) | -4.05 | -0.66 | 3.23 | -0.40 |
| bid move after 15m (R) | -4.87 | -0.89 | 3.35 | -0.48 |

Reached +0.5R before -0.5R: 35.3% of 116 trades that reached either. Stops 79: 7 had first been +1R or better, 49 stopped within 60 s; near-target reversals (MFE >= 80% of target, no target exit): 3.

## Breakdowns by entry-time-known features

### session

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| premarket | 105 | 27.6% | -0.247 | -1.038 | 0.68 | [-0.51, +0.02] |  |
| afterhours | 12 | 41.7% | 0.369 | -0.454 | 1.73 | [-0.46, +1.28] | *inconclusive* |

### hour_et

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 4 | 32 | 34.4% | -0.059 | -0.959 | 0.92 | [-0.54, +0.43] |  |
| 5 | 17 | 41.2% | 0.227 | -1.018 | 1.34 | [-0.55, +1.04] | *inconclusive* |
| 6 | 19 | 26.3% | -0.241 | -1.045 | 0.68 | [-0.80, +0.40] | *inconclusive* |
| 7 | 23 | 21.7% | -0.558 | -1.104 | 0.39 | [-1.05, +0.00] | *inconclusive* |
| 8 | 11 | 0.0% | -1.063 | -1.062 | 0.00 | [-1.12, -1.01] | *inconclusive* |
| 9 | 3 | 33.3% | 0.416 | -0.260 | 2.03 | [-0.95, +2.46] | *inconclusive* |
| 16 | 9 | 44.4% | 0.337 | -0.804 | 1.61 | [-0.66, +1.33] | *inconclusive* |
| 18 | 3 | 33.3% | 0.466 | -0.105 | 2.33 | [-0.95, +2.45] | *inconclusive* |

### price

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 2–5 | 71 | 29.6% | -0.134 | -1.037 | 0.82 | [-0.46, +0.21] |  |
| 5–10 | 32 | 28.1% | -0.413 | -1.042 | 0.50 | [-0.84, +0.05] |  |
| 10–20 | 14 | 28.6% | 0.088 | -0.753 | 1.15 | [-0.65, +0.90] | *inconclusive* |

### change_pct

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 5–10 | 2 | 100.0% | 2.157 | 2.157 | — | [+1.86, +2.45] | *inconclusive* |
| 10–20 | 20 | 25.0% | -0.249 | -0.976 | 0.69 | [-0.87, +0.46] | *inconclusive* |
| 20–50 | 59 | 28.8% | -0.231 | -1.045 | 0.70 | [-0.58, +0.12] |  |
| 50–100 | 18 | 27.8% | -0.253 | -1.054 | 0.66 | [-0.81, +0.37] | *inconclusive* |
| >= 100 | 18 | 27.8% | -0.144 | -0.981 | 0.80 | [-0.73, +0.55] | *inconclusive* |

### session_volume

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 100000–300000 | 10 | 30.0% | -0.311 | -1.164 | 0.65 | [-1.26, +0.71] | *inconclusive* |
| 300000–1e+06 | 27 | 37.0% | 0.064 | -0.898 | 1.10 | [-0.47, +0.62] | *inconclusive* |
| 1e+06–3e+06 | 30 | 20.0% | -0.380 | -1.041 | 0.54 | [-0.82, +0.09] |  |
| 3e+06–1e+07 | 29 | 31.0% | -0.176 | -1.070 | 0.78 | [-0.70, +0.37] | *inconclusive* |
| >= 1e+07 | 21 | 28.6% | -0.171 | -0.970 | 0.76 | [-0.68, +0.37] | *inconclusive* |

### volume_ratio

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 2–3 | 45 | 28.9% | -0.236 | -1.038 | 0.69 | [-0.63, +0.20] |  |
| 3–5 | 35 | 37.1% | 0.127 | -0.898 | 1.21 | [-0.32, +0.64] |  |
| 5–10 | 21 | 23.8% | -0.301 | -1.082 | 0.64 | [-0.86, +0.34] | *inconclusive* |
| 10–20 | 14 | 21.4% | -0.529 | -1.083 | 0.45 | [-1.21, +0.25] | *inconclusive* |
| >= 20 | 2 | 0.0% | -0.765 | -0.765 | 0.00 | [-1.04, -0.49] | *inconclusive* |

### breakout_strength_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–25 | 6 | 16.7% | -0.494 | -1.089 | 0.41 | [-1.14, +0.56] | *inconclusive* |
| 25–50 | 7 | 0.0% | -0.861 | -1.018 | 0.00 | [-1.04, -0.58] | *inconclusive* |
| 50–100 | 14 | 35.7% | -0.112 | -0.974 | 0.84 | [-0.79, +0.67] | *inconclusive* |
| 100–200 | 22 | 50.0% | 0.429 | 0.093 | 1.95 | [-0.16, +1.00] | *inconclusive* |
| 200–500 | 40 | 22.5% | -0.435 | -1.054 | 0.51 | [-0.84, -0.00] |  |
| >= 500 | 28 | 28.6% | -0.104 | -1.025 | 0.86 | [-0.65, +0.48] | *inconclusive* |

### signal_spread_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–10 | 3 | 0.0% | -0.416 | -0.062 | 0.00 | [-1.18, -0.00] | *inconclusive* |
| 10–20 | 21 | 33.3% | -0.222 | -1.045 | 0.70 | [-0.78, +0.38] | *inconclusive* |
| 20–35 | 42 | 28.6% | -0.156 | -1.027 | 0.80 | [-0.59, +0.29] |  |
| 35–50 | 51 | 29.4% | -0.177 | -1.012 | 0.77 | [-0.57, +0.22] |  |

### signal_quote_age_s

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0–0.5 | 103 | 26.2% | -0.273 | -1.045 | 0.66 | [-0.53, -0.01] |  |
| 0.5–1 | 9 | 33.3% | 0.175 | -0.105 | 1.36 | [-0.64, +1.07] | *inconclusive* |
| 1–2 | 3 | 100.0% | 1.429 | 2.027 | — | [+0.21, +2.04] | *inconclusive* |
| 2–3 | 2 | 50.0% | 0.398 | 0.398 | 1.74 | [-1.07, +1.86] | *inconclusive* |

## Breakdowns by post-entry execution features (diagnostic only; not entry filters)

### seconds_to_fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| 0.5–1 | 100 | 29.0% | -0.208 | -1.025 | 0.73 | [-0.48, +0.07] |  |
| 1–2 | 7 | 28.6% | -0.058 | -1.070 | 0.91 | [-0.97, +0.95] | *inconclusive* |
| 2–5 | 6 | 33.3% | 0.056 | -0.896 | 1.08 | [-1.04, +1.25] | *inconclusive* |
| >= 5 | 4 | 25.0% | -0.143 | -1.083 | 0.83 | [-1.13, +1.78] | *inconclusive* |

### fill

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| full | 117 | 29.1% | -0.183 | -1.030 | 0.76 | [-0.43, +0.08] |  |

### entry_slippage_bps

| bucket | n | win rate | avg R | median R | profit factor | 95% CI avg R | |
|---|---:|---:|---:|---:|---:|---|---|
| < -1 | 35 | 31.4% | -0.080 | -1.018 | 0.89 | [-0.56, +0.47] |  |
| 0–1 | 73 | 30.1% | -0.162 | -1.012 | 0.78 | [-0.48, +0.20] |  |
| 5–10 | 1 | 0.0% | -1.035 | -1.035 | 0.00 | — | *inconclusive* |
| 10–25 | 8 | 12.5% | -0.719 | -1.092 | 0.25 | [-1.13, +0.05] | *inconclusive* |

