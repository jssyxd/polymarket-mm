# paper-review

Review `src/pmm/strategy/taker.py` and `src/pmm/paper/broker.py` after the first two land.

Look for: a live order path that could fire, a fee or slippage that is silently zero,
a Kelly size that can exceed the cap, a ledger write that is not idempotent.
Report findings as file:line with a one-line severity. Do not edit code.
