# Taker-route simulator

`src/pmm/sim/taker.py` scores a cross-and-hold trade: take the offered side
when an external fair value says the ask is too cheap, then hold to
settlement. Fees are zero on the fills observed so far, so the only costs are
the spread and being wrong.

Inputs per observation: `fair` (from the OKX mid + window strike, priced as a
binary option), `quote` (bid/ask of the outcome token), and `won` (settlement).

First run on `/tmp/pilot-run/events.jsonl` (one resolved 5-minute window,
424 book snapshots, 55 scored observations, `min_edge` 0.005–0.05):

| min_edge | trades | wins | pnl | pnl/share |
|---|---|---|---|---|
| 0.005 | 55 | 0 | −2.80 | −0.00255 |
| 0.05 | 55 | 0 | −2.80 | −0.00255 |

The quoted edge averaged 0.463, which is not believable: the oracle was run
with an annualised volatility pinned at the 2.5 cap, so it produced near-certain
probabilities. **One resolved window is not evidence for or against the taker
route**; it only proves the harness works end to end. The real measurement
needs tens of resolved windows and a calibrated volatility estimate.
