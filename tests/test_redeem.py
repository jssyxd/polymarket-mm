"""Redeem: only resolved wins, one call per market, and the payout is booked."""

from __future__ import annotations

from pmm.execution.config import ExecutionConfig
from pmm.execution.journal import Journal, compute_pnl
from pmm.execution.redeem import RedeemTarget, plan_redeems, run_redeem


def _pos(size=57.33, price=1.0, redeemable=True, index=0, condition="0xcond", token="T1"):
    return {
        "condition_id": condition,
        "title": "market",
        "outcome_index": index,
        "outcome": "Yes" if index == 0 else "No",
        "token_id": token,
        "current_size": size,
        "current_price": price,
        "redeemable": redeemable,
    }


def test_only_a_resolved_winning_leg_is_redeemed():
    plans = plan_redeems([_pos()])

    assert plans == [RedeemTarget("0xcond", "market", 57.33, "Yes", 57.33)]


def test_a_losing_leg_pays_nothing_and_is_skipped():
    assert plan_redeems([_pos(price=0.0, index=1, token="T2")]) == []


def test_an_unresolved_market_is_skipped():
    assert plan_redeems([_pos(redeemable=False)]) == []


def test_one_call_per_market_even_with_both_legs_listed():
    rows = [_pos(), _pos(price=0.0, index=1, token="T2")]

    assert len(plan_redeems(rows)) == 1


class _Handle:
    def __init__(self):
        self.waited = False

    def wait(self):
        self.waited = True


class _Client:
    def __init__(self) -> None:
        self.calls = []
        self.handles = []

    def redeem_positions(self, **kwargs):
        self.calls.append(kwargs)
        handle = _Handle()
        self.handles.append(handle)
        return handle


def test_a_dry_run_plans_and_calls_nothing():
    client = _Client()
    config = ExecutionConfig(dry_run=True)

    results = run_redeem(config, client=client, positions=[_pos()])

    assert results[0]["status"] == "dry_run"
    assert client.calls == []


def test_a_live_run_redeems_and_books_the_payout(tmp_path):
    client = _Client()
    journal = Journal(tmp_path / "journal")
    config = ExecutionConfig(dry_run=False, owner_pk="0x" + "11" * 32)
    journal.append("fill", condition_id="0xcond", token_id="T1", outcome="Yes", side="BUY",
                   price=0.90, size=57.33, notional=51.6, ts=1795437000, fill_id="t1:o1")
    journal.append("fill", condition_id="0xcond", token_id="T2", outcome="No", side="BUY",
                   price=0.05, size=57.33, notional=2.87, ts=1795437100, fill_id="t2:o2")

    results = run_redeem(config, client=client, positions=[_pos()], journal=journal)

    assert client.calls[0]["condition_id"] == "0xcond"
    assert client.handles[0].waited is True
    assert results[0]["status"] == "redeemed"

    pnl = compute_pnl(journal.fills(), {"T1": 1.0, "T2": 0.0})
    assert abs(pnl["realized_pnl"] - (57.33 - (0.90 + 0.05) * 57.33)) < 1e-6
    assert pnl["position_value"] == 0.0, "the redeemed shares are gone"
