# Task: wire the Polymarket MM modules into one runnable service and a deploy bundle

Read `/home/da/.agents/skills/poteto-mode/SKILL.md` in full, including its Principles section, before any work.

## Context

You are the integration worker. Four modules already exist and are tested. You do not rewrite them; you wire them together, package them, and produce the deploy bundle.

The repo is `/home/da/桌面/polymarketMM`. The Python package is `polymarket-mm/` with `src/pmm/`.

Existing modules and their public surface (read them, do not trust this list blindly):

- `src/pmm/data/clob.py` — read-only CLOB client: `get_server_time()`, `get_market(condition_id)`, `get_book(token_id)`, `get_midpoint(token_id)`, `get_tick_size(token_id)`, `get_fee_rate_bps(token_id)`, `list_reward_markets(page_size=500)`, `list_updown_markets(asset, duration)`, `get_gamma_market(slug)`. Error type `pmm.data.clob.CLOBError`.
- `src/pmm/data/rewards.py` — `order_score`, `q_one`, `q_two`, `q_min`, `normalize`, `epoch_score`, `final_share`, dataclasses `Book`, `Level`.
- `src/pmm/data/universe.py` — `RewardCandidate`, `score_candidate(market, book_a, book_b, mid_a, mid_b, our_size_shares, our_spread_cents)`, `updown_candidate(...)`, `select_candidates(candidates, capital_usd, max_spread_cents_cap=4.5, min_rate_per_day=50.0)`, `market_meta(clob_market, rewards_row=None, rate_per_day=None)`, `gamma_market_meta(gamma_market, rate_per_day=0.0)`, `size_cutoff_midpoint`.
- `src/pmm/pricing/probability.py` — `FairProbability`, `black_scholes_digital_prob(spot, strike, sigma_sqrt_second, tau_seconds)`, `implied_prob_from_book(book)`, `probability_space_vol(spot, strike, tau_seconds, confidence=2.0)`.
- `src/pmm/pricing/quotes.py` — `QuoteSide`, `Quote`, `Inventory(up_shares, down_shares, max_inventory_per_side)`, `build_quotes(fair_prob, sigma_p, tau_seconds, tick_size, min_size, inventory, half_spread_cents=None, reward_max_spread_cents=None, min_reward_size=0.0, gamma=0.15)`.
- `src/pmm/pricing/pairing.py` — `paired_fill_pnl`, `unpaired_fill_exposure`, `expected_net_bps`, `merge_arbitrage_threshold`.
- `src/pmm/execution/config.py` — `ExecutionConfig.from_env()`, `.redacted()`, `.has_owner_key()`.
- `src/pmm/execution/clob.py` — `OrderExecutor(config, journal=None)`, `build_client(config)`, `ExecutionError`. `place_or_dry`, `place_batch`, `cancel_all`, `cancel_order`, `Heartbeat` (read the file for exact signatures).
- `src/pmm/execution/journal.py` — `Journal(path)`, `.append(kind, **fields)`, `.read_day`, `.read_all`, `.fills()`, `compute_pnl(fills, marks)`, `pnl_from_journal(journal, marks, day=None)`.
- `src/pmm/execution/positions.py` — read it for the position-reading functions.
- `src/pmm/risk/gates.py` — `MarketState` (read the dataclass for every field), `GateDecision`, `GateStack().evaluate(state) -> GateDecision`.
- `src/pmm/monitor/metrics.py`, `src/pmm/monitor/agent.py` (`MonitorAgent().run_once(state, fills, params) -> dict`), `src/pmm/monitor/report.py` (`write_report`).

Read `/home/da/桌面/polymarketMM/docs/polymarket-mm-plan.md` sections 3, 4, 5, 8 first. The pair invariant in section 3 is the reason the quote side is two resting BIDS, not a bid and an ask: buying YES at `p` and NO at `1-p` costs `1 - 2*delta` and merges back to 1 pUSD.

Read `/home/da/桌面/polymarketMM/.research/credentials.md` for the access constraint: the account owner private key is NOT available on this machine, so the runner must be able to run dry-run and paper mode end to end without it. The live-post path must stay refused, not silently skipped.

## What to build

You own exactly these paths and no others:

- `src/pmm/__init__.py`
- `src/pmm/core/__init__.py`
- `src/pmm/core/market.py` — a market snapshot model: one dataclass per market holding condition id, question, the two token ids, tick size, min order size, reward min size, reward max spread, rate per day, midpoint, the raw books, the expiry timestamp, and the neg-risk flag. Give it a `from_clob_market(...)` classmethod and a `to_dict()`.
- `src/pmm/core/inventory.py` — the paired-inventory model: unpaired UP shares, unpaired DOWN shares, the box, the notional at risk if the market resolves against the position, and the mergeable coverage fraction. It must convert to and from the `pmm.pricing.quotes.Inventory` the quote builder takes.
- `src/pmm/core/selection.py` — the quote-cycle selector: given the current candidate list, the capital budget, the per-side size, the current half-spread, and the gate decision, choose the market(s) to quote this cycle and return the quote intents with their reasons.
- `src/pmm/engine/__init__.py`
- `src/pmm/engine/cycle.py` — the quote cycle: for each selected market, build the two-sided quote, run it through the gate stack, and emit order intents. This is the module the runner calls once per cycle.
- `src/pmm/engine/runner.py` — the service loop: one cycle, then sleep, then next cycle. It owns the journal, the heartbeat (single instance, same process as the order placement, cancel-all before the heartbeat stops), and the reconciliation of resting orders against the live book.
- `src/pmm/engine/self_tune.py` — reads the journal, calls the monitor agent once, and writes the resulting parameter file back to disk atomically so the next cycle picks it up. This is the "hourly self-adjustment" the operator asked for.
- `tools/run_mm.py` — CLI entry point for the service: `--dry-run`, `--paper`, `--once`, `--journal`, `--params`, `--capital`, `--size`, `--half-spread`, `--interval`, `--markets`, `--top`. It must work with no credentials at all.
- `tools/record_book.py` — CLI that records live books to a JSONL file for later replay, so the quote cycle can be replayed offline.
- `tests/test_core.py`
- `tests/test_engine.py`
- `pyproject.toml`
- `deploy/`

