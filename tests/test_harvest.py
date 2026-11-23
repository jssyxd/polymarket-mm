"""Plan B standing by: harvest planning and the SELL invariants that gate it."""

from __future__ import annotations

import pytest

from pmm.core.selection import QuoteIntent
from pmm.engine.runner import _resting_key
from pmm.execution.clob import ExecutionError
from pmm.execution.harvest import HarvestPlan, plan_harvests


def _pos(size=57.33, mark=0.9955, cost=0.90, token="T1"):
    return {
        "condition_id": "0xcond",
        "title": "market",
        "token_id": token,
        "current_size": size,
        "current_price": mark,
        "avg_price": cost,
    }


def _intent(**overrides) -> QuoteIntent:
    fields = dict(
        condition_id="0xcond",
        question="q",
        leg="up",
        token_id="T1",
        price=0.99,
        size=57.33,
        side="SELL",
        post_only=True,
        kind="harvest",
    )
    fields.update(overrides)
    return QuoteIntent(**fields)


def test_a_nearly_won_profitable_leg_is_harvestable():
    plans = plan_harvests([_pos()])

    assert plans == [HarvestPlan("0xcond", "market", "T1", 57.33, 0.99, 0.9955, 0.90)]


def test_selling_at_the_floor_must_still_be_profitable():
    assert plan_harvests([_pos(cost=0.99)]) == []
    assert plan_harvests([_pos(cost=0.97)]) != []


def test_a_leg_below_the_floor_is_not_harvested():
    assert plan_harvests([_pos(mark=0.98)]) == []


def test_a_small_leg_or_an_already_resting_order_is_skipped():
    assert plan_harvests([_pos(size=4.0)]) == []
    assert plan_harvests([_pos()], open_assets=["T1"]) == []


def test_the_resting_key_keeps_a_buy_and_a_sell_on_one_leg_apart():
    buy = _intent(side="BUY", kind="quote")
    sell = _intent(side="SELL")

    assert _resting_key(buy) != _resting_key(sell)
    assert _resting_key(buy) == ("0xcond", "up", "BUY")


def test_a_plain_sell_intent_is_still_refused():
    with pytest.raises(ExecutionError, match="not a buy"):
        Runner_payloads([_intent(kind="quote")])


def test_a_harvest_sell_below_the_floor_is_refused():
    with pytest.raises(ExecutionError, match="floor"):
        Runner_payloads([_intent(price=0.98)])


def test_a_harvest_sell_must_be_post_only():
    with pytest.raises(ExecutionError, match="post-only"):
        Runner_payloads([_intent(post_only=False)])


def test_a_harvest_sell_at_the_floor_is_allowed():
    payloads = Runner_payloads([_intent()])

    assert payloads[0]["side"] == "SELL"
    assert payloads[0]["price"] == 0.99
    assert payloads[0]["post_only"] is True


def Runner_payloads(intents):
    from pmm.engine.runner import Runner

    return Runner._payloads(intents)


class _Client:
    def get_open_orders(self):
        return []


class _Executor:
    def __init__(self) -> None:
        self.client = _Client()
        self.placed: list[dict] = []

    def build_payload(self, intent):
        return dict(intent)

    def place(self, payload, reason):
        self.placed.append(payload)
        return {"status": "live", "success": True}


def test_a_live_harvest_is_refused_unless_the_switch_is_on():
    from pmm.execution.config import ExecutionConfig
    from pmm.execution.harvest import run_harvest

    config = ExecutionConfig(dry_run=False, owner_pk="0x" + "11" * 32, harvest_enabled=False)
    with pytest.raises(RuntimeError, match="POLY_HARVEST"):
        run_harvest(config, executor=_Executor(), positions=[_pos()])


def test_the_switch_arms_it_and_the_sell_is_post_only():
    from pmm.execution.config import ExecutionConfig
    from pmm.execution.harvest import run_harvest

    executor = _Executor()
    config = ExecutionConfig(dry_run=False, owner_pk="0x" + "11" * 32, harvest_enabled=True)

    results = run_harvest(
        config, executor=executor, positions=[_pos()],
        best_bids={"T1": 0.97}, ticks={"T1": 0.001},
    )

    assert executor.placed[0]["side"] == "SELL"
    assert executor.placed[0]["post_only"] is True
    assert executor.placed[0]["price"] == 0.99
    assert results[0]["status"] == "live"


def test_a_dry_run_works_with_the_switch_off():
    from pmm.execution.config import ExecutionConfig
    from pmm.execution.harvest import run_harvest

    executor = _Executor()
    config = ExecutionConfig(dry_run=True, harvest_enabled=False)

    results = run_harvest(
        config, executor=executor, positions=[_pos()],
        best_bids={"T1": 0.97}, ticks={"T1": 0.001},
    )

    assert results[0]["status"] == "dry_run"
    assert executor.placed == []


def test_a_book_at_the_ceiling_yields_no_order():
    from pmm.execution.config import ExecutionConfig
    from pmm.execution.harvest import run_harvest

    executor = _Executor()
    config = ExecutionConfig(dry_run=False, owner_pk="0x" + "11" * 32, harvest_enabled=True)

    results = run_harvest(
        config, executor=executor, positions=[_pos()],
        best_bids={"T1": 0.999}, ticks={"T1": 0.001},
    )

    assert executor.placed == [], "a sell under a 0.999 bid would cross and be refused"
    assert results[0]["status"].startswith("skipped")


def test_the_passive_price_clears_the_bid_by_one_tick():
    from pmm.execution.harvest import passive_ask_price

    assert passive_ask_price(0.97, 0.001) == 0.99, "the floor wins when the bid is low"
    assert passive_ask_price(0.990, 0.001) == 0.991
    assert passive_ask_price(0.999, 0.001) is None
    assert passive_ask_price(0.0, 0.01) == 0.99
