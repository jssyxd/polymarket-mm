# GLFTmm architectural deep dive

Scope: the repository at `GLFTmm/` (23 commits on `main`, 2026-11-01 → 2026-11-09). All paths are relative to the repo root. Everything below was read from source; every number I quote was reproduced locally with the repo's own code (see §9 for the verification script and its output). Where the code does not settle a question I say so explicitly instead of guessing.

Headline for a Polymarket port: **the pricing layer is not doing the work the README claims it does.** The GLFT spread output is pinned by a constant minimum-spread hurdle, the inventory term is numerically inert at any realistic volatility, and the fee hurdle uses a fee rate 5x the one the repo's own live fill log shows. The parts that actually protect the P&L are the hard gates (inventory box, one-sided cooldown, toxicity cut, session pause), and those are the portable part.

---

## 1. Module map

| Path | Purpose (one line) |
|---|---|
| `shared/glft_engine/glft_solver.py` | `StationaryGLFTSolver`: stationary GLFT reservation price + half-spreads with a fee floor (`compute_reservation_price` `:18`, `compute_optimal_spreads` `:38`). |
| `shared/toxic_gate/causal_features.py` | Reads the `W:\database` parquet lake, computes OFI / rolling vol / a future-looking toxicity label (`:44`). |
| `shared/sentinel/market_regime_sentinel.py` | L2 book sentinel: fee floor, top-5 depth, OBI, micro-vol, 4-state regime with `allow_quote`/`allow_open` (`evaluate_regime` `:86`). |
| `shared/aggregator/micro_aggregator.py` | Compresses L2 + trades into 1-second feature rows for Kaggle retraining (`:15`). |
| `01_crypto_altcoin_perp_mm/models/vpin_gate.py` | `VPINCalculator` (`:5`) volume-bucketed toxicity + `DefensiveCooldownManager` (`:63`) 5s one-sided freeze. Not imported anywhere. |
| `02_rwa_tokenized_equity_mm/core/hyperliquid_sndk_live.py` | The only live engine: dual-WS `xyz:SNDK` HIP-3 maker, post-only, LightGBM gate, inventory box (`HyperliquidDualWSProductionMM` `:126`, loop `:315`). |
| `02_rwa_tokenized_equity_mm/core/hyperliquid_quota_guard.py` | L1 request-quota accounting + a self-trade "refill" to mint quota + 500ms/1500ms watchdog (`:54`). Not wired to the engine. |
| `02_rwa_tokenized_equity_mm/core/micro_optimizer.py` | 2h/100-fill observer that scores realised spread and writes "no improvement / overfit" verdicts to a JSONL log (`:134`). |
| `02_rwa_tokenized_equity_mm/regime/regime_classifier.py` | `RWARegimeClassifier` with integer regimes 0/1/2 + Monday gap window (`:4`). Not imported by the live engine. |
| `02_rwa_tokenized_equity_mm/models/lgbm_toxicity_gate_SNDK.txt` | 30-tree LightGBM binary model, features `px_rel sz vol_10 side_buy` (`:feature_names=`). |
| `02_rwa_tokenized_equity_mm/backtest/sndk_real_fills_20261102.csv` | 247 real mainnet fills, 2026-11-02 10:19:16 → 12:58:15 UTC (the only live evidence in the repo). |
| `02_rwa_tokenized_equity_mm/core/hyperliquid-sndk.service`, `hyperliquid-optimizer.service` | systemd units pointing at `/opt/nautilus_cluster/` (not the repo path). |
| `03_dex_concentrated_lp_mm/hedging/concentrated_lp_manager.py` | Uniswap-V3 tick-range placement from a reservation price + spot/perp delta hedge size (`:11`, `:31`). |
| `experiments/matrix_backtest/matrix_engine.py` | `run_causal_simulation` `:18`: tick-level causal simulator with 4 strategy modes. |
| `experiments/matrix_backtest/run_matrix_benchmark.py` | 3-symbol matrix + fee stress + 500x block-bootstrap Monte Carlo (`:38`). |
| `experiments/matrix_backtest/run_all_assets_benchmark.py` | 13-symbol matrix, IS/OOS split only, no stress tests (`:46`). |
| `experiments/matrix_backtest/results/master_matrix_summary.json` | Committed summary for WOO / CORE / XYZ_NVDA. |
| `experiments/matrix_backtest/results_all_assets/all_assets_matrix_summary.json` | Committed summary for 13 symbols. |
| `audit_reports/OMP_INSPECTOR_0{1,2,3}_*.md` | Three external inspector verdicts (causality, fees, overfitting). |
| `kaggle_pipeline/kaggle_trainer_bridge.py` | Writes `~/.kaggle/kaggle.json`, generates kernel metadata, and a *simulated* offline A/k calibration (`:59`). Makes no Kaggle API call. |
| `scripts/ingest_cryptohftdata_lake.py`, `scripts/ingest_90d_deep_lake.py` | Download + timestamp-normalise CryptoHFTData parquet into `W:\database\01_raw_lake`. |
| `scripts/verify_lake_governance.py` | Walks the lake, checks monotonic timestamps + non-null price/qty, writes `manifest_governance.json` (`:10`). |
| `tests/test_regime_sentinel.py`, `tests/test_kaggle_bridge.py` | The only tests: sentinel regimes, aggregator bucketing, bridge metadata. 8 tests, all pass. |
| `20261101对话.html`, `20261102对话.html` | Full operator/agent transcripts (the richest unmined source of design intent). |

Dead / unreachable from the live path: `01_crypto_altcoin_perp_mm/models/vpin_gate.py`, `02_rwa.../core/hyperliquid_quota_guard.py`, `02_rwa.../regime/regime_classifier.py`, `03_dex_concentrated_lp_mm/hedging/concentrated_lp_manager.py`, `shared/sentinel/market_regime_sentinel.py` (tests only), `shared/aggregator/micro_aggregator.py` (tests only), `kaggle_pipeline/` (tests only). Verified by grepping every `import` in the tree: no module imports the sentinel, the aggregator, the quota guard, the VPIN gate, the LP manager or the regime classifier except the test files.

The README's directory tree (`README.md:14-37`) advertises branches that do not exist in the tree: `shared/data_lake_client/`, `01_crypto_altcoin_perp_mm/core/`, `01_crypto_altcoin_perp_mm/backtest/`, `03_dex_concentrated_lp_mm/core/`, `03_dex_concentrated_lp_mm/backtest/`. `shared/data_lake_client/` is the client the README's governance section depends on (`README.md:67-70`); the only lake code present is the three scripts under `scripts/`. The README also describes a `Left-Open / Right-Close` timestamp shift `T_event_close = T_parquet_left_open + ΔT_bar` (`README.md:70`); grepping for `left_open`, `event_close`, `T_bar` finds **no implementation anywhere** in the tree, and `scripts/ingest_cryptohftdata_lake.py:74-77` only converts `event_time`/`trade_time` to UTC and sorts.

