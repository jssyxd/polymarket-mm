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
from pmm.monitor.alerts import evaluate, timer_alerts  # noqa: E402
from pmm.engine.self_tune import disable_quoting, load_params  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--params", default=None)
    parser.add_argument("--dry-run", action="store_true", help="report, journal nothing")
    parser.add_argument("--check-timers", action="store_true",
                        help="also verify the recycling timers are active (VPS only)")
    parser.add_argument("--no-pause", action="store_true", help="do not disable quoting on alert")
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
    if args.check_timers:
        import subprocess

        required = ["pmm-merge.timer", "pmm-redeem.timer", "pmm-alerts.timer"]
        states = {}
        for unit in required:
            try:
                states[unit] = subprocess.run(
                    ["systemctl", "is-active", unit], capture_output=True, text=True, timeout=10
                ).stdout.strip()
            except Exception:
                states[unit] = "unknown"
        alerts = alerts + timer_alerts(states, required)

    for alert in alerts:
        if not args.dry_run:
            journal.append("alert", alert=alert.kind, detail=alert.detail)
        print(f"ALERT {alert.kind}: {alert.detail}")
    if not alerts:
        print("ok: no alerts")
        return 0
    if not args.dry_run and not args.no_pause:
        params_path = args.params or __import__("os").environ.get("POLY_PARAMS_PATH", "")
        if params_path:
            disable_quoting(params_path, reason=alerts[0].kind)
            print("quoting disabled in the parameter file")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
