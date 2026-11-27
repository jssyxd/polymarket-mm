# Audit — Polymarket maker: what the evidence kills, what survives, and the reward-only re-plan

Date: 2026-11-27. Scope: `src/pmm/`, `tools/`, `docs/decisions/0001–0014`, `docs/paper-run-1.md`.
Status of the service: live trading stopped (`docs/decisions/0014-strategy-falsified.md:4`).

## 1. What is disproved

| Claim | Proof |
|---|---|
| "Both legs fill, so the pair merges for 1.00 and the edge is the spread." | `0014:26-29` — run 1: 78% naked shares (223.8 pairs vs 796.1 excess); run 2: 100% naked, zero pairs. `0014:50-59`: `fill_pair_rate ≈ 0`, EV collapses to the negative single-leg term. |
| "A paired fill earns 3c per set; the pair segment is profitable." | `0014:38-48` — paired segment −188.08 pUSD, single-leg segment −109.63 pUSD, total −297.74 pUSD; realised return −65% of cost. Even "both legs ≥5 shares" was lopsided (103.5 up vs 52.8 down). |
| "A resting bid is not directional risk." | `0013:30-35, 42-48` — one-sided fills were directional bets held to settlement; every large loss sat in a market resolving the same day it was quoted (the informed taker hits our resting bid). `0014:32-34`: in run 2 every fill was the cheap side (0.07–0.26); the expensive leg never filled. |
| "A quote commits only its cheaper leg (the pair funds itself on merge)." | `0001:31-34` — the venue reserves every resting buy and the legs sum to ~1, so a pair commits ~`size` pUSD. `0013:56-59`: the per-market cap must count both legs. The model still lives in `src/pmm/core/selection.py:14-17` and in the fallback `src/pmm/core/selection.py:155-157` (`size * min(up, down)`). |
| "Redeeming the 18 old positions recovers capital." | `0012:16-23` — every redeemed leg had `current_price = 0.0`; payout is 0. It clears the view, it does not recover pUSD. |
| "A taker round trip captures the spread." | `docs/paper-run-1.md:20-26` — 2,748 local and 7,454 VPS round trips, mean PnL −0.354 and −1.018 pUSD, best case −0.02; the cost floor is the spread, not the fee (`:29-34`). |
| "The reward band is a floor to quote toward." | `0002:22-26` — score is `((v−s)/v)²`; a quote at `s = 0.8v` scores 0.04 of maximum. `0002:30-38`: a 4.5c band produced a 6.4c half-spread, i.e. a quote earning zero on the pool it was picked for. |
| "The inventory skew (Avellaneda–Stoikov) leans the quote to flatten." | `src/pmm/pricing/quotes.py:153-159` — the shift is ~3e-6 of probability at `sigma_p = 0.0009, tau = 600`, i.e. below one tick (0.01); it can never move a price. |
| "The ToxicityGate compares our fair value against the book." | `src/pmm/engine/cycle.py:266` derives `fair_prob` from the same book (`size_cutoff_midpoint`, `src/pmm/data/universe.py:107-134`) and the gate compares it with that book's midpoint (`src/pmm/risk/gates.py:185-199`). There is no external oracle; the gate compares the book with itself. |

## 2. Modules to delete

| Path | Why (proof) | Replaced by |
|---|---|---|
| `src/pmm/pricing/pairing.py` (`expected_net_bps`, `paired_fill_pnl`, `unpaired_fill_exposure`), its re-exports at `src/pmm/pricing/__init__.py:19-23`, `tests/test_pairing.py` | The whole EV model assumes a positive `p_both_fill` (`pairing.py:19-24, 117-190`); measured `p ≈ 0` (`0014:26-29`). No production module imports it — only `pricing/__init__.py` and its own test. | Nothing. The reward-only net function in §4 replaces it. |
| `src/pmm/sim/taker.py`, `tests/test_sim_taker.py` | Only its own test imports it; it needs an oracle feed and resolved windows that do not exist (`docs/paper-run-1.md:46-50`), and the measured taker route loses money (`paper-run-1.md:20-26`). | Nothing, until resolved-window data exists. |
| `src/pmm/monitor/agent.py:139-184` (Rule 2: widen the spread when nothing filled), and the `half_spread_cents` widening knob at `src/pmm/engine/self_tune.py:39-46` | Widening a quote inside the band lowers the reward score quadratically (`0002:22-26`); a reward-only maker that widens on a quiet hour is buying a zero-scoring quote. | Rule that switches market, or holds the spread and re-ranks by expected reward per pUSD. |
| `src/pmm/pricing/quotes.py:235-246` (inventory skew) plus the `gamma` argument at `:129` | Magnitude below one tick (`quotes.py:153-159`); it also moves the quote away from the midpoint, which lowers the reward score. | Nothing. |
| `src/pmm/core/selection.py:14-17` and `:155-157` (cheaper-leg budget fallback) | Understates reserved collateral by ~half (`0001:13-15, 31-34`); `0013:56-59` requires both legs counted. | The both-legs model already present at `src/pmm/core/selection.py:249` (`size * (p_up + p_down)`), which `src/pmm/data/universe.py:209` already computes. |
| `src/pmm/execution/rescue.py`, `tools/rescue.py`, `deploy/pmm-rescue.*` | The completion buy cannot clear the venue's $1 BUY minimum at our size (`src/pmm/execution/rescue.py:38-41`, `README.md:154-157`: 20 shares at 1c = $0.20, rejected). | `src/pmm/execution/repair.py` (kept) with a deadline instead of a price-based age rule. |

