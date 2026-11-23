"""Metric computations for the hourly monitor.

Every function is pure and works on plain dicts so the monitor can be fed
straight from the execution worker's journal without an import cycle. A
fill record is a dict with at least:

* ``notional``: pUSD traded on that fill.
* ``pnl``: realized pUSD on that fill, already net of fees.
* ``ts``: epoch seconds of the fill (optional, used for hourly counts).
* ``side``: "up" or "down" (optional).

Units. Capture is reported in basis points of notional, the same unit the
upstream account was measured in when it lost 0.55 bp per notional traded.
"""

from __future__ import annotations

from datetime import datetime, timezone

__all__ = [
    "fill_notional",
    "fill_pnl",
    "fill_timestamp",
    "fill_net_bps",
    "realized_bps",
    "rolling_net_bps",
    "win_rate",
    "inventory_exposure",
    "pair_coverage",
    "reward_estimate",
]

_NOTIONAL_KEYS = ("notional", "notional_usd", "size_usd")
_PNL_KEYS = ("pnl", "pnl_usd", "realized_pnl")
_TIME_KEYS = ("ts", "timestamp", "time", "t")


def _first_number(record: dict, keys: tuple[str, ...]) -> float:
    for key in keys:
        if key in record:
            value = record[key]
            if isinstance(value, bool):
                continue
            if isinstance(value, (int, float)):
                return float(value)
    return 0.0


def fill_notional(fill: dict) -> float:
    """pUSD traded on one fill."""
    return _first_number(fill, _NOTIONAL_KEYS)


def fill_pnl(fill: dict) -> float:
    """Realized pUSD on one fill."""
    return _first_number(fill, _PNL_KEYS)


def fill_timestamp(fill: dict) -> float | None:
    """Epoch seconds of one fill, or None when the record carries no clock."""
    for key in _TIME_KEYS:
        if key not in fill:
            continue
        value = fill[key]
        if isinstance(value, bool):
            continue
        if isinstance(value, (int, float)):
            return float(value)
        if isinstance(value, str):
            text = value.strip()
            try:
                return float(text)
            except ValueError:
                pass
            try:
                parsed = datetime.fromisoformat(text.replace("Z", "+00:00"))
            except ValueError:
                continue
            if parsed.tzinfo is None:
                parsed = parsed.replace(tzinfo=timezone.utc)
            return parsed.timestamp()
    return None


def fill_net_bps(fill: dict) -> float:
    """Net capture of one fill in basis points of notional."""
    notional = fill_notional(fill)
    if notional <= 0.0:
        return 0.0
    return fill_pnl(fill) / notional * 1e4


def realized_bps(fills: list[dict], journal_pnl: dict) -> float:
    """Net capture over the given fills, in basis points of notional.

    The journal totals are the fallback when no fill list is available. The
    journal may carry ``total_notional``, ``total_pnl`` and ``fees``; fees
    are only subtracted on the journal path because a fill's ``pnl`` is
    already net.

    Returns 0.0 when there is no notional to divide by.
    """
    fill_list = list(fills or [])
    total_notional = sum(fill_notional(f) for f in fill_list)
    total_pnl = sum(fill_pnl(f) for f in fill_list)
    if total_notional <= 0.0:
        journal = journal_pnl or {}
        total_notional = float(journal.get("total_notional") or 0.0)
        total_pnl = float(journal.get("total_pnl") or 0.0)
        total_pnl -= float(journal.get("fees") or 0.0)
    if total_notional <= 0.0:
        return 0.0
    return total_pnl / total_notional * 1e4


def rolling_net_bps(fills: list[dict], window: int = 100) -> float:
    """Mean net capture per fill over the last ``window`` fills.

    This is the ``e_rolling_100`` of the upstream design. An empty fill
    list yields 0.0, which callers must not read as "losing": with no fills
    there is no evidence either way.
    """
    if window <= 0:
        raise ValueError(f"window must be positive: {window}")
    recent = list(fills or [])[-window:]
    if not recent:
        return 0.0
    values = [fill_net_bps(f) for f in recent]
    return sum(values) / len(values)


def win_rate(fills: list[dict]) -> float:
    """Fraction of fills that realized a positive pUSD."""
    fill_list = list(fills or [])
    if not fill_list:
        return 0.0
    wins = sum(1 for f in fill_list if fill_pnl(f) > 0.0)
    return wins / len(fill_list)


def inventory_exposure(
    up_shares: float,
    down_shares: float,
    mark_up: float,
    mark_down: float,
) -> float:
    """pUSD at risk if the market resolves fully against the position.

    Resolution one way kills the other leg, so the exposure is the larger
    of the two leg values. A one-sided position of ``up_shares`` at
    ``mark_up`` risks exactly ``up_shares * mark_up``.
    """
    up_value = max(up_shares, 0.0) * mark_up
    down_value = max(down_shares, 0.0) * mark_down
    return max(up_value, down_value)


def pair_coverage(up_shares: float, down_shares: float) -> float:
    """Fraction of the inventory that sits in a complete, mergeable set.

    ``min(up, down)`` complete sets are worth 1 pUSD each and can be
    merged, so ``2 * min(up, down)`` of the held shares are mergeable.
    """
    up = max(up_shares, 0.0)
    down = max(down_shares, 0.0)
    total = up + down
    if total <= 0.0:
        return 0.0
    return 2.0 * min(up, down) / total


def reward_estimate(
    min_size: float,
    max_spread_cents: float,
    rate_per_day: float,
    q_min: float,
    total_q_min: float,
    quote_size: float | None = None,
    quote_spread_cents: float | None = None,
) -> float:
    """Estimated daily reward in pUSD.

    The market's daily rate is split in proportion to the score each maker
    contributes, so the estimate is ``rate_per_day * q_min / total_q_min``.
    The share is clipped to one because one maker cannot take more than the
    market's own daily allocation.

    ``min_size`` is the venue's reward minimum order size in shares and
    ``max_spread_cents`` is the venue's reward maximum spread. When the
    quote that produced ``q_min`` is given as ``quote_size`` and
    ``quote_spread_cents``, an order below the minimum size or outside the
    spread band scores nothing and the estimate is zero.
    """
    if total_q_min <= 0.0:
        return 0.0
    if quote_size is not None and quote_size < min_size:
        return 0.0
    if quote_spread_cents is not None and quote_spread_cents > max_spread_cents:
        return 0.0
    share = max(q_min, 0.0) / total_q_min
    share = min(share, 1.0)
    return rate_per_day * share
