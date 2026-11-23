"""Remember the fee the venue actually charged, per market.

`fee_rate_bps` from the market metadata is a configured ceiling, not what a
trade cost: two live sells in a market configured at 1000 bps were charged 0,
and the cash matched the gross proceeds to the cent. The harvest profit guard
should therefore prefer the observed fee and fall back to the configuration
only when nothing has been measured yet.
"""

from __future__ import annotations

import json
import os
from pathlib import Path
from typing import Any, Mapping, Optional

__all__ = ["load_fees", "record_fees", "observed_fee_bps"]

FILE_NAME = "fees.json"


def _path(journal_path: Any) -> Path:
    return Path(str(journal_path)).expanduser() / FILE_NAME


def load_fees(journal_path: Any) -> dict[str, float]:
    """Observed fee in bps per condition id. A missing file is an empty map."""
    path = _path(journal_path)
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return {}
    if not isinstance(payload, dict):
        return {}
    out: dict[str, float] = {}
    for key, value in payload.items():
        try:
            out[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    return out


def record_fees(journal_path: Any, observations: Mapping[str, float]) -> dict[str, float]:
    """Merge observations into the store and write it atomically."""
    current = load_fees(journal_path)
    for key, value in observations.items():
        if value is None:
            continue
        try:
            current[str(key)] = float(value)
        except (TypeError, ValueError):
            continue
    path = _path(journal_path)
    path.parent.mkdir(parents=True, exist_ok=True)
    tmp = path.with_suffix(".tmp")
    tmp.write_text(json.dumps(current, indent=1, sort_keys=True), encoding="utf-8")
    os.replace(tmp, path)
    return current


def observed_fee_bps(journal_path: Any, condition_id: str) -> Optional[float]:
    """The measured fee for one market, or None when nothing was observed."""
    return load_fees(journal_path).get(str(condition_id))
