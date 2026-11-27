from pmm.data.public_trades import PublicTrade
from pmm.engine.paper_fills import consume, queue_ahead


def trade(size, price=0.50, side="SELL", token="up", ts=100.0, trade_id=None):
    return PublicTrade(
        trade_id=trade_id or f"t{ts}-{size}-{price}",
        condition_id="0xabc",
        token_id=token,
        side=side,
        price=price,
        size=size,
        ts=ts,
    )


def test_queue_ahead_sums_bids_at_or_above_price():
    book = {"bids": [{"price": "0.51", "size": "10"}, {"price": "0.50", "size": "20"}, {"price": "0.49", "size": "30"}]}
    assert queue_ahead(book, 0.50) == 30.0
    assert queue_ahead(book, 0.49) == 60.0


def test_sell_below_ahead_does_not_fill():
    remaining, fill = consume(100.0, [trade(40)], price=0.50, token_id="up", placed_ts=90.0, seen=set())
    assert remaining == 60.0
    assert fill is None


def test_sell_above_ahead_fills():
    remaining, fill = consume(100.0, [trade(101)], price=0.50, token_id="up", placed_ts=90.0, seen=set())
    assert remaining == 0.0
    assert fill is not None


def test_exact_ahead_empties_queue_without_fill():
    remaining, fill = consume(100.0, [trade(100), trade(5)], price=0.50, token_id="up", placed_ts=90.0, seen=set())
    assert remaining == 0.0
    assert fill is not None


def test_filters_side_price_token_and_time():
    seen = set()
    trades = [
        trade(500, side="BUY", trade_id="buy"),
        trade(500, price=0.51, trade_id="high"),
        trade(500, token="down", trade_id="other"),
        trade(500, ts=10.0, trade_id="old"),
    ]
    remaining, fill = consume(10.0, trades, price=0.50, token_id="up", placed_ts=90.0, seen=seen)
    assert remaining == 10.0
    assert fill is None
    assert seen == set()
