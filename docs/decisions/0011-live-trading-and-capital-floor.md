# Decision 0011 — Live trading is on, and the capital floor it needs

Date: 2026-11-23
Status: accepted

## The short version

The order-signing key arrived, so the account trades. The service runs live
on the VPS (`pmm-mm.service`, no `--paper`, `POLY_DRY_RUN=0`) with two
resting bids. The binding constraint is no longer access, it is capital: one
20-share pair costs about 19–20 pUSD, so 23.37 pUSD runs exactly one market.

## Why the blocker turned out to be smaller than recorded

Decision 0005 and the credential notes concluded the venue required a
Deposit Wallet maker. That was wrong. The failure was a maker/signer pairing,
not a wallet migration. Verified live:

| Attempt | Result |
|---|---|
| `signature_type=0/1/2` with maker ≠ API key's address | `400 maker address not allowed` |
| `signature_type=1`, maker = proxy `0x6F7D43A8…`, signer = `0x18af…` | accepted, `status: live` |

So the legacy POLY_PROXY path trades on the v2 order envelope with the owner
key alone. No session key, no Deposit Wallet, no Builder key.

The Relayer API key (bound to `0x18af…`) is not used by the order path. It is
only needed for split / merge / redeem, each of which needs its own signed
batch.

## What changed in the code

`Runner._place` now reads the venue's free collateral (`OrderExecutor.collateral_balance`,
6-decimal pUSD) and drops intents the balance cannot fund, journaling
`order_skipped` with `reason: insufficient_collateral`.

The gate exists because the selector's budget model is the merge-funded one
(a quote commits its cheaper leg, because the pair funds itself on merge),
while the venue reserves **both** resting bids at placement time. With a
static `--capital` the selector can therefore authorise a quote the venue
will reject. Reading the balance each cycle closes that gap. Two intents in
the same pair are kept or dropped in the order given, never interleaved.

Tests: `test_the_balance_guard_drops_the_leg_it_cannot_fund` and
`test_the_runner_skips_an_unaffordable_leg_instead_of_sending_it`. Full
suite: 199 passed.

## The capital floor

Verified against the venue on 2026-11-23:

| Fact | Value |
|---|---|
| venue minimum order size | 5 shares |
| reward `min_size` across 1500 rewarded markets | 1088 markets allow ≤ 20, only **9** allow ≤ 5 |
| cost of a pair at size S | ≈ S × (p_up + p_down), and p_up + p_down ≤ 0.99 |
| first live pair | 20 @ 0.57 + 20 @ 0.40 = **19.4 pUSD** |
| free collateral | 23.368904 pUSD |

So:

- **20 shares per side is the practical minimum.** At mid 0.5 a pair needs
  ~20 pUSD; one market is what 23.37 pUSD buys.
- **5 shares per side is not a smaller version of the same strategy.** It is
  order-valid but reward-ineligible in 99.4% of markets, leaving only the
  ~1 cent per completed pair of spread. Sizing down buys nothing.
- Each additional market adds ~20 pUSD: 2 markets ≈ 43, 3 ≈ 63, 4 (the
  default `max_markets`) ≈ 83.

Leftover positions from old trades should be redeemed before the balance is
treated as a fresh budget; the relayer key can do that once a redeem batch is
built and signed by the owner key.
