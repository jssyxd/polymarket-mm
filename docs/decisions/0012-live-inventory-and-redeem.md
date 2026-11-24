# Decision 0012 — Live inventory comes from the venue; redeeming the old positions pays nothing

Date: 2026-11-23
Status: accepted

## The short version

The live loop was quoting against an inventory it could not see, because
`Runner._inventory` derived positions from journal fills and a live fill never
writes one. It now reads the venue's positions. Separately, the 18 "redeemable"
positions turned out to be resolved losers: redeeming them is cleanup worth
**0 pUSD**, not recovered capital.

## What the redeem actually recovered

Redeemed through the relayer with the owner signature (`SecureClient.redeem_positions`,
one CTF call per condition, gasless). The first one moved the account from 20
positions to 19, which confirms the path works for a POLY_PROXY wallet.

Every redeemed leg had `current_price = 0.0`: they were the losing side of
temperature markets that resolved in September. Payout per leg is
`size × 1` for the winning token and **0** for the losing one, so the batch
returns nothing. It only clears the portfolio view.

The account's other 18 positions from that period are gone or resolved; the
19 pUSD of value sits in two positions opened **today by the live loop**, not
in anything historical.

## Where the capital actually went

| Item | pUSD |
|---|---|
| free collateral before the live loop | 23.368904 |
| filled: 20 Amsterdam Yes @ 0.82 | 16.40 |
| filled: 40 Munich No @ 0.08 | 3.20 |
| free collateral after | 3.768904 |

Those are one-legged fills: the paired-bid design expects both legs, so a
single leg is naked directional exposure, and it consumed 85% of the budget.
With 3.77 pUSD free the loop cannot fund a 20-share pair and the balance
guard now drops every intent, which is why the book is empty.

The engine never saw those fills. `_inventory` built positions from
`journal.fills()`, and only `_record_paper_fills` writes fills, so the live
path always reported a flat book: the inventory box gate was blind and the
cycle kept quoting as if nothing had been bought.

## The fix

`Runner` takes a `positions_source`; in live mode it defaults to
`read_positions()` (Data API v2 `/v2/positions`, keyed by token id) and the
journal stays the fallback. Test:
`test_live_inventory_is_read_from_the_venue_not_the_journal`. Full suite: 200 passed.

## Why the positions were not sold to raise cash

Both markets charge `fee_rate_bps = 1000`, a **10% taker fee**, and the best
bids were 0.76 (Amsterdam Yes, 5 shares deep) and 0.047 (Munich No). Exiting
would return roughly 15.4 pUSD against 19.6 paid — a ~4.2 pUSD loss — while
holding to resolution on 2026-11-23 (today) pays face value with no fee.

So the capital is parked, not lost: it comes back as pUSD on resolution, via
`redeem_positions`. Until then the loop has 3.77 pUSD and stays flat.

## What this means for sizing

A one-legged fill can eat the whole budget. Until the loop re-posts the
counter-leg of every filled pair (or refuses to quote markets where it cannot
fund both legs up front), the capital floor per market must cover **both**
legs: ~20 pUSD at 20 shares, not the ~10 the merge-funded model assumes.
