"""Complete nearly-won positions by buying the cheap leg, so merge can pay 1.00.

Run it on a timer. For every market where exactly one outcome is held and that
outcome trades at or above --min-price, it posts a post-only buy at the tick
floor on the other outcome. Once both legs are held, the merge timer converts
the complete set into 1.00 pUSD per set, without waiting for resolution.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.rescue import (  # noqa: E402
    DEFAULT_MIN_PRICE,
    DEFAULT_MIN_DAYS_TO_RESOLUTION,
    DEFAULT_MIN_SIZE,
    run_rescue,
)


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report plans, place nothing")
    parser.add_argument("--min-price", type=float, default=DEFAULT_MIN_PRICE,
                        help="held leg must be at or above this price")
    parser.add_argument("--min-size", type=float, default=DEFAULT_MIN_SIZE)
    parser.add_argument("--max-orders", type=int, default=5, help="orders per run")
    parser.add_argument("--min-days", type=float, default=DEFAULT_MIN_DAYS_TO_RESOLUTION,
                        help="skip markets resolving sooner than this many days")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = ExecutionConfig.from_env()
    if args.dry_run:
        config.dry_run = True
    results = run_rescue(
        config,
        min_price=args.min_price,
        min_size=args.min_size,
        min_days_to_resolution=args.min_days,
        max_orders=args.max_orders,
    )
    print(json.dumps(results, indent=1))
    return 0 if all(not str(r["status"]).startswith("failed") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
