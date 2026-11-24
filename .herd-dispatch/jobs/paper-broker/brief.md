# paper-broker

Deliverable: `src/pmm/paper/broker.py` plus `tests/test_paper_broker.py`.

Shape: `Order(token, side, price, size, ts)` in; `Fill(price, size, fee, slippage, ts)` out,
appended to a JSONL ledger. Fees are a parameter (default 0, the measured value);
slippage is modelled from the book depth, not invented.

Constraints: no network in tests, deterministic given the same book, ledger is append-only
and idempotent on `order_id`. `PYTHONPATH=src python -m pytest -q` must pass.
