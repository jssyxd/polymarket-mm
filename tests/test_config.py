"""Execution config tests."""

from __future__ import annotations

import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1] / "src"))

from pmm.execution.config import ExecutionConfig  # noqa: E402

SECRET = "c2VjcmV0LXNlY3JldC1zZWNyZXQtc2VjcmV0LXNlY3JldA=="
PASSPHRASE = "0" * 64
OWNER_PK = "0x" + "4ceb4b9b4b95311b782d1a86cc5004d103da5de15c1bc455b8db50501bd9d21f"


def _env(**overrides):
    env = {
        "POLY_API_KEY": "11111111-2222-4333-8444-555555555555",
        "POLY_API_SECRET": SECRET,
        "POLY_API_PASSPHRASE": PASSPHRASE,
    }
    env.update({k: v for k, v in overrides.items() if v is not None})
    return env


def test_defaults_without_owner_key():
    config = ExecutionConfig.from_env(_env())
    assert config.host == "https://clob.polymarket.com"
    assert config.chain_id == 137
    assert config.heartbeat_seconds == 5
    assert config.post_only is True
    assert config.max_batch == 15
    assert config.order_ticker_seconds == 1.0
    assert config.journal_path
    assert config.owner_pk == ""
    assert config.has_owner_key is False


def test_dry_run_defaults_to_on_without_owner_key():
    config = ExecutionConfig.from_env(_env())
    assert config.dry_run is True


def test_dry_run_defaults_to_off_with_owner_key():
    config = ExecutionConfig.from_env(_env(POLY_OWNER_PK=OWNER_PK))
    assert config.dry_run is False


def test_dry_run_can_be_forced_on_with_owner_key():
    config = ExecutionConfig.from_env(_env(POLY_OWNER_PK=OWNER_PK, POLY_DRY_RUN="1"))
    assert config.dry_run is True


def test_env_overrides_are_honoured():
    config = ExecutionConfig.from_env(
        _env(
            POLY_HOST="https://clob.example.test",
            POLY_CHAIN_ID="80002",
            POLY_HEARTBEAT_SECONDS="9",
            POLY_POST_ONLY="0",
            POLY_MAX_BATCH="7",
            POLY_ORDER_TICKER_SECONDS="0.5",
            POLY_JOURNAL_PATH="/tmp/pmm-journal",
            POLY_FUNDER="0xabc",
            POLY_SIGNATURE_TYPE="1",
        )
    )
    assert config.host == "https://clob.example.test"
    assert config.chain_id == 80002
    assert config.heartbeat_seconds == 9
    assert config.post_only is False
    assert config.max_batch == 7
    assert config.order_ticker_seconds == 0.5
    assert config.journal_path == "/tmp/pmm-journal"
    assert config.funder == "0xabc"
    assert config.signature_type == 1


def test_max_batch_is_capped_at_the_clob_limit():
    config = ExecutionConfig.from_env(_env(POLY_MAX_BATCH="50"))
    assert config.max_batch == 15


def test_redacted_hides_every_secret():
    config = ExecutionConfig.from_env(_env(POLY_OWNER_PK=OWNER_PK))
    redacted = config.redacted()
    dumped = json.dumps(redacted)

    assert SECRET not in dumped
    assert PASSPHRASE not in dumped
    assert OWNER_PK not in dumped
    assert "11111111-2222-4333-8444-555555555555" not in dumped

    assert redacted["api_secret"] == f"<secret:{len(SECRET)}>"
    assert redacted["api_passphrase"] == f"<secret:{len(PASSPHRASE)}>"
    assert redacted["owner_pk"] == f"<secret:{len(OWNER_PK)}>"


def test_repr_does_not_leak_secrets():
    config = ExecutionConfig.from_env(_env(POLY_OWNER_PK=OWNER_PK))
    assert SECRET not in repr(config)
    assert OWNER_PK not in repr(config)


def test_secret_values_lists_the_literals_for_scrubbing():
    config = ExecutionConfig.from_env(_env(POLY_OWNER_PK=OWNER_PK))
    assert SECRET in config.secret_values()
    assert OWNER_PK in config.secret_values()
