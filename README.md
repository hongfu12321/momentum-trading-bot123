# Momentum Trading Research & Paper Bot

Research-first small-cap momentum trading system. Python 3.12, Alpaca historical market data and **paper trading only**.

## Current milestone: M1 — Historical market-data feasibility

Verify historical SIP access on Alpaca Basic, compare consolidated SIP and IEX one-minute bars in premarket (04:00–09:30 ET) and after-hours (16:00–20:00 ET), and produce reproducible coverage and candidate-discovery reports.

**Start here:** [Full technical design](docs/DESIGN.md) and [Claude Code guidance](CLAUDE.md).

## Development rules

- M1 is read-only market-data research: **no order placement**.
- Never use live brokerage credentials or endpoints; later milestones are Alpaca paper only.
- Preserve timestamps, data feed, coverage gaps, API failure evidence, and reproducibility.
- Do not claim strategy profitability from IEX-only observations or idealized paper fills.

## M1 setup

Requires Python 3.12. Only runtime dependency: `tzdata` (IANA time zones on Windows).

### Windows PowerShell

```powershell
python --version                    # should report Python 3.12.x
python -m venv .venv
.venv\Scripts\Activate.ps1
python -m pip install -e ".[dev]"
Copy-Item .env.example .env         # then fill in Alpaca keys
```

The VS Code workspace terminal prepends the Python 3.12 install directories
to PATH. Open a **new integrated terminal** after installing Python. In an
external PowerShell window, close and reopen it to pick up the user PATH. To
fix an already-open PowerShell window immediately, run:

```powershell
$python312 = Join-Path $env:LOCALAPPDATA 'Programs\Python\Python312'
$env:Path = "$python312;$python312\Scripts;$env:Path"
python --version
```

For external terminals, ensure `$env:LOCALAPPDATA\Programs\Python\Python312`
and its `Scripts` subdirectory are in your user PATH.

### macOS and Linux

```bash
python3.12 -m venv .venv
source .venv/bin/activate
pip install -e ".[dev]"
cp .env.example .env               # then fill in Alpaca keys
```

Keys can also be set as environment variables `APCA_API_KEY_ID` / `APCA_API_SECRET_KEY`; real environment variables take precedence over `.env`.

## M1 command

```bash
momentum-bot m1-validate --symbols SOUN,MARA,PLUG,FFIE,NKLA --start 2024-03-04 --end 2024-03-08
# or: python -m momentum_bot.cli m1-validate --symbols-file symbols.txt --start ... --end ...
```

For each trading day (plus the prior trading day, for reference closes) it requests 04:00–20:00 ET 1-minute bars with `feed=sip` and then `feed=iex`, `adjustment=raw`, from `data.alpaca.markets` only. The end date must be older than the SIP delay window (default 16 minutes). Output goes to `reports/runs/m1_<UTC timestamp>/`:

| File | Contents |
|---|---|
| `report.md` | Status, failures, coverage/volume tables, candidate and breakout recall, limitations |
| `manifest.json` | Run provenance: dates, symbols, feeds, adjustment, code SHA, scan parameters, failures, summary |
| `fetch_log.csv` | Every request: feed, date, window, status, HTTP code, error |
| `bars.csv` | Completed in-session bars with UTC and ET timestamps, session and feed |
| `session_comparison.csv` | Per symbol-session coverage, volume, session high/low and matched-bar OHLC differences |
| `missing_intervals.csv` | Contiguous minutes with no bar, per feed |
| `candidates.csv`, `candidate_matches.csv` | Scanner candidates per feed and their SIP/IEX matching |
| `breakouts.csv`, `breakout_matches.csv` | Tentative breakout bars per feed and their matching |

Exit codes: `0` complete, `1` partial (some requests failed), `2` usage/credential error, `3` entitlement- or auth-blocked. If SIP is refused, the run still writes an explicit `sip_entitlement_blocked` report; IEX is never substituted for SIP.

## Dataset command (broad universe, multi-day)

```bash
momentum-bot m1-dataset --start 2026-06-03 --end 2026-10-09 --out-dir reports/datasets/m2_sip_20260603_20261009
```

Builds an approximate point-in-time universe: a Nasdaq Trader listing snapshot, plus symbols delisted or renamed since the start date (Alpaca corporate actions), plus inactive and OTC symbols from a **read-only** `GET /v2/assets` on Alpaca's **paper** host (skip with `--no-alpaca-assets`). Then for every trading day it fetches premarket and after-hours 1m SIP and IEX bars for every symbol whose prior official close lets it qualify, and scans both feeds against the same SIP reference close. Trading days are split chronologically into in-sample, a one-day embargo and the most recent third as out-of-sample (`--oos-fraction`, `--embargo-days`).

