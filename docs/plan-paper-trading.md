# Plan: paper trading before any more capital

Status: phase 1 running, phases 2-4 queued. No live orders in any phase.

## Why

The maker premise was falsified by its own fills (decision 0014): 78% of the
volume was unpaired, and the leg that filled was systematically the one the
market was pricing to zero. The next strategy is judged on paper first, with
fees and slippage charged against it.

## Phase 1 - Recording (8 hours, both hosts)

`tools/record_book.py --top 8 --interval 5 --duration 28800`, writing
`/var/lib/pmm/books/books-<date>.jsonl` on the VPS and `data/books-<date>.jsonl`
locally. Public endpoints only, no credentials, no orders. The two files are
deliberately independent: one host's outage must not void the sample.

Acceptance: both files grow every 5 seconds, and each line carries both books
plus tick size and reward parameters.

## Phase 2 - Development (herdr workers, one worktree each)

| Worker | Deliverable | Done means |
|---|---|---|
| `taker-strategy` | `src/pmm/strategy/taker.py` | edge = fair - ask, sizing by Kelly fraction, refusal rules |
| `paper-broker` | `src/pmm/paper/broker.py` | fills at ask, fee model, slippage model, ledger JSONL |
| `ci-pipeline` | `.github/workflows/ci.yml` | tests + lint on push, manual `workflow_dispatch` for a paper run |
| `paper-review` | review notes | independent read of the two modules, no author review |

Constraints for every worker: no live order path, no credentials, tests for
each behaviour, and `PYTHONPATH=src` so the suite runs unchanged.

## Phase 3 - Paper run on the VPS (12 hours minimum)

`tools/paper_mm.py --duration 43200` replaying the recorded books through the
strategy and the paper broker, writing one ledger line per simulated order and
one per simulated fill.

Costs charged per fill: taker fee (measured 0 on the observed markets, but the
parameter stays explicit), half the quoted spread as slippage when the size
exceeds the top of book, and the full spread when the trade crosses more than
one level.

Acceptance: the ledger has at least 200 simulated fills, and a daily summary
reports hit rate, PnL per share, and the fee/slippage split.

## Phase 4 - Analysis and CI/CD

Read the ledger, split PnL into edge and cost, and only then decide whether the
taker route deserves capital. The workflow gets a scheduled paper run and a
report artifact, so a regression shows up without a human running anything.

## What must not happen

- No live orders in phases 1-3.
- No strategy conclusion from fewer than one full paper day.
- No parameter tuning against a single market.
