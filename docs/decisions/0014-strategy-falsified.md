# Decision 0014 — The paired-bid strategy is falsified by its own fills

Date: 2026-11-24
Status: accepted — live trading stopped

## Method

Every number below comes from the venue's trade list, synced into the journal
(`pmm.execution.trades`), and from the venue's positions. Nothing is
extrapolated. Windows: run 1 = 2026-11-23 11:50 → 2026-11-24 02:00 UTC
(111 fills, 21 markets); run 2 = 2026-11-24 19:52 → 20:08 local (6 fills,
3 markets, 20.26 pUSD of capital).

## The premise, stated

Rest a bid on both outcomes at `mid ∓ half_spread`. If both fill, the pair
costs `p_up + p_down < 1` and merges for exactly 1.00 — the edge is the
spread. A single leg, by contrast, is a naked directional bet. Therefore

```
EV = fill_pair_rate × spread  −  (1 − fill_pair_rate) × E[loss | single leg]
```

## What actually happened

| Run | fills | markets | paired sets | excess (naked) shares | naked share |
|---|---|---|---|---|---|
| run 1 | 111 | 21 | 223.8 | **796.1** | **78%** |
| run 2 | 6 | 3 | 0.0 | 6 legs | **100%** |

Run 2 is the cleanest observation: 20.26 pUSD of capital, six fills, every one
of them the cheap side (0.07, 0.10, 0.10, 0.14, 0.16, 0.26), zero pairs.
Capital was down to 1.17 pUSD sixteen minutes later. The expensive leg never
filled because nobody sells a ~0.90 token at 0.87.

## The money, run 1

| Segment | cost | sold | value | net |
|---|---|---|---|---|
| markets with both legs ≥5 shares | 324.97 | 127.80 | 9.09 | **−188.08** |
| single-leg markets | 127.85 | 0.00 | 18.22 | **−109.63** |
| **total** | **452.82** | **127.80** | **27.28** | **−297.74** |

Even the "paired" segment lost 58% of its cost, because "both legs ≥5 shares"
is not "balanced": the sizes were lopsided (e.g. 103.5 up against 52.8 down),
and the unmatched remainder is the part that lost.

Realised return per unit of cost: `158.4 / 452.82 = 35%`, i.e. **−65%**.

## Verdict

`fill_pair_rate ≈ 0%` on the run where the guards were active. With that
number the EV expression collapses to the single-leg term, which is negative
because the leg that fills is systematically the side the market is pricing
towards zero — adverse selection, not bad luck.

**The strategy has no positive expectation in these markets.** This is not a
parameter problem: the mechanism that creates the edge (both legs filling)
does not occur.

## What is worth keeping

The infrastructure was proven in production and is reusable: order signing and
the v2 order envelope, the capital guard, venue inventory, merge, harvest
(0.999 sells, zero fee), redeem, the alert pass, and the fill journal.

## Two viable successors, both post-falsification

**A. Taker-side spread capture.** Trade only at a price that crosses and fills
immediately, so there is no resting risk. Verified enabler: a 0.99 limit sell
in a 0.999 book filled at 0.999 with `fee_bps = 0`. Requirements: a taker
budget, an explicit per-trade edge estimate, and no expectation of rewards.

**B. Event-driven with a Kelly cap.** Treat it as an explicit bet with a
probability model, size by fractional Kelly, and remove the maker machinery
from the decision path. The reward programme becomes irrelevant.

Choosing between them is a product decision and is not made here.

## Position plan (17 positions, 31.22 pUSD of marks)

| Class | Positions | Value | Action |
|---|---|---|---|
| redeemable, dead (price 0) | 6 | 0.00 | `pmm-redeem.timer` burns them; payout 0 |
| near-zero, not redeemable | 4 | 3.40 | leave; redeem when the market resolves |
| live, mid-range | 7 | 27.80 | hold to settlement; redeem pays face |

No new orders. `pmm-mm.service` is stopped; `pmm-merge`, `pmm-redeem` and
`pmm-alerts` keep running because they only recycle.
