"""The hourly self-tuning monitor agent.

The agent reads the metrics, applies at most one parameter change, and
reports what it saw and what it did. It is conservative on purpose: the
account it protects lost 0.55 bp per notional traded while every layer of
the upstream stack still said "healthy", so the first thing the agent does
when net capture is at or below zero is stop, not retune.

The parameter vocabulary is a plain dict so the agent can be driven from a
config file, a journal, or a test:

``quoting_enabled``
    Whether the maker quotes at all.
``half_spread_cents``
    Half-spread of the resting quotes, in cents.
``max_spread_cents``
    The venue's reward spread band for this market. The half-spread is
    never widened past it, because a quote outside the band earns no
    reward at all.
``inventory_box``
    Per-leg inventory box, in shares.
"""

from __future__ import annotations

import time

from ..risk.gates import GateStack, MarketState
from .metrics import (
    fill_timestamp,
    inventory_exposure,
    pair_coverage,
    realized_bps,
    rolling_net_bps,
    win_rate,
)

__all__ = ["MonitorAgent", "PARAM_QUOTING", "PARAM_HALF_SPREAD", "PARAM_INVENTORY_BOX"]

PARAM_QUOTING = "quoting_enabled"
PARAM_HALF_SPREAD = "half_spread_cents"
PARAM_INVENTORY_BOX = "inventory_box"

_HOUR_SECONDS = 3600.0


