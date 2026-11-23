"""Candidate market selection for a small-capital maker.

Picks markets where a maker with a few pUSD can qualify for liquidity rewards,
scores how much of the market's daily pool our own quote would capture, and
keeps the selection inside the capital budget.

Scoring model (see :mod:`pmm.data.rewards` for the formula):

``Q_one`` collects bids on the market token plus asks on the complement
token, ``Q_two`` collects the other way round.

The live CLOB serves the two outcome books of a binary condition as price
mirrors of one another: a bid at ``p`` on one token is the same resting
liquidity as an ask at ``1 - p`` on the other, with identical size. The
methodology's two-sided aggregate therefore counts every resting order twice,
ours and the competitors' alike. That factor cancels out of the estimated
share, since ``min`` and ``max`` are homogeneous of degree one.

Levels whose total size is below the market's ``min_size`` cannot host a
qualifying order and are dropped before scoring, which is the size cutoff the
methodology applies.

The rest of the book is treated as one blob of competitor liquidity and its
``Q_min`` stands in for the sum of the individual competitors' ``Q_min``
values. That substitution is an approximation: the blob takes the minimum of
the two aggregated sides, while the real sum is taken per maker. Over random
balanced and one-sided maker mixes the blob overstated the competitor total
in about three quarters of cases, so the estimated share is usually
conservative rather than optimistic.

Level granularity is a second approximation. A price level aggregates many
orders, and the methodology qualifies individual orders, so a level is
dropped when its total size is below the cutoff. That is exact for a level
whose whole size is under the cutoff (it cannot hold a qualifying order) and
generous for a level above it (it may hold no qualifying order at all).
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Sequence

from .rewards import Book, Level, order_score, q_min, q_one, q_two


@dataclass
class RewardCandidate:
    """One market worth quoting, with our score in it.

    ``q_one``, ``q_two`` and ``q_min`` are our own contribution: the points
    our hypothetical orders would add to this market's per-maker score.
    ``est_share_pct`` is our estimated share of the market's daily reward
    pool. ``notional_usd`` is the pUSD needed to hold the qualifying size on
    the cheaper side of the market.
    """

    condition_id: str
    question: str
    tokens: list[str]
    min_size: float
    max_spread_cents: float
    rate_per_day: float
    midpoint: float
    q_one: float
    q_two: float
    q_min: float
    est_share_pct: float
    notional_usd: float

    @property
    def est_daily_usd(self) -> float:
        """Expected pUSD per day from this market's pool."""
        return self.rate_per_day * self.est_share_pct / 100.0


def _levels_from_book(
    book: dict[str, Any], midpoint: float, side: str, min_size: float
) -> tuple[Level, ...]:
    """Convert a CLOB book's raw levels into midpoint-relative levels.

    Levels below ``min_size`` are dropped: the methodology only counts orders
    that reach the size cutoff, so a level whose whole size is under the
    cutoff cannot contribute.
    """
    levels: list[Level] = []
    for entry in book.get(side) or ():
        price = float(entry["price"])
        size = float(entry["size"])
        if size < min_size:
            continue
        if side == "bids":
            spread = (midpoint - price) * 100.0
        else:
            spread = (price - midpoint) * 100.0
        levels.append(Level(spread_cents=max(spread, 0.0), size=size))
    return tuple(levels)


def _book_from_raw(book: dict[str, Any], midpoint: float, min_size: float) -> Book:
    return Book(
        bids=_levels_from_book(book, midpoint, "bids", min_size),
        asks=_levels_from_book(book, midpoint, "asks", min_size),
    )


def size_cutoff_midpoint(
    book: dict[str, Any], min_size: float, fallback: float
) -> float:
    """The size-cutoff-adjusted midpoint the methodology measures spread from.

    The spread in the scoring function is measured from the midpoint of the
    book after the size cutoff has been applied, not from the raw CLOB
    midpoint. The adjusted midpoint is the average of the best qualifying bid
    and the best qualifying ask. ``fallback`` is used when the book has no
    qualifying level on one of the two sides.
    """
    bids = [
        float(entry["price"])
        for entry in book.get("bids") or ()
        if float(entry["size"]) >= min_size
    ]
    asks = [
        float(entry["price"])
        for entry in book.get("asks") or ()
        if float(entry["size"]) >= min_size
    ]
    if bids and asks:
        return (max(bids) + min(asks)) / 2.0
    if bids:
        return max(bids)
    if asks:
        return min(asks)
    return fallback


