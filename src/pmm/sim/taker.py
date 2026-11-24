"""Taker-route simulator: does crossing the spread and holding pay?

The maker premise was falsified (decision 0014). The alternative worth
measuring is the opposite: take liquidity at the ask when a fair value says
the ask is too cheap, then hold to settlement. Fees are known to be zero on
these markets for the fills we observed, so the only costs are the spread and
being wrong.

The fair value comes from the CLOB book? No — that would be circular. It comes
from an external oracle: the OKX spot mid and the window's strike, priced as a
binary option. That is the whole thesis of the taker route: the Polymarket
book lags the underlying.
"""

from __future__ import annotations

import math
from dataclasses import dataclass
from typing import Iterable, Mapping, Sequence

__all__ = ["Quote", "fair_probability", "taker_edge", "simulate", "Result"]


@dataclass(frozen=True)
class Quote:
    """One book snapshot for one outcome token."""

    ts: float
    token_id: str
    bid: float
    ask: float

    @property
    def mid(self) -> float:
        return (self.bid + self.ask) / 2.0


def _norm_cdf(x: float) -> float:
    return 0.5 * (1.0 + math.erf(x / math.sqrt(2.0)))


def fair_probability(
    spot: float, strike: float, tau_seconds: float, annual_vol: float
) -> float:
    """P(close above strike) for a zero-drift geometric walk."""
    if spot <= 0 or strike <= 0 or tau_seconds <= 0 or annual_vol <= 0:
        return 0.5
    years = tau_seconds / 31_536_000.0
    sd = annual_vol * math.sqrt(years)
    if sd <= 0:
        return 1.0 if spot > strike else 0.0
    return _norm_cdf(math.log(spot / strike) / sd)


def taker_edge(fair: float, quote: Quote) -> float:
    """Edge per share of taking the offered side, fee-free."""
    return fair - quote.ask


@dataclass
class Result:
    trades: int = 0
    wins: int = 0
    pnl: float = 0.0
    shares: float = 0.0
    edge_sum: float = 0.0

    @property
    def hit_rate(self) -> float:
        return self.wins / self.trades if self.trades else 0.0

    @property
    def pnl_per_share(self) -> float:
        return self.pnl / self.shares if self.shares else 0.0

    @property
    def mean_edge(self) -> float:
        return self.edge_sum / self.trades if self.trades else 0.0

    def summary(self) -> dict:
        return {
            "trades": self.trades,
            "wins": self.wins,
            "hit_rate": round(self.hit_rate, 4),
            "shares": round(self.shares, 2),
            "pnl": round(self.pnl, 4),
            "pnl_per_share": round(self.pnl_per_share, 6),
            "mean_edge_quoted": round(self.mean_edge, 6),
        }


def simulate(
    observations: Iterable[Mapping],
    *,
    min_edge: float = 0.02,
    size: float = 20.0,
    max_price: float = 0.98,
) -> Result:
    """Play every observation: take the offered side when the edge clears.

    An observation is `{fair, quote, won}`: `won` is the settlement result for
    the token being bought. Holding to settlement means the payoff is 1 or 0
    per share, so the realised PnL per share is `won - ask`.
    """
    result = Result()
    for item in observations:
        quote = item["quote"]
        fair = float(item["fair"])
        ask = quote.ask
        if ask <= 0 or ask > max_price:
            continue
        edge = fair - ask
        if edge < min_edge:
            continue
        won = 1.0 if item["won"] else 0.0
        result.trades += 1
        result.shares += size
        result.edge_sum += edge
        result.pnl += (won - ask) * size
        if won:
            result.wins += 1
    return result
