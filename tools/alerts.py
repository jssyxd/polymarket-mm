"""Check the live invariants and journal an alert for every breach.

Exits non-zero when anything fires, so systemd records the run as failed and
`systemctl --failed` surfaces it without a notification service.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.execution.clob import OrderExecutor  # noqa: E402
from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.journal import Journal  # noqa: E402
from pmm.execution.positions import read_positions  # noqa: E402
from pmm.monitor.alerts import evaluate  # noqa: E402
from pmm.engine.self_tune import load_params  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", default=None)
    parser.add_argument("--dry-run", action="store_true", help="report, journal nothing")
    args = parser.parse_args(argv)

    config = ExecutionConfig.from_env()
    journal = Journal(config.journal_path)
    params = load_params(args.params or __import__("os").environ.get("POLY_PARAMS_PATH", ""))
    box = float(params.get("inventory_box", 0.0) or 0.0)

    positions = read_positions(config).get("api_positions") or []
    try:
        executor = OrderExecutor(config)
        cash = executor.collateral_balance() or 0.0
        open_orders = len(executor.client.get_open_orders())
    except Exception as exc:  # noqa: BLE001 - a blind check is itself a condition
        print(f"could not read the account: {exc}", file=sys.stderr)
        return 2

    alerts = evaluate(
        positions,
        cash=cash,
        open_orders=open_orders,
        inventory_box=box,
        fills=journal.fills(),
    )
    for alert in alerts:
        if not args.dry_run:
            journal.append("alert", kind=alert.kind, detail=alert.detail)
        print(f"ALERT {alert.kind}: {alert.detail}")
    if not alerts:
        print("ok: no alerts")
    return 0 if not alerts else 1


if __name__ == "__main__":
    raise SystemExit(main())
