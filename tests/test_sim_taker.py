"""The taker simulator values a cross-and-hold trade from the oracle, not the book."""

from __future__ import annotations

import math

from pmm.sim.taker import Quote, fair_probability, simulate, taker_edge


def test_the_fair_probability_is_a_half_at_the_money_and_monotone():
    assert abs(fair_probability(100, 100, 300, 0.5) - 0.5) < 1e-9
    up = fair_probability(100.5, 100, 300, 0.5)
    down = fair_probability(99.5, 100, 300, 0.5)
    assert 0.5 < up < 1 and 0 < down < 0.5
    assert math.isclose(up + down, 1.0, abs_tol=1e-3)


def test_the_edge_is_the_oracle_minus_the_ask():
    q = Quote(ts=0, token_id="T", bid=0.60, ask=0.62)

    assert math.isclose(taker_edge(0.70, q), 0.08)


def test_only_edges_above_the_threshold_are_taken():
    quote = Quote(ts=0, token_id="T", bid=0.60, ask=0.62)
    observations = [
        {"fair": 0.70, "quote": quote, "won": True},   # edge 0.08 -> taken, wins
        {"fair": 0.63, "quote": quote, "won": False},  # edge 0.01 -> skipped
    ]

    result = simulate(observations, min_edge=0.02, size=10)

    assert result.trades == 1
    assert result.wins == 1
    assert math.isclose(result.pnl, (1 - 0.62) * 10)


def test_losing_trades_are_counted_at_the_ask():
    quote = Quote(ts=0, token_id="T", bid=0.40, ask=0.45)

    result = simulate([{"fair": 0.55, "quote": quote, "won": False}], min_edge=0.02, size=10)

    assert result.trades == 1 and result.wins == 0
    assert math.isclose(result.pnl, -0.45 * 10)
