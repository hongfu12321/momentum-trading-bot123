# M1-A data validation: observations

**Status: passed.** Historical SIP and IEX 1m bars are both entitled on this Alpaca account for dates older than the delay window.

M1-A sample run (local folder `reports/runs/m1_20261013T163100Z/`, not committed): SOUN, MARA, PLUG on 2024-03-08, status `complete`, 4 API requests, 0 orders.

| session | SIP bar minutes | IEX bar minutes | SIP volume | IEX volume | IEX share |
|---|---:|---:|---:|---:|---:|
| premarket | 755 | 17 | 8,895,120 | 5,679 | 0.06% |
| after-hours | 565 | 1 | 5,501,333 | 500 | 0.01% |

IEX missed the one SIP scanner candidate and all 11 price-band breakouts. Three symbols on one day is a feasibility check only. The broad 30-day study and the M2 recommendation are in [`m1_feasibility.md`](m1_feasibility.md).
