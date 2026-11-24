"""Close a leg that has stood alone too long by buying its pair.

Runs every five minutes. A repair is only placed when the held leg's entry
cost plus the missing leg's ask is at most 1 pUSD, so the merge that follows
cannot lose. Disabled unless POLY_REPAIR=1; `--dry-run` always works.
"""

from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.data.clob import get_book  # noqa: E402
from pmm.execution.clob import OrderExecutor  # noqa: E402
from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.positions import read_positions  # noqa: E402
from pmm.execution.repair import (  # noqa: E402
    DEFAULT_MAX_AGE_SECONDS,
    plan_repairs,
)


def _best_ask(book: dict) -> float:
    asks = book.get("asks") or []
    return min((float(level.get("price") or 0) for level in asks), default=0.0)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-age", type=float, default=DEFAULT_MAX_AGE_SECONDS)
    parser.add_argument("--max-orders", type=int, default=3)
    args = parser.parse_args(argv)

    config = ExecutionConfig.from_env()
    if not (args.dry_run or config.dry_run):
        if not getattr(config, "repair_enabled", False):
            print("refused: set POLY_REPAIR=1 to place live repair orders", file=sys.stderr)
            return 2

    executor = OrderExecutor(config)
    positions = read_positions(config).get("api_positions") or []
    try:
        open_assets = [str(o.get("asset_id")) for o in executor.client.get_open_orders() if isinstance(o, dict)]
    except Exception:  # noqa: BLE001
        open_assets = []

    asks: dict[str, float] = {}
    for row in positions:
        if float(row.get("current_size") or 0) <= 0:
            continue
        condition_id = str(row.get("condition_id") or "")
        token_id = str(row.get("opposite_token_id") or "")
        if not condition_id or not token_id:
            continue
        try:
            asks[condition_id] = _best_ask(get_book(token_id))
        except Exception:  # noqa: BLE001 - no book, no plan
            continue

    plans = plan_repairs(
        positions,
        complement_asks=asks,
        open_assets=open_assets,
        now=time.time(),
        max_age_seconds=args.max_age,
    )[: max(0, int(args.max_orders))]

    results = []
    for plan in plans:
        record = {
            "condition_id": plan.condition_id,
            "size": plan.size,
            "price": plan.price,
            "pair_cost": plan.pair_cost,
            "age_seconds": plan.age_seconds,
        }
        if config.dry_run:
            record["status"] = "dry_run"
            results.append(record)
            continue
        intent = {
            "token_id": plan.token_id,
            "price": plan.price,
            "size": plan.size,
            "side": "BUY",
            "post_only": False,  # take the ask: the pair must actually close
        }
        try:
            payload = executor.build_payload(intent)
            response = executor.place(payload=payload, reason=f"repair:{plan.condition_id[:10]}")
            record["status"] = str(response.get("status") or "unknown")
            if response.get("success") is False:
                record["status"] = f"failed: {response.get('errorMsg') or response}"
        except Exception as exc:  # noqa: BLE001
            record["status"] = f"failed: {type(exc).__name__}: {exc}"[:200]
        results.append(record)

    print(json.dumps(results, indent=1))
    return 0 if all(not str(r["status"]).startswith("failed") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
