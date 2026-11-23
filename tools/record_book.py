#!/usr/bin/env python3
"""Record live books to a JSONL file so a quote cycle can be replayed offline.

One line per market per sample. Each line carries everything a market
snapshot holds, including both raw books, so the replay sees exactly what the
live cycle saw.

    python tools/record_book.py --out books.jsonl --top 5 --duration 60
    python tools/record_book.py --out books.jsonl --markets 0xabc...,0xdef...
    python tools/run_mm.py --dry-run --once --replay books.jsonl

The file needs no credentials: every endpoint used here is public.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.data.clob import CLOBError  # noqa: E402
from pmm.engine.runner import RunnerConfig, discover_markets  # noqa: E402

DEFAULT_OUT = "books.jsonl"


def parse_args(argv: list[str] | None = None) -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Record live books for replay")
    parser.add_argument("--out", default=DEFAULT_OUT, help="JSONL file to append to")
    parser.add_argument("--markets", default="", help="comma separated condition ids")
    parser.add_argument("--top", type=int, default=5, help="reward markets to record")
    parser.add_argument("--interval", type=float, default=5.0, help="seconds between samples")
    parser.add_argument("--duration", type=float, default=0.0, help="seconds to run, 0 is forever")
    parser.add_argument("--once", action="store_true", help="one sample and exit")
    parser.add_argument("--size", type=float, default=20.0, help="size used for the reward score")
    return parser.parse_args(argv)


def main(argv: list[str] | None = None) -> int:
    args = parse_args(argv)
    out_path = Path(args.out).expanduser()
    out_path.parent.mkdir(parents=True, exist_ok=True)

    condition_ids = [part.strip() for part in args.markets.split(",") if part.strip()]
    config = RunnerConfig(
        size_shares=args.size,
        top=args.top,
        min_rate_per_day=0.0,
        max_spread_cents_cap=1e9,
    )

    deadline = time.monotonic() + args.duration if args.duration > 0 else None
    samples = 0
    with out_path.open("a", encoding="utf-8") as handle:
        while True:
            try:
                pairs = discover_markets(config, 1.0, condition_ids)
            except CLOBError as exc:
                print(f"discovery failed: {exc}", file=sys.stderr)
                pairs = []
            for snapshot, _ in pairs:
                payload = snapshot.to_dict()
                payload["ts"] = datetime.now(timezone.utc).isoformat()
                handle.write(json.dumps(payload, separators=(",", ":"), default=str) + "\n")
            handle.flush()
            samples += 1
            print(f"sample {samples}: {len(pairs)} markets -> {out_path}")

            if args.once:
                break
            if deadline is not None and time.monotonic() >= deadline:
                break
            time.sleep(max(args.interval, 0.1))

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
