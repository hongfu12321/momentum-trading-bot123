# Bull Flag intrabar breakout: specification (research only)

Historical simulation only. Nothing here can place an order. In-sample days only; the code refuses any other sample. The parameters below were fixed before the first in-sample run and were not changed afterwards. Implementation: `src/momentum_bot/bullflag_intrabar.py`. Tests: `tests/test_bull_flag_intrabar.py`.

## Command (reproducible, cache-only, read-only)

```powershell
.\.venv\Scripts\momentum-bot.exe m2-bullflag-intrabar --dataset reports\datasets\m2_sip_20260603_20261009
```

- Reads the dataset's SIP bars, `references.csv.gz` and the quote cache. Never writes to the dataset or the cache, and makes no network requests.
- Hashes every input file before and after the run (`inputs_unchanged`); the command fails if they differ.
- Writes per-setup and per-trade CSVs to `research_out/bull_flag_intrabar/` (git-ignored, outside the dataset), and the aggregate, symbol-free summary to `reports/research_program/bull_flag_intrabar_summary.json`.

## Setup (completed bars only)

When a 1-minute SIP bar j completes, the bars up to and including j are checked for a flagpole followed by a consolidation ending at j. The rules are those of `bullflag.FlagParams` (#9), without its breakout rules:

| rule | definition |
|---|---|
| complete bars | pole and flag are consecutive minutes; a missing bar is never filled |
| flagpole | 3–10 bars; last pole bar's high / first pole bar's low − 1 ≥ 5%, and the last pole bar holds the pole's highest high |
| consolidation | 2–8 bars; the flag's highest high is not above the pole top |
| pullback | (pole top − flag low) / (pole top − pole base) ≤ 50% |
| volume contraction | flag average volume < pole average volume (after-hours closing-auction bar counted as 0) |
| scanner gate | bar j passes the scanner gate: price $1–$20, change ≥ 10% premarket / 5% after hours, session volume ≥ 100k |

The shortest valid consolidation wins, then the shortest flagpole.

**Reference candle:** the consolidation bar with the highest high (the latest one on ties). This is a rule, not a fixed index: in the user's example it is candle 7, and the breakout happens during candle 9.

**Setup ID:** `symbol | trading date | session | reference bar start`.

**New flag versus repeated signals:** later bars that pick the same reference candle are the same setup, with the same ID, and are dropped. A new setup needs a different reference candle. A reference candle can produce at most one entry.

**Arming:** the setup is known at bar j's end, and it can trigger during the following 3 minutes (`arm_bars = 3`). A completed bar closing below the reference Low voids it.

## Breakout trigger and entry

Data are used in this order:

1. **Trade prints:** none are cached, so this source is unsupported. No result has trade-level sequencing (`reliable_sequencing_trades = 0`).
2. **NBBO quotes (`nbbo_proxy`):** used only when the local quote cache covers the whole span from the setup's start, through its expiry, to the latest possible exit. The trigger is the first fresh, executable quote after the setup is known whose **Bid exceeds the reference High**. This is a proxy: a quote crossing the level does not prove a trade at that price. The buy order arrives after the existing 0.5 s latency and fills at the Ask, within the displayed size, with a limit 20 bps above the trigger Ask, the existing 50 bps spread cap and a 10 s timeout. Quotes that are stale, crossed or locked never trigger anything.
3. **1-minute OHLC (`ohlc_approx`):** used when quotes do not cover the setup. The trigger is the first bar whose High exceeds the reference High; touching it is not enough. The entry is max(bar open, reference High) plus 25 bps, capped at 10% of the trigger bar's volume. The fill time inside the minute is unknown, so these results are labelled approximate.

A fill is never assumed at the reference High.

**Sizing:** shares = floor(min($15 / (price − stop), $750 / price)), using the limit price for NBBO and the entry price for OHLC. A setup is rejected when price − stop ≤ 0.

## Exits

- **Stop:** the reference candle's Low, frozen at entry and never moved. NBBO: the first fresh executable Bid at or below the stop triggers a sell at the Bid after latency, with partial fills; unsold shares are recorded, never assumed sold. A gap below the stop fills at the executable Bid, not at the stop. OHLC: a bar whose low reaches the stop exits at min(open, stop) − 25 bps.
- **Red candle (primary exit):** the first completed bar with Close < Open whose whole interval begins at or after the entry fill. The bar containing the entry is therefore never eligible. The exit is known when that bar completes. NBBO: a sell at the Bid after latency. OHLC: a sell at the next available bar's open − 25 bps. A stop seen before the red candle completes takes priority, including at equal timestamps.
- **Safety exits:** these are risk constraints, not profit targets, and there is no 2R target.
  - 15 minutes after entry (`max_hold`).
  - The session flatten time, 2 minutes before the close.
  - Entries after the entry cutoff, 10 minutes before the close, are skipped.
  - In OHLC mode, if no later bar exists to price an exit, the shares stay unsold and are reported as incomplete.
- **Ambiguity:**
  - OHLC: an entry bar that also trades at or below the stop is labelled `uncertain`, and the worse outcome is assumed (stop).
  - NBBO: a stop-level Bid with the same timestamp as the fill is labelled `uncertain`.

R = net P&L / ((entry − stop) × shares), using the actual executed entry.

## Portfolio and re-entry

The baseline's account rules apply unchanged: one position at a time, $15 risk per trade, at most 5 entries a day, a $45 daily loss limit, and a pause after 3 losses in a row.

- **Re-entry in the same symbol:** allowed only on a new setup, with a new reference candle, after the previous position has fully exited. There is no averaging down.
- **A setup that triggers while a position is open** is consumed: it is never re-armed later just because price is still above its level.

Variants:

- `bf_intrabar`: every setup.
- `top5_bf_intrabar`: setups whose setup bar is in the point-in-time Top 5 of the cached sub-$20 universe (#8's ranking, with the 5-minute freshness policy).

## Scenarios (predeclared)

| scenario | NBBO | OHLC |
|---|---|---|
| base | existing `base`: 0.5 s latency, 100% of displayed size, touch prices | 25 bps per side |
| stress | existing `stress`: 2 s latency, 50% of displayed size, 10 bps adverse | 50 bps per side |

## Fixed for a future, separately pre-registered experiment

The red-candle definition (Close < Open, the whole bar after the entry), `arm_bars = 3`, the 15-minute safety hold and the OHLC costs are the single primary configuration. Changing any of them is a new experiment to register before it is run, never a tweak made after looking at these results.
