# M2 research: point-in-time Top 5 (cached sub-$20 universe) and Bull Flag

Historical simulation only. Nothing here can place, change or route an order. These are exploratory hypotheses on in-sample days only, not validated edges; the code refuses to run it on the inspected out-of-sample block. Validation needs fresh trading days after 2026-10-09.

"Top 5" always means **Top 5 within the dataset's cached sub-$20 universe**, never the market-wide top-gainers list.

## Command (Windows PowerShell)

```powershell
.\.venv\Scripts\momentum-bot.exe m2-research --dataset reports\datasets\m2_sip_20260603_20261009
```

- It rebuilds the Top 5 rankings, Bull Flag candidates and signal sets from the cached SIP bars (no API calls).
- It backtests the three strategies with the frozen `base_cap50` model and runs the PR #5 diagnostics on the two variants.
- The baseline is rerun from the quote cache only, and the run fails unless it reproduces the PR #4 ledgers byte for byte, so baseline results cannot change.
- Variant diagnostics record their provenance (dataset, signal and ledger hashes, configuration) under `provenance_variant`.
- The dataset needs `references.csv.gz`. A cache-only `m1-dataset` rebuild writes it with 0 API requests.

## Strategies compared (same in-sample sessions, same execution and risk settings)

| strategy | signals passed to the unchanged backtester |
|---|---|
| Original HOS Breakout | The PR #4 baseline: candidate-gated SIP completed-bar session-high breakouts. |
| Top 5 (cached universe) HOS Breakout | The same breakouts, kept only when the symbol is in the Top 5 snapshot of the trigger bar. |
| Top 5 (cached universe) + Bull Flag Breakout | Qualified Bull Flag breakouts of a symbol in the Top 5 at the breakout bar that also pass the scanner gate (price $1–$20, change ≥ 10% premarket / 5% after hours, session volume ≥ 100k). |

Unchanged for all three: 3% stop, 2R target, 15-minute time exit, entry cutoff and flatten times, 0.5 s latency, 10 s entry timeout, 50 bps spread cap, $15 risk per trade, one position at a time, and the shared daily limits (5 entries, $45 loss, 3-loss pause). A position is never closed because its symbol leaves the Top 5; exits are only the existing stop, target, time and session-end rules.

## Point-in-time ranking

- **Snapshot timing:** a snapshot is taken after every 1-minute bar of the session. The snapshot for the bar starting at t uses bars that started at or before t, and is available at t + 1 minute, the same moment a signal on that bar becomes known.
- **Price:** a symbol's price is its last completed-bar close.
- **Change:** measured against the reference close the dataset already uses (`references.csv.gz`). That is the previous official close for premarket and the same day's official close after hours, split-adjusted on ex-dates.
- **Who is ranked:** the scanner's own floor applies. The price must be in $1–$20 and cumulative session volume at least 100k shares, with the after-hours closing-auction bar counted as zero volume.
- **Ties:** broken by symbol.
- **Change events:** `enter`, `exit` (reason `displaced` or `left_price_band`) and `rank_change`.
- **Limitation, reported in every comparison:** the dataset fetched bars only for symbols whose reference close could reach the scan band (≤ about $18.2 premarket, $19.0 after hours). The ranking is therefore the Top 5 of that sub-$20 universe, not the market-wide top-gainers list. Survivorship limits are as in the dataset report.

## Bull Flag detector (initial hypothesis, not tuned)

The detector runs at every bar whose close exceeds the previous bar's high (a breakout attempt) and reads only that bar and earlier ones. It tries every consolidation length of 2–8 bars and every flagpole length of 3–10 bars before the consolidation. It keeps the pair that passes the most rules; ties go to the shorter consolidation, then the shorter pole.

| rule | definition |
|---|---|
| `complete_bars` | Pole, flag and breakout bar are consecutive minutes: no missing candle inside the pattern. |
| `flagpole` | Last pole bar's high / first pole bar's low − 1 ≥ 5%, and the last pole bar holds the pole's highest high. |
| `consolidation` | The flag's highest high is not above the pole top. |
| `pullback` | (pole top − flag low) / (pole top − pole base) ≤ 50%. |
| `volume_contraction` | Flag average volume < pole average volume. |
| `breakout_close` | The breakout bar closes above the flag resistance (the flag's highest high). |
| `breakout_volume` | Breakout bar volume ≥ 1.5 × flag average volume. |

Each candidate logs pole and flag start/end, pole base and top, flag high, low and resistance, pullback share, volumes, breakout time and price, every rule's pass/fail, and `reason` (`qualified`, `failed_<first failed rule>` or `insufficient_history`). Parameters live in `bullflag.FlagParams`; the detector is in `bullflag.py`, separate from the baseline strategy and from `research.py`.

## Outputs

| file (under the dataset folder) | contents | committed? |
|---|---|---|
| `references.csv.gz` | reference close per eligible symbol and session | no (per symbol) |
| `research/in_sample/top5_snapshots.csv.gz` | every snapshot: rank, symbol, change, price, session volume, minutes since last trade | no |
| `research/in_sample/top5_changes.csv.gz` | enter / exit / rank_change events | no |
| `research/in_sample/top5_coverage.csv` | per session: eligible symbols, symbols with bars, minutes without any bar, minutes with fewer than 5 ranked, or `missing` | no |
| `research/in_sample/bullflag_candidates.csv.gz` | every evaluated breakout attempt of a Top 5 member, with all rule results | no |
| `research/in_sample/signals_<strategy>.csv` | signals in the `breakout_matches.csv` schema | no |
| `research/in_sample/filtered.csv.gz`, `decisions.csv.gz` | filter-stage removals and every backtester outcome, in time order | no |
| `backtest/in_sample/<variant>/base_cap50/` | `trades.csv`, `attempts.csv` | no |
| `diagnostics/in_sample/<variant>/base_cap50/` | PR #5 ledgers, failure cases and dashboard for each variant | no |
| `research_comparison_in_sample.{json,md}` | aggregate comparison, Top 5 coverage and Bull Flag rule counts | yes |
| `diagnostics_in_sample_<variant>_base_cap50.{json,md}` | PR #5 aggregate diagnostics per variant | yes |
