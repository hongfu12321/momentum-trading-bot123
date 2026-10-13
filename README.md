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

```bash
python3.12 -m venv .venv
source .venv/bin/activate          # Windows: .venv\Scripts\activate
pip install -e ".[dev]"
cp .env.example .env               # then fill in Alpaca keys (paper-account keys work for market data)
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

## Tests

```bash
pytest            # offline, deterministic, no credentials or network needed
```

## For Claude Code

Clone this repository and read `CLAUDE.md` and `docs/DESIGN.md` before implementing M1. Do not implement M2–M4 unless explicitly requested.
