"""Tests for the domain models: market snapshot, paired inventory, selection.

No network, no credentials, standard library only.
"""

from __future__ import annotations

import json
import sys
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.core.inventory import PairedInventory  # noqa: E402
from pmm.core.market import MarketSnapshot  # noqa: E402
from pmm.core.selection import (  # noqa: E402
    QuoteIntent,
    QuotePlan,
    effective_half_spread_cents,
    select_quotes,
)
from pmm.pricing.quotes import Inventory as QuoteInventory  # noqa: E402
from pmm.pricing.quotes import Quote, QuoteSide  # noqa: E402
from pmm.risk.gates import GateDecision  # noqa: E402

TICK = 0.01


def _snapshot(**overrides) -> MarketSnapshot:
    base = {
        "condition_id": "0xabc",
        "question": "Will it rain?",
        "up_token_id": "111",
        "down_token_id": "222",
        "tick_size": TICK,
        "min_order_size": 20.0,
        "reward_min_size": 20.0,
        "reward_max_spread_cents": 4.5,
        "rate_per_day": 140.0,
        "midpoint": 0.5,
        "book_up": {"bids": [{"price": "0.49", "size": "100"}], "asks": [{"price": "0.51", "size": "100"}]},
        "book_down": {"bids": [{"price": "0.49", "size": "100"}], "asks": [{"price": "0.51", "size": "100"}]},
        "expires_at": 0.0,
        "neg_risk": False,
    }
    base.update(overrides)
    return MarketSnapshot(**base)


def _quote(up_price: float = 0.46, down_price: float = 0.46, size: float = 20.0) -> Quote:
    return Quote(
        up=QuoteSide(token_id="111", price=up_price, size=size, is_buy=True),
        down=QuoteSide(token_id="222", price=down_price, size=size, is_buy=True),
        reason="",
        fair_prob=0.5,
        half_spread=0.036,
        expires_at=0.0,
    )


# -- market snapshot -------------------------------------------------------


def test_snapshot_from_clob_market_reads_the_reward_settings():
    market = {
        "condition_id": "0xdef",
        "question": "Will the price go up?",
        "tokens": [
            {"token_id": "up-token", "outcome": "Yes", "price": 0.62},
            {"token_id": "down-token", "outcome": "No", "price": 0.38},
        ],
        "order_price_min_tick_size": "0.01",
        "order_min_size": "5",
        "neg_risk": True,
        "end_date_iso": "2026-12-31T00:00:00Z",
        "rewards": {"min_size": 50.0, "max_spread": 6.5},
    }
    snapshot = MarketSnapshot.from_clob_market(market)

    assert snapshot.condition_id == "0xdef"
    assert snapshot.up_token_id == "up-token"
    assert snapshot.down_token_id == "down-token"
    assert snapshot.tick_size == 0.01
    assert snapshot.min_order_size == 5.0
    assert snapshot.reward_min_size == 50.0
    assert snapshot.reward_max_spread_cents == 6.5
    assert snapshot.neg_risk is True
    assert snapshot.expires_at > 0.0


def test_snapshot_prefers_the_reward_row_over_the_market_object():
    market = {
        "condition_id": "0xdef",
        "tokens": [{"token_id": "a"}, {"token_id": "b"}],
        "rewards": {"min_size": 50.0, "max_spread": 6.5},
    }
    row = {
        "condition_id": "0xdef",
        "rewards_min_size": 20.0,
        "rewards_max_spread": 4.5,
        "rewards_config": [{"rate_per_day": 330.0}],
    }
    snapshot = MarketSnapshot.from_clob_market(market, rewards_row=row)

    assert snapshot.reward_min_size == 20.0
    assert snapshot.reward_max_spread_cents == 4.5
    assert snapshot.rate_per_day == 330.0


def test_snapshot_to_dict_is_json_serialisable():
    payload = _snapshot().to_dict()
    assert json.loads(json.dumps(payload))["condition_id"] == "0xabc"
    assert payload["up_token_id"] == "111"


# -- paired inventory ------------------------------------------------------


