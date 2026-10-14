# M2 historical replay viewer, plus Top 5 and Bull Flag research

Historical simulation only. Nothing here can place, change or route an order; there is no broker, paper or live execution code.

- **The viewer replays the baseline strategy by default:** `candle_close_confirmation` with the frozen 50 bps configuration from PR #4. It covers every dataset date that has PR #5 ledgers, both in-sample and the report-only out-of-sample block.
- **Top 5 and Bull Flag are exploratory research layers.** They stay hidden unless you switch them on, cover in-sample days only, and are hypotheses rather than validated edges. Validation needs fresh trading days after 2026-10-09; the code refuses to run the variants on the inspected out-of-sample block.

## Commands (Windows PowerShell)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[viewer]"      # once: Streamlit + Plotly for the viewer and chart export
.\.venv\Scripts\momentum-bot.exe m2-viewer                     # opens http://127.0.0.1:8501 (localhost only)
.\.venv\Scripts\momentum-bot.exe m2-chart --dataset reports\datasets\m2_sip_20260603_20261009 --date 2026-10-09 --session premarket
.\.venv\Scripts\momentum-bot.exe m2-research --dataset reports\datasets\m2_sip_20260603_20261009   # optional research layers
```

- **`m2-viewer`** needs only the outputs of `m2-backtest` and `m2-diagnostics`. It reads local files only. Changing the date, session, stock or a filter never reruns a backtest. Each session's 1-minute bars load from the SIP cache when first opened, and the last 12 sessions stay in memory.
- **`m2-chart`** writes one standalone HTML file per session to `charts/<date>_<session>_<strategy>.html` in the dataset folder (git-ignored). Plotly is inlined, so no network is needed. The viewer's export button does the same.
- **`m2-research`** builds the optional research layers:
  - It rebuilds Top 5 rankings, Bull Flag candidates and signal sets from the cached SIP bars (about 2.5 minutes, no API calls).
  - It backtests the three strategies with the frozen `base_cap50` model and runs the PR #5 diagnostics on the two variants.
  - The baseline is rerun from the quote cache only, and the run fails unless it reproduces the PR #4 ledgers byte for byte.
  - Variant diagnostics record their provenance (dataset, signal and ledger hashes, configuration) under `provenance_variant`.
  - The dataset needs `references.csv.gz`. A cache-only `m1-dataset` rebuild writes it with 0 API requests.

## Viewer

**Top of every page:**
- A red **HISTORICAL REPLAY — NOT LIVE** banner.
- The dataset's start and end dates, plus the in-sample, embargo and out-of-sample ranges. Out-of-sample dates are marked report-only.
- One shared row of controls: **trading date**, **session** and **stock**. Every tab follows it. The date defaults to the latest historical trading date with ledgers (2026-10-09), never today. Picking a row in the signals or trades table moves the shared selection to that stock.
- A daily summary for the selected date: signals, entries, completed trades, incomplete exits, simulated net P&L, and the unrealized mark.
  - Net P&L covers completed exits only. Incomplete exits are never added to it, and their unrealized mark is shown separately ("unknown" if no bid existed).

**Tabs:**
- **Scanner replay:**
  - Warnings for missing or incomplete data: no cached quotes, no quote at signal time, incomplete exits, and sparse bars.
  - Every signal in the session with the fields known at its signal time: trigger bar, time the signal became known, trigger price, change versus reference, session volume, volume ratio, signal-time spread, quote age and quote state. Each signal also shows its simulated outcome (skipped, rejected, unfilled, partial, completed or incomplete exit) and reason code, and can be filtered by stock and outcome.
  - The scanner candidates: the first completed bar at which each stock met the scan rules.
- **Chart:**
  - 1-minute SIP candles and volume. Minutes without trades stay empty gaps and are never filled in.
  - Markers for scanner candidates, breakout signals with their outcome and reason, simulated entry and exit fills, and stop and target levels per trade. Incomplete exits are marked as such.
  - Every tooltip gives exact ET times (milliseconds for fills) and prices.
  - The title restates the timing rule: a signal exists only after its trigger candle closes, and the simulated order arrives after that close plus latency.
  - Views: full session, or 15 minutes before to 20 minutes after a chosen event.
- **Trades:** the PR #5 trade ledger for the date, with entry and exit times and prices, R, net P&L of completed trades, unsold shares and their mark, MFE/MAE and spread cost. Selecting a trade opens it on the Chart tab, and each trade on the selected stock has a decision trace.
- **Overview:**
  - The baseline backtest results for both samples, from `backtest_summary_*.json`.
  - The diagnostics provenance (generating commit and the backtest run it explains), and the path to the PR #5 diagnostics dashboard. The viewer does not duplicate that dashboard.

**Research layers (sidebar switch, off by default; in-sample only):**
- **Strategies:** a choice of Original, Top 5 HOS, or Top 5 + Bull Flag.
- **Top 5 rank:** a rank strip, enter and exit markers, and a snapshot table. The ranking is within the cached sub-$20 universe, not the market-wide top-gainers list, and every label says so.
- **Bull Flag:** flagpole and flag regions, plus breakout markers.
- **Comparison:** the in-sample comparison of the three strategies.

All times are US Eastern (ET) and are labelled as such. Everything the viewer shows is derived from licensed market data and stays on your machine: do not publish the viewer, exported charts or ledgers.

## Research: strategies compared (same in-sample sessions, same execution and risk settings)

| strategy | signals passed to the unchanged backtester |
|---|---|
| Original HOS Breakout | The PR #4 baseline: candidate-gated SIP completed-bar session-high breakouts. |
| Top 5 (cached universe) HOS Breakout | The same breakouts, kept only when the symbol is in the Top 5 snapshot of the trigger bar. |
| Top 5 (cached universe) + Bull Flag Breakout | Qualified Bull Flag breakouts of a symbol in the Top 5 at the breakout bar that also pass the scanner gate (price $1–$20, change ≥ 10% premarket / 5% after hours, session volume ≥ 100k). |

Unchanged for all three: 3% stop, 2R target, 15-minute time exit, entry cutoff and flatten times, 0.5 s latency, 10 s entry timeout, 50 bps spread cap, $15 risk per trade, one position at a time, and the shared daily limits (5 entries, $45 loss, 3-loss pause). A position is never closed because its symbol leaves the Top 5; exits are only the existing stop, target, time and session-end rules.

## Research: point-in-time Top 5 (cached sub-$20 universe)

- **Snapshot timing:** a snapshot is taken after every 1-minute bar of the session. The snapshot for the bar starting at t uses bars that started at or before t, and is available at t + 1 minute, the same moment a signal on that bar becomes known.
- **Price:** a symbol's price is its last completed-bar close.
- **Change:** measured against the reference close the dataset already uses (`references.csv.gz`). That is the previous official close for premarket and the same day's official close after hours, split-adjusted on ex-dates.
- **Who is ranked:** the scanner's own floor applies. The price must be in $1–$20 and cumulative session volume at least 100k shares, with the after-hours closing-auction bar counted as zero volume.
- **Ties:** broken by symbol.
- **Change events:** `enter`, `exit` (reason `displaced` or `left_price_band`) and `rank_change`.
- **Limitation, reported in every comparison:** the dataset fetched bars only for symbols whose reference close could reach the scan band (≤ about $18.2 premarket, $19.0 after hours). The ranking is therefore the Top 5 of that sub-$20 universe, not the market-wide top-gainers list. Survivorship limits are as in the dataset report.

## Research: Bull Flag detector (initial hypothesis, not tuned)

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

Each candidate logs pole and flag start/end, pole base and top, flag high, low and resistance, pullback share, volumes, breakout time and price, every rule's pass/fail, and `reason` (`qualified`, `failed_<first failed rule>` or `insufficient_history`). Parameters live in `research.FlagParams`.

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
| `charts/*.html` | exported annotated charts | no |
| `research_comparison_in_sample.{json,md}` | aggregate comparison, Top 5 coverage and Bull Flag rule counts | yes |
| `diagnostics_in_sample_<variant>_base_cap50.{json,md}` | PR #5 aggregate diagnostics per variant | yes |
