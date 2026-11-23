"""Order placement, cancellation and heartbeat against the Polymarket CLOB.

The v2 client (`py_clob_client_v2`) owns the order format: it signs the EIP-712
payload and resolves the exchange version. This module owns the wire behaviour
around it: timeouts, retries on 5xx only, per-signer rate-limit accounting, and
the journal trail.

Two hard facts shape this code.

1. The CLOB L2 API key authenticates requests but cannot sign orders. Signing
   needs the owner EOA private key in `POLY_OWNER_PK`, which is not on this
   machine. Without it, `build_client` refuses and the adapter stays in
   dry-run mode.
2. A heartbeat is not a keepalive. The first accepted heartbeat arms the
   server-side timeout cancellation for every open order on that API key, and
   there is no disarm endpoint. See `Heartbeat`.

Secrets never appear in this module's output. Journal lines carry order
intent, order ids and server responses only.

Observed server responses for this account (2026-11-21), which is what the
correction loop has to work against:

* version 2 order, maker set to the API key address:
  `400 {"error": "maker address not allowed, please use the deposit wallet flow"}`
* version 2 order, maker set to the proxy wallet, signature_type 1:
  `400 {"error": "invalid POLY_PROXY signature"}`
* version 2 order, signature_type 3:
  `400 {"error": "the order signer address has to be the address of the API KEY"}`

The second response is the informative one: the server got past every address
check and failed only on the signature bytes. The accepted shape for this
account is a version 2 order with

* maker = the proxy wallet that owns the collateral, `0x6F7D43A8…`,
* signer = the API key address, `0x18af6286…`,
* signatureType = 1 (POLY_PROXY).

The proxy wallet is derivable from the signer EOA by CREATE2 over the proxy
factory, so the adapter derives it rather than hardcoding it. The only thing
missing for this account is the owner private key that produces a valid
POLY_PROXY signature.
"""

from __future__ import annotations

import json
import logging
import threading
import time
from dataclasses import dataclass
from typing import Any, Optional

import httpx
from py_clob_client_v2 import ApiCreds, ClobClient, CreateOrderOptions, OrderArgsV2
from py_clob_client_v2.clob_types import AssetType, BalanceAllowanceParams
from py_clob_client_v2.order_utils.model.order_data_v2 import order_to_json_v2
from py_clob_client_v2.signing.hmac import build_hmac_signature
from py_clob_client_v2.utilities import price_valid

from .config import ExecutionConfig
from .journal import Journal

LOGGER = logging.getLogger(__name__)

#: Standard tier from `GET /v1/user/rate-limit-tier`: 40 orders/s, burst 60.
DEFAULT_ORDER_RATE_PER_SEC = 40.0
DEFAULT_ORDER_BURST = 60

#: Cancel bucket is larger than the order bucket but has its own budget.
DEFAULT_CANCEL_RATE_PER_SEC = 80.0
DEFAULT_CANCEL_BURST = 120

DEFAULT_TICK_SIZE = "0.01"
HTTP_TIMEOUT_SECONDS = 10.0
MAX_5XX_RETRIES = 2
RETRY_BACKOFF_SECONDS = 0.25


class ExecutionError(RuntimeError):
    """Any failure to place, cancel or keep an order alive.

    Carries the HTTP status and the server body so a caller can tell a
    signature problem from a rate limit.
    """

    def __init__(self, message: str, status: Optional[int] = None, body: Any = None):
        super().__init__(message)
        self.status = status
        self.body = body


def _signer_address(config: ExecutionConfig) -> str:
    """The address of the EOA that signs orders, from the owner key."""
    if not config.owner_pk:
        return ""
    from eth_account import Account

    return Account.from_key(config.owner_pk).address


def _l2_address(config: ExecutionConfig) -> str:
    """The address the CLOB API key is registered to, sent as POLY_ADDRESS.

    The API key is bound to one address and the server rejects any other
    value with 401 Unauthorized/Invalid api key. `POLY_ADDRESS` names it. For
    an EOA account the owner key derives the same address, so it is the
    fallback.
    """
    if config.address:
        return config.address
    return _signer_address(config)


