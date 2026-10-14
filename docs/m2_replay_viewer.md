# M2 historical replay viewer

Historical simulation only. Nothing here can place, change or route an order; there is no broker, paper or live execution code, and the viewer makes no network requests.

The viewer replays the **baseline strategy only**: `candle_close_confirmation` (a signal exists only after its 1-minute trigger candle closes) with the frozen `base_cap50` configuration from PR #4. It reads the outputs of `m2-backtest` and `m2-diagnostics`. It covers every dataset date whose ledgers pass the provenance check, in-sample and the report-only out-of-sample block.

## Commands (Windows PowerShell)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[viewer]"      # once: Streamlit + Plotly for the viewer and chart export
.\.venv\Scripts\momentum-bot.exe m2-viewer                     # opens http://127.0.0.1:8501 (localhost only)
.\.venv\Scripts\momentum-bot.exe m2-chart --dataset reports\datasets\m2_sip_20260603_20261009 --date 2026-10-09 --session premarket
```

- **`m2-viewer`** needs only the outputs of `m2-backtest` and `m2-diagnostics` (run diagnostics for each sample you want to replay). Changing the date, session, stock or a filter never reruns a backtest. Each session's 1-minute bars load from the SIP cache when first opened, and the last 12 sessions stay in memory.
- **`m2-chart`** writes one standalone HTML file per session to `charts/<date>_<session>_hos.html` in the dataset folder (git-ignored). Plotly is inlined, so no network is needed. The viewer's export button does the same. It refuses dates without validated ledgers.

## Provenance check: nothing stale or mismatched is shown

Before showing a sample, the viewer checks its PR #5 ledgers against the provenance record `m2-diagnostics` wrote in `diagnostics_<sample>_base_cap50.json`:

1. `manifest.json`, `breakout_matches.csv`, `backtest_summary_<sample>.json` and the PR #4 `trades.csv` / `attempts.csv` still have the recorded hashes.
2. The ledgers have the current schema, including the corrected exit fields (`exit_complete`, `exit_qty`, `remaining_qty`, `realized_usd`, `marked_usd`), and the recorded row counts.
3. Every ledger row belongs to the sample, and its date lies in the manifest's range for it.
4. The ledgers reconcile with the backtest summary: entries, completed trades, incomplete exits and completed-trade net P&L.

A sample that fails is not shown, and the page lists each problem with the command to fix it. A sample without ledgers is reported as absent. The checks rerun whenever any of those files changes on disk.

## Canonical hashing policy (Windows CRLF vs LF)

Provenance hashes use `diagnostics.HASH_POLICY = "sha256-text-lf-v1"`: text files (`.csv`, `.json`, `.md`, `.txt`) are hashed after converting CRLF line endings to LF; every other file (for example `.gz`) is hashed as raw bytes. The same content therefore hashes the same whether it was written on Windows, checked out with `core.autocrlf`, or produced on macOS/Linux. New records carry `"hash_policy"`.

Records written before the policy have no `hash_policy` field and may hold the raw hash of a CRLF file (the committed `diagnostics_*_base_cap50.json` were written on Windows). For those, a match against the CRLF form of the same text is accepted and shown as a note, never silently. `.gitattributes` also checks text files out with LF on every OS.

## Viewer

**Top of every page:**
- A red **HISTORICAL REPLAY — NOT LIVE** banner.
- The dataset's start and end dates, plus the in-sample, embargo and out-of-sample ranges. Out-of-sample dates are marked report-only.
- One shared row of controls: **trading date**, **session** and **stock**. Every tab follows it. The date defaults to the latest historical trading date with validated ledgers, never today. Picking a row in the signals or trades table moves the shared selection to that stock.
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

## Limitations

- Fills, P&L and quotes shown are the PR #4 simulation against historical SIP NBBO; they are not evidence of live or paper fill quality.
- The PR #5 trade ledger does not store the exit-window end, so the unsold-remainder marker is placed at trigger + 2 minutes (capped at the session close), the same rule the backtester uses.
- The viewer trusts the ledgers' content once their provenance and totals check out; it does not re-simulate trades.
