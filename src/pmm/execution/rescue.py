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

import math
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

#: The venue rejects a BUY below this notional, whatever the share count.
#: It is what makes a small position uneconomic to complete: at 1c a share,
#: $1 is 100 shares.
MIN_BUY_NOTIONAL = 1.0

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
    held_token_id: str = ""


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


def _ceil_to_tick(value: float, tick: float) -> float:
    """The smallest tick multiple at or above `value`."""
    if tick <= 0:
        tick = 0.01
    steps = math.ceil(round(value / tick, 9))
    return round(steps * tick, 6)


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
    ticks: Optional[Mapping[str, float]] = None,
    min_days_to_resolution: float = DEFAULT_MIN_DAYS_TO_RESOLUTION,
    today: date | None = None,
) -> list[RescuePlan]:
    """Which complement bids would complete a nearly-won set.

    A plan is emitted only when all of these hold:

    * the market holds exactly one of the two outcomes, with size >= min_size;
    * that held leg is priced at or above `min_price`;
    * the complement token is known and has no resting order already;
    * the balance can fund `size * price`;
    * the market does not resolve sooner than `min_days_to_resolution`;
    * the bid clears the venue's $1 minimum notional **and** stays at or
      below what the complement is marked at, so the completion is an
      arbitrage against the book rather than a bet on time value.

    `ticks` maps a token id to its tick size; a missing tick uses `tick`.
    The price is the cheapest tick multiple that clears the notional floor.

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
        leg_tick = float((ticks or {}).get(complement, tick) or tick)
        price = _ceil_to_tick(max(leg_tick, MIN_BUY_NOTIONAL / size), leg_tick)
        complement_mark = max(0.0, 1.0 - held_price)
        if price <= 0 or price > complement_mark + 1e-9:
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
                held_token_id=str(row.get("token_id") or ""),
            )
        )
    return plans


def _held_bid(executor: Any, token_id: str, supplied: Optional[Mapping[str, float]]) -> float:
    """Best bid on the held leg, or 0 when it cannot be read."""
    if supplied is not None:
        return float(supplied.get(token_id, 0.0) or 0.0)
    if not token_id:
        return 0.0
    try:
        from ..data.clob import get_book

        book = get_book(token_id)
        return max((float(level.get("price") or 0) for level in book.get("bids") or []), default=0.0)
    except Exception:  # noqa: BLE001 - an unreadable book means "no bid"
        return 0.0


def run_rescue(
    config: Any,
    *,
    executor: Any = None,
    positions: Optional[Sequence[Mapping[str, Any]]] = None,
    min_price: float = DEFAULT_MIN_PRICE,
    min_size: float = DEFAULT_MIN_SIZE,
    min_days_to_resolution: float = DEFAULT_MIN_DAYS_TO_RESOLUTION,
    max_orders: int = 5,
    held_bids: Optional[Mapping[str, float]] = None,
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
    )
    # The venue's tick varies per market (0.001 or 0.01), and the cheapest
    # acceptable price depends on it. Re-plan once the real ticks are known.
    ticks: dict[str, float] = {}
    for plan in plans:
        try:
            ticks[plan.token_id] = float(executor.market_params(plan.token_id)[0])
        except Exception:  # noqa: BLE001 - fall back to the default tick
            continue
    if ticks:
        plans = plan_rescues(
            positions,
            open_assets=open_assets,
            min_price=min_price,
            min_size=min_size,
            balance=balance,
            min_days_to_resolution=min_days_to_resolution,
            ticks=ticks,
        )
    results: list[dict[str, Any]] = []
    # Harvest takes precedence: when the held leg already has a bid at or above
    # the harvest floor, selling it beats spending 1c to complete the set
    # (0.999 collected now against 1.00 minus the 1c complement).
    from .harvest import HARVEST_MIN_PRICE

    kept: list[RescuePlan] = []
    for plan in plans:
        held_bid = _held_bid(executor, plan.held_token_id, held_bids)
        if held_bid >= HARVEST_MIN_PRICE - 1e-9:
            results.append(
                {
                    "condition_id": plan.condition_id,
                    "size": plan.size,
                    "held_side_price": plan.held_side_price,
                    "best_bid": held_bid,
                    "status": "skipped: harvest takes precedence",
                }
            )
            continue
        kept.append(plan)
    plans = kept[: max(0, int(max_orders))]

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
