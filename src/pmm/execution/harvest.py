"""Plan B, standing by: turn a nearly-won leg into cash with a 99c sell.

Rule A (rescue) completes a set by buying the cheap leg and merging for 1.00.
It only works when the completion clears the venue's $1 notional and stays at
or below the cheap leg's own mark. A large winner whose complement is marked
far below 1c per share cannot be completed that way, and its capital stays
locked until the market resolves.

Plan B is the fallback: rest a post-only sell near the top of the book. It
returns 0.99 per share instead of 1.00 — a 1% haircut — and buys back the
capital immediately.

Nothing calls this yet. It exists so the exit path is designed, tested and
reviewable before it is armed, and so the SELL invariants in
`Runner._payloads` have a producer to validate against.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional

__all__ = ["HarvestPlan", "HARVEST_MIN_PRICE", "plan_harvests"]

#: The lowest price a harvest sell may rest at.
HARVEST_MIN_PRICE = 0.99

#: The venue's minimum order size.
MIN_ORDER_SIZE = 5.0


@dataclass(frozen=True)
class HarvestPlan:
    """One post-only sell that converts a nearly-won leg into cash."""

    condition_id: str
    title: str
    token_id: str
    size: float
    price: float
    mark: float
    avg_cost: float

    @property
    def profit_per_share(self) -> float:
        return self.price - self.avg_cost


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def plan_harvests(
    positions: Iterable[Mapping[str, Any]],
    *,
    open_assets: Iterable[str] = (),
    min_price: float = HARVEST_MIN_PRICE,
    min_size: float = MIN_ORDER_SIZE,
) -> list[HarvestPlan]:
    """Which held legs could be sold at the floor instead of held to resolution.

    A plan is emitted only when all of these hold:

    * the leg is held with a size at or above the venue minimum;
    * its mark is at or above `min_price`;
    * selling at `min_price` is still profitable against the entry cost;
    * no order is already resting on that token.
    """
    resting = {str(asset) for asset in open_assets}
    plans: list[HarvestPlan] = []
    for row in positions:
        if not isinstance(row, Mapping):
            continue
        token_id = str(row.get("token_id") or "")
        size = _f(row.get("current_size"))
        mark = _f(row.get("current_price"))
        cost = _f(row.get("avg_price"), mark)
        if not token_id or size < min_size or mark < min_price:
            continue
        if token_id in resting:
            continue
        if min_price <= cost:
            continue  # no profit at the floor
        plans.append(
            HarvestPlan(
                condition_id=str(row.get("condition_id") or ""),
                title=str(row.get("title") or ""),
                token_id=token_id,
                size=size,
                price=min_price,
                mark=mark,
                avg_cost=cost,
            )
        )
    return plans