Do NOT modify any file outside those paths. Do not modify the four existing modules. If you find a genuine bug in an existing module, report it in your final reply with file and line, and do not edit it.

## Requirements

### Package
`pyproject.toml` declares the project (`polymarket-mm`), the package under `src/`, and the dependencies already installed in `polymarket-mm/.venv`: `py_clob_client_v2==1.2.2`, `pytest`. No new third-party dependency may be introduced; the runtime code must work with the standard library plus what is already installed. The `pmm` package must import cleanly with `python3.12+` and with `from __future__ import annotations` style used by the existing modules.

### The quote cycle
- The cycle must produce TWO resting BIDS per market (buy UP and buy DOWN), never a bid and an ask, because the profit source is the paired fill that merges back to 1 pUSD. Cite the pair invariant in a module docstring.
- The two bid prices must satisfy `bid_up + bid_down <= 1 - tick_size`, so a paired fill always leaves a positive mergeable margin. `build_quotes` already enforces this; do not undo it.
- The cycle must read the reward settings from the market snapshot and pass `reward_max_spread_cents` and `min_reward_size` into `build_quotes`, so the quote stays inside the venue's reward band and is at least the venue's minimum size.
- The gate stack must run BEFORE any order intent is emitted. A gate that blocks a side removes that side's intent and records the reason in the intent. A hard stop removes both sides and the cycle records it.
- The half-spread used by the cycle comes from the parameter file written by the self-tune step, defaulting to 1.0 cent, and is clamped to the market's reward max spread.
- Post-only is mandatory: every intent carries `post_only=True` and the executor rejects any intent that is not post-only.

### The runner
- One process. The heartbeat lives in the runner, not in a separate service, because the venue cancels all resting orders when the heartbeat lapses.
- On shutdown the runner cancels all orders FIRST, then stops the heartbeat, then closes the client. The order matters and must be visible in the code.
- The runner must refuse to place a real order when `ExecutionConfig.has_owner_key()` is false, and must say so once at startup, then continue in dry-run or paper mode.
- Paper mode means: watch the live book, and record a `fill` journal line when the book would have crossed our resting quote. It never sends anything to the exchange.
- The runner must survive a network error: a CLOBError or ExecutionError in one cycle logs the error, waits, and continues. It must not crash the service.

### The self-tune step
- Runs the monitor agent once, with the current `MarketState` built from the journal, and the current parameters.
- Writes the parameters back atomically (write a temp file in the same directory, then `os.replace`).
- Writes an hourly report through `pmm.monitor.report.write_report` into a reports directory.
- It must be safe to run with an empty journal: no fills means "no evidence", not a crash.

### The deploy bundle under `deploy/`
Produce, as text files with no secrets in them:

- `deploy/README.md` — how to run the service on a 1 vCPU / 960 MB Debian 12 box: the venv setup, the environment variables, the systemd unit files, the cron entry for the hourly self-tune, the journal and report paths, and how to stop cleanly.
- `deploy/pmm-mm.service` — a systemd unit for the runner, with `Restart=always`, a low memory limit, `WorkingDirectory`, and an `ExecStart` that reads the environment from `/etc/pmm-mm/pmm.env`.
- `deploy/pmm-selftune.service` and `deploy/pmm-selftune.timer` — a systemd timer that runs the self-tune step hourly.
- `deploy/pmm.env.example` — every environment variable the code reads, with a placeholder value and a comment. No real credential values anywhere.
- `deploy/install.sh` — a script that creates the venv, installs the package, creates the directory layout, and installs the unit files. It must not contain credentials and must not start the service; it must print the next command to run.

### The CLIs
`tools/run_mm.py` must be runnable as `python tools/run_mm.py --dry-run --once` from the repo root with no credentials and must exit 0 having produced a journal directory and printed one cycle summary.

## Verification

```
cd /home/da/桌面/polymarketMM/polymarket-mm
.venv/bin/python -m pytest tests -q
.venv/bin/python tools/run_mm.py --dry-run --once --journal /tmp/pmm-journal-int --capital 3.4 --size 20
```

Both must succeed. The pytest run must include your new tests, and the whole suite (all workers' tests included) must stay green.

Your new tests must assert observable behavior, not wiring:
- the pair invariant: for a built quote, `bid_up + bid_down <= 1 - tick_size`;
- a gate hard stop removes both intents;
- the self-tune step writes a parameter file that the next cycle reads, and the file is valid JSON with the expected keys;
- the runner's shutdown order is cancel-then-stop-heartbeat;
- the inventory model reports zero exposure for a perfectly paired position and non-zero for an unpaired one.

## Report

Answer in your final reply with: the file list you wrote, the pytest output line, the run_mm.py output summary, the exact parameter file contents after one self-tune run, and anything you found broken in an existing module (file and line, no edits).

---
Role: implementer
Working directory: /home/da/桌面/polymarketMM
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.

---
Role: implementer
Working directory: /home/da/桌面/polymarketMM
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.

---
Role: implementer
Working directory: /home/da/桌面/polymarketMM
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.
