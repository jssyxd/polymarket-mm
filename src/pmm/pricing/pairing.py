"""Paired-bid arithmetic: where the maker's profit actually comes from.

A Polymarket binary is a pair of complementary tokens, UP and DOWN, and a
complete set of both redeems for exactly 1 pUSD. That identity is the whole
business:

    buy UP at p_u and DOWN at p_d  ->  cost p_u + p_d
    merge the complete set          ->  receive 1
    profit per share pair           =  1 - (p_u + p_d)

The profit does not depend on which way the event resolves. Only the
probability of getting there does, and that is what the two unpaired-exposure
terms price: if one leg fills and the other does not, the maker holds a naked
share that is worth 0 the moment the market resolves the other way, so the
loss on that leg is exactly what was paid for it.

Arithmetic, stated once so every function below is a restatement of it.

Let ``b_u`` and ``b_d`` be the quoted UP and DOWN bid prices, ``p`` the
probability that both legs fill, ``u_p, u_s`` the UP fill price and share
count, ``d_p, d_s`` the DOWN fill price and share count.

Paired gain per share pair:

    G = 1 - (b_u + b_d)

Unpaired exposure, the loss on a single leg when the market resolves
against it:

    exposure_up   = u_s * u_p
    exposure_down = d_s * d_p

Three mutually exclusive outcomes are weighted by probability.

Both legs fill, probability ``p``. The ``min(u_s, d_s)`` share pairs merge
for a gain of ``G`` each. Any excess shares on the larger leg have no hedge
and are charged their full stake, the same worst case the unpaired exposure
uses:

    pnl_both = min(u_s, d_s) * G - max(0, u_s - d_s) * u_p - max(0, d_s - u_s) * d_p
    notional_both = u_s * u_p + d_s * d_p

Only the UP leg fills. The stake is lost if the market resolves to zero:

    pnl_up     = -u_s * u_p
    notional_up = u_s * u_p

Only the DOWN leg fills, symmetric:

    pnl_down     = -d_s * d_p
    notional_down = d_s * d_p

The residual probability mass ``1 - p`` is split between the two one-sided
outcomes in proportion to the share count of each leg, ``w_u = u_s / (u_s +
d_s)`` and ``w_d = 1 - w_u``. That split is an assumption, not a
measurement: the joint fill probability is an input, the marginals are not
observable from it, and share count is the only weight available here.

Expected net PnL and expected traded notional:

    E_pnl      = p * pnl_both + (1 - p) * (w_u * pnl_up + w_d * pnl_down)
    E_notional = p * notional_both + (1 - p) * (w_u * notional_up + w_d * notional_down)
    net_bps    = E_pnl / E_notional * 10_000

A negative value means the quote loses money on expectation, which is the
signal to widen, or to stop quoting that leg. A pure one-sided fill is
exactly -10_000 bps of the notional actually traded, since the whole stake
is lost.
"""

from __future__ import annotations

__all__ = [
    "expected_net_bps",
    "merge_arbitrage_threshold",
    "paired_fill_pnl",
    "unpaired_fill_exposure",
]


def paired_fill_pnl(bid_up: float, bid_down: float) -> float:
    """Profit per share pair when both legs fill and the set is merged.

    You bought a complete set for ``bid_up + bid_down`` and merge it back for
    1 pUSD, so the profit per share pair is ``1 - (bid_up + bid_down)``.

    Args:
        bid_up: UP bid price in probability units.
        bid_down: DOWN bid price in probability units.

    Returns:
        The per-pair profit in pUSD. Positive when the pair was bought below
        its merge value.
    """
    return 1.0 - (bid_up + bid_down)


def unpaired_fill_exposure(bid_up: float, fill_price: float, shares: float) -> float:
    """Loss on a single leg when only that leg fills and the market goes to zero.

    The share was bought at ``fill_price`` and is worth 0 once the market
    resolves the other way, so the whole stake is the loss.

    Args:
        bid_up: UP bid price of the quote that produced the fill. Accepted so
            a caller can pass the paired leg's context alongside the fill; the
            loss itself depends only on the filled leg.
        fill_price: Price actually paid for the filled shares.
        shares: Number of shares filled.

    Returns:
        The exposure in pUSD, as a positive number.
    """
    return shares * fill_price