Keep, but re-scope: `src/pmm/execution/repair.py:28` (`DEFAULT_MAX_AGE_SECONDS = 900`) is a stand-alone-lag rule, not a settlement rule — it must become "exit before resolution" (§5).

## 3. What survives (measured evidence only)

| Module | Evidence |
|---|---|
| Order signing, v2 envelope, heartbeat — `src/pmm/execution/clob.py:427-473`, `:475`, `:509`, `:604`; `src/pmm/execution/config.py` | `0011:19-22` — `signature_type=1`, maker = proxy, signer = owner key, accepted, `status: live`. `0014:63-65` lists signing as worth keeping. |
| Capital guard — `src/pmm/engine/runner.py:471-495` (`_affordable`), `:497-536` (`_place`) | `0011:33-45` — reads real venue collateral each cycle, drops unfundable legs and journals `order_skipped`. Caveat: it is **not pair-atomic** (`runner.py:485-495` can keep leg 1 and drop leg 2 → a naked resting leg). |
| Venue inventory — `src/pmm/execution/positions.py:115-153`; `src/pmm/engine/runner.py:72-83`, `:321-362` | `0012:43-53` — the journal-only view reported a flat book while 19.6 pUSD was held; inventory must come from the venue. |
| Merge — `src/pmm/execution/merge.py:39-74`, `:88-141`; `deploy/pmm-merge.timer` | `0013:24-26` — 107.91 pUSD came back from the London/Milan sales at 0.999. Monetises winners; cannot rescue losers. |
| Harvest — `src/pmm/execution/harvest.py:62-75`, `:78-119`; SELL invariant `src/pmm/engine/runner.py:445-462` | `README.md:172-184` — two 0.99 limit sells filled at 0.999 with `fee_bps = 0`. |
| Redeem — `src/pmm/execution/redeem.py:192-225`, `:238-296` | `0012:16-23` — the path works for a POLY_PROXY wallet (20 positions → 19); losers pay 0. |
| Alerts — `src/pmm/monitor/alerts.py:205-208`, `:217-277` | `README.md:200-207` — unpaired exposure, cash floor, single-leg flow share, account unreachable. |
| Journal + venue fill sync — `src/pmm/execution/journal.py:64-149`; `src/pmm/execution/trades.py:104-137` | `0014:7-12` — every number in the falsification comes from the journal synced out of the venue trade list. |
| Reward scoring and market selection — `src/pmm/data/rewards.py:50-97`; `src/pmm/data/universe.py:185-199`, `:209` | `0004:49-60` — the venue's `market_competitiveness` is the correct denominator (book-rebuild was 219× too large) and candidates are ranked by expected pUSD/day. |

## 4. Zero-risk target function

Per market, per day:

```
net = reward + merge − single_leg_loss − fee
reward        = Σ_m rate_per_day(m) · q_min_ours / (q_min_ours + market_competitiveness(m))
                for every market where both bids rest inside rewards_max_spread with size ≥ rewards_min_size
merge         = Σ_pairs merged_size · (1 − (bid_up + bid_down))      # complete set redeems for exactly 1.00
single_leg_loss = Σ_unpaired legs  stake · 1[resolved against us before the exit]
fee           = taker fees on any exit + merge/redeem gas (relayer is gasless)
```

`single_leg_loss = 0` iff, at every instant of resolution, the position is **flat or a complete set** — never exactly one leg. Three conditions make that true:

1. **No leg survives to settlement.** Every resting bid is cancelled and every filled leg is closed strictly before the market's resolution time. Today only the *entry* side is guarded (`src/pmm/engine/runner.py:54`, `:151-167`, `:174`: `min_hours_to_resolution = 24`); a fill on a 25-hour market is still held into settlement. A deadline rule is required (§5).
2. **The close is cost-neutral by construction.** The exit completes the set — buy the complement while `entry_cost + ask + fee ≤ 1.00` (`src/pmm/execution/repair.py:31`, `:55-122`) — so the pair merges for exactly 1.00 and the loss is provably ≤ 0. A single-leg sell is only safe at ≥ 0.99 (`src/pmm/execution/harvest.py:62-75`); selling a losing leg at ~0 loses the whole stake.
3. **The venue's $1 BUY minimum is respected**, otherwise condition 2 cannot be executed at our size (`README.md:154-157`).