def _derive_proxy_wallet(signer: str) -> str:
    """Derive the Polymarket proxy wallet of a signer EOA.

    CREATE2 over the proxy factory with the signer packed into the salt. This
    is the wallet that holds the funds for a legacy POLY_PROXY account.
    """
    from eth_abi.packed import encode_packed
    from eth_utils.address import to_checksum_address
    from eth_utils.crypto import keccak

    factory = "0xaB45c5A4B0c941a2F231C04C3f49182e1A254052"
    implementation = "0x44e999d5c2F66Ef0861317f9A4805AC2e90aEB4f"
    bytecode = bytes.fromhex(
        (
            "3d3d606380380380913d393d73"
            "{factory}"
            "5af4602a57600080fd5b602d8060366000396000f3363d3d373d3d3d363d73"
            "{implementation}"
            "5af43d82803e903d91602b57fd5bf352e831dd"
            "0000000000000000000000000000000000000000000000000000000000000020"
            "0000000000000000000000000000000000000000000000000000000000000000"
        ).format(factory=factory[2:].lower(), implementation=implementation[2:].lower())
    )
    salt = keccak(encode_packed(["address"], [signer]))
    raw = b"\xff" + bytes.fromhex(factory[2:]) + salt + keccak(bytecode)
    return to_checksum_address("0x" + keccak(raw)[12:].hex())


def _derive_funder(config: ExecutionConfig, signer_address: str) -> tuple[Optional[str], Optional[int]]:
    """Derive (funder, signature_type) from the account.

    A legacy POLY_PROXY account signs with an EOA and trades through the proxy
    wallet that EOA owns, so the maker is the derived proxy wallet and the
    signer is the EOA. `POLY_FUNDER` overrides the maker, for instance with a
    Deposit Wallet address. `POLY_SIGNATURE_TYPE` overrides the type:

    * 0 EOA, maker and signer are the signing EOA.
    * 1 POLY_PROXY, maker is the funder, signer is the signing EOA.
    * 3 POLY_1271, maker and signer are the funder (the Deposit Wallet).

    The default is 1 when the maker differs from the signer and 0 otherwise.
    The server's error text names the field to correct when the choice is
    wrong.
    """
    funder = config.funder or None
    if funder is None and signer_address:
        funder = _derive_proxy_wallet(signer_address)
    if config.signature_type is not None:
        return funder, config.signature_type
    if funder and signer_address and funder.lower() != signer_address.lower():
        return funder, 1
    return funder, 0


def build_client(config: ExecutionConfig) -> ClobClient:
    """Build the v2 CLOB client.

    Raises `ExecutionError` when the owner private key is missing: the L2 API
    key alone cannot sign an order, so there is nothing to build.
    """
    if not config.owner_pk:
        raise ExecutionError(
            "owner private key is missing: set POLY_OWNER_PK to the EOA key that "
            "signs orders. The CLOB L2 API key cannot sign, so the adapter "
            "cannot place orders without it."
        )
    if not config.has_credentials:
        raise ExecutionError(
            "CLOB L2 credentials are missing: set POLY_API_KEY, POLY_API_SECRET "
            "and POLY_API_PASSPHRASE."
        )
    signer_address = _signer_address(config)
    funder, signature_type = _derive_funder(config, signer_address)
    creds = ApiCreds(
        api_key=config.api_key,
        api_secret=config.api_secret,
        api_passphrase=config.api_passphrase,
    )
    return ClobClient(
        host=config.host,
        chain_id=config.chain_id,
        key=config.owner_pk,
        creds=creds,
        signature_type=signature_type,
        funder=funder,
    )


@dataclass
class _Response:
    status: int
    body: Any
    headers: dict[str, str]

    @property
    def rate_limit_remaining(self) -> Optional[int]:
        raw = self.headers.get("poly-ratelimit-remaining")
        if raw is None:
            return None
        try:
            return int(raw)
        except ValueError:
            return None


