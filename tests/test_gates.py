"""Tests for the risk gate stack.

No network, no credentials, standard library only.
"""

from __future__ import annotations

import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.risk import (  # noqa: E402
    CooldownGate,
    ERollingGate,
    ExpiryGate,
    GateStack,
    HardStopGate,
    InventoryBoxGate,
    MarketState,
    TickGate,
    ToxicityGate,
)


def _state(**overrides) -> MarketState:
    base = {
        "up_shares": 0.0,
        "down_shares": 0.0,
        "max_inventory_per_side": 100.0,
        "last_fill_side": None,
        "last_fill_ts": None,
        "now": 1000.0,
        "tau_seconds": 600.0,
        "fair_prob": 0.50,
        "mid": 0.50,
        "tick_size": 0.01,
        "recent_net_bps": [1.0] * 10,
        "equity_usd": 3.4,
        "drawdown_pct": 0.0,
        "heartbeat_ok": True,
        "oracle_age_seconds": 1.0,
        "min_order_size": 5.0,
    }
    base.update(overrides)
    return MarketState(**base)


class TestHardStopGate:
    def test_permissive_when_healthy(self) -> None:
        up, down, reason = HardStopGate().evaluate(_state())
        assert (up, down, reason) == (True, True, None)

    def test_fires_on_missing_heartbeat(self) -> None:
        up, down, reason = HardStopGate().evaluate(_state(heartbeat_ok=False))
        assert up is False and down is False
        assert reason is not None and "heartbeat" in reason

    def test_fires_on_stale_oracle(self) -> None:
        up, down, reason = HardStopGate().evaluate(_state(oracle_age_seconds=16.0))
        assert up is False and down is False
        assert reason is not None and "oracle" in reason

    def test_oracle_at_the_limit_does_not_fire(self) -> None:
        up, down, reason = HardStopGate().evaluate(_state(oracle_age_seconds=15.0))
        assert (up, down, reason) == (True, True, None)

    def test_fires_on_drawdown(self) -> None:
        up, down, reason = HardStopGate().evaluate(_state(drawdown_pct=21.0))
        assert up is False and down is False
        assert reason is not None and "drawdown" in reason

    def test_drawdown_at_the_limit_does_not_fire(self) -> None:
        up, down, reason = HardStopGate().evaluate(_state(drawdown_pct=20.0))
        assert (up, down, reason) == (True, True, None)


class TestInventoryBoxGate:
    def test_fires_on_the_full_side_only(self) -> None:
        up, down, reason = InventoryBoxGate().evaluate(_state(up_shares=100.0))
        assert up is False
        assert down is True
        assert reason is not None and "up" in reason

    def test_fires_on_the_down_side_only(self) -> None:
        up, down, reason = InventoryBoxGate().evaluate(_state(down_shares=100.0))
        assert up is True
        assert down is False
        assert reason is not None and "down" in reason

    def test_permissive_below_the_box(self) -> None:
        up, down, reason = InventoryBoxGate().evaluate(_state(up_shares=99.0))
        assert (up, down, reason) == (True, True, None)


class TestCooldownGate:
    def test_blocks_the_side_that_filled(self) -> None:
        state = _state(last_fill_side="up", last_fill_ts=997.0, now=1000.0)
        up, down, reason = CooldownGate().evaluate(state)
        assert up is False
        assert down is True
        assert reason is not None and "cooldown" in reason

    def test_releases_after_five_seconds(self) -> None:
        state = _state(last_fill_side="up", last_fill_ts=995.0, now=1000.0)
        up, down, reason = CooldownGate().evaluate(state)
        assert (up, down, reason) == (True, True, None)

    def test_no_fill_is_permissive(self) -> None:
        up, down, reason = CooldownGate().evaluate(_state())
        assert (up, down, reason) == (True, True, None)


class TestToxicityGate:
    def test_fires_when_fair_and_mid_disagree(self) -> None:
        up, down, reason = ToxicityGate().evaluate(_state(fair_prob=0.55, mid=0.50))
        assert up is False and down is False
        assert reason is not None and "toxicity" in reason

    def test_permissive_at_the_threshold(self) -> None:
        up, down, reason = ToxicityGate().evaluate(_state(fair_prob=0.53, mid=0.50))
        assert (up, down, reason) == (True, True, None)


