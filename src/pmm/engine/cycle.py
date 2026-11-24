"""The quote cycle: one pass over the candidate markets.

The pair invariant, and why the quote is two resting bids.

A Polymarket binary is a pair of complementary tokens. A complete set, one
UP and one DOWN, redeems for exactly 1 pUSD. So when the maker rests a bid on
both legs, at ``p - delta`` on UP and ``(1 - p) - delta`` on DOWN, a paired
fill costs ``1 - 2 * delta`` and merges back to 1 pUSD. The gain is
``2 * delta`` per share pair and it does not depend on which way the event
resolves.

That is the whole profit source, and it is why the quote is two resting
bids, never a bid and an ask. Selling a leg would need the outcome token in
hand, which means splitting pUSD first, and the paired gain would be spent on
the round trip. The maker buys the pair cheaper than the merge pays for it.

The invariant the cycle enforces is therefore:

    bid_up + bid_down <= 1 - tick_size

A paired fill always leaves a positive mergeable margin, at least one tick.
:func:`pmm.pricing.quotes.build_quotes` enforces it while rounding onto the
price grid; the cycle re-checks it before anything is sent, because an order
that breaks the invariant is an order that converts a riskless pair into a
directional bet.

Order of operations, and it matters:

1. The gate stack runs before any intent is emitted. A gate that blocks a leg
   removes that leg and records why. A hard stop removes the whole market.
2. The quote is built from the market's own reward settings, so the resting
   price stays inside the venue's reward band and the size is at least the
   venue's minimum.
3. Only then are the intents emitted, and every intent carries
   ``post_only=True``.
"""

from __future__ import annotations

import time
from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..core.inventory import PairedInventory
from ..core.market import MarketSnapshot
from ..core.selection import (
    QuoteIntent,
    QuotePlan,
    SelectionResult,
    effective_half_spread_cents,
    select_quotes,
)
from ..data.universe import size_cutoff_midpoint
from ..pricing.quotes import Quote, build_quotes
from ..risk.gates import GateDecision, GateStack, MarketState

__all__ = ["CycleResult", "QuoteCycle", "DEFAULT_HALF_SPREAD_CENTS", "DEFAULT_SIZE_SHARES"]

#: The half-spread the cycle runs before the self-tune step has an opinion.
DEFAULT_HALF_SPREAD_CENTS = 1.0

#: Shares per side before the self-tune step has an opinion.
DEFAULT_SIZE_SHARES = 20.0

#: Fallback horizon when a market publishes no resolution time.
DEFAULT_TAU_SECONDS = 600.0


@dataclass
class CycleResult:
    """Everything one cycle decided.

    Attributes:
        intents: The quote intents to send.
        plans: The per-market plans the cycle built.
        selection: The selector's verdict.
        rejected: One reason per market or leg that was dropped.
        hard_stops: Condition ids a hard stop gate removed.
        quoted: Condition ids that were quoted.
        committed_usd: Capital committed by the quoted markets.
        capital_usd: The budget the cycle ran against.
    """

    intents: list[QuoteIntent] = field(default_factory=list)
    plans: list[QuotePlan] = field(default_factory=list)
    selection: SelectionResult = field(default_factory=SelectionResult)
    rejected: list[str] = field(default_factory=list)
    hard_stops: list[str] = field(default_factory=list)
    quoted: list[str] = field(default_factory=list)
    committed_usd: float = 0.0
    capital_usd: float = 0.0
    quoting_enabled: bool = True

    @property
    def intent_count(self) -> int:
        return len(self.intents)

    def summary(self) -> str:
        """One line an operator can read at a glance."""
        return (
            f"markets={len(self.plans)} quoted={len(self.quoted)} "
            f"intents={len(self.intents)} committed={self.committed_usd:.3f}/"
            f"{self.capital_usd:.3f} pUSD hard_stops={len(self.hard_stops)}"
            + ("" if self.quoting_enabled else " quoting_disabled")
        )


