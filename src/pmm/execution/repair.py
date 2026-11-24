"""Pair a leg that has been alone too long.

A paired bid only has an edge when both legs fill. When one fills and the
other does not, the position becomes a directional bet, and waiting for the
market to settle is how the first live run lost its money.

A repair closes the pair on purpose: buy the missing leg at its ask, provided
`entry cost of the held leg + ask <= 1 pUSD`. That bound is what makes the
trade riskless — the complete set merges for exactly 1, so the pair can only
break even or better. The wait is the part that matters: a leg that filled
seconds ago may still get its partner, and paying the ask too early just
donates the spread.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = [
    "RepairPlan",
    "DEFAULT_MAX_AGE_SECONDS",
    "DEFAULT_MAX_PAIR_COST",
    "plan_repairs",
]

#: How long a leg may stand alone before the pair is forced closed.
DEFAULT_MAX_AGE_SECONDS = 900.0

#: A complete set redeems for 1 pUSD, so the pair must cost at most that.
DEFAULT_MAX_PAIR_COST = 1.0


@dataclass(frozen=True)
class RepairPlan:
    """One forced completion of a single leg."""

    condition_id: str
    title: str
    token_id: str
    size: float
    price: float
    held_cost: float
    pair_cost: float
    age_seconds: float


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def plan_repairs(
    positions: Iterable[Mapping[str, Any]],
    *,
    complement_asks: Mapping[str, float] | None = None,
    open_assets: Iterable[str] = (),
    now: float,
    max_age_seconds: float = DEFAULT_MAX_AGE_SECONDS,
    max_pair_cost: float = DEFAULT_MAX_PAIR_COST,
    min_size: float = 5.0,
) -> list[RepairPlan]:
    """Legs that have stood alone too long and can still be paired profitably.

    `complement_asks` maps a condition id to the best ask of the *missing*
    leg. Without it nothing is planned: the cost bound cannot be checked, and
    an unchecked repair is just another directional buy.
    """
    if not complement_asks:
        return []
    resting = {str(asset) for asset in open_assets}
    by_condition: dict[str, dict[int, Mapping[str, Any]]] = {}
    for row in positions:
        if not isinstance(row, Mapping):
            continue
        condition_id = str(row.get("condition_id") or "")
        if not condition_id:
            continue
        try:
            index = int(row.get("outcome_index"))
        except (TypeError, ValueError):
            continue
        if _f(row.get("current_size")) > 0:
            by_condition.setdefault(condition_id, {})[index] = row

    plans: list[RepairPlan] = []
    for condition_id, legs in by_condition.items():
        if len(legs) != 1:
            continue  # already paired, or nothing held
        row = next(iter(legs.values()))
        size = _f(row.get("current_size"))
        if size < min_size:
            continue
        token_id = str(row.get("opposite_token_id") or "")
        if not token_id or token_id in resting:
            continue
        ask = _f((complement_asks or {}).get(condition_id))
        if ask <= 0.0:
            continue
        held_cost = _f(row.get("avg_price"))
        pair_cost = held_cost + ask
        if pair_cost > max_pair_cost + 1e-9:
            continue
        entered = _f(row.get("first_entry_at"))
        age = max(0.0, now - entered) if entered > 0 else 0.0
        if entered > 0 and age < max_age_seconds:
            continue
        plans.append(
            RepairPlan(
                condition_id=condition_id,
                title=str(row.get("title") or ""),
                token_id=token_id,
                size=size,
                price=round(ask, 6),
                held_cost=held_cost,
                pair_cost=round(pair_cost, 6),
                age_seconds=round(age, 1),
            )
        )
    return plans
