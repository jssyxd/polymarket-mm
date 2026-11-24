# taker-strategy

Deliverable: `src/pmm/strategy/taker.py` plus `tests/test_taker_strategy.py`.

Shape: `Observation(fair, bid, ask, tau_seconds, won)` in, `Intent(side, price, size)` out.
Rules: take only when `fair - ask >= min_edge`; size by fractional Kelly with a hard
cap; refuse when `tau_seconds <= 180` or the book is stale or one-sided.

Constraints: pure functions, no network, no credentials. `PYTHONPATH=src python -m pytest -q`
must pass. Report the assumptions you made about the probability model.
