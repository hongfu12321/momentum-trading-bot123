# M2 research: point-in-time Top 5 (cached sub-$20 universe)

Historical simulation only. Nothing here can place, change or route an order. This is an exploratory hypothesis on in-sample days only, not a validated edge; the code refuses to run it on the inspected out-of-sample block. Validation needs fresh trading days after 2026-10-09.

"Top 5" always means **Top 5 within the dataset's cached sub-$20 universe**, never the market-wide top-gainers list.

## Command (Windows PowerShell)

```powershell
.\.venv\Scripts\momentum-bot.exe m2-research --dataset reports\datasets\m2_sip_20260603_20261009
```

- It rebuilds the Top 5 rankings and signal sets from the cached SIP bars (no API calls).
- It is cache-only by default: a variant signal whose SIP quotes are not in `cache/backtest_quotes` stops the run with an explicit error instead of downloading them. `--fetch-missing-quotes` allows the download (Alpaca keys required).
- It backtests both strategies with the frozen `base_cap50` model and runs the PR #5 diagnostics on the variant.
- The baseline is rerun from the quote cache only, and the run fails unless it reproduces the PR #4 ledgers byte for byte, so baseline results cannot change.
- Variant diagnostics record their provenance (dataset, signal and ledger hashes, configuration) under `provenance_variant`.
- The dataset needs `references.csv.gz`. Datasets built before it existed (including the 2026-10-14 Google Drive snapshot of M2) lack it. It is recovered offline by rebuilding the dataset tables from `inputs/` and `cache/` with every network call refused, in a scratch folder: all other rebuilt tables must match the originals exactly, and only `references.csv.gz` is copied back, so the frozen manifest and tables are not rewritten.

## Strategies compared (same in-sample sessions, same execution and risk settings)

| strategy | signals passed to the unchanged backtester |
|---|---|
| Original HOS Breakout | The PR #4 baseline: candidate-gated SIP completed-bar session-high breakouts. |
| Top 5 (cached universe) HOS Breakout | The same breakouts, kept only when the symbol is in the Top 5 snapshot of the trigger bar. |

Unchanged for both: 3% stop, 2R target, 15-minute time exit, entry cutoff and flatten times, 0.5 s latency, 10 s entry timeout, 50 bps spread cap, $15 risk per trade, one position at a time, and the shared daily limits (5 entries, $45 loss, 3-loss pause). A position is never closed because its symbol leaves the Top 5; exits are only the existing stop, target, time and session-end rules.

## Point-in-time ranking

- **Snapshot timing:** a snapshot is taken after every 1-minute bar of the session. The snapshot for the bar starting at t uses bars that started at or before t, and is available at t + 1 minute, the same moment a signal on that bar becomes known.
- **Price:** a symbol's price is its last completed-bar close.
- **Freshness (no forward fill):** missing SIP bars are never filled. A minute without a bar means no trade was reported, so the last close is kept only while it is at most **5 minutes** old (`RankParams.max_staleness_minutes`). After that the symbol is not ranked (exit reason `stale`) until it trades again. Each snapshot row records `minutes_since_trade` and `stale_excluded`, and each session records `stale_exclusion_symbol_minutes`. The 5-minute limit is a fixed policy set before looking at results, not a tuned value; a symbol whose breakout triggers a signal always has a bar on its trigger minute, so the limit only decides which competitors can hold it out of the Top 5.
- **Change:** measured against the reference close the dataset already uses (`references.csv.gz`). That is the previous official close for premarket and the same day's official close after hours, split-adjusted on ex-dates.
- **Who is ranked:** the scanner's own floor applies. The price must be in $1–$20 and cumulative session volume at least 100k shares, with the after-hours closing-auction bar counted as zero volume.
- **Ties:** broken by symbol.
- **Change events:** `enter`, `exit` (reason `stale`, `left_price_band` or `displaced`) and `rank_change`.
- **Universe label:** every snapshot row, coverage row and comparison records `universe = cached_eligible_sub20`.
- **Limitation, reported in every comparison:** the dataset fetched bars only for symbols whose reference close could reach the scan band (≤ about $18.2 premarket, $19.0 after hours). The ranking is therefore the Top 5 of that sub-$20 universe, not the market-wide top-gainers list. Survivorship limits are as in the dataset report.

## Assumptions and limitations

- **Availability of historical bars:** a bar is treated as known at its end (start + 1 minute). Historical bars cannot show real-time publication delays or late corrections, so live availability may be later.
- **Reference closes:** taken from the SIP daily bar close, which the dataset report labels the regular-session official close. The after-hours reference is the same day's close, known only after the 16:00 closing auction; the closing-auction bar's volume is excluded.
- **Universe membership:** the eligible set is fixed per session from the reference close and the dataset's symbol directory and corporate-action snapshots. Symbols are not added or removed intra-session. The directory snapshot postdates the sample, so symbols delisted without a recorded corporate action may be missing (survivorship bias).
- **Input snapshots:** in the Google Drive M2 snapshot, `inputs/` holds directory, corporate-action and asset files downloaded after the ones whose hashes `manifest.json` records. An offline rebuild from them still reproduces every committed table exactly, so the references derived from them are consistent with the frozen dataset, but the manifest's input hashes no longer describe the files on disk.
- **Out of sample:** never built, backtested or inspected by this command.

## Outputs

| file (under the dataset folder) | contents | committed? |
|---|---|---|
| `references.csv.gz` | reference close per eligible symbol and session | no (per symbol) |
| `research/in_sample/top5_snapshots.csv.gz` | every snapshot: rank, symbol, change, price, session volume, minutes since last trade, stale exclusions, universe | no |
| `research/in_sample/top5_changes.csv.gz` | enter / exit / rank_change events | no |
| `research/in_sample/top5_coverage.csv` | per session: eligible symbols, symbols with bars, minutes without any bar, minutes with fewer than 5 ranked, stale exclusions, or `missing` | no |
| `research/in_sample/signals_<strategy>.csv` | signals in the `breakout_matches.csv` schema | no |
| `research/in_sample/filtered.csv.gz`, `decisions.csv.gz` | filter-stage removals and every backtester outcome, in time order | no |
| `backtest/in_sample/<variant>/base_cap50/` | `trades.csv`, `attempts.csv` | no |
| `diagnostics/in_sample/<variant>/base_cap50/` | PR #5 ledgers, failure cases and dashboard for each variant | no |
| `research_comparison_in_sample.{json,md}` | aggregate comparison and Top 5 coverage | yes |
| `diagnostics_in_sample_<variant>_base_cap50.{json,md}` | PR #5 aggregate diagnostics per variant | yes |
