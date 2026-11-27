"""Public taker trades from the Polymarket Data API.

Paper mode needs the trade tape, not just the book. A resting bid fills when a
taker SELL prints at or below its price; the book's best ask staying above the
bid is the normal case and says nothing about fills.

The endpoint is public and needs no credentials:

    GET https://data-api.polymarket.com/v2/trades?condition=<id>&limit=500
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from dataclasses import dataclass

__all__ = ["PublicTrade", "PublicTradesError", "get_recent_trades"]

DATA_API = "https://data-api.polymarket.com"
USER_AGENT = "polymarket-mm/0.1 (paper trade tape)"


class PublicTradesError(RuntimeError):
    """The public trade tape could not be read."""


@dataclass(frozen=True)
class PublicTrade:
    trade_id: str
    condition_id: str
    token_id: str
    side: str
    price: float
    size: float
    ts: float


def _request(url: str, timeout: float) -> dict:
    request = urllib.request.Request(
        url, headers={"User-Agent": USER_AGENT, "Accept": "application/json"}
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            payload = response.read().decode("utf-8", "replace")
    except (urllib.error.URLError, TimeoutError, OSError) as exc:
        raise PublicTradesError(f"GET {url} failed: {exc}") from exc
    try:
        data = json.loads(payload)
    except json.JSONDecodeError as exc:
        raise PublicTradesError(f"GET {url} returned non-JSON") from exc
    if not isinstance(data, dict):
        raise PublicTradesError(f"GET {url} returned a non-object")
    return data


def get_recent_trades(condition_id: str, limit: int = 500, timeout: float = 12.0) -> list[PublicTrade]:
    """The most recent public trades for one condition, oldest first."""
    params = urllib.parse.urlencode({"condition": condition_id, "limit": int(limit)})
    payload = _request(f"{DATA_API}/v2/trades?{params}", timeout)
    rows = payload.get("data") or []
    out: list[PublicTrade] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        try:
            price = float(row["price"])
            size = float(row["size"])
            ts = float(row["timestamp"])
        except (KeyError, TypeError, ValueError):
            continue
        token = str(row.get("token_id") or "")
        side = str(row.get("side") or "").upper()
        tx = str(row.get("transaction_hash") or "")
        trade_id = f"{tx}:{token}:{ts:.0f}:{price:.6f}:{size:.6f}:{side}" if tx else f"{token}:{ts:.0f}:{price:.6f}:{size:.6f}:{side}"
        out.append(
            PublicTrade(
                trade_id=trade_id,
                condition_id=str(row.get("condition_id") or condition_id),
                token_id=token,
                side=side,
                price=price,
                size=size,
                ts=ts,
            )
        )
    out.sort(key=lambda trade: (trade.ts, trade.trade_id))
    return out
