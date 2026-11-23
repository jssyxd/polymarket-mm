"""Complete a nearly-won position by buying the cheap leg, then let merge pay 1.00.

When one leg of a market is priced at or above `min_price`, the other leg is
priced at or below `1 - min_price`. A holder of the winning leg is locked out
of that capital until the market resolves. Buying the cheap leg completes a
set, and `merge` converts a complete set into exactly 1.00 pUSD whatever the
outcome is — so the capital comes back without waiting.

This is deliberately a *buy* path. Selling the winner at 0.99 would return
0.99 per share; merging returns 1.00. Selling the loser at 0.01 returns
0.01 — nothing — while it is exactly the token that completes the set.

The plan is computed by a pure function so it can be tested without a venue.
"""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = [
    "RescuePlan",
    "DEFAULT_MIN_PRICE",
    "DEFAULT_MIN_SIZE",
    "DEFAULT_MIN_DAYS_TO_RESOLUTION",
    "plan_rescues",
    "run_rescue",
]

#: Below this the winning leg is not "nearly won" enough to spend on.
DEFAULT_MIN_PRICE = 0.97

#: The venue's minimum order size. A cheaper completion is not accepted.
DEFAULT_MIN_SIZE = 5.0

#: Skip markets that resolve this soon. Buying the cheap leg costs the tick
#: (1c) while the leg's fair value is at or below it, so the completion is
#: cheaper than holding only if the freed capital can be redeployed first.
#: A market that resolves in hours leaves no time to redeploy.
DEFAULT_MIN_DAYS_TO_RESOLUTION = 1.0


@dataclass(frozen=True)
class RescuePlan:
    """One complement bid that would complete a set."""

    condition_id: str
    title: str
    token_id: str
    size: float
    price: float
    held_side_price: float


def _days_to_resolution(row: Mapping[str, Any], today: date) -> float | None:
    """Whole days until the market's end date, or None when it is unknown."""
    raw = str(row.get("end_date") or "").strip()
    if not raw:
        return None
    try:
        end = date.fromisoformat(raw[:10])
    except ValueError:
        return None
    return float((end - today).days)


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def plan_rescues(
    positions: Iterable[Mapping[str, Any]],
    *,
    open_assets: Iterable[str] = (),
    min_price: float = DEFAULT_MIN_PRICE,
    min_size: float = DEFAULT_MIN_SIZE,
    balance: Optional[float] = None,
    tick: float = 0.01,
    min_days_to_resolution: float = DEFAULT_MIN_DAYS_TO_RESOLUTION,
    today: date | None = None,
) -> list[RescuePlan]:
    """Which complement bids would complete a nearly-won set.

    A plan is emitted only when all of these hold:

    * the market holds exactly one of the two outcomes, with size >= min_size;
    * that held leg is priced at or above `min_price`;
    * the complement token is known and has no resting order already;
    * the balance can fund `size * price`;
    * the market does not resolve sooner than `min_days_to_resolution`.

    `open_assets` are the token ids that already have an order, so a second
    cycle does not stack duplicates.
    """
    legs: dict[str, dict[int, Mapping[str, Any]]] = {}
    for row in positions:
        if not isinstance(row, Mapping):
            continue
        condition_id = str(row.get("condition_id") or "")
        if not condition_id:
            continue
        size = _f(row.get("current_size"))
        if size <= 0:
            continue
        try:
            index = int(row.get("outcome_index"))
        except (TypeError, ValueError):
            continue
        legs.setdefault(condition_id, {})[index] = row

    resting = {str(asset) for asset in open_assets}
    price = max(float(tick), 0.01)
    plans: list[RescuePlan] = []
    for condition_id, pair in legs.items():
        if len(pair) != 1:
            continue  # already paired: the merge timer owns it
        row = next(iter(pair.values()))
        size = _f(row.get("current_size"))
        held_price = _f(row.get("current_price"))
        complement = str(row.get("opposite_token_id") or "")
        if size < min_size or held_price < min_price or not complement:
            continue
        if complement in resting:
            continue
        days_left = _days_to_resolution(row, today or date.today())
        if days_left is not None and days_left < min_days_to_resolution:
            continue
        if balance is not None and size * price > balance + 1e-9:
            continue
        plans.append(
            RescuePlan(
                condition_id=condition_id,
                title=str(row.get("title") or ""),
                token_id=complement,
                size=size,
                price=price,
                held_side_price=held_price,
            )
        )
    return plans


def run_rescue(
    config: Any,
    *,
    executor: Any = None,
    positions: Optional[Sequence[Mapping[str, Any]]] = None,
    min_price: float = DEFAULT_MIN_PRICE,
    min_size: float = DEFAULT_MIN_SIZE,
    min_days_to_resolution: float = DEFAULT_MIN_DAYS_TO_RESOLUTION,
    max_orders: int = 5,
) -> list[dict[str, Any]]:
    """Plan and place the complement bids, returning one record per market."""
    from .clob import OrderExecutor
    from .positions import read_positions

    if executor is None:
        executor = OrderExecutor(config)
    if positions is None:
        positions = read_positions(config).get("api_positions") or []

    open_assets: list[str] = []
    balance: Optional[float] = None
    try:
        open_assets = [
            str(order.get("asset_id"))
            for order in executor.client.get_open_orders()
            if isinstance(order, dict)
        ]
    except Exception:  # noqa: BLE001 - an unreadable book means "unknown"
        open_assets = []
    balance = executor.collateral_balance()

    plans = plan_rescues(
        positions,
        open_assets=open_assets,
        min_price=min_price,
        min_size=min_size,
        balance=balance,
        min_days_to_resolution=min_days_to_resolution,
    )[: max(0, int(max_orders))]

    results: list[dict[str, Any]] = []
    if config.dry_run or not config.owner_pk:
        for plan in plans:
            results.append(
                {
                    "condition_id": plan.condition_id,
                    "size": plan.size,
                    "price": plan.price,
                    "held_side_price": plan.held_side_price,
                    "status": "dry_run",
                }
            )
        return results

    for plan in plans:
        intent = {
            "token_id": plan.token_id,
            "price": plan.price,
            "size": plan.size,
            "side": "BUY",
            "post_only": True,
        }
        try:
            payload = executor.build_payload(intent)
            response = executor.place(payload=payload, reason=f"rescue_complete_set:{plan.condition_id[:10]}")
            status = str(response.get("status") or "unknown")
            if response.get("success") is False:
                status = f"failed: {response.get('errorMsg') or response}"
        except Exception as exc:  # noqa: BLE001 - one market must not stop the rest
            status = f"failed: {type(exc).__name__}: {exc}"[:200]
        results.append(
            {
                "condition_id": plan.condition_id,
                "size": plan.size,
                "price": plan.price,
                "held_side_price": plan.held_side_price,
                "status": status,
            }
        )
    return results
