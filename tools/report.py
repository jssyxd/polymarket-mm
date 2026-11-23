"""Summarise what the live loop actually did: fills, notional, PnL, inventory.

Reads the journal (the record of every confirmed fill the venue reported) and
the current marks, and prints one block per figure. Nothing here talks to the
venue except to read marks when asked.
"""

from __future__ import annotations

import argparse
import json
import sys
from collections import Counter, defaultdict
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.journal import Journal, compute_pnl  # noqa: E402


def _marks(config: ExecutionConfig) -> dict[str, float]:
    """Current mark per token, from the account's positions."""
    from pmm.execution.positions import read_positions

    marks: dict[str, float] = {}
    for row in read_positions(config).get("api_positions") or []:
        token = str(row.get("token_id") or "")
        if token:
            marks[token] = float(row.get("current_price") or 0.0)
    return marks


def summarise(journal: Journal, marks: dict[str, float] | None = None, day: str | None = None) -> dict:
    fills = journal.fills()
    if day:
        fills = [f for f in fills if str(f.get("ts", "")) and _utc_date(f) == day]

    by_market: dict[str, dict] = defaultdict(lambda: {"fills": 0, "notional": 0.0, "size": 0.0})
    sides: Counter = Counter()
    for fill in fills:
        market = str(fill.get("condition_id") or "")
        record = by_market[market]
        record["fills"] += 1
        record["notional"] += float(fill.get("notional") or 0.0)
        record["size"] += float(fill.get("size") or 0.0)
        sides[str(fill.get("side") or "").upper()] += 1

    pnl = compute_pnl(fills, marks or {}) if fills else {"realized": 0.0, "position_value": 0.0}
    return {
        "fills": len(fills),
        "notional": round(sum(float(f.get("notional") or 0.0) for f in fills), 2),
        "sides": dict(sides),
        "markets": len(by_market),
        "top": sorted(by_market.items(), key=lambda kv: -kv[1]["notional"])[:5],
        "realized": round(float(pnl.get("realized") or 0.0), 2),
        "position_value": round(float(pnl.get("position_value") or 0.0), 2),
    }


def _utc_date(fill: dict) -> str:
    import datetime as dt

    try:
        stamp = dt.datetime.fromtimestamp(float(fill.get("ts") or 0), dt.timezone.utc)
        return stamp.strftime("%Y-%m-%d")
    except (TypeError, ValueError):
        return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--journal", default=None, help="journal directory")
    parser.add_argument("--day", default=None, help="UTC date, YYYY-MM-DD")
    parser.add_argument("--no-marks", action="store_true", help="skip reading live marks")
    parser.add_argument("--json", action="store_true", help="machine readable")
    args = parser.parse_args(argv)

    config = ExecutionConfig.from_env()
    journal = Journal(args.journal or config.journal_path)
    marks = {} if args.no_marks else _marks(config)
    summary = summarise(journal, marks, args.day)

    if args.json:
        print(json.dumps(summary, indent=1))
        return 0

    print(f"fills         {summary['fills']}")
    print(f"markets       {summary['markets']}")
    print(f"notional      {summary['notional']:.2f} pUSD")
    print(f"sides         {summary['sides']}")
    print(f"realized PnL  {summary['realized']:.2f} pUSD")
    print(f"inventory     {summary['position_value']:.2f} pUSD")
    if summary["top"]:
        print("\ntop markets by notional")
        for market, record in summary["top"]:
            print(f"  {market[:12]}  fills={record['fills']:<4} notional={record['notional']:>8.2f}  size={record['size']:>9.2f}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
