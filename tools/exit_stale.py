"""Sell a leg that has stood alone for more than the exit age.

Dry-run by default. A live sell requires POLY_EXIT=1. The sell is a marketable
limit at the current best bid, so it can cross and fill immediately; it is not
a maker quote.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.data.clob import get_book, get_market  # noqa: E402
from pmm.execution.clob import OrderExecutor  # noqa: E402
from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.exit import DEFAULT_MAX_AGE_SECONDS, plan_exits  # noqa: E402
from pmm.execution.journal import Journal  # noqa: E402
from pmm.execution.positions import read_positions  # noqa: E402


def _best(book: dict, side: str) -> float:
    levels = book.get(side) or []
    prices = []
    for level in levels:
        try:
            prices.append(float(level.get("price") or 0))
        except (TypeError, ValueError):
            continue
    if not prices:
        return 0.0
    return min(prices) if side == "asks" else max(prices)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dry-run", action="store_true")
    parser.add_argument("--max-age", type=float, default=DEFAULT_MAX_AGE_SECONDS)
    parser.add_argument("--max-orders", type=int, default=3)
    args = parser.parse_args(argv)

    config = ExecutionConfig.from_env()
    if not args.dry_run and os.environ.get("POLY_EXIT") != "1":
        print("refused: set POLY_EXIT=1 to sell a stale leg", file=sys.stderr)
        return 2

    executor = OrderExecutor(config)
    positions = read_positions(config).get("api_positions") or []
    try:
        open_assets = [str(o.get("asset_id")) for o in executor.client.get_open_orders() if isinstance(o, dict)]
    except Exception:  # noqa: BLE001
        open_assets = []

    journal = Journal(config.journal_path)
    entry_times: dict[str, float] = {}
    for fill in journal.fills():
        token = str(fill.get("token_id") or "")
        stamp = fill.get("ts")
        try:
            stamp_f = float(stamp) if not isinstance(stamp, bool) else 0.0
        except (TypeError, ValueError):
            stamp_f = 0.0
        if token and stamp_f > 0 and (token not in entry_times or stamp_f < entry_times[token]):
            entry_times[token] = stamp_f

    bids: dict[str, float] = {}
    asks: dict[str, float] = {}
    market_tokens: dict[str, list[str]] = {}
    for row in positions:
        if float(row.get("current_size") or 0) <= 0:
            continue
        token_id = str(row.get("token_id") or row.get("asset_id") or row.get("asset") or "")
        condition_id = str(row.get("condition_id") or "")
        if token_id:
            try:
                bids[token_id] = _best(get_book(token_id), "bids")
            except Exception:  # noqa: BLE001
                pass
        if condition_id and condition_id not in market_tokens:
            try:
                market = get_market(condition_id)
                market_tokens[condition_id] = [str(t.get("token_id")) for t in market.get("tokens") or [] if isinstance(t, dict)]
            except Exception:  # noqa: BLE001
                market_tokens[condition_id] = []
        opposite = str(row.get("opposite_token_id") or "")
        if not opposite and token_id:
            others = [t for t in market_tokens.get(condition_id, []) if t != token_id]
            opposite = others[0] if others else ""
        if opposite:
            try:
                asks[condition_id] = _best(get_book(opposite), "asks")
            except Exception:  # noqa: BLE001
                pass

    plans = plan_exits(
        positions,
        best_bids=bids,
        complement_asks=asks,
        open_assets=open_assets,
        entry_times=entry_times,
        now=time.time(),
        max_age_seconds=args.max_age,
    )[: max(0, int(args.max_orders))]

    results = []
    for plan in plans:
        record = {
            "condition_id": plan.condition_id,
            "size": plan.size,
            "price": plan.price,
            "avg_cost": plan.avg_cost,
            "age_seconds": plan.age_seconds,
            "pair_cost": plan.pair_cost,
        }
        if config.dry_run or args.dry_run:
            record["status"] = "dry_run"
            results.append(record)
            continue
        intent = {
            "token_id": plan.token_id,
            "price": plan.price,
            "size": plan.size,
            "side": "SELL",
            "post_only": False,
        }
        try:
            payload = executor.build_payload(intent)
            response = executor.place(payload=payload, reason=f"exit:{plan.condition_id[:10]}")
            record["status"] = str(response.get("status") or "unknown")
        except Exception as exc:  # noqa: BLE001
            record["status"] = f"failed: {type(exc).__name__}: {exc}"[:200]
        results.append(record)

    print(json.dumps(results, indent=1))
    return 0 if all(not str(r["status"]).startswith("failed") for r in results) else 1


if __name__ == "__main__":
    raise SystemExit(main())
