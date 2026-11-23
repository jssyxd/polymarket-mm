"""Merge complete outcome pairs back into pUSD.

A paired-bid maker ends up holding both tokens of a market. Once both legs are
held, each complete set is worth exactly 1 pUSD and can be merged on-chain —
that merge is how the strategy recycles capital. Without it the cash drains
into inventory and the quoting loop stalls with nothing to post.

The merge is a relayer operation: it needs the owner key to sign and a Relayer
API key to submit. It is kept out of the quoting loop on purpose, so a relayer
outage cannot take the book down.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Iterable, Mapping, Optional, Sequence

__all__ = [
    "MergeTarget",
    "MERGE_MIN_SIZE",
    "balanced_pairs",
    "merge_pairs",
]

#: Below the venue's minimum order size a merge costs more attention than it
#: returns, so a pair smaller than this is left alone.
MERGE_MIN_SIZE = 5.0


@dataclass(frozen=True)
class MergeTarget:
    """One market with both outcomes held, and the mergeable size."""

    condition_id: str
    title: str
    size: float


def balanced_pairs(
    positions: Iterable[Mapping[str, Any]], min_size: float = MERGE_MIN_SIZE
) -> list[MergeTarget]:
    """Markets where both outcome tokens are held, with the mergeable size.

    `positions` are Data API v2 rows (`condition_id`, `outcome_index`,
    `current_size`, `title`). The mergeable amount is the smaller of the two
    legs; whatever is left stays as inventory.
    """
    legs: dict[str, dict[int, float]] = {}
    titles: dict[str, str] = {}
    for row in positions:
        if not isinstance(row, Mapping):
            continue
        condition_id = str(row.get("condition_id") or "")
        if not condition_id:
            continue
        try:
            index = int(row.get("outcome_index"))
        except (TypeError, ValueError):
            continue
        try:
            size = float(row.get("current_size") or 0.0)
        except (TypeError, ValueError):
            continue
        legs.setdefault(condition_id, {})[index] = size
        titles.setdefault(condition_id, str(row.get("title") or ""))

    targets: list[MergeTarget] = []
    for condition_id, pair in legs.items():
        if 0 not in pair or 1 not in pair:
            continue
        size = min(pair[0], pair[1])
        if size >= min_size:
            targets.append(MergeTarget(condition_id, titles.get(condition_id, ""), size))
    return targets


def _secure_client(config: Any) -> Any:
    """The unified SDK client, created lazily so the import stays optional."""
    from polymarket import RelayerApiKey, SecureClient

    return SecureClient.create(
        private_key=config.owner_pk,
        wallet=config.funder,
        api_key=RelayerApiKey(key=config.relayer_api_key, address=config.relayer_address),
    )


def merge_pairs(
    config: Any,
    *,
    positions: Optional[Sequence[Mapping[str, Any]]] = None,
    client: Any = None,
    journal: Any = None,
    min_size: float = MERGE_MIN_SIZE,
) -> list[dict[str, Any]]:
    """Merge every market that holds both legs and return what was merged.

    Returns one record per market with `condition_id`, `size` and `status`.
    Nothing is merged in dry-run mode: the targets are reported with
    `status: "dry_run"` so a caller can see what would have happened.
    """
    if positions is None:
        from .positions import read_positions

        positions = read_positions(config).get("api_positions") or []

    targets = balanced_pairs(positions, min_size=min_size)
    results: list[dict[str, Any]] = []
    if config.dry_run or not config.owner_pk:
        for target in targets:
            results.append(
                {"condition_id": target.condition_id, "size": target.size, "status": "dry_run"}
            )
        return results

    active = client if client is not None else _secure_client(config)
    for target in targets:
        try:
            handle = active.merge_positions(
                condition_id=target.condition_id,
                amount="max",
                metadata=f"merge {target.title[:40]}",
            )
            handle.wait()
            status = "merged"
            if journal is not None:
                journal.append(
                    "merge",
                    condition_id=target.condition_id,
                    side="MERGE",
                    size=target.size,
                    price=1.0,
                    notional=target.size,
                    reason="complete_set",
                )
        except Exception as exc:  # noqa: BLE001 - one failure must not stop the rest
            status = f"failed: {type(exc).__name__}: {exc}"[:200]
        results.append(
            {"condition_id": target.condition_id, "size": target.size, "status": status}
        )
    return results
