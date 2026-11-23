"""The rescue step: complete a nearly-won set with a cheap complement bid."""

from __future__ import annotations

from pmm.execution.config import ExecutionConfig
from pmm.execution.rescue import RescuePlan, plan_rescues, run_rescue


def _pos(size=20.0, price=0.99, index=0, complement="COMP", condition="0xcond"):
    return {
        "condition_id": condition,
        "title": "market",
        "outcome_index": index,
        "current_size": size,
        "current_price": price,
        "opposite_token_id": complement,
    }


def test_a_nearly_won_single_leg_gets_a_complement_bid_at_the_tick_floor():
    plans = plan_rescues([_pos()])

    assert plans == [RescuePlan("0xcond", "market", "COMP", 20.0, 0.01, 0.99)]


def test_a_paired_market_is_left_to_the_merge_timer():
    assert plan_rescues([_pos(), _pos(index=1, price=0.01, complement="OTHER")]) == []


def test_a_leg_below_the_threshold_is_not_rescued():
    assert plan_rescues([_pos(price=0.90)]) == []


def test_an_existing_order_on_the_complement_blocks_a_second_one():
    assert plan_rescues([_pos()], open_assets=["COMP"]) == []


def test_a_size_below_the_venue_minimum_is_skipped():
    assert plan_rescues([_pos(size=4.0)]) == []


def test_a_balance_that_cannot_fund_the_bid_blocks_it():
    assert plan_rescues([_pos()], balance=0.05) == []
    assert len(plan_rescues([_pos()], balance=1.0)) == 1


class _Client:
    def get_open_orders(self):
        return []


class _Executor:
    def __init__(self) -> None:
        self.client = _Client()
        self.placed: list[dict] = []

    def collateral_balance(self):
        return 10.0

    def build_payload(self, intent):
        return dict(intent, dry_run=True)

    def place(self, payload, reason):
        self.placed.append(payload)
        return {"status": "live", "success": True}


def test_a_dry_run_reports_the_plan_and_places_nothing():
    executor = _Executor()
    config = ExecutionConfig(dry_run=True)

    results = run_rescue(config, executor=executor, positions=[_pos()])

    assert results[0]["status"] == "dry_run"
    assert executor.placed == []


def test_a_live_run_places_a_post_only_buy_on_the_complement():
    executor = _Executor()
    config = ExecutionConfig(dry_run=False, owner_pk="0x" + "11" * 32)

    results = run_rescue(config, executor=executor, positions=[_pos()])

    assert executor.placed[0]["token_id"] == "COMP"
    assert executor.placed[0]["side"] == "BUY"
    assert executor.placed[0]["post_only"] is True
    assert executor.placed[0]["price"] == 0.01
    assert results[0]["status"] == "live"


def test_a_market_resolving_today_is_not_worth_completing():
    from datetime import date

    row = _pos()
    row["end_date"] = "2026-11-23"

    assert plan_rescues([row], today=date(2026, 11, 23)) == []
    assert len(plan_rescues([row], today=date(2026, 11, 21))) == 1


def test_a_market_with_days_left_is_completed():
    from datetime import date

    row = _pos()
    row["end_date"] = "2027-06-30"

    assert len(plan_rescues([row], today=date(2026, 11, 23))) == 1
