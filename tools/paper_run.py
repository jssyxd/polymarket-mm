"""Paper run: quote one live up/down market and record the intent.

Resolves a live market from the Gamma API, reads its book from the CLOB,
builds two quote objects (a bid and an ask on the up token, sized at the
market minimum), records them as `order_intent` lines in the journal, and
prints the journal path.

In paper mode the tool then watches the live book and records a `fill` line
for any quote the book would have crossed. Nothing is ever sent to the
exchange unless `POLY_DRY_RUN=0` and `POLY_OWNER_PK` is set.

Usage:
    python tools/paper_run.py --market btc-updown-5m --dry-run
"""

from __future__ import annotations

import argparse
import json
import sys
import time
import urllib.error
import urllib.parse
import urllib.request
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.execution.clob import ExecutionError, OrderExecutor  # noqa: E402
from pmm.execution.config import ExecutionConfig  # noqa: E402
from pmm.execution.journal import Journal  # noqa: E402

GAMMA_API = "https://gamma-api.polymarket.com"
CLOB_HOST = "https://clob.polymarket.com"
HTTP_TIMEOUT_SECONDS = 15.0


def _get_json(url: str) -> object:
    request = urllib.request.Request(url, headers={"Accept": "*/*", "User-Agent": "pmm-paper/1"})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        return json.loads(response.read().decode("utf-8"))


def resolve_market(prefix: str) -> dict:
    """Find the live market whose slug starts with `prefix`, newest first."""
    params = urllib.parse.urlencode(
        {
            "closed": "false",
            "active": "true",
            "limit": "200",
            "order": "startDate",
            "ascending": "false",
        }
    )
    payload = _get_json(f"{GAMMA_API}/markets?{params}")
    markets = payload if isinstance(payload, list) else []
    matches = [
        market
        for market in markets
        if isinstance(market, dict) and str(market.get("slug", "")).startswith(prefix)
    ]
    if not matches:
        raise SystemExit(f"no live market found with slug prefix {prefix!r}")
    matches.sort(key=lambda market: str(market.get("slug", "")), reverse=True)
    return matches[0]


def read_book(token_id: str) -> dict:
    url = f"{CLOB_HOST}/book?{urllib.parse.urlencode({'token_id': token_id})}"
    try:
        payload = _get_json(url)
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _best(book: dict, side: str) -> float | None:
    levels = book.get(side) or []
    prices = []
    for level in levels:
        try:
            prices.append(float(level.get("price")))
        except (TypeError, ValueError):
            continue
    if not prices:
        return None
    return max(prices) if side == "bids" else min(prices)


def build_quotes(market: dict) -> list[dict]:
    """Build a bid and an ask on the up token of an up/down market."""
    token_ids = market.get("clobTokenIds")
    outcomes = market.get("outcomes")
    if isinstance(token_ids, str):
        token_ids = json.loads(token_ids)
    if isinstance(outcomes, str):
        outcomes = json.loads(outcomes)
    if not token_ids:
        raise SystemExit(f"market {market.get('slug')} has no clob token ids")
    if not outcomes or str(outcomes[0]).lower() != "up":
        raise SystemExit(f"market {market.get('slug')} does not have an up leg")

    up_token = str(token_ids[0])
    down_token = str(token_ids[1]) if len(token_ids) > 1 else None
    book = read_book(up_token)
    tick = float(book.get("tick_size") or market.get("orderPriceMinTickSize") or 0.01)
    size = float(market.get("orderMinSize") or book.get("min_order_size") or 5)

    best_bid = _best(book, "bids")
    best_ask = _best(book, "asks")
    if best_bid is None and best_ask is None:
        mid = 0.5
        best_bid = round(mid - tick / 2, 4)
        best_ask = round(mid + tick / 2, 4)

    def _round_down(price: float) -> float:
        steps = int(price / tick + 1e-9)
        return round(steps * tick, 4)

    def _round_up(price: float) -> float:
        steps = int(price / tick + 1e-9)
        if steps * tick < price - 1e-9:
            steps += 1
        return round(steps * tick, 4)

    bid_price = _round_down(best_bid if best_bid is not None else 0.49)
    ask_price = _round_up(best_ask if best_ask is not None else 0.51)

    common = {
        "condition_id": market.get("conditionId") or market.get("condition_id"),
        "market_slug": market.get("slug"),
        "up_token_id": up_token,
        "down_token_id": down_token,
        "tick_size": tick,
        "size": size,
    }
    return [
        dict(common, token_id=up_token, side="BUY", price=bid_price, outcome="Up"),
        dict(common, token_id=up_token, side="SELL", price=ask_price, outcome="Up"),
    ]


def paper_check(quotes: list[dict]) -> list[dict]:
    """Return a simulated fill for every quote the live book has crossed."""
    books: dict[str, dict] = {}
    fills: list[dict] = []
    for quote in quotes:
        token_id = str(quote["token_id"])
        if token_id not in books:
            books[token_id] = read_book(token_id)
        book = books[token_id]
        if quote["side"] == "BUY":
            best_ask = _best(book, "asks")
            if best_ask is not None and best_ask <= float(quote["price"]):
                fills.append(dict(quote, fill_price=float(quote["price"])))
        else:
            best_bid = _best(book, "bids")
            if best_bid is not None and best_bid >= float(quote["price"]):
                fills.append(dict(quote, fill_price=float(quote["price"])))
    return fills


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Paper-quote one live up/down market.")
    parser.add_argument("--market", required=True, help="market slug prefix, e.g. btc-updown-5m")
    parser.add_argument("--dry-run", action="store_true", help="force dry-run mode")
    parser.add_argument("--watch", type=float, default=0.0, help="seconds to watch the live book")
    parser.add_argument("--interval", type=float, default=1.0, help="seconds between book reads")
    args = parser.parse_args(argv)

    config = ExecutionConfig.from_env()
    if args.dry_run:
        config.dry_run = True

    market = resolve_market(args.market)
    quotes = build_quotes(market)
    journal = Journal(config.journal_path)
    executor = OrderExecutor(config, journal)

    for quote in quotes:
        executor.place(quote, reason=f"paper:{market.get('slug')}")

    book = read_book(str(quotes[0]["token_id"]))
    journal.record_position(
        {
            "market_slug": market.get("slug"),
            "condition_id": quotes[0].get("condition_id"),
            "up_token_id": quotes[0].get("up_token_id"),
            "down_token_id": quotes[0].get("down_token_id"),
            "best_bid": _best(book, "bids"),
            "best_ask": _best(book, "asks"),
            "tick_size": quotes[0].get("tick_size"),
            "min_order_size": quotes[0].get("size"),
        },
        mode="paper",
    )

    if config.dry_run and args.watch > 0:
        deadline = time.time() + args.watch
        while time.time() < deadline:
            for fill in paper_check(quotes):
                journal.append(
                    "fill",
                    mode="paper",
                    token_id=fill["token_id"],
                    condition_id=fill.get("condition_id"),
                    outcome=fill.get("outcome"),
                    side=fill["side"],
                    price=fill["fill_price"],
                    size=fill["size"],
                )
            time.sleep(max(args.interval, 0.1))

    path = journal.file_for(time.strftime("%Y-%m-%d"))
    print(f"market: {market.get('slug')}")
    print(f"quotes: {len(quotes)}")
    print(f"dry_run: {config.dry_run}")
    print(f"journal: {path}")
    executor.close()
    return 0


if __name__ == "__main__":
    try:
        raise SystemExit(main())
    except ExecutionError as error:
        print(f"execution error: {error}", file=sys.stderr)
        raise SystemExit(1)
