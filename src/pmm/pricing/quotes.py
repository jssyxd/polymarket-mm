"""Quote construction for a binary YES/NO pair, in probability space.

A maker on this venue buys both legs of the pair. Buying the UP token at
``p_up`` and the DOWN token at ``p_down`` costs ``p_up + p_down``, and a
complete set redeems for 1 pUSD, so a pair bought below 1 is worth the
difference no matter which way the event resolves. That paired gain is the
engine's actual profit source; the directional risk of holding one leg is
managed by the inventory skew.

Everything in this module is a pure function of its arguments. There is no
clock read, no network call, and no shared state.

Units. Prices are probabilities in (0, 1). Spreads that the venue expresses in
cents are converted on entry. The tick size is the venue's price grid.
"""

from __future__ import annotations

import math
import time
from dataclasses import dataclass

__all__ = [
    "Inventory",
    "Quote",
    "QuoteSide",
    "build_quotes",
    "round_down_to_tick",
    "round_up_to_tick",
]

#: Hard cap on the half-spread, in probability units (20 cents).
MAX_HALF_SPREAD = 0.20


@dataclass(frozen=True)
class QuoteSide:
    """One resting order.

    Attributes:
        token_id: Venue token identifier for the leg.
        price: Limit price in probability units.
        size: Order size in shares.
        is_buy: True for a resting bid.
    """

    token_id: str
    price: float
    size: float
    is_buy: bool


@dataclass(frozen=True)
class Quote:
    """A two-sided quote on one binary market.

    Attributes:
        up: The resting order on the UP token.
        down: The resting order on the DOWN token.
        reason: Human-readable note on how the quote was shaped.
        fair_prob: The clamped fair probability used for the UP leg.
        half_spread: Half-spread in probability units.
        expires_at: Epoch seconds at which the market resolves.
    """

    up: QuoteSide
    down: QuoteSide
    reason: str
    fair_prob: float
    half_spread: float
    expires_at: float


@dataclass
class Inventory:
    """Current maker inventory across the two legs of one market.

    Attributes:
        up_shares: Shares held of the UP token.
        down_shares: Shares held of the DOWN token.
        max_inventory_per_side: Inventory box, per leg, in shares.
    """

    up_shares: float = 0.0
    down_shares: float = 0.0
    max_inventory_per_side: float = 0.0

    @property
    def net_shares(self) -> float:
        """Signed position, positive when long the UP leg."""
        return self.up_shares - self.down_shares

    @property
    def unpaired_shares(self) -> float:
        """Shares held on one leg with no offsetting share on the other."""
        return self.up_shares if self.up_shares > self.down_shares else self.down_shares

    @property
    def paired_shares(self) -> float:
        """Shares held on both legs that can be merged."""
        return min(self.up_shares, self.down_shares)


def round_down_to_tick(price: float, tick_size: float) -> float:
    """Round a bid down onto the venue's price grid."""
    if tick_size <= 0.0:
        raise ValueError(f"tick_size must be positive: {tick_size}")
    steps = math.floor(price / tick_size + 1e-9)
    return round(steps * tick_size, 10)


def round_up_to_tick(price: float, tick_size: float) -> float:
    """Round an ask up onto the venue's price grid."""
    if tick_size <= 0.0:
        raise ValueError(f"tick_size must be positive: {tick_size}")
    steps = math.ceil(price / tick_size - 1e-9)
    return round(steps * tick_size, 10)


