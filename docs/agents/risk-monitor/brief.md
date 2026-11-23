# Task: build the risk gates and the hourly monitoring agent

Read `/home/da/.agents/skills/poteto-mode/SKILL.md` in full, including its Principles section, before any work.

## Context

We are building a Polymarket market-making system for a maker account holding about 3.4 pUSD. The two upstream repos (`GLFTmm/`, `asgrid-mm/`) contain the risk gates we are porting, and the research in `/home/da/桌面/polymarketMM/.research/` describes what those gates are and what was broken about them.

Read first:
- `/home/da/桌面/polymarketMM/.research/glft-dive.md` sections 3, 5, 7 (gate-by-gate inventory, backtest fidelity problems, audit verdicts)
- `/home/da/桌面/polymarketMM/.research/asgrid-dive.md` sections 5, 6, 8, 10 (gates, ML reality, backtest fidelity, the five lessons)
- `/home/da/桌面/polymarketMM/.research/poly-platform.md` sections 3, 4, 9 (order mechanics, rate limits, traps)

The most important number in either repo is in `asgrid-dive.md` section 8.4: on the OKX account the live strategy captured **-0.55 bp per notional** traded, because adverse selection ate 3.05 bp of a 4.5 bp half-spread. The lesson the author drew is at `asgrid-dive.md` section 10: the first-priority alert is `e_rolling_100 <= 0`, meaning stop adding risk.

Your job is to make that alarm real.

## What to build

You own exactly these files and no others:

- `src/pmm/risk/__init__.py`
- `src/pmm/risk/gates.py` — the gate stack
- `src/pmm/monitor/__init__.py`
- `src/pmm/monitor/metrics.py` — the metric computations
- `src/pmm/monitor/agent.py` — the hourly self-tuning monitor agent
- `src/pmm/monitor/report.py` — the hourly report writer
- `tests/test_gates.py`
- `tests/test_metrics.py`
- `tests/test_agent.py`
- `tools/monitor_tick.py`

## Requirements

### `gates.py`
A `GateStack` that evaluates an ordered list of gates against a `MarketState` and returns the decisions. Model the domain with typed dataclasses rather than a chain of booleans.

- `MarketState` dataclass: `up_shares`, `down_shares`, `max_inventory_per_side`, `last_fill_side` (`"up"`, `"down"` or `None`), `last_fill_ts`, `now`, `tau_seconds`, `fair_prob`, `mid`, `tick_size`, `recent_net_bps` (list), `equity_usd`, `drawdown_pct`, `heartbeat_ok`, `oracle_age_seconds`, `min_order_size`.
- `GateDecision` dataclass: `allowed_up`, `allowed_down`, `reasons` (list of str), `hard_stop` (bool).
- Gates, in this order, each contributing a reason string when it fires:
  1. `HardStopGate`: fires when `heartbeat_ok` is false, or `oracle_age_seconds` exceeds 15, or `drawdown_pct` exceeds 20 percent. Sets `hard_stop` true and both sides false.
  2. `InventoryBoxGate`: a side is blocked when that side's shares reach `max_inventory_per_side`. The other side stays allowed so the position can be flattened.
  3. `CooldownGate`: after a fill on one side, that same side is blocked for 5 seconds.
  4. `ToxicityGate`: fires when `abs(fair_prob - mid)` exceeds 0.03, meaning the external fair value and the book disagree. Both sides blocked.
  5. `ExpiryGate`: when `tau_seconds` is below 90, both sides blocked, because a position must be closed before resolution, not held into it.
  6. `ERollingGate`: when the mean of `recent_net_bps` over the last 100 fills is at or below zero, both sides blocked. This is the alarm the upstream author called the first priority.
  7. `TickGate`: when the computed quote cannot be placed on the tick grid, the side is blocked.
- `GateStack.evaluate(state) -> GateDecision`. The order of the gates matters and a test must prove that a hard stop beats a permissive inventory gate.
- Every gate is a small class with an `evaluate(state) -> tuple[bool, bool, str | None]` method, so a gate can be tested alone.

