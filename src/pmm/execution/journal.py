"""Order and fill journal, plus the PnL accounting that reads it.

The journal is a JSON-lines file per UTC day inside `POLY_JOURNAL_PATH`. Each
line carries a UTC ISO 8601 `ts`, a `kind` and the payload fields for that
kind. Kinds: `order_intent`, `order_ack`, `order_reject`, `fill`, `cancel`,
`heartbeat`, `pnl_update`, `position`.

Fill records are the input to the PnL math. A fill looks like:

    {"kind": "fill", "ts": "...", "token_id": "...", "condition_id": "0x..",
     "outcome": "Up", "side": "BUY", "price": 0.49, "size": 5}

PnL model. Inventory is tracked per condition, per outcome leg, with average
cost. A leg that is bought and sold back to flat is a round trip.

Merge accounting. When the up leg and the down leg of one condition are held
at the same time, a complete set of one up plus one down is worth exactly
1 pUSD. The position value is therefore
`min(up_shares, down_shares) * 1.0 + unpaired_up * mark_up + unpaired_down * mark_down`,
and the unrealized PnL is that value minus the cost basis still held.
"""

from __future__ import annotations

import json
import os
import threading
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Optional

JOURNAL_KINDS = (
    "order_intent",
    "order_ack",
    "order_reject",
    "fill",
    "cancel",
    "heartbeat",
    "pnl_update",
    "position",
)

_UP = "up"
_DOWN = "down"


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat(timespec="milliseconds")


def _normalize_date(value: Any) -> str:
    if isinstance(value, datetime):
        return value.astimezone(timezone.utc).date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value)


def _leg(outcome: Optional[str]) -> str:
    text = (outcome or "").strip().lower()
    return _UP if text in ("up", "yes", "higher") else _DOWN


class Journal:
    """Append-only JSON-lines journal, one file per UTC day."""

    def __init__(self, path: str | os.PathLike[str]):
        self.path = Path(path).expanduser()
        self._lock = threading.Lock()

    @property
    def directory(self) -> Path:
        return self.path

    def file_for(self, day: Any) -> Path:
        return self.path / f"{_normalize_date(day)}.jsonl"

    def append(self, kind: str, **fields: Any) -> dict:
        """Write one journal line and return the record that was written."""
        record = {"ts": _utc_now(), "kind": kind}
        record.update(fields)
        line = json.dumps(record, separators=(",", ":"), ensure_ascii=False, default=str)
        target = self.file_for(datetime.now(timezone.utc))
        with self._lock:
            target.parent.mkdir(parents=True, exist_ok=True)
            with target.open("a", encoding="utf-8") as handle:
                handle.write(line + "\n")
        return record

    def read_day(self, day: Any) -> list[dict]:
        """Read every record written on one UTC day. A missing day yields []."""
        target = self.file_for(day)
        if not target.is_file():
            return []
        return self._read_file(target)

    def read_all(self) -> list[dict]:
        """Read every record from every day file, oldest day first."""
        if not self.path.is_dir():
            return []
        records: list[dict] = []
        for target in sorted(self.path.glob("*.jsonl")):
            records.extend(self._read_file(target))
        return records

    @staticmethod
    def _read_file(target: Path) -> list[dict]:
        records: list[dict] = []
        with target.open("r", encoding="utf-8") as handle:
            for line in handle:
                line = line.strip()
                if not line:
                    continue
                try:
                    records.append(json.loads(line))
                except ValueError:
                    continue
        return records

    def fills(self, days: Optional[Iterable[Any]] = None) -> list[dict]:
        """Fill records for the given days, or every day when days is None."""
        if days is None:
            records = self.read_all()
        else:
            records = []
            for day in days:
                records.extend(self.read_day(day))
        return [record for record in records if record.get("kind") == "fill"]

    def record_pnl(self, pnl: dict, **fields: Any) -> dict:
        """Record a PnL snapshot."""
        return self.append(
            "pnl_update",
            realized_pnl=pnl.get("realized_pnl", 0.0),
            unrealized_pnl=pnl.get("unrealized_pnl", 0.0),
            total_pnl=pnl.get("total_pnl", 0.0),
            position_value=pnl.get("position_value", 0.0),
            **fields,
        )

    def record_position(self, position: dict, **fields: Any) -> dict:
        """Record a position snapshot."""
        return self.append("position", position=position, **fields)


