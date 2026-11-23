"""Live fills are read from the venue's trades and written to the journal once."""

from __future__ import annotations

from pmm.execution.config import ExecutionConfig
from pmm.execution.journal import Journal
from pmm.execution.trades import sync_fills, venue_fills

OWNER = "11111111-2222-4333-8444-555555555555"
WALLET = "0x00000000000000000000000000000000000000aa"


def _trade(**overrides):
    trade = {
        "id": "trade-1",
        "market": "0xcond",
        "asset_id": "999",
        "side": "BUY",
        "size": "6.0",
        "price": "0.47",
        "outcome": "No",
        "status": "CONFIRMED",
        "match_time": "1795437707",
        "owner": "someone-else",
        "transaction_hash": "0xhash",
        "maker_orders": [
            {
                "order_id": "0xorder1",
                "owner": OWNER,
                "maker_address": WALLET,
                "matched_amount": "5.5",
                "price": "0.5300000292673974",
                "asset_id": "111",
                "outcome": "Yes",
                "side": "BUY",
            },
            {
                "order_id": "0xorder2",
                "owner": "other-owner",
                "maker_address": "0xdead",
                "matched_amount": "1.0",
                "price": "0.54",
                "asset_id": "222",
                "outcome": "Yes",
                "side": "BUY",
            },
        ],
    }
    trade.update(overrides)
    return trade


class _Client:
    def __init__(self, trades):
        self.trades = trades
        self.calls = 0

    def get_trades(self, params=None, only_first_page=False):
        self.calls += 1
        return self.trades


def _config(tmp_path) -> ExecutionConfig:
    return ExecutionConfig(
        dry_run=False,
        journal_path=str(tmp_path / "journal"),
        api_key=OWNER,
        funder=WALLET,
        owner_pk="0x" + "11" * 32,
    )


def test_only_our_maker_side_is_taken_from_a_trade(tmp_path):
    fills = venue_fills(_config(tmp_path), client=_Client([_trade()]))

    assert len(fills) == 1
    fill = fills[0]
    assert fill["size"] == 5.5, "the other maker's 1.0 is not ours"
    assert fill["outcome"] == "Yes"
    assert fill["token_id"] == "111"
    assert fill["price"] == 0.53, "the venue's float noise is rounded"
    assert fill["condition_id"] == "0xcond"
    assert fill["side"] == "BUY"


def test_an_unconfirmed_trade_is_ignored(tmp_path):
    fills = venue_fills(_config(tmp_path), client=_Client([_trade(status="FAILED")]))

    assert fills == []


def test_the_journal_records_each_fill_once(tmp_path):
    config = _config(tmp_path)
    journal = Journal(tmp_path / "journal")
    client = _Client([_trade()])

    first = sync_fills(journal, config, client=client)
    second = sync_fills(journal, config, client=client)

    assert len(first) == 1
    assert second == [], "a second poll must not duplicate the fill"
    recorded = journal.fills()
    assert len(recorded) == 1
    assert recorded[0]["fill_id"] == "trade-1:0xorder1"
    assert recorded[0]["size"] == 5.5
