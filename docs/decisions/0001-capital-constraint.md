# Decision 0001 — The account's capital cannot fund a qualifying quote

Date: 2026-11-21
Status: accepted

## What was decided

The maker's capital model uses the **sum of both legs**, not the price of the
cheaper leg, and the candidate selector filters on the corrected number.

## Why

`pmm.data.universe` originally computed a candidate's notional as
`min_size * min(p_up, p_no)`. That is the price of one leg's qualifying
size. It understates what the account must have, by roughly half.

The reason is the venue's balance rule. From the official order-lifecycle
documentation
(https://docs.polymarket.com/concepts/order-lifecycle):

> Order size is limited by your available balance minus any amounts reserved
> by existing open orders.
>
> maxOrderSize = balance − Σ(openOrderSize − filledAmount)

and from the place-orders reference
(https://docs.polymarket.com/trading/place-orders):

> **Balance** — Sufficient pUSD for buys or outcome tokens for sells

Every resting buy reserves its collateral. The maker rests **two** bids per
market, one on each leg, so both reserve at once. The two legs are
complementary, so `p_up + p_no ≈ 1` and a pair of size `S` commits about
`S` pUSD, not `S * min(p_up, p_no)`.

## What the corrected model implies for this account

The funded account holds **3.402804 pUSD** (verified against
`GET /balance-allowance?asset_type=COLLATERAL&signature_type=1` and against
the pUSD balance of the proxy wallet `0x6F7D43A8…` on Polygon).

The venue's minimum order size is **5 shares** (verified live: `mos: 5` on
every sampled market).

| Quote | Collateral reserved | Affordable on 3.402804 pUSD? |
|---|---|---|
| One 5-share bid at 0.50 | 2.50 pUSD | yes |
| A 5+5 pair at 1.0c half-spread | ≈ 4.90 pUSD | **no** |
| A 5+5 pair at 4.5c half-spread | ≈ 4.55 pUSD | **no** |
| A reward-qualifying 20+20 pair | ≈ 18.4 pUSD | **no** |
| A reward-qualifying 50+50 pair | ≈ 46.0 pUSD | **no** |

So with the balance as it stands today, the account cannot rest a
venue-legal two-sided quote at all: even the minimum-size pair needs about
4.6 to 4.9 pUSD against 3.40 available. It can rest one leg of a minimum
order, which is exactly the position the plan exists to avoid, because a
single filled leg is naked directional inventory.

The reward pools need more still. `rewards_min_size` is 20 on 381 of the
7,833 reward markets, 50 on 27, 100 on 31, 200 on 10, and 1,000 on 4. A
reward-qualifying pair costs about `min_size` pUSD of collateral.

## What this means for the plan

Lane A as written assumed a capital budget that this account does not have.
Three ways forward, in the order they should be tried:

1. **Raise the account's balance.** The smallest viable figure is about
   5 pUSD, to rest one minimum-size pair, and about 20 pUSD to qualify for
   the cheapest reward pool. The two legs merge back into 1 pUSD per share
   pair, so the capital is committed rather than spent, and it recycles.
2. **Deposit into the account.** The proxy wallet holds the collateral, and
   the deposit wallet flow is the documented path for it.
3. **Re-scope the first live run to a single market** with the capital that
   exists, which after (1) or (2) means one market at the venue minimum
   size, and accept that the reward is zero until the size reaches
   `rewards_min_size`.

The dry-run and paper modes are unaffected: they need no balance, and they
are what the hourly tick learns from.

## What was checked

- `GET /balance-allowance?asset_type=COLLATERAL&signature_type=1` → balance
  `3402804` (six decimals), allowance unlimited to the CTF Exchange, the
  Neg-Risk Adapter, the Neg-Risk Exchange and ExchangeV3.
- `eth_call` of `balanceOf` on the pUSD token `0xC011a7E7…` for the proxy
  wallet → `0x33ec34` = 3.402804 pUSD.
- `GET /rewards/markets/current` over 7,833 markets → the `rewards_min_size`
  distribution in the table above.
- `GET /markets/{condition_id}` on 40 sampled reward markets →
  `minimum_order_size: 5` on every one.
- The balance reservation rule, quoted above, from the official docs.
