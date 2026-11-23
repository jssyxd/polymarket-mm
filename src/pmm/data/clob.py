"""Read-only Polymarket CLOB and Gamma HTTP client.

Standard library only. Every endpoint used here is public and unauthenticated,
so this module never needs credentials and never holds one.
"""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.parse
import urllib.request
from typing import Any

CLOB_BASE = "https://clob.polymarket.com"
GAMMA_BASE = "https://gamma-api.polymarket.com"

DEFAULT_TIMEOUT = 15.0
#: The reward market list pages through the whole venue, thousands of rows
#: over about sixteen requests, and each page is a few hundred kilobytes. A
#: single slow page must not abort the scan, so this endpoint gets a longer
#: deadline than the per-market reads.
BULK_TIMEOUT = 45.0
USER_AGENT = "polymarket-mm/0.1 (read-only market scanner)"

#: In-game multiplier ``b`` from the rewards methodology is 1 everywhere we quote.
UPDOWN_ASSETS = ("btc", "eth", "sol", "xrp", "doge", "bnb", "hype", "zec")
UPDOWN_DURATIONS = {"5m": 300, "15m": 900}

_MARKET_CACHE_TTL = 60.0
_market_cache: dict[str, tuple[float, dict[str, Any]]] = {}


class CLOBError(RuntimeError):
    """Typed failure from a CLOB or Gamma request.

    ``status`` is the HTTP status when one was received, ``None`` for transport
    failures. ``body`` carries the response payload (truncated) or the
    transport error text.
    """

    def __init__(self, message: str, status: int | None = None, body: str = "") -> None:
        super().__init__(message)
        self.status = status
        self.body = body

    def __str__(self) -> str:
        base = super().__str__()
        if self.status is None:
            return f"{base} (no HTTP status)"
        return f"{base} (HTTP {self.status})"


def _truncate(body: str, limit: int = 600) -> str:
    body = body.strip()
    return body if len(body) <= limit else body[:limit] + "..."


def _request_json(url: str, timeout: float = DEFAULT_TIMEOUT) -> Any:
    """GET ``url`` and decode JSON, raising :class:`CLOBError` on any failure."""
    request = urllib.request.Request(
        url,
        headers={"User-Agent": USER_AGENT, "Accept": "application/json"},
        method="GET",
    )
    attempts = 3
    for attempt in range(attempts):
        try:
            with urllib.request.urlopen(request, timeout=timeout) as response:
                payload = response.read().decode("utf-8", "replace")
        except urllib.error.HTTPError as exc:
            body = exc.read().decode("utf-8", "replace")
            if exc.code in (429, 500, 502, 503, 504) and attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise CLOBError(f"GET {url} failed", status=exc.code, body=_truncate(body)) from exc
        except (urllib.error.URLError, TimeoutError, OSError) as exc:
            reason = getattr(exc, "reason", exc)
            if attempt + 1 < attempts:
                time.sleep(0.5 * (attempt + 1))
                continue
            raise CLOBError(f"GET {url} failed", status=None, body=str(reason)) from exc

        try:
            return json.loads(payload)
        except json.JSONDecodeError as exc:
            raise CLOBError(
                f"GET {url} returned non-JSON", status=200, body=_truncate(payload)
            ) from exc
    raise CLOBError(f"GET {url} failed", status=None, body="retries exhausted")


def _query(base: str, path: str, params: dict[str, str]) -> str:
    url = f"{base}{path}?{urllib.parse.urlencode(params)}"
    return url


def _as_float(payload: dict[str, Any], key: str, what: str) -> float:
    try:
        return float(payload[key])
    except (KeyError, TypeError, ValueError) as exc:
        raise CLOBError(
            f"{what} response is missing a numeric {key!r}", status=200, body=str(payload)[:600]
        ) from exc


def get_server_time(timeout: float = DEFAULT_TIMEOUT) -> int:
    """Current CLOB server time as a Unix epoch second."""
    payload = _request_json(f"{CLOB_BASE}/time", timeout=timeout)
    try:
        return int(payload)
    except (TypeError, ValueError) as exc:
        raise CLOBError(
            "server time is not an integer", status=200, body=str(payload)[:600]
        ) from exc