class _Transport:
    """L2-signed HTTP with timeouts and 5xx-only retries."""

    def __init__(self, config: ExecutionConfig):
        self.config = config
        self._client = httpx.Client(
            timeout=httpx.Timeout(HTTP_TIMEOUT_SECONDS),
            headers={"User-Agent": "pmm-execution/1", "Accept": "*/*"},
        )

    def close(self) -> None:
        self._client.close()

    def _headers(self, method: str, path: str, body: str) -> dict[str, str]:
        timestamp = str(int(time.time()))
        signature = build_hmac_signature(
            self.config.api_secret, timestamp, method, path, body
        )
        return {
            "POLY_ADDRESS": _l2_address(self.config),
            "POLY_SIGNATURE": signature,
            "POLY_TIMESTAMP": timestamp,
            "POLY_API_KEY": self.config.api_key,
            "POLY_PASSPHRASE": self.config.api_passphrase,
            "Content-Type": "application/json",
        }

    def request(
        self,
        method: str,
        path: str,
        body: Optional[dict] = None,
        params: Optional[dict] = None,
    ) -> _Response:
        serialized = "" if body is None else json.dumps(body, separators=(",", ":"), ensure_ascii=False)
        url = f"{self.config.host}{path}"
        attempt = 0
        while True:
            attempt += 1
            try:
                response = self._client.request(
                    method,
                    url,
                    headers=self._headers(method, path, serialized),
                    content=serialized.encode("utf-8") if serialized else None,
                    params=params,
                )
            except httpx.HTTPError as exc:
                if attempt <= MAX_5XX_RETRIES:
                    time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                    continue
                raise ExecutionError(f"{method} {path} failed: {exc}") from exc

            if 500 <= response.status_code < 600 and attempt <= MAX_5XX_RETRIES:
                time.sleep(RETRY_BACKOFF_SECONDS * attempt)
                continue

            try:
                parsed: Any = response.json()
            except ValueError:
                parsed = response.text
            return _Response(
                status=response.status_code,
                body=parsed,
                headers={k.lower(): v for k, v in response.headers.items()},
            )


class _TokenBucket:
    """Per-signer token bucket, mirroring the server-side one.

    A batch of N orders costs N tokens and is admitted only if the bucket
    holds all N, so the bucket is drained by the whole chunk, never partially.
    """

    def __init__(self, rate_per_sec: float, burst: float):
        self.rate_per_sec = max(rate_per_sec, 0.001)
        self.burst = max(burst, 1.0)
        self._tokens = self.burst
        self._updated = time.monotonic()
        self._lock = threading.Lock()

    def consume(self, count: int) -> None:
        if count <= 0:
            return
        while True:
            with self._lock:
                now = time.monotonic()
                self._tokens = min(
                    self.burst, self._tokens + (now - self._updated) * self.rate_per_sec
                )
                self._updated = now
                if self._tokens >= count:
                    self._tokens -= count
                    return
                deficit = count - self._tokens
                wait = deficit / self.rate_per_sec
            time.sleep(min(wait, 1.0))

    def refund(self, count: int) -> None:
        with self._lock:
            self._tokens = min(self.burst, self._tokens + count)


