# M1 data validation — observations

**Status: not yet run against the Alpaca API.** No real observations are recorded here, and none
should be inferred from the offline test fixtures, which are synthetic.

To produce real results, run the documented command (see README, "M1 command") with Alpaca
credentials, then summarise the generated `reports/runs/m1_<timestamp>/report.md` here:

- Run folder, code SHA, dates, symbols and how the symbol list was chosen (selection bias).
- Whether historical SIP was entitled on the account (copy any entitlement error verbatim).
- Premarket and after-hours coverage, IEX volume share, session high/low differences.
- Candidate and breakout recall of IEX relative to SIP, with sample sizes.
- Limitations listed in the run report, plus anything unexpected (e.g. IEX-only minutes).