def test_perfectly_paired_inventory_has_no_exposure():
    inventory = PairedInventory(
        up_shares=40.0,
        down_shares=40.0,
        max_inventory_per_side=100.0,
        mark_up=0.5,
        mark_down=0.5,
    )

    assert inventory.unpaired_up == 0.0
    assert inventory.unpaired_down == 0.0
    assert inventory.box == 40.0
    assert inventory.notional_at_risk == 0.0
    assert inventory.mergeable_coverage == 1.0


def test_unpaired_inventory_reports_exposure():
    inventory = PairedInventory(
        up_shares=40.0,
        down_shares=25.0,
        max_inventory_per_side=100.0,
        mark_up=0.6,
        mark_down=0.4,
    )

    assert inventory.unpaired_up == 15.0
    assert inventory.unpaired_down == 0.0
    assert inventory.box == 25.0
    assert inventory.notional_at_risk == pytest.approx(15.0 * 0.6)
    assert inventory.mergeable_coverage == pytest.approx(2 * 25.0 / 65.0)


def test_inventory_converts_to_and_from_the_quote_inventory():
    quote_inventory = QuoteInventory(
        up_shares=10.0, down_shares=4.0, max_inventory_per_side=50.0
    )
    inventory = PairedInventory.from_quote_inventory(quote_inventory, 0.55, 0.45)

    assert inventory.up_shares == 10.0
    assert inventory.down_shares == 4.0
    back = inventory.to_quote_inventory()
    assert back.up_shares == 10.0
    assert back.down_shares == 4.0
    assert back.max_inventory_per_side == 50.0


# -- selection -------------------------------------------------------------


def test_selection_emits_two_bids_and_respects_the_budget():
    plan = QuotePlan(
        snapshot=_snapshot(),
        quote=_quote(),
        decision=GateDecision(),
    )
    result = select_quotes([plan], capital_usd=100.0, size_shares=20.0, half_spread_cents=1.0)

    assert len(result.intents) == 2
    assert {intent.leg for intent in result.intents} == {"up", "down"}
    assert all(intent.side == "BUY" for intent in result.intents)
    assert all(intent.post_only for intent in result.intents)
    assert result.selected == ["0xabc"]


def test_selection_drops_a_market_that_does_not_fit_the_budget():
    plan = QuotePlan(
        snapshot=_snapshot(),
        quote=_quote(),
        decision=GateDecision(),
    )
    result = select_quotes([plan], capital_usd=1.0, size_shares=20.0, half_spread_cents=1.0)

    assert result.intents == []
    assert result.selected == []
    assert any("pUSD" in reason for reason in result.rejected)


def test_selection_drops_the_leg_a_gate_blocks_and_keeps_the_reason():
    plan = QuotePlan(
        snapshot=_snapshot(),
        quote=_quote(),
        decision=GateDecision(allowed_up=False, reasons=["cooldown_up_1.0s"]),
    )
    result = select_quotes([plan], capital_usd=100.0, size_shares=20.0, half_spread_cents=1.0)

    assert [intent.leg for intent in result.intents] == ["down"]
    assert any("up" in reason and "cooldown_up" in reason for reason in result.rejected)


def test_selection_drops_both_legs_on_a_hard_stop():
    plan = QuotePlan(
        snapshot=_snapshot(),
        quote=_quote(),
        decision=GateDecision(
            allowed_up=False, allowed_down=False, reasons=["hard_stop_heartbeat_lost"], hard_stop=True
        ),
    )
    result = select_quotes([plan], capital_usd=100.0, size_shares=20.0, half_spread_cents=1.0)

    assert result.intents == []
    assert any("hard_stop" in reason for reason in result.rejected)


def test_half_spread_is_clamped_to_the_reward_band():
    assert effective_half_spread_cents(9.0, _snapshot(reward_max_spread_cents=4.5)) == 4.5
    assert effective_half_spread_cents(1.0, _snapshot(reward_max_spread_cents=4.5)) == 1.0
    assert effective_half_spread_cents(9.0, _snapshot(reward_max_spread_cents=0.0)) == 9.0


def test_intent_payload_carries_post_only():
    intent = QuoteIntent(
        condition_id="0xabc",
        question="q",
        leg="up",
        token_id="111",
        price=0.46,
        size=20.0,
    )
    payload = intent.to_payload()

    assert payload["post_only"] is True
    assert payload["side"] == "BUY"
    assert payload["token_id"] == "111"
