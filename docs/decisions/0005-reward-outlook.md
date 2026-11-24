# Decision 0005 — What the reward actually pays, and what is still missing

Date: 2026-11-23
Status: accepted

## The short version

The reward arithmetic is now correct and the account can fund a qualifying
quote. The expected daily reward on the market the system has selected is
about 460 pUSD, but **nothing has been earned yet and nothing can be earned
until the account can sign an order.** Two things stand between the current
state and a paid reward: the balance changed without explanation, and the
order-signing key is still missing.

## What the selected market pays

The market the runner picks, verified against the venue on 2026-11-23:

| Field | Value | Source |
|---|---|---|
| Market | Will Anthropic close below its IPO price by November 27, 2026? | `GET /markets/{id}` |
| Pool | 500 pUSD/day | `rewards_config[0].rate_per_day` |
| Minimum qualifying size | 20 shares a side | `rewards_min_size` |
| Reward band | 6.5 cents from the midpoint | `rewards_max_spread` |
| Competition | 2.09 | `market_competitiveness` |
| Midpoint | 0.325 | `GET /midpoint` |

Our quote, two 20-share bids at a 1.28 cent half-spread:

- our `Q_min` per side: `((6.5 - 1.28) / 6.5)² * 20` = 25.8
- our share: `25.8 / (25.8 + 2.09)` = **92.5%**
- expected reward: **≈ 462 pUSD/day**

The spread barely moves it. At 3 cents the share is still 85%, because the
competition in this market is thin enough that our own size dominates.

The capital fits: 20 shares of each leg at 0.325 and 0.675 reserves
20.0 pUSD, against 23.37 pUSD on the account.

## What has actually been earned

Nothing. Checked three ways on 2026-11-23:

- `GET /rewards/user/total` returns `[]` for 2026-11-21, 11-22 and 11-23.
- `GET /rewards/user/percentages` returns `{}`.
- Every row of `GET /rewards/user/markets` shows `earning_percentage` 0 and
  `earnings` 0.

That is consistent with the account's history rather than a bug: its 142
maker trades ran from 2026-08-13 to 2026-11-15, before the current pool
settings existed, and the 2026-11-20 rule change removed the maker-side
payout that used to apply below the volume tiers. The account also holds 18
redeemable leftovers from the temperature markets it traded in August.

## The balance changed, and this system did not do it

The collateral was 3.402804 pUSD on 2026-11-21 and is **23.368904 pUSD** now.
Confirmed two ways: `GET /balance-allowance?signature_type=1` returns
`23368904` (six decimals), and the pUSD balance of the proxy wallet
`0x6F7D43A8…` on Polygon reads the same.

This system placed no orders, and it could not have: the journal records
13,296 order intents and zero fills, `GET /data/orders` is empty, and
`GET /data/trades` shows the account's last trade on 2026-11-15, before this
system was deployed. The balance arrived from outside the trading path.

The change is welcome, because it clears the bar from decision 0001: 23.37 pUSD
funds a 20-share pair where 3.40 did not. It does not clear the bar for a
50-share pair (about 46 pUSD) or a 100-share pair (about 92 pUSD), so the
pools with the highest rates are still out of reach.

## What is still missing: the signing key

Order placement is still refused, for the reason in decision 0003. The
account is a legacy `POLY_PROXY` wallet and the exchange now wants a version
2 order whose maker is a deposit wallet and whose signer is the API key's
address. Every shape we can sign from this machine is rejected:

| Shape | Response |
|---|---|
| v1 order, `signature_type=1` | `maker is required` |
| v2 order, `signature_type=0/1/2` | `maker address not allowed, please use the deposit wallet flow` |
| v2 order, `signature_type=3` | `the order signer address has to be the address of the API KEY` |

So the reward is currently a paper number. The 18 hours of collection the
operator asked for produces the evidence that says *whether* the strategy
works; it cannot produce a paid reward until one of these is true:

1. **The owner key of `0x18af…` is obtained**, and the account is migrated to
   the deposit-wallet flow; or
2. **A session signer is authorized** on a deposit wallet belonging to the
   account. The authorization needs the owner's signature or a Relayer API
   key bound to the owner's address. We have that key
   (`019f2d27-…`, confirmed live against `GET /relayer/api/keys`, bound to
   `0x18af…`), and the unified SDK's `authorize_session_key` takes exactly
   this combination: a signer for the deposit wallet plus a Relayer API key.
   The signer still has to be a key we hold, and the deposit wallet has to
   exist for `0x18af…`; `GET /deployed?type=WALLET` says it does not, so the
   wallet has to be created first, which is the same owner-signature
   problem.

**A note on the owner key.** The browser profile holds a private key,
`4ceb4b9b…`, which derives to `0xb8b91b98…`, a different account with a
deposit wallet of its own and no balance. The funded account's owner key is
not in the browser profile, not in the workspace, and not in the deployment
environment.

## What the 18-hour run will produce

The paper service has run since 2026-11-21 and has collected 7,772 cycles
and 13,296 intents. The corrected selection and spread are live from
2026-11-23. What the run measures, and what it cannot:

| It measures | It cannot measure |
|---|---|
| Whether our quotes sit where the book's participants are | Whether the reward is actually paid out |
| How often a paired fill would occur | The realised maker rebate, which is zero below the volume tiers |
| The inventory drift a one-sided fill would cause | Anything requiring a signed order |

The one thing it does settle is the pair invariant: whether the two legs can
be quoted so that both fill and merge back above cost.
