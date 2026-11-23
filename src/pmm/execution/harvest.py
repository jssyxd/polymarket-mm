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
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = [
    "HarvestPlan",
    "HARVEST_MIN_PRICE",
    "harvest_price",
    "plan_harvests",
    "run_harvest",
]

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


def harvest_price(best_bid: float, floor: float = HARVEST_MIN_PRICE) -> Optional[float]:
    """The limit price for a harvest sell, or None when nothing is worth hitting.

    Measured on 2026-11-24: a 0.99 limit sell in a book bidding 0.999 filled at
    0.999 with a zero fee, because the venue gives price improvement to the
    crossing order. So the floor is the limit, not a cap: it guarantees the
    minimum we accept, and the book decides whether we get more.

    A book whose best bid is below the floor has nothing at or above it, and
    hitting it would sell below our minimum, so there is nothing to do.
    """
    if best_bid + 1e-9 < floor:
        return None
    return floor


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


def run_harvest(
    config: Any,
    *,
    executor: Any = None,
    positions: Optional[Sequence[Mapping[str, Any]]] = None,
    min_price: float = HARVEST_MIN_PRICE,
    min_size: float = MIN_ORDER_SIZE,
    max_orders: int = 3,
    force: bool = False,
    best_bids: Optional[Mapping[str, float]] = None,
    ticks: Optional[Mapping[str, float]] = None,
    fee_bps: Optional[int] = None,
) -> list[dict[str, Any]]:
    """Plan and place the harvest sells, returning one record per leg.

    Refuses to run unless `POLY_HARVEST` is set, or `force` is passed by a
    dry run. The order path keeps the same invariants as `Runner._payloads`:
    post-only, a sell, price at or above the floor.
    """
    from .clob import OrderExecutor
    from .positions import read_positions

    if config.dry_run or not config.owner_pk:
        planning_only = True
    elif getattr(config, "harvest_enabled", False) or force:
        planning_only = False
    else:
        raise RuntimeError(
            "harvest is disabled: set POLY_HARVEST=1 to rest live sell orders"
        )

    if executor is None:
        executor = OrderExecutor(config)
    if positions is None:
        positions = read_positions(config).get("api_positions") or []

    open_assets: list[str] = []
    try:
        open_assets = [
            str(order.get("asset_id"))
            for order in executor.client.get_open_orders()
            if isinstance(order, dict)
        ]
    except Exception:  # noqa: BLE001 - unreadable book means "unknown"
        open_assets = []

    plans = plan_harvests(
        positions, open_assets=open_assets, min_price=min_price, min_size=min_size
    )[: max(0, int(max_orders))]

    # A resting ask must clear the best bid. Near the top of the grid there is
    # no valid price at all, and the honest answer is "no order", not a
    # rejection and not a 10% taker fee.
    priced: list[tuple[Any, float]] = []
    results: list[dict[str, Any]] = []
    for plan in plans:
        best_bid = _best_bid(executor, plan.token_id, best_bids)
        price = harvest_price(best_bid, floor=min_price)
        if price is None:
            results.append(
                {
                    "condition_id": plan.condition_id,
                    "size": plan.size,
                    "mark": plan.mark,
                    "best_bid": best_bid,
                    "status": "skipped: no bid at or above the floor",
                }
            )
            continue
        fee_bps = _fee_bps(config, executor, plan, fee_bps)
        if price * (1.0 - fee_bps / 10_000.0) <= plan.avg_cost:
            results.append(
                {
                    "condition_id": plan.condition_id,
                    "size": plan.size,
                    "mark": plan.mark,
                    "best_bid": best_bid,
                    "fee_bps": fee_bps,
                    "status": "skipped: fee-adjusted proceeds do not clear cost",
                }
            )
            continue
        priced.append((plan, price))

    if planning_only:
        for plan, price in priced:
            results.append(
                {
                    "condition_id": plan.condition_id,
                    "size": plan.size,
                    "price": price,
                    "mark": plan.mark,
                    "profit_per_share": round(price - plan.avg_cost, 4),
                    "status": "dry_run",
                }
            )
        return results

    for plan, price in priced:
        intent = {
            "token_id": plan.token_id,
            "price": price,
            "size": plan.size,
            "side": "SELL",
            # Crossing the bid is the point: the venue gives price
            # improvement, so a 0.99 limit in a 0.999 book fills at 0.999.
            "post_only": False,
        }
        try:
            payload = executor.build_payload(intent)
            response = executor.place(payload=payload, reason=f"harvest:{plan.condition_id[:10]}")
            status = str(response.get("status") or "unknown")
            if response.get("success") is False:
                status = f"failed: {response.get('errorMsg') or response}"
        except Exception as exc:  # noqa: BLE001 - one leg must not stop the rest
            status = f"failed: {type(exc).__name__}: {exc}"[:200]
        results.append(
            {
                "condition_id": plan.condition_id,
                "size": plan.size,
                "price": price,
                "mark": plan.mark,
                "profit_per_share": round(price - plan.avg_cost, 4),
                "status": status,
            }
        )
    return results


def _best_bid(executor: Any, token_id: str, supplied: Optional[Mapping[str, float]]) -> float:
    if supplied is not None:
        return float(supplied.get(token_id, 0.0) or 0.0)
    from ..data.clob import get_book

    book = get_book(token_id)
    return max((float(level.get("price") or 0) for level in book.get("bids") or []), default=0.0)


def _fee_bps(config: Any, executor: Any, plan: Any, supplied: Optional[int]) -> int:
    """The fee to assume: measured first, then the market's configured rate."""
    if supplied is not None:
        return int(supplied)
    from .fees import observed_fee_bps

    try:
        measured = observed_fee_bps(config.journal_path, plan.condition_id)
    except Exception:  # noqa: BLE001 - the store is advisory
        measured = None
    if measured is not None:
        return int(measured)
    from ..data.clob import get_fee_rate_bps

    try:
        return int(get_fee_rate_bps(plan.token_id))
    except Exception:  # noqa: BLE001 - an unknown fee is treated as the worst seen
        return 1000


def _tick(executor: Any, token_id: str, supplied: Optional[Mapping[str, float]]) -> float:
    if supplied is not None:
        return float(supplied.get(token_id, 0.01) or 0.01)
    return float(executor.market_params(token_id)[0])

    for plan in plans:
        intent = {
            "token_id": plan.token_id,
            "price": plan.price,
            "size": plan.size,
            "side": "SELL",
            # Crossing the bid is the point: the venue gives price
            # improvement, so a 0.99 limit in a 0.999 book fills at 0.999.
            "post_only": False,
        }
        try:
            payload = executor.build_payload(intent)
            response = executor.place(payload=payload, reason=f"harvest:{plan.condition_id[:10]}")
            status = str(response.get("status") or "unknown")
            if response.get("success") is False:
                status = f"failed: {response.get('errorMsg') or response}"
        except Exception as exc:  # noqa: BLE001 - one leg must not stop the rest
            status = f"failed: {type(exc).__name__}: {exc}"[:200]
        results.append(
            {
                "condition_id": plan.condition_id,
                "size": plan.size,
                "price": plan.price,
                "mark": plan.mark,
                "profit_per_share": round(plan.profit_per_share, 4),
                "status": status,
            }
        )
    return results
