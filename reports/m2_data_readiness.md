# M2 data readiness: 90-day SIP dataset, historical quotes and survivorship

**Dataset:** `reports/datasets/m2_sip_20260603_20261009/`. Only `report.md`, `manifest.json`, count-only `eligibility.csv` and the aggregate `quote_probe_summary.json` are committed. Per-symbol tables, raw bars, raw quotes, the asset snapshot and other input snapshots are licensed data and stay local (`.gitignore` allowlist).
**Window:** 90 trading days, 2026-06-03 to 2026-10-09; premarket 04:00–09:30 ET and after-hours 16:00–20:00 ET
**Code:** `bb9c7a4` · **API:** Alpaca market data plus one read-only paper `GET /v2/assets` lookup (1,874 requests on the first build, 0 on the cached rerun; 100 for the quote probe) · **Orders placed or cancelled:** 0
**Reproduce:**

```
momentum-bot m1-dataset --start 2026-06-03 --end 2026-10-09 --out-dir reports/datasets/m2_sip_20260603_20261009
momentum-bot m2-quote-probe --dataset reports/datasets/m2_sip_20260603_20261009 --sample 60 --minutes 30 --seed 20261013
```

**Profitability:** not evaluated. No strategy has been run. Transaction costs, spreads, slippage and non-fills are not modelled yet, and nothing here is evidence that the strategy makes money.

## Recommendation

**Execution simulation can begin, on SIP bars plus SIP quotes, with in-sample days only.** Historical SIP quotes are available for every sampled extended-hours candidate window, and fetching them for all 4,187 candidates is affordable (about 7,000 requests, 1.5 hours and 4.7 GB of raw JSON before compression).

The simulator must handle these points before any result is reported:

1. **Spreads are wide.** The median candidate window has a time-weighted spread of 100 bps in premarket and 111 bps after hours. Both are about twice the design's 50 bps cap. A strict cap would block most entries: the median window is within the cap only 18% of the time in premarket and 8% after hours. Whether to keep, raise or make the cap time-varying is a strategy decision. Make it on in-sample days only.
2. **Fills must come from quotes, not bar prices.** Buys should fill at the ask and sells at the bid, after a latency delay. Limit orders that the market never reaches are non-fills. Size must be capped by the displayed size at the time of the order.
3. **Locked and crossed quotes occur.** Reg NMS lock/cross protections do not apply in extended hours. Crossed quotes are 0.3–0.4% of all quotes and locked quotes 2–3%. Treat a crossed quote as unusable. Treat a locked quote as having no spread advantage.
4. **Quote gaps exist.** The median window's longest gap between quotes is 20 s (premarket) and 26 s (after hours), and the p90 is about 165 s. Stops and exits need a rule for a stale quote.
5. **Fees:** Alpaca equity trades are commission-free, but sells pay SEC and FINRA TAF fees. Model them from the start.

## Findings

### 1. The 90-day SIP dataset

| | premarket | after-hours |
|---|---:|---:|
| Sessions | 90 | 90 |
| Eligible symbols per session (mean) | 3,416 | 3,471 |
| SIP 1m bars | 4,056,277 | 3,028,505 |
| SIP scanner candidates | 2,309 | 1,878 |
| SIP minute coverage after trigger (median) | 96.6% | 78.9% |
| Longest SIP gap after trigger (median minutes) | 1 | 4 |
| IEX candidate recall of SIP | 6.4% | 1.0% |

The 30-day M1-B findings hold over 90 days. IEX is still unusable in extended hours: it carries about 0.1% of SIP volume, with the closing-auction bar excluded.

### 2. Chronological out-of-sample split

| sample | trading days | dates | SIP candidates (PM / AH) | gated breakouts (PM / AH) |
|---|---:|---|---:|---:|
| in-sample | 59 | 2026-06-03 to 2026-08-26 | 1,652 / 1,281 | 1,622 / 1,537 |
| embargo | 1 | 2026-08-27 | 26 / 21 | 23 / 14 |
| out-of-sample | 30 | 2026-08-28 to 2026-10-09 | 631 / 576 | 705 / 783 |

Every candidate, breakout, eligibility and quote-window row carries its `sample` label (`momentum_bot/split.py`). The one-day embargo stops an after-hours setup and the next morning's premarket from straddling the boundary. Parameters must be chosen on in-sample days. Out-of-sample results are reported once.

