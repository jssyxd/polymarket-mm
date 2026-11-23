# Decision 0002 — The reward band caps the spread, it does not set it

Date: 2026-11-21
Status: accepted

## What was decided

`pmm.pricing.quotes.build_quotes` treats `rewards_max_spread` as a **ceiling**
on the half-spread, not a floor.

## Why

The venue pays a liquidity reward only for orders that rest inside its
`rewards_max_spread` band around the midpoint. From the research in
`.research/poly-platform.md` §2 and §10.5:

> `rewards_max_spread` — the band inside which a resting order scores.
> An order outside the band scores zero.

A band that is scored inside is a ceiling by definition. Treating it as a
floor pushes every quote out to 80 percent of the band, which:

1. **Earns almost nothing.** The venue's score is
   `S = ((v - s) / v)²`, so a quote at `s = 0.8v` scores
   `((0.2v)/v)² = 0.04` of a maximum quote, a 25-fold loss against a quote
   at one tick inside the band.
2. **Gives away the spread.** The strategy's profit is the pair:
   `bid_up + bid_down` bought below 1 pUSD. Widening the spread to the band
   edge shrinks that margin for nothing.
3. **Does not even fit the band.** The widening term
   `half_spread = base * (1 + 0.5 * sigma_p * sqrt(tau))` grows with the
   square root of the time to resolution. On a market with a week left it
   pushes the half-spread past the band entirely, so the quote earns zero
   reward while looking like it is aimed at the band.

The observed failure was concrete. A live dry-run cycle on a market with a
4.5 cent band produced a half-spread of 6.4 cents, outside the band, so the
quote would have scored zero reward on the pool it was selected for.

## What changed

The floor is now the requested operating spread, at least one tick. The
ceiling is `min(20 cents, 0.8 * rewards_max_spread)`. The widened spread is
pulled back inside it and the reason string records it.

The requested spread wider than the band is honoured, and recorded, because
a deliberately wide quote is a spread-capture quote and not a reward quote.
That case needs the operator's intent, not a silent clamp.

## What this means for the parameter file

The hourly agent widens `half_spread_cents` by one cent when a market has
not filled in an hour, and the agent already refuses to widen past
`max_spread_cents`. With the ceiling in place, the agent's widening now
stays inside the band by construction, so the reward score degrades
gracefully as the spread widens instead of dropping to zero at the edge.

## What was checked

- The scoring formula and the band semantics, from
  `.research/poly-platform.md` §2, sourced to
  https://docs.polymarket.com/programs/liquidity-rewards.md.
- The live dry-run cycle that produced the 6.4 cent half-spread against a
  4.5 cent band.
- `tests/test_pricing.py` now asserts the ceiling, that the quote stays
  inside the band under a long horizon and a large sigma, and the worked
  example's new numbers.
