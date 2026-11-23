# Task: research the Polymarket platform as a maker, as of 2026-11-21

Read `/home/da/.agents/skills/poteto-mode/SKILL.md` in full, including its Principles section, before any work.

## Goal
Produce a factual, cited capability report on the Polymarket platform for a small-capital pure-maker market maker. This report is the ground truth that a Polymarket adaptation plan is built on. Wrong facts here make the whole plan wrong.

## Method
Use the official docs at https://docs.polymarket.com (append `.md` to a page path for raw markdown; https://docs.polymarket.com/llms.txt is the index). Use the live public APIs where the docs are ambiguous. Prefer official docs and on-chain/verified sources over blog posts. Every non-obvious number must carry its source URL.

## Facts to pin down, with a source for each
1. Fee and rebate rules in force right now (the 2026-11-20 23:59 UTC change is already in effect as of today, 2026-11-21). Exact maker-rebate tier table, taker-fee coefficient table, and how maker weighted volume is computed. Confirm whether the 200k 30-day maker-weighted-volume threshold applies and what it means for a small account. Cite the docs page.
2. Liquidity Rewards: the exact scoring formula, how `rewards_min_size` and `rewards_max_spread` are defined and in what units, how the daily payout is computed and its competition factor, the minimum payout, and the endpoint to list reward markets with their current rate per day.
3. The public read APIs: `clob.polymarket.com` endpoints for markets, books, prices, midpoint, tick size, and the rewards market list. Include exact URLs and a working example of each. Note auth requirements.
4. Trading endpoints and their exact limits: order placement, batch orders, cancel, cancel-all, post-only support, order size and price tick rules, rate limits (orders per second, per minute), and any documented heartbeat or dead-man-switch mechanism that cancels resting orders on disconnect.
5. The official Python client `py-clob-client`: current version, its public API surface for the operations above, and its auth model (EOA vs proxy/email wallet, `signature_type`, funder address). Also note the newer `@polymarket/client` TS/Python SDK if it exists and what it offers.
6. Binary option specifics: how Up/Down 5-minute and 15-minute crypto markets are created and settled, the reference price source and timestamp rule, whether the market's strike/open price is published in the market metadata, and where a bot can obtain it.
7. CTF mechanics: the Conditional Token Framework addresses on Polygon, whether `mergePositions` and `splitPosition` are callable by an EOA, gas costs, the collateral token addresses (USDC vs USDC.e) for the current deployment, and whether Polymarket exposes a relayer or gasless path. Confirm which contract Polymarket's markets currently use.
8. Market selection data: list, right now, the crypto 5-minute and 15-minute up/down markets that are currently active with their rewards settings (min size, max spread, rate per day), and the same for the highest-rate-per-day markets overall. Give a short table.
9. Constraints and traps for a maker: post-only rejection rules, minimum order size, whether a maker can be adversely selected on Up/Down markets given the public underlying price, and any documented anti-wash or anti-manipulation rules that a maker must respect.
10. Anything in the docs that contradicts the assumption that a maker earns a rebate on every fill. State clearly what a maker does NOT earn.

## Output
Write your report to `/home/da/桌面/polymarketMM/.research/poly-platform.md`. Create the directory if needed. Include a `## Sources` section listing every URL you used with what it supports. Mark anything you could not verify as "UNVERIFIED" and say what would verify it.

## Acceptance
Every number has a URL. Facts you verified live are marked with the command you ran and the observed output. No claims sourced to blog posts when an official doc exists.

---
Role: researcher
Working directory: /home/da/桌面/polymarketMM
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.