class TestExpiryGate:
    def test_fires_close_to_resolution(self) -> None:
        up, down, reason = ExpiryGate().evaluate(_state(tau_seconds=89.0))
        assert up is False and down is False
        assert reason is not None and "expiry" in reason

    def test_permissive_at_the_threshold(self) -> None:
        up, down, reason = ExpiryGate().evaluate(_state(tau_seconds=90.0))
        assert (up, down, reason) == (True, True, None)


class TestERollingGate:
    def test_blocks_both_sides_when_capture_is_negative(self) -> None:
        state = _state(recent_net_bps=[-0.4] * 100)
        up, down, reason = ERollingGate().evaluate(state)
        assert up is False and down is False
        assert reason is not None and "e_rolling" in reason

    def test_blocks_at_exactly_zero(self) -> None:
        state = _state(recent_net_bps=[0.0] * 100)
        up, down, reason = ERollingGate().evaluate(state)
        assert up is False and down is False
        assert reason is not None

    def test_permissive_when_capture_is_positive(self) -> None:
        state = _state(recent_net_bps=[0.2] * 100)
        up, down, reason = ERollingGate().evaluate(state)
        assert (up, down, reason) == (True, True, None)

    def test_uses_only_the_last_hundred_fills(self) -> None:
        state = _state(recent_net_bps=[-5.0] * 100 + [1.0] * 100)
        up, down, reason = ERollingGate().evaluate(state)
        assert (up, down, reason) == (True, True, None)

    def test_no_history_is_not_a_loss(self) -> None:
        up, down, reason = ERollingGate().evaluate(_state(recent_net_bps=[]))
        assert (up, down, reason) == (True, True, None)


class TestTickGate:
    def test_blocks_a_price_outside_the_band(self) -> None:
        up, down, reason = TickGate().evaluate(_state(mid=1.0))
        assert up is False and down is False
        assert reason is not None and "price" in reason

    def test_blocks_when_the_box_room_is_below_the_minimum_size(self) -> None:
        state = _state(up_shares=98.0, max_inventory_per_side=100.0, min_order_size=5.0)
        up, down, reason = TickGate().evaluate(state)
        assert up is False
        assert down is True
        assert reason is not None and "size" in reason

    def test_permissive_on_a_normal_market(self) -> None:
        up, down, reason = TickGate().evaluate(_state(mid=0.505))
        assert (up, down, reason) == (True, True, None)


class TestGateStack:
    def test_healthy_market_allows_both_sides(self) -> None:
        decision = GateStack().evaluate(_state())
        assert decision.allowed_up is True
        assert decision.allowed_down is True
        assert decision.reasons == []
        assert decision.hard_stop is False

    def test_hard_stop_beats_a_permissive_inventory_gate(self) -> None:
        state = _state(up_shares=100.0, heartbeat_ok=False)
        decision = GateStack().evaluate(state)
        assert decision.hard_stop is True
        assert decision.allowed_up is False
        assert decision.allowed_down is False
        assert any("heartbeat" in reason for reason in decision.reasons)
        assert any("inventory" in reason for reason in decision.reasons)

    def test_inventory_box_alone_keeps_the_other_side_open(self) -> None:
        decision = GateStack().evaluate(_state(up_shares=100.0))
        assert decision.allowed_up is False
        assert decision.allowed_down is True
        assert decision.hard_stop is False

    def test_rolling_alarm_blocks_both_sides(self) -> None:
        state = _state(recent_net_bps=[-0.55] * 100)
        decision = GateStack().evaluate(state)
        assert decision.allowed_up is False
        assert decision.allowed_down is False
        assert any("e_rolling" in reason for reason in decision.reasons)

    def test_reasons_follow_the_stack_order(self) -> None:
        state = _state(tau_seconds=10.0, fair_prob=0.60, mid=0.50)
        decision = GateStack().evaluate(state)
        reasons = decision.reasons
        assert any("toxicity" in reason for reason in reasons)
        assert any("expiry" in reason for reason in reasons)
        assert reasons.index([r for r in reasons if "toxicity" in r][0]) < reasons.index(
            [r for r in reasons if "expiry" in r][0]
        )
