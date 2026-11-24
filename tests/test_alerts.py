"""The alerts that would have caught the first live loss."""

from __future__ import annotations

from pmm.monitor.alerts import evaluate


def _pos(u=0.0, d=0.0, condition="0xcond"):
    rows = []
    if u:
        rows.append({"condition_id": condition, "outcome_index": 0, "current_size": u})
    if d:
        rows.append({"condition_id": condition, "outcome_index": 1, "current_size": d})
    return rows


def test_a_balanced_book_with_cash_is_quiet():
    assert evaluate(_pos(u=20, d=20), cash=40.0, open_orders=2, inventory_box=40) == []


def test_unpaired_exposure_beyond_the_box_alerts():
    alerts = evaluate(_pos(u=80, d=20), cash=40.0, open_orders=2, inventory_box=40)

    assert [a.kind for a in alerts] == ["unpaired_exposure"]


def test_cash_without_orders_alerts():
    alerts = evaluate(_pos(u=20, d=20), cash=5.0, open_orders=0, inventory_box=40)

    assert [a.kind for a in alerts] == ["starved"]


def test_mostly_one_sided_flow_alerts():
    fills = []
    for i in range(12):
        fills.append({"condition_id": f"0x{i}", "outcome": "Yes", "side": "BUY"})
    alerts = evaluate(
        [], cash=40.0, open_orders=1, inventory_box=40, fills=fills
    )

    assert [a.kind for a in alerts] == ["single_leg_flow"]
