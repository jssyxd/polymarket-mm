"""Redeem resolved positions, so a settled win becomes pUSD without a human.

Nothing in the venue credits a resolved position automatically: a winning
token pays 1 pUSD per share only when `redeemPositions` is called. The 18
positions from September that sat unredeemed are the proof.

The call is a relayer operation (owner signature + Relayer API key), one per
market, and it burns both legs: the winning one pays, the losing one pays
nothing. Only markets with a winning leg are planned, because burning a
loser alone returns zero and costs a transaction.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = [
    "RedeemTarget",
    "REDEEM_MIN_SIZE",
    "REDEEM_MIN_PRICE",
    "plan_redeems",
    "run_redeem",
]

#: The venue's minimum order size; a smaller position is not worth a call.
REDEEM_MIN_SIZE = 5.0

#: A leg at or above this price is the winning side of a resolved market.
REDEEM_MIN_PRICE = 0.5


@dataclass(frozen=True)
class RedeemTarget:
    """One resolved market with a winning leg to redeem."""

    condition_id: str
    title: str
    size: float
    outcome: str
    payout: float


def _f(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def plan_redeems(
    positions: Iterable[Mapping[str, Any]],
    *,
    min_size: float = REDEEM_MIN_SIZE,
    min_price: float = REDEEM_MIN_PRICE,
) -> list[RedeemTarget]:
    """Resolved markets whose winning leg is worth redeeming.

    A position is eligible when the venue marks it `redeemable`, its share
    count clears the venue minimum, and its mark says it is the winning side.
    Losers are left alone: redeeming them pays zero.
    """
    best: dict[str, RedeemTarget] = {}
    for row in positions:
        if not isinstance(row, Mapping):
            continue
        if not row.get("redeemable"):
            continue
        condition_id = str(row.get("condition_id") or "")
        size = _f(row.get("current_size"))
        price = _f(row.get("current_price"))
        if not condition_id or size < min_size or price < min_price:
            continue
        target = RedeemTarget(
            condition_id=condition_id,
            title=str(row.get("title") or ""),
            size=size,
            outcome=str(row.get("outcome") or ""),
            payout=round(size * 1.0, 6),
        )
        current = best.get(condition_id)
        if current is None or target.size > current.size:
            best[condition_id] = target
    return list(best.values())


def _secure_client(config: Any) -> Any:
    from polymarket import RelayerApiKey, SecureClient

    return SecureClient.create(
        private_key=config.owner_pk,
        wallet=config.funder,
        api_key=RelayerApiKey(key=config.relayer_api_key, address=config.relayer_address),
    )


def run_redeem(
    config: Any,
    *,
    client: Any = None,
    positions: Optional[Sequence[Mapping[str, Any]]] = None,
    journal: Any = None,
    min_size: float = REDEEM_MIN_SIZE,
    min_price: float = REDEEM_MIN_PRICE,
) -> list[dict[str, Any]]:
    """Redeem every eligible market, returning one record per market."""
    from .positions import read_positions

    if positions is None:
        positions = read_positions(config).get("api_positions") or []
    targets = plan_redeems(positions, min_size=min_size, min_price=min_price)

    if config.dry_run or not config.owner_pk:
        return [
            {
                "condition_id": t.condition_id,
                "size": t.size,
                "payout": t.payout,
                "status": "dry_run",
            }
            for t in targets
        ]

    active = client if client is not None else _secure_client(config)
    results: list[dict[str, Any]] = []
    for target in targets:
        status = "redeemed"
        try:
            handle = active.redeem_positions(
                condition_id=target.condition_id,
                metadata=f"redeem {target.title[:40]}",
            )
            handle.wait()
        except Exception as exc:  # noqa: BLE001 - one market must not stop the rest
            status = f"failed: {type(exc).__name__}: {exc}"[:200]
        if status == "redeemed" and journal is not None:
            journal.append(
                "redeem",
                condition_id=target.condition_id,
                side="REDEEM",
                size=target.size,
                price=1.0,
                notional=target.payout,
                outcome=target.outcome,
                reason="resolved_win",
            )
        results.append(
            {
                "condition_id": target.condition_id,
                "size": target.size,
                "payout": target.payout,
                "status": status,
            }
        )
    return results
