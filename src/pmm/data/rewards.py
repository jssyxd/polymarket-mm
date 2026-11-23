"""Official Polymarket liquidity-reward scoring.

Implements the published methodology
(https://docs.polymarket.com/programs/liquidity-rewards.md) as of 2026-11-21.

The in-game multiplier ``b`` is 1 on every market we quote, so it is omitted.

Units used throughout:

* ``max_spread_cents`` and ``spread_cents`` are cents. The CLOB value
  ``rewards_max_spread`` of ``4.5`` means 4.5 cents.
* Sizes are shares.
* Midpoints are dollars in ``[0, 1]``.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

#: Scaling factor ``c`` from the methodology. Single-sided liquidity scores at
#: ``Q / c`` when the midpoint is inside the ``[0.10, 0.90]`` band.
SCALING_FACTOR = 3.0

#: Midpoints inside this band let single-sided liquidity score at ``Q / c``.
#: Outside it, liquidity must be double-sided to score at all.
SINGLE_SIDED_BAND = (0.10, 0.90)


@dataclass(frozen=True)
class Level:
    """One price level of a book, expressed relative to its midpoint.

    ``spread_cents`` is the absolute distance from the midpoint in cents and
    ``size`` is the share-denominated quantity resting there.
    """

    spread_cents: float
    size: float


@dataclass(frozen=True)
class Book:
    """The two sides of one book, in midpoint-relative terms."""

    bids: tuple[Level, ...] = ()
    asks: tuple[Level, ...] = ()


def order_score(max_spread_cents: float, spread_cents: float) -> float:
    """Order position scoring function ``S(v, s) = ((v - s) / v) ** 2``.

    ``max_spread_cents`` is ``v`` and ``spread_cents`` is ``s``. Orders outside
    the qualifying spread score zero.
    """
    if max_spread_cents <= 0:
        return 0.0
    if spread_cents > max_spread_cents:
        return 0.0
    return ((max_spread_cents - spread_cents) / max_spread_cents) ** 2


def _side_score(levels: Iterable[Level], max_spread_cents: float) -> float:
    return sum(order_score(max_spread_cents, level.spread_cents) * level.size for level in levels)


def q_one(market: Book, complement: Book, max_spread_cents: float) -> float:
    """First market side score.

    ``Q_one = S(v, Spread_m1) * BidSize_m1 + ... + S(v, Spread_m'1) * AskSize_m'1``
    """
    return _side_score(market.bids, max_spread_cents) + _side_score(
        complement.asks, max_spread_cents
    )


def q_two(market: Book, complement: Book, max_spread_cents: float) -> float:
    """Second market side score.

    ``Q_two = S(v, Spread_m1) * AskSize_m1 + ... + S(v, Spread_m'1) * BidSize_m'1``
    """
    return _side_score(market.asks, max_spread_cents) + _side_score(
        complement.bids, max_spread_cents
    )


def q_min(q_one: float, q_two: float, midpoint: float) -> float:
    """Minimum of the two side scores, with the single-sided adjustment.

    Inside the ``[0.10, 0.90]`` band a single-sided quote still scores, at
    ``Q / c``. Outside the band only double-sided liquidity scores.
    """
    low, high = SINGLE_SIDED_BAND
    if low <= midpoint <= high:
        return max(min(q_one, q_two), max(q_one, q_two) / SCALING_FACTOR)
    return min(q_one, q_two)


def normalize(scores: Sequence[float]) -> list[float]:
    """Divide each score by the sum of all scores in the sample."""
    total = sum(scores)
    if total <= 0:
        return [0.0] * len(scores)
    return [score / total for score in scores]


def epoch_score(samples: Sequence[Sequence[float]], maker_index: int = 0) -> float:
    """Epoch score of one maker: the sum of its normalized per-sample scores.

    ``samples[u]`` holds the ``Q_min`` of every maker in sample ``u``.
    """
    total = 0.0
    for sample in samples:
        normalized = normalize(sample)
        if 0 <= maker_index < len(normalized):
            total += normalized[maker_index]
    return total


def final_share(epoch_scores: dict[str, float]) -> dict[str, float]:
    """Divide each epoch score by the sum of all epoch scores."""
    total = sum(epoch_scores.values())
    if total <= 0:
        return {name: 0.0 for name in epoch_scores}
    return {name: score / total for name, score in epoch_scores.items()}
