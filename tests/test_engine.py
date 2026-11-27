"""Tests for the engine: quote cycle, service runner, hourly self-tune.

No network, no credentials, standard library only.
"""

from __future__ import annotations

import json
import sys
import time
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.core.market import MarketSnapshot  # noqa: E402
from pmm.core.selection import QuoteIntent  # noqa: E402
from pmm.data.clob import CLOBError  # noqa: E402
from pmm.data.public_trades import PublicTrade  # noqa: E402
from pmm.engine.cycle import QuoteCycle  # noqa: E402
from pmm.engine.runner import Runner, RunnerConfig  # noqa: E402
from pmm.engine.self_tune import (  # noqa: E402
    DEFAULT_PARAMS,
    load_params,
    run_self_tune,
    write_params,
)
from pmm.execution.clob import ExecutionError  # noqa: E402
from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.journal import Journal  # noqa: E402

TICK = 0.01


def _book(mid: float, bid: float = 0.01, ask: float = 0.01) -> dict:
    """A book that agrees with the midpoint it is paired with."""
    return {
        "bids": [{"price": f"{max(mid - bid, 0.01):.4f}", "size": "100"}],
        "asks": [{"price": f"{min(mid + ask, 0.99):.4f}", "size": "100"}],
    }


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
        "book_up": _book(0.5),
        "book_down": _book(0.5),
        "expires_at": 0.0,
        "neg_risk": False,
    }
    base.update(overrides)
    snapshot = MarketSnapshot(**base)
    if "book_up" not in overrides:
        snapshot.book_up = _book(snapshot.midpoint)
    if "book_down" not in overrides:
        snapshot.book_down = _book(1.0 - snapshot.midpoint)
    return snapshot


def _params(**overrides) -> dict:
    params = dict(DEFAULT_PARAMS)
    params.update(overrides)
    return params


def _config(journal_path: str) -> ExecutionConfig:
    return ExecutionConfig(dry_run=True, journal_path=journal_path)


class _FakeExecutor:
    """Records what the runner asked the venue to do."""

    def __init__(self) -> None:
        self.events: list[str] = []
        self.payloads: list[dict] = []

    def place_batch(self, payloads: list[dict], reason: str = "batch") -> list[dict]:
        self.events.append("place_batch")
        self.payloads.extend(payloads)
        return [{"status": "dry_run"} for _ in payloads]

    def cancel(self, order_id: str) -> dict:
        self.events.append(f"cancel:{order_id}")
        return {"status": "dry_run"}

    def cancel_all(self) -> dict:
        self.events.append("cancel_all")
        return {"status": "dry_run"}

    def close(self) -> None:
        self.events.append("close")


class _FakeHeartbeat:
    def __init__(self, events: list[str]) -> None:
        self.events = events

    def start(self) -> None:
        self.events.append("heartbeat_start")

    def stop(self) -> None:
        self.events.append("heartbeat_stop")


# -- the quote cycle -------------------------------------------------------


def test_cycle_quotes_two_bids_that_keep_the_pair_invariant():
    cycle = QuoteCycle()
    result = cycle.run(
        [_snapshot()],
        _params(),
        capital_usd=100.0,
        size_shares=20.0,
    )

    assert len(result.intents) == 2
    assert {intent.leg for intent in result.intents} == {"up", "down"}
    assert all(intent.side == "BUY" for intent in result.intents)
    assert all(intent.post_only for intent in result.intents)

    up = next(intent for intent in result.intents if intent.leg == "up")
    down = next(intent for intent in result.intents if intent.leg == "down")
    assert up.price + down.price <= 1.0 - TICK + 1e-9


def test_cycle_holds_the_pair_invariant_across_market_states():
    cycle = QuoteCycle()
    for midpoint in (0.05, 0.2, 0.5, 0.8, 0.95):
        snapshot = _snapshot(midpoint=midpoint)
        result = cycle.run([snapshot], _params(), capital_usd=100.0, size_shares=20.0)
        assert len(result.intents) == 2, midpoint
        up = next(intent for intent in result.intents if intent.leg == "up")
        down = next(intent for intent in result.intents if intent.leg == "down")
        assert up.price + down.price <= 1.0 - snapshot.tick_size + 1e-9


