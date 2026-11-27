"""Turn the invariants that matter into alerts, not into a post-mortem.

The first live run lost money that no monitor would have announced: nothing
watched the ratio of unpaired exposure, the cash floor, or how much of the
flow was one-sided. These checks are deliberately few and cheap.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Sequence

__all__ = ["Alert", "evaluate", "timer_alerts"]

#: Below this much free collateral the loop cannot fund a paired order.
CASH_FLOOR = 20.0

#: Above this share of one-sided fills the pair premise is not holding.
MAX_SINGLE_LEG_SHARE = 0.5


@dataclass(frozen=True)
class Alert:
    kind: str
    detail: str


def evaluate(
    positions: Iterable[Mapping[str, Any]],
    *,
    cash: float,
    open_orders: int,
    inventory_box: float,
    fills: Sequence[Mapping[str, Any]] = (),
    window_fills: int = 200,
) -> list[Alert]:
    """Check the four conditions that would have flagged the last loss."""
    alerts: list[Alert] = []
    legs: dict[str, dict[int, float]] = {}
    for row in positions:
        condition_id = str(row.get("condition_id") or "")
        size = float(row.get("current_size") or 0.0)
        if not condition_id or size <= 0:
            continue
        try:
            index = int(row.get("outcome_index"))
        except (TypeError, ValueError):
            continue
        legs.setdefault(condition_id, {})[index] = size

    for condition_id, pair in legs.items():
        excess = abs(pair.get(0, 0.0) - pair.get(1, 0.0))
        if inventory_box > 0 and excess > inventory_box:
            alerts.append(
                Alert(
                    "unpaired_exposure",
                    f"{condition_id[:10]}: {excess:.1f} shares unpaired, "
                    f"above the box {inventory_box:.0f}",
                )
            )

    if cash < CASH_FLOOR and open_orders == 0:
        alerts.append(
            Alert(
                "starved",
                f"{cash:.2f} pUSD free with no resting orders: the loop cannot quote",
            )
        )

    recent = list(fills)[-window_fills:]
    if len(recent) >= 10:
        by_market: dict[str, set[int]] = {}
        for fill in recent:
            condition_id = str(fill.get("condition_id") or "")
            outcome = str(fill.get("outcome") or "").lower()
            index = 0 if outcome in ("yes", "up", "higher") else 1
            by_market.setdefault(condition_id, set()).add(index)
        single = sum(1 for legs_seen in by_market.values() if len(legs_seen) == 1)
        share = single / len(by_market) if by_market else 0.0
        if share > MAX_SINGLE_LEG_SHARE:
            alerts.append(
                Alert(
                    "single_leg_flow",
                    f"{single}/{len(by_market)} traded markets filled only one leg "
                    f"({share:.0%}): the pair premise is not holding",
                )
            )
    return alerts


def timer_alerts(states: Mapping[str, str], required: Sequence[str]) -> list[Alert]:
    """A recycling timer that is not active is a silent capital leak.

    `pmm-merge.timer` was observed dead for 47 minutes with `Trigger: n/a`
    after a single run. Nothing noticed, because nothing watched the timers
    themselves.
    """
    alerts: list[Alert] = []
    for unit in required:
        state = str(states.get(unit) or "unknown")
        if state != "active":
            alerts.append(
                Alert("timer_inactive", f"{unit} is {state}: recycling is not scheduled")
            )
    return alerts