def _price_of(market: dict[str, Any], index: int, fallback: float) -> float:
    prices = market.get("prices") or []
    if index < len(prices):
        try:
            return float(prices[index])
        except (TypeError, ValueError):
            pass
    return fallback


def _score(
    market: dict[str, Any],
    book_a: dict[str, Any],
    book_b: dict[str, Any],
    mid_a: float,
    mid_b: float,
    our_size_shares: float,
    our_spread_cents: float,
    rate_per_day: float,
    market_competitiveness: float | None = None,
) -> RewardCandidate:
    min_size = float(market["min_size"])
    max_spread_cents = float(market["max_spread_cents"])

    # The methodology measures spread from the size-cutoff-adjusted midpoint.
    adj_a = size_cutoff_midpoint(book_a, min_size, mid_a)
    adj_b = size_cutoff_midpoint(book_b, min_size, mid_b)

    competitor_a = _book_from_raw(book_a, adj_a, min_size)
    competitor_b = _book_from_raw(book_b, adj_b, min_size)

    competitors_q_one = q_one(competitor_a, competitor_b, max_spread_cents)
    competitors_q_two = q_two(competitor_a, competitor_b, max_spread_cents)

    # Our own orders: one on each side of the market token, at our spread from
    # that book's adjusted midpoint. They appear in the complement book as the
    # mirrored side, so each of our orders feeds both Q_one and Q_two.
    qualifies = our_size_shares >= min_size and our_spread_cents <= max_spread_cents
    per_order = (
        order_score(max_spread_cents, our_spread_cents) * our_size_shares if qualifies else 0.0
    )
    ours_q_one = 2.0 * per_order
    ours_q_two = 2.0 * per_order

    midpoint = adj_a
    ours_q_min = q_min(ours_q_one, ours_q_two, midpoint)
    competitors_q_min = q_min(competitors_q_one, competitors_q_two, midpoint)

    if market_competitiveness is not None:
        # The venue publishes the market's competition score itself, as
        # ``market_competitiveness``. That number is the sum of every other
        # maker's Q_min for the market, which is exactly the denominator the
        # methodology divides by, so it is the correct figure to divide by.
        #
        # Reconstructing it from the book overstates it by two orders of
        # magnitude: the book aggregates every maker's size into one level,
        # and a level's size is not one maker's order. Measured against the
        # venue's own number on the same market, the book-based figure came
        # out 219 times too large.
        competitors_q_min = max(float(market_competitiveness), 0.0)

    total_q_min = ours_q_min + competitors_q_min
    est_share_pct = 100.0 * ours_q_min / total_q_min if total_q_min > 0 else 0.0

    p_up = _price_of(market, 0, mid_a)
    p_no = _price_of(market, 1, mid_b)
    # A qualifying quote rests BOTH legs, and the exchange reserves the
    # collateral of every resting buy. The two legs are complementary, so the
    # prices sum to about one and the pair commits about ``min_size`` pUSD,
    # not the price of the cheap leg. Using the cheap leg's price here
    # understates the capital by roughly half, which is the difference between
    # a market the account can quote and one it cannot.
    notional_usd = min_size * (p_up + p_no)

    return RewardCandidate(
        condition_id=str(market["condition_id"]),
        question=str(market.get("question", "")),
        tokens=list(market.get("tokens") or []),
        min_size=min_size,
        max_spread_cents=max_spread_cents,
        rate_per_day=rate_per_day,
        midpoint=midpoint,
        q_one=ours_q_one,
        q_two=ours_q_two,
        q_min=ours_q_min,
        est_share_pct=est_share_pct,
        notional_usd=notional_usd,
    )


def score_candidate(
    market: dict[str, Any],
    book_a: dict[str, Any],
    book_b: dict[str, Any],
    mid_a: float,
    mid_b: float,
    our_size_shares: float,
    our_spread_cents: float,
    market_competitiveness: float | None = None,
) -> RewardCandidate:
    """Score one market for our hypothetical quote.

    ``market`` is the normalized dict produced by :func:`market_meta` or
    :func:`gamma_market_meta`: ``condition_id``, ``question``, ``tokens``,
    ``min_size``, ``max_spread_cents`` and optionally ``prices``.
    ``book_a`` is the book of ``tokens[0]`` and ``book_b`` the book of
    ``tokens[1]``.

    ``market_competitiveness`` is the venue's own published competition score
    for the market. Passing it makes the share estimate exact rather than an
    approximation rebuilt from the book.
    """
    return _score(
        market,
        book_a,
        book_b,
        mid_a,
        mid_b,
        our_size_shares,
        our_spread_cents,
        float(market.get("rate_per_day", 0.0)),
        market_competitiveness,
    )


