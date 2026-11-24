"""The risk guards that were missing when the live run lost money."""

from __future__ import annotations

import datetime as dt

from pmm.core.market import MarketSnapshot
from pmm.core.selection import QuoteIntent, select_quotes
from pmm.engine.runner import is_tradeable
from pmm.pricing.quotes import Quote, QuoteSide
from pmm.core.selection import QuotePlan
from pmm.risk.gates import GateDecision


def _now_iso(hours: float) -> str:
    stamp = dt.datetime.now(dt.timezone.utc) + dt.timedelta(hours=hours)
    return stamp.strftime("%Y-%m-%dT%H:%M:%SZ")


def test_a_market_settling_within_the_horizon_is_not_tradeable():
    market = {"end_date_iso": _now_iso(2), "closed": False, "accepting_orders": True}

    assert is_tradeable(market, now=dt.datetime.now(dt.timezone.utc).timestamp(), min_hours=24) is False


def test_a_market_far_from_settlement_is_tradeable():
    market = {"end_date_iso": _now_iso(72), "closed": False, "accepting_orders": True}

    assert is_tradeable(market, now=dt.datetime.now(dt.timezone.utc).timestamp(), min_hours=24) is True


def test_a_closed_or_non_accepted_market_is_not_tradeable():
    now = dt.datetime.now(dt.timezone.utc).timestamp()
    far = _now_iso(72)

    assert is_tradeable({"end_date_iso": far, "closed": True}, now=now, min_hours=24) is False
    assert (
        is_tradeable({"end_date_iso": far, "closed": False, "accepting_orders": False},
                     now=now, min_hours=24)
        is False
    )


def _plan(commit_price: float = 0.45, size: float = 20.0) -> QuotePlan:
    snapshot = MarketSnapshot(
        condition_id="0xcond",
        question="q",
        up_token_id="U",
        down_token_id="D",
        midpoint=0.5,
        tick_size=0.01,
        min_order_size=5.0,
        reward_min_size=20.0,
        reward_max_spread_cents=4.5,
        rate_per_day=100.0,
        book_up={"bids": [], "asks": []},
        book_down={"bids": [], "asks": []},
    )
    quote = Quote(
        up=QuoteSide(token_id="U", price=commit_price, size=size, is_buy=True),
        down=QuoteSide(token_id="D", price=round(1 - commit_price - 0.02, 2), size=size, is_buy=True),
        reason="test",
        fair_prob=0.5,
        half_spread=0.02,
        expires_at=0.0,
    )
    return QuotePlan(snapshot=snapshot, quote=quote, decision=GateDecision(),
                     candidate=None, reasons=())


def test_a_market_that_commits_above_the_cap_is_rejected():
    plan = _plan(commit_price=0.47)  # 20 * (0.47 + 0.51) = 19.6 pUSD at risk

    capped = select_quotes([plan], capital_usd=1000.0, size_shares=20.0,
                           half_spread_cents=2.0, max_market_usd=15.0)
    assert capped.intents == []
    assert any("per-market cap" in reason for reason in capped.rejected)

    uncapped = select_quotes([plan], capital_usd=1000.0, size_shares=20.0,
                             half_spread_cents=2.0, max_market_usd=0.0)
    assert uncapped.intents
