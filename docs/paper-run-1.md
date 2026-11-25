# Paper run 1: the cost floor of a taker round trip

## Sample

Two independent recordings, same recorder, same 5 s interval:

| host | snapshots | markets | window | file |
|---|---|---|---|---|
| local | 1,662 | 12 | 2026-11-24 17:09 to 11-25 11:28 UTC (18.3 h) | `data/books-2026-11-25.jsonl` |
| VPS | 3,727 | - | longer, independent | `/var/lib/pmm/books/books-2026-11-25.jsonl` |

## Model

`src/pmm/paper/broker.py` fills by walking the book (a 20-share taker pays the
asks it consumes), charges `fee_bps` on the notional, and reports the average
price minus the best level as slippage. `tools/paper_mm.py` measures one round
trip per snapshot per outcome token: buy 20 at the asks, sell 20 at the bids,
on the same book.

## Result (20 shares, fee 0)

| host | round trips | median spread | mean PnL | per share | worst | best |
|---|---|---|---|---|---|---|
| local | 2,748 | 0.0100 | **-0.354** | **-0.0177** | -17.90 | **-0.02** |
| VPS | 7,454 | 0.0100 | **-1.018** | **-0.0509** | -17.90 | **-0.02** |

## What it says

1. **A round trip is always a loss.** The best case is -0.02 pUSD and the
   median book spread is one cent, so the cost floor is the spread, not the
   fee (which measured zero on the venue).
2. The VPS sample costs three times more per share than the local one. Same
   recorder, different markets: depth, not the fee, drives the number
   (-5.09c/share against -1.77c/share).
3. A taker strategy therefore has to earn its edge by **holding to
   settlement**. The round-trip loss is the threshold that edge must beat.

## Correction

The first pass reported a negative median spread and claimed 100% of books
were crossed. That was a sign error in the metric: `spread` was computed as
`bid - ask`. The books are normal (bids ascend from 0.001, asks descend from
0.999); the median ask-minus-bid is 0.01. The PnL numbers were correct
throughout, because they never used that field.

## Not yet measured

- Whether the oracle edge beats the floor. That needs **resolved windows**
  (book + outcome), and the recordings hold books only.
- Depth beyond 20 shares: the -17.90 worst case shows how fast it degrades.
