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

## For Claude Code

Clone this repository and read `CLAUDE.md` and `docs/DESIGN.md` before implementing M1. Do not implement M2–M4 unless explicitly requested.
