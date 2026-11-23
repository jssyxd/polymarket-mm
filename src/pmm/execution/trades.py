"""Record the venue's fills in the journal.

The quoting loop never sees its own fills: an order rests, someone takes it,
and the only trace is on the venue. Without this step the journal has no
trades, so PnL, fill rate and per-leg attribution cannot be computed, and the
inventory falls back to a guess.

The source is the venue's own trade list. Each trade carries a `maker_orders`
array, and the entry whose `owner` is our API key is the size *we* filled, at
*our* price and side — which is not the same as the trade's taker-side fields.
"""

from __future__ import annotations

import logging
from typing import Any, Optional, Sequence

__all__ = ["venue_fills", "sync_fills"]

LOGGER = logging.getLogger(__name__)

#: Only a confirmed trade moved the position. FAILED and MINED do not.
CONFIRMED = "CONFIRMED"


def _as_float(value: Any) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _fill(trade: dict, leg: dict) -> dict:
    """One fill record, built from a trade and one side of it."""
    price = round(_as_float(leg.get("price") or trade.get("price")), 6)
    size = _as_float(leg.get("matched_amount") or leg.get("size") or trade.get("size"))
    return {
        "fill_id": f"{trade.get('id')}:{leg.get('order_id') or 'taker'}",
        "trade_id": trade.get("id"),
        "condition_id": str(trade.get("market") or ""),
        "token_id": str(leg.get("asset_id") or trade.get("asset_id") or ""),
        "outcome": str(leg.get("outcome") or trade.get("outcome") or ""),
        "side": str(leg.get("side") or trade.get("side") or "").upper(),
        "price": price,
        "size": size,
        "notional": round(price * size, 6),
        "ts": int(_as_float(trade.get("match_time")) or 0),
        "transaction_hash": trade.get("transaction_hash"),
        "source": "venue",
    }


def venue_fills(config: Any, client: Any = None) -> list[dict]:
    """The account's confirmed fills, most recent page of the venue's trades.

    Only trades where this account was the maker or the taker are returned.
    """
    if client is None:
        from .clob import build_client

        client = build_client(config)

    trades = client.get_trades(None, only_first_page=True) or []
    owner = str(getattr(config, "api_key", "") or "").lower()
    wallet = str(getattr(config, "funder", "") or "").lower()

    fills: list[dict] = []
    for trade in trades:
        if not isinstance(trade, dict):
            continue
        if str(trade.get("status") or "").upper() != CONFIRMED:
            continue
        matched = False
        for leg in trade.get("maker_orders") or []:
            if not isinstance(leg, dict):
                continue
            if (owner and str(leg.get("owner") or "").lower() == owner) or (
                wallet and str(leg.get("maker_address") or "").lower() == wallet
            ):
                matched = True
                fill = _fill(trade, leg)
                if fill["size"] > 0:
                    fills.append(fill)
        if not matched and owner and str(trade.get("owner") or "").lower() == owner:
            fill = _fill(trade, trade)
            if fill["size"] > 0:
                fills.append(fill)
    return fills


def sync_fills(journal: Any, config: Any, client: Any = None) -> list[dict]:
    """Append the fills the journal has not seen yet, and return them.

    Deduplicated on `fill_id`, so running this every cycle records each fill
    exactly once. A venue error returns nothing rather than raising: the
    quoting loop must not stop because the trade list was slow.
    """
    known = {str(fill.get("fill_id")) for fill in journal.fills() if fill.get("fill_id")}
    try:
        fills = venue_fills(config, client=client)
    except Exception as exc:  # noqa: BLE001 - the journal is best effort
        LOGGER.warning("venue fills unavailable: %s", exc)
        return []

    fresh: list[dict] = []
    for fill in fills:
        if fill["fill_id"] in known:
            continue
        known.add(fill["fill_id"])
        journal.append("fill", **fill)
        fresh.append(fill)
    return fresh