def updown_candidate(
    market: dict[str, Any],
    book_a: dict[str, Any],
    book_b: dict[str, Any],
    mid_a: float,
    mid_b: float,
    our_size_shares: float,
    our_spread_cents: float,
    market_competitiveness: float | None = None,
) -> RewardCandidate:
    """Score a crypto up/down market.

    These markets carry reward settings but no active reward allocation, so
    ``rate_per_day`` is zero and the candidate earns no liquidity rewards.
    """
    return _score(
        market,
        book_a,
        book_b,
        mid_a,
        mid_b,
        our_size_shares,
        our_spread_cents,
        0.0,
        market_competitiveness,
    )


def select_candidates(
    candidates: Sequence[RewardCandidate],
    capital_usd: float,
    max_spread_cents_cap: float = 4.5,
    min_rate_per_day: float = 50.0,
) -> list[RewardCandidate]:
    """Pick the markets we can afford, best estimated share first.

    Keeps candidates whose rate per day clears ``min_rate_per_day`` and whose
    configured max spread is at or below ``max_spread_cents_cap``, drops the
    ones our size cannot qualify in, sorts by estimated share of the daily
    pool descending, and takes them while the total notional stays inside
    ``capital_usd``.
    """
    eligible = [
        candidate
        for candidate in candidates
        if candidate.rate_per_day >= min_rate_per_day
        and candidate.max_spread_cents <= max_spread_cents_cap
        and candidate.est_share_pct > 0.0
    ]
    eligible.sort(key=lambda candidate: candidate.est_share_pct, reverse=True)

    selected: list[RewardCandidate] = []
    spent = 0.0
    for candidate in eligible:
        if spent + candidate.notional_usd > capital_usd:
            continue
        selected.append(candidate)
        spent += candidate.notional_usd
    return selected


def market_meta(
    clob_market: dict[str, Any],
    rewards_row: dict[str, Any] | None = None,
    rate_per_day: float | None = None,
) -> dict[str, Any]:
    """Normalize a CLOB market object into the dict :func:`score_candidate` takes.

    ``rewards_row`` is one row of ``/rewards/markets/current``; it carries the
    authoritative min size, max spread and daily rate for the pool.
    """
    tokens = [str(token["token_id"]) for token in clob_market.get("tokens") or ()]
    prices = [
        float(token["price"]) for token in clob_market.get("tokens") or () if "price" in token
    ]

    rewards = clob_market.get("rewards") or {}
    min_size = rewards.get("min_size", 0.0)
    max_spread_cents = rewards.get("max_spread", 0.0)

    if rewards_row is not None:
        min_size = rewards_row.get("rewards_min_size", min_size)
        max_spread_cents = rewards_row.get("rewards_max_spread", max_spread_cents)
        if rate_per_day is None:
            configs = rewards_row.get("rewards_config") or ()
            rates = [
                float(config["rate_per_day"]) for config in configs if "rate_per_day" in config
            ]
            rate_per_day = max(rates) if rates else float(rewards_row.get("native_daily_rate", 0.0))

    if rate_per_day is None:
        rate_per_day = 0.0

    return {
        "condition_id": str(clob_market["condition_id"]),
        "question": str(clob_market.get("question", "")),
        "tokens": tokens,
        "prices": prices,
        "min_size": float(min_size),
        "max_spread_cents": float(max_spread_cents),
        "rate_per_day": float(rate_per_day),
    }


def gamma_market_meta(gamma_market: dict[str, Any], rate_per_day: float = 0.0) -> dict[str, Any]:
    """Normalize a Gamma market object into the same shape as :func:`market_meta`."""
    token_ids = json.loads(gamma_market.get("clobTokenIds") or "[]")
    outcome_prices = json.loads(gamma_market.get("outcomePrices") or "[]")
    return {
        "condition_id": str(gamma_market["conditionId"]),
        "question": str(gamma_market.get("question", "")),
        "tokens": [str(token_id) for token_id in token_ids],
        "prices": [float(price) for price in outcome_prices],
        "min_size": float(gamma_market.get("rewardsMinSize", 0.0)),
        "max_spread_cents": float(gamma_market.get("rewardsMaxSpread", 0.0)),
        "rate_per_day": float(rate_per_day),
    }