def test_a_hard_stop_removes_both_intents():
    cycle = QuoteCycle()
    result = cycle.run(
        [_snapshot()],
        _params(),
        capital_usd=100.0,
        size_shares=20.0,
        heartbeat_ok=False,
    )

    assert result.intents == []
    assert result.hard_stops == ["0xabc"]
    assert any("hard_stop" in reason for reason in result.rejected)


def test_a_gate_that_blocks_one_leg_keeps_the_other():
    class _BlockUp:
        def evaluate(self, state):
            return (False, True, "cooldown_up_1.0s")

    from pmm.risk.gates import GateStack

    cycle = QuoteCycle(gates=GateStack([_BlockUp()]))
    result = cycle.run([_snapshot()], _params(), capital_usd=100.0, size_shares=20.0)

    assert [intent.leg for intent in result.intents] == ["down"]
    assert any("cooldown_up" in reason for reason in result.rejected)


def test_the_half_spread_comes_from_the_parameter_file():
    snapshot = _snapshot()
    cycle = QuoteCycle()

    narrow = cycle.run([snapshot], _params(half_spread_cents=1.0), capital_usd=100.0, size_shares=20.0)
    wide = cycle.run([snapshot], _params(half_spread_cents=4.5), capital_usd=100.0, size_shares=20.0)

    narrow_up = next(intent for intent in narrow.intents if intent.leg == "up")
    wide_up = next(intent for intent in wide.intents if intent.leg == "up")
    assert wide_up.price < narrow_up.price


def test_the_half_spread_is_clamped_to_the_reward_band():
    snapshot = _snapshot(reward_max_spread_cents=4.5)
    cycle = QuoteCycle()

    clamped = cycle.run([snapshot], _params(half_spread_cents=9.0), capital_usd=100.0, size_shares=20.0)
    at_band = cycle.run([snapshot], _params(half_spread_cents=4.5), capital_usd=100.0, size_shares=20.0)

    clamped_up = next(intent for intent in clamped.intents if intent.leg == "up")
    at_band_up = next(intent for intent in at_band.intents if intent.leg == "up")
    assert clamped_up.price == at_band_up.price


def test_a_market_below_the_rate_floor_is_not_quoted():
    cycle = QuoteCycle(min_rate_per_day=50.0)
    result = cycle.run(
        [_snapshot(rate_per_day=1.0)],
        _params(),
        capital_usd=100.0,
        size_shares=20.0,
    )

    assert result.intents == []
    assert any("rate_per_day" in reason for reason in result.rejected)


# -- the runner ------------------------------------------------------------


def test_shutdown_cancels_the_orders_before_stopping_the_heartbeat(tmp_path):
    executor = _FakeExecutor()
    events = executor.events
    runner = Runner(
        _config(str(tmp_path / "journal")),
        RunnerConfig(capital_usd=100.0, size_shares=20.0),
        params_path=str(tmp_path / "params.json"),
        journal=Journal(tmp_path / "journal"),
        executor=executor,
        heartbeat=_FakeHeartbeat(events),
    )

    runner.shutdown()

    assert events.index("cancel_all") < events.index("heartbeat_stop")
    assert events.index("heartbeat_stop") < events.index("close")


def test_the_runner_refuses_an_intent_that_is_not_post_only():
    intent = QuoteIntent(
        condition_id="0xabc",
        question="q",
        leg="up",
        token_id="111",
        price=0.46,
        size=20.0,
        post_only=False,
    )
    with pytest.raises(ExecutionError):
        Runner._payloads([intent])


def test_the_runner_refuses_an_intent_that_is_not_a_buy():
    intent = QuoteIntent(
        condition_id="0xabc",
        question="q",
        leg="up",
        token_id="111",
        price=0.46,
        size=20.0,
        side="SELL",
    )
    with pytest.raises(ExecutionError):
        Runner._payloads([intent])