def get_market(condition_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Market object for ``condition_id``, cached in process for 60 seconds."""
    now = time.monotonic()
    cached = _market_cache.get(condition_id)
    if cached is not None and now - cached[0] < _MARKET_CACHE_TTL:
        return cached[1]

    market = _request_json(f"{CLOB_BASE}/markets/{condition_id}", timeout=timeout)
    if not isinstance(market, dict):
        raise CLOBError(
            f"market {condition_id} returned a non-object", status=200, body=str(market)[:600]
        )
    _market_cache[condition_id] = (now, market)
    return market


def get_book(token_id: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any]:
    """Order book for a token id."""
    book = _request_json(
        _query(CLOB_BASE, "/book", {"token_id": token_id}), timeout=timeout
    )
    if not isinstance(book, dict):
        raise CLOBError(
            f"book {token_id} returned a non-object", status=200, body=str(book)[:600]
        )
    return book


def get_midpoint(token_id: str, timeout: float = DEFAULT_TIMEOUT) -> float:
    """Midpoint price for a token id, in dollars."""
    payload = _request_json(
        _query(CLOB_BASE, "/midpoint", {"token_id": token_id}), timeout=timeout
    )
    return _as_float(payload, "mid", "midpoint")


def get_tick_size(token_id: str, timeout: float = DEFAULT_TIMEOUT) -> str:
    """Minimum price tick for a token id, as a decimal string."""
    payload = _request_json(
        _query(CLOB_BASE, "/tick-size", {"token_id": token_id}), timeout=timeout
    )
    try:
        return str(payload["minimum_tick_size"])
    except (KeyError, TypeError) as exc:
        raise CLOBError(
            "tick size response is missing 'minimum_tick_size'",
            status=200,
            body=str(payload)[:600],
        ) from exc


def get_fee_rate_bps(token_id: str, timeout: float = DEFAULT_TIMEOUT) -> int:
    """Fee rate for a token id in basis points."""
    payload = _request_json(
        _query(CLOB_BASE, "/fee-rate", {"token_id": token_id}), timeout=timeout
    )
    try:
        return int(payload["base_fee"])
    except (KeyError, TypeError, ValueError) as exc:
        raise CLOBError(
            "fee rate response is missing 'base_fee'", status=200, body=str(payload)[:600]
        ) from exc


def list_reward_markets(
    page_size: int = 500, timeout: float = BULK_TIMEOUT
) -> list[dict[str, Any]]:
    """Every market that currently carries a reward allocation.

    Pages ``/rewards/markets/current`` with the ``next_cursor`` parameter until
    the cursor terminates with ``LTE=``.
    """
    rows: list[dict[str, Any]] = []
    cursor: str | None = None
    seen_cursors: set[str] = set()

    while True:
        params = {"limit": str(page_size)}
        if cursor is not None:
            params["next_cursor"] = cursor
        payload = _request_json(
            _query(CLOB_BASE, "/rewards/markets/current", params), timeout=timeout
        )
        page = payload.get("data") or []
        if not isinstance(page, list):
            raise CLOBError(
                "rewards page data is not a list", status=200, body=str(payload)[:600]
            )
        rows.extend(row for row in page if isinstance(row, dict))

        next_cursor = payload.get("next_cursor")
        if not next_cursor or next_cursor == "LTE=" or next_cursor in seen_cursors:
            break
        seen_cursors.add(next_cursor)
        cursor = next_cursor

    return rows


def get_gamma_market(slug: str, timeout: float = DEFAULT_TIMEOUT) -> dict[str, Any] | None:
    """Gamma market object for an exact slug, or ``None`` when there is none."""
    payload = _request_json(
        _query(GAMMA_BASE, "/markets", {"slug": slug}), timeout=timeout
    )
    if isinstance(payload, list):
        return payload[0] if payload else None
    if isinstance(payload, dict):
        return payload
    return None


def list_reward_markets_with_competition(
    page_size: int = 500, timeout: float = BULK_TIMEOUT
) -> list[dict[str, Any]]:
    """Every reward market, with the venue's own competition score.

    ``/rewards/markets/multi`` carries everything the estimator needs:
    the pool settings (``rewards_min_size``, ``rewards_max_spread``), the
    daily rate in ``rewards_config``, and ``market_competitiveness``, which
    is the sum of every other maker's ``Q_min`` for the market. That last
    number is the exact denominator the reward methodology divides by, so
    the share estimate does not have to be rebuilt from the book.

    The list is sorted by daily rate descending. One page of 500 covers every
    market paying at least 50 pUSD a day, and the markets a small maker can
    qualify for all pay less than that, so one page is enough and a full
    sweep of the venue's 8,000-odd markets is not needed.
    """
    params = {"page_size": str(page_size), "order_by": "rate_per_day", "position": "DESC"}
    payload = _request_json(
        _query(CLOB_BASE, "/rewards/markets/multi", params), timeout=timeout
    )
    rows: list[dict[str, Any]] = []
    for row in payload.get("data") or []:
        if isinstance(row, dict):
            rows.append(row)
    return rows


def list_updown_markets(
    asset: str, duration: str, timeout: float = DEFAULT_TIMEOUT
) -> list[dict[str, Any]]:
    """Crypto up/down markets for ``asset`` over the current and next two windows.

    ``duration`` is ``"5m"`` or ``"15m"``. The slug pattern is
    ``{asset}-updown-{duration}-{window_start_epoch}``.
    """
    if duration not in UPDOWN_DURATIONS:
        raise ValueError(f"unsupported duration {duration!r}, expected one of {sorted(UPDOWN_DURATIONS)}")

    seconds = UPDOWN_DURATIONS[duration]
    now = get_server_time(timeout=timeout)
    window_start = (now // seconds) * seconds

    markets: list[dict[str, Any]] = []
    for offset in range(3):
        slug = f"{asset}-updown-{duration}-{window_start + offset * seconds}"
        market = get_gamma_market(slug, timeout=timeout)
        if market is not None:
            markets.append(market)
    return markets