### `metrics.py`
- `realized_bps(fills: list[dict], journal_pnl: dict) -> float` — net capture in basis points of notional, from a fill list that carries `notional` and `pnl` fields.
- `rolling_net_bps(fills: list[dict], window: int = 100) -> float` — the mean net bps over the last `window` fills.
- `win_rate(fills: list[dict]) -> float`.
- `inventory_exposure(up_shares: float, down_shares: float, mark_up: float, mark_down: float) -> float` — the pUSD at risk if the market resolves fully against the position.
- `pair_coverage(up_shares: float, down_shares: float) -> float` — the fraction of the position that is a complete set and therefore mergeable into pUSD.
- `reward_estimate(min_size: float, max_spread_cents: float, rate_per_day: float, q_min: float, total_q_min: float) -> float` — the estimated daily reward in pUSD, proportional to the share of the market's score the account contributes.

### `agent.py`
An hourly self-tuning monitor agent. It must be conservative and reversible.
- `MonitorAgent` class with `run_once(state: MarketState, fill_history: list[dict], current_params: dict) -> dict`. It reads the metrics, applies at most one parameter change, and returns a decision record with `changed`, `param`, `from_value`, `to_value`, `reason`, and the metrics it saw.
- The tuning rules, in order of preference:
  1. If the rolling net bps is at or below zero, stop quoting entirely and record a stop. Do not tune sizes upward while losing.
  2. If the fill count in the last hour is zero while the account is eligible to quote, widen the half-spread by one cent and record that the market did not fill.
  3. If the rolling net bps is positive and the inventory box is at least half full, raise the inventory box by 25 percent.
  4. Otherwise change nothing.
- The agent must never raise the inventory box while the rolling net bps is at or below zero, and never raise it by more than 25 percent in one step. A test must prove both rules.
- The agent must never widen the half-spread beyond `max_spread_cents` of the market it is quoting, because a quote outside the reward band earns no reward and violates the reward eligibility.

### `report.py`
- `write_report(path: str, payload: dict) -> str` — writes one hourly report as Markdown with a fixed set of sections: the metrics, the decision, and the state. It must not include any credential.
- `read_reports(directory: str) -> list[dict]` — reads back the reports for the last 24 hours.

### `tools/monitor_tick.py`
A CLI that reads the newest journal file from the execution worker, recomputes the metrics, runs the monitor agent once, prints the decision, and appends a report. It must run with no credentials and must handle a missing journal by reporting "no data" rather than raising.

## Verification
```
cd /home/da/桌面/polymarketMM/polymarket-mm
.venv/bin/python -m pytest tests/test_gates.py tests/test_metrics.py tests/test_agent.py -q
```
The venv is created by the execution worker. If it does not exist yet, create it the same way:
```
python3 -m venv .venv && .venv/bin/pip install pytest
```

Tests must cover: every gate firing on its own trigger, the hard stop dominating, the rolling-bps alarm blocking both sides, the agent's refusal to raise the box while losing, the one-step 25 percent cap, the reward estimate being proportional to the score share, and the inventory exposure of a one-sided position.

No network in tests. No credentials anywhere. Python 3.11+.

## Constraints
- Do not create or modify any file outside the list above. `src/pmm/data/`, `src/pmm/pricing/`, `src/pmm/execution/` and `tools/scan_pools.py` and `tools/paper_run.py` belong to other workers.
- Your modules must not import `pmm.data` or `pmm.pricing`, so they stand alone. The monitor agent takes plain dicts and dataclasses.
- `src/pmm/monitor/agent.py` must not import `pmm.execution`.

## Report
Reply with the pytest result and a worked example: 100 fills with a rolling net of -0.4 bp, inventory at 60 percent of the box, no fills in the last hour. State the decision and the single parameter the agent changed.

---
Role: implementer
Working directory: /home/da/桌面/polymarketMM
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.
