"""Paired inventory: what the maker holds on the two legs of one market.

The maker's inventory is not a signed position. It is two independent
quantities, the UP shares and the DOWN shares, because the profit comes from
holding both legs at once: a complete set redeems for 1 pUSD. A signed model
cannot express that, and it is the reason the whole package tracks the two
legs separately.

The three numbers that matter for a risk decision:

``box``
    Complete sets, ``min(up, down)``. These are mergeable and carry no
    directional risk.
``notional_at_risk``
    The stake lost if the market resolves against the position. A perfectly
    paired position has none, because whichever way the market resolves, one
    leg of every complete set pays 1 pUSD.
``mergeable_coverage``
    The share of held shares that sits in a complete set.

The model converts to and from :class:`pmm.pricing.quotes.Inventory`, which is
what the quote builder takes.
"""

from __future__ import annotations

from dataclasses import dataclass

from ..pricing.quotes import Inventory as QuoteInventory

__all__ = ["PairedInventory"]


@dataclass
class PairedInventory:
    """Maker inventory on one market.

    Attributes:
        up_shares: Shares held of the UP token.
        down_shares: Shares held of the DOWN token.
        max_inventory_per_side: Inventory box per leg, in shares.
        mark_up: Current price of the UP token.
        mark_down: Current price of the DOWN token.
    """

    up_shares: float = 0.0
    down_shares: float = 0.0
    max_inventory_per_side: float = 0.0
    mark_up: float = 0.0
    mark_down: float = 0.0

    @property
    def unpaired_up(self) -> float:
        """UP shares with no offsetting DOWN share."""
        return max(self.up_shares - self.down_shares, 0.0)

    @property
    def unpaired_down(self) -> float:
        """DOWN shares with no offsetting UP share."""
        return max(self.down_shares - self.up_shares, 0.0)

    @property
    def box(self) -> float:
        """Complete, mergeable sets. Each one redeems for 1 pUSD."""
        return min(self.up_shares, self.down_shares)

    @property
    def notional_at_risk(self) -> float:
        """pUSD lost if the market resolves against the position.

        Resolution one way kills the other leg, so the exposure is the larger
        of the two unpaired leg values. A perfectly paired position holds no
        unpaired shares and risks nothing.
        """
        return max(self.unpaired_up * self.mark_up, self.unpaired_down * self.mark_down)

    @property
    def mergeable_coverage(self) -> float:
        """Fraction of the held shares that sits in a complete set."""
        total = self.up_shares + self.down_shares
        if total <= 0.0:
            return 0.0
        return 2.0 * self.box / total

    @property
    def net_shares(self) -> float:
        """Signed position, positive when long the UP leg."""
        return self.up_shares - self.down_shares

    def to_quote_inventory(self) -> QuoteInventory:
        """The inventory the quote builder takes."""
        return QuoteInventory(
            up_shares=self.up_shares,
            down_shares=self.down_shares,
            max_inventory_per_side=self.max_inventory_per_side,
        )

    @classmethod
    def from_quote_inventory(
        cls,
        inventory: QuoteInventory,
        mark_up: float = 0.0,
        mark_down: float = 0.0,
    ) -> "PairedInventory":
        """Build a paired inventory from the quote builder's inventory."""
        return cls(
            up_shares=inventory.up_shares,
            down_shares=inventory.down_shares,
            max_inventory_per_side=inventory.max_inventory_per_side,
            mark_up=mark_up,
            mark_down=mark_down,
        )

    @classmethod
    def from_position_row(
        cls,
        row: dict,
        max_inventory_per_side: float = 0.0,
        mark_up: float = 0.0,
        mark_down: float = 0.0,
    ) -> "PairedInventory":
        """Build from one entry of the PnL accounting's position map."""
        return cls(
            up_shares=float(row.get("up_shares", 0.0) or 0.0),
            down_shares=float(row.get("down_shares", 0.0) or 0.0),
            max_inventory_per_side=max_inventory_per_side,
            mark_up=mark_up,
            mark_down=mark_down,
        )
