# CLAUDE.md — Coding Agent Instructions

## Mission
Build a research-first US small-cap momentum system, with Alpaca PAPER execution only in later milestones. Read `docs/DESIGN.md` before changing architecture.

## Current task: M1 only
Implement historical Alpaca SIP vs IEX data feasibility and comparison. Test premarket 04:00–09:30 ET and after-hours 16:00–20:00 ET. Report entitlement errors explicitly; never silently replace SIP with IEX. Include deterministic offline fixture tests, a simple CLI, clear setup instructions, and reproducible CSV/JSON results.

## Hard rules
- M1 makes **no trading orders**, has no broker execution client and requires no OpenAI key.
- Never connect to live trading endpoints or add real-money trading capabilities.
- Use Python 3.12, typed code where practical, pytest and small, maintainable modules.
- Keep API keys in environment variables, never source control. Provide `.env.example` and `.gitignore`.
- Use America/New_York exchange session boundaries and retain UTC timestamps; account for DST, market holidays and shortened sessions.
- Use only completed bars. Record feed, symbol, start/end time, adjusted/unadjusted treatment, failures and missing intervals.
- Model provider limitations, survivorship bias and IEX-vs-SIP discrepancies honestly.
- Keep third-party dependencies few; isolate Alpaca behind a data-provider interface.
- Build a testable comparison of coverage, traded volume, highs/lows, scan candidates, and signal mismatches.
- Do not claim profitability or enable automated order placement based on M1 outputs.
- Make small changes, run tests, and report commands, test results, limitations and next decisions.

## Acceptance
A documented command fetches an entitled historical sample, generates a SIP-vs-IEX report (or an explicit entitlement-blocked report), and offline tests pass. No orders placed.

## Scope control
Do not build full backtester, momentum live scanner, AI news classifier, dashboard, or order manager until M1 is reviewed.
