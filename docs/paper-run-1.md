# Paper run 1: the cost floor of a taker round trip

## Sample

Local recording, 1662 snapshots across 12 markets, 11-24 17:09 to 11-25 11:28 UTC (18.3 h). The VPS file holds a longer, independent sample; this run uses the local one.

## Model

`src/pmm/paper/broker.py` fills by walking the book (a taker of 20 shares pays
the asks it consumes), charges `fee_bps` on the notional, and reports the
average price minus the best level as slippage. `tools/paper_mm.py` measures
one round trip per snapshot on each outcome token: buy 20 at the asks, sell 20
at the bids, same book.

## Result (2,748 round trips, 20 shares, fee 0)

| metric | value |
|---|---|
| mean PnL per round trip | **-0.354 pUSD** |
| per share | -0.0177 pUSD |
| median quoted spread | -0.01 (books are frequently crossed) |
| mean buy slippage | 0.000232 pUSD/share |
| worst / best round trip | -17.90 / -0.02 |

## What it says

1. Crossing both ways is a guaranteed loss on a normal book: the mean is
   negative and the best case is still negative. The cost is the spread, not
   the fee (which is zero on the observed markets).
2. A median spread of -0.01 means the recorded books are often **crossed**:
   stale quotes with a bid above the ask. That inflates the sample in both
   directions and must be filtered before the number is trusted as a cost
   floor.
3. Therefore a taker strategy has to hold for the settlement edge, not for a
   round trip. The round-trip number is the threshold that edge must beat.

## Not yet measured

- Whether the oracle edge exceeds that threshold (needs resolved windows, not
  just books).
- Depth beyond 20 shares: the worst case (-17.9) shows how fast it degrades.
