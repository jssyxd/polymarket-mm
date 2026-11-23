# Task: build the Polymarket market-selection module

Read `/home/da/.agents/skills/poteto-mode/SKILL.md` in full, including its Principles section, before any work.

## Context

We are building a small Polymarket market-making system for a maker account with ~3.4 pUSD. A research pass already established the platform facts. Read `/home/da/桌面/polymarketMM/.research/poly-platform.md` first, especially sections 1, 2, 6, 8, 9. Read `/home/da/桌面/polymarketMM/.research/credentials.md` for access constraints.

Do not re-derive the platform facts. Use them.

## What to build

A Python package at `/home/da/桌面/polymarketMM/polymarket-mm/src/pmm/` (the directory exists). You own exactly these files and no others:

- `src/pmm/data/__init__.py`
- `src/pmm/data/clob.py` — read-only Polymarket CLOB client
- `src/pmm/data/rewards.py` — liquidity-reward scoring
- `src/pmm/data/universe.py` — candidate market selection
- `tests/test_rewards.py`
- `tests/test_universe.py`
- `tools/scan_pools.py`

## Requirements

### `clob.py`
Read-only HTTP client, standard library only (no new third-party dependencies; use `urllib.request`). Base URL `https://clob.polymarket.com`, Gamma base `https://gamma-api.polymarket.com`.

Functions:
- `get_server_time() -> int`
- `get_market(condition_id) -> dict` (route `/markets/{condition_id}`)
- `get_book(token_id) -> dict`
- `get_midpoint(token_id) -> float`
- `get_tick_size(token_id) -> str`
- `get_fee_rate_bps(token_id) -> int`
- `list_reward_markets(page_size=500) -> list[dict]` — page through `/rewards/markets/current` using `next_cursor` until `LTE=`; return every row. This endpoint is public and unauthenticated; it currently returns 7,833 markets.
- `list_updown_markets(asset: str, duration: str) -> list[dict]` — discover crypto up/down markets by slug `{asset}-updown-{5m|15m}-{window_start_epoch}`, where `window_start_epoch = (now // seconds) * seconds` with seconds 300 for 5m and 900 for 15m, for the current and next two windows, per asset in `btc eth sol xrp doge bnb hype zec`. Use Gamma `/markets?slug=...`.
- `get_gamma_market(slug) -> dict | None`

Every function must have a timeout and must raise a typed error (`pmm.data.clob.CLOBError`) carrying the HTTP status and body, never a bare `urllib` exception. Cache `get_market` results in-process with a TTL of 60 seconds.

### `rewards.py`
Implement the official scoring exactly, from the docs, with these names:
- `order_score(max_spread_cents: float, spread_cents: float) -> float` — `S = ((v - s) / v) ** 2`, zero when `s > v`.
- `q_one(...)`, `q_two(...)` — aggregate over a market and its complement.
- `q_min(q_one: float, q_two: float, midpoint: float) -> float` — `max(min(q_one, q_two), max(q_one, q_two) / 3.0)` when `0.10 <= midpoint <= 0.90`, else `min(q_one, q_two)`.
- `normalize(scores: list[float]) -> list[float]` — divide by the sum.
- `epoch_score(samples: list[list[float]]) -> float` — sum of normalized per-sample scores.
- `final_share(epoch_scores: dict[str, float]) -> dict[str, float]` — divide each by the sum.

Units: `max_spread_cents` and `spread_cents` are in cents (the CLOB `rewards_max_spread` value 4.5 means 4.5 cents). Sizes are in shares.

### `universe.py`
- `RewardCandidate` dataclass: `condition_id`, `question`, `tokens` (list of token ids), `min_size`, `max_spread_cents`, `rate_per_day`, `midpoint`, `q_one`, `q_two`, `q_min`, `est_share_pct`, `notional_usd`.
- `score_candidate(market: dict, book_a: dict, book_b: dict, mid_a: float, mid_b: float, our_size_shares: float, our_spread_cents: float) -> RewardCandidate` — compute our own Q contribution assuming we rest `our_size_shares` on each side at `our_spread_cents` from the midpoint, and the rest of the book as competitors.
- `select_candidates(candidates: list[RewardCandidate], capital_usd: float, max_spread_cents_cap: float = 4.5, min_rate_per_day: float = 50.0) -> list[RewardCandidate]` — filter by rate, sort by estimated share descending, and greedily accept while the sum of `notional_usd` stays inside `capital_usd`. `notional_usd` is the pUSD needed to hold the qualifying size on the cheaper side: `min_size * min(p_up, p_no)`.
- `updown_candidate(market: dict, ...) -> RewardCandidate` for up/down markets, whose `rate_per_day` is 0 because they carry no active reward allocation.

### `tools/scan_pools.py`
A CLI that prints the top candidates for a given capital and our per-side size, as a table. It must not print credentials. It must work with no credentials at all, because every endpoint it uses is public.

## Verification
You must prove it works against the live API. Run it.

```
cd /home/da/桌面/polymarketMM/polymarket-mm
python3 -m pytest tests/test_rewards.py tests/test_universe.py -q
python3 tools/scan_pools.py --capital 3.4 --size 20 --top 15
```

The scan must produce a real table with real market names and real numbers. If the live call fails, fix the code, not the expectation. Do not hardcode any market, rate, or price.

Test coverage must assert the formula against the worked example in the docs: max spread 3 cents, bid 100 at 1 cent spread, bid 200 at 2 cents, ask 100 on the complement at 1 cent gives Q_one = 100*(2/3)^2 + 200*(1/3)^2 + 100*(2/3)^2.

## Constraints
- Python 3.11+ compatible. Standard library only.
- No file outside the list above may be created or modified.
- Do not touch `src/pmm/pricing/`, `src/pmm/execution/`, `src/pmm/risk/`, `src/pmm/monitor/`, or the deploy directory. Other workers own those.
- No credentials in the code. No printing of secrets.

## Report
Reply with the path of the scan output and the top 5 rows, plus any platform fact you found that contradicts `.research/poly-platform.md`. Flag surprises; do not fix another worker's file.

---
Role: implementer
Working directory: /home/da/桌面/polymarketMM
You are a worker, not an orchestrator. Do not run `herdr agent start`, `herdr pane split`, `herd-dispatch`, or spawn any peer agent. Answer in your final reply. If the output is long or is a deliverable, write a file and name that path in the reply.
