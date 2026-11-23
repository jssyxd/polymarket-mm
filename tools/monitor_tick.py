#!/usr/bin/env python3
"""One hourly monitor tick.

Reads the newest execution journal, recomputes the metrics, runs the
monitor agent once, prints the decision and appends a report.

The tool needs no credentials and no network. A missing journal is reported
as "no data" instead of raising, because the hourly tick has to survive the
worker being down.

Usage::

    python tools/monitor_tick.py --journal ~/.pmm/journal --reports-dir reports
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from datetime import datetime, timezone

sys.path.insert(0, os.path.join(os.path.dirname(os.path.abspath(__file__)), "..", "src"))

from pmm.monitor.agent import MonitorAgent  # noqa: E402
from pmm.monitor.metrics import fill_net_bps  # noqa: E402
from pmm.monitor.report import write_report  # noqa: E402
from pmm.risk.gates import MarketState  # noqa: E402

REPO_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
DEFAULT_JOURNAL = os.path.expanduser(
    os.environ.get("POLY_JOURNAL_PATH", "~/.pmm/journal")
)
DEFAULT_JOURNAL_DIR = os.path.join(REPO_ROOT, "journals")
DEFAULT_REPORTS_DIR = os.path.join(REPO_ROOT, "reports")

DEFAULT_PARAMS = {
    "quoting_enabled": True,
    "half_spread_cents": 1.0,
    "max_spread_cents": 4.5,
}

_STATE_KEYS = (
    "up_shares",
    "down_shares",
    "max_inventory_per_side",
    "last_fill_side",
    "last_fill_ts",
    "now",
    "tau_seconds",
    "fair_prob",
    "mid",
    "tick_size",
    "equity_usd",
    "drawdown_pct",
    "heartbeat_ok",
    "oracle_age_seconds",
    "min_order_size",
)


def newest_journal(directory: str) -> str | None:
    """Path of the most recently modified file in the journal directory."""
    if not os.path.isdir(directory):
        return None
    candidates = [
        os.path.join(directory, name)
        for name in os.listdir(directory)
        if os.path.isfile(os.path.join(directory, name))
        and not name.startswith(".")
    ]
    if not candidates:
        return None
    return max(candidates, key=os.path.getmtime)


def resolve_journal(path_or_dir: str) -> str | None:
    """The journal to read: a file, or the newest file in a directory."""
    if os.path.isfile(path_or_dir):
        return path_or_dir
    if os.path.isdir(path_or_dir):
        return newest_journal(path_or_dir)
    return None


def read_journal(path: str) -> tuple[list[dict], dict]:
    """Read a JSONL journal into (fills, state_record).

    A line is a fill when it carries a notional or a pnl, and a state
    record when it carries position or account fields. Malformed lines are
    skipped rather than fatal.
    """
    records: list[dict] = []
    with open(path, encoding="utf-8") as handle:
        text = handle.read()
    try:
        whole = json.loads(text)
    except json.JSONDecodeError:
        whole = None
    if isinstance(whole, list):
        records = [item for item in whole if isinstance(item, dict)]
    else:
        for line in text.splitlines():
            line = line.strip()
            if not line:
                continue
            try:
                record = json.loads(line)
            except json.JSONDecodeError:
                continue
            if isinstance(record, dict):
                records.append(record)
    fills: list[dict] = []
    state: dict = {}
    for record in records:
        if record.get("type") == "state" or any(
            key in record for key in ("up_shares", "down_shares", "equity_usd")
        ):
            state.update({key: record[key] for key in _STATE_KEYS if key in record})
            continue
        if any(
            key in record for key in ("notional", "notional_usd", "pnl", "pnl_usd")
        ):
            fills.append(record)
    return fills, state


def build_state(state_record: dict, fills: list[dict]) -> MarketState:
    """Assemble a MarketState from the journal."""
    values: dict = {}
    for key in _STATE_KEYS:
        if key in state_record:
            values[key] = state_record[key]
    values.setdefault("now", datetime.now(timezone.utc).timestamp())
    values.setdefault("heartbeat_ok", True)
    values.setdefault("fair_prob", 0.5)
    values.setdefault("mid", 0.5)
    values.setdefault("tick_size", 0.01)
    if "recent_net_bps" not in values:
        values["recent_net_bps"] = [fill_net_bps(f) for f in fills[-100:]]
    return MarketState(**values)


def load_params(path: str | None, state: MarketState) -> dict:
    params = dict(DEFAULT_PARAMS)
    params["inventory_box"] = state.max_inventory_per_side
    if path and os.path.isfile(path):
        with open(path, encoding="utf-8") as handle:
            params.update(json.load(handle))
    return params


def report_path(reports_dir: str, timestamp: datetime) -> str:
    """A report path that does not overwrite an earlier tick."""
    base = f"monitor-{timestamp.strftime('%Y%m%d-%H%M%S')}"
    path = os.path.join(reports_dir, f"{base}.md")
    counter = 2
    while os.path.exists(path):
        path = os.path.join(reports_dir, f"{base}-{counter}.md")
        counter += 1
    return path


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--journal",
        default=None,
        help="journal file or directory (default: $POLY_JOURNAL_PATH, then ./journals)",
    )
    parser.add_argument("--reports-dir", default=DEFAULT_REPORTS_DIR)
    parser.add_argument("--params", default=None, help="JSON file of current params")
    parser.add_argument("--json", action="store_true", help="print the decision as JSON")
    args = parser.parse_args(argv)

    agent = MonitorAgent()
    timestamp = datetime.now(timezone.utc)
    candidates = [args.journal] if args.journal else [DEFAULT_JOURNAL, DEFAULT_JOURNAL_DIR]
    journal = None
    for candidate in candidates:
        journal = resolve_journal(candidate)
        if journal is not None:
            break

    if journal is None:
        payload = {
            "timestamp": timestamp.isoformat(),
            "metrics": {},
            "decision": {
                "changed": False,
                "action": "hold",
                "param": None,
                "from_value": None,
                "to_value": None,
                "reason": "no data",
            },
            "state": {"journal": None},
        }
        path = report_path(args.reports_dir, timestamp)
        write_report(path, payload)
        print(f"no data: no journal found in {', '.join(candidates)}")
        print(f"report: {path}")
        return 0

    fills, state_record = read_journal(journal)
    state = build_state(state_record, fills)
    params = load_params(args.params, state)
    decision = agent.run_once(state, fills, params)

    payload = {
        "timestamp": timestamp.isoformat(),
        "metrics": decision["metrics"],
        "decision": {k: v for k, v in decision.items() if k != "metrics"},
        "state": {
            "journal": os.path.basename(journal),
            "fill_count": len(fills),
            "up_shares": state.up_shares,
            "down_shares": state.down_shares,
            "max_inventory_per_side": state.max_inventory_per_side,
            "equity_usd": state.equity_usd,
            "drawdown_pct": state.drawdown_pct,
            "tau_seconds": state.tau_seconds,
            "heartbeat_ok": state.heartbeat_ok,
        },
    }
    path = report_path(args.reports_dir, timestamp)
    write_report(path, payload)

    if args.json:
        print(json.dumps(decision, indent=2, default=str))
    else:
        print(f"journal: {journal}")
        print(f"rolling_net_bps: {decision['metrics'].get('rolling_net_bps')}")
        print(f"changed: {decision['changed']}")
        print(f"param: {decision['param']}")
        print(f"from_value: {decision['from_value']}")
        print(f"to_value: {decision['to_value']}")
        print(f"reason: {decision['reason']}")
    print(f"report: {path}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
