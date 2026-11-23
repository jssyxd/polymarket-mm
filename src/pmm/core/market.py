"""Market snapshot: everything the quote cycle needs about one binary market.

A snapshot is a flat, serialisable description of a single condition. It is
the boundary object between the venue (a pile of JSON with several different
schemas) and the engine (which wants one typed shape with named fields).

The snapshot carries the two outcome token ids, because the maker quotes both
legs of the pair: buying UP at ``p`` and DOWN at ``1 - p`` costs
``1 - 2 * delta`` and merges back to 1 pUSD. See
:mod:`pmm.pricing.quotes` for the quote itself and :mod:`pmm.engine.cycle`
for the cycle that builds it.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any

__all__ = ["MarketSnapshot", "DEFAULT_TICK_SIZE"]

#: The venue's price grid when the market object does not publish one.
DEFAULT_TICK_SIZE = 0.01


def _as_float(value: Any, fallback: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return fallback


def _epoch(value: Any) -> float:
    """Epoch seconds from an ISO 8601 string, or 0.0 when there is none."""
    if isinstance(value, (int, float)) and not isinstance(value, bool):
        return float(value)
    if not isinstance(value, str) or not value.strip():
        return 0.0
    text = value.strip().replace("Z", "+00:00")
    try:
        parsed = datetime.fromisoformat(text)
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


@dataclass
class MarketSnapshot:
    """One binary market, as the engine sees it.

    Attributes:
        condition_id: Venue condition id.
        question: Market question, for logs and reports.
        up_token_id: Token id of the first outcome.
        down_token_id: Token id of the second outcome.
        tick_size: Venue price grid in probability units.
        min_order_size: Venue minimum order size in shares.
        reward_min_size: Venue liquidity-reward minimum size in shares.
        reward_max_spread_cents: Venue liquidity-reward maximum spread, cents.
        rate_per_day: Daily reward pool of this market, in pUSD.
        midpoint: Midpoint of the UP book, in probability units.
        book_up: Raw CLOB book of the UP token.
        book_down: Raw CLOB book of the DOWN token.
        expires_at: Epoch seconds of resolution, 0.0 when unknown.
        neg_risk: Whether the market sits in a neg-risk adapter market.
    """

    condition_id: str
    question: str = ""
    up_token_id: str = ""
    down_token_id: str = ""
    tick_size: float = DEFAULT_TICK_SIZE
    min_order_size: float = 0.0
    reward_min_size: float = 0.0
    reward_max_spread_cents: float = 0.0
    rate_per_day: float = 0.0
    midpoint: float = 0.5
    book_up: dict[str, Any] = field(default_factory=dict)
    book_down: dict[str, Any] = field(default_factory=dict)
    expires_at: float = 0.0
    neg_risk: bool = False

    @classmethod
    def from_clob_market(
        cls,
        clob_market: dict[str, Any],
        *,
        book_up: dict[str, Any] | None = None,
        book_down: dict[str, Any] | None = None,
        rewards_row: dict[str, Any] | None = None,
        rate_per_day: float | None = None,
        midpoint: float | None = None,
        tick_size: float | None = None,
        expires_at: float | None = None,
        neg_risk: bool | None = None,
    ) -> "MarketSnapshot":
        """Build a snapshot from a CLOB market object.

        ``rewards_row`` is one row of ``/rewards/markets/current``. It carries
        the authoritative reward min size, max spread and daily rate, which
        the market object itself only reports for markets whose reward
        configuration is still live.
        """
        tokens = clob_market.get("tokens") or ()
        token_ids = [str(token.get("token_id", "")) for token in tokens if isinstance(token, dict)]
        if not token_ids:
            token_ids = [str(token) for token in tokens]
        while len(token_ids) < 2:
            token_ids.append("")

        rewards = clob_market.get("rewards") or {}
        reward_min_size = _as_float(rewards.get("min_size"), 0.0)
        reward_max_spread = _as_float(rewards.get("max_spread"), 0.0)
        resolved_rate = 0.0

        if rewards_row is not None:
            reward_min_size = _as_float(
                rewards_row.get("rewards_min_size"), reward_min_size
            )
            reward_max_spread = _as_float(
                rewards_row.get("rewards_max_spread"), reward_max_spread
            )
            configs = rewards_row.get("rewards_config") or ()
            rates = [
                _as_float(config.get("rate_per_day"))
                for config in configs
                if isinstance(config, dict) and "rate_per_day" in config
            ]
            resolved_rate = max(rates) if rates else _as_float(
                rewards_row.get("native_daily_rate"), 0.0
            )

        if rate_per_day is not None:
            resolved_rate = float(rate_per_day)

        tick = tick_size
        if tick is None:
            raw_tick = clob_market.get("order_price_min_tick_size")
            if raw_tick is None:
                raw_tick = clob_market.get("tick_size")
            tick = _as_float(raw_tick, DEFAULT_TICK_SIZE) or DEFAULT_TICK_SIZE

        mid = midpoint
        if mid is None:
            mid = _as_float(
                (clob_market.get("tokens") or [{}])[0].get("price")
                if clob_market.get("tokens")
                else 0.5,
                0.5,
            )
        if book_up:
            from ..pricing.probability import implied_prob_from_book

            mid = implied_prob_from_book(book_up)

        expiry = expires_at
        if expiry is None:
            expiry = _epoch(
                clob_market.get("end_date_iso") or clob_market.get("end_date")
            )

        neg = neg_risk
        if neg is None:
            neg = bool(clob_market.get("neg_risk", False))

        return cls(
            condition_id=str(clob_market.get("condition_id", "")),
            question=str(clob_market.get("question", "")),
            up_token_id=token_ids[0],
            down_token_id=token_ids[1],
            tick_size=float(tick),
            min_order_size=_as_float(clob_market.get("order_min_size"), 0.0),
            reward_min_size=reward_min_size,
            reward_max_spread_cents=reward_max_spread,
            rate_per_day=resolved_rate,
            midpoint=float(mid),
            book_up=dict(book_up or {}),
            book_down=dict(book_down or {}),
            expires_at=float(expiry),
            neg_risk=bool(neg),
        )

    def to_dict(self) -> dict[str, Any]:
        """A JSON-serialisable view of the snapshot."""
        return {
            "condition_id": self.condition_id,
            "question": self.question,
            "up_token_id": self.up_token_id,
            "down_token_id": self.down_token_id,
            "tick_size": self.tick_size,
            "min_order_size": self.min_order_size,
            "reward_min_size": self.reward_min_size,
            "reward_max_spread_cents": self.reward_max_spread_cents,
            "rate_per_day": self.rate_per_day,
            "midpoint": self.midpoint,
            "book_up": self.book_up,
            "book_down": self.book_down,
            "expires_at": self.expires_at,
            "neg_risk": self.neg_risk,
        }

    @property
    def tau_seconds(self) -> float:
        """Seconds left to resolution, from ``now``. 0.0 when unknown."""
        if self.expires_at <= 0.0:
            return 0.0
        import time

        return max(self.expires_at - time.time(), 0.0)
