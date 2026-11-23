"""Print the top liquidity-reward candidates for a given capital and size.

Every endpoint used here is public, so this runs without credentials.

    python3 tools/scan_pools.py --capital 3.4 --size 20 --top 15
"""

from __future__ import annotations

import argparse
import sys
from concurrent.futures import ThreadPoolExecutor
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.data import clob  # noqa: E402
from pmm.data.universe import (  # noqa: E402
    RewardCandidate,
    market_meta,
    score_candidate,
    select_candidates,
)


def _rate_of(row: dict) -> float:
    configs = row.get("rewards_config") or ()
    rates = [float(c["rate_per_day"]) for c in configs if "rate_per_day" in c]
    if rates:
        return max(rates)
    return float(row.get("native_daily_rate") or 0.0)


def build_candidates(
    size_shares: float,
    spread_cents: float,
    min_rate_per_day: float,
    max_spread_cap: float,
    limit: int,
) -> list[RewardCandidate]:
    """Score the most promising reward markets for our hypothetical quote."""
    rows = clob.list_reward_markets_with_competition()
    pool = [
        row
        for row in rows
        if _rate_of(row) >= min_rate_per_day
        and float(row.get("rewards_max_spread") or 0.0) <= max_spread_cap
        and float(row.get("rewards_min_size") or 0.0) <= size_shares
    ]
    pool.sort(key=_rate_of, reverse=True)
    pool = pool[:limit]

    def score_row(row: dict) -> RewardCandidate | None:
        try:
            market = clob.get_market(row["condition_id"])
        except clob.CLOBError:
            return None
        meta = market_meta(market, rewards_row=row)
        tokens = meta["tokens"]
        if len(tokens) != 2:
            return None
        try:
            book_a = clob.get_book(tokens[0])
            book_b = clob.get_book(tokens[1])
            mid_a = clob.get_midpoint(tokens[0])
            mid_b = clob.get_midpoint(tokens[1])
        except clob.CLOBError:
            return None
        return score_candidate(
            meta,
            book_a,
            book_b,
            mid_a,
            mid_b,
            size_shares,
            spread_cents,
            row.get("market_competitiveness"),
        )

    with ThreadPoolExecutor(max_workers=8) as pool_executor:
        scored = list(pool_executor.map(score_row, pool))

    return [candidate for candidate in scored if candidate is not None]


def format_table(candidates: list[RewardCandidate], capital: float) -> str:
    header = (
        f"{'#':>2}  {'market':<60.60} {'rate/day':>9} {'minsz':>6} {'spread':>6} "
        f"{'share%':>7} {'est$/day':>8} {'notional':>8} {'mid':>6}"
    )
    lines = [header, "-" * len(header)]
    total = 0.0
    for index, candidate in enumerate(candidates, start=1):
        total += candidate.notional_usd
        lines.append(
            f"{index:>2}  {candidate.question[:60]:<60.60} "
            f"{candidate.rate_per_day:>9.2f} {candidate.min_size:>6.0f} "
            f"{candidate.max_spread_cents:>6.1f} {candidate.est_share_pct:>7.3f} "
            f"{candidate.est_daily_usd:>8.3f} {candidate.notional_usd:>8.3f} "
            f"{candidate.midpoint:>6.3f}"
        )
    lines.append("-" * len(header))
    lines.append(f"capital {capital:.3f} pUSD, notional committed {total:.3f} pUSD")
    return "\n".join(lines)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capital", type=float, default=3.4, help="pUSD to commit")
    parser.add_argument("--size", type=float, default=20.0, help="shares per side")
    parser.add_argument("--top", type=int, default=15, help="rows to print")
    parser.add_argument("--spread", type=float, default=1.0, help="our spread from midpoint, cents")
    parser.add_argument("--min-rate", type=float, default=50.0, help="minimum rate per day")
    parser.add_argument(
        "--max-spread-cap", type=float, default=4.5, help="cap on the market's max spread, cents"
    )
    parser.add_argument(
        "--scan-limit", type=int, default=40, help="markets to pull books for before ranking"
    )
    parser.add_argument("--out", help="also write the table to this file")
    args = parser.parse_args(argv)

    candidates = build_candidates(
        size_shares=args.size,
        spread_cents=args.spread,
        min_rate_per_day=args.min_rate,
        max_spread_cap=args.max_spread_cap,
        limit=args.scan_limit,
    )
    selected = select_candidates(
        candidates,
        capital_usd=args.capital,
        max_spread_cents_cap=args.max_spread_cap,
        min_rate_per_day=args.min_rate,
    )
    table = format_table(selected[: args.top], args.capital)
    print(table)
    if args.out:
        Path(args.out).write_text(table + "\n", encoding="utf-8")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
