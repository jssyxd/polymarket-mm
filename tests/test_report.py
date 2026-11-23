"""The report summarises what the journal says, not what the loop hoped."""

from __future__ import annotations

from pmm.execution.journal import Journal
from tools.report import summarise


def _fill(journal, **fields):
    journal.append("fill", **fields)


def test_a_paired_position_is_valued_at_one_per_set(tmp_path):
    journal = Journal(tmp_path / "journal")
    _fill(journal, condition_id="0xabc", token_id="U", outcome="Yes", side="BUY",
          price=0.50, size=20.0, notional=10.0, ts=1795437000, fill_id="t1:o1")
    _fill(journal, condition_id="0xabc", token_id="D", outcome="No", side="BUY",
          price=0.45, size=20.0, notional=9.0, ts=1795437100, fill_id="t2:o2")

    summary = summarise(journal, marks={"U": 0.52, "D": 0.47})

    assert summary["fills"] == 2
    assert summary["notional"] == 19.0
    assert summary["sides"] == {"BUY": 2}
    assert summary["position_value"] == 20.0, "a complete set is worth 1.00 each"
    assert summary["markets"] == 1


def test_the_day_filter_keeps_only_that_utc_day(tmp_path):
    journal = Journal(tmp_path / "journal")
    _fill(journal, condition_id="0xabc", token_id="U", outcome="Yes", side="BUY",
          price=0.50, size=20.0, notional=10.0, ts=1795437000, fill_id="t1:o1")
    _fill(journal, condition_id="0xabc", token_id="U", outcome="Yes", side="BUY",
          price=0.50, size=10.0, notional=5.0, ts=1795350600, fill_id="t0:o0")

    assert summarise(journal, marks={}, day="2026-11-23")["fills"] == 1
    assert summarise(journal, marks={})["fills"] == 2


def test_a_merge_is_realized_and_removes_the_inventory(tmp_path):
    journal = Journal(tmp_path / "journal")
    _fill(journal, condition_id="0xabc", token_id="U", outcome="Yes", side="BUY",
          price=0.50, size=20.0, notional=10.0, ts=1795437000, fill_id="t1:o1")
    _fill(journal, condition_id="0xabc", token_id="D", outcome="No", side="BUY",
          price=0.45, size=20.0, notional=9.0, ts=1795437100, fill_id="t2:o2")
    journal.append("merge", condition_id="0xabc", side="MERGE", size=20.0, price=1.0,
                   notional=20.0, reason="complete_set")

    summary = summarise(journal, marks={"U": 0.52, "D": 0.47})

    assert summary["position_value"] == 0.0, "the merged shares are gone"
    assert summary["realized"] == 1.0, "20 sets bought for 0.95 redeem for 1.00"