Snapshots are saved under `inputs/` and raw bars under `cache/`; rerunning on the same folder reuses them, so results are reproducible and resumable. Findings: `reports/m1_feasibility.md` and `reports/m2_data_readiness.md`.

## SIP quote probe (M2 prerequisite)

```bash
momentum-bot m2-quote-probe --dataset reports/datasets/m2_sip_20260603_20261009 --sample 60 --minutes 30
```

Samples scanner candidates deterministically, fetches SIP NBBO quotes for the window starting when each trigger bar completes, and reports availability, fresh-quote coverage (quotes at most 3 s old), executable spreads, locked/crossed quotes as diagnostics, gaps and the cost of fetching quotes for every candidate. Raw quotes stay in the local cache.

## Quote-aware backtest (simulation only)

```bash
momentum-bot m2-backtest --dataset reports/datasets/m2_sip_20260603_20261009 --sample in_sample
```

Simulates the candidate-gated SIP breakout strategy (`candle_close_confirmation`: entries only after the trigger bar closes; intrabar resistance-cross entries are a separate future strategy) against historical SIP quotes in three scenarios (`idealized` reference, quote-aware `base`, `stress`). Orders reach the market only after the trigger bar completes plus latency. They fill only on fresh, executable quotes within the spread cap and displayed size; the same displayed shares are never taken twice, and the unfilled remainder expires after the entry timeout. Exits that do not fully fill within 2 minutes are reported as incomplete, with unsold shares marked separately from realized P&L. Fees and risk limits follow `docs/DESIGN.md`. The aggregate result goes to `backtest_summary_<sample>.json`; per-trade rows stay local under `backtest/`. Out-of-sample runs require `--confirm-out-of-sample` and should be run once, with frozen settings. Results: `reports/m2_backtest.md`. Spread-cap comparison on in-sample data: `--spread-caps 50,100,150,200`; the frozen out-of-sample run: `--sample out_of_sample --spread-caps 50 --confirm-out-of-sample`.

## Trade diagnostics (why trades win or lose)

```bash
momentum-bot m2-diagnostics --dataset reports/datasets/m2_sip_20260603_20261009 --sample in_sample --scenario base_cap50
```

Replays only the cached backtest quotes and makes no network requests. It writes reason-coded signal and trade ledgers, MFE/MAE, post-entry moves, slippage and spread cost, and bucketed breakdowns with small-sample flags. Entry-time features are kept separate from post-entry diagnostics. The aggregate report and JSON are committable. Ledgers, failure cases and the standalone `dashboard.html` stay local. Out-of-sample needs `--confirm-out-of-sample` and is for reporting only. Data dictionary: `docs/m2_diagnostics.md`. Findings: `reports/m2_diagnostics.md`.

## Historical replay viewer (localhost)

```powershell
.\.venv\Scripts\python.exe -m pip install -e ".[viewer]"
.\.venv\Scripts\momentum-bot.exe m2-viewer
```

`m2-viewer` serves a Streamlit app on 127.0.0.1:8501 that replays the baseline backtest day by day from local files: scanner signals with their outcomes and reason codes, annotated 1-minute SIP candlestick charts with entry, exit, stop and target markers, trades and a daily P&L summary. It shows a **Historical Replay — Not Live** banner, makes no network requests and never reruns a backtest. Before anything is shown, each sample's ledgers are checked against the provenance `m2-diagnostics` recorded, and a mismatched sample is refused with the reason. All times are US Eastern. `m2-chart --date YYYY-MM-DD --session premarket` exports a session's charts to standalone HTML. `m2-viewer-check` audits every total and chart marker the viewer would show against the backtest ledgers, offline. Details, including the canonical CRLF/LF hashing policy: `docs/m2_replay_viewer.md`.

## Licensed data stays local

Raw bars, quotes, per-symbol tables and input snapshots are Alpaca or third-party data and are git-ignored. Only aggregate outputs are committed: `report.md`, `manifest.json` (including the sha256 of every input snapshot), count-only `eligibility.csv`, `quote_probe_summary.json`, `backtest_summary_*.json` and `diagnostics_*.{json,md}`. The viewer and exported charts stay local.

## Safety

No code path places, replaces or cancels orders; the backtest is an offline simulation with no broker client. Market data comes from `data.alpaca.markets`. The only trading-host call is the read-only `GET /v2/assets` on `paper-api.alpaca.markets`, which refuses live-looking keys. A test enforces both.

## Tests

```bash
pytest            # offline, deterministic, no credentials or network needed
```

## For Claude Code

Clone this repository and read `CLAUDE.md` and `docs/DESIGN.md` before implementing M1. Do not implement M2–M4 unless explicitly requested.
