"""Tests for the hourly monitor agent and the report writer.

No network, no credentials, standard library only.
"""

from __future__ import annotations

import sys
from datetime import datetime, timezone
from pathlib import Path

import pytest

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.monitor import MonitorAgent, read_reports, write_report  # noqa: E402
from pmm.risk import MarketState  # noqa: E402

NOW = 1_700_000_000.0


def _state(**overrides) -> MarketState:
    base = {
        "up_shares": 0.0,
        "down_shares": 0.0,
        "max_inventory_per_side": 100.0,
        "now": NOW,
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


def _fill(pnl: float, notional: float = 100.0, ts: float = NOW - 60.0) -> dict:
    return {"notional": notional, "pnl": pnl, "ts": ts}


def _params(**overrides) -> dict:
    base = {
        "quoting_enabled": True,
        "half_spread_cents": 1.0,
        "max_spread_cents": 4.5,
        "inventory_box": 100.0,
    }
    base.update(overrides)
    return base


class TestStopRule:
    def test_stops_quoting_when_capture_is_negative(self) -> None:
        agent = MonitorAgent()
        fills = [_fill(-0.004) for _ in range(100)]
        decision = agent.run_once(_state(), fills, _params())
        assert decision["changed"] is True
        assert decision["param"] == "quoting_enabled"
        assert decision["from_value"] is True
        assert decision["to_value"] is False
        assert decision["action"] == "stop"
        assert "at_or_below_zero" in decision["reason"]

    def test_stops_when_capture_is_exactly_zero(self) -> None:
        agent = MonitorAgent()
        decision = agent.run_once(_state(), [_fill(0.0) for _ in range(100)], _params())
        assert decision["param"] == "quoting_enabled"
        assert decision["to_value"] is False

    def test_never_raises_the_inventory_box_while_losing(self) -> None:
        agent = MonitorAgent()
        fills = [_fill(-0.004) for _ in range(100)]
        state = _state(up_shares=60.0)
        decision = agent.run_once(state, fills, _params())
        assert decision["param"] != "inventory_box"
        assert decision["to_value"] != 125.0

    def test_already_stopped_makes_no_change(self) -> None:
        agent = MonitorAgent()
        fills = [_fill(-0.004) for _ in range(100)]
        decision = agent.run_once(
            _state(), fills, _params(quoting_enabled=False)
        )
        assert decision["changed"] is False
        assert decision["param"] == "quoting_enabled"
        assert decision["to_value"] is False

    def test_no_fills_is_not_read_as_a_loss(self) -> None:
        agent = MonitorAgent()
        decision = agent.run_once(_state(), [], _params())
        assert decision["param"] != "quoting_enabled"

    def test_no_widen_when_the_maker_was_not_quoting(self) -> None:
        # Zero intents in the last hour means there is no evidence about the
        # spread, so the spread must not move.
        agent = MonitorAgent()
        decision = agent.run_once(_state(), [], _params(), intents_last_hour=0)
        assert decision["changed"] is False
        assert decision["param"] is None


class TestWidenRule:
    def test_widens_one_cent_when_the_market_did_not_fill(self) -> None:
        agent = MonitorAgent()
        old = [_fill(0.01, ts=NOW - 7200.0) for _ in range(100)]
        decision = agent.run_once(_state(), old, _params())
        assert decision["changed"] is True
        assert decision["param"] == "half_spread_cents"
        assert decision["from_value"] == 1.0
        assert decision["to_value"] == 2.0
        assert "no_fills_in_last_hour" in decision["reason"]

    def test_never_widens_past_the_reward_band(self) -> None:
        agent = MonitorAgent()
        old = [_fill(0.01, ts=NOW - 7200.0) for _ in range(100)]
        decision = agent.run_once(
            _state(), old, _params(half_spread_cents=4.5, max_spread_cents=4.5)
        )
        assert decision["changed"] is False
        assert decision["to_value"] <= 4.5

    def test_does_not_widen_when_the_reward_band_is_unknown(self) -> None:
        agent = MonitorAgent()
        old = [_fill(0.01, ts=NOW - 7200.0) for _ in range(100)]
        params = _params()
        params["max_spread_cents"] = 0.0
        decision = agent.run_once(_state(), old, params)
        assert decision["changed"] is False
        assert decision["to_value"] == 1.0

    def test_widen_is_capped_inside_the_reward_band(self) -> None:
        agent = MonitorAgent()
        old = [_fill(0.01, ts=NOW - 7200.0) for _ in range(100)]
        decision = agent.run_once(
            _state(), old, _params(half_spread_cents=4.0, max_spread_cents=4.5)
        )
        # 4.0 is already past the 80 percent cap, so the spread is held
        # rather than widened. A quote at the band edge scores exactly zero.
        assert decision["changed"] is False
        assert decision["to_value"] == 4.0

        decision = agent.run_once(
            _state(), old, _params(half_spread_cents=3.0, max_spread_cents=4.5)
        )
        assert decision["to_value"] == 3.6

    def test_does_not_widen_when_the_account_cannot_quote(self) -> None:
        agent = MonitorAgent()
        old = [_fill(0.01, ts=NOW - 7200.0) for _ in range(100)]
        decision = agent.run_once(
            _state(heartbeat_ok=False), old, _params(quoting_enabled=True)
        )
        assert decision["param"] != "half_spread_cents"

    def test_does_not_widen_a_market_that_is_closed_to_quoting(self) -> None:
        agent = MonitorAgent()
        old = [_fill(0.01, ts=NOW - 7200.0) for _ in range(100)]
        decision = agent.run_once(_state(tau_seconds=10.0), old, _params())
        assert decision["param"] != "half_spread_cents"

    def test_does_not_raise_the_box_on_a_market_closed_to_quoting(self) -> None:
        agent = MonitorAgent()
        fills = [_fill(0.01) for _ in range(100)]
        state = _state(up_shares=60.0, tau_seconds=10.0)
        decision = agent.run_once(state, fills, _params())
        assert decision["param"] != "inventory_box"


class TestRaiseBoxRule:
    def test_raises_the_box_by_25_percent_when_profitable_and_busy(self) -> None:
        agent = MonitorAgent()
        fills = [_fill(0.01) for _ in range(100)]
        state = _state(up_shares=60.0)
        decision = agent.run_once(state, fills, _params())
        assert decision["changed"] is True
        assert decision["param"] == "inventory_box"
        assert decision["from_value"] == 100.0
        assert decision["to_value"] == pytest.approx(125.0)

    def test_one_step_never_exceeds_25_percent(self) -> None:
        agent = MonitorAgent()
        fills = [_fill(0.01) for _ in range(100)]
        state = _state(up_shares=600.0, max_inventory_per_side=1000.0)
        decision = agent.run_once(state, fills, _params(inventory_box=1000.0))
        assert decision["param"] == "inventory_box"
        assert decision["to_value"] <= decision["from_value"] * 1.25
        assert decision["to_value"] == pytest.approx(1250.0)

    def test_does_not_raise_the_box_below_half_full(self) -> None:
        agent = MonitorAgent()
        fills = [_fill(0.01) for _ in range(100)]
        state = _state(up_shares=40.0)
        decision = agent.run_once(state, fills, _params())
        assert decision["param"] != "inventory_box"
        assert decision["changed"] is False


class TestHoldRule:
    def test_changes_nothing_when_no_rule_fires(self) -> None:
        agent = MonitorAgent()
        fills = [_fill(0.01) for _ in range(100)]
        state = _state(up_shares=10.0)
        decision = agent.run_once(state, fills, _params())
        assert decision["changed"] is False
        assert decision["param"] is None
        assert decision["action"] == "hold"

    def test_the_record_carries_the_metrics_it_saw(self) -> None:
        agent = MonitorAgent()
        fills = [_fill(-0.004) for _ in range(100)]
        decision = agent.run_once(_state(up_shares=100.0), fills, _params())
        metrics = decision["metrics"]
        assert metrics["rolling_net_bps"] == pytest.approx(-0.4)
        assert metrics["fill_count"] == 100
        assert metrics["fills_last_hour"] == 100
        assert metrics["inventory_exposure"] == pytest.approx(50.0)
        assert metrics["pair_coverage"] == 0.0


class TestReport:
    def test_writes_the_three_sections(self, tmp_path: Path) -> None:
        path = str(tmp_path / "report.md")
        payload = {
            "timestamp": "2026-11-21T10:00:00+00:00",
            "metrics": {"rolling_net_bps": -0.4},
            "decision": {
                "changed": True,
                "param": "quoting_enabled",
                "from_value": True,
                "to_value": False,
                "reason": "rolling_net_bps_-0.40_at_or_below_zero_freeze_quoting",
            },
            "state": {"up_shares": 60.0},
        }
        write_report(path, payload)
        text = Path(path).read_text()
        assert "## Metrics" in text
        assert "## Decision" in text
        assert "## State" in text
        assert "rolling_net_bps" in text

    def test_never_writes_a_credential(self, tmp_path: Path) -> None:
        path = str(tmp_path / "report.md")
        payload = {
            "timestamp": "2026-11-21T10:00:00+00:00",
            "metrics": {"api_key": "SECRET", "rolling_net_bps": -0.4},
            "decision": {"reason": "ok", "passphrase": "hunter2"},
            "state": {"private_key": "0xdead", "equity_usd": 3.4},
        }
        write_report(path, payload)
        text = Path(path).read_text()
        assert "SECRET" not in text
        assert "hunter2" not in text
        assert "0xdead" not in text

    def test_reads_the_last_day_back(self, tmp_path: Path) -> None:
        # The timestamp has to be now: the reader keeps the last 24 hours, so a
        # hardcoded date makes this test fail the day after it is written.
        payload = {
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "metrics": {"rolling_net_bps": -0.4},
            "decision": {"changed": True},
            "state": {},
        }
        write_report(str(tmp_path / "a.md"), payload)
        reports = read_reports(str(tmp_path))
        assert len(reports) == 1
        assert reports[0]["metrics"]["rolling_net_bps"] == -0.4

    def test_ignores_reports_older_than_a_day(self, tmp_path: Path) -> None:
        payload = {
            "timestamp": "2020-01-01T00:00:00+00:00",
            "metrics": {},
            "decision": {},
            "state": {},
        }
        write_report(str(tmp_path / "old.md"), payload)
        assert read_reports(str(tmp_path)) == []