class QuoteCycle:
    """Builds the two-sided quote for each candidate and gates it.

    The cycle is a pure function of its arguments: no clock read beyond the
    gate state, no network call, no shared state. The runner owns the
    journal and the venue connection.
    """

    def __init__(
        self,
        gates: GateStack | None = None,
        *,
        min_rate_per_day: float = 0.0,
        max_spread_cents_cap: float | None = None,
        max_markets: int = 4,
        default_tau_seconds: float = DEFAULT_TAU_SECONDS,
        gamma: float = 0.15,
    ) -> None:
        self.gates = gates if gates is not None else GateStack()
        self.min_rate_per_day = min_rate_per_day
        self.max_spread_cents_cap = max_spread_cents_cap
        self.max_markets = max_markets
        self.default_tau_seconds = default_tau_seconds
        self.gamma = gamma

    # -- helpers ----------------------------------------------------------

    def _state(
        self,
        snapshot: MarketSnapshot,
        inventory: PairedInventory,
        fair_prob: float,
        mid: float,
        tau_seconds: float,
        recent_net_bps: Sequence[float],
        equity_usd: float,
        last_fill: tuple[str | None, float | None],
        heartbeat_ok: bool,
    ) -> MarketState:
        side, ts = last_fill
        return MarketState(
            up_shares=inventory.up_shares,
            down_shares=inventory.down_shares,
            max_inventory_per_side=inventory.max_inventory_per_side,
            last_fill_side=side,
            last_fill_ts=ts,
            now=time.time(),
            tau_seconds=tau_seconds,
            fair_prob=fair_prob,
            mid=mid,
            tick_size=snapshot.tick_size,
            recent_net_bps=list(recent_net_bps),
            equity_usd=equity_usd,
            drawdown_pct=0.0,
            heartbeat_ok=heartbeat_ok,
            oracle_age_seconds=0.0,
            min_order_size=snapshot.min_order_size,
        )

    def _quote(
        self,
        snapshot: MarketSnapshot,
        fair_prob: float,
        sigma_p: float,
        tau_seconds: float,
        inventory: PairedInventory,
        half_spread_cents: float,
        size_shares: float,
    ) -> Quote:
        return build_quotes(
            fair_prob=fair_prob,
            sigma_p=sigma_p,
            tau_seconds=tau_seconds,
            tick_size=snapshot.tick_size,
            min_size=size_shares,
            inventory=inventory.to_quote_inventory(),
            half_spread_cents=effective_half_spread_cents(half_spread_cents, snapshot),
            reward_max_spread_cents=snapshot.reward_max_spread_cents,
            min_reward_size=snapshot.reward_min_size,
            gamma=self.gamma,
        )

    # -- the cycle --------------------------------------------------------

    def run(
        self,
        snapshots: Sequence[MarketSnapshot],
        params: Mapping[str, Any] | None = None,
        *,
        candidates: Sequence[Any] | None = None,
        inventory: Mapping[str, PairedInventory] | None = None,
        last_fills: Mapping[str, tuple[str | None, float | None]] | None = None,
        recent_net_bps: Sequence[float] = (),
        capital_usd: float = 0.0,
        size_shares: float | None = None,
        equity_usd: float = 0.0,
        heartbeat_ok: bool = True,
    ) -> CycleResult:
        """Run one quote cycle.

        ``params`` is the parameter file the self-tune step maintains. It
        supplies the half-spread, the size and the quoting switch.
        """
        settings = dict(params or {})
        result = CycleResult(capital_usd=float(capital_usd))

        if not bool(settings.get("quoting_enabled", True)):
            result.quoting_enabled = False
            return result

        half_spread_cents = float(
            settings.get("half_spread_cents", DEFAULT_HALF_SPREAD_CENTS)
        )
        size = float(size_shares if size_shares is not None else settings.get("size_shares", DEFAULT_SIZE_SHARES))
        sigma_p = float(settings.get("sigma_p", 0.0) or 0.0)
        box = float(settings.get("inventory_box", 0.0) or 0.0)

        by_condition = {
            getattr(candidate, "condition_id", ""): candidate
            for candidate in (candidates or [])
        }
        inventories = inventory or {}
        fills = last_fills or {}

        plans: list[QuotePlan] = []
        for snapshot in snapshots:
            candidate = by_condition.get(snapshot.condition_id)
            position = inventories.get(snapshot.condition_id) or PairedInventory(
                max_inventory_per_side=box
            )
            if position.max_inventory_per_side <= 0.0:
                position = PairedInventory(
                    up_shares=position.up_shares,
                    down_shares=position.down_shares,
                    max_inventory_per_side=box,
                    mark_up=position.mark_up,
                    mark_down=position.mark_down,
                )

            mid = snapshot.midpoint
            cutoff_size = max(snapshot.reward_min_size, snapshot.min_order_size)
            fair_prob = size_cutoff_midpoint(snapshot.book_up, cutoff_size, mid)

            tau = snapshot.tau_seconds or self.default_tau_seconds
            tau = max(tau, 1.0)

            try:
                quote = self._quote(
                    snapshot,
                    fair_prob,
                    sigma_p,
                    tau,
                    position,
                    half_spread_cents,
                    size,
                )
            except ValueError as exc:
                result.rejected.append(f"{snapshot.condition_id}: quote rejected: {exc}")
                continue

            cap = 1.0 - snapshot.tick_size
            if quote.up.price + quote.down.price > cap + 1e-9:
                result.rejected.append(
                    f"{snapshot.condition_id}: pair invariant broken "
                    f"({quote.up.price} + {quote.down.price} > {cap})"
                )
                continue

            decision: GateDecision = self.gates.evaluate(
                self._state(
                    snapshot,
                    position,
                    fair_prob,
                    mid,
                    tau,
                    recent_net_bps,
                    equity_usd,
                    fills.get(snapshot.condition_id, (None, None)),
                    heartbeat_ok,
                )
            )
            if decision.hard_stop:
                result.hard_stops.append(snapshot.condition_id)

            plans.append(
                QuotePlan(
                    snapshot=snapshot,
                    quote=quote,
                    decision=decision,
                    candidate=candidate,
                    reasons=tuple(r for r in quote.reason.split(";") if r),
                )
            )

        result.plans = plans
        selection = select_quotes(
            plans,
            capital_usd=capital_usd,
            size_shares=size,
            half_spread_cents=half_spread_cents,
            min_rate_per_day=self.min_rate_per_day,
            max_spread_cents_cap=self.max_spread_cents_cap,
            max_markets=self.max_markets,
            max_market_usd=float(settings.get("max_market_usd", 0.0) or 0.0),
        )
        result.selection = selection
        result.intents = list(selection.intents)
        result.quoted = list(selection.selected)
        result.committed_usd = selection.committed_usd
        result.rejected.extend(selection.rejected)
        return result
