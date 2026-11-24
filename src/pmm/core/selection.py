"""Which market do we quote this cycle, and on which legs.

The selector is the budget and the gate verdict folded into one decision. It
takes the candidate list, the capital budget, the size we want on each side,
the half-spread we are running and the gate decision per market, and returns
the quote intents to send this cycle, each with the reason it was kept or
dropped.

Two rules shape it.

The gate verdict comes first. A gate that blocks a leg removes that leg and
nothing else; a hard stop removes the whole market and the cycle records it.

The capital budget is the existing one from :mod:`pmm.data.universe`: a
quote commits the cost of its cheaper leg, because the pair funds itself on
merge. The same model is used here, so the candidate scan and the cycle
agree on what fits.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from typing import Any, Mapping, Sequence

from ..pricing.quotes import Quote
from ..risk.gates import GateDecision
from .market import MarketSnapshot

__all__ = [
    "QuoteIntent",
    "QuotePlan",
    "SelectionResult",
    "effective_half_spread_cents",
    "select_quotes",
]


def effective_half_spread_cents(half_spread_cents: float, snapshot: MarketSnapshot) -> float:
    """The half-spread to use on one market.

    The parameter file sets the half-spread, but the venue's reward band is
    the hard ceiling: a quote wider than the band earns no reward at all, so
    the half-spread is clamped to the market's reward max spread.
    """
    cap = snapshot.reward_max_spread_cents
    if cap <= 0.0:
        return float(half_spread_cents)
    return float(min(half_spread_cents, cap))


@dataclass(frozen=True)
class QuoteIntent:
    """One resting order the cycle wants to place.

    Attributes:
        condition_id: Market the order belongs to.
        question: Market question, for logs.
        leg: "up" or "down".
        token_id: Venue token id of the leg.
        price: Limit price in probability units.
        size: Order size in shares.
        side: "BUY". Both legs are buys, never a bid and an ask.
        post_only: Always True. The venue rejects a crossing order.
        reason: Why this intent exists.
        tick_size: Venue price grid of the market.
        neg_risk: Whether the market sits in a neg-risk adapter market.
        kind: "quote" for a resting bid, "harvest" for a Plan B exit sell.
    """

    condition_id: str
    question: str
    leg: str
    token_id: str
    price: float
    size: float
    side: str = "BUY"
    post_only: bool = True
    reason: str = ""
    tick_size: float = 0.01
    neg_risk: bool = False
    kind: str = "quote"

    def to_payload(self) -> dict[str, Any]:
        """The dict the execution layer takes."""
        return {
            "token_id": self.token_id,
            "price": self.price,
            "size": self.size,
            "side": self.side,
            "post_only": self.post_only,
            "tick_size": self.tick_size,
            "neg_risk": self.neg_risk,
            "condition_id": self.condition_id,
            "leg": self.leg,
            "reason": self.reason,
        }


@dataclass(frozen=True)
class QuotePlan:
    """A candidate market with its built quote and its gate verdict.

    Attributes:
        snapshot: The market snapshot.
        quote: The two-sided quote built for it.
        decision: The gate stack's verdict for this market.
        candidate: The reward candidate, when the market came from a scan.
        reasons: Notes carried over from the quote builder.
    """

    snapshot: MarketSnapshot
    quote: Quote
    decision: GateDecision
    candidate: Any = None
    reasons: tuple[str, ...] = ()


@dataclass
class SelectionResult:
    """What the selector decided.

    Attributes:
        intents: The quote intents to send this cycle.
        selected: Condition ids that were quoted.
        rejected: One reason per market that was not quoted.
        committed_usd: Capital committed by the selected markets.
        capital_usd: The budget the selection ran against.
    """

    intents: list[QuoteIntent] = field(default_factory=list)
    selected: list[str] = field(default_factory=list)
    rejected: list[str] = field(default_factory=list)
    committed_usd: float = 0.0
    capital_usd: float = 0.0

    @property
    def market_count(self) -> int:
        return len(self.selected)


def _commit_usd(
    plan: QuotePlan,
    size_shares: float,
) -> float:
    """pUSD the quote commits.

    The candidate's notional is the venue minimum sized at the cheaper leg.
    When we quote more than the venue minimum, the commitment scales with the
    size.
    """
    candidate = plan.candidate
    if candidate is not None and getattr(candidate, "min_size", 0.0) > 0.0:
        per_min = float(candidate.notional_usd) / float(candidate.min_size)
        return per_min * size_shares
    up = plan.quote.up.price
    down = plan.quote.down.price
    return size_shares * min(up, down)


def select_quotes(
    plans: Sequence[QuotePlan],
    capital_usd: float,
    size_shares: float,
    half_spread_cents: float,
    *,
    min_rate_per_day: float = 0.0,
    max_spread_cents_cap: float | None = None,
    max_markets: int = 4,
    max_market_usd: float = 0.0,
) -> SelectionResult:
    """Choose the markets to quote this cycle.

    Markets are taken in order of estimated share of the daily reward pool.
    Each market is kept when its rate clears ``min_rate_per_day``, its reward
    spread band is inside ``max_spread_cents_cap``, its size is legal for the
    venue, and it fits in the remaining capital.
    """
    result = SelectionResult(capital_usd=float(capital_usd))

    ordered = sorted(
        plans,
        key=lambda plan: (
            -float(getattr(plan.candidate, "est_share_pct", 0.0) or 0.0),
            -plan.snapshot.rate_per_day,
        ),
    )

    remaining = float(capital_usd)
    for plan in ordered:
        snapshot = plan.snapshot
        decision = plan.decision
        label = snapshot.condition_id or snapshot.question

        if decision.hard_stop:
            result.rejected.append(f"{label}: hard_stop: {';'.join(decision.reasons)}")
            continue

        if snapshot.rate_per_day < min_rate_per_day:
            result.rejected.append(
                f"{label}: rate_per_day {snapshot.rate_per_day:.2f} below "
                f"minimum {min_rate_per_day:.2f}"
            )
            continue

        if (
            max_spread_cents_cap is not None
            and snapshot.reward_max_spread_cents > max_spread_cents_cap
        ):
            result.rejected.append(
                f"{label}: reward_max_spread {snapshot.reward_max_spread_cents:.2f}c "
                f"above cap {max_spread_cents_cap:.2f}c"
            )
            continue

        required_size = max(snapshot.min_order_size, snapshot.reward_min_size)
        if required_size > 0.0 and size_shares < required_size:
            result.rejected.append(
                f"{label}: size {size_shares:g} below venue minimum {required_size:g} shares"
            )
            continue

        commit = _commit_usd(plan, size_shares)
        # The budget model counts the cheaper leg (the pair funds itself on
        # merge), but the venue reserves both resting bids. A per-market
        # exposure cap must use what is actually at risk, so it sums both.
        notional = float(size_shares) * (
            float(plan.quote.up.price) + float(plan.quote.down.price)
        )
        if max_market_usd > 0.0 and notional > max_market_usd + 1e-9:
            result.rejected.append(
                f"{label}: reserves {notional:.3f} pUSD across both legs, above "
                f"the per-market cap {max_market_usd:.3f}"
            )
            continue
        if commit > remaining + 1e-9:
            result.rejected.append(
                f"{label}: needs {commit:.3f} pUSD, {remaining:.3f} pUSD left in the budget"
            )
            continue

        legs = (("up", plan.quote.up), ("down", plan.quote.down))
        intents: list[QuoteIntent] = []
        for leg, side in legs:
            token_id = snapshot.up_token_id if leg == "up" else snapshot.down_token_id
            allowed = decision.allowed_up if leg == "up" else decision.allowed_down
            if not allowed:
                result.rejected.append(
                    f"{label}: {leg} leg blocked by gate: {';'.join(decision.reasons)}"
                )
                continue
            if side.size <= 0.0 or side.price <= 0.0:
                result.rejected.append(f"{label}: {leg} leg has no placeable size or price")
                continue
            intents.append(
                QuoteIntent(
                    condition_id=snapshot.condition_id,
                    question=snapshot.question,
                    leg=leg,
                    token_id=token_id,
                    price=side.price,
                    size=side.size,
                    side="BUY",
                    post_only=True,
                    reason=(
                        f"paired_bid half_spread "
                        f"{effective_half_spread_cents(half_spread_cents, snapshot):g}c "
                        f"reward_band {snapshot.reward_max_spread_cents:g}c"
                    ),
                    tick_size=snapshot.tick_size,
                    neg_risk=snapshot.neg_risk,
                )
            )

        if not intents:
            continue

        remaining -= commit
        result.committed_usd += commit
        result.intents.extend(intents)
        result.selected.append(snapshot.condition_id)

        if len(result.selected) >= max_markets:
            break

    return result


def decisions_by_market(
    decisions: Mapping[str, GateDecision] | None,
    condition_id: str,
) -> GateDecision:
    """The gate verdict for one market, defaulting to a permissive one."""
    if decisions:
        found = decisions.get(condition_id)
        if found is not None:
            return found
    return GateDecision(allowed_up=True, allowed_down=True)
