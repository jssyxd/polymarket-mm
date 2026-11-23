"""Redeem resolved winning positions into pUSD.

Runs on a timer. For every market the venue marks `redeemable` with a
winning leg, it signs a relayer transaction and records the payout in the
journal. Losing legs are skipped: redeeming them pays nothing.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.journal import Journal  # noqa: E402
from pmm.execution.redeem import (  # noqa: E402
    REDEEM_MIN_PRICE,
    REDEEM_MIN_SIZE,
    run_redeem,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report targets, redeem nothing")
    parser.add_argument("--min-size", type=float, default=REDEEM_MIN_SIZE)
    parser.add_argument("--min-price", type=float, default=REDEEM_MIN_PRICE)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = ExecutionConfig.from_env()
    if args.dry_run:
        config.dry_run = True
    results = run_redeem(
        config,
        journal=Journal(config.journal_path),
        min_size=args.min_size,
        min_price=args.min_price,
    )
    print(json.dumps(results, indent=1))
    return 0 if all(not str(r["status"]).startswith("failed") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
