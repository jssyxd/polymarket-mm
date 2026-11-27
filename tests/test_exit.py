from pmm.execution.exit import ExitPlan, plan_exits

NOW = 1_795_500_000.0


def _pos(size=20.0, cost=0.55, entered=NOW - 120, condition="0xcond", token="HELD", opposite="COMP"):
    return {
        "condition_id": condition,
        "title": "market",
        "outcome_index": 0,
        "current_size": size,
        "avg_price": cost,
        "first_entry_at": entered,
        "token_id": token,
        "opposite_token_id": opposite,
    }


def test_an_old_leg_that_cannot_be_repaired_is_sold_at_best_bid():
    plans = plan_exits(
        [_pos()],
        best_bids={"HELD": 0.48},
        complement_asks={"0xcond": 0.50},
        now=NOW,
        max_age_seconds=60,
    )
    assert plans == [ExitPlan("0xcond", "market", "HELD", 20.0, 0.48, 0.55, 120.0, 1.05)]


def test_a_young_leg_is_left_for_the_partner():
    plans = plan_exits([_pos(entered=NOW - 30)], best_bids={"HELD": 0.48}, now=NOW)
    assert plans == []


def test_a_repairable_pair_is_not_sold_at_a_loss():
    plans = plan_exits(
        [_pos(cost=0.45)],
        best_bids={"HELD": 0.44},
        complement_asks={"0xcond": 0.50},
        now=NOW,
    )
    assert plans == []


def test_without_a_bid_nothing_is_sold():
    plans = plan_exits([_pos()], best_bids={}, complement_asks={"0xcond": 0.50}, now=NOW)
    assert plans == []


def test_a_paired_position_is_not_exited():
    row = _pos()
    paired = dict(row, outcome_index=1, token_id="OTHER")
    plans = plan_exits([row, paired], best_bids={"HELD": 0.48}, now=NOW)
    assert plans == []


def test_actual_position_shape_uses_journal_entry_time():
    row = {
        "condition_id": "0xcond",
        "token_id": "HELD",
        "current_size": 20.0,
        "avg_price": 0.55,
    }
    plans = plan_exits(
        [row],
        best_bids={"HELD": 0.48},
        complement_asks={"0xcond": 0.50},
        entry_times={"HELD": NOW - 120},
        now=NOW,
    )
    assert plans and plans[0].token_id == "HELD"
    assert plans[0].age_seconds == 120.0


def test_two_tokens_in_one_condition_are_a_pair():
    rows = [
        {"condition_id": "0xcond", "token_id": "A", "current_size": 20.0, "avg_price": 0.5},
        {"condition_id": "0xcond", "token_id": "B", "current_size": 20.0, "avg_price": 0.5},
    ]
    plans = plan_exits(rows, best_bids={"A": 0.4, "B": 0.4}, now=NOW)
    assert plans == []
