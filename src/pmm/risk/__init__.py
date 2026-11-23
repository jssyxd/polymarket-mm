"""Risk gates for the Polymarket binary maker.

The stack is deliberately boring: one class per trigger, one method, one
tuple in and one tuple out. Everything the maker needs to know about the
account and the market arrives as a :class:`~pmm.risk.gates.MarketState`,
and the verdict comes back as a :class:`~pmm.risk.gates.GateDecision`.
"""

from __future__ import annotations

from .gates import (
    CooldownGate,
    ERollingGate,
    ExpiryGate,
    Gate,
    GateDecision,
    GateStack,
    HardStopGate,
    InventoryBoxGate,
    MarketState,
    TickGate,
    ToxicityGate,
    default_gates,
)

__all__ = [
    "CooldownGate",
    "ERollingGate",
    "ExpiryGate",
    "Gate",
    "GateDecision",
    "GateStack",
    "HardStopGate",
    "InventoryBoxGate",
    "MarketState",
    "TickGate",
    "ToxicityGate",
    "default_gates",
]
