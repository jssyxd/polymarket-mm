"""Fair probability for a binary YES/NO pair from an external spot signal.

The venue prices a market as a pair of complementary tokens, each in (0, 1).
The maker's edge is not directional: the profit comes from buying both legs of
the pair cheaper than the 1 pUSD a merged complete set redeems for. Everything
here therefore lives in probability space, never in price-times-basis-points
units, and every function is pure and side-effect free.

Conventions used throughout the package:

* ``prob`` is the probability that the UP token resolves to 1.
* ``sigma_p`` is the volatility of that probability, per sqrt(second).
* ``tau_seconds`` is the time left to the resolution event.
* The strike is the reference price at the start of the window. For crypto
  up/down markets it is the Chainlink TWAP at the window start, which the
  public market metadata does not publish, so the maker reconstructs it from
  the TWAP stream.

Standard library only.
"""

from __future__ import annotations

import math
from dataclasses import dataclass

__all__ = [
    "FairProbability",
    "black_scholes_digital_prob",
    "implied_prob_from_book",
    "probability_space_vol",
]


@dataclass(frozen=True)
class FairProbability:
    """A fair probability estimate for one side of a binary pair.

    Attributes:
        prob: Fair probability of the UP outcome, in [0, 1].
        sigma_p: Volatility of the probability, per sqrt(second).
        tau_seconds: Time remaining until resolution.
        strike: Reference price at the start of the window.
        spot: Current external price signal.
        method: How the estimate was produced, for logging and audit.
    """

    prob: float
    sigma_p: float
    tau_seconds: float
    strike: float
    spot: float
    method: str

    def __post_init__(self) -> None:
        if not 0.0 <= self.prob <= 1.0:
            raise ValueError(f"prob out of range: {self.prob}")
        if self.sigma_p < 0.0:
            raise ValueError(f"sigma_p must be non-negative: {self.sigma_p}")
        if self.tau_seconds < 0.0:
            raise ValueError(f"tau_seconds must be non-negative: {self.tau_seconds}")


def _norm_cdf(x: float) -> float:
    """Standard normal CDF via ``math.erf`` (no SciPy)."""
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def _norm_pdf(x: float) -> float:
    """Standard normal PDF."""
    return math.exp(-0.5 * x * x) / math.sqrt(2.0 * math.pi)


def black_scholes_digital_prob(
    spot: float,
    strike: float,
    sigma_sqrt_second: float,
    tau_seconds: float,
) -> tuple[float, float]:
    """Risk-neutral zero-drift digital probability and its probability-space vol.

    The UP token pays 1 if the underlying finishes at or above the strike, so
    its price is the digital option value ``N(d2)`` with

        d2 = (ln(spot / strike) - 0.5 * sigma^2 * tau) / (sigma * sqrt(tau))

    and no drift term (the platform compares two TWAP observations, it does not
    pay a financing rate).

    The probability-space volatility is the density at the strike divided by
    the square root of the horizon, ``sigma_p = phi(d2) / sqrt(tau)``. Because
    ``phi`` is dimensionless and ``tau`` is in seconds, ``sigma_p`` comes out
    per sqrt(second), the same unit as ``sigma_sqrt_second``.

    Args:
        spot: Current external price signal, strictly positive.
        strike: Reference price at the start of the window, strictly positive.
        sigma_sqrt_second: Underlying volatility per sqrt(second).
        tau_seconds: Time remaining to resolution.

    Returns:
        ``(prob, sigma_p)``. A degenerate horizon or volatility collapses to the
        deterministic payoff: 1.0 when ``spot >= strike`` (the platform resolves
        a tie as UP), 0.0 otherwise, with ``sigma_p == 0.0``.
    """
    if spot <= 0.0:
        raise ValueError(f"spot must be positive: {spot}")
    if strike <= 0.0:
        raise ValueError(f"strike must be positive: {strike}")
    if sigma_sqrt_second < 0.0:
        raise ValueError(f"sigma_sqrt_second must be non-negative: {sigma_sqrt_second}")
    if tau_seconds < 0.0:
        raise ValueError(f"tau_seconds must be non-negative: {tau_seconds}")

    if tau_seconds == 0.0 or sigma_sqrt_second == 0.0:
        return (1.0 if spot >= strike else 0.0), 0.0

    sqrt_tau = math.sqrt(tau_seconds)
    sigma = sigma_sqrt_second
    d2 = (math.log(spot / strike) - 0.5 * sigma * sigma * tau_seconds) / (sigma * sqrt_tau)
    prob = _norm_cdf(d2)
    sigma_p = _norm_pdf(d2) / sqrt_tau
    return prob, sigma_p


