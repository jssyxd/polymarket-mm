"""Fill a simulated order against a recorded book, with fees and slippage.

Price comes from walking the book, never from the mid: a taker of size N pays
the asks it actually consumes. The difference between that average price and
the best level is reported as slippage, so a strategy cannot quietly borrow
depth that did not exist.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Iterable, Sequence

__all__ = ["Level", "Book", "Fill", "execute"]


@dataclass(frozen=True)
class Level:
    price: float
    size: float


@dataclass(frozen=True)
class Book:
    bids: Sequence[Level]
    asks: Sequence[Level]

    @classmethod
    def from_raw(cls, raw: dict) -> "Book":
        def levels(key: str, reverse: bool) -> tuple[Level, ...]:
            rows = []
            for item in raw.get(key) or []:
                try:
                    if isinstance(item, dict):
                        rows.append(Level(float(item.get("price")), float(item.get("size"))))
                    else:
                        rows.append(Level(float(item[0]), float(item[1])))
                except (TypeError, ValueError, IndexError, KeyError):
                    continue
            rows.sort(key=lambda level: level.price, reverse=reverse)
            return tuple(rows)

        return cls(bids=levels("bids", True), asks=levels("asks", False))

    @property
    def best_bid(self) -> float:
        return self.bids[0].price if self.bids else 0.0

    @property
    def best_ask(self) -> float:
        return self.asks[0].price if self.asks else 0.0


@dataclass(frozen=True)
class Fill:
    price: float
    size: float
    fee: float
    slippage: float
    best: float

    @property
    def notional(self) -> float:
        return round(self.price * self.size, 6)


def _walk(levels: Iterable[Level], size: float, limit: float | None) -> tuple[float, float, float]:
    """Return (notional, filled, best price) while walking one side."""
    remaining = size
    notional = 0.0
    best = 0.0
    for level in levels:
        if remaining <= 0:
            break
        if limit is not None:
            if level.price > limit:
                break
        take = min(remaining, level.size)
        if take <= 0:
            continue
        if best == 0.0:
            best = level.price
        notional += take * level.price
        remaining -= take
    return notional, size - remaining, best


def execute(
    book: Book,
    side: str,
    size: float,
    *,
    limit: float | None = None,
    fee_bps: float = 0.0,
) -> Fill | None:
    """Fill `size` on `side` against the book, or None when nothing crossable.

    BUY walks the asks from the lowest price upward; SELL walks the bids from
    the highest downward. A limit that the book does not cross yields None.
    """
    if size <= 0:
        return None
    levels = book.asks if side.upper() == "BUY" else book.bids
    if not levels:
        return None
    notional, filled, best = _walk(levels, size, limit)
    if filled <= 0:
        return None
    average = notional / filled
    fee = notional * fee_bps / 10_000.0
    return Fill(
        price=round(average, 6),
        size=round(filled, 6),
        fee=round(fee, 6),
        slippage=round(average - best, 6),
        best=best,
    )