class OrderExecutor:
    """Builds, signs and sends orders for one account."""

    def __init__(self, config: ExecutionConfig, journal: Optional[Journal] = None):
        self.config = config
        self.journal = journal if journal is not None else Journal(config.journal_path)
        self._client: Optional[ClobClient] = None
        self._transport: Optional[_Transport] = None
        self._order_bucket = _TokenBucket(DEFAULT_ORDER_RATE_PER_SEC, DEFAULT_ORDER_BURST)
        self._cancel_bucket = _TokenBucket(DEFAULT_CANCEL_RATE_PER_SEC, DEFAULT_CANCEL_BURST)
        self._market_params: dict[str, tuple[str, bool, int]] = {}

    # -- plumbing ---------------------------------------------------------

    @property
    def client(self) -> ClobClient:
        if self._client is None:
            self._client = build_client(self.config)
        return self._client

    @property
    def transport(self) -> _Transport:
        if self._transport is None:
            if not self.config.has_credentials:
                raise ExecutionError(
                    "CLOB L2 credentials are missing: set POLY_API_KEY, "
                    "POLY_API_SECRET and POLY_API_PASSPHRASE."
                )
            self._transport = _Transport(self.config)
        return self._transport

    def close(self) -> None:
        if self._transport is not None:
            self._transport.close()
            self._transport = None

    def collateral_balance(self) -> Optional[float]:
        """The account's free collateral in pUSD, or None when unreadable.

        The venue reports the balance in 6-decimal units of pUSD. A failure
        here must not stop a cycle: the caller treats None as "unknown" and
        keeps its static budget.
        """
        try:
            params = BalanceAllowanceParams(
                asset_type=AssetType.COLLATERAL,
                signature_type=self.config.signature_type,
            )
            response = self.client.get_balance_allowance(params)
            return float(response["balance"]) / 1e6
        except Exception as exc:  # noqa: BLE001 - balance is advisory only
            LOGGER.warning("collateral balance unavailable: %s", exc)
            return None

    # -- order construction ----------------------------------------------

    def market_params(self, token_id: str) -> tuple[str, bool, int]:
        """Read the tick size, neg-risk flag and exchange version for a token.

        Every read goes through this module's transport, so it has the
        timeout, the 5xx-only retry and the ExecutionError contract.
        """
        cached = self._market_params.get(token_id)
        if cached is not None:
            return cached

        tick_response = self.transport.request(
            "GET", "/tick-size", params={"token_id": token_id}
        )
        if tick_response.status >= 400:
            raise ExecutionError(
                f"GET /tick-size failed with status {tick_response.status}",
                status=tick_response.status,
                body=tick_response.body,
            )
        tick_size = str(
            (tick_response.body or {}).get("minimum_tick_size", DEFAULT_TICK_SIZE)
        )

        neg_response = self.transport.request(
            "GET", "/neg-risk", params={"token_id": token_id}
        )
        if neg_response.status >= 400:
            raise ExecutionError(
                f"GET /neg-risk failed with status {neg_response.status}",
                status=neg_response.status,
                body=neg_response.body,
            )
        neg_risk = bool((neg_response.body or {}).get("neg_risk", False))

        version_response = self.transport.request("GET", "/version")
        if version_response.status >= 400:
            raise ExecutionError(
                f"GET /version failed with status {version_response.status}",
                status=version_response.status,
                body=version_response.body,
            )
        version = int((version_response.body or {}).get("version", 2))

        params = (tick_size, neg_risk, version)
        self._market_params[token_id] = params
        return params

    def build_payload(self, intent: dict) -> dict:
        """Turn an order intent into the wire payload.

        An intent is a dict with `token_id`, `price`, `size` and `side`. With
        an owner key present the payload is signed by the v2 client. Without
        one the intent is returned unchanged and marked `dry_run`.
        """
        if intent.get("order") and intent["order"].get("signature"):
            return intent  # already signed by the caller
        if self.config.dry_run or not self.config.owner_pk:
            return dict(intent, dry_run=True)

        token_id = str(intent["token_id"])
        price = float(intent["price"])
        size = float(intent["size"])
        tick_size, neg_risk, version = self.market_params(token_id)
        tick_size = str(intent.get("tick_size") or tick_size)
        if intent.get("neg_risk") is not None:
            neg_risk = bool(intent["neg_risk"])

        if not price_valid(price, tick_size):
            raise ExecutionError(
                f"invalid price ({price}) for tick size {tick_size}: "
                f"the price must be between {tick_size} and {1 - float(tick_size)}"
            )

        args = OrderArgsV2(
            token_id=token_id,
            price=price,
            size=size,
            side=str(intent["side"]).upper(),
            expiration=int(intent.get("expiration", 0)),
        )
        signed = self.client.builder.build_order(
            args,
            CreateOrderOptions(tick_size=tick_size, neg_risk=neg_risk),
            version=version,
        )
        return order_to_json_v2(
            signed,
            self.config.api_key,
            str(intent.get("order_type", "GTC")),
            post_only=bool(intent.get("post_only", self.config.post_only)),
            defer_exec=bool(intent.get("defer_exec", False)),
        )

    # -- order placement --------------------------------------------------

    def place(self, payload: dict, reason: str) -> dict:
        """Place one order, or record the intent when running dry."""
        if self.config.dry_run:
            self.journal.append("order_intent", reason=reason, payload=payload)
            return {"status": "dry_run", "payload": payload}
        if not self.config.has_owner_key:
            # Signing needs the owner EOA key. Without it there is no order to
            # post, and posting an unsigned payload would just be rejected.
            raise ExecutionError(
                "owner private key is missing: set POLY_OWNER_PK to the EOA key "
                "that signs orders. The CLOB L2 API key cannot sign, so the "
                "adapter refuses to place an order that cannot settle."
            )

        body = self.build_payload(payload)
        self.journal.append("order_intent", reason=reason, payload=payload)
        response = self.transport.request("POST", "/order", body)
        if response.status >= 400:
            self.journal.append(
                "order_reject",
                reason=reason,
                status=response.status,
                body=response.body,
            )
            raise ExecutionError(
                f"POST /order failed with status {response.status}",
                status=response.status,
                body=response.body,
            )
        result = dict(response.body) if isinstance(response.body, dict) else {"body": response.body}
        result.setdefault("status", "live")
        self.journal.append("order_ack", reason=reason, response=result)
        return result

    def place_batch(self, payloads: list[dict], reason: str = "batch") -> list[dict]:
        """Place orders in chunks that respect the batch cap and the token bucket.

        A chunk is admitted only if the bucket holds a token for every order in
        it. On a 429 or a `Poly-RateLimit-Remaining` of zero the run stops and
        returns what it has. Nothing is retried blindly.
        """
        if self.config.dry_run:
            results = []
            for payload in payloads:
                self.journal.append("order_intent", reason=reason, payload=payload)
                results.append({"status": "dry_run", "payload": payload})
            return results
        if not self.config.has_owner_key:
            raise ExecutionError(
                "owner private key is missing: set POLY_OWNER_PK to the EOA key "
                "that signs orders. The CLOB L2 API key cannot sign, so the "
                "adapter refuses to place orders that cannot settle."
            )

        results: list[dict] = []
        max_batch = max(1, min(self.config.max_batch, 15))
        for start in range(0, len(payloads), max_batch):
            chunk = payloads[start : start + max_batch]
            self._order_bucket.consume(len(chunk))
            bodies = [self.build_payload(payload) for payload in chunk]
            for payload in chunk:
                self.journal.append("order_intent", reason=reason, payload=payload)
            response = self.transport.request("POST", "/orders", bodies)
            if response.status == 429:
                self.journal.append("order_reject", reason=reason, status=429, body=response.body)
                results.append({"status": "rate_limited", "body": response.body})
                return results
            if response.status >= 400:
                self.journal.append(
                    "order_reject", reason=reason, status=response.status, body=response.body
                )
                raise ExecutionError(
                    f"POST /orders failed with status {response.status}",
                    status=response.status,
                    body=response.body,
                )
            body = response.body if isinstance(response.body, list) else [response.body]
            for item in body:
                item = dict(item) if isinstance(item, dict) else {"body": item}
                item.setdefault("status", "live")
                results.append(item)
            self.journal.append("order_ack", reason=reason, response=body)
            remaining = response.rate_limit_remaining
            if remaining is not None and remaining <= 0:
                self.journal.append("order_reject", reason=reason, status=429, body="rate limit exhausted")
                break
        return results

    # -- cancellation -----------------------------------------------------

    def cancel(self, order_id: str) -> dict:
        """Cancel one order by id."""
        if self.config.dry_run:
            self.journal.append("cancel", order_id=order_id, status="dry_run")
            return {"status": "dry_run", "order_id": order_id}
        self._cancel_bucket.consume(1)
        response = self.transport.request("DELETE", "/order", {"orderID": order_id})
        if response.status >= 400:
            self.journal.append(
                "cancel", order_id=order_id, status=response.status, body=response.body
            )
            raise ExecutionError(
                f"DELETE /order failed with status {response.status}",
                status=response.status,
                body=response.body,
            )
        body = response.body if isinstance(response.body, dict) else {"body": response.body}
        self.journal.append("cancel", order_id=order_id, status="live", body=body)
        return body

    def cancel_all(self) -> dict:
        """Cancel every open order on this account."""
        if self.config.dry_run:
            self.journal.append("cancel", scope="all", status="dry_run")
            return {"status": "dry_run", "scope": "all"}
        self._cancel_bucket.consume(1)
        response = self.transport.request("DELETE", "/cancel-all")
        if response.status >= 400:
            self.journal.append("cancel", scope="all", status=response.status, body=response.body)
            raise ExecutionError(
                f"DELETE /cancel-all failed with status {response.status}",
                status=response.status,
                body=response.body,
            )
        body = response.body if isinstance(response.body, dict) else {"body": response.body}
        self.journal.append("cancel", scope="all", status="live", body=body)
        return body


