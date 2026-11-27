"""Queue-aware paper fills from the public trade tape.

A resting bid at P fills only when taker SELL volume at or below P has first
consumed the visible size resting at or above P. The visible size is a
snapshot at quote time; it is deliberately conservative because it does not
model later cancellations or new size arriving in front.
"""

from __future__ import annotations

from typing import Any, Iterable

from ..data.public_trades import PublicTrade

__all__ = ["queue_ahead", "consume"]


def _level(entry: Any) -> tuple[float, float] | None:
    try:
        if isinstance(entry, dict):
            return float(entry["price"]), float(entry["size"])
        return float(entry[0]), float(entry[1])
    except (KeyError, TypeError, ValueError, IndexError):
        return None


def queue_ahead(book: dict[str, Any] | None, price: float) -> float:
    """Visible bid size at or above ``price`` in a raw CLOB book."""
    if not book:
        return 0.0
    total = 0.0
    for entry in book.get("bids") or []:
        parsed = _level(entry)
        if parsed is None:
            continue
        level_price, level_size = parsed
        if level_price >= price - 1e-9 and level_size > 0:
            total += level_size
    return total


def consume(
    ahead: float,
    trades: Iterable[PublicTrade],
    *,
    price: float,
    token_id: str,
    placed_ts: float,
    seen: set[str],
) -> tuple[float, PublicTrade | None]:
    """Consume taker sells against the queue.

    Returns the remaining visible size and the trade that filled us, if any.
    A trade exactly equal to the remaining queue empties it but does not fill;
    the next print is needed.
    """
    remaining = max(float(ahead), 0.0)
    for trade in trades:
        if trade.trade_id in seen:
            continue
        if trade.token_id != token_id:
            continue
        if trade.side.upper() != "SELL":
            continue
        if trade.price > price + 1e-9:
            continue
        if trade.ts < placed_ts - 1e-9:
            continue
        seen.add(trade.trade_id)
        if trade.size <= remaining + 1e-9:
            remaining -= trade.size
        else:
            return 0.0, trade
    return remaining, None