---

## 2. Pricing math as implemented

### 2.1 The shared solver (`shared/glft_engine/glft_solver.py`)

Public surface: `StationaryGLFTSolver(gamma=0.5, fee_maker_bps=2.0, min_spread_bps=8.0, q_max=5.0)` `:12`; `compute_reservation_price(micro_price, q, sigma) -> float` `:18`; `compute_optimal_spreads(micro_price, q, sigma, A_ask=2.0, k_ask_bps=1.5, A_bid=2.0, k_bid_bps=1.5) -> (delta_ask_price, delta_bid_price)` `:38`. The solver is stateless and side-effect free.

Reservation price, `:35`:

```python
skew = q * self.gamma * (sigma ** 2) * lambda_inv * micro_price
return micro_price - skew
```

`lambda_inv` is a three-step amplifier on `|q|/q_max`: `1.0` below 60%, `3.0` at 60%, `8.0` at 80% (`:27-32`).

Half-spreads, `:48-54` (bid at `:52-54`, ask at `:48-50`):

```python
term_ask_base_bps = (1.0 / self.gamma) * np.log(1.0 + self.gamma / max(k_ask_bps, 0.1)) * 6.0
term_ask_inv_bps  = ((2.0 * q + 1.0) * self.gamma * (sigma ** 2) * 10000.0) / (2.0 * max(k_ask_bps, 0.1) * max(A_ask, 0.1))
delta_ask_bps = max(1.0, term_ask_base_bps + term_ask_inv_bps)
term_bid_base_bps = (1.0 / self.gamma) * np.log(1.0 + self.gamma / max(k_bid_bps, 0.1)) * 6.0
term_bid_inv_bps  = ((2.0 * q - 1.0) * self.gamma * (sigma ** 2) * 10000.0) / (2.0 * max(k_bid_bps, 0.1) * max(A_bid, 0.1))
delta_bid_bps = max(1.0, term_bid_base_bps - term_bid_inv_bps)
```

Fee hurdle, `:56-60`:

```python
min_half_hurdle_bps = max(self.min_spread_bps / 2.0, self.fee_maker_bps * 2.0)
final_delta_ask_bps = max(delta_ask_bps, min_half_hurdle_bps)
final_delta_bid_bps = max(delta_bid_bps, min_half_hurdle_bps)
```

Output units are **price space**, `:62-64`:

```python
delta_ask_price = micro_price * (final_delta_ask_bps * 0.0001)
delta_bid_price = micro_price * (final_delta_bid_bps * 0.0001)
```

So the solver returns two *absolute price offsets* (not prices, not bps). Callers add them to a price: `bid_quote = r_price - d_bid` (`experiments/matrix_backtest/matrix_engine.py:67`).

### 2.2 The live engine has its own copy of the math

`02_rwa_tokenized_equity_mm/core/hyperliquid_sndk_live.py:91-124` defines a second `StationaryGLFTSolver` that is **not** the shared class. Differences that matter:

* `lambda_inv` breakpoints are `0.8 / 0.5` (`:100-103`) vs `0.8 / 0.6` in the shared solver (`shared/glft_engine/glft_solver.py:27-32`). Same intent, different numbers.
* The live copy returns **prices**, not deltas (`:122-123`):

```python
bid_p = round(r_price - mid_price * (d_bid_bps * 0.0001), 1)
ask_p = round(r_price + mid_price * (d_ask_bps * 0.0001), 1)
```

  Rounding is to 1 decimal place, i.e. tick 0.1 USD (`self.min_tick = 0.1` `:161`).
* It applies the regime multiplier *after* the floor (`:112`, `:116`) and re-applies a `spread_mult`-scaled hurdle (`:118-120`):

```python
min_half = max(self.min_spread_bps / 2.0, self.fee_maker_bps * 2.0) * spread_mult
```

### 2.3 How `A_a/A_b` and `k_a/k_b` are actually calibrated

They are not. `A_ask/A_bid/k_ask_bps/k_bid_bps` are constructor arguments with hardcoded defaults `2.0 / 1.5` (`:38-40`), and **every call site passes the defaults**: `matrix_engine.py:65,73,87` (`A_ask=2.0, k_ask_bps=1.5`), live `compute_quotes(..., k_bps=1.5, A=2.0)` `:98`.

The only "calibration" code in the tree is `kaggle_pipeline/kaggle_trainer_bridge.py:59-95`:

```python
"A_arrival": round(max(1.0, 50.0 / max(med_spread, 5.0)), 3),
"k_decay":   round(max(0.8, med_spread * 0.18), 3),
```

* It is a **stub**: with no input file it returns hardcoded `A=3.85, k=2.15` (`:66-67`); it never contacts Kaggle (no `urlopen` anywhere in the file despite `import urllib.request` `:11`); it writes `~/.kaggle/kaggle.json` on construction (`:31-39`).
* Nothing imports it except `tests/test_kaggle_bridge.py`, which feeds it a synthetic JSONL of `spread_bps`.
* Its `k` is in "spread units" (`med_spread * 0.18`), which is not the dimensionless ratio the solver puts inside `ln(1+γ/k)`. So even if wired, the units would not line up.

Also note the internal contradiction: the solver docstring (`:9`) says `k` has dimension `[1/price_spread]` and that "if the fill probability decays 10% per 1 bps, k_bps ≈ 1000", while the code uses `k=1.5` as a pure number and multiplies the dimensionless log term by an unexplained `6.0` fudge to call the result "bps". The README's own formula (`README.md:49`) has no `6.0` factor. **Unclear from code** where 6.0 comes from; it is the single constant that sets the base half-spread (3.4522 bps at γ=0.5, k=1.5).

### 2.4 How `sigma` enters, and what it actually is

`solver.compute_reservation_price` treats `sigma` as a **return stdev**: the skew is `q γ σ² λ P`, i.e. a variance scaled by price. `solver.compute_optimal_spreads` treats the same `sigma` as a **price-space volatility** in the classic `(2q±1)γσ²(T−t)/(2kA)` shape, with `σ²·10000` inserted to convert to bps. The two usages are dimensionally inconsistent with each other and with the classical formula (where `σ²(T−t)` has units of price²).

What the callers pass:

* Backtest: `sigma = df["rolling_vol"]` = stdev of log returns over 50 trades (`shared/toxic_gate/causal_features.py:58-59`, `.fillna(0.0001)`), passed at `matrix_engine.py:64,72,84`.
* Live: `sigma = max(0.0005, np.std(np.diff(np.log(self.price_history))))` where `price_history` holds up to 50 mid prices pushed from the L2 socket (`hyperliquid_sndk_live.py:195-197,353`).

