"""Time-limited pair repair: close a leg before it becomes a bet."""

from __future__ import annotations

from pmm.execution.repair import RepairPlan, plan_repairs

NOW = 1_795_500_000.0


def _pos(size=20.0, cost=0.45, entered=NOW - 3600, condition="0xcond", opposite="COMP"):
    return {
        "condition_id": condition,
        "title": "market",
        "outcome_index": 0,
        "current_size": size,
        "avg_price": cost,
        "first_entry_at": entered,
        "opposite_token_id": opposite,
    }


def test_an_old_single_leg_is_repaired_when_the_pair_still_costs_under_one():
    plans = plan_repairs(
        [_pos(cost=0.45)], complement_asks={"0xcond": 0.52}, now=NOW, max_age_seconds=900
    )

    assert plans == [RepairPlan("0xcond", "market", "COMP", 20.0, 0.52, 0.45, 0.97, 3600.0)]


def test_a_young_leg_is_left_alone_so_the_partner_can_still_fill():
    plans = plan_repairs(
        [_pos(entered=NOW - 60)],
        complement_asks={"0xcond": 0.52},
        now=NOW,
        max_age_seconds=900,
    )

    assert plans == []


def test_a_pair_that_would_cost_more_than_one_is_not_repaired():
    plans = plan_repairs(
        [_pos(cost=0.55)], complement_asks={"0xcond": 0.50}, now=NOW, max_age_seconds=900
    )

    assert plans == [], "0.55 + 0.50 > 1.00, merging would lock in a loss"


def test_without_the_missing_asks_nothing_is_planned():
    assert plan_repairs([_pos()], now=NOW, max_age_seconds=900) == []


def test_a_leg_is_closed_before_its_market_resolves():
    import datetime as dt

    row = _pos(entered=NOW - 60)  # young: the age rule would leave it alone
    row["end_date"] = dt.datetime.fromtimestamp(NOW + 2 * 3600, dt.timezone.utc).strftime("%Y-%m-%d")

    plans = plan_repairs([row], complement_asks={"0xcond": 0.52}, now=NOW, max_age_seconds=900)

    assert len(plans) == 1, "a market resolving in two hours must not carry a single leg in"