def test_the_runner_continues_in_dry_run_without_an_owner_key(tmp_path, caplog):
    executor = _FakeExecutor()
    runner = Runner(
        _config(str(tmp_path / "journal")),
        RunnerConfig(capital_usd=100.0, size_shares=20.0),
        params_path=str(tmp_path / "params.json"),
        journal=Journal(tmp_path / "journal"),
        executor=executor,
        market_source=lambda: [(_snapshot(), None)],
    )

    outcome = runner.run_once()

    assert runner.live_refused is True
    assert outcome["summary"]
    assert len(outcome["intents"]) == 2
    assert all(payload["post_only"] for payload in executor.payloads)


def test_paper_mode_records_the_fill_the_book_would_have_given(tmp_path, monkeypatch):
    # The UP book has 100 shares ahead of the quote, so the taker sell must be
    # larger than that before our 20-share bid fills.
    snapshot = _snapshot(
        midpoint=0.46,
        book_up={"bids": [{"price": "0.50", "size": "100"}], "asks": [{"price": "0.42", "size": "100"}]},
    )
    trade = PublicTrade(
        trade_id="paper-trade",
        condition_id="0xabc",
        token_id="111",
        side="SELL",
        price=0.45,
        size=200.0,
        ts=time.time() + 5.0,
    )
    monkeypatch.setattr("pmm.engine.runner.get_recent_trades", lambda *args, **kwargs: [trade])
    journal = Journal(tmp_path / "journal")
    runner = Runner(
        _config(str(tmp_path / "journal")),
        RunnerConfig(capital_usd=100.0, size_shares=20.0, paper=True),
        params_path=str(tmp_path / "params.json"),
        journal=journal,
        executor=_FakeExecutor(),
        market_source=lambda: [(snapshot, None)],
    )

    runner.run_once()

    fills = journal.fills()
    assert len(fills) == 1
    assert fills[0]["paper"] is True
    assert fills[0]["outcome"] == "Up"
    assert fills[0]["side"] == "BUY"
    assert fills[0]["trade_id"] == "paper-trade"


def test_a_network_error_does_not_take_the_service_down(tmp_path):
    calls = {"n": 0}

    def _failing_source():
        calls["n"] += 1
        if calls["n"] >= 3:
            runner.stop()
        raise CLOBError("network is down", status=None, body="timeout")

    journal = Journal(tmp_path / "journal")
    runner = Runner(
        _config(str(tmp_path / "journal")),
        RunnerConfig(capital_usd=100.0, size_shares=20.0, interval_seconds=0.0),
        params_path=str(tmp_path / "params.json"),
        journal=journal,
        executor=_FakeExecutor(),
        market_source=_failing_source,
    )

    runner.run_forever()

    errors = [record for record in journal.read_all() if record.get("kind") == "error"]
    assert calls["n"] >= 3
    assert len(errors) == calls["n"]
    assert all("network is down" in record["error"] for record in errors)


# -- the self-tune step ----------------------------------------------------


def test_self_tune_writes_a_parameter_file_the_next_cycle_reads(tmp_path):
    journal = Journal(tmp_path / "journal")
    params_path = tmp_path / "params.json"
    reports_dir = tmp_path / "reports"

    result = run_self_tune(journal, _params(), params_path, reports_dir)

    written = json.loads(Path(result["params_path"]).read_text(encoding="utf-8"))
    assert set(DEFAULT_PARAMS).issubset(written.keys())
    assert written["half_spread_cents"] == pytest.approx(DEFAULT_PARAMS["half_spread_cents"])
    assert Path(result["report_path"]).is_file()

    on_disk = load_params(params_path)
    assert on_disk["half_spread_cents"] == written["half_spread_cents"]

    snapshot = _snapshot(reward_max_spread_cents=1.0)
    cycle = QuoteCycle()
    from_params = cycle.run([snapshot], on_disk, capital_usd=100.0, size_shares=20.0)
    assert len(from_params.intents) == 2


