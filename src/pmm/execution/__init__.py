"""Execution adapter for the Polymarket CLOB.

`config` holds the environment-derived settings, `clob` places and cancels
orders, `journal` records what happened and computes PnL, `positions` reads
balances.
"""

from .config import ExecutionConfig
from .journal import Journal, compute_pnl, win_rate
from .positions import read_onchain_pUSD, read_positions

__all__ = [
    "ExecutionConfig",
    "Journal",
    "compute_pnl",
    "read_onchain_pUSD",
    "read_positions",
    "win_rate",
]
