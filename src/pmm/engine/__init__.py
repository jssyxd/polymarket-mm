"""The service: quote cycle, service loop, hourly self-adjustment.

Three modules, and the order of a service lifetime is the order of the
imports below.

:mod:`pmm.engine.cycle`
    Builds the two-sided quote for each candidate market, runs the gate
    stack, and emits post-only order intents. The quote is two resting bids
    because the profit is a paired fill that merges back to 1 pUSD.
:mod:`pmm.engine.runner`
    The service loop. It owns the journal, the heartbeat and the
    reconciliation of resting orders against the live book.
:mod:`pmm.engine.self_tune`
    The hourly step. It reads the journal, runs the monitor agent once and
    writes the parameters back atomically.
"""

from __future__ import annotations

from .cycle import CycleResult, QuoteCycle
from .runner import Runner, RunnerConfig, discover_markets
from .self_tune import DEFAULT_PARAMS, load_params, run_self_tune, write_params

__all__ = [
    "CycleResult",
    "DEFAULT_PARAMS",
    "QuoteCycle",
    "Runner",
    "RunnerConfig",
    "discover_markets",
    "load_params",
    "run_self_tune",
    "write_params",
]
