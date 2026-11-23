"""Polymarket binary market maker.

The package is layered so every layer can be exercised on its own.

* :mod:`pmm.data` reads the venue (CLOB and Gamma) and scores the reward
  pools. Every endpoint is public, so this layer never needs credentials.
* :mod:`pmm.pricing` is pure: it turns a fair probability into a two-sided
  quote and holds the paired-bid arithmetic that is the maker's profit source.
* :mod:`pmm.core` holds the domain models: the market snapshot, the paired
  inventory and the cycle selector.
* :mod:`pmm.engine` runs the service: the quote cycle, the service loop and
  the hourly self-adjustment.
* :mod:`pmm.execution` talks to the CLOB, journals what happened and reads
  positions.
* :mod:`pmm.risk` holds the gate stack, one trigger per rule.
* :mod:`pmm.monitor` computes the hourly metrics and applies at most one
  parameter change per tick.

Standard library only, plus the venue's own client in the execution layer.
"""

from __future__ import annotations

__version__ = "0.1.0"

__all__ = ["__version__"]