def _book_prices(levels: object) -> list[float]:
    """Extract prices from one side of a CLOB book.

    Accepts the shape the venue serves (``[{"price": "0.51", "size": "10"}, ...]``)
    and the plain ``[[price, size], ...]`` shape some feeds use. Entries that
    carry no usable price are skipped rather than raising, because a partially
    malformed book should degrade to a worse mid, not to a crash.
    """
    if not isinstance(levels, (list, tuple)):
        return []
    prices: list[float] = []
    for level in levels:
        raw: object = None
        if isinstance(level, dict):
            raw = level.get("price")
        elif isinstance(level, (list, tuple)) and level:
            raw = level[0]
        if raw is None:
            continue
        try:
            price = float(raw)
        except (TypeError, ValueError):
            continue
        if 0.0 <= price <= 1.0:
            prices.append(price)
    return prices


def implied_prob_from_book(book: dict) -> float:
    """Midpoint of the top of book, the market's own implied probability.

    The UP token's book is quoted directly, so the midpoint between the best
    bid and the best ask on that token is the implied probability that the
    event resolves UP.

    Args:
        book: A CLOB book with ``bids`` and ``asks`` levels.

    Returns:
        The midpoint, or the level itself when only one side is present. An
        empty or unusable book returns 0.5, the fair value of a coin flip.
    """
    if not isinstance(book, dict):
        return 0.5

    bids = _book_prices(book.get("bids"))
    asks = _book_prices(book.get("asks"))

    best_bid = max(bids) if bids else None
    best_ask = min(asks) if asks else None

    if best_bid is None and best_ask is None:
        return 0.5
    if best_bid is None:
        return float(best_ask)
    if best_ask is None:
        return float(best_bid)
    return (best_bid + best_ask) / 2.0


def probability_space_vol(
    spot: float,
    strike: float,
    tau_seconds: float,
    confidence: float = 2.0,
) -> float:
    """Fallback probability-space vol per sqrt(second) derived from moneyness.

    The maker needs a volatility even when no external vol feed exists. The
    fallback is built from the distance between spot and strike, because that
    distance is what makes the outcome probability move.

    Method. The assumed one-sigma log move of the underlying over the window
    is ``REFERENCE_MOVE / confidence``, where ``REFERENCE_MOVE`` is 1 percent.
    That prior gives an underlying vol of ``REFERENCE_MOVE / (confidence *
    sqrt(tau))`` per sqrt(second), which is fed through the digital formula to
    get the density at the strike. The density is the probability-space
    sensitivity: an at-the-money market is the most sensitive and a market far
    from its strike is nearly insensitive, which is the behaviour the engine
    needs. The result is scaled to per sqrt(second) by dividing by
    ``sqrt(tau)``.

    ``confidence`` is the number of standard deviations the assumed reference
    move spans. A larger value means a quieter underlying and therefore a
    smaller probability-space vol.

    Clamp. The result is clamped to ``[1e-6, 0.05]`` per sqrt(second). The
    lower clamp keeps the quote arithmetic finite for a deep out-of-the-money
    market, where the digital density underflows to zero; the upper clamp
    stops an at-the-money market that is about to expire from producing a
    half-spread wider than the engine's own 20-cent cap.

    Args:
        spot: Current external price signal, strictly positive.
        strike: Reference price at the start of the window, strictly positive.
        tau_seconds: Time remaining to resolution, strictly positive.
        confidence: Standard deviations spanned by the assumed reference move.

    Returns:
        Probability-space vol per sqrt(second).
    """
    if spot <= 0.0:
        raise ValueError(f"spot must be positive: {spot}")
    if strike <= 0.0:
        raise ValueError(f"strike must be positive: {strike}")
    if tau_seconds <= 0.0:
        raise ValueError(f"tau_seconds must be positive: {tau_seconds}")
    if confidence <= 0.0:
        raise ValueError(f"confidence must be positive: {confidence}")

    reference_move = 0.01
    sigma = reference_move / (confidence * math.sqrt(tau_seconds))
    sqrt_tau = math.sqrt(tau_seconds)
    d2 = (math.log(spot / strike) - 0.5 * sigma * sigma * tau_seconds) / (sigma * sqrt_tau)
    sigma_p = _norm_pdf(d2) / sqrt_tau

    return min(max(sigma_p, 1e-6), 0.05)
