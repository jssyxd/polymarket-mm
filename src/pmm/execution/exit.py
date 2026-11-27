"""Forced exit for a leg that has stood alone too long.

Repair closes a pair only when the missing ask keeps the pair at or below
1 pUSD. When it does not, the leg is a directional bet. After a bounded age
the only honest action is to sell it at the best bid and take the loss now,
rather than carry it into settlement.

The planner is pure. The tool that calls it is dry-run by default and requires
POLY_EXIT=1 for a live sell.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping

__all__ = ["ExitPlan", "DEFAULT_MAX_AGE_SECONDS", "plan_exits"]

#: A leg alone longer than this is a bet, not a maker position.
DEFAULT_MAX_AGE_SECONDS = 60.0

#: The venue minimum order size.
MIN_ORDER_SIZE = 5.0


@dataclass(frozen=True)
class ExitPlan:
    condition_id: str
    title: str
    token_id: str
    size: float
    price: float
    avg_cost: float
    age_seconds: float
    pair_cost: float | None


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _token(row: Mapping[str, Any]) -> str:
    for key in ("token_id", "asset_id", "asset"):
        value = row.get(key)
        if value:
            return str(value)
    return ""


def _first_entry(row: Mapping[str, Any]) -> float:
    for key in ("first_entry_at", "first_entry_ts", "first_fill_at", "created_at"):
        value = row.get(key)
        parsed = _f(value)
        if parsed > 0:
            return parsed
    return 0.0


def plan_exits(
    positions: Iterable[Mapping[str, Any]],
    *,
    best_bids: Mapping[str, float],
    complement_asks: Mapping[str, float] | None = None,
    open_assets: Iterable[str] = (),
    entry_times: Mapping[str, float] | None = None,
    now: float,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    min_size: float = MIN_ORDER_SIZE,
) -> list[ExitPlan]:
    """Single legs old enough to exit, where a riskless repair is unavailable."""
    resting = {str(asset) for asset in open_assets}
    clocks = entry_times or {}
    by_condition: dict[str, list[Mapping[str, Any]]] = {}
    for row in positions:
        if not isinstance(row, Mapping):
            continue
        condition_id = str(row.get("condition_id") or "")
        if not condition_id or _f(row.get("current_size")) <= 0:
            continue
        by_condition.setdefault(condition_id, []).append(row)

    asks = complement_asks or {}
    plans: list[ExitPlan] = []
    for condition_id, legs in by_condition.items():
        if len(legs) != 1:
            continue
        row = legs[0]
        size = _f(row.get("current_size"))
        if size < min_size:
            continue
        token_id = _token(row)
        if not token_id or token_id in resting:
            continue
        entered = _f(clocks.get(token_id)) or _f(clocks.get(condition_id)) or _first_entry(row)
        age = max(0.0, now - entered) if entered > 0 else 0.0
        if age < max_age_seconds:
            continue
        ask = _f(asks.get(condition_id))
        pair_cost = (_f(row.get("avg_price")) + ask) if ask > 0 else None
        if pair_cost is not None and pair_cost <= 1.0 + 1e-9:
            continue  # repair can close this pair without a loss
        bid = _f(best_bids.get(token_id))
        if bid <= 0.0:
            continue
        plans.append(
            ExitPlan(
                condition_id=condition_id,
                title=str(row.get("title") or ""),
                token_id=token_id,
                size=size,
                price=round(bid, 6),
                avg_cost=_f(row.get("avg_price")),
                age_seconds=round(age, 1),
                pair_cost=round(pair_cost, 6) if pair_cost is not None else None,
            )
        )
    return plans