If the completion cannot be executed (book moved, minimum notional, outage), the residual is the spread-sized premium, not the stake — and it must be reported, not assumed away.

**Residual risks that cannot be removed**

- **Adverse fill.** Any resting bid may be filled by an informed taker into a falling token (`0013:42-48`, `0014:32-34`). The exit rule bounds it; it does not remove it.
- **Reward formula change.** The venue can change the scoring formula, the band or the minimum size; a 2026-11-20 rule change already removed the maker-side rebate (`0004:83-86`). The reward is a venue policy, not a contract.
- **Venue / infrastructure risk.** Relayer or API outage freezes capital recycling (`src/pmm/execution/merge.py:8-10`); a lapsed heartbeat cancels every open order on the API key (`src/pmm/engine/runner.py:5-8`, `:669-678`).

## 5. Reward-only design

Both buy sides are quoted inside the band at or above the reward minimum; the pair margin is a bonus, never the business model.

| Rule | Parameter | Where it lives now / must live |
|---|---|---|
| Quote UP and DOWN, both `BUY`, both post-only | `half_spread_cents` ≤ 0.8 × `rewards_max_spread_cents` | `src/pmm/engine/self_tune.py:41`; clamp at `src/pmm/pricing/quotes.py:200-224`; BUY-only invariant `src/pmm/engine/runner.py:463-467` |
| Size at or above the reward minimum | `size_shares ≥ rewards_min_size` | `src/pmm/pricing/quotes.py:267-271`; market rejected otherwise at `src/pmm/core/selection.py:216-221` |
| Bands the market may have | `max_spread_cents` (cap) | `src/pmm/engine/runner.py:107`; `src/pmm/core/selection.py:206-214` |
| Quote off the **venue** midpoint, not the size-cutoff book midpoint, or the order scores zero | `venue_midpoint` | read at `src/pmm/engine/runner.py:213-214`; the quote is currently built from `size_cutoff_midpoint` (`src/pmm/engine/cycle.py:266`) — must change |
| Never hold a leg into settlement | `min_hours_to_resolution` (entry) **and** `max_leg_hold_hours` (exit deadline, new) | entry: `src/pmm/engine/runner.py:54`, `:151-167`; exit deadline: replaces the age rule at `src/pmm/execution/repair.py:28` |
| Merge as soon as both legs are held | `merge_interval` ≤ reward sampling epoch | `deploy/pmm-merge.timer` (`OnCalendar=*:0/3`), `src/pmm/execution/merge.py:88-141` |
| Exit flat otherwise | `pair_exit_cost_max = 1.00` (complete the set), `harvest_floor = 0.99` (sell a winner) | `src/pmm/execution/repair.py:31`; `src/pmm/execution/harvest.py:32` |
| One pair of capital per market, atomic | `max_market_usd`, `inventory_box`, **pair-atomic capital guard** | `src/pmm/core/selection.py:249-255`; `src/pmm/engine/runner.py:471-495` must drop *both* legs of a pair if either is unfundable |
| Rank markets by expected reward per pUSD, not by pool rate | `est_share_pct`, `rate_per_day` | `src/pmm/core/selection.py:181-187`; `0004:36-47` |

Kill switches that stay: single-leg fill share > 50% (`src/pmm/monitor/alerts.py:208`), cash floor (`src/pmm/monitor/alerts.py:205`), unpaired exposure above the box (`src/pmm/monitor/alerts.py:240-249`). Under reward-only the single-leg alert is the primary one, because one leg is the whole risk.

## 6. Open questions that need data, not opinion

1. **Has a reward ever actually been paid?** `0005:40-47` and `0004:79-86`: earnings 0 across every date, and no account-side evidence that the 2026-11 settings pay at all. Needed: one epoch of resting orders plus `/rewards/user/markets` for the same epoch.
2. **Which midpoint does the venue score against** — the CLOB midpoint or the size-cutoff midpoint? Our quotes are built off the latter (`src/pmm/engine/cycle.py:266`). Needed: our resting order price vs the venue's own per-epoch score.
3. **What reward does a 20-share quote actually capture** in the thin-competition markets `0004:41-47` and `0005:28-32` predicted at ~462 pUSD/day? Needed: epoch score, not the estimate.
4. **How adverse are our fills?** `0014:32-34` says the cheap side always fills. Needed: fill price vs the midpoint of the same leg over a full reward epoch, to size the exit premium.
5. **Which fee governs an exit on a reward-eligible market** — the market config's 1000 bps (`0012:57-60`) or the measured `fee_bps = 0` (`README.md:180-182`)? Needed: one measured taker fill on such a market, since the fee decides whether `pair_exit_cost_max = 1.00` is achievable.