**Consequence, measured:** with `sigma` at these magnitudes the inventory terms are ~1e-9 (reservation price) and ~1e-3 bps (spread). I re-ran the shared solver over q ∈ {0,1,3,4,5} and σ ∈ {5e-4 … 1e-1} with defaults: the returned half-spreads were **identical (0.46712 USD = 4 bps) for every q and every σ below 0.1**. The live copy with its real parameters (γ=0.5, fee=1.5, min_spread=8, q_max=0.05, σ=1e-4, mult=1.5) returns `bid=1167.1 ask=1168.5` for inventory **+0.05 and −0.05 alike**. The quote is a function of mid and the regime multiplier only.

### 2.5 The fee-endogenous hurdle as coded vs as advertised

| Claim | Where claimed | As coded |
|---|---|---|
| `δ_half ≥ max(δ_GLFT, Fee_maker × 2.5, Min_Tick)` | `README.md:57` | `max(min_spread_bps/2, fee_maker_bps × 2.0)` — `shared/glft_engine/glft_solver.py:57`, `hyperliquid_sndk_live.py:118`. Multiplier is **2.0**, not 2.5; there is **no Min_Tick term**; the third term is `min_spread/2`. |
| fee floor ×2.5 | `README.md:58` | Only in the sentinel, and there it is ×2.5 of the *round-trip* fee (`market_regime_sentinel.py:32`: `total_roundtrip_fee_bps * 2.5` → 10 bps for a 2 bps maker). |
| half-spread ≥ 2× maker fee | `audit_reports/OMP_INSPECTOR_02_FEES_STRESS_REPORT.md:15` | Matches the code (×2.0) but still lists a `Min_Tick` term that does not exist. |

So: **2.0 not 2.5, no tick term.** The `2.5` in the README is the sentinel's round-trip convention leaking into the solver's documentation.

### 2.6 Backtest-side fee check (different from the solver's)

`experiments/matrix_backtest/matrix_engine.py:100-103`:

```python
min_fee_hurdle = curr_p * maker_fee_rate
if (curr_p - bid_quote) < min_fee_hurdle or (ask_quote - curr_p) < min_fee_hurdle:
    continue
```

Three defects:

1. It compares against **one** side's fee, while the solver requires 2× (round trip).
2. It measures from the *last trade price* `curr_p` to the quote, but the quote is anchored to `r_price`, which contains the inventory skew. When `r_price > curr_p` (short inventory) `curr_p - bid_quote` goes negative and the whole tick is skipped. I reproduced this: at q=−1 with σ=0.05 the bid leg is skipped outright; the asymmetry flips with the sign of `q`.
3. `continue` skips the entire tick, so both sides go silent, not just the offending one.

---

## 3. The risk stack, gate by gate

### 3.1 Live engine (`02_rwa_tokenized_equity_mm/core/hyperliquid_sndk_live.py`)

| # | Gate | Trigger | Action | Location |
|---|---|---|---|---|
| R1 | US regular-hours pause | session == `REGULAR_MARKET_HOURS` and `PAUSE_ON_REGULAR_STOCK_HOURS=True` | cancel all orders, sleep 10s, skip the cycle | `:57`, `:79-81`, `:320-330` |
| R2 | 8.5 bps sniper drift | `abs(mid - last_seen_mid)/last_seen_mid*1e4 >= 8.5` and there are open orders | cancel all, sleep 3s, skip the cycle | `:342-351` |
| R3 | Account value floor | `acc_val < 5.0` | stop quoting that cycle (no cancel) | `:356-359` |
| R4 | Crossed-book clamp | `target_bid >= best_ask` / `target_ask <= best_bid` | pull bid to `best_ask - 0.1`, ask to `best_bid + 0.1` | `:364-367` |
| R5 | 5s one-sided cooldown | `now - last_{bid,ask}_fill_time < 5.0` | drop that side's quote (and cancel the resting order) | `:158-160`, `:226-229`, `:372-374`, `:381-382`, `:392-393`, `:403-404` |
| R6 | LightGBM toxicity cut | `p_toxic_down > 0.60` → bid cut; `p_toxic_up > 0.60` → ask cut | drop that side's quote | `:376-382` |
| R7 | Inventory box | `inv < Q_MAX` required to quote bids, `inv > -Q_MAX` to quote asks (Q_MAX=0.05) | drop that side | `:381-382`, `:53` |
| R8 | Emergency de-inventory | `inv > Q_MAX` | bid cut **and** ask re-anchored to `max(best_bid+0.1, best_ask)` (passive, does not cross) | `:384-386` |
| R9 | Fee / min-spread hurdle | inside `compute_quotes` | widen to `max(min_spread/2, 2×fee) × regime_mult` | `:110-120` |
| R10 | Inventory skew | inside `compute_quotes` | `r_price = mid - inv γ σ² λ mid` | `:107-108` |
| R11 | Queue-preserving replace | `abs(cur_px - target_px) > min_tick*1.5` | cancel + repost at target | `:399`, `:410` |
| R12 | Post-only | always | `order_type={"limit": {"tif": "Alo"}}` | `:294` |
| R13 | Exception swallow | any exception in the cycle | log, sleep 2s, continue (orders left as-is) | `:421-423` |

R5 is the only "5 second" mechanism in the live path. `01_crypto_altcoin_perp_mm/models/vpin_gate.py:63-88` implements a semantically identical `DefensiveCooldownManager` and is **not imported**; the live engine reimplements the same idea inline.

### 3.2 Backtest engine (`experiments/matrix_backtest/matrix_engine.py`)

| # | Gate | Trigger | Action | Location |
|---|---|---|---|---|
| B1 | Fee hurdle | `(curr_p - bid_quote) < fee` or `(ask_quote - curr_p) < fee` | `continue` — skip the whole tick | `:100-103` |
| B2 | Tick cooldown | `i - last_{bid,ask}_fill_tick < cooldown_ticks` (default 10 ticks, never overridden) | block that side | `:105-112` |
| B3 | Inventory box | `inventory >= q_max` / `<= -q_max` (q_max=5.0 units) | block that side | `:114-118` |
| B4 | OFI toxic widening | `abs(ofi) > 0.6` | double the spread on the side the flow points at | `:90-94` |
| B5 | OFI momentum skew | always in `DEFENSIVE_GLFT_MATRIX` | `r_price += curr_p * ofi * 0.0001` | `:86` |
| B6 | Hybrid mode switch | `abs(inventory)/q_max >= 0.5` | switch A-S → GLFT spreads | `:71-73` |