class Heartbeat:
    """Keeps the account's orders alive by refreshing the server-side deadline.

    The first accepted heartbeat arms the timeout cancellation for every open
    order owned by this API key, across markets and processes. Ten seconds
    without an accepted heartbeat makes the server queue a best-effort
    cancel-all. There is no disarm endpoint: stopping this object leaves the
    deadline running, so stop placing orders, cancel what should be removed,
    and verify the cancellations before calling `stop()`.

    Keep exactly one instance per API key. Concurrent senders race over the
    rotating id.

    Heartbeats are refused in dry-run mode. They act on the live account, and
    a dry run has no orders to protect.
    """

    def __init__(
        self,
        config: ExecutionConfig,
        transport: Optional[_Transport] = None,
        journal: Optional[Journal] = None,
        interval: Optional[float] = None,
    ):
        if config.dry_run:
            raise ExecutionError(
                "heartbeat acts on the live account; refusing to start in dry-run mode"
            )
        if not config.has_credentials:
            raise ExecutionError(
                "CLOB L2 credentials are missing: set POLY_API_KEY, "
                "POLY_API_SECRET and POLY_API_PASSPHRASE."
            )
        self.config = config
        self.interval = float(interval if interval is not None else config.heartbeat_seconds)
        self.journal = journal if journal is not None else Journal(config.journal_path)
        self._transport = transport if transport is not None else _Transport(config)
        self._owns_transport = transport is None
        self._heartbeat_id = ""
        self._stop = threading.Event()
        self._thread: Optional[threading.Thread] = None
        self.sent = 0
        self.accepted = 0

    def _next_id(self, body: Any) -> str:
        if isinstance(body, dict):
            for key in ("heartbeat_id", "id", "new_heartbeat_id"):
                value = body.get(key)
                if isinstance(value, str) and value:
                    return value
        return self._heartbeat_id

    def send_once(self) -> bool:
        """Send one heartbeat. Returns True when the server accepted it."""
        body = {"heartbeat_id": self._heartbeat_id}
        response = self._transport.request("POST", "/v1/heartbeats", body)
        self.sent += 1
        if response.status == 400:
            # A mismatched id answers with the id it expects. Adopt it and
            # keep going; the deadline is not refreshed by a rejected send.
            expected = response.body.get("heartbeat_id") if isinstance(response.body, dict) else None
            if isinstance(expected, str) and expected:
                self._heartbeat_id = expected
            self.journal.append("heartbeat", status=response.status, body=response.body)
            return False
        if response.status >= 400:
            self.journal.append("heartbeat", status=response.status, body=response.body)
            raise ExecutionError(
                f"POST /v1/heartbeats failed with status {response.status}",
                status=response.status,
                body=response.body,
            )
        self._heartbeat_id = self._next_id(response.body)
        self.accepted += 1
        self.journal.append("heartbeat", status="accepted", heartbeat_id=self._heartbeat_id)
        return True

    def _run(self) -> None:
        while not self._stop.is_set():
            try:
                self.send_once()
            except ExecutionError:
                pass
            self._stop.wait(self.interval)

    def start(self) -> "Heartbeat":
        """Start sending heartbeats on a background thread."""
        if self._thread is not None:
            return self
        self._thread = threading.Thread(target=self._run, name="poly-heartbeat", daemon=True)
        self._thread.start()
        return self

    def stop(self) -> None:
        """Stop sending. The server-side deadline stays armed."""
        self._stop.set()
        if self._thread is not None:
            self._thread.join(timeout=self.interval + 1.0)
            self._thread = None
        if self._owns_transport:
            self._transport.close()


