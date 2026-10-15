# Bull Flag intrabar breakout: in-sample research report

**Verdict: NO-GO for this configuration.** With quote-level simulation of every entry and exit, both variants lose money in the base scenario: −0.16 R and −0.14 R per trade, profit factor about 0.7. Both lose clearly under the predeclared stress costs, where the 95% CI is entirely below zero. The rule should not be traded as specified. Any change, such as a different exit, filter or arming window, is a new experiment to pre-register before it is run.

Simulation only; 0 orders. In-sample days only: 59 days, 2026-06-03 to 2026-08-26. This run covers the **premarket session only** (`--sessions premarket`). The out-of-sample block was not used or inspected. The dataset and its quote cache were read only, with identical hashes before and after.

- Run at `de483a9`, with 4 workers.
- The quote windows for this run were downloaded beforehand with approval into a research cache outside the dataset (`research_out/bull_flag_intrabar/quote_cache`). This run itself made 0 API requests.
- Machine-readable summary: `reports/research_program/bull_flag_intrabar_summary.json`. Specification: `docs/research/bull_flag_intrabar_spec.md`.

## Reproduce

```powershell
.\.venv\Scripts\momentum-bot.exe m2-bullflag-intrabar --dataset reports\datasets\m2_sip_20260603_20261009 --sessions premarket --workers 4
```

Add `--fetch-missing-quotes` to download any setup windows that are still missing. The download is serial, before the parallel backtest.

## Rules as implemented (unchanged since before the first run)

- **Setup:** a Bull Flag on completed SIP 1-minute bars, scanner-gated. Pole: 3–10 bars, ≥ 5%. Flag: 2–8 bars, at most a 50% pullback, with lower volume than the pole.
  - Reference candle: the flag's highest-high bar.
  - Setup ID: symbol | date | session | reference bar.
  - The setup is armed for 3 minutes after it becomes known, and is voided if a bar closes below the reference Low.
- **Entry (NBBO proxy):** the first fresh, executable quote whose Bid exceeds the reference High. The buy arrives after 0.5 s and fills at the Ask, within the displayed size, the 20 bps limit, the 50 bps spread cap and the 10 s timeout.
- **Stop:** the reference Low, frozen at entry. It triggers on an executable Bid at or below it, and the sale fills at the Bid after latency, with partial fills.
- **Red-candle exit:** the first completed bar with Close < Open that begins at or after the entry. A stop takes priority.
- **Safety exits and limits:**
  - 15-minute maximum hold.
  - Session flatten 2 minutes before the close, and no entries in the last 10 minutes.
  - One position at a time, $15 risk per trade, 5 entries a day, $45 daily loss limit, pause after 3 losses in a row.
- **R:** net P&L / ((executed entry − reference Low) × shares).

## In-sample results, premarket (completed trades; no incomplete exits)

| | Bull Flag intrabar (no Top 5) | Top 5 + Bull Flag intrabar |
|---|---:|---:|
| setups detected | 4,349 | 3,042 |
| breakout signals (triggered) | 1,374 | 1,029 |
| voided before trigger / never triggered | 2,271 / 704 | 1,600 / 413 |
| non-fills (mostly spread above the 50 bps cap at the trigger) | 388 | 329 |
| executable entries = completed trades | 217 | 212 |
| same-symbol re-entries | 76 | 74 |
| win rate | 24.0% | 25.9% |
| average winner / loser | $20.14 / −$8.90 | $20.05 / −$9.36 |
| mean R (95% bootstrap CI) / median R | −0.16 [−0.32, 0.02] / −0.50 | −0.14 [−0.30, 0.04] / −0.50 |
| net realized P&L | −$421.66 | −$367.17 |
| max drawdown | $572.30 | $611.25 |
| profit factor | 0.71 | 0.75 |
| exits: red candle / stop / safety timeout / session end | 142 / 75 / 0 / 0 | 138 / 74 / 0 / 0 |
| mean R by exit: red candle / stop | +0.33 / −1.07 | +0.37 / −1.08 |
| skipped (position open, daily limits, entry cutoff) | 769 | 488 |
| partial entries | 12 | 6 |
| **stress:** trades, mean R (95% CI), net | 206, −0.26 [−0.42, −0.09], −$679.31 | 195, −0.30 [−0.45, −0.13], −$742.21 |

For comparison, the frozen HOS baseline (both sessions, its own exits) has mean R −0.24 and −$847.12.

## Sequencing and data quality

- **Trade prints:** none are cached, so no trade has trade-level sequencing (`reliable = 0`).
- **NBBO proxy:** all 217 and 212 base-scenario trades. The entry and every exit are simulated on quotes. No trade needed the 1-minute OHLC approximation, because every setup that broke out on the bars had its quote window.
- **Uncertain:** 0 in base, and 1 in the no-Top 5 stress run, where a stop-level Bid had the same timestamp as the entry fill.
- **Quote coverage:**
  - 1,886 of 4,349 setups (no Top 5) and 1,369 of 3,042 (Top 5) have quotes.
  - The setups without quotes never traded above their reference High on the bars, so they could not trigger. They were detected but needed no quotes.

## What the data supports

1. **The rule loses money as specified.** The red-candle exit captures winners (+0.33 R on average), but the stops (−1.07 R) and a 24–26% win rate outweigh them. The base CI's upper end touches zero; under stress the whole CI is negative.
2. **Spreads are a real constraint.** 331 of 1,374 triggers (24%) were rejected because the spread exceeded 50 bps at the breakout quote.
3. **The Top 5 filter barely changes the result:** −0.14 R against −0.16 R, with overlapping CIs.

## Differences from the frozen M2 baseline

The baseline (`hos`, `base_cap50`) is unchanged and is not part of this module. This strategy differs in all of the following:

- an intrabar entry above a structural reference High, not a candle-close confirmation;
- a structural stop at the reference Low, not a 3% stop;
- a red-candle exit, not a 2R target;
- the 15-minute hold used as a safety exit only;
- same-symbol re-entry on new reference candles;
- premarket only in this run.

## Limitations

- NBBO-triggered entries are proxies: a Bid above the level is not proof of a trade there. There are no trade prints.
- The universe is the dataset's cached sub-$20 eligible universe, with its survivorship limits; the Top 5 is point-in-time within that universe, not market-wide.
- In-sample only, and premarket only. One primary configuration, with no parameter search.