`vpin_threshold` is accepted as a parameter (`:27`) and **never used in the body**. There is no VPIN in the backtest, no 5-second cooldown (only a 10-tick one), and no inventory-based emergency unwind. `DEFENSIVE_GLFT_MATRIX` = GLFT + OFI skew + OFI widening, nothing more.

### 3.3 Sentinel (not in the live path)

`shared/sentinel/market_regime_sentinel.py:86-215`, `allow_quote`/`allow_open` per state:

| Regime | Trigger | allow_quote | allow_open |
|---|---|---|---|
| `DEPTH_INSUFFICIENT` (panic) | top-5 min depth < `panic_depth_usd` (500) | false | false |
| `DEPTH_INSUFFICIENT` | top-5 min depth < `min_depth_usd` (1500) | only if `abs(inventory_usd) > 1.0` | false |
| `HALT_TOXIC` | `toxic_prob >= 0.70` or `abs(flow_imb) > 0.85` | false | false |
| `EXPAND_SPREAD` | `vol_bps > 20` or `toxic_prob >= 0.55` | true | true (spread × 1.8 floor) |
| `HEALTHY_MM` | otherwise | true | true |

Also: empty or crossed book → `DEPTH_INSUFFICIENT` (`:103-127`). Fee floor `maker_fee_bps*2*2.5` (`:32`).

### 3.4 Quota guard (not in the live path)

`02_rwa_tokenized_equity_mm/core/hyperliquid_quota_guard.py`: quota = `10000 + int(cumulative_taker_volume_usd) - consumed_requests` (`:73-80`); critical at ≤15% remaining (`:82-88`); the "self-heal" is a BTC buy-then-sell round trip to mint quota (`:94-160`), with pre-flight depth/spread checks (`:162-188`) and a 500ms / 1500ms two-stage watchdog (`:213-258`). The `client.order(...)` calls use `symbol=`/`reduce_only=` kwargs (`:127-132`, `:202-208`), which is **not** the Hyperliquid SDK signature used by the live engine (`name=`/`is_buy=`/`limit_px=`/`order_type=`, `hyperliquid_sndk_live.py:289-295`), so the guard targets a different, unspecified client.

### 3.5 Runtime gates in the shared modules that nothing enforces

`shared/toxic_gate/causal_features.py` computes a toxicity label from the future (`:61-64`):

```python
future_ret = (df["price"].shift(-10) - df["price"]) / df["price"]
df["is_toxic_flow"] = (np.abs(future_ret) > 0.0005).astype(int)
```

This is fine as a *label* and the engine never reads it, but it sits in the same frame as the features, so any future use of `is_toxic_flow` inside a decision path would be look-ahead.

---

## 4. The live execution loop as implemented

`run_strategy_cycle` (`hyperliquid_sndk_live.py:315-423`), one iteration per second (`time.sleep(1)` `:419`; the comment "毫秒级循环缩短至 1 秒" `:419` is self-contradictory).

**Order lifecycle.**

1. Session gate → `get_market_session()` returns `(tag, spread_mult, allow_trade)` (`:320`, classifier `:59-89`). If `allow_trade` is false (US regular hours) → `cancel_all_orders()`, sleep 10 (`:323-330`).
2. Snapshot `open_orders` **once** at the top of the cycle (`:321`) and `latest_mid/best_bid/best_ask` under `self.lock` (`:333-336`).
3. Compute quotes: `target_bid, target_ask = self.solver.compute_quotes(mid, inv, sigma, spread_mult=spread_mult)` (`:362`), then clamp against the best bid/ask (`:364-367`).
4. Size: `sz = round(max(0.010, ORDER_NOTIONAL_USD / price), 3)` (`:369-370`) → 0.010 shares ≈ 11.7 USD notional at 1167.
5. Per side: if not allowed → cancel the resting order (`:392-393`, `:403-404`); if allowed and no order → place (`:396`, `:407`); if allowed and the resting price differs by more than 1.5 ticks → cancel + repost (`:399-401`, `:410-412`).
6. Heartbeat log + sleep 1s (`:414-419`).

**Post-only.** Enforced at the venue, not locally: `order_type={"limit": {"tif": "Alo"}}` (`:294`). The local clamp (R4) is only a crossed-book sanity check against a possibly stale WS snapshot. **Post-only rejections are not handled**: `place_order_safe` returns the raw response (`:296-297`) and the caller never inspects `statuses`, so a rejected `Alo` is silently a no-op and the loop simply tries again next cycle.

**Inventory tracking.** From REST, not from fills: `get_account_state()` POSTs `clearinghouseState` and reads `assetPositions[].position.szi` (`:236-257`), polled once per second at `:354`. The private fills channel does **not** touch inventory; it only records `last_bid_fill_time` / `last_ask_fill_time` (`:219-229`). `szi` sign = position sign (long positive), which matches the solver's convention (positive `q` → lower reservation price → sell more). Note the fills CSV shows `startPosition` up to **+0.16** against `Q_MAX = 0.05` — a 3.2× overshoot of the stated hard limit during the logged session (that session predates the current `Q_MAX`, see §8).

**One-sided fill.** Three mechanisms, in order of effect:
1. Cooldown (R5): the side that was just filled is frozen for 5s. Note this freezes the *filled* direction — after a bid fill you stop bidding (you are now long, so this is inventory-reducing, not inventory-adding). The cooldown timer starts at WS *receipt* time, not exchange fill time (`:219`).
2. Inventory box (R7): bid quotes suppressed at `inv >= Q_MAX`.
3. Emergency de-inventory (R8): only for `inv > Q_MAX`, and it only re-anchors the ask to the touch — it is a passive maker exit, it does not cross the spread and does not size up. A short-side overshoot (`inv < -Q_MAX`) has no equivalent path; the ask side is simply suppressed.

**Disconnects.** Both WS threads reconnect in an infinite loop with a 2s sleep (`:198-200`, `:230-232`). There is **no staleness check on the market feed**: if channel 1 dies, `latest_mid` keeps its last value and the loop keeps quoting off it; R2 cannot fire because `last_seen_mid` is equally stale. If the private fills channel dies, the 5s cooldown silently stops working (nothing else sets those timestamps). REST calls use `timeout=5` and are wrapped in try/except returning defaults (`:255-257`, `:269-271`): a failed `clearinghouseState` returns `inv=0.0, acc_val=0.0`, which trips R3 (`acc_val < 5.0`) and stops quoting — fail-safe, but it also silently zeroes inventory, so if R3 were ever relaxed the bot would believe it is flat.

**API quota.** No quota accounting in the live path. The loop issues 2 REST calls per second (`openOrders` `:263`, `clearinghouseState` `:240`) plus cancels and places, i.e. ≥120 info requests/minute before order traffic. The quota guard that models this (`:73-80`) is a separate module with an incompatible client API and is never imported.

