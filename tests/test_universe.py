"""Tests for candidate scoring and selection."""

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.data.universe import (  # noqa: E402
    RewardCandidate,
    market_meta,
    score_candidate,
    select_candidates,
    size_cutoff_midpoint,
    updown_candidate,
)


def _book(bids, asks):
    return {
        "bids": [{"price": str(p), "size": str(s)} for p, s in bids],
        "asks": [{"price": str(p), "size": str(s)} for p, s in asks],
    }


def _market(**overrides):
    market = {
        "condition_id": "0xabc",
        "question": "Will it rain tomorrow?",
        "tokens": ["111", "222"],
        "prices": [0.60, 0.40],
        "min_size": 20.0,
        "max_spread_cents": 4.5,
        "rate_per_day": 100.0,
    }
    market.update(overrides)
    return market


def _candidate(**overrides):
    fields = {
        "condition_id": "0xabc",
        "question": "Will it rain tomorrow?",
        "tokens": ["111", "222"],
        "min_size": 20.0,
        "max_spread_cents": 4.5,
        "rate_per_day": 100.0,
        "midpoint": 0.60,
        "q_one": 10.0,
        "q_two": 10.0,
        "q_min": 10.0,
        "est_share_pct": 1.0,
        "notional_usd": 1.0,
    }
    fields.update(overrides)
    return RewardCandidate(**fields)


def test_score_candidate_computes_our_contribution():
    market = _market()
    book_a = _book([(0.59, 500)], [(0.61, 500)])
    book_b = _book([(0.39, 500)], [(0.41, 500)])

    candidate = score_candidate(market, book_a, book_b, 0.60, 0.40, 20.0, 1.0)

    # 1 cent spread inside a 4.5 cent max spread, 20 shares, each side counted
    # once per side of the pair.
    per_order = ((4.5 - 1.0) / 4.5) ** 2 * 20.0
    assert candidate.q_one == 2.0 * per_order
    assert candidate.q_two == 2.0 * per_order
    assert candidate.q_min == 2.0 * per_order
    assert candidate.midpoint == 0.60
    assert candidate.tokens == ["111", "222"]


def test_score_candidate_share_grows_with_our_size():
    market = _market()
    book_a = _book([(0.59, 500)], [(0.61, 500)])
    book_b = _book([(0.39, 500)], [(0.41, 500)])

    small = score_candidate(market, book_a, book_b, 0.60, 0.40, 20.0, 1.0)
    large = score_candidate(market, book_a, book_b, 0.60, 0.40, 200.0, 1.0)

    assert large.est_share_pct > small.est_share_pct
    assert 0.0 < small.est_share_pct < 100.0


def test_score_candidate_scores_zero_when_size_is_below_the_cutoff():
    market = _market(min_size=50.0)
    book_a = _book([(0.59, 500)], [(0.61, 500)])
    book_b = _book([(0.39, 500)], [(0.41, 500)])

    candidate = score_candidate(market, book_a, book_b, 0.60, 0.40, 20.0, 1.0)

    assert candidate.q_min == 0.0
    assert candidate.est_share_pct == 0.0


def test_score_candidate_scores_zero_outside_the_max_spread():
    market = _market(max_spread_cents=4.5)
    book_a = _book([(0.59, 500)], [(0.61, 500)])
    book_b = _book([(0.39, 500)], [(0.41, 500)])

    candidate = score_candidate(market, book_a, book_b, 0.60, 0.40, 20.0, 6.0)

    assert candidate.q_min == 0.0
    assert candidate.est_share_pct == 0.0


def test_notional_covers_both_legs_of_the_quote():
    market = _market(prices=[0.60, 0.40], min_size=20.0)
    book_a = _book([(0.59, 500)], [(0.61, 500)])
    book_b = _book([(0.39, 500)], [(0.41, 500)])

    candidate = score_candidate(market, book_a, book_b, 0.60, 0.40, 20.0, 1.0)

    # Both legs rest, and the exchange reserves the collateral of each.
    assert candidate.notional_usd == 20.0 * (0.60 + 0.40)