**Contamination disclosure:** the out-of-sample block is exactly the 30-day M1-B window. That window was inspected for data quality, and the closing-auction exclusion came from it. No strategy parameters were fitted on it. The scanner thresholds come from `docs/DESIGN.md` and have not been tuned. The quote probe's 60 windows include 19 out-of-sample windows. They were used only to judge whether quote data is available, not to choose a spread cap or other parameters. A clean out-of-sample test needs data after 2026-10-09 that nobody has looked at.

### 3. Historical SIP quote availability

The probe used 60 SIP candidates (30 per session), sampled deterministically with seed 20261013, and fetched 30 minutes of SIP quotes after each trigger. After-hours windows were clipped at 20:00 ET.

| | premarket | after-hours |
|---|---:|---:|
| Windows returned / requested | 30 / 30 | 30 / 30 |
| Entitlement or other errors | 0 | 0 |
| Quotes per window (median; p10–p90) | 7,224 (310–29,845) | 3,141 (252–22,752) |
| Minutes with at least one quote (median; p10) | 100%; 83% | 100%; 90% |
| Median spread (median window; p10–p90) | 84 bps (35–185) | 89 bps (54–268) |
| Time-weighted spread (median window; p10–p90) | 100 bps (41–163) | 111 bps (61–228) |
| Time within 50 bps cap (median window; p90) | 18%; 64% | 8%; 38% |
| Locked / crossed share of quotes | 3.3% / 0.44% | 2.2% / 0.33% |
| Longest quote gap (median window; p90) | 20 s; 164 s | 26 s; 171 s |

Results are heavy-tailed and depend on the sample. The 30-day probe measured a 24% locked share in premarket, and most of that came from one symbol. Final numbers should come from the full candidate set.

### 4. Read-only inactive-symbol lookup and remaining survivorship bias

The lookup was one `GET /v2/assets?status=inactive|active&asset_class=us_equity` call per status on the paper host, using Alpaca **paper** credentials. The client refuses live (`AK…`) keys. It can reach only `paper-api.alpaca.markets` and `/v2/assets`, and the offline tests enforce this. It returned 19,170 inactive and 14,387 active assets. After removing non-common and fund-named assets, it added 16,062 inactive symbols and 975 active OTC symbols to the universe.

| origin | symbols in universe | eligible per session (mean) | SIP candidates |
|---|---:|---:|---:|
| current listing (Nasdaq Trader snapshot) | 5,897 | 3,308 | 4,050 |
| renamed (corporate actions) | 94 | 32 | 108 |
| delisted (corporate actions) | 326 | 50 | 2 |
| Alpaca OTC (assets lookup) | 975 | 51 | 27 |
| Alpaca inactive (assets lookup) | 16,062 | 1.9 | 0 |

The inactive lookup changed little in this window. Most inactive assets stopped trading before 2026-06-03, so they have no SIP bars here and stay ineligible. Corporate-action delistings are eligible about 50 times per session, which shows that Alpaca still serves bars for symbols that have since been delisted. In total, 137 of 4,187 SIP candidates (3.3%) are not in today's listing. A today-only universe would have silently dropped them. Duplicate daily series hid 62 symbol-days.

**Remaining survivorship bias, stated explicitly:**

- **Issues Alpaca never carried, or purged,** are invisible. No free source covers them.
- **Delisting dates are unknown** for symbols found only through the assets lookup. Eligibility depends on a prior-day SIP bar, so a delisted symbol counts only on days it actually traded on an exchange. Post-delisting OTC trading is not in SIP.
- **Renames missing from corporate actions** can double-count one issuer under two tickers. The identical-series de-duplication mitigates this but cannot catch renames whose series differ.
- **Security type is judged from today's names,** so an issue that was a fund or warrant in the past, or changed its name, may be misclassified.
- **Ticker reuse:** a pre-rename ticker that is listed again today is treated as a different issuer. This is right in most cases but not checked against CUSIPs.
- **The universe snapshot is dated 2026-10-13,** after the window ends. Symbols listed after the window have no bars in it and cannot leak in. Symbols that left the market before today depend entirely on the add-backs above.

The bias that remains most likely leans optimistic: failed small caps are the issues most likely to be missing. Only an approved paid point-in-time reference source (CRSP, Norgate or similar) would close it.

## Decisions needed

1. **Spread cap:** keep 50 bps (few trades), raise it, or tie it to price and time. Decide on in-sample data only.
2. **Fresh out-of-sample data:** reserve trading days after 2026-10-09 as the first untouched hold-out, given the contamination above.
3. **Full quote fetch:** approve fetching SIP quotes for all candidates (about 1.5 h and 4.7 GB raw, stored locally and gzip-compressed, never committed) as the simulator's input.
