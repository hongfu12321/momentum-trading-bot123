# Momentum Trading Research & Paper Bot — Design v1.0

**Status:** Proposal / M1 implementation-ready  
**Primary language:** Python 3.12  
**Broker:** Alpaca **paper only**  
**Trading sessions:** 04:00–09:30 and 16:00–20:00 America/New_York  
**Principle:** Validate data and strategy economics before automating orders.

## 1. Goals

Build a research-first, fully automated paper-trading platform inspired by small-cap momentum trading. Discover candidates, generate deterministic breakout signals, simulate realistic execution, analyze results, and eventually route qualified signals to Alpaca paper trading. Optional AI categorizes news catalysts; it never independently places orders or bypasses risk controls.

### Non-goals
- No live-money trading, live credentials, or live broker endpoints.
- No guarantee of profitability or replication of a particular trader's returns.
- No LLM-generated trading decisions or autonomous strategy mutation.
- No paid market-data dependency for M1.

## 2. Milestones

### M1 — Historical market-data feasibility (FIRST)
1. Test Alpaca Basic historical SIP access on dates **older than the applicable delay window**. Log entitlement failures, rate limits and session coverage; do not assume access.
2. Download one-minute **SIP and IEX** bars for matched symbols, dates and extended trading hours, where entitled.
3. Keep original UTC timestamps, derived ET session, source feed, download time, adjustment settings, and explicit missing-data markers.
4. Compare bar availability, volume, OHLC differences, scanner-candidate discovery and breakout signals across the two feeds.
5. Produce a reproducible report stating sample sizes, candidate misses and biases. IEX is not full-market consolidated volume.

**M1 acceptance:** One documented CLI command fetches sample historical bars and generates either a SIP-vs-IEX report or an explicit entitlement-blocked report. Offline fixture tests pass. **No orders are placed.**

### M2 — Deterministic backtesting
- Use point-in-time candidate universes, including delisted securities when available; report survivorship bias where not.
- Use only completed bars and data available at the decision time (previous close, volume, news, session high).
- Initial strategy: completed-bar high-of-session breakout with volume confirmation and liquidity filter.
- Simulate limit orders, quote spreads, slippage, non-fills, partial fills, timeout and transaction costs.
- Test walk-forward/out-of-sample; split premarket and after-hours performance.

### M3 — Real-time News Scanner + automated Alpaca PAPER execution
- Implement a read-only real-time news collector first, independently deployable from paper execution; start with Alpaca News REST/WebSocket using existing credentials, and verify entitlement, timeliness, ticker coverage and extended-hours availability empirically. Do not assume the feed is real time until tested.
- Provider abstraction for optional paid news feeds later, chosen based on measured latency, coverage, license, reliability and cost; no premium membership or OpenAI key is required to start.
- Normalize ticker(s), source, headline, article ID/version, provider published_at, local received_at, and alert/classified_at in UTC; deduplicate updates, handle reconnect/replay, and store a durable append-only journal.
- Detect and tag candidate catalysts (FDA/regulatory, earnings, contracts, M&A, offerings/dilution, reverse splits, promotions and no-news momentum). Start with deterministic tags; optional AI structured classification may be added in M3 behind a feature flag, with confidence/unknown states and no trading authority.
- Combine news with the SIP price/volume scanner for candidate alerts, including the stock's gap, volume, spread and price movement between publication and receipt. Record end-to-end alert latency and late-news cases. Never infer that a headline is bullish solely from positive wording.
- News is advisory only: never directly place orders, override risk checks, or block independent price/volume strategies. Make alerts usable without paper execution.
- Separately implement WebSocket market feed, stateful scanner, independent risk manager, paper broker adapter and persistent journal.
- Persistent kill switch, idempotent client_order_id, restart reconciliation, order lifecycle, disconnect fail-safe.
- Enforce **paper only** through configuration, credentials, endpoints, and tests; reject live modes.
- Acceptance: offline tests for duplicate/out-of-order articles, timestamp correctness, reconnection, delayed news, missing ticker and stale feeds; documented measured news availability/latency, with zero live orders.

### M4 — News/AI effectiveness evaluation and provider upgrades
- Compare news-tagged, optionally AI-filtered and price/volume-only strategies over matched periods; account for publication versus actual receipt time, costs and non-fills.
- Optional OpenAI structured classification: catalyst, sentiment, materiality, dilution risk, evidence and uncertainty; do not assume this improves returns.
- If AI is unavailable, news-required experiments fail closed; independent price/volume strategies continue.
- Evaluate paid news APIs only if M3 measured latency or coverage warrants the expense.

### M5 — Upgrade assessment
Evaluate full real-time SIP, point-in-time float data and higher-quality low-latency news. Live-money execution is **outside scope** until a separately approved design.

## 3. High-level architecture

```text
Historical / Live Data --> Normalizer --> Scanner --> Strategy Engine
          |                    |                          |
          v                    v                          v
    Coverage Audit       Event Journal              Risk Manager
          |                                               |
          v                                               v
    Backtest Engine <-- Execution Simulator        Alpaca PAPER Adapter
          |                                               |
          +----------------> Metrics / Reports <-----------+
News Provider --> Deduplicator --> Optional AI Classifier --> Signal Metadata
```

Backtest and forward paper-trading must share the same pure strategy interface. Keep adapters, signals, risk and execution separate.

## 4. Candidate selection (research hypotheses)