def test_updown_candidate_has_no_reward_rate():
    market = _market(rate_per_day=500.0)
    book_a = _book([(0.49, 500)], [(0.51, 500)])
    book_b = _book([(0.49, 500)], [(0.51, 500)])

    candidate = updown_candidate(market, book_a, book_b, 0.50, 0.50, 50.0, 1.0)

    assert candidate.rate_per_day == 0.0
    assert candidate.est_daily_usd == 0.0
    assert candidate.q_min > 0.0


def test_select_candidates_filters_by_rate_and_spread_cap():
    candidates = [
        _candidate(condition_id="0xlow", rate_per_day=10.0),
        _candidate(condition_id="0xwide", max_spread_cents=6.5),
        _candidate(condition_id="0xok", rate_per_day=100.0),
    ]

    selected = select_candidates(candidates, capital_usd=10.0, min_rate_per_day=50.0)

    assert [candidate.condition_id for candidate in selected] == ["0xok"]


def test_select_candidates_sorts_by_share_and_respects_capital():
    candidates = [
        _candidate(condition_id="0xa", est_share_pct=1.0, notional_usd=1.5),
        _candidate(condition_id="0xb", est_share_pct=5.0, notional_usd=2.0),
        _candidate(condition_id="0xc", est_share_pct=3.0, notional_usd=0.5),
    ]

    selected = select_candidates(candidates, capital_usd=3.4)

    assert [candidate.condition_id for candidate in selected] == ["0xb", "0xc"]


def test_select_candidates_skips_candidates_with_no_share():
    candidates = [_candidate(condition_id="0xzero", est_share_pct=0.0, q_min=0.0)]

    assert select_candidates(candidates, capital_usd=3.4) == []


def test_size_cutoff_midpoint_ignores_sub_cutoff_levels():
    book = _book([(0.50, 5), (0.48, 100)], [(0.70, 5), (0.72, 100)])
    # The best bid and ask under the cutoff are 0.48 and 0.72.
    assert size_cutoff_midpoint(book, 20.0, 0.60) == (0.48 + 0.72) / 2.0


def test_size_cutoff_midpoint_falls_back_when_nothing_qualifies():
    book = _book([(0.50, 5)], [(0.70, 5)])
    assert size_cutoff_midpoint(book, 20.0, 0.60) == 0.60


def test_estimate_is_invariant_under_book_mirroring():
    """The CLOB serves a binary condition's two token books as mirrors.

    A bid at p on one token is the same resting liquidity as an ask at 1 - p
    on the other, with the same size. The two-view aggregate the methodology
    defines is therefore twice the single-view aggregate, for the competitors
    and for us alike, so the estimated share is the single-view share.
    """
    market = _market(min_size=20.0, max_spread_cents=4.5)
    book_a = _book([(0.59, 400)], [(0.61, 300)])
    book_b = _book([(0.39, 300)], [(0.41, 400)])

    candidate = score_candidate(market, book_a, book_b, 0.60, 0.40, 20.0, 1.0)

    score = ((4.5 - 1.0) / 4.5) ** 2
    ours = score * 20.0
    competitors_one = score * 400.0
    competitors_two = score * 300.0

    # Both views are counted, so every quantity is twice its single-view value.
    assert candidate.q_one == 2.0 * ours
    assert candidate.q_two == 2.0 * ours

    expected_share = 100.0 * ours / (ours + min(competitors_one, competitors_two))
    assert candidate.est_share_pct == pytest.approx(expected_share)


def test_market_meta_reads_the_reward_row():
    clob_market = {
        "condition_id": "0xabc",
        "question": "Will it rain tomorrow?",
        "tokens": [
            {"token_id": "111", "outcome": "Yes", "price": 0.6},
            {"token_id": "222", "outcome": "No", "price": 0.4},
        ],
        "rewards": {"min_size": 20, "max_spread": 4.5},
    }
    rewards_row = {
        "condition_id": "0xabc",
        "rewards_min_size": 20,
        "rewards_max_spread": 4.5,
        "rewards_config": [{"rate_per_day": 250.0}],
    }

    meta = market_meta(clob_market, rewards_row=rewards_row)

    assert meta["tokens"] == ["111", "222"]
    assert meta["min_size"] == 20.0
    assert meta["max_spread_cents"] == 4.5
    assert meta["rate_per_day"] == 250.0
