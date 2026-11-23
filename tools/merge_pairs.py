"""Merge complete outcome pairs back into pUSD.

Run it after the quoting loop has filled both legs of a market. It reads the
account's positions, merges every market where both outcomes are held, and
prints what it did. Safe to run repeatedly: a market with only one leg is
left alone.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.merge import MERGE_MIN_SIZE, merge_pairs  # noqa: E402


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true", help="report targets, merge nothing")
    parser.add_argument("--min-size", type=float, default=MERGE_MIN_SIZE, help="smallest pair to merge")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    config = ExecutionConfig.from_env()
    if args.dry_run:
        config.dry_run = True
    results = merge_pairs(config, min_size=args.min_size)
    print(json.dumps(results, indent=1))
    return 0 if all(not r["status"].startswith("failed") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