def expected_net_bps(
    bid_up: float,
    bid_down: float,
    p_both_fill: float,
    up_fill_price: float,
    up_fill_shares: float,
    down_fill_price: float,
    down_fill_shares: float,
) -> float:
    """Expected net PnL of a two-sided quote in basis points of notional traded.

    Combines the paired gain, which is direction independent, with the two
    unpaired exposures, which are the cost of the event resolving before the
    other leg fills.

    The formula, with ``p = p_both_fill``:

        pnl_both = min(u_s, d_s) * (1 - (b_u + b_d))
                   - max(0, u_s - d_s) * u_p - max(0, d_s - u_s) * d_p
        pnl_up = -u_s * u_p, pnl_down = -d_s * d_p
        w_u = u_s / (u_s + d_s), w_d = d_s / (u_s + d_s)
        E_pnl = p * pnl_both + (1 - p) * (w_u * pnl_up + w_d * pnl_down)
        E_notional = p * (u_s * u_p + d_s * d_p)
                     + (1 - p) * (w_u * u_s * u_p + w_d * d_s * d_p)
        net_bps = E_pnl / E_notional * 10_000

    Args:
        bid_up: UP bid price in probability units.
        bid_down: DOWN bid price in probability units.
        p_both_fill: Probability that both legs fill, in [0, 1].
        up_fill_price: Price paid for the UP shares when they fill.
        up_fill_shares: UP shares filled.
        down_fill_price: Price paid for the DOWN shares when they fill.
        down_fill_shares: DOWN shares filled.

    Returns:
        Net expected PnL in basis points of the notional traded. Zero when
        nothing is traded. Negative when one-sided fill risk dominates.
    """
    if not 0.0 <= p_both_fill <= 1.0:
        raise ValueError(f"p_both_fill must be in [0, 1]: {p_both_fill}")

    notional_both = up_fill_shares * up_fill_price + down_fill_shares * down_fill_price
    notional_up = up_fill_shares * up_fill_price
    notional_down = down_fill_shares * down_fill_price
    if notional_both <= 0.0:
        return 0.0

    paired_shares = min(up_fill_shares, down_fill_shares)
    excess_up = max(0.0, up_fill_shares - down_fill_shares)
    excess_down = max(0.0, down_fill_shares - up_fill_shares)

    pnl_both = paired_shares * paired_fill_pnl(bid_up, bid_down)
    pnl_both -= excess_up * up_fill_price + excess_down * down_fill_price
    pnl_up = -unpaired_fill_exposure(bid_up, up_fill_price, up_fill_shares)
    pnl_down = -unpaired_fill_exposure(bid_down, down_fill_price, down_fill_shares)

    total_shares = up_fill_shares + down_fill_shares
    if total_shares > 0.0:
        weight_up = up_fill_shares / total_shares
        weight_down = down_fill_shares / total_shares
    else:
        weight_up = 0.5
        weight_down = 0.5

    expected_pnl = p_both_fill * pnl_both + (1.0 - p_both_fill) * (
        weight_up * pnl_up + weight_down * pnl_down
    )
    expected_notional = p_both_fill * notional_both + (1.0 - p_both_fill) * (
        weight_up * notional_up + weight_down * notional_down
    )
    if expected_notional <= 0.0:
        return 0.0
    return expected_pnl / expected_notional * 10_000.0


def merge_arbitrage_threshold(
    tick_size: float,
    gas_cost_per_pair: float,
    fee_per_pair: float,
) -> float:
    """Minimum half-spread, in cents, at which a paired fill covers merge costs.

    A paired fill earns ``2 * half_spread`` per share pair, because both legs
    are quoted half a spread away from their own fair values and the two
    fair values sum to 1. The merge of the complete set then costs gas and
    fees, so the pair is worth merging only when

        2 * half_spread >= gas_cost_per_pair + fee_per_pair

    Args:
        tick_size: Venue price grid, in probability units (0.01 is one cent).
        gas_cost_per_pair: Gas cost of one merge, in cents per share pair.
        fee_per_pair: Venue fee of one merge, in cents per share pair.

    Returns:
        The threshold half-spread in cents. It is never below one tick, since
        a quote narrower than the price grid cannot be represented.
    """
    if tick_size <= 0.0:
        raise ValueError(f"tick_size must be positive: {tick_size}")
    tick_cents = tick_size * 100.0
    required = (gas_cost_per_pair + fee_per_pair) / 2.0
    return max(required, tick_cents)