def build_quotes(
    fair_prob: float,
    sigma_p: float,
    tau_seconds: float,
    tick_size: float,
    min_size: float,
    inventory: Inventory,
    half_spread_cents: float | None = None,
    reward_max_spread_cents: float | None = None,
    min_reward_size: float = 0.0,
    gamma: float = 0.15,
) -> Quote:
    """Build a two-sided quote on a binary market.

    The two legs are resting bids on the UP and DOWN tokens. Their sum is
    kept at or below ``1 - tick_size`` so that a paired fill always leaves a
    mergeable complete set worth strictly more than the pair cost.

    Construction order, which the rules below depend on:

    1. ``fair_prob`` is clamped into ``[tick_size, 1 - tick_size]``.
    2. The half-spread floor is
       ``max(half_spread_cents/100, reward_max_spread_cents/100 * 0.8)``,
       with a one-tick minimum.
    3. The floor is widened for time and volatility:
       ``base * (1 + 0.5 * sigma_p * sqrt(tau_seconds))``, capped at 20 cents
       and never below the floor.
    4. The inventory skew shifts the reservation probability by
       ``q * gamma * sigma_p**2 * sqrt(tau_seconds)`` where
       ``q = net_shares / max_inventory_per_side`` clamped to (-1, 1). A long
       UP position lowers the reservation probability, which lowers the UP bid
       and raises the DOWN bid, so the quote leans toward flattening.

       Magnitude caveat. ``sigma_p`` is a probability-space vol per
       sqrt(second), so the shift is small in absolute probability terms: at
       ``sigma_p = 0.0009`` and ``tau = 600`` it is about 3e-6 of probability,
       far below one tick, and the skew then only shows up where the price
       sits near a tick boundary. It bites when ``sigma_p`` is large, which
       is the near-expiry or high-volatility regime. ``gamma`` is the knob
       that scales it if the maker wants the lean to be visible earlier.
    5. Prices are rounded onto the tick grid, downward for bids.
    6. If the two bids would sum above ``1 - tick_size``, the UP bid is
       reduced a tick at a time until the invariant holds.
    7. Size is ``max(min_size, min_reward_size)`` when ``min_reward_size`` is
       positive, otherwise ``min_size``.
    8. A leg at or beyond the inventory box is quoted at size zero.

    Args:
        fair_prob: Fair probability of the UP outcome.
        sigma_p: Probability-space vol per sqrt(second).
        tau_seconds: Time remaining to resolution.
        tick_size: Venue price grid.
        min_size: Minimum order size in shares.
        inventory: Current inventory and box.
        half_spread_cents: Optional explicit half-spread floor, in cents.
        reward_max_spread_cents: Venue reward spread cap, in cents.
        min_reward_size: Venue reward minimum size, in shares.
        gamma: Inventory skew strength.

    Returns:
        The quote, with a reason string describing every adjustment applied.
    """
    if not 0.0 <= fair_prob <= 1.0:
        raise ValueError(f"fair_prob must be in [0, 1]: {fair_prob}")
    if tick_size <= 0.0:
        raise ValueError(f"tick_size must be positive: {tick_size}")
    if sigma_p < 0.0:
        raise ValueError(f"sigma_p must be non-negative: {sigma_p}")
    if tau_seconds <= 0.0:
        raise ValueError(f"tau_seconds must be positive: {tau_seconds}")
    if tick_size > 0.5:
        raise ValueError(f"tick_size must be at most 0.5: {tick_size}")

    reasons: list[str] = []

    # 1. Clamp the fair probability onto the tradable band.
    clamped_prob = min(max(fair_prob, tick_size), 1.0 - tick_size)
    if abs(clamped_prob - fair_prob) > 1e-12:
        reasons.append(f"fair_prob_clamped_from_{fair_prob:.6f}")

    # 2. Half-spread floor and ceiling.
    # The floor is the operating spread the caller asked for, at least one
    # tick. The reward band is a CEILING, not a floor: the venue pays a
    # liquidity reward only for orders inside ``rewards_max_spread`` of the
    # midpoint, so a quote wider than the band earns nothing at all. Using
    # the band as a floor would push every quote to the band edge and give
    # up the spread capture the strategy is built on.
    floor = (half_spread_cents / 100.0) if half_spread_cents is not None else 0.0
    if floor < tick_size:
        floor = tick_size
        reasons.append("half_spread_floor_raised_to_one_tick")

    ceiling = MAX_HALF_SPREAD
    if reward_max_spread_cents is not None:
        band_ceiling = reward_max_spread_cents / 100.0 * 0.8
        if band_ceiling < ceiling:
            ceiling = band_ceiling
    if ceiling < floor:
        # The caller asked for a spread wider than the band. Pull it back to
        # the band instead of honouring the request: a quote at the band edge
        # scores exactly zero, because the score is ((v - s) / v) squared and
        # s = v gives zero. A wide quote that earns nothing is worse than a
        # narrower quote that earns something.
        floor = ceiling
        reasons.append("half_spread_clamped_to_reward_band")

    # 3. Widen for time and volatility, then pull back inside the ceiling.
    base = max(floor, tick_size)
    half_spread = base * (1.0 + 0.5 * sigma_p * math.sqrt(tau_seconds))
    if half_spread > ceiling:
        half_spread = ceiling
        reasons.append("half_spread_capped_at_reward_band")
    if half_spread < floor:
        half_spread = floor

    # 4. Inventory skew on the reservation probability.
    max_inv = inventory.max_inventory_per_side
    if max_inv > 0.0:
        q = inventory.net_shares / max_inv
    else:
        q = 0.0
    q = min(max(q, -1.0), 1.0)
    skew = q * gamma * (sigma_p**2) * math.sqrt(tau_seconds)
    reservation = clamped_prob - skew
    reservation = min(max(reservation, tick_size), 1.0 - tick_size)
    if abs(skew) > 0.0:
        reasons.append(f"inventory_skew_{skew:+.8f}")

    # 5. Prices onto the grid, downward for bids.
    up_bid = round_down_to_tick(reservation - half_spread, tick_size)
    down_bid = round_down_to_tick((1.0 - reservation) - half_spread, tick_size)
    if up_bid < 0.0:
        up_bid = 0.0
    if down_bid < 0.0:
        down_bid = 0.0

    # 6. Keep the pair mergeable. The DOWN bid alone is always below the cap,
    # since it sits at most 1 - tick_size - half_spread, so reducing the UP bid
    # is always enough.
    max_pair = 1.0 - tick_size
    reduced_up = False
    while up_bid + down_bid > max_pair + 1e-12 and up_bid > 0.0:
        up_bid = round_down_to_tick(up_bid - tick_size, tick_size)
        reduced_up = True
    if reduced_up:
        reasons.append("up_bid_reduced_for_pair_invariant")

    # 7. Size.
    if min_reward_size > 0.0:
        size = max(min_size, min_reward_size)
    else:
        size = min_size

    up_size = size
    down_size = size

    # 8. Inventory box.
    if max_inv > 0.0:
        if inventory.up_shares >= max_inv:
            up_size = 0.0
            reasons.append("up_leg_at_inventory_box")
        if inventory.down_shares >= max_inv:
            down_size = 0.0
            reasons.append("down_leg_at_inventory_box")

    if up_bid <= 0.0:
        up_size = 0.0

    return Quote(
        up=QuoteSide(token_id="", price=up_bid, size=up_size, is_buy=True),
        down=QuoteSide(token_id="", price=down_bid, size=down_size, is_buy=True),
        reason=";".join(reasons),
        fair_prob=clamped_prob,
        half_spread=half_spread,
        expires_at=time.time() + tau_seconds,
    )
