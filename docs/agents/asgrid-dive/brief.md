# Task: deep dive on the asgrid-mm repository

Read `/home/da/.agents/skills/poteto-mode/SKILL.md` in full, including its Principles section, before any work.

## Goal
Produce a precise architectural report on the repository at `/home/da/桌面/polymarketMM/asgrid-mm` so a designer can plan a Polymarket binary-options market-making adaptation that reuses its execution and operations machinery.

## Scope, read-only
Read the repo. Do not modify anything in it. Key files:
- `README.md`, `ARCHITECTURE_AND_EXECUTION_FLOW.md`, `AS_GRID_FULL_SPECIFICATION.md`, `LESSONS_LEARNED.md`, `THEORY_PAPERS.md`
- `docs/design/00-methodology-master.md` through `05-portable-open-source-survey.md`
- `src/avellaneda_stoikov_engine.py` (exact A-S implementation: reservation price, optimal spread, T-t term, inventory handling, units)
- `src/as_ml_engine.py`, `src/as_risk_guard.py`, `src/grid_risk_controller.py`, `src/as_nautilus_strategy.py`
- `src/backtest_avellaneda_grid.py`, `src/run_2year_asgrid_backtest.py`
- `live_cluster/run_live.py`, `run_live_v2.py`, `okx_ws_manager.py`, `gateway_okx_client.py`, `as_dynamic_risk.py`, `as_nautilus_strategy.py`, `cron_hot_monitor.py`, `cron_accountbot3_ml_guard.py`
- `reports/ASGRID_2YEAR_BENCHMARK_REPORT.md` and the metrics JSONs under `reports/`
- `tests/test_012_components_smoke.py`
- `checkpoints/` (model artifacts and trainer log headers only, do not load large binaries)

## What to report
1. Module map with exact file paths and one-line purpose each.
2. The A-S math as implemented: exact formulas, arguments, units, and where `T-t` appears. Note explicitly how the author documented the `T-t` defect.
3. The NautilusTrader integration: which Nautilus version, which nodes/strategies, the order lifecycle, how the strategy consumes the WS feed, how it emits orders and handles acknowledgements/fills.
4. The OKX WebSocket manager and gateway client: what channels are subscribed, reconnect behavior, how the client handles rate limits and credentials, how orders are signed and placed (post-only? reduce-only? amend?).
5. The risk stack: every gate in `as_risk_guard.py` and `grid_risk_controller.py` and `as_dynamic_risk.py`, with trigger and action.
6. The ML pieces: what the LightGBM models predict, feature list, training loop, drift guard, and how a prediction blocks or reshapes a quote.
7. The ops machinery: what the two cron watchdogs do, what they alert on, what state they persist.
8. The backtest fidelity claim and the headline numbers in the reports. State the metric names and values exactly as recorded.
9. Assumptions that break for a Polymarket binary option: price bounded in (0,1), terminal settlement, no shorting (sell = buy the complement token), tick size 0.01 or 0.001, maker-only, and expiry at a known timestamp. Cite lines.
10. `LESSONS_LEARNED.md` content that generalizes to any market-making port, with the author's own wording.

## Output
Write your report to `/home/da/桌面/polymarketMM/.research/asgrid-dive.md`. Create the directory if needed. Use relative-to-root paths like `src/avellaneda_stoikov_engine.py:88` for every claim. No code changes anywhere else.

## Acceptance
Dense, cited, specific. Every claim locatable. No marketing language. If unclear from code, say "unclear from code".

---
Role: researcher
Working directory: /home/da/桌面/polymarketMM
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.
