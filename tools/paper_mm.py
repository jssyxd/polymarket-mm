"""Replay recorded books through the paper broker and write a ledger.

Every sample contributes one round-trip measurement: buy `size` at the asks,
sell `size` at the bids, on the same book. That number is the cost floor any
taker strategy has to beat, and it needs no oracle to compute.

Fees are explicit (`--fee-bps`, default 0, the value measured on the venue).
Slippage is whatever the book depth actually charges.
"""

from __future__ import annotations

import argparse
import json
import statistics
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.paper.broker import Book, execute  # noqa: E402


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--books", required=True, help="recorded books JSONL")
    parser.add_argument("--ledger", default="paper-ledger.jsonl")
    parser.add_argument("--size", type=float, default=20.0)
    parser.add_argument("--fee-bps", type=float, default=0.0)
    parser.add_argument("--limit", type=int, default=0, help="stop after N samples")
    args = parser.parse_args(argv)

    rows = 0
    round_trip: list[float] = []
    spreads: list[float] = []
    buy_slip: list[float] = []
    with open(args.books, encoding="utf-8") as src, open(args.ledger, "w", encoding="utf-8") as out:
        for line in src:
            try:
                record = json.loads(line)
            except ValueError:
                continue
            for key in ("book_up", "book_down"):
                raw = record.get(key)
                if not isinstance(raw, dict):
                    continue
                book = Book.from_raw(raw)
                if not book.bids or not book.asks:
                    continue
                buy = execute(book, "BUY", args.size, fee_bps=args.fee_bps)
                sell = execute(book, "SELL", args.size, fee_bps=args.fee_bps)
                if buy is None or sell is None or buy.size < args.size or sell.size < args.size:
                    continue
                cost = buy.notional + buy.fee
                proceeds = sell.notional - sell.fee
                pnl = proceeds - cost
                out.write(json.dumps({
                    "ts": record.get("ts"),
                    "condition_id": record.get("condition_id"),
                    "token": key,
                    "size": args.size,
                    "buy": buy.price,
                    "sell": sell.price,
                    "spread": round(sell.best - buy.best, 6),
                    "buy_slippage": buy.slippage,
                    "sell_slippage": sell.slippage,
                    "fee": round(buy.fee + sell.fee, 6),
                    "pnl": round(pnl, 6),
                    "pnl_per_share": round(pnl / args.size, 6),
                }) + "\n")
                round_trip.append(pnl)
                spreads.append(sell.best - buy.best)
                buy_slip.append(buy.slippage)
                rows += 1
            if args.limit and rows >= args.limit:
                break

    if not round_trip:
        print(json.dumps({"samples": 0, "error": "no crossable books"}))
        return 1
    summary = {
        "samples": rows,
        "size": args.size,
        "fee_bps": args.fee_bps,
        "mean_pnl_per_round_trip": round(statistics.fmean(round_trip), 6),
        "median_spread": round(statistics.median(spreads), 6),
        "mean_buy_slippage": round(statistics.fmean(buy_slip), 6),
        "worst_pnl": round(min(round_trip), 6),
        "best_pnl": round(max(round_trip), 6),
        "ledger": args.ledger,
    }
    print(json.dumps(summary, indent=1))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