| Parameter | Premarket | After-hours |
|---|---:|---:|
| Price | $1–$20 | $1–$20 |
| Change vs previous regular close | >= 10% | >= 5% |
| Cumulative session volume | >= 100,000 shares | >= 100,000 shares |
| RVOL | >= 5, only if defensible | Research only |
| Float | <= 20M, only with trustworthy point-in-time source | Same |
| Breakout volume confirmation | >= 2x mean previous five completed 1m bars | Same |

Missing point-in-time float or spread must be tagged unknown, not fabricated. Avoid hindsight selection of eventual daily winners when evaluating candidate recall.

## 5. Session and risk policy

- `America/New_York`; exchange calendar, holiday, DST and early-close awareness.
- Entry windows: **04:00–09:20 ET** and **16:00–19:50 ET**, where venue and broker support permit.
- No new positions in 09:20–16:00 and 19:50–04:00. Continue managing existing exposures where markets permit; exits are never guaranteed.
- Extended-hours orders must satisfy broker-specific limit-order and `extended_hours` requirements. Do not rely on brackets or software stops to guarantee an exit.
- Research account $3,000; risk budget 0.5%/trade ($15); daily threshold 1.5% ($45); max notional 25%/position; one concurrent position; five entries/day; spread cap 0.5%; quote age <= 3s; pause after three consecutive losses.
- Count both realized and unrealized P&L, outstanding exposure and trading costs. Treat thresholds as intended risk controls, **not guaranteed loss caps**.
- Block all new orders on stale data, uncertain broker state, duplicate-order suspicion or persistent kill switch.

## 6. Execution simulator

Produce three labeled scenarios: idealized upper-bound reference; quote-aware base case; conservative stress case. For limit orders, model non-fill and partial-fill probability instead of subtracting only an arbitrary fixed haircut. Use historical quote/trade data when available and licensed; clearly label bar-only proxies. Model halts, sparse prints, gaps, adverse selection and cancellation races. Paper fills are not proof of live fill quality.

## 7. Metrics

- Net expectancy in R and USD, profit factor, drawdown, win rate, average win/loss, exposure, sample size and uncertainty intervals.
- SIP-vs-IEX candidate recall and signal differences on matched universe and intervals.
- Fill rate, spreads, slippage estimates, time-to-fill, missed exits and order failures.
- Segment by session, price bucket, volume bucket, market regime and month.
- Target preliminary 200–300 trades plus out-of-sample validation; not a guarantee of significance.
- Disclose survivorship, look-ahead, selection, corporate actions and data coverage caveats.

## 8. Optional AI integration (M3 feature flag; evaluated in M4)

- OpenAI Python SDK with configurable model and validated structured JSON.
- Output fields: ticker, article_id, sentiment, catalyst_type, strength_0_to_10, dilution_risk, confidence, evidence, unknown_reason.
- Treat article text as **untrusted data**, not operational instructions. Never send broker keys to the model.
- Log both publication timestamp and receipt/classification timestamps to prevent backtest look-ahead.
- Configurable 3-second deadline; timeout/error => unknown. Cache by article version.
- Classification strength is a heuristic, **not** calibrated return probability.

## 9. Storage contracts

SQLite for MVP, versioned migrations; optionally Parquet for raw data.
- `bars`: ticker, timestamp_utc, session, feed, OHLCV, ingestion_time, quality_flags.
- `quotes`: ticker, timestamp_utc, bid/ask and sizes, feed.
- `signals`: strategy/version, ticker, observed_at, features, decision, rejection reasons.
- `orders`: client_order_id, broker_order_id, states, requested/filled qty, timestamps.
- `fills`: order_id, price, qty, timestamp, simulation_or_paper.
- `news`: article_id, ticker, published_at, received_at, source, hash and classification.
- `runs`: code SHA, configuration snapshot, data provenance, assumptions, dates and metrics.

## 10. Suggested structure

```text
README.md
CLAUDE.md
docs/DESIGN.md
config/{scanner,strategy,risk}.yaml
src/momentum_bot/
  data/{alpaca_historical,normalize,coverage}.py
  scanner/{gap,momentum}.py
  strategies/{base,hod_breakout}.py
  backtest/{engine,execution,metrics}.py
  broker/{alpaca_paper,orders}.py
  risk/manager.py
  news/{provider,ai_classifier}.py
  journal/store.py
tests/{fixtures,unit,integration}/
scripts/validate_historical_data.py
reports/
.env.example
pyproject.toml
```

## 11. Engineering standards

Python 3.12, type hints, pytest, linting/formatting, pinned dependencies. Environment variables for secrets; `.env` ignored, `.env.example` contains placeholders only. Offline tests must work without credentials/network. Network tests opt-in. Experiments must record exact dates, feed, configuration, commit and assumptions. Use bounded retries, logs, API rate limiting and explicit provider errors. No orders in M1/M2 and no live orders in any phase.

## 12. Immediate Claude Code assignment: M1 only

1. Scaffold minimal Python package, `pyproject.toml`, `.gitignore`, `.env.example`, and pytest tests.
2. Implement Alpaca historical-bars adapter with explicit `feed=sip` / `feed=iex` and date ranges; report entitlement failures clearly.
3. Implement UTC/ET session normalization and sample-download CLI.
4. Compare feed coverage, matched-bar volumes, OHLC differences, missed candidates and tentative breakout mismatches.
5. Write `reports/m1_data_validation.md` with real observations and limitations. Never invent API results.
6. Run deterministic offline tests; document setup and commands.

**Done when:** documented CLI produces an honest report or a clear entitlement-blocked artifact, offline tests pass, and no orders or AI/dashboard code exists.
