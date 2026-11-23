"""Pricing engine for binary YES/NO markets on a Polymarket-style CLOB.

Three modules, each pure:

* :mod:`pmm.pricing.probability` turns an external spot signal into a fair
  probability and its probability-space volatility.
* :mod:`pmm.pricing.quotes` builds a two-sided quote on the UP and DOWN
  tokens, with the pair invariant ``bid_up + bid_down <= 1 - tick_size`` and an
  inventory skew that leans the quote toward flattening.
* :mod:`pmm.pricing.pairing` holds the paired-bid arithmetic, which is the
  actual profit source: buy the pair below 1, merge it, and the profit does
  not depend on the direction of the event.

Everything is standard library only.
"""

from __future__ import annotations

from .pairing import (
    expected_net_bps,
    merge_arbitrage_threshold,
    paired_fill_pnl,
    unpaired_fill_exposure,
)
from .probability import (
    FairProbability,
    black_scholes_digital_prob,
    implied_prob_from_book,
    probability_space_vol,
)
from .quotes import (
    Inventory,
    Quote,
    QuoteSide,
    build_quotes,
    round_down_to_tick,
    round_up_to_tick,
)

__all__ = [
    "FairProbability",
    "Inventory",
    "Quote",
    "QuoteSide",
    "black_scholes_digital_prob",
    "build_quotes",
    "expected_net_bps",
    "implied_prob_from_book",
    "merge_arbitrage_threshold",
    "paired_fill_pnl",
    "probability_space_vol",
    "round_down_to_tick",
    "round_up_to_tick",
    "unpaired_fill_exposure",
]