**Watchdog.** None in the MM loop. The only watchdogs in the repo are the quota guard's 500ms/1500ms leg-2 timers (`:213-258`), which protect the BTC self-trade, not the maker. The systemd unit provides `Restart=always` / `RestartSec=5` (`hyperliquid-sndk.service`).

**Toxicity gate wiring (and its limits).** `predict_toxicity` (`:302-313`) builds

```python
feats = np.array([[px_rel, 0.010, sigma, 1 if is_buy_side else 0]])
```

against model features `px_rel sz vol_10 side_buy` (model file `feature_names=`). `px_rel = (mid - mean(last 10 mids))/mid` (`:306-307`), `sigma` is the live mid-return stdev, `sz` is the hardcoded 0.010, and `is_buy_side` becomes `side_buy`. The same single sigmoid is therefore used for both directions: `p_toxic_down = predict(side_buy=1)` and `p_toxic_up = predict(side_buy=0)` (`:376-377`). I swept the model over `px_rel ∈ [-0.004, 0.004] × sigma ∈ [1e-5, 1e-2]`:

* `side_buy=0` (the ASK_CUT path): predicted probability never exceeds **0.0171** → the 0.60 threshold is unreachable, so `ASK_CUT` is effectively dead code.
* `side_buy=1` (the BID_CUT path): exceeds 0.60 only for `px_rel ≳ 0.00145` (≈14.5 bps above the 10-message mean); max observed 0.8069.

The model uses features 0, 2, 3 in its splits (`sz` is never split on), so the hardcoded `sz` is harmless. There is no training script in the repo, so **what the label was** (toxic direction, future toxic move, or something else) and how `side_buy` was encoded is unclear from code. The CHANGELOG claims the model was trained on the 247 fills (`CHANGELOG.md:27`) — i.e. on the same fills it then traded.

---

## 5. The backtest engine

`experiments/matrix_backtest/matrix_engine.py:18-199`.

**What it claims.** Strict causality: quote at tick `i`, fill only against tick `i+1`; no `bfill`; no same-bar crossing (docstring `:1-7`, mirrored in `run_all_assets_benchmark.py:6-12`).

**What it does.**

* Inputs are a parquet lake under `W:\database\01_raw_lake\{exchange}\{symbol}\{data_type}\*\*.parquet` (`shared/toxic_gate/causal_features.py:6,9`), symbols sanitised `:`→`_` by the ingest scripts. **The whole backtest is Windows-path-bound and cannot run on this machine**; the committed JSONs are the only artefact.
* Feature set consumed: `price`, `ts_ms`, `ofi`, `rolling_vol`, `side` (`:33-37`). `ofi` is a 50-trade volume imbalance normalised to [-1,1] (`causal_features.py:52-55`); `rolling_vol` is the 50-trade stdev of log returns, `fillna(0.0001)` (`:58-59`); `side` is aggressor side from `is_buyer_maker` (`:41-43`).
* Fill model (`:120-161`): a bid fills if the **next** tick is an aggressive sell with `next_p <= bid_quote`; an ask fills if the next tick is an aggressive buy with `next_p >= ask_quote`. Fill size is a constant `1.0` unit (`:123`). Fill price is the quote, not the print. Fee = `maker_fee_rate × quote × 1.0`, paid on both sides (`:127`, `:146`).
* Accounting: `cash -= (px + fee)` on buys, `cash += (px - fee)` on sells (`:128`, `:147`); `final_equity = cash + inventory * final_price` (`:163-164`).
* Four modes (`:57-98`): `PURE_AS` (A-S skew + fixed half-spread), `PURE_GLFT` (solver), `AS_GLFT_HYBRID` (switch at 50% of box), `DEFENSIVE_GLFT_MATRIX` (GLFT + OFI skew + OFI widening).
* IS/OOS split 60/40 on time order (`run_matrix_benchmark.py:54-58`, `run_all_assets_benchmark.py:62-65`). No walk-forward re-fitting, no parameter estimation on IS, despite the "walk-forward" wording.

**Fidelity gaps, in severity order.**

1. **No capital constraint.** `cash` starts at 0 (`:39`) and is never checked. XYZ100 trades at 28668 USD/unit with size 1.0, so the simulator takes ~1M USD of notional with zero capital. The JSON `final_pnl` values are therefore mark-to-market of an unbounded, unfinanced position, not strategy P&L. This is why the summary numbers span -5515 to +204 for the same code.
2. **`net_profit` double-counts fees.** `final_equity` already has fees deducted from `cash` (`:128`,`:147`), yet `:192` computes `net_profit = final_equity - total_fee_paid`. Reproduced on synthetic data: `final_pnl = -51.54`, `total_fee_paid = 12.93`, `net_profit = -64.47`. The printed "Net PnL" in the runners uses `final_pnl` (`run_matrix_benchmark.py:79`), so the JSON's `net_profit` field is the broken one.
3. **Fill model is optimistic on gaps and has no queue.** A resting quote fills whenever the next print crosses it, at the quote price, with a full 1.0 unit, regardless of how far the print gapped. No queue position, no partial fills, no size/depth check, no latency, no post-only cancel-on-gap.
4. **`win_rate` is not a round-trip statistic.** `:178-184` pairs `sell_prices[i]` with `buy_prices[i]` by index, not FIFO; `roundtrips = min(#buys, #sells)` (`:180`). The CHANGELOG and the dialogue quote this as "往返胜率".
5. **`max_drawdown` is measured only at trade closes** (`:173-176`), on the trade-level `pnl_mtm` series — intratrade and intraperiod drawdown are invisible.
6. **`fill_size` is 1.0 *unit*, not notional, and `q_max` is 5.0 *units** (`:22`). Risk per fill therefore scales with the asset price: 5 units of WOO at 0.0116 is $0.058 of exposure, 5 units of XYZ100 at 28668 is $143k. The box is not comparable across the summary.
7. **The 4-mode comparison is degenerate.** I re-ran the engine on synthetic data: `PURE_AS` and `PURE_GLFT` produced identical trade counts and win rates whenever the fee hurdle and min-spread floor bind, differing only through `lambda_inv` amplification at the box edge. In the committed summary, WOO IS: PURE_AS 365 trades, PURE_GLFT 365, HYBRID 365; OOS: 242 / 242 / 242. CORE IS: 52 / 56 / 56. XYZ100 IS: 36 / 5 / 5. The modes mostly differ by how far the σ² terms move the price at all.

**What the summary JSON metrics mean** (`master_matrix_summary.json`, `all_assets_matrix_summary.json`):

