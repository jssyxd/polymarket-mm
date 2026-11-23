"""Risk gate stack for a two-sided binary market maker.

The stack answers one question per quote cycle: may we rest a bid on the UP
leg, the DOWN leg, or neither. Every gate owns exactly one trigger and
returns the same shape, so a gate can be exercised on its own and the order
of the stack can be reasoned about.

Units. Prices are probabilities in (0, 1). ``tick_size`` is the venue price
grid, ``max_inventory_per_side`` is the per-leg inventory box in shares,
``drawdown_pct`` is a percentage, ``oracle_age_seconds`` is age in seconds.
"""

from __future__ import annotations

import math
from dataclasses import dataclass, field
from typing import Protocol, Sequence

__all__ = [
    "MarketState",
    "GateDecision",
    "Gate",
    "HardStopGate",
    "InventoryBoxGate",
    "CooldownGate",
    "ToxicityGate",
    "ExpiryGate",
    "ERollingGate",
    "TickGate",
    "GateStack",
    "default_gates",
]


@dataclass
class MarketState:
    """Everything the gates need to know about one market right now.

    Attributes:
        up_shares: Shares held of the UP token.
        down_shares: Shares held of the DOWN token.
        max_inventory_per_side: Inventory box per leg, in shares. Zero means
            no box is configured and the inventory gate stays inactive.
        last_fill_side: Leg of the most recent fill, "up", "down", or None.
        last_fill_ts: Epoch seconds of that fill.
        now: Current epoch seconds.
        tau_seconds: Time left before resolution.
        fair_prob: External fair probability of the UP outcome.
        mid: Midpoint of the book for the UP leg.
        tick_size: Venue price grid.
        recent_net_bps: Net capture per fill in basis points, oldest first.
        equity_usd: Account equity in pUSD.
        drawdown_pct: Drawdown from peak equity, in percent.
        heartbeat_ok: False when the execution worker heartbeat is missing.
        oracle_age_seconds: Age of the external price feed.
        min_order_size: Venue minimum order size in shares.
    """

    up_shares: float = 0.0
    down_shares: float = 0.0
    max_inventory_per_side: float = 0.0
    last_fill_side: str | None = None
    last_fill_ts: float | None = None
    now: float = 0.0
    tau_seconds: float = 0.0
    fair_prob: float = 0.5
    mid: float = 0.5
    tick_size: float = 0.01
    recent_net_bps: list[float] = field(default_factory=list)
    equity_usd: float = 0.0
    drawdown_pct: float = 0.0
    heartbeat_ok: bool = True
    oracle_age_seconds: float = 0.0
    min_order_size: float = 0.0


@dataclass
class GateDecision:
    """The verdict of the gate stack for one cycle.

    Attributes:
        allowed_up: Whether a resting bid on the UP leg is permitted.
        allowed_down: Whether a resting bid on the DOWN leg is permitted.
        reasons: One string per gate that fired, in stack order.
        hard_stop: True when a hard stop gate fired. A hard stop is not a
            risk limit that can be widened, it is a full stop.
    """

    allowed_up: bool = True
    allowed_down: bool = True
    reasons: list[str] = field(default_factory=list)
    hard_stop: bool = False


class Gate(Protocol):
    """One trigger in the stack."""

    def evaluate(self, state: MarketState) -> tuple[bool, bool, str | None]:
        """Return (allowed_up, allowed_down, reason).

        The reason is None when the gate did not fire.
        """
        ...


def _floor_to_grid(price: float, tick: float) -> float:
    steps = math.floor(price / tick + 1e-9)
    return round(steps * tick, 10)


class HardStopGate:
    """Stops the maker when the process is not trustworthy.

    Fires on a missing heartbeat, a stale oracle, or a drawdown past the
    limit. Unlike every other gate this one blocks both legs outright.
    """

    is_hard_stop = True

    def __init__(
        self,
        max_oracle_age_seconds: float = 15.0,
        max_drawdown_pct: float = 20.0,
    ) -> None:
        self.max_oracle_age_seconds = max_oracle_age_seconds
        self.max_drawdown_pct = max_drawdown_pct

    def evaluate(self, state: MarketState) -> tuple[bool, bool, str | None]:
        reasons: list[str] = []
        if not state.heartbeat_ok:
            reasons.append("hard_stop_heartbeat_lost")
        if state.oracle_age_seconds > self.max_oracle_age_seconds:
            reasons.append(f"hard_stop_oracle_stale_{state.oracle_age_seconds:.1f}s")
        if state.drawdown_pct > self.max_drawdown_pct:
            reasons.append(f"hard_stop_drawdown_{state.drawdown_pct:.1f}pct")
        if not reasons:
            return (True, True, None)
        return (False, False, ";".join(reasons))


class InventoryBoxGate:
    """Blocks a leg whose inventory box is full.

    The other leg stays allowed so the position can still be flattened.
    """

    def evaluate(self, state: MarketState) -> tuple[bool, bool, str | None]:
        box = state.max_inventory_per_side
        if box <= 0.0:
            return (True, True, None)
        up_full = state.up_shares >= box
        down_full = state.down_shares >= box
        if not up_full and not down_full:
            return (True, True, None)
        reasons: list[str] = []
        if up_full:
            reasons.append("inventory_box_up")
        if down_full:
            reasons.append("inventory_box_down")
        return (not up_full, not down_full, ";".join(reasons))


