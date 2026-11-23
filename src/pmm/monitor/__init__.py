"""Hourly monitoring for the Polymarket binary maker.

Three pieces, all independent of the execution and pricing layers:

* :mod:`pmm.monitor.metrics` computes capture, win rate, exposure and the
  reward estimate from plain fill dicts.
* :mod:`pmm.monitor.agent` turns those metrics into at most one parameter
  change per hourly tick.
* :mod:`pmm.monitor.report` writes the hourly report and reads the last
  24 hours back.
"""

from __future__ import annotations

from .agent import MonitorAgent
from .metrics import (
    fill_net_bps,
    fill_notional,
    fill_pnl,
    fill_timestamp,
    inventory_exposure,
    pair_coverage,
    realized_bps,
    reward_estimate,
    rolling_net_bps,
    win_rate,
)
from .report import read_reports, write_report

__all__ = [
    "MonitorAgent",
    "fill_net_bps",
    "fill_notional",
    "fill_pnl",
    "fill_timestamp",
    "inventory_exposure",
    "pair_coverage",
    "read_reports",
    "realized_bps",
    "reward_estimate",
    "rolling_net_bps",
    "win_rate",
    "write_report",
]
