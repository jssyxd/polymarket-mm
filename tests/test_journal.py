"""Journal and PnL tests."""

from __future__ import annotations

import sys
from datetime import date, datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.execution.journal import Journal, compute_pnl, win_rate  # noqa: E402

UP_TOKEN = "111"
DOWN_TOKEN = "222"
CONDITION = "0xcondition"


def _fill(token_id, outcome, side, price, size, condition=CONDITION):
    return {
        "kind": "fill",
        "token_id": token_id,
        "condition_id": condition,
        "outcome": outcome,
        "side": side,
        "price": price,
        "size": size,
    }


def test_journal_appends_and_reads_by_day(tmp_path):
    journal = Journal(tmp_path / "journal")
    journal.append("order_intent", reason="test", payload={"side": "BUY"})
    journal.append("fill", token_id=UP_TOKEN, side="BUY", price=0.49, size=5)

    today = datetime.now(timezone.utc).date()
    records = journal.read_day(today)
    assert [record["kind"] for record in records] == ["order_intent", "fill"]
    assert all("ts" in record for record in records)
    assert records[0]["ts"].endswith("+00:00") or records[0]["ts"].endswith("Z")

    assert journal.read_day(date(1999, 1, 1)) == []


def test_journal_day_file_is_one_file_per_day(tmp_path):
    journal = Journal(tmp_path / "journal")
    journal.append("cancel", order_id="0xabc")
    files = list((tmp_path / "journal").glob("*.jsonl"))
    assert len(files) == 1
    assert files[0].name.endswith(".jsonl")


def test_compute_pnl_merged_pair_is_worth_one_pusd():
    """Holding both legs: the pair is worth 1 pUSD, the surplus at its mark."""
    fills = [
        _fill(UP_TOKEN, "Up", "BUY", 0.45, 100),
        _fill(DOWN_TOKEN, "Down", "BUY", 0.50, 60),
    ]
    marks = {UP_TOKEN: 0.55, DOWN_TOKEN: 0.40}

    pnl = compute_pnl(fills, marks)

    position = pnl["positions"][CONDITION]
    assert position["up_shares"] == 100
    assert position["down_shares"] == 60
    assert position["paired_shares"] == 60
    # 60 complete sets at 1.0 each plus 40 unpaired up shares at 0.55.
    assert position["position_value"] == 60 * 1.0 + 40 * 0.55
    assert pnl["position_value"] == 60 * 1.0 + 40 * 0.55
    # Cost basis is 100 * 0.45 + 60 * 0.50.
    assert pnl["cost_basis"] == 100 * 0.45 + 60 * 0.50
    assert pnl["unrealized_pnl"] == pytest_approx(
        (60 * 1.0 + 40 * 0.55) - (100 * 0.45 + 60 * 0.50)
    )
    assert pnl["realized_pnl"] == 0.0


def test_compute_pnl_realized_from_a_sold_leg():
    fills = [
        _fill(UP_TOKEN, "Up", "BUY", 0.45, 100),
        _fill(UP_TOKEN, "Up", "SELL", 0.55, 100),
    ]
    pnl = compute_pnl(fills, {UP_TOKEN: 0.55, DOWN_TOKEN: 0.45})
    assert pnl["realized_pnl"] == pytest_approx(10.0)
    assert pnl["positions"][CONDITION]["up_shares"] == 0
    assert pnl["position_value"] == 0.0


def test_compute_pnl_merging_a_pair_realizes_one_pusd():
    """Both legs bought then merged: the pair returns exactly 1 pUSD."""
    fills = [
        _fill(UP_TOKEN, "Up", "BUY", 0.49, 100),
        _fill(DOWN_TOKEN, "Down", "BUY", 0.49, 100),
        _fill(UP_TOKEN, "Up", "SELL", 0.50, 100),
        _fill(DOWN_TOKEN, "Down", "SELL", 0.50, 100),
    ]
    pnl = compute_pnl(fills, {UP_TOKEN: 0.50, DOWN_TOKEN: 0.50})
    assert pnl["realized_pnl"] == pytest_approx(2.0)
    assert pnl["positions"][CONDITION]["paired_shares"] == 0


def test_win_rate_counts_a_merged_pair_as_one_round_trip():
    fills = [
        _fill(UP_TOKEN, "Up", "BUY", 0.49, 100),
        _fill(DOWN_TOKEN, "Down", "BUY", 0.49, 100),
        _fill(UP_TOKEN, "Up", "SELL", 0.50, 100),
        _fill(DOWN_TOKEN, "Down", "SELL", 0.50, 100),
    ]
    # Two legs, one merged pair, one round trip, positive.
    assert win_rate(fills) == 1.0


def test_win_rate_is_zero_without_a_closed_round_trip():
    fills = [_fill(UP_TOKEN, "Up", "BUY", 0.45, 100)]
    assert win_rate(fills) == 0.0


def test_win_rate_separate_legs_are_two_round_trips():
    fills = [
        _fill(UP_TOKEN, "Up", "BUY", 0.45, 100),
        _fill(UP_TOKEN, "Up", "SELL", 0.50, 100),
        _fill(DOWN_TOKEN, "Down", "BUY", 0.45, 100),
        _fill(DOWN_TOKEN, "Down", "SELL", 0.40, 100),
    ]
    # One winning round trip and one losing one.
    assert win_rate(fills) == 0.5


def test_pnl_is_computed_from_the_journal(tmp_path):
    journal = Journal(tmp_path / "journal")
    journal.append(
        "fill",
        token_id=UP_TOKEN,
        condition_id=CONDITION,
        outcome="Up",
        side="BUY",
        price=0.45,
        size=100,
    )
    journal.append(
        "fill",
        token_id=DOWN_TOKEN,
        condition_id=CONDITION,
        outcome="Down",
        side="BUY",
        price=0.50,
        size=60,
    )

    fills = journal.fills()
    assert len(fills) == 2

    pnl = compute_pnl(fills, {UP_TOKEN: 0.55, DOWN_TOKEN: 0.40})
    assert pnl["position_value"] == pytest_approx(60 * 1.0 + 40 * 0.55)
    assert pnl["cost_basis"] == pytest_approx(100 * 0.45 + 60 * 0.50)


def test_journal_records_pnl_and_position_snapshots(tmp_path):
    journal = Journal(tmp_path / "journal")
    journal.record_pnl({"realized_pnl": 1.0, "unrealized_pnl": 2.0, "total_pnl": 3.0})
    journal.record_position({"up_shares": 10}, scope="all")

    kinds = [record["kind"] for record in journal.read_day(datetime.now(timezone.utc).date())]
    assert kinds == ["pnl_update", "position"]


def test_journal_lines_carry_no_secret(tmp_path):
    journal = Journal(tmp_path / "journal")
    journal.append("order_intent", payload={"side": "BUY", "size": 5})
    line = (tmp_path / "journal").glob("*.jsonl").__next__().read_text()
    assert "secret" not in line.lower()
    assert "passphrase" not in line.lower()


def pytest_approx(value):
    import pytest

    return pytest.approx(value, rel=1e-9, abs=1e-9)
