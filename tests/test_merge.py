"""The merge step: which markets have a complete pair, and what it does."""

from __future__ import annotations

from pmm.execution.config import ExecutionConfig
from pmm.execution.merge import MergeTarget, balanced_pairs, merge_pairs


def _row(condition_id: str, index: int, size: float, title: str = "market") -> dict:
    return {
        "condition_id": condition_id,
        "outcome_index": index,
        "current_size": size,
        "title": title,
    }


def test_only_markets_holding_both_legs_above_the_floor_are_merged():
    positions = [
        _row("A", 0, 20.0),
        _row("A", 1, 13.79),
        _row("B", 0, 20.0),
        _row("C", 0, 3.0),
        _row("C", 1, 7.0),
    ]

    assert balanced_pairs(positions) == [MergeTarget("A", "market", 13.79)]


class _Handle:
    def __init__(self) -> None:
        self.waited = False

    def wait(self) -> None:
        self.waited = True


class _Client:
    def __init__(self, fail: bool = False) -> None:
        self.calls: list[dict] = []
        self.handles: list[_Handle] = []
        self.fail = fail

    def merge_positions(self, **kwargs):
        self.calls.append(kwargs)
        if self.fail:
            raise RuntimeError("relayer said no")
        handle = _Handle()
        self.handles.append(handle)
        return handle


def test_a_dry_run_reports_targets_and_merges_nothing():
    client = _Client()
    config = ExecutionConfig(dry_run=True)

    results = merge_pairs(
        config, positions=[_row("A", 0, 20.0), _row("A", 1, 10.0)], client=client
    )

    assert results == [{"condition_id": "A", "size": 10.0, "status": "dry_run"}]
    assert client.calls == []


def test_the_merge_is_sent_and_waited_on():
    client = _Client()
    config = ExecutionConfig(dry_run=False, owner_pk="0x" + "11" * 32)

    results = merge_pairs(
        config, positions=[_row("A", 0, 20.0), _row("A", 1, 10.0)], client=client
    )

    assert client.calls[0]["condition_id"] == "A"
    assert client.calls[0]["amount"] == "max"
    assert client.handles[0].waited is True
    assert results == [{"condition_id": "A", "size": 10.0, "status": "merged"}]


def test_one_failed_merge_does_not_stop_the_next_market():
    calls: list[str] = []

    class _Flaky:
        def merge_positions(self, **kwargs):
            calls.append(kwargs["condition_id"])
            if kwargs["condition_id"] == "A":
                raise RuntimeError("relayer said no")
            return _Handle()

    config = ExecutionConfig(dry_run=False, owner_pk="0x" + "11" * 32)
    positions = [
        _row("A", 0, 20.0),
        _row("A", 1, 10.0),
        _row("B", 0, 20.0),
        _row("B", 1, 10.0),
    ]

    results = merge_pairs(config, positions=positions, client=_Flaky())

    assert calls == ["A", "B"]
    assert [r["status"].startswith("failed") for r in results] == [True, False]
