# Task: deep dive on the GLFTmm repository

Read `/home/da/.agents/skills/poteto-mode/SKILL.md` in full, including its Principles section, before any work.

## Goal
Produce a precise architectural report on the repository at `/home/da/桌面/polymarketMM/GLFTmm` so a designer can plan a Polymarket binary-options market-making adaptation on top of it.

## Scope, read-only
Read the repo. Do not modify anything in it. Key files to cover:
- `README.md`, `CHANGELOG.md`, `SECURITY.md`
- `shared/glft_engine/glft_solver.py` (the Stationary GLFT solver: exact public functions, signatures, units, how arrival intensity `A_a/A_b` and decay `k_a/k_b` are calibrated, how `sigma` enters, how fee-endogenous hurdle `delta_half >= max(delta_glft, fee*2.5, min_tick)` is implemented)
- `shared/toxic_gate/causal_features.py`, `shared/sentinel/market_regime_sentinel.py`, `shared/aggregator/micro_aggregator.py`
- `01_crypto_altcoin_perp_mm/models/vpin_gate.py`
- `02_rwa_tokenized_equity_mm/core/hyperliquid_sndk_live.py` (the live main loop: quote cycle, post-only handling, inventory box, 5s one-sided cooldown, LightGBM toxicity gate integration, quota guard, watchdog)
- `02_rwa_tokenized_equity_mm/core/hyperliquid_quota_guard.py`, `core/micro_optimizer.py`, `regime/regime_classifier.py`
- `03_dex_concentrated_lp_mm/hedging/concentrated_lp_manager.py`
- `experiments/matrix_backtest/matrix_engine.py`, `run_matrix_benchmark.py`, `run_all_assets_benchmark.py` and `results*/master_matrix_summary.json`, `all_assets_matrix_summary.json`
- `audit_reports/*.md` (three OMP inspector reports: causality, fee stress, overfitting)
- `tests/`

## What to report
1. Module map with exact file paths and one-line purpose each.
2. The pricing math as implemented: which symbols, which arguments, what units (probability-space vs price-space), which outputs. Quote the actual key lines, do not paraphrase from the README.
3. The risk stack as implemented: list every hard gate, its trigger condition and its action, with file and symbol.
4. The live execution loop as implemented: order lifecycle, how post-only is enforced, how inventory is tracked, what happens on a one-sided fill, how the loop handles disconnects and API quota limits.
5. The backtest engine: what fidelity it claims, what data it needs, how it computes fills and fees, what the summary JSON metrics mean.
6. Assumptions baked into the code that break for a binary option priced in (0,1) settling to 0 or 1, with no leverage, no shorting, and no continuous underlying. Be concrete and cite lines. Examples to check: unbounded price space, sigma meaning, inventory sign conventions, tick sizes, fee units.
7. The three audit reports' verdict in one line each, and anything they flag as a live risk that would also apply to a Polymarket port.
8. What is production-hardened (has been run live) versus what is a backtest-only artifact.

## Output
Write your report to `/home/da/桌面/polymarketMM/.research/glft-dive.md`. Create the directory if needed. Use relative-to-root paths like `shared/glft_engine/glft_solver.py:123` for every claim. No code changes anywhere else.

## Acceptance
The report is dense, cited, and specific. A reader can locate every claim. No marketing language. If something is unclear from the code, say "unclear from code" rather than guessing.

---
Role: researcher
Working directory: /home/da/桌面/polymarketMM
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.
