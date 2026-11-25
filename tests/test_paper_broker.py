"""The paper broker pays the book, not the mid."""

from __future__ import annotations

from pmm.paper.broker import Book, execute


def _book() -> Book:
    return Book.from_raw(
        {
            "bids": [[0.48, 10], [0.47, 100]],
            "asks": [[0.50, 10], [0.52, 100]],
        }
    )


def test_a_buy_inside_the_top_level_pays_the_ask():
    fill = execute(_book(), "BUY", 10)

    assert fill.price == 0.50
    assert fill.slippage == 0.0
    assert fill.size == 10


def test_a_buy_larger_than_the_top_level_walks_the_book():
    fill = execute(_book(), "BUY", 30)

    assert abs(fill.price - (10 * 0.50 + 20 * 0.52) / 30) < 1e-6
    assert fill.slippage > 0
    assert fill.size == 30


def test_a_limit_below_the_ask_does_not_fill():
    assert execute(_book(), "BUY", 10, limit=0.49) is None


def test_the_fee_is_charged_on_the_notional():
    fill = execute(_book(), "BUY", 10, fee_bps=100)

    assert abs(fill.fee - 10 * 0.50 * 0.01) < 1e-9


def test_a_sell_walks_the_bids_downward():
    fill = execute(_book(), "SELL", 20)

    assert abs(fill.price - (10 * 0.48 + 10 * 0.47) / 20) < 1e-9
    assert execute(_book(), "SELL", 5).price == 0.48
