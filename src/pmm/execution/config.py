"""Execution configuration for the Polymarket adapter.

Every credential is read from the environment. Nothing is hardcoded here and
nothing in this module prints a secret: `ExecutionConfig.__repr__` is the
redacted view, so a stray `print(config)` cannot leak a key.

The account's CLOB L2 API key authenticates reads and signs L2 requests, but it
cannot sign orders. Order signing needs the owner EOA private key
(`POLY_OWNER_PK`, the key behind the account signer 0x18af...). Without it the
adapter refuses to place orders and runs in dry-run mode.

The funded account is a legacy POLY_PROXY wallet: `POLY_FUNDER` is the proxy
wallet 0x6F7D43A8... and `POLY_SIGNATURE_TYPE` is 1. Verified live on
2026-11-23: post-only orders place and cancel on the v2 order envelope with
maker = proxy wallet and signer = 0x18af.
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Mapping, Optional

DEFAULT_HOST = "https://clob.polymarket.com"
DEFAULT_CHAIN_ID = 137
DEFAULT_HEARTBEAT_SECONDS = 5
DEFAULT_MAX_BATCH = 15
DEFAULT_ORDER_TICKER_SECONDS = 1.0
DEFAULT_JOURNAL_PATH = "~/.pmm/journal"

# The CLOB rejects a batch larger than this, so the configured batch size is
# clamped to it rather than sent as-is.
CLOB_MAX_BATCH = 15

#: Fields whose value must never reach a log line, a journal line, or a repr.
SECRET_FIELDS = (
    "api_key",
    "api_secret",
    "api_passphrase",
    "owner_pk",
    "relayer_api_key",
)

_TRUE = {"1", "true", "yes", "on"}
_FALSE = {"0", "false", "no", "off"}


def _as_bool(raw: Optional[str], default: bool) -> bool:
    if raw is None:
        return default
    value = raw.strip().lower()
    if value in _TRUE:
        return True
    if value in _FALSE:
        return False
    raise ValueError(f"expected a boolean flag, got {raw!r}")


def _as_int(raw: Optional[str], default: Optional[int]) -> Optional[int]:
    if raw is None or raw.strip() == "":
        return default
    return int(raw)


def _as_float(raw: Optional[str], default: Optional[float]) -> Optional[float]:
    if raw is None or raw.strip() == "":
        return default
    return float(raw)


def _load_env_file(path: str) -> dict[str, str]:
    """Parse a `KEY=VALUE` file into a dict. Missing file yields an empty dict."""
    values: dict[str, str] = {}
    file_path = Path(path).expanduser()
    if not file_path.is_file():
        return values
    for line in file_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, value = line.partition("=")
        value = value.strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in "\"'":
            value = value[1:-1]
        values[key.strip()] = value
    return values


@dataclass(repr=False)
class ExecutionConfig:
    """Everything the execution adapter needs to talk to the CLOB."""

    host: str = DEFAULT_HOST
    chain_id: int = DEFAULT_CHAIN_ID
    api_key: str = ""
    api_secret: str = ""
    api_passphrase: str = ""
    owner_pk: str = ""
    relayer_api_key: str = ""
    relayer_address: str = ""
    funder: str = ""
    signature_type: Optional[int] = None
    dry_run: bool = True
    heartbeat_seconds: int = DEFAULT_HEARTBEAT_SECONDS
    post_only: bool = True
    harvest_enabled: bool = False
    repair_enabled: bool = False
    max_batch: int = DEFAULT_MAX_BATCH
    order_ticker_seconds: float = DEFAULT_ORDER_TICKER_SECONDS
    journal_path: str = DEFAULT_JOURNAL_PATH
    address: str = ""

    @classmethod
    def from_env(cls, env: Optional[Mapping[str, str]] = None) -> "ExecutionConfig":
        """Build the config from the environment.

        `POLY_ENV_FILE` may point at a `KEY=VALUE` file; real environment
        variables always win over the file.
        """
        base = dict(os.environ)
        file_env = _load_env_file(base["POLY_ENV_FILE"]) if base.get("POLY_ENV_FILE") else {}
        if env is not None:
            base = dict(env)
        values = {**file_env, **base}

        owner_pk = values.get("POLY_OWNER_PK", "").strip()
        dry_raw = values.get("POLY_DRY_RUN")
        dry_run = _as_bool(dry_raw, default=not owner_pk)

        max_batch = _as_int(values.get("POLY_MAX_BATCH"), DEFAULT_MAX_BATCH) or DEFAULT_MAX_BATCH
        max_batch = max(1, min(max_batch, CLOB_MAX_BATCH))

        return cls(
            host=values.get("POLY_HOST", DEFAULT_HOST).strip() or DEFAULT_HOST,
            chain_id=_as_int(values.get("POLY_CHAIN_ID"), DEFAULT_CHAIN_ID) or DEFAULT_CHAIN_ID,
            api_key=values.get("POLY_API_KEY", "").strip(),
            api_secret=values.get("POLY_API_SECRET", "").strip(),
            api_passphrase=values.get("POLY_API_PASSPHRASE", "").strip(),
            owner_pk=owner_pk,
            relayer_api_key=values.get("POLY_RELAYER_API_KEY", "").strip(),
            relayer_address=values.get("POLY_RELAYER_ADDRESS", "").strip(),
            funder=values.get("POLY_FUNDER", "").strip(),
            signature_type=_as_int(values.get("POLY_SIGNATURE_TYPE"), None),
            dry_run=dry_run,
            heartbeat_seconds=_as_int(values.get("POLY_HEARTBEAT_SECONDS"), DEFAULT_HEARTBEAT_SECONDS)
            or DEFAULT_HEARTBEAT_SECONDS,
            post_only=_as_bool(values.get("POLY_POST_ONLY"), True),
            harvest_enabled=_as_bool(values.get("POLY_HARVEST"), False),
            repair_enabled=_as_bool(values.get("POLY_REPAIR"), False),
            max_batch=max_batch,
            order_ticker_seconds=_as_float(
                values.get("POLY_ORDER_TICKER_SECONDS"), DEFAULT_ORDER_TICKER_SECONDS
            )
            or DEFAULT_ORDER_TICKER_SECONDS,
            journal_path=values.get("POLY_JOURNAL_PATH", DEFAULT_JOURNAL_PATH).strip()
            or DEFAULT_JOURNAL_PATH,
            address=values.get("POLY_ADDRESS", "").strip(),
        )

    @property
    def has_owner_key(self) -> bool:
        return bool(self.owner_pk)

    @property
    def has_credentials(self) -> bool:
        return bool(self.api_key and self.api_secret and self.api_passphrase)

    def secret_values(self) -> tuple[str, ...]:
        """The literal secret strings, so a journal can scrub them out."""
        return tuple(
            value
            for value in (getattr(self, name, "") for name in SECRET_FIELDS)
            if value
        )

    def redacted(self) -> dict[str, object]:
        """A dict safe to log. Every secret becomes a length-only marker."""
        out: dict[str, object] = {}
        for name in self.__dataclass_fields__:
            value = getattr(self, name)
            if name in SECRET_FIELDS:
                out[name] = f"<secret:{len(value)}>" if value else "<unset>"
            else:
                out[name] = value
        return out

    def __repr__(self) -> str:  # pragma: no cover - trivial
        return f"ExecutionConfig({self.redacted()!r})"
