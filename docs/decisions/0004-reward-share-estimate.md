# Decision 0004 — The reward share is divided by the venue's own competition score

Date: 2026-11-23
Status: accepted

## What was decided

The expected share of a reward pool is computed as our own `Q_min` divided by
the venue's published `market_competitiveness`, not by a competition figure
rebuilt from the order book. The candidate list comes from
`/rewards/markets/multi`, and the market is selected by expected pUSD per day,
not by the pool's headline rate.

## Why

Two errors were found, both in the same place, and both made the system
mis-target the market.

**The competition figure was overstated by two orders of magnitude.** The
estimator summed `S(v,s) * size` over every book level, treating each level's
size as one maker's order. A book level aggregates every maker resting at
that price, so this counts the same liquidity many times over. Measured on
the same market at the same moment against the venue's own number:

| Market | Venue `market_competitiveness` | Our book-based figure |
|---|---|---|
| Lindsay Clancy (Google search) | 59.10 | 13,675 |
| Netanyahu out by end of 2026 | 34.31 | 59.26 with size capped at `min_size` |
| Xi Jinping out before 2027 | 3,162.64 | 1,997.33 with size capped |

Capping each level's size at `rewards_min_size` brings the estimate onto the
venue's scale (59.26 against 59.10 on the first market). The venue's own
number is the right one to use: it is the sum of every other maker's `Q_min`,
which is exactly the denominator the methodology divides by (equation 5).

**The market was picked by pool rate instead of by what we would earn.** The
runner sorted candidates by `rate_per_day` and took the largest. The market it
landed on had a 500 pUSD/day pool and a competition score high enough that a
20-share quote earned roughly nothing, and it produced 13,302 quote intents
over three days and zero fills. The markets with the best expected return
for a small maker are the ones nobody is quoting: the venue reports
`market_competitiveness` of 0 to 0.01 on several temperature markets paying
65 to 82 pUSD/day.

Sorting by expected pUSD per day, the selection changed from the 500 pUSD/day
crowded market to a market paying 82 pUSD/day with a competition score of
0.012, where a qualifying 20-share quote takes effectively the whole pool.

## What changed

- `pmm.data.clob.list_reward_markets_with_competition` reads
  `/rewards/markets/multi`, which carries the pool settings, the daily rate
  and `market_competitiveness` in one row. The list is sorted by rate
  descending, so one page of 500 covers every market paying at least 50
  pUSD/day, and every market a small maker can qualify for.
- `pmm.data.universe.score_candidate` takes the competition score and uses it
  as the denominator.
- `pmm.core.selection.expected_share` computes our own `Q_min` the same way
  the methodology does, and `select_targets` orders candidates by expected
  pUSD per day.

## The numbers it changes

With 20 shares a side at a 1 cent spread, on a market whose competition score
is 0.012:

- our `Q_min` per side: `((4.5 - 1) / 4.5)² * 20` = 12.1
- our share: `12.1 / (12.1 + 0.012)` ≈ 99.9%
- expected daily reward at an 82 pUSD/day pool: ≈ 82 pUSD/day

The same quote on the market the runner used to pick, with a competition
score of 34.3:

- our share: `12.1 / (12.1 + 34.3)` ≈ 26%
- expected daily reward at a 95 pUSD/day pool: ≈ 25 pUSD/day

## What this does not change

The reward is only paid if an order rests and the sampling clock sees it, and
the payout floor is 1 pUSD. The account has earned nothing so far:
`GET /rewards/user/total` returns an empty list for every date queried,
`GET /rewards/user/percentages` returns `{}`, and every row of
`GET /rewards/user/markets` shows `earning_percentage` 0 and `earnings` 0. The
account's 142 maker trades ran from 2026-08-13 to 2026-11-15, before the
current pool settings, and the venue's rebate rule change on 2026-11-20
removed the maker-side payout that used to apply below the volume tiers.

## The capital, again

The account's collateral is now **23.368904 pUSD**, confirmed by
`GET /balance-allowance?signature_type=1` and by the pUSD balance of the
proxy wallet `0x6F7D43A8…` on Polygon. It was 3.402804 pUSD on 2026-11-21. The
increase is not explained by anything this system did: the journal records
13,296 order intents and no fills, and the account made no order
(`GET /data/orders` is empty). The account's trade history stops at
2026-11-15, and its 18 positions are all redeemable leftovers of the
temperature markets it traded in August.

Whatever the source, the number now clears the bar set in decision 0001: a
20-share pair needs about 20 pUSD of reserved collateral, and 23.37 pUSD
covers it with a small margin. It does not clear the bar for a 50-share
pair (about 46 pUSD) or a 100-share pair (about 92 pUSD), so the reward pools
with `rewards_min_size` above 20 are still out of reach.
