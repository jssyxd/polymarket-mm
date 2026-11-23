"""Position reads: on-chain pUSD balances and off-chain CLOB/Data API holdings.

`read_positions` uses the read-only L2 key, so it works without the owner
private key. It never raises on a missing field: every lookup returns a
default so a partial API response still yields a usable dict.

`read_onchain_pUSD` reads the ERC-20 balance of an address over a Polygon
RPC. This module uses the standard library only.
"""

from __future__ import annotations

import json
import urllib.error
import urllib.parse
import urllib.request
from typing import Any, Optional

from .config import ExecutionConfig

#: pUSD is the current collateral for every Polymarket trade.
PUSD_ADDRESS = "0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB"
PUSD_DECIMALS = 6

#: drpc and polygon-rpc.com answer 403 from this network. 1rpc.io works.
DEFAULT_RPC_URL = "https://1rpc.io/matic"

DEFAULT_DATA_API = "https://data-api.polymarket.com"

#: `balanceOf(address)` selector.
BALANCE_OF_SELECTOR = "70a08231"

HTTP_TIMEOUT_SECONDS = 15.0


def _get_json(url: str, headers: Optional[dict[str, str]] = None) -> Any:
    request = urllib.request.Request(url, headers=headers or {})
    with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
        body = response.read().decode("utf-8")
    if not body:
        return {}
    return json.loads(body)


def _l2_headers(config: ExecutionConfig, method: str, path: str, body: str = "") -> dict[str, str]:
    """L2 auth headers for the read endpoints.

    The server binds the API key to one address and rejects any other value
    with 401. `POLY_ADDRESS` names that address.
    """
    import base64
    import hashlib
    import hmac
    import time

    timestamp = str(int(time.time()))
    message = timestamp + method + path
    if body:
        message += body
    secret = base64.urlsafe_b64decode(config.api_secret)
    digest = hmac.new(secret, message.encode("utf-8"), hashlib.sha256).digest()
    signature = base64.urlsafe_b64encode(digest).decode("utf-8")
    return {
        "POLY_ADDRESS": config.address or config.funder or "",
        "POLY_SIGNATURE": signature,
        "POLY_TIMESTAMP": timestamp,
        "POLY_API_KEY": config.api_key,
        "POLY_PASSPHRASE": config.api_passphrase,
        "Accept": "*/*",
        "User-Agent": "pmm-execution/1",
    }


def _balance_allowance(
    config: ExecutionConfig, asset_type: str, token_id: Optional[str] = None
) -> dict:
    """Read `GET /balance-allowance`. Returns {} on any failure."""
    path = "/balance-allowance"
    params = {
        "asset_type": asset_type,
        "signature_type": str(config.signature_type if config.signature_type is not None else 1),
    }
    if token_id:
        params["token_id"] = str(token_id)
    url = f"{config.host}{path}?{urllib.parse.urlencode(params)}"
    try:
        payload = _get_json(url, _l2_headers(config, "GET", path))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return {}
    return payload if isinstance(payload, dict) else {}


def _api_positions(config: ExecutionConfig, condition_id: Optional[str]) -> list[dict]:
    """Read the Data API v2 positions for the account."""
    address = config.address or config.funder or ""
    if not address:
        return []
    params = {"user": address, "limit": "100"}
    if condition_id:
        params["condition_id"] = str(condition_id)
    url = f"{DEFAULT_DATA_API}/v2/positions?{urllib.parse.urlencode(params)}"
    try:
        payload = _get_json(url, {"Accept": "*/*", "User-Agent": "pmm-execution/1"})
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return []
    if isinstance(payload, dict):
        data = payload.get("data")
    else:
        data = payload
    if not isinstance(data, list):
        return []
    return [row for row in data if isinstance(row, dict)]


def read_positions(
    config: ExecutionConfig, condition_id: Optional[str] = None, token_ids: Optional[list[str]] = None
) -> dict:
    """Read the account's collateral balance, allowances and API positions.

    Works with the read-only L2 key. A missing field yields an empty value
    rather than an exception.
    """
    token_ids = list(token_ids or [])
    collateral = _balance_allowance(config, "COLLATERAL")

    balances: dict[str, float] = {}
    raw_balance = collateral.get("balance")
    if raw_balance is not None:
        try:
            balances["COLLATERAL"] = float(raw_balance) / (10 ** PUSD_DECIMALS)
        except (TypeError, ValueError):
            balances["COLLATERAL"] = 0.0
    else:
        balances["COLLATERAL"] = 0.0

    for token_id in token_ids:
        payload = _balance_allowance(config, "COLLATERAL", token_id)
        raw = payload.get("balance")
        try:
            balances[str(token_id)] = float(raw) / (10 ** PUSD_DECIMALS) if raw is not None else 0.0
        except (TypeError, ValueError):
            balances[str(token_id)] = 0.0

    allowances = collateral.get("allowances")
    if not isinstance(allowances, dict):
        allowances = {}

    return {
        "balance": balances.get("COLLATERAL", 0.0),
        "balances": balances,
        "allowances": allowances,
        "api_positions": _api_positions(config, condition_id),
    }


def read_onchain_pUSD(address: str, rpc_url: str = DEFAULT_RPC_URL) -> float:
    """Read the pUSD balance of an address over a Polygon RPC.

    Returns 0.0 when the call fails. Uses the standard library only.
    """
    payload = {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "eth_call",
        "params": [
            {
                "to": PUSD_ADDRESS,
                "data": "0x" + BALANCE_OF_SELECTOR + address.lower().replace("0x", "").rjust(64, "0"),
            },
            "latest",
        ],
    }
    request = urllib.request.Request(
        rpc_url,
        data=json.dumps(payload).encode("utf-8"),
        headers={"Content-Type": "application/json", "User-Agent": "pmm-execution/1"},
    )
    try:
        with urllib.request.urlopen(request, timeout=HTTP_TIMEOUT_SECONDS) as response:
            result = json.loads(response.read().decode("utf-8"))
    except (urllib.error.URLError, urllib.error.HTTPError, ValueError, OSError):
        return 0.0
    raw = result.get("result") if isinstance(result, dict) else None
    if not raw or not isinstance(raw, str):
        return 0.0
    try:
        return int(raw, 16) / (10 ** PUSD_DECIMALS)
    except ValueError:
        return 0.0