def _condition_key(fill: dict) -> str:
    return str(fill.get("condition_id") or fill.get("market_id") or fill.get("token_id") or "")


class _LegState:
    """Long and short inventory for one outcome leg of one condition."""

    __slots__ = ("long_qty", "long_cost", "short_qty", "short_cost", "realized", "overlapped")

    def __init__(self) -> None:
        self.long_qty = 0.0
        self.long_cost = 0.0
        self.short_qty = 0.0
        self.short_cost = 0.0
        self.realized = 0.0
        self.overlapped = False

    @property
    def long_avg(self) -> float:
        return self.long_cost / self.long_qty if self.long_qty > 0 else 0.0

    @property
    def short_avg(self) -> float:
        return self.short_cost / self.short_qty if self.short_qty > 0 else 0.0


def _apply_fill(state: _LegState, side: str, price: float, size: float) -> float:
    """Apply one fill to a leg and return the realized PnL it produced."""
    realized = 0.0
    if side in ("BUY", "B"):
        if state.short_qty > 0:
            covered = min(size, state.short_qty)
            realized += (state.short_avg - price) * covered
            state.short_qty -= covered
            state.short_cost -= state.short_avg * covered
            size -= covered
        if size > 0:
            state.long_qty += size
            state.long_cost += size * price
    elif side in ("SELL", "S"):
        if state.long_qty > 0:
            sold = min(size, state.long_qty)
            realized += (price - state.long_avg) * sold
            state.long_qty -= sold
            state.long_cost -= state.long_avg * sold
            size -= sold
        if size > 0:
            state.short_qty += size
            state.short_cost += size * price
    return realized


def _states(fills: list[dict]) -> dict[str, dict[str, _LegState]]:
    grouped: dict[str, dict[str, _LegState]] = {}
    for fill in fills:
        key = _condition_key(fill)
        legs = grouped.setdefault(key, {_UP: _LegState(), _DOWN: _LegState()})
        legs.setdefault(_leg(fill.get("outcome")), _LegState())
    return grouped


def _marks_by_leg(fills: list[dict], marks: dict[str, float]) -> dict[str, dict[str, float]]:
    """Map condition id to leg to mark, using token ids and the 1.0 complement."""
    out: dict[str, dict[str, float]] = {}
    for fill in fills:
        key = _condition_key(fill)
        leg = _leg(fill.get("outcome"))
        token_id = str(fill.get("token_id"))
        legs = out.setdefault(key, {})
        if token_id in marks and leg not in legs:
            legs[leg] = marks[token_id]
    for key, legs in out.items():
        if _UP in legs and _DOWN not in legs:
            legs[_DOWN] = 1.0 - legs[_UP]
        elif _DOWN in legs and _UP not in legs:
            legs[_UP] = 1.0 - legs[_DOWN]
        else:
            legs.setdefault(_UP, 0.0)
            legs.setdefault(_DOWN, 0.0)
    return out


