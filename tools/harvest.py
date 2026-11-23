"""Plan B: sell a nearly-won leg at the 0.99 floor instead of waiting to settle.

Disabled by default. `--dry-run` always works and prints what it would sell;
a live run requires POLY_HARVEST=1 in the environment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.harvest import (  # noqa: E402
    HARVEST_MIN_PRICE,
    MIN_ORDER_SIZE,
    run_harvest,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report plans, place nothing")
    parser.add_argument("--min-price", type=float, default=HARVEST_MIN_PRICE)
    parser.add_argument("--min-size", type=float, default=MIN_ORDER_SIZE)
    parser.add_argument("--max-orders", type=int, default=3)
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = ExecutionConfig.from_env()
    if args.dry_run:
        config.dry_run = True
    try:
        results = run_harvest(
            config,
            min_price=args.min_price,
            min_size=args.min_size,
            max_orders=args.max_orders,
        )
    except RuntimeError as exc:
        print(f"refused: {exc}", file=sys.stderr)
        return 2
    print(json.dumps(results, indent=1))
    return 0 if all(not str(r["status"]).startswith("failed") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
