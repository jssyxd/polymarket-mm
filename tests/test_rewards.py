"""Tests for the liquidity-reward scoring formulas.

The worked example is the one published at
https://docs.polymarket.com/programs/liquidity-rewards.md
"""

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.data.rewards import (  # noqa: E402
    Book,
    Level,
    epoch_score,
    final_share,
    normalize,
    order_score,
    q_min,
    q_one,
    q_two,
)


def test_order_score_matches_quadratic_formula():
    # S(v, s) = ((v - s) / v) ** 2
    assert order_score(3.0, 1.0) == (2.0 / 3.0) ** 2
    assert order_score(3.0, 2.0) == (1.0 / 3.0) ** 2
    assert order_score(3.0, 3.0) == 0.0
    assert order_score(4.5, 0.0) == 1.0


def test_order_score_is_zero_outside_max_spread():
    assert order_score(3.0, 3.5) == 0.0
    assert order_score(3.0, 100.0) == 0.0


def test_q_one_worked_example_from_docs():
    """Step 2 of the published worked example.

    Max spread 3 cents, midpoint 0.50:
      100Q bid on m @ 1 cent spread
      200Q bid on m @ 2 cents spread
      100Q ask on m' @ 1 cent spread
    """
    market = Book(
        bids=(Level(spread_cents=1.0, size=100.0), Level(spread_cents=2.0, size=200.0)),
        asks=(),
    )
    complement = Book(
        bids=(),
        asks=(Level(spread_cents=1.0, size=100.0),),
    )

    expected = 100.0 * ((3.0 - 1.0) / 3.0) ** 2 + 200.0 * ((3.0 - 2.0) / 3.0) ** 2 + 100.0 * (
        (3.0 - 1.0) / 3.0
    ) ** 2

    assert q_one(market, complement, 3.0) == expected
    assert q_one(market, complement, 3.0) == 100.0 * 4 / 9 + 200.0 * 1 / 9 + 100.0 * 4 / 9


def test_q_two_worked_example_from_docs():
    """Step 3 of the published worked example.

    The doc numbers the three orders as spreads 1.5, 2 and 0.5 cents with
    sizes 100, 100 and 200. Equation 3 puts asks on the market and bids on
    the complement in Q_two, so the orders are placed on those sides here.
    """
    market = Book(bids=(), asks=(Level(spread_cents=1.5, size=100.0),))
    complement = Book(
        bids=(Level(spread_cents=2.0, size=100.0), Level(spread_cents=0.5, size=200.0)),
        asks=(),
    )

    expected = 100.0 * ((3.0 - 1.5) / 3.0) ** 2 + 100.0 * ((3.0 - 2.0) / 3.0) ** 2 + 200.0 * (
        (3.0 - 0.5) / 3.0
    ) ** 2

    assert q_two(market, complement, 3.0) == expected


def test_q_one_and_q_two_pick_opposite_sides():
    market = Book(
        bids=(Level(spread_cents=1.0, size=100.0),),
        asks=(Level(spread_cents=1.0, size=100.0),),
    )
    complement = Book(
        bids=(Level(spread_cents=1.0, size=100.0),),
        asks=(Level(spread_cents=1.0, size=100.0),),
    )

    # One order per side, all at one cent inside a three cent max spread.
    unit = ((3.0 - 1.0) / 3.0) ** 2 * 100.0
    assert q_one(market, complement, 3.0) == 2 * unit
    assert q_two(market, complement, 3.0) == 2 * unit


def test_q_min_uses_single_sided_adjustment_inside_the_band():
    # Inside [0.10, 0.90]: max(min(q1, q2), max(q1, q2) / 3)
    assert q_min(10.0, 3.0, 0.50) == 10.0 / 3.0
    assert q_min(10.0, 1.0, 0.50) == 10.0 / 3.0
    assert q_min(0.0, 9.0, 0.50) == 3.0
    assert q_min(6.0, 6.0, 0.10) == 6.0
    assert q_min(6.0, 6.0, 0.90) == 6.0


def test_q_min_requires_double_sided_outside_the_band():
    assert q_min(10.0, 3.0, 0.05) == 3.0
    assert q_min(10.0, 3.0, 0.95) == 3.0
    assert q_min(10.0, 3.0, 0.0) == 3.0
    assert q_min(10.0, 3.0, 1.0) == 3.0


def test_normalize_divides_by_the_sum():
    assert normalize([1.0, 3.0]) == [0.25, 0.75]
    assert normalize([]) == []
    assert normalize([0.0, 0.0]) == [0.0, 0.0]


def test_epoch_score_sums_normalized_per_sample_scores():
    samples = [[1.0, 3.0], [2.0, 2.0]]
    # sample 1: 0.25 + 0.75, sample 2: 0.5 + 0.5
    assert epoch_score(samples, maker_index=0) == 0.25 + 0.5
    assert epoch_score(samples, maker_index=1) == 0.75 + 0.5


def test_final_share_divides_by_the_total():
    shares = final_share({"a": 30.0, "b": 10.0})
    assert shares == {"a": 0.75, "b": 0.25}
    assert final_share({}) == {}