| Key | Meaning | Caveat |
|---|---|---|
| `final_pnl` | `cash + inventory × last_price`, fees already netted | unfinanced position; not a return |
| `total_fee_paid` | sum of `maker_fee_rate × px × 1.0` over fills | one-sided count only |
| `net_profit` | `final_pnl − total_fee_paid` | **double-counts fees** (`matrix_engine.py:192`) |
| `num_trades` | fill count | |
| `roundtrips` | `min(#buys, #sells)` | index pairing, not FIFO |
| `win_rate` | % of index-pairs with `sell > buy` | not a round-trip win rate |
| `max_drawdown` | max peak-to-trough of trade-close equity | ignores intra-trade marks |
| `final_inventory` | signed units left at the end | units, not USD |
| `stress_tests.fee_stress` | same mode at 1.0/1.5/2.0/3.0× maker fee | 3× fee collapses trades (WOO OOS 172 → 20) because the solver widens to `2×fee` |
| `stress_tests.monte_carlo_500` | 500 block-bootstrap resamples (50-tick blocks) of the OOS slice | **features are not recomputed** after resampling, so `ofi`/`rolling_vol` no longer match the resampled prices; blocks are also concatenated out of order (`run_matrix_benchmark.py:97-102`) |

---

## 6. Assumptions that break for a binary option priced in (0,1), settling to 0 or 1, no leverage, no shorting, no continuous underlying

Each item is a property of the code, then the consequence.

**6.1 Unbounded, multiplicative price space.** Every spread is `micro_price × bps × 1e-4` (`shared/glft_engine/glft_solver.py:63-64`, live `:122-123`). The spread scales with the *price level*, not with the risk of the position. For a binary quoted at 0.50, a 4 bps half-spread is 0.0002 price units — below one 0.01 tick. At 0.99 it is 0.0004. The `min_spread_bps` and `fee × 2` hurdles would have to be re-expressed in **ticks**, and the whole "bps of price" parameterisation (half-spreads, 8.5 bps drift, 20 bps vol threshold, 5 bps/2.5× fee floors) has no meaning in probability space. Nothing in the code knows about probability-space ticks, and the live rounding (`round(..., 1)`, `:122-123`, tick 0.1) would collapse a 0–1 binary price to one decimal.

