# Decision 0013 — The live run lost ~100 pUSD, and what caused it

Date: 2026-11-24
Status: accepted

## What happened

The first live run (2026-11-23 11:50 UTC → 2026-11-24 ~02:00 UTC) went from
about 150 pUSD of equity to 51.7. Deposits were about 103 pUSD, so the net
loss is roughly 51 pUSD, with a peak-to-trough of about 100.

Measured from the journal and the venue's positions:

| Metric | Value |
|---|---|
| fills | 111 |
| markets | 21 |
| bought | 452.82 pUSD (gross, including recycling) |
| sold | 127.80 pUSD |
| still held | 46.45 pUSD |
| net of that turnover | **−278.57 pUSD** |
| equity now | 51.73 pUSD (cash 0.477 + positions 51.25) |

The three recycling paths worked: `merge`, `harvest` and `redeem` all paid
(107.91 pUSD came back from the London and Milan sales at 0.999). They
monetise winners; they cannot rescue losers.

## The three causes

**1. Single-leg fills are directional bets, and they were losing.**

The strategy rests two bids so that both filling produces an outcome-independent
1.00 set (the edge is 3c per set). Most fills were one-sided: the other leg
never followed, so the position became a bet on one outcome, held to
settlement. The loser side goes to zero.

**2. Nothing capped the inventory, so the bets were pyramided.**

`inventory_box` was 0, which the engine reads as "no limit". Every cycle
re-quoted and filled again: a 20-share position became 80, 100, 156 shares.

**3. The quoted markets were about to settle.**

Every large loss is a market resolving the same day it was quoted: "highest
temperature on November 23", "gas price November 24". Near settlement the
book still shows a midpoint while the outcome is being decided, so our
resting bid is exactly what an informed taker hits. The most expensive single
market (`0xcddadc9c99`, 80 shares at 0.55) went to zero.

## What changed

1. **Horizon filter** — `discover_markets` refuses closed markets and any
   market whose `end_date_iso` is under 24 hours away
   (`min_hours_to_resolution`).
2. **Per-market exposure cap** — `select_quotes` rejects a market whose two
   legs would reserve more than `max_market_usd` (25 pUSD). The cap counts
   both legs, which is what the venue reserves, not the cheaper-leg budget
   model.
3. **Inventory box** — `inventory_box = 40` shares, so a market cannot be
   pyramided past twice the order size.

Tests: `tests/test_guards.py`. Full suite 249 passed.

## What is still open

- A one-sided fill still becomes a directional position; the guards bound the
  damage but do not remove the exposure. The honest next step is to require
  both legs to fill, or to exit a leg that has not been paired within a
  bounded time — neither is implemented.
- The equity attribution above uses the journal, which only became complete
  on 2026-11-23. Earlier fills were backfilled from the venue's trade list.
- The 6-hour dry run after these guards decides whether quoting is re-armed.
  Re-arming is a separate, explicit decision.
