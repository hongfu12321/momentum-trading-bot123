# M3 — Real-time News Scanner

**Goal:** Identify US small-cap momentum candidates as soon as relevant news arrives, particularly premarket and after-hours. This is an M3 planning specification; do not interrupt ongoing M2 backtesting.

## Scope
1. **Alpaca first:** Test News REST + WebSocket using existing credentials; verify actual news entitlements, receipt latency, extended-hours coverage, and relevant small-cap ticker mapping. Do not assume real-time entitlement from historical SIP access.
2. **News ingest:** Provider-neutral adapter, retry/reconnect, idempotent article/version deduplication, durable local journal and timestamped raw metadata (respect provider licensing).
3. **Catalyst tags:** FDA/regulatory, earnings, contracts, M&A, financing/offering/dilution, reverse splits, promotions, other/unknown. Initially deterministic; optional AI classification behind an off-by-default flag. News is untrusted input.
4. **Scanner join:** Correlate each article with SIP candidate metrics, pre/post-news price moves, volume, quote spread where available, and publication-to-receipt-to-alert latency.
5. **Alerts only initially:** Console/log notification, later optional Telegram; no autonomous trades based on a headline. Existing M3 Alpaca PAPER execution is a separate, gated workstream with independent risk limits and kill switch.
6. **Provider decision:** Compare actual coverage/latency/reliability/cost before adding a paid Benzinga or other API. Avoid requiring a premium UI membership.

## Acceptance criteria
- Deterministic offline tests for out-of-order timestamps, duplicates, corrections, missing ticker, stale feeds, reconnect/replay and clock skew.
- Document provider entitlement and measured end-to-end latency with representative premarket/after-hours observations.
- Persist `article_id`, `ticker(s)`, `source`, `published_at`, `received_at`, `alerted_at`, `version/hash`, `catalyst_tag`, `unknown_reason` where applicable.
- Never commit secrets or restricted news payloads; no live-money trading, no order placement from news, and no alteration to M2 code.

## Sequencing
Complete M2 first. In M3, implement news ingest and alerts as a standalone read-only slice before connecting them to the paper-trading pipeline.