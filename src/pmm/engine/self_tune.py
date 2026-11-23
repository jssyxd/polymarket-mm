"""Hourly self-adjustment: read the journal, let the monitor agent decide, write
the parameters back.

The step is deliberately small. It reads the fills the runner journaled, builds
the market state from them, runs :class:`pmm.monitor.agent.MonitorAgent` once
and applies at most the one change the agent made. The parameters go back to
disk atomically, so a reader never sees a half-written file, and the next
quote cycle picks the new values up.

An empty journal is not an error. No fills means no evidence, and the agent
is asked to decide on an empty history rather than being skipped.
"""

from __future__ import annotations

import json
import os
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Mapping

from ..execution.journal import Journal
from ..monitor.agent import MonitorAgent
from ..monitor.metrics import fill_net_bps
from ..monitor.report import write_report
from ..risk.gates import MarketState

__all__ = [
    "DEFAULT_PARAMS",
    "build_state",
    "load_params",
    "net_capture_series",
    "run_self_tune",
    "write_params",
]

#: The parameter vocabulary. Every key the engine and the agent read.
DEFAULT_PARAMS: dict[str, Any] = {
    "quoting_enabled": True,
    "half_spread_cents": 1.0,
    "max_spread_cents": 4.5,
    "inventory_box": 100.0,
    "size_shares": 20.0,
    "sigma_p": 0.0,
}


def load_params(path: str | os.PathLike[str]) -> dict[str, Any]:
    """Read the parameter file, falling back to the defaults.

    A missing file, an unreadable file or a file with broken JSON yields the
    defaults. A parameter file that is momentarily half-written must not take
    the service down.
    """
    params = dict(DEFAULT_PARAMS)
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        return params
    try:
        raw = json.loads(file_path.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return params
    if isinstance(raw, dict):
        params.update(raw)
    return params


def write_params(path: str | os.PathLike[str], params: Mapping[str, Any]) -> str:
    """Write the parameter file atomically and return the path.

    The temporary file is written in the same directory, so the rename is
    atomic and never crosses a filesystem boundary.
    """
    file_path = Path(path).expanduser()
    file_path.parent.mkdir(parents=True, exist_ok=True)
    merged = dict(DEFAULT_PARAMS)
    merged.update(dict(params or {}))

    temp_path = file_path.with_name(f".{file_path.name}.tmp")
    body = json.dumps(merged, indent=2, sort_keys=True) + "\n"
    with temp_path.open("w", encoding="utf-8") as handle:
        handle.write(body)
        handle.flush()
        os.fsync(handle.fileno())
    os.replace(temp_path, file_path)
    return str(file_path)


def net_capture_series(fills: list[dict]) -> list[float]:
    """Net capture per fill, for the fills that carry a realized PnL.

    A fill without a PnL field carries no evidence of capture, so it is left
    out rather than counted as zero. Counting it as zero would read as
    "losing money" and stop the maker on a book that simply has not traded.
    """
    values: list[float] = []
    for fill in fills:
        if "pnl" not in fill and "pnl_usd" not in fill and "realized_pnl" not in fill:
            continue
        values.append(fill_net_bps(fill))
    return values


def build_state(
    journal: Journal,
    params: Mapping[str, Any] | None = None,
    *,
    now: float | None = None,
) -> MarketState:
    """Build the market state the monitor agent reads.

    The state comes from the journal: the positions the fills imply, the net
    capture per fill, and the equity the parameters carry.
    """
    settings = dict(params or {})
    fills = journal.fills()
    positions = _positions(journal, fills)

    up_shares = 0.0
    down_shares = 0.0
    for row in positions.values():
        up_shares += float(row.get("up_shares", 0.0) or 0.0)
        down_shares += float(row.get("down_shares", 0.0) or 0.0)

    stamp = time.time() if now is None else float(now)
    return MarketState(
        up_shares=up_shares,
        down_shares=down_shares,
        max_inventory_per_side=float(settings.get("inventory_box", 0.0) or 0.0),
        now=stamp,
        tau_seconds=600.0,
        fair_prob=0.5,
        mid=0.5,
        tick_size=0.01,
        recent_net_bps=net_capture_series(fills),
        equity_usd=float(settings.get("equity_usd", 0.0) or 0.0),
        drawdown_pct=0.0,
        heartbeat_ok=True,
        oracle_age_seconds=0.0,
        min_order_size=float(settings.get("size_shares", 0.0) or 0.0),
    )


def _positions(journal: Journal, fills: list[dict]) -> dict[str, dict]:
    """Positions per condition, from the journal's own PnL accounting."""
    from ..execution.journal import compute_pnl

    if not fills:
        return {}
    result = compute_pnl(fills, {})
    positions = result.get("positions")
    return positions if isinstance(positions, dict) else {}


def _last_fill(fills: list[dict]) -> tuple[str | None, float | None]:
    """The side and timestamp of the most recent fill."""
    if not fills:
        return (None, None)
    fill = fills[-1]
    outcome = str(fill.get("outcome", "")).strip().lower()
    side = "up" if outcome in ("up", "yes", "higher") else "down"
    stamp = fill.get("ts")
    parsed: float | None = None
    if isinstance(stamp, (int, float)) and not isinstance(stamp, bool):
        parsed = float(stamp)
    elif isinstance(stamp, str):
        try:
            parsed = datetime.fromisoformat(stamp.replace("Z", "+00:00")).timestamp()
        except ValueError:
            parsed = None
    return (side, parsed)


def run_self_tune(
    journal: Journal,
    params: Mapping[str, Any],
    params_path: str | os.PathLike[str],
    reports_dir: str | os.PathLike[str],
    *,
    state: MarketState | None = None,
    now: float | None = None,
) -> dict[str, Any]:
    """Run one tuning tick and write the results to disk.

    Returns the decision record, the new parameters and the paths written.
    """
    settings = dict(params or {})
    settings.setdefault("quoting_enabled", True)
    fills = journal.fills()
    market_state = state if state is not None else build_state(journal, settings, now=now)

    agent = MonitorAgent()
    decision = agent.run_once(market_state, fills, settings)

    updated = dict(settings)
    applied = bool(decision.get("changed"))
    if applied and not fills:
        # The agent widens the spread when the book did not fill. On an empty
        # journal that is not evidence, it is the absence of any, so the
        # parameters are left where the operator put them.
        applied = False
        decision = dict(
            decision,
            applied=False,
            reason=f"{decision.get('reason', '')}_no_fills_no_evidence",
        )
    elif applied:
        param = decision.get("param")
        if param in updated:
            updated[param] = decision.get("to_value")
        else:
            applied = False
    else:
        decision = dict(decision, applied=False)

    written_params = write_params(params_path, updated)

    stamp = datetime.now(timezone.utc)
    report_name = stamp.strftime("%Y%m%dT%H%M%SZ") + ".md"
    report_path = write_report(
        os.path.join(str(reports_dir), report_name),
        {
            "timestamp": stamp.isoformat(),
            "metrics": decision.get("metrics", {}),
            "decision": decision,
            "state": {
                "up_shares": market_state.up_shares,
                "down_shares": market_state.down_shares,
                "max_inventory_per_side": market_state.max_inventory_per_side,
                "fill_count": len(fills),
                "recent_net_bps": list(market_state.recent_net_bps),
                "equity_usd": market_state.equity_usd,
            },
        },
    )

    return {
        "changed": bool(decision.get("changed")),
        "applied": applied,
        "decision": decision,
        "params": updated,
        "params_path": written_params,
        "report_path": report_path,
        "fill_count": len(fills),
        "last_fill": _last_fill(fills),
    }
