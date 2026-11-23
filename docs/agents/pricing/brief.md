# Task: build the binary-market pricing engine

Read `/home/da/.agents/skills/poteto-mode/SKILL.md` in full, including its Principles section, before any work.

## Context

We are building a Polymarket market-making system. The target venue is a binary CLOB: each market is a YES/NO pair in (0,1), one token per outcome, and the two tokens of one market are complements. The existing upstream repos (`GLFTmm/`, `asgrid-mm/`) hold the maker engine we are porting, and the research in `/home/da/桌面/polymarketMM/.research/` describes the platform and the two codebases.

Read first:
- `/home/da/桌面/polymarketMM/.research/poly-platform.md` sections 3, 4, 6, 9 (order mechanics, up/down markets, traps)
- `/home/da/桌面/polymarketMM/.research/glft-dive.md` sections 2, 6 (what the GLFT math actually does, what breaks for a binary)
- `/home/da/桌面/polymarketMM/.research/asgrid-dive.md` sections 2, 9, 10

The upstream pricing code is a trap. `shared/glft_engine/glft_solver.py` computes half-spreads that are pinned by a constant minimum-spread hurdle and whose inventory term is numerically inert. Do not port it. Write a new engine in probability space.

## What to build

You own exactly these files and no others:

- `src/pmm/pricing/__init__.py`
- `src/pmm/pricing/probability.py` — fair probability from an external spot signal
- `src/pmm/pricing/quotes.py` — quote construction with a hard expiry term
- `src/pmm/pricing/pairing.py` — the paired-bid arithmetic that is the actual profit source
- `tests/test_pricing.py`
- `tests/test_pairing.py`

## Requirements

### `probability.py`
`FairProbability` dataclass: `prob` (0..1), `sigma_p` (probability-space vol per sqrt(second)), `tau_seconds` (to expiry), `strike` (the reference price at window start), `spot`, `method`.

- `black_scholes_digital_prob(spot, strike, sigma_sqrt_second, tau_seconds) -> tuple[float, float]` — returns `(prob, sigma_p)`. Use the risk-neutral zero-drift digital formula `N(d2)` with `d2 = (ln(spot/strike) - 0.5*sigma^2*tau) / (sigma*sqrt(tau))`, and `sigma_p = phi(d2) / sqrt(tau)` expressed per sqrt(second) when `sigma_sqrt_second` is per sqrt(second). Use `math.erf` for the normal CDF, no SciPy.
- `implied_prob_from_book(book: dict) -> float` — mid of the top of book, fallback 0.5 on an empty book.
- `probability_space_vol(spot, strike, tau_seconds, confidence=2.0) -> float` — a per-sqrt-second vol estimate from the distance between spot and strike, so the engine still prices when no external vol feed exists. Clamp to `[1e-6, 0.05]` per sqrt(second). Document the clamp in the docstring.

### `quotes.py`
- `QuoteSide` dataclass: `token_id`, `price`, `size`, `is_buy`.
- `Quote` dataclass: `up` (QuoteSide), `down` (QuoteSide), `reason` (str), `fair_prob`, `half_spread`, `expires_at`.
- `Inventory` dataclass: `up_shares`, `down_shares`, `max_inventory_per_side`. Property `net_shares` = up - down, `unpaired_shares` = up if up>down else down, `paired_shares` = min(up,down).
- `build_quotes(fair_prob: float, sigma_p: float, tau_seconds: float, tick_size: float, min_size: float, inventory: Inventory, half_spread_cents: float | None = None, reward_max_spread_cents: float | None = None, min_reward_size: float = 0.0, gamma: float = 0.15) -> Quote`

Rules, all in this order:
1. Clamp `fair_prob` to `[tick_size, 1 - tick_size]`.
2. Half-spread floor: `max(half_spread_cents/100, reward_max_spread_cents/100 * 0.8 if reward_max_spread_cents else 0)`, with a one-tick minimum.
3. Half-spread widens with time-to-expiry and volatility: `half_spread = base * (1 + 0.5 * sigma_p * sqrt(tau_seconds))`, capped at 0.20 (20 cents), never below the floor from step 2.
4. Inventory skew: with `q = inventory.net_shares / inventory.max_inventory_per_side` in (-1, 1), shift the reservation probability by `q * gamma * sigma_p**2 * sqrt(tau_seconds)`, then clamp back into `[tick_size, 1-tick_size]`. The skew must reduce the up bid and raise the down bid when long up, so the quotes lean toward flattening inventory.
5. Prices are rounded to the tick, downward for bids and upward for asks, so a quote never crosses.
6. The two bid prices must satisfy `up_bid + down_bid <= 1 - tick_size`. If they do not, reduce the up bid by ticks until they do, and record that in `reason`.
7. `size` per side is `max(min_size, min_reward_size)` when `min_reward_size > 0`, else `min_size`.
8. If the inventory box is breached on one side, that side's quote size is 0 and the reason says so.

### `pairing.py`
This is the part the whole system rests on. Write it precisely and document the arithmetic in the module docstring.
- `paired_fill_pnl(bid_up: float, bid_down: float) -> float` — if both bids fill, you bought a complete set for `bid_up + bid_down` and can merge it back to 1 pUSD. Return `1 - (bid_up + bid_down)` per share pair. This is the profit that does not depend on direction.
- `unpaired_fill_exposure(bid_up: float, fill_price: float, shares: float) -> float` — the loss if only one side fills and the market goes to zero: `shares * fill_price`.
- `expected_net_bps(bid_up, bid_down, p_both_fill, up_fill_price, up_fill_shares, down_fill_price, down_fill_shares) -> float` — combine the paired gain and the two unpaired exposures into a net figure expressed in basis points of the notional traded. Document the formula.
- `merge_arbitrage_threshold(tick_size: float, gas_cost_per_pair: float, fee_per_pair: float) -> float` — the minimum half-spread in cents at which a paired fill still covers merge gas and fees: `2*half_spread >= gas_cost_per_pair + fee_per_pair`.

## Verification
```
cd /home/da/桌面/polymarketMM/polymarket-mm
python3 -m pytest tests/test_pricing.py tests/test_pairing.py -q
```
Tests must cover: the N(d2) formula against a hand-computed value, tick rounding, the `up_bid + down_bid <= 1 - tick` invariant, the inventory skew direction, the paired-fill PnL identity, and the expected-net-bps sign in the one-sided-fill case.

No network in tests. No credentials. Python 3.11+.

## Constraints
- Do not create or modify any file outside the list above.
- `src/pmm/data/`, `src/pmm/execution/`, `src/pmm/risk/`, `src/pmm/monitor/`, `deploy/`, and `tools/` belong to other workers.
- Standard library only.

## Report
Reply with the test result and the numbers from a small worked example: fair prob 0.52, sigma_p 0.0009, tau 600 s, tick 0.01, min_size 5, reward_max_spread 4.5, inventory 0/0. Show the two bid prices, the half-spread, and the paired PnL per share.

---
Role: implementer
Working directory: /home/da/桌面/polymarketMM
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.