def compute_pnl(fills: list[dict], marks: dict[str, float]) -> dict:
    """Realized and unrealized PnL for a list of fills.

    `marks` maps a token id to its current price. A missing mark falls back to
    the complement of the other leg's mark, since the two legs of a binary
    market sum to 1 pUSD, and then to zero.

    Merge accounting: when both the up leg and the down leg of a condition
    are held, `min(up_shares, down_shares)` complete sets are worth 1 pUSD
    each, so the position value is
    `min(up_shares, down_shares) * 1.0 + unpaired_up * mark_up + unpaired_down * mark_down`.
    """
    marks = {str(k): float(v) for k, v in (marks or {}).items()}
    state = _states(fills)
    leg_marks = _marks_by_leg(fills, marks)

    realized = 0.0
    for fill in fills:
        key = _condition_key(fill)
        leg = _leg(fill.get("outcome"))
        side = str(fill.get("side", "")).strip().upper()
        price = float(fill.get("price", 0.0))
        size = abs(float(fill.get("size", 0.0)))
        current = state[key][leg]
        other = state[key][_DOWN if leg == _UP else _UP]
        realized += _apply_fill(current, side, price, size)
        if current.long_qty > 0 and other.long_qty > 0:
            current.overlapped = True
            other.overlapped = True

    position_value = 0.0
    cost_basis = 0.0
    positions: dict[str, dict[str, Any]] = {}
    for key, legs in state.items():
        up = legs.get(_UP, _LegState())
        down = legs.get(_DOWN, _LegState())
        mark_up = leg_marks.get(key, {}).get(_UP, 0.0)
        mark_down = leg_marks.get(key, {}).get(_DOWN, 0.0)
        paired = min(up.long_qty, down.long_qty)
        unpaired_up = up.long_qty - paired
        unpaired_down = down.long_qty - paired
        value = paired * 1.0 + unpaired_up * mark_up + unpaired_down * mark_down
        basis = up.long_cost + down.long_cost
        position_value += value
        cost_basis += basis
        positions[key] = {
            "up_shares": up.long_qty,
            "down_shares": down.long_qty,
            "paired_shares": paired,
            "mark_up": mark_up,
            "mark_down": mark_down,
            "position_value": value,
            "cost_basis": basis,
            "up_short": up.short_qty,
            "down_short": down.short_qty,
        }

    short_pnl = 0.0
    for key, legs in state.items():
        mark_up = leg_marks.get(key, {}).get(_UP, 0.0)
        mark_down = leg_marks.get(key, {}).get(_DOWN, 0.0)
        for leg, leg_state in legs.items():
            if leg_state.short_qty <= 0:
                continue
            mark = mark_up if leg == _UP else mark_down
            short_pnl += leg_state.short_qty * (leg_state.short_avg - mark)

    unrealized = position_value - cost_basis + short_pnl
    return {
        "realized_pnl": realized,
        "unrealized_pnl": unrealized,
        "total_pnl": realized + unrealized,
        "position_value": position_value,
        "cost_basis": cost_basis,
        "positions": positions,
        "fill_count": len(fills),
    }


def win_rate(fills: list[dict]) -> float:
    """Fraction of closed round trips that ended positive.

    A round trip is one leg that went from flat to holding and back to flat.
    When both legs of a condition were held at the same time they form a
    merged pair, and that pair counts as one round trip with the PnL of both
    legs, not two.
    """
    state = _states(fills)
    episodes: dict[str, dict[str, Optional[dict]]] = {}
    closures: list[tuple[str, str, float, bool]] = []

    for fill in fills:
        key = _condition_key(fill)
        leg = _leg(fill.get("outcome"))
        side = str(fill.get("side", "")).strip().upper()
        price = float(fill.get("price", 0.0))
        size = abs(float(fill.get("size", 0.0)))
        current = state[key][leg]
        other = state[key][_DOWN if leg == _UP else _UP]
        legs_state = episodes.setdefault(key, {_UP: None, _DOWN: None})

        was_long = current.long_qty > 0
        pnl = _apply_fill(current, side, price, size)
        if was_long and current.long_qty <= 0:
            episode = legs_state[leg]
            if episode is not None:
                episode["pnl"] += pnl
                closures.append((key, leg, episode["pnl"], episode["overlapped"]))
                legs_state[leg] = None
        elif not was_long and current.long_qty > 0:
            legs_state[leg] = {"pnl": 0.0, "overlapped": False}
        else:
            episode = legs_state[leg]
            if episode is not None:
                episode["pnl"] += pnl

        if current.long_qty > 0 and other.long_qty > 0:
            for active in legs_state.values():
                if active is not None:
                    active["overlapped"] = True

    wins = 0
    total = 0
    pending: dict[str, list[tuple[str, float, bool]]] = {}
    for key, leg, pnl, overlapped in closures:
        bucket = pending.setdefault(key, [])
        if overlapped:
            partner = next(
                (
                    index
                    for index, entry in enumerate(bucket)
                    if entry[2] and entry[0] != leg
                ),
                None,
            )
            if partner is not None:
                other_leg, other_pnl, _ = bucket.pop(partner)
                combined = pnl + other_pnl
                total += 1
                wins += 1 if combined > 0 else 0
                continue
        bucket.append((leg, pnl, overlapped))
    for bucket in pending.values():
        for _, pnl, _ in bucket:
            total += 1
            wins += 1 if pnl > 0 else 0
    if total == 0:
        return 0.0
    return wins / total


def pnl_from_journal(journal: Journal, marks: dict[str, float], day: Any = None) -> dict:
    """Compute PnL from the fills recorded in the journal."""
    fills = journal.fills([day]) if day is not None else journal.fills()
    return compute_pnl(fills, marks)