**6.2 `sigma` has no meaning without a continuous underlying.** The solver needs a diffusion for the inventory term (`:35`, `:49`, `:53`). In a binary, the quoted probability is a **bounded** martingale-ish process that jumps to 0 or 1 at resolution; there is no continuous underlying whose variance you can read off. Worse, the only σ the code can obtain is the stdev of its own quoted price (`:353`), which is **endogenous** to its own quoting — a market maker that widens its spread manufactures the volatility that then drives its inventory skew. For a binary you need the volatility of the *underlying event* (or the derivative of the digital's price w.r.t. that event), which is not present anywhere in this repo. The σ²×10000 and σ²×P scalings (`:35` vs `:49`) also cannot both be right for a quantity whose price range is [0,1].

**6.3 Inventory sign conventions assume a two-sided, shortable, linear-payoff asset.** `q` is a signed count of the instrument with `q>0` = long, and the reservation price moves *down* as `q` rises (`:35`). The box is symmetric `±q_max` (`:381-382`, `matrix_engine.py:114-118`), and the fee check at `:100-103` is asymmetric under short inventory (skips the whole tick). On a venue where you cannot short, `q < 0` is unreachable, the `inv > -Q_MAX` half of the box is dead, and long inventory in a binary has **bounded** loss (≤ stake) and *convex* payoff rather than a symmetric ±spread. The `lambda_inv` 3×/8× amplifier at 60%/80% of the box (`:27-32`) is a linear price-proportional kick; a digital's risk is not proportional to its probability.

**6.4 No expiry, no settlement, no time dimension.** The entire design premise is "perpetuals have no expiry so drop the (T−t) term" (`shared/glft_engine/glft_solver.py:6`, `README.md:44-47`). A binary has a hard expiry at which the position resolves discontinuously to 0 or 1. The repo contains **no** expiry, maturity, or time-to-resolution symbol anywhere (grep for `expiry|expiration|maturity|T-t` finds only the two docstring/README mentions). Consequences: no discounting of a position that must be flattened before resolution; no forced de-risk as resolution approaches; no distinction between "toxic flow" and "the event is about to be known"; and the stationary/infinite-horizon assumption is exactly the assumption a dated binary violates. The one time-aware structure in the repo is the *session* clock (`RWARegimeClassifier`, `:59-89`), which is about US market hours, not about the contract's own lifetime.

**6.5 Fee units are venue-specific and here are already wrong by 5x.** The solver assumes a symmetric, per-side maker fee in **bps of notional** (`fee_maker_bps`, `:14`, hurdle `×2` `:57`). The repo's own live log disagrees with its own assumption: in `02_rwa_tokenized_equity_mm/backtest/sndk_real_fills_20261102.csv` the per-fill fee is 0.000354 USD on 11.80 USD of notional = **0.30 bps**, while the engine hardcodes `MAKER_FEE_BPS = 1.5` (`hyperliquid_sndk_live.py:51`). So the fee hurdle is ~5x conservative relative to what was actually charged, and the min-spread floor (8 bps → 4 bps half) is what actually binds. A binary venue with a different fee basis (per-fill flat fee, fee on proceeds/winnings, or zero maker fee with a taker fee) cannot be expressed by `fee_maker_bps` at all, and the "2× maker fee covers the round trip" rule (`:57`) is a *perp* convention.

**6.6 Tick size and rounding.** Live: `min_tick = 0.1` USD (`hyperliquid_sndk_live.py:161`), prices rounded to 1 dp (`:122-123`), replacement threshold 1.5 ticks (`:399`), sniper trigger 8.5 bps (`:345`). A binary at p=0.50 with a 0.01 tick has 1 tick = 20 bps, so an 8.5 bps drift gate is finer than the market's own grid, and a 4 bps half-spread is a fraction of a tick. All of these must be redefined in tick units.

**6.7 Capital, leverage, margin.** `TARGET_LEVERAGE = 10` is defined (`hyperliquid_sndk_live.py:49`) and **used nowhere** (grep: only the definition). The CHANGELOG's margin arithmetic (`CHANGELOG.md:43-45`: 0.05 contracts × 1170 USD at 10× = 5.85 USDT of margin, "77% safety buffer") is narrative, not code. The backtest has no capital constraint at all (§5, gap 1). A binary position is fully funded: max loss = stake, no margin, no liquidation, no funding rate. The live engine's only capital-related gate is `acc_val < 5.0` (`:356-359`), which is an account-value floor, not a position-risk limit. The order sizing rule `ORDER_NOTIONAL_USD / price` (`:369-370`) also assumes a per-unit notional that carries a margin requirement.

**6.8 Order-book / microstructure assumptions.** The live engine reads a single consolidated L2 book (`l2Book` `:179`) and computes mid from best bid/ask (`:189-194`); `shared/sentinel/market_regime_sentinel.py` assumes top-5 depth in USD (`min_depth_usd=1500`, `panic_depth_usd=500`) — in probability space, depth is better measured in *contracts* or dollars of payout, and a binary near resolution can have a one-sided book with zero depth on the side you need. `micro_aggregator.py:53-60` computes OBI and spread from `bids[0][0]`/`asks[0][0]` with an implicit assumption of a continuous two-sided book.

**6.9 Directionality of "toxicity".** The entire defensive stack treats adverse selection as *order-flow imbalance* (OFI `:52-55`, flow imbalance `:72-84`) and *short-term price drift* (`px_rel`, `sigma`). For a binary that resolves on a news event, the dominant adverse-selection risk is a **jump in the underlying** that re-prices the event probability discontinuously, with no corresponding order-flow signature in the CLOB and no way to distinguish informed flow from a genuine repricing. The 8.5 bps drift gate (`:345`) and the 5s cooldown are calibrated to a continuous tape.

**6.10 Regime/session logic.** `RWARegimeClassifier` (`:59-89`) hardcodes America/New_York equity sessions with multipliers 1.0 / 1.5 / 1.8 / 2.5 / 3.0 and pauses quoting in US regular hours. For a binary, the meaningful "regimes" are time-to-resolution buckets and the event calendar (plus the underlying's own trading hours), not US equity hours.

---

## 7. The three audit verdicts, and what carries over to a Polymarket port

**Verdicts, one line each.**

* `audit_reports/OMP_INSPECTOR_01_CAUSALITY_REPORT.md:5` — **"通过 (PASS - STRICT CAUSAL)"**: claims quotes read only `prices[i]`, `ofis[i]`, `vols[i]` and fills only on tick `i+1`; cites `matrix_engine.py` L45–L130 and L135–L175 (the actual quote block is `:49-98` and the fill block `:120-161`, so the line citations are stale).
* `audit_reports/OMP_INSPECTOR_02_FEES_STRESS_REPORT.md:5` — **"通过 (PASS - FEES FULLY ENDOGENIZED)"**: claims `δ_half ≥ max(δ_GLFT, Fee_maker×2.0, Min_Tick)` and reports WOO OOS fee stress of 1.0/1.5/2.0/3.0× with trades shrinking 172 → 118 and "capital-protection sleep" at 3×.
* `audit_reports/OMP_INSPECTOR_03_OVERFITTING_REPORT.md:5` — **"通过 (PASS - DEFENSIVE BOUNDS SOUND)"**: claims per-symbol asymmetric parameters (WOO/CORE/NVDA half-spread 4/7/5 bps, box 5/5/3, OFI triggers 0.6/0.6/0.5) and reports a 500× bootstrap on CORE with mean −$0.0345 and VaR95 −$0.0746.

**Which of those numbers survive against the code.**

* Report 01's causality claim is true for the engine and false for the rest of the pipeline: `shared/aggregator/micro_aggregator.py` has a one-second **look-ahead** in the book it attributes to a second. Reproduced: with books at t, t+1, t+2 and a trade at t+0.9, the row labelled `sec=t` carries `mid_px` from the book at **t+1**, and the trade from second t+1 is booked into second t. The aggregator is the feature producer for the retraining loop described in the transcript (`kaggle_pipeline/kaggle_trainer_bridge.py` consumes `spread_bps` rows of exactly this shape, `kaggle_trainer_bridge.py:78`), so any model trained on it inherits the leak.
* Report 02's fee numbers do not match the committed summary: `master_matrix_summary.json` shows WOO OOS DEFENSIVE trades 172 → **166** (1.5×) → 164 (2.0×) → 20 (3.0×), not 172 → 118; and `total_fee_paid` at 1.0× is 0.000398 USD with `net_profit` −0.001561, not "$0.00062 / −$0.0012". Its `Min_Tick` term does not exist in the code.
* Report 03's Monte-Carlo figures *do* match (`CORE` mean −0.034547, p5 −0.074625 in `master_matrix_summary.json`). Its per-symbol table does **not**: the code has one global `q_max=5.0` (`matrix_engine.py:22`), one global OFI trigger 0.6 with a 2.0× widening (`:90-94`) — no 0.5/2.5× variant — and the two runners disagree with each other on the same symbol (`XYZ_NVDA` half-spread 5.0 bps in `run_matrix_benchmark.py:33` vs 4.0 bps in `run_all_assets_benchmark.py:30`).
* Report 03's "5s cooldown blocked 78 same-side buys in live testing" has **no supporting artefact** in the repo; the live cooldown exists (`hyperliquid_sndk_live.py:372-374`) but logs no such counter, and the backtest's cooldown is 10 ticks, not 5 seconds.

**Live risks flagged by the audits that a Polymarket port inherits.**

1. *Causality.* The tick-level "next print crosses the quote" fill model has no queue position and fills 1.0 unit at the quote regardless of gap size — an over-estimate of fill rate that is exactly the bias a Polymarket-style passive book (deep queue, thin touch) would punish hardest. The lookahead in `micro_aggregator.py` additionally means any retraining loop trained on those rows learns a spurious feature-to-price relation.
2. *Fee stress.* The fee hurdle is calibrated to a maker rate that the repo's own log contradicts (0.30 bps charged vs 1.5 bps assumed). A port must re-derive the hurdle from *observed* fees per fill, and must handle venues where the maker fee is zero and the cost is in adverse selection instead. Also: the "2× fee covers the round trip" rule assumes symmetric round-trip cost, which is false for a binary that resolves 0/1 with a fee on proceeds.
3. *Overfitting.* The LightGBM gate was trained on the same 247 fills it then traded (`CHANGELOG.md:27`; no training script in the repo), the toxicity threshold 0.60 was picked on that session, and the parameters differ between the two benchmark runners for the same symbol. For a binary port the analogue is worse: a model trained on one event's flow will not transfer to another event, and a single-event training set cannot support a 4-feature model with 30 trees. The `ask`-side gate is already non-functional at threshold 0.60 (§4), which is exactly the kind of thing a P0 audit should have caught and did not.

---

## 8. Production-hardened vs backtest-only

**Has run live (evidence: real mainnet fills + systemd units + transcript logs).**

* `02_rwa_tokenized_equity_mm/core/hyperliquid_sndk_live.py` — the only live engine. Evidence: `sndk_real_fills_20261102.csv` (247 fills, 2h39m, all `crossed=False`, i.e. 100% maker), `hyperliquid-sndk.service`, and the CHANGELOG's captured heartbeats (`CHANGELOG.md:64-69`).
* `02_rwa_tokenized_equity_mm/models/lgbm_toxicity_gate_SNDK.txt` — trained, deployed, and loaded in production (`CHANGELOG.md:64`).
* `02_rwa_tokenized_equity_mm/core/micro_optimizer.py` — has a systemd unit (`hyperliquid-optimizer.service`); writes JSONL verdicts.
* `02_rwa_tokenized_equity_mm/core/hyperliquid_quota_guard.py` — committed with a detailed design, but **no service unit, no imports, incompatible client API**. Treat as untested design, not shipped code.

**Never ran / cannot run as committed.**

* The backtest itself: `W:\database` and `W:\GLFTmm` paths (`causal_features.py:6`, `matrix_engine.py:15`, `run_matrix_benchmark.py:23,27`) make it Windows-only. The committed JSONs are the deliverable.
* `hyperliquid_sndk_live.py` as committed **cannot authenticate**: `AGENT_PK = "<HL_AGENT_PRIVATE_KEY_FROM_ENV>"` (`:46`) is a literal placeholder string, not an `os.environ` read (grep: no `environ`/`getenv` in the file). `Account.from_key("<...>")` at `:128` will raise. `SECURITY.md:28` claims "所有凭证从环境变量读取" — the tree does not do that.
* The live engine also depends on `lightgbm`, `hyperliquid`, `eth_account`, `websockets`, `pytz` — none installed in any local venv I checked, so the live path is unsmoke-testable here.
* `shared/sentinel/`, `shared/aggregator/`, `kaggle_pipeline/`, `01_crypto.../vpin_gate.py`, `03_dex.../concentrated_lp_manager.py`, `02_rwa.../regime/regime_classifier.py` — unit-test-only or standalone.
* `kaggle_pipeline/kaggle_trainer_bridge.py` performs no Kaggle API call and returns canned A/k; the "rolling retraining with weight hot-reload" loop described in the transcript does not exist in code.

**Test coverage.** 8 tests, all passing (`pytest tests/ -q` → `8 passed`, run with `/home/da/.venvs/chd/bin/python` because the default python3 has no pytest). They cover: the sentinel's fee floor and 3 regimes (`tests/test_regime_sentinel.py:15-54`), the aggregator's 1-second bucketing (`:56-68`), and the bridge's metadata + stub calibration (`tests/test_kaggle_bridge.py:19-37`). **Zero tests** for the solver, the matrix engine, the live loop, the quota guard, the VPIN gate, the cooldown manager, or the LP manager.

**Test-quality note:** `tests/test_regime_sentinel.py:15-18` asserts a fee floor of 10 bps, which encodes the ×2.5-round-trip rule; the solver uses ×2.0. The two conventions are both "correct" in their own file and neither is flagged anywhere.

**Security posture.** `SECURITY.md` documents the HL/OKX credential leak and prescribes rotation (steps 1-5, `:20-24`). Rotation status of the other two leaked tokens is unverifiable from the tree, and two live-looking secrets are still committed: the Kaggle token (`kaggle_pipeline/kaggle_trainer_bridge.py:16`, also echoed in `tests/test_kaggle_bridge.py:15,17`) and a CryptoHFTData API key (`scripts/ingest_cryptohftdata_lake.py:16`, `scripts/ingest_90d_deep_lake.py:23`). The HL agent key itself is scrubbed from the working tree (`:46`) but remains in git history per `SECURITY.md:15`.

---

## 9. Verification performed (reproducible)

Everything numeric above was produced by executing the repo's own code in `/home/da/.venvs/quant/bin/python` (numpy 2.4.6, lightgbm 4.7.0) or `/home/da/.venvs/chd/bin/python` (pytest 9.2.0):

1. `pytest tests/ -q` → **8 passed**.
2. Shared solver sweep over `q ∈ {0,1,3,4,5}`, `σ ∈ {5e-4 … 1e-1}`: half-spreads constant at 0.46712 USD (4 bps) for every `q` below `σ=0.1`.
3. Live-solver replication (γ=0.5, fee=1.5, min_spread=8, q_max=0.05, mult=1.5, σ=1e-4): `r=1167.800000`, `dask=dbid=6.0 bps`, `bid=1167.1 ask=1168.5` for inventory **+0.05 and −0.05 alike**.
4. Term magnitudes: `term_inv_bps` = 9.2e-6 bps (q=0.05, σ=1e-4) and 0.0092 bps (q=5, σ=1e-3) → the inventory term is inert at realistic σ.
5. `net_profit` double-count: synthetic run → `final_pnl=-51.5425`, `total_fee_paid=12.9299`, `net_profit=-64.4725`; recomputed `cash + inv*px` reproduces `final_pnl` exactly.
6. Mode degeneracy: synthetic run → `PURE_AS` 937 trades vs `PURE_GLFT` 951, but identical when the fee hurdle is removed (937/937 vs 951/951 across `fee=2bps` and `fee≈0`), confirming the modes differ only through the σ² terms.
7. Live CSV: 247 rows; fee 0.000354 USD on 11.80 notional = **0.30 bps** (vs `MAKER_FEE_BPS=1.5`); `crossed=False` on all rows; `startPosition` range −0.07 … +0.16 (3.2× `Q_MAX=0.05`); `closedPnl` sum −0.53467 USD; fee sum 0.08699 USD; 44 of 115 close-rows positive (38.3%); per-hour closed PnL +0.039 / +0.062 / −0.635 (the third hour is where the CHANGELOG's drawdown story comes from); FIFO reconstruction of the same fills gives +4.00 USD gross over 115 round trips while an average-entry reconstruction gives −0.116 USD realized, and the exchange's own `closedPnl` column says −0.535 USD — **the three accountings disagree and the log lacks a per-fill entry price, so the session P&L cannot be reconciled from the CSV** (flagged, not resolved).
8. LightGBM sweep over `px_rel ∈ [-0.004, 0.004] × σ ∈ [1e-5, 1e-2]`: `side_buy=0` max p = **0.017137** (ASK_CUT unreachable at 0.60); `side_buy=1` max p = **0.806949**, exceeding 0.60 only for `px_rel ≳ 0.00145`.
9. Aggregator timing: rows for `sec=t` carry the book from `t+1`, and second `t+1` trades are booked into `t`.
10. Fee-hurdle asymmetry in `matrix_engine.py:100-103`: at `q=-1, σ=0.05` the bid leg's `(curr_p - bid_quote)` goes negative → the tick is skipped entirely.

The repo was read only; no file under `GLFTmm/` was modified.