class CooldownGate:
    """Blocks the leg that just filled for a short cooling period.

    A fill on one leg means the book moved against us there. Quoting the
    same leg again immediately invites a second adverse fill.
    """

    def __init__(self, cooldown_seconds: float = 5.0) -> None:
        self.cooldown_seconds = cooldown_seconds

    def evaluate(self, state: MarketState) -> tuple[bool, bool, str | None]:
        side = state.last_fill_side
        if side not in ("up", "down") or state.last_fill_ts is None:
            return (True, True, None)
        elapsed = state.now - state.last_fill_ts
        if elapsed >= self.cooldown_seconds:
            return (True, True, None)
        elapsed = max(elapsed, 0.0)
        reason = f"cooldown_{side}_{elapsed:.1f}s"
        return (side != "up", side != "down", reason)


class ToxicityGate:
    """Blocks both legs when the external fair value and the book disagree.

    A gap this wide means the feed and the book are pricing different
    events, so any quote we place is either stale or crossing.
    """

    def __init__(self, max_gap: float = 0.03) -> None:
        self.max_gap = max_gap

    def evaluate(self, state: MarketState) -> tuple[bool, bool, str | None]:
        gap = abs(state.fair_prob - state.mid)
        if gap <= self.max_gap + 1e-9:
            return (True, True, None)
        return (False, False, f"toxicity_fair_mid_gap_{gap:.4f}")


class ExpiryGate:
    """Blocks both legs close to resolution.

    A position has to be closed before the market settles, not held into it.
    """

    def __init__(self, min_tau_seconds: float = 90.0) -> None:
        self.min_tau_seconds = min_tau_seconds

    def evaluate(self, state: MarketState) -> tuple[bool, bool, str | None]:
        if state.tau_seconds >= self.min_tau_seconds:
            return (True, True, None)
        return (False, False, f"expiry_tau_{state.tau_seconds:.0f}s")


class ERollingGate:
    """The first-priority alarm: net capture over the recent fills.

    When the mean net capture per notional is at or below zero the maker is
    paying to trade. The upstream account lost 0.55 bp per notional traded
    while believing it was capturing 4.5 bp, so this gate stops the book
    rather than trying to price around a negative edge.
    """

    def __init__(self, window: int = 100, max_net_bps: float = 0.0) -> None:
        self.window = window
        self.max_net_bps = max_net_bps

    def evaluate(self, state: MarketState) -> tuple[bool, bool, str | None]:
        values = list(state.recent_net_bps)[-self.window:]
        if not values:
            return (True, True, None)
        mean = sum(values) / len(values)
        if mean > self.max_net_bps:
            return (True, True, None)
        return (False, False, f"e_rolling_{len(values)}_{mean:+.2f}bp")


class TickGate:
    """Blocks a leg whose order cannot be placed as specified.

    Two ways that happens: the resting price falls outside the venue price
    band, or the room left inside the inventory box is smaller than one
    minimum order, so any order we place either breaks the box or is
    rejected by the venue.
    """

    def __init__(
        self,
        tick_size: float | None = None,
        min_order_size: float | None = None,
    ) -> None:
        self.tick_size = tick_size
        self.min_order_size = min_order_size

    def evaluate(self, state: MarketState) -> tuple[bool, bool, str | None]:
        tick = self.tick_size if self.tick_size is not None else state.tick_size
        if tick <= 0.0:
            return (True, True, None)
        min_size = (
            self.min_order_size
            if self.min_order_size is not None
            else state.min_order_size
        )
        box = state.max_inventory_per_side
        sides = (
            ("up", _floor_to_grid(state.mid, tick), state.up_shares),
            ("down", _floor_to_grid(1.0 - state.mid, tick), state.down_shares),
        )
        results: dict[str, list[str]] = {}
        for side, price, shares in sides:
            reasons: list[str] = []
            if price < tick or price > 1.0 - tick:
                reasons.append(f"tick_{side}_price_not_placeable")
            if min_size > 0.0 and box > 0.0:
                remaining = box - shares
                if 0.0 < remaining < min_size:
                    reasons.append(f"tick_{side}_size_below_minimum")
            results[side] = reasons
        up_reasons = results["up"]
        down_reasons = results["down"]
        if not up_reasons and not down_reasons:
            return (True, True, None)
        return (
            not up_reasons,
            not down_reasons,
            ";".join(up_reasons + down_reasons),
        )


def default_gates() -> list[Gate]:
    """The gate stack in the order the maker applies it."""
    return [
        HardStopGate(),
        InventoryBoxGate(),
        CooldownGate(),
        ToxicityGate(),
        ExpiryGate(),
        ERollingGate(),
        TickGate(),
    ]


class GateStack:
    """Evaluates an ordered list of gates against one market state.

    A gate can only remove permission, never grant it, so the order of the
    stack decides which reason is reported first but never changes the
    verdict of a gate that blocks both legs. A hard stop therefore survives
    a later permissive gate.
    """

    def __init__(self, gates: Sequence[Gate] | None = None) -> None:
        self.gates: list[Gate] = list(gates) if gates is not None else default_gates()

    def evaluate(self, state: MarketState) -> GateDecision:
        allowed_up = True
        allowed_down = True
        reasons: list[str] = []
        hard_stop = False
        for gate in self.gates:
            up, down, reason = gate.evaluate(state)
            allowed_up = allowed_up and up
            allowed_down = allowed_down and down
            if reason:
                reasons.append(reason)
            if getattr(gate, "is_hard_stop", False) and not up and not down:
                hard_stop = True
        return GateDecision(
            allowed_up=allowed_up,
            allowed_down=allowed_down,
            reasons=reasons,
            hard_stop=hard_stop,
        )