class MonitorAgent:
    """Applies at most one conservative parameter change per hourly tick.

    Rules, in order of preference:

    1. Rolling net capture at or below zero: stop quoting. Losing money
       while quoting more is how the upstream account bled.
    2. No fill in the last hour while the account is eligible to quote:
       widen the half-spread by one cent, so the quote can find a counterparty.
    3. Rolling net capture positive and the inventory box at least half
       full: raise the box by 25 percent, so a profitable maker can hold
       more of a position it is good at.
    4. Otherwise change nothing.
    """

    def __init__(
        self,
        gates: GateStack | None = None,
        window: int = 100,
        spread_step_cents: float = 1.0,
        box_step: float = 0.25,
        half_full: float = 0.5,
    ) -> None:
        self.gates = gates if gates is not None else GateStack()
        self.window = window
        self.spread_step_cents = spread_step_cents
        self.box_step = min(max(box_step, 0.0), 0.25)
        self.half_full = half_full

    def run_once(
        self,
        state: MarketState,
        fill_history: list[dict],
        current_params: dict,
        intents_last_hour: int | None = None,
    ) -> dict:
        """Run one tuning tick and return the decision record.

        ``intents_last_hour`` is how many order intents the maker placed in
        the last hour. When it is zero the maker was not quoting, so a tick
        with no fills carries no evidence about the spread and must not
        widen it. When it is None the caller does not know, and the widen
        rule is allowed to fire.
        """
        params = dict(current_params or {})
        fills = list(fill_history or [])
        metrics = self._metrics(state, fills, params)
        metrics["intents_last_hour"] = intents_last_hour
        gate_decision = self.gates.evaluate(state)
        metrics["hard_stop"] = gate_decision.hard_stop
        metrics["gate_reasons"] = list(gate_decision.reasons)

        quoting = bool(params.get(PARAM_QUOTING, True))
        half_spread = float(params.get(PARAM_HALF_SPREAD, 0.0) or 0.0)
        max_spread = float(params.get("max_spread_cents", 0.0) or 0.0)
        box = float(params.get(PARAM_INVENTORY_BOX, state.max_inventory_per_side) or 0.0)

        rolling = metrics["rolling_net_bps"]
        fills_last_hour = metrics["fills_last_hour"]
        was_quoting = intents_last_hour is None or intents_last_hour > 0
        eligible = (
            quoting
            and not gate_decision.hard_stop
            and (gate_decision.allowed_up or gate_decision.allowed_down)
        )

        # Rule 1: the loss alarm. No tuning happens while losing.
        if fills and rolling <= 0.0:
            reason = (
                f"rolling_net_bps_{rolling:+.2f}_at_or_below_zero_"
                "freeze_quoting"
            )
            if not quoting:
                return self._record(
                    changed=False,
                    param=PARAM_QUOTING,
                    from_value=quoting,
                    to_value=quoting,
                    reason=f"{reason}_already_stopped",
                    action="stop",
                    metrics=metrics,
                )
            return self._record(
                changed=True,
                param=PARAM_QUOTING,
                from_value=True,
                to_value=False,
                reason=reason,
                action="stop",
                metrics=metrics,
            )

        # Rule 2: the market did not fill while we were quoting. Widen by one
        # cent, never past the venue's reward band. With no intents in the
        # last hour there is no evidence about the spread, so the spread is
        # left alone.
        if eligible and fills_last_hour == 0 and was_quoting:
            if max_spread <= 0.0:
                return self._record(
                    changed=False,
                    param=PARAM_HALF_SPREAD,
                    from_value=half_spread,
                    to_value=half_spread,
                    reason="no_fills_in_last_hour_max_spread_cents_unknown",
                    action="hold",
                    metrics=metrics,
                )
            # The cap is 80 percent of the band, not the band itself. The
            # score is ((v - s) / v) squared, so a quote at the band edge
            # scores exactly zero, and a maker that widened to the edge would
            # earn nothing while paying for the privilege of never filling.
            target = min(half_spread + self.spread_step_cents, max_spread * 0.8)
            if target <= half_spread:
                return self._record(
                    changed=False,
                    param=PARAM_HALF_SPREAD,
                    from_value=half_spread,
                    to_value=half_spread,
                    reason=(
                        f"no_fills_in_last_hour_half_spread_at_"
                        f"max_spread_{max_spread:g}c"
                    ),
                    action="hold",
                    metrics=metrics,
                )
            return self._record(
                changed=True,
                param=PARAM_HALF_SPREAD,
                from_value=half_spread,
                to_value=target,
                reason=(
                    f"no_fills_in_last_hour_widen_half_spread_"
                    f"{half_spread:g}c_to_{target:g}c"
                ),
                action="widen",
                metrics=metrics,
            )

        # Rule 3: profitable and busy, so carry more inventory. Never while
        # losing, and never by more than one 25 percent step.
        if (
            eligible
            and rolling > 0.0
            and metrics["inventory_utilization"] >= self.half_full
        ):
            target = box * (1.0 + self.box_step)
            return self._record(
                changed=True,
                param=PARAM_INVENTORY_BOX,
                from_value=box,
                to_value=target,
                reason=(
                    f"rolling_net_bps_{rolling:+.2f}_positive_and_inventory_"
                    f"box_{metrics['inventory_utilization']:.0%}_full_"
                    f"raise_box_{self.box_step:.0%}"
                ),
                action="raise_box",
                metrics=metrics,
            )

        return self._record(
            changed=False,
            param=None,
            from_value=None,
            to_value=None,
            reason="no_rule_fired",
            action="hold",
            metrics=metrics,
        )

    def _metrics(
        self,
        state: MarketState,
        fills: list[dict],
        params: dict,
    ) -> dict:
        now = state.now if state.now > 0.0 else time.time()
        cutoff = now - _HOUR_SECONDS
        fills_last_hour = 0
        for fill in fills:
            ts = fill_timestamp(fill)
            if ts is not None and ts > cutoff:
                fills_last_hour += 1
        mark_up = state.fair_prob
        mark_down = 1.0 - state.fair_prob
        box = float(params.get(PARAM_INVENTORY_BOX, state.max_inventory_per_side) or 0.0)
        used = max(state.up_shares, state.down_shares)
        utilization = used / box if box > 0.0 else 0.0
        metrics = {
            "fill_count": len(fills),
            "fills_last_hour": fills_last_hour,
            "realized_bps": realized_bps(fills, {}),
            "rolling_net_bps": rolling_net_bps(fills, self.window),
            "win_rate": win_rate(fills),
            "inventory_exposure": inventory_exposure(
                state.up_shares, state.down_shares, mark_up, mark_down
            ),
            "pair_coverage": pair_coverage(state.up_shares, state.down_shares),
            "inventory_utilization": utilization,
            "equity_usd": state.equity_usd,
            "drawdown_pct": state.drawdown_pct,
            "hard_stop": False,
            "gate_reasons": [],
        }
        rate = params.get("rate_per_day")
        q_min = params.get("q_min")
        total_q_min = params.get("total_q_min")
        if rate is not None and q_min is not None and total_q_min is not None:
            from .metrics import reward_estimate

            metrics["reward_estimate"] = reward_estimate(
                float(params.get("rewards_min_size", 0.0) or 0.0),
                float(params.get("max_spread_cents", 0.0) or 0.0),
                float(rate),
                float(q_min),
                float(total_q_min),
            )
        return metrics

    @staticmethod
    def _record(
        changed: bool,
        param: str | None,
        from_value,
        to_value,
        reason: str,
        action: str,
        metrics: dict,
    ) -> dict:
        return {
            "changed": changed,
            "param": param,
            "from_value": from_value,
            "to_value": to_value,
            "reason": reason,
            "action": action,
            "metrics": metrics,
        }