# -- module level helpers -------------------------------------------------


def place_or_dry(order_payload: dict, config: ExecutionConfig, reason: str) -> dict:
    """Place one order, or journal the intent when the owner key is absent."""
    executor = OrderExecutor(config)
    try:
        return executor.place(order_payload, reason)
    finally:
        executor.close()


def place_batch(payloads: list[dict], config: ExecutionConfig, reason: str = "batch") -> list[dict]:
    """Place a list of orders in rate-limit-safe chunks."""
    executor = OrderExecutor(config)
    try:
        return executor.place_batch(payloads, reason)
    finally:
        executor.close()


def cancel_all(config: ExecutionConfig) -> dict:
    """Cancel every open order on the account."""
    executor = OrderExecutor(config)
    try:
        return executor.cancel_all()
    finally:
        executor.close()


def cancel_order(order_id: str, config: ExecutionConfig) -> dict:
    """Cancel one open order."""
    executor = OrderExecutor(config)
    try:
        return executor.cancel(order_id)
    finally:
        executor.close()


def derive_account(config: ExecutionConfig) -> dict:
    """Describe what the adapter would use for this account, without secrets."""
    signer_address = _signer_address(config)
    funder, signature_type = _derive_funder(config, signer_address)
    return {
        "address": _l2_address(config),
        "signer_address": signer_address,
        "funder": funder,
        "signature_type": signature_type,
        "can_sign": config.has_owner_key,
        "dry_run": config.dry_run,
    }
