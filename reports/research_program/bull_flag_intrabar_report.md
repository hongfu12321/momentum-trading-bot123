# Bull Flag intrabar breakout: in-sample research report

**Verdict: BLOCKED.** An executable, quote-level evaluation is not possible with the local data: only 20 of 7,208 setups (0.3%) have cached NBBO coverage, and no trade prints are cached. The 1-minute OHLC approximation loses money (−$775 base, −$1,354 stress), but that loss comes entirely from trades whose intrabar order of entry and stop is unknown and was resolved against the strategy. The data cannot tell a working rule from a failing one. Do not trade this; unblocking it needs quotes or trade prints for the setup windows.

Simulation only; 0 orders. In-sample days only (59 days, 2026-06-03 to 2026-08-26, 118 sessions, 0 missing bar files). Out-of-sample data was not used or inspected. 0 network requests. The dataset and quote cache were read only, and their hashes were identical before and after the run. Machine-readable summary: `reports/research_program/bull_flag_intrabar_summary.json`. Specification: `docs/research/bull_flag_intrabar_spec.md`.

## Reproduce

```powershell
.\.venv\Scripts\momentum-bot.exe m2-bullflag-intrabar --dataset reports\datasets\m2_sip_20260603_20261009
```

## Rules as implemented

- **Setup:** a Bull Flag on completed SIP 1-minute bars, scanner-gated. Pole: 3–10 bars, ≥ 5%. Flag: 2–8 bars, at most a 50% pullback, with lower volume than the pole.
  - Reference candle: the flag's highest-high bar.
  - Setup ID: symbol | date | session | reference bar.
  - The setup is armed for 3 minutes after it becomes known, and is voided if a bar closes below the reference Low.
- **Entry:** the first moment the market is above the reference High.
  - NBBO proxy: the Bid exceeds the High. The buy arrives after 0.5 s and fills at the Ask, within the displayed size, the 20 bps limit, the 50 bps spread cap and the 10 s timeout.
  - OHLC approximation: the bar High exceeds the reference High. The entry is max(open, High) + 25 bps, capped at 10% of the bar's volume.
- **Stop:** the reference Low, frozen at entry. NBBO: an executable Bid at or below it, with a sale at the Bid after latency and partial fills. OHLC: min(open, stop) − 25 bps.
- **Red-candle exit:** the first completed bar with Close < Open that begins at or after the entry. A stop takes priority.
- **Safety exits and limits:**
  - 15-minute maximum hold.
  - Session flatten 2 minutes before the close, and no entries in the last 10 minutes.
  - One position at a time, $15 risk per trade, 5 entries a day, $45 daily loss limit, pause after 3 losses in a row.
  - Same-symbol re-entry only on a new reference candle.
- **R:** net P&L / ((executed entry − reference Low) × shares).

## In-sample results (completed trades only; no incomplete exits occurred)

| | Bull Flag intrabar (no Top 5) | Top 5 + Bull Flag intrabar |
|---|---:|---:|
| setups detected | 7,208 | 5,335 |
| breakout signals (triggered) | 2,620 | 1,981 |
| voided before trigger / never triggered | 3,727 / 861 | 2,811 / 543 |
| executable entries | 233 | 241 |
| completed trades / incomplete exits | 233 / 0 | 241 / 0 |
| same-symbol re-entries | 66 | 78 |
| win rate | 23.2% | 26.6% |
| average winner / loser | $23.08 / −$11.29 | $21.35 / −$11.39 |
| mean / median R | −0.31 / −1.02 | −0.26 / −1.00 |
| net realized P&L | −$774.66 | −$649.15 |
| max drawdown | $774.66 | $693.37 |
| profit factor | 0.62 | 0.68 |
| exits: stop / red candle / safety timeout / session end | 117 / 116 / 0 / 0 | 119 / 122 / 0 / 0 |
| skipped (risk limits, position open, entry cutoff) | 2,387 | 1,740 |
| rejected / non-fill | 0 / 0 | 0 / 0 |
| **stress** net P&L / mean R | −$1,353.50 / −0.47 | −$1,227.31 / −0.42 |

All trades were premarket. The shared daily limits (5 entries, $45 loss, 3-loss pause) were used up before the after-hours session on every day that had premarket trades.

## Sequencing quality (the decisive limitation)

| sequencing | no Top 5: trades, net, mean R | Top 5: trades, net, mean R |
|---|---|---|
| reliable (trade prints) | 0 | 0 |
| NBBO proxy | 3, +$85.13, +1.95 | 2, +$87.87, +3.12 |
| OHLC approximate | 158, +$137.80, +0.03 | 155, +$426.64, +0.18 |
| **OHLC uncertain** (the entry minute also traded at or below the stop; stop assumed) | **72, −$997.59, −1.14** | **84, −$1,163.66, −1.14** |

The whole loss comes from the uncertain trades, where the strategy's own rule cannot be applied because the order of breakout and stop inside one minute is unknown. The conservative assumption (stop) was predeclared and not changed. The remaining OHLC trades are roughly flat, but they too are approximations, with no knowledge of the fill time, spread or displayed size. Splitting the results this way is descriptive only; nothing was tuned on it.

**Missing-quote coverage:** 7,188 of 7,208 setups (99.7%) have no cached NBBO for their window. The cache holds only short windows around the HOS baseline and Top 5 signals.

## Differences from the frozen M2 baseline

The baseline (`hos`, `base_cap50`) is unchanged and is not part of this module. This strategy differs in all of the following:

- an intrabar entry, not a candle-close confirmation;
- a structural stop at the reference Low, not a 3% stop;
- a red-candle exit, not a 2R target;
- the 15-minute hold used as a safety exit only;
- same-symbol re-entry on new reference candles.

It shares the latency, spread cap, timeout, displayed-size and fee model, and the account limits.

## Limitations

- No trade prints, and NBBO for only 0.3% of setups. Results are approximations, not executable estimates.
- The OHLC entry price, exit price and fill time inside a minute are assumed; the costs are predeclared (25 bps per side base, 50 bps stress) and not measured.
- The universe is the dataset's cached sub-$20 eligible universe, with its survivorship limits; the Top 5 is point-in-time within that universe, not market-wide.
- The red-candle definition, the 3-minute arming, the 15-minute safety hold and the costs form one primary configuration. Any change is a new pre-registered experiment.

## Next decision

Unblocking needs, for the in-sample setup windows only, SIP quotes (or trade prints) from each setup's start to its latest exit. That would be about 7,200 short windows, a data download that needs separate approval. Without it, the only honest statement is that this rule cannot be evaluated on this dataset.