def test_self_tune_is_safe_with_an_empty_journal(tmp_path):
    journal = Journal(tmp_path / "journal")
    result = run_self_tune(journal, _params(), tmp_path / "params.json", tmp_path / "reports")

    assert result["fill_count"] == 0
    assert Path(result["params_path"]).is_file()
    assert Path(result["report_path"]).is_file()
    assert load_params(result["params_path"])["quoting_enabled"] is True


def test_self_tune_stops_quoting_when_the_roll_capture_is_negative(tmp_path):
    journal = Journal(tmp_path / "journal")
    journal.append(
        "fill",
        condition_id="0xabc",
        token_id="111",
        outcome="Up",
        side="BUY",
        price=0.5,
        size=20.0,
        notional=10.0,
        pnl=-0.01,
    )
    result = run_self_tune(journal, _params(), tmp_path / "params.json", tmp_path / "reports")

    assert result["changed"] is True
    assert result["params"]["quoting_enabled"] is False
    assert load_params(result["params_path"])["quoting_enabled"] is False


def test_writing_the_parameters_is_atomic(tmp_path):
    params_path = tmp_path / "params.json"
    write_params(params_path, _params(half_spread_cents=2.5))

    assert json.loads(params_path.read_text(encoding="utf-8"))["half_spread_cents"] == 2.5
    assert [path.name for path in tmp_path.iterdir()] == ["params.json"]


def test_the_balance_guard_drops_the_leg_it_cannot_fund():
    up = QuoteIntent(
        condition_id="0xabc", question="q", leg="up", token_id="111", price=0.46, size=20.0
    )
    down = QuoteIntent(
        condition_id="0xabc", question="q", leg="down", token_id="222", price=0.52, size=20.0
    )

    # 9.2 + 10.4 = 19.6, so 19.6 fits exactly and 15.0 only pays for the first leg.
    assert Runner._affordable([up, down], balance_pusd=19.6) == ([up, down], [])
    kept, dropped = Runner._affordable([up, down], balance_pusd=15.0)
    assert kept == [up]
    assert dropped == [down]
    assert Runner._affordable([up, down], balance_pusd=None) == ([up, down], [])


def test_the_runner_skips_an_unaffordable_leg_instead_of_sending_it(tmp_path):
    class _BudgetExecutor(_FakeExecutor):
        def collateral_balance(self):
            return 10.0

    snapshot = _snapshot(midpoint=0.46)
    journal = Journal(tmp_path / "journal")
    runner = Runner(
        ExecutionConfig(dry_run=False, journal_path=str(tmp_path / "journal"), owner_pk="0x" + "11" * 32),
        RunnerConfig(capital_usd=100.0, size_shares=20.0),
        params_path=str(tmp_path / "params.json"),
        journal=journal,
        executor=_BudgetExecutor(),
        market_source=lambda: [(snapshot, None)],
    )

    runner.run_once()

    payloads = runner.executor.payloads
    assert len(payloads) == 1, payloads
    skipped = [
        record for record in journal.read_all() if record.get("kind") == "order_skipped"
    ]
    assert skipped and skipped[0]["reason"] == "insufficient_collateral"


def test_live_inventory_is_read_from_the_venue_not_the_journal(tmp_path):
    # A live fill never reaches the journal, so the journal would say "flat".
    snapshot = _snapshot()
    runner = Runner(
        ExecutionConfig(
            dry_run=False,
            journal_path=str(tmp_path / "journal"),
            owner_pk="0x" + "11" * 32,
        ),
        RunnerConfig(capital_usd=100.0, size_shares=20.0),
        params_path=str(tmp_path / "params.json"),
        journal=Journal(tmp_path / "journal"),
        executor=_FakeExecutor(),
        positions_source=lambda: {snapshot.up_token_id: 20.0},
    )

    inventory = runner._inventory([(snapshot, None)])

    position = inventory[snapshot.condition_id]
    assert position.up_shares == 20.0
    assert position.down_shares == 0.0
