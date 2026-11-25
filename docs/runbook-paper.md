# Runbook: paper pipeline without a human in the loop

State on 2026-11-25: the three workers returned `done` with no deliverable.
`taker-strategy` hit `429 rate_limit`; all three panes show only the CLI
startup banner and change nothing but `.pi/`. Nothing was merged because
there is nothing to merge.

## What runs by itself now

| Job | Host | Mechanism | Ends |
|---|---|---|---|
| book recording | VPS | `nohup tools/record_book.py --duration 28800` | 8h |
| book recording | laptop | same, explicit `--markets` | 8h |
| merge / redeem / alerts | VPS | systemd timers | permanent |

Recording is the only part that self-terminates and needs no attention.

## What has to be built before a paper ledger can exist

`tools/run_mm.py --paper` records simulated fills at the book ask, with no fee
and no slippage model. A ledger that can be judged needs:

1. `src/pmm/paper/broker.py` - fills at ask, explicit fee (default 0, the
   measured value) and slippage from book depth.
2. `tools/paper_mm.py` - replay a recorded book file through the strategy and
   the broker, one ledger line per simulated order and fill.
3. The strategy module the broker feeds.

None of these exist yet; the workers that were meant to write them produced no
files.

## Commands, in order

```bash
# 1. rebuild the three modules (single agent, not a fan-out, until dispatch is reliable)
#    briefs are in .herd-dispatch/jobs/*/brief.md

# 2. run 12 hours of paper trading against the recorded books
PYTHONPATH=src python tools/paper_mm.py \
  --books /var/lib/pmm/books/books-2026-11-25.jsonl --duration 43200 \
  --ledger /var/lib/pmm/paper-ledger.jsonl

# 3. read the ledger
PYTHONPATH=src python tools/report.py --journal /var/lib/pmm --day 2026-11-26
```

## Why there is no "AI intervenes by itself" yet

A background job that finishes can wake the agent; a timer cannot. Anything
that must survive a session boundary has to be a process on the VPS or a
GitHub Action. That is why recording is a `nohup` process and the recycling
jobs are systemd timers, and why the paper run must become a script before it
can be called automatic.
