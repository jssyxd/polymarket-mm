# asgrid-mm Architectural Dive

Repo root: `asgrid-mm/`. All paths relative to that root. Read-only analysis; nothing in the repo was modified.

The repo is not a system. It is a **live trading service with a bag of abandoned prototypes next to it**. The distinction matters more than anything else below, because the four pricing engines in it disagree with each other and only one of them has ever run against a real exchange.

---

## 0. The single most important finding

The production path (`live_cluster/run_live.py` == `live_cluster/run_live_v2.py`, byte-identical) **never loads the LightGBM models and never calls the A-S engine class**. It calls one hand-written pricing function with hand-written rule-based substitutes for the ML outputs.

- `live_cluster/as_nautilus_strategy.py:7-10` imports only `math`, `numpy`, `datetime`, `typing`. No `lightgbm`.
- `live_cluster/as_nautilus_strategy.py:72-75` derives `mu_pred` from a linear blend of OFI and MA20 deviation.
- `live_cluster/as_nautilus_strategy.py:92-93` derives toxicity from a three-condition rule, not from a model.
- `src/run_2year_asgrid_backtest.py:274-278` derives the backtest's "ML" inputs (`pred_drift`, `pred_tox_d`, `pred_tox_u`) from closed-form linear/logistic formulas, **not** from the trained boosters.
- The only file that ever loads the three boosters is `live_cluster/legacy_run_live_v1.py:155-157`, which is orphaned (no importer anywhere; confirmed by grep across all `.py`).
- The only `lightgbm` imports in the tree are `live_cluster/legacy_run_live_v1.py:53` and `src/alpha_gpt_evolution_engine.py:23`.

Consequence for a designer: **the trained LightGBM artifacts, the headline backtest numbers, and the live execution path are three disconnected systems.** The backtest numbers in `reports/` were produced by a surrogate, not by the model in `checkpoints/`. Reusing "the ML layer" means re-establishing that wiring, not copying files.

---

## 1. Module map

### 1.1 Production path (the only code with a live exchange history)

| Path | One-line purpose |
|---|---|
| `live_cluster/run_live.py` | Production entrypoint: 2 s loop, REST+WS fill accounting, post-only quoting, JSON status persistence. |
| `live_cluster/run_live_v2.py` | Byte-identical duplicate of `run_live.py` (`diff` returns no output). |
| `live_cluster/as_nautilus_strategy.py` | Pricing state machine (`compute_quotes`) + strict real-fill accounting (`on_real_fill`). Not NautilusTrader. |
| `live_cluster/okx_ws_manager.py` | Dual OKX WebSocket manager: public `books5`/`trades`, private `orders`/`account`; OFI accumulation; fill queue. |
| `live_cluster/gateway_okx_client.py` | OKX v5 REST client: HMAC-SHA256 signing, order place/cancel, balance, positions, candles. |
| `live_cluster/as_dynamic_risk.py` | Equity-tier → {gamma, kappa, alpha, beta, max_inventory, lot_sz, min_spread_bps} mapping. Only used by the legacy v1 runner and tests. |
| `live_cluster/cron_hot_monitor.py` | 5-minute performance observer; Telegram report; persists `monitor_perf_state.json`. |
| `live_cluster/cron_accountbot3_ml_guard.py` | Compliance watchdog: container liveness, heartbeat, feature-range checks, 4 decision-alignment goals, `accountbot3_ml_health.json`. |
| `live_cluster/legacy_run_live_v1.py` | Older runner that *does* load LightGBM boosters and *does* use `as_dynamic_risk`. Orphaned. |
| `live_cluster/Dockerfile` | python:3.11-slim; installs numpy/pandas/scipy/lightgbm/requests/pyarrow; copies `run_live.py`. No NautilusTrader install. |

### 1.2 Research / prototype path (never executed in production)

| Path | One-line purpose |
|---|---|
| `src/avellaneda_stoikov_engine.py` | Standalone A-S grid engine class with the textbook `r = s − qγσ²(T−t)` header. Zero importers; `step()` is never called. |
| `src/as_ml_engine.py` | A-S + toxicity gate engine (fourth distinct reservation-price formula). Imported only by the smoke test. |
| `src/as_risk_guard.py` | Drawdown / notional / vol-surge circuit breaker. Imported only by the smoke test. |
| `src/grid_risk_controller.py` | Vol-surge / margin-overload / ADX guard. **Zero importers.** |
| `src/as_nautilus_strategy.py` | The only file that actually imports `nautilus_trader`; a stub that computes prices and never submits an order. Zero importers. |
| `src/backtest_avellaneda_grid.py` | 8,000-bar 1m bar-touch backtest, A-S vs naive symmetric grid. Not queue-aware. |
| `src/run_2year_asgrid_backtest.py` | 2-year Numba bar-touch backtest; produces `reports/ASGRID_2YEAR_BENCHMARK_REPORT.md` and `reports/asgrid_2year_metrics.json`. |
| `src/alpha_gpt_evolution_engine.py` | LLM-mutation + Numba-fitness evolutionary loop over A-S parameters. |
| `src/download_real_btc_1m.py`, `download_real_btc_1m.py` | BTCUSDT 1m parquet fetchers. |

### 1.3 Specification / design documents

| Path | Purpose |
|---|---|
| `README.md` | Positioning (maker rebate / points farming), venue list, and the operational doctrine: post-only, amend-not-repost, OFI toxicity breaker. |
| `ARCHITECTURE_AND_EXECUTION_FLOW.md` | Six-stage live information flow: WS → features → ML → A-S pricing → risk → fill accounting. |
| `AS_GRID_FULL_SPECIFICATION.md` | v2.4.0 whitepaper: A-S derivation, data governance, ML architecture, order-lifecycle red lines, equity scaling table, migration guide. |
| `LESSONS_LEARNED.md` | Five measured production defects and their standardized fixes. |
| `THEORY_PAPERS.md` | Four arXiv PDFs and why each is relevant. |
| `docs/design/00-methodology-master.md` | Integration entrypoint for five parallel design slices; the repo's own self-critique and blocker list. |
| `docs/design/01-data-pipeline-and-symbol-selection.md` | Venue coverage, unit traps, symbol selection. |
| `docs/design/02-ml-training-loop.md` | Labels, features, walk-forward, decision layer, hard-constraint clamp, degradation ladder. |
| `docs/design/03-queue-aware-backtest-engine.md` | Design of the queue-aware engine that does not exist yet. |
| `docs/design/04-live-ops-capital-and-monitoring.md` | Gates, capital scaling, three-tier monitoring, runbook. |
| `docs/design/05-portable-open-source-survey.md` | Survey of hftbacktest / nautilus_trader / Hummingbot / ccxt with license and adoption verdicts. |
| `as_grid_development_full_history.html` | Full research log: HJB derivation, GTL (2012) correction, the -188% audit, theory-to-production table. |
| `KAGGLE_RESOURCES.md`, `kaggle_trainer/trainer.py`, `kaggle_trainer/kernel-metadata.json` | Offline training pipeline. |

### 1.4 Artifacts

| Path | Purpose |
|---|---|
| `checkpoints/lgb_drift_model.txt` | LightGBM regressor, 7 features (`Column_0..6`), 50 trees, 75,503 bytes. |
| `checkpoints/lgb_tox_down_model.txt` | LightGBM binary classifier, 7 features, 40 trees, 59,955 bytes. |
| `checkpoints/lgb_tox_up_model.txt` | LightGBM binary classifier, 7 features, 40 trees, 59,952 bytes. |
| `checkpoints/as_mm_checkpoint.json` | Evolved A-S params: gamma 0.0422, kappa 1.8285, drift_alpha 0.599, toxic_beta 1.0982, min_spread_bps 2.0, 3 generations, best_fitness 6.1386. |
| `checkpoints/btc-as-lob-mm-trainer.log` | Kaggle stdout; contains the OOS metrics (see §6). |
| `reports/ASGRID_2YEAR_BENCHMARK_REPORT.md`, `reports/asgrid_2year_metrics.json` | 2-year headline backtest. |
| `reports/ASGRID_ORIG_V2_BENCHMARK_REPORT.md`, `reports/asgrid_orig_v2_metrics.json` | 3.12-year original baseline. |
| `reports/ASGRID_RECT_V2_BENCHMARK_REPORT.md`, `reports/asgrid_rect_v2_metrics.json` | 3.12-year "rectified" run. |
| `tests/test_012_components_smoke.py` | 7 smoke tests over the prototype modules only. No test touches `run_live.py` end-to-end beyond one pricing call. |
| `data_btc_1m_real.parquet`, `REAL_BTC_GRID_FILLS.csv`, `trades/btc_as_black_swan_20240805_trades.csv` | Data and trade dumps. |

---

## 2. The A-S math as implemented

There are **four** distinct reservation-price implementations. They do not agree.

### 2.1 `src/avellaneda_stoikov_engine.py` — the textbook form (orphaned)

Header claim, `src/avellaneda_stoikov_engine.py:8`:

```
r(s, q, t) = s - q * gamma * sigma^2 * (T - t)
```

Implementation, `src/avellaneda_stoikov_engine.py:54-58`:

```python
def compute_reservation_price(self, mid_price, sigma, t_left=1.0) -> float:
    # r(s, q, t) = s - q * gamma * sigma^2 * (T - t)
    skew = self.inventory * self.gamma * (sigma ** 2) * t_left
    return mid_price - skew
```

Units: `sigma` is a **volatility in price units** (the caller at `src/avellaneda_stoikov_engine.py:94-95` passes `sigma` straight through from `step()`); `t_left` is dimensionless; `gamma` and `kappa` are dimensionless (defaults 0.1 / 1.5, `src/avellaneda_stoikov_engine.py:34-35`). `skew` therefore comes out in **price units** only if `gamma*sigma^2` is already price^-1. It is not. `q` is an integer count of contracts (`src/avellaneda_stoikov_engine.py:49`), not a notional.

Spreads, `src/avellaneda_stoikov_engine.py:60-72`:

```python
base_half_spread = (1.0 / self.gamma) * np.log(1.0 + self.gamma / self.kappa)
vol_adjusted_half = base_half_spread * (1.0 + 3.0 * sigma)
inventory_bias = (2.0 * self.inventory + 1.0) * self.gamma * (sigma ** 2) * t_left / 2.0
delta_ask = vol_adjusted_half + inventory_bias
delta_bid = vol_adjusted_half - inventory_bias
return max(0.0005, delta_bid), max(0.0005, delta_ask)
```

Three defects, all citable:

1. **The base half-spread is not scaled by price.** `(1/γ)·ln(1+γ/κ)` with γ=0.1, κ=1.5 equals `0.6454`, used as an **absolute price offset**. On BTC at 60,000 that is ~1 bp by coincidence. On a 0–1 probability token it is 64.5 cents. The `max(0.0005, ...)` floor at line 72 is likewise an absolute price quantity, not a tick count.
2. **The A-S base half-spread term `γσ²(T−t)/2` is absent.** The A-S optimal total spread is `2/γ·ln(1+γ/κ) + γσ²(T−t)`; the code carries only the first term plus a multiplicative `(1+3σ)` factor that appears in no source.
3. **The inventory-bias sign is inverted relative to A-S.** A-S gives `δ^b* = base + (2q+1)/2·γσ²(T−t)` and `δ^a* = base − (2q−1)/2·γσ²(T−t)`, i.e. with long inventory the bid distance *grows* and the ask distance *shrinks*. Here `delta_bid = base − bias` and `delta_ask = base + bias`, i.e. with long inventory the ask is pushed *away* from the reservation price. Because the quotes are placed around `r` rather than around `s` (`src/avellaneda_stoikov_engine.py:114-115`), the A-S identity `bid = r − base`, `ask = r + base` is what the math actually implies; the extra bias term double-counts inventory and pushes the quote pair asymmetrically in the wrong direction.

Where `T−t` appears: `src/avellaneda_stoikov_engine.py:57` (reservation price) and `:67` (inventory bias). Both multiply by `t_left`, whose default is `1.0` and which is never passed by any caller — `src/avellaneda_stoikov_engine.py:94-95` calls `compute_reservation_price(mid_price, sigma)` and `compute_optimal_spreads(sigma)` with no `t_left`. **`(T−t) ≡ 1.0` constant, forever.** `self.T` is assigned at `src/avellaneda_stoikov_engine.py:43` and never read again anywhere in the tree.

### 2.2 `src/as_ml_engine.py` — production-family formula

`src/as_ml_engine.py:38-44`:

```python
inventory_skew = self.inventory * self.gamma * (sigma ** 2) * mid_price * 0.001 * t_left
drift_adjustment = self.alpha_drift * mu_pred * (mid_price * 0.0005)
return mid_price - inventory_skew + drift_adjustment
```

Differences from §2.1: `mid_price` re-enters the skew (so `skew` is now nominally a *price* if `sigma` is a fractional return and `0.001` is a unit bridge), a drift term is added, and `t_left` again defaults to `1.0` and is never passed (`src/as_ml_engine.py:60` calls with three positional args). `self.T` at `:27` is dead.

Spreads, `src/as_ml_engine.py:62-64`: `base_half_spread = (1/γ)·ln(1+γ/κ)·(mid·0.0004)` — now price-proportional. `min_half_spread = mid·min_spread_ratio` where `min_spread_ratio = min_spread_bps/10000` (`:30`), default 4.0 bps (`:21`). Floors at `:77-78` use `min_half_spread * 0.8`, i.e. the fee floor is allowed to fall 20% *below* the fee hurdle. Maker guarantee at `:84-85` pins `bid ≤ mid − min_half·0.5` and `ask ≥ mid + min_half·0.5`.

### 2.3 `live_cluster/as_nautilus_strategy.py` — the formula that actually runs

`live_cluster/as_nautilus_strategy.py:68-78`:

```python
sig = max(0.10, gk_vol)
ofi_norm = np.clip(rolling_ofi / 5.0, -3.0, 3.0)
mu_pred = np.clip(0.35 * ofi_norm - 0.20 * ma20_dev, -2.0, 2.0)
drift_adj = 0.5563 * mu_pred * (mid_price * 0.0003)
lot_float = float(self.lot_sz)
inv_skew = (self.inventory * lot_float) * self.gamma * (sig ** 2) * mid_price * 0.0008
r = mid_price - inv_skew + drift_adj
```

Note the fourth distinct constant: `0.0008` here, versus `0.001` in `src/as_ml_engine.py:42` and `src/run_2year_asgrid_backtest.py:96`. And `0.0005` for drift here versus `0.0005` in `src/as_ml_engine.py:43` and `0.0005` in `src/run_2year_asgrid_backtest.py:97` — but the backtest uses `0.0005` while the live uses `0.0003` for the drift coefficient. **The live service and the 2-year backtest that "proves" it use different pricing constants.**

`live_cluster/as_nautilus_strategy.py:81-83`:

```python
base_half_spd = (1.0 / self.gamma) * math.log(1.0 + self.gamma / self.kappa) * (mid_price * 0.0004)
min_half_spd = mid_price * (self.min_spread_bps * 0.5 / 10000.0)  # 4.5 bps
base_half_spd = max(min_half_spd, base_half_spd)
```

With `min_spread_bps=9.0` (constructor default, `live_cluster/as_nautilus_strategy.py:27`) the half-spread floor is 4.5 bps and the total spread floor is 9.0 bps.

Inventory bias, `live_cluster/as_nautilus_strategy.py:96-100`:

```python
inv_ratio = np.clip(self.inventory / max(self.max_inventory, 1e-6), -1.0, 1.0)
inv_bias = inv_ratio * base_half_spd * 0.75
delta_ask = base_half_spd * (1.5 if is_toxic_up else 1.0) - inv_bias
delta_bid = base_half_spd * (1.5 if is_toxic_down else 1.0) + inv_bias
```

This one has the **correct** A-S sign (long inventory → ask closer, bid further), because the comments at `live_cluster/legacy_run_live_v1.py:355` state the intent explicitly ("long inventory widens bid, narrows ask"). It differs from §2.1 in exactly the way §2.1 got wrong.

### 2.4 `src/run_2year_asgrid_backtest.py` — the formula that produced the headline numbers

`src/run_2year_asgrid_backtest.py:96-98`:

```python
inv_skew = (q * lot_size) * gamma * (sig_gk ** 2) * s * 0.001
drift_adj = alpha_drift * mu_pred * (s * 0.0005)
r = s - inv_skew + drift_adj
```

Parameters used at `src/run_2year_asgrid_backtest.py:318`: `gamma=0.0451, kappa=2.1346, alpha_drift=0.5563, beta_toxic=0.9544, maker_fee=0.0002, taker_fee=0.0005`, `lot_size=0.05`, `max_inv=10.0`.

### 2.5 Where `T−t` appears, and how the author documented the defect

**All appearances of the horizon term in the tree:**

| Location | Form |
|---|---|
| `src/avellaneda_stoikov_engine.py:8` | Docstring: `r(s, q, t) = s - q * gamma * sigma^2 * (T - t)` |
| `src/avellaneda_stoikov_engine.py:14` | Docstring: `(T - t): 剩余控制时域` |
| `src/avellaneda_stoikov_engine.py:36` | `terminal_horizon: float = 1.0,   # T - t: 归一化时间窗口` |
| `src/avellaneda_stoikov_engine.py:56` | Inline comment repeating the formula |
| `src/avellaneda_stoikov_engine.py:57` | `skew = self.inventory * self.gamma * (sigma ** 2) * t_left` |
| `src/avellaneda_stoikov_engine.py:67` | `inventory_bias = (2.0 * self.inventory + 1.0) * self.gamma * (sigma ** 2) * t_left / 2.0` |
| `src/as_ml_engine.py:42` | `... * t_left` (default 1.0, never passed) |
| `AS_GRID_FULL_SPECIFICATION.md:36` | Spec formula with `(T - t) · λ_inv` |
| `THEORY_PAPERS.md:17` | "本策略保留价格 r = s − qγσ²(T−t) 与最优价差的直接来源" |
| `as_grid_development_full_history.html:4959,4962,4964-4967` | Full A-S derivation with `(T−t)` |
| `docs/design/02-ml-training-loop.md:1238` | "保留价格含 `−qγσ²T`" |
| `docs/design/02-ml-training-loop.md:1291` | "保留价 r = mid − qγσ²T + αμ" |

**How the author documented the defect — the author's own words:**

1. `AS_GRID_FULL_SPECIFICATION.md:43` is the explicit acknowledgment:
   > `$(T - t)$：做市周期的剩余标准化时间视野（实盘中离散化为常数阻尼项）。`

   Translation: *"(T − t) is the remaining normalized time horizon of the quoting cycle (in live trading it is discretized into a constant damping term)."* This is the author's documented substitution of a shrinking horizon with a constant.

2. `docs/design/02-ml-training-loop.md:1072` restates the inventory cost with a constant horizon and a units prescription:
   > "所有库存成本：A-S 形式 `q · γ · σ² · T`，其中 σ 用 **bps/√s**、T 用秒、结果得到 bps"

   `T` in seconds is a fixed horizon, not a shrinking one.

3. `docs/design/02-ml-training-loop.md:1074` is the explicit defect ticket against the shipped code:
   > "**【实测/待修】** 现有 `as_ml_engine.py` 的库存偏置写作 `q·γ·σ²·mid·0.001`，把 bps 单位的 σ 与价格单位的 mid 相乘，量纲不干净。**【建议】** 在 ML 决策层统一用 bps 口径，旧的 `as_ml_engine` 保留为 L2 降级路径（并在文档中标注其参数是启发式标定值，不是量纲一致的解）。"

4. The theoretical license for freezing the horizon is in the research log. `as_grid_development_full_history.html:4973`:
   > "GTL (2012) 彻底解决了 A-S 2008 的理论悬案：**A-S 原著并未在严格库存截断边界下求解，且其公式仅是终端临近时的粗糙近似**。"

   and `as_grid_development_full_history.html:5009-5010`:
   > "GTL 证明，Avellaneda-Stoikov (2008) 原文给出的解析公式，**实质上仅仅是该 ODE 系统在 $t \to T$（交易时段即将结束时）的一阶泰勒展开展开项**。在长期持续高频做市中（$T - t \gg 0$），$\mathbf{v}(t)$ 迅速收敛于矩阵 $M$ 的**最小特征值所对应的主特征向量**。这意味着**真实高频做市的最优挂单与时间 $t$ 无关，呈现出稳态空间几何特征**。"

   So the author reasoned: for a perpetual with no expiry, freezing `(T−t)` is *approximately* right because the steady-state solution is time-independent. For a Polymarket binary with a known expiry, that reasoning inverts — `(T−t)` is the single most important term in the whole strategy.

5. The author also records the drift-augmented reservation price as future work, `as_grid_development_full_history.html:5088`:
   > "将漂移项 μ 显式纳入 HJB 方程：$dS_t = \mu dt + \sigma dW_t$，使保留价格 $r^*(s, q, t) = s + \frac{\mu}{\gamma \sigma^2} - q \gamma \sigma^2 (T - t)$"

   This form is what a binary-option adaptation would need: it is the only place in the repo where a term linear in `1/γ` appears, and it makes the reservation price shift by a *constant* rather than a *time-decaying* amount.

**Summary of the defect:** `(T−t)` is not merely frozen — it is *absent* from the production formula. `live_cluster/as_nautilus_strategy.py:77` has no horizon factor at all, and `src/run_2year_asgrid_backtest.py:96` has none. The skew is constant for the life of a position. There is no mechanism anywhere in the tree that increases inventory urgency as expiry approaches.

---

## 3. NautilusTrader integration

### 3.1 Which version

No version is pinned in code. `live_cluster/Dockerfile` installs `numpy pandas scipy lightgbm requests pyarrow` and no NautilusTrader at all.

Versions appear only in the design docs, as *survey findings about the author's machine*, not as a dependency:

- `docs/design/03-queue-aware-backtest-engine.md:722`: "**关键事实（实测）**：本机 Python 环境**已装 nautilus_trader 1.221.0**，但 `live_cluster/` 里的 'nautilus' 只是命名借用，**并未真正使用该库**（`live_cluster/as_nautilus_strategy.py` 只 import `math/numpy/typing`）。→ 引入真实 NautilusTrader 是**新增能力**，不是复用。"
- `docs/design/03-queue-aware-backtest-engine.md:1021`: "nautilus_trader 1.221.0 已装".
- `docs/design/05-portable-open-source-survey.md:171`: "**PyPI 稳定版** | **1.231.0，上传 2026-08-02**，`requires_python >=3.12,<3.15`".
- `docs/design/05-portable-open-source-survey.md:173`: "**v2 状态** | tag 列表含 `v2.0.0rc9` … `v2.0.0rc5`，**v2 未 GA**".
- `docs/design/05-portable-open-source-survey.md:35`: "**不整体引入**" (do not adopt wholesale).

### 3.2 Which nodes / strategies exist

**Two files carry the name, and they are different things.**

**`src/as_nautilus_strategy.py` — a genuine but inert NautilusTrader stub.**
- Imports `nautilus_trader.trading.strategy.Strategy`, `Bar`, `OrderBookDeltas`, `OrderSide`, `TimeInForce`, `OrderType`, `InstrumentId`, `Price`, `Quantity` (`src/as_nautilus_strategy.py:8-12`).
- `NautilusAvellanedaMMStrategy(Strategy)` at `:15`.
- `on_start` subscribes bars only (`:37`). It never subscribes to `OrderBookDeltas` despite importing it, and never subscribes to quotes.
- `on_bar` (`:40-50`) computes `r` and a half-spread, then assigns them to `self.active_bid_order` / `self.active_ask_order` — **as floats** (`:49-50`). There is no `submit_order`, no `OrderFactory`, no `PostOnly` order type, no `OrderStatus` handling, no fill handler, no cancel logic beyond `cancel_all_orders` in `on_stop` (`:53`).
- The pricing at `:45-46` is a fifth variant: `r = s - (q·lot)·γ·(0.25²)·s·0.0008` with **σ hardcoded to 0.25** and `half_spread = max(s·0.0004, (1/γ)·(s·0.0004))` — the `(1/γ)·ln(1+γ/κ)` term is replaced by a plain `1/γ`, which is not the A-S formula.
- `self.instrument_id` is hardcoded to `BTCUSDT-PERP.BINANCE` (`:26`) — the Binance venue, not the OKX venue the rest of the repo trades.
- Zero importers.

**`live_cluster/as_nautilus_strategy.py` — not NautilusTrader at all.**
- `NautilusAvellanedaV2MMStrategy` is a plain Python class (`:12`) with no base class.
- Two methods of substance: `compute_quotes(...)` (`:55-157`) and `on_real_fill(fill_event)` (`:159-193`).
- It holds `active_orders: Dict[str, Dict[str, Any]]` (`:49`) that is **never written or read** — the live order bookkeeping actually lives in `run_live.py`.

**The actual "nodes" in the running system** are therefore:

| Node | File | Role |
|---|---|---|
| WS manager | `live_cluster/okx_ws_manager.py` | Two WebSocket connections on one asyncio loop in one daemon thread (`:78-84`), sharing a `threading.Lock` (`:40`). |
| REST gateway | `live_cluster/gateway_okx_client.py` | Synchronous `urllib` calls from the main thread. |
| Pricing kernel | `live_cluster/as_nautilus_strategy.py` | Pure function, no I/O, no state beyond inventory. |
| Event loop | `live_cluster/run_live.py:184-347` | 2 s cadence (`sleep_time = max(0.5, 2.0 - elapsed)`, `:346`). |

### 3.3 Order lifecycle in the running system

Per iteration of the 2 s loop:

1. **Drain fills** — `ws_mgr.pop_new_fills()` (`live_cluster/run_live.py:189`), each fed to `strategy.on_real_fill(f)` (`:191`) and logged as `⭐ [REAL FILL CONFIRMED]` (`:192`).
2. **Update cooldown state** — inventory direction change sets a 5 s per-side cooldown (`:195-204`, `FILL_COOLDOWN_SEC = 5.0` at `:180`).
3. **Refresh features** — 30 × 1m candles every 15 s (`:207-211`), producing GK vol, MA20 deviation, ADX(14), trend direction via `compute_gk_vol` (`:76-126`).
4. **Read the book** — `ws_mgr.get_latest_book()` (`:214`); if `mid <= 0` fall back to REST ticker, then to a hardcoded `69000.0` (`:216-218`).
5. **Compute quotes** — `strategy.compute_quotes(...)` (`:223-233`).
6. **Reconcile live orders** — `client.get_pending_orders(...)` (`:242`). For each pending order: keep it if the side is allowed **and** `|px − target| <= PRICE_TOLERANCE_USDT` where `PRICE_TOLERANCE_USDT = max(1.5, mid_px * 0.0001)` (`:241`, `:254`, `:259`); otherwise queue for cancellation (`:257`, `:262`). Cancellation is a single batch call (`:264`), capped at 20 by `live_cluster/gateway_okx_client.py:143`.
7. **Post missing quotes** — if allowed and no live order exists: `place_order(inst_id, td_mode="cross", side, ord_type="post_only", px, sz, cl_ord_id)` (`:277-285`, `:299-307`). `cl_ord_id` is `f"asb{now_ms}"[-32:]` / `f"asa{now_ms}"[-32:]` (`:276`, `:298`).

**Action strings emitted** (consumed by the watchdog): `BID_QUEUE_HOLD(px)`, `BID_POST(px)`, `BID_REJ(msg)`, `BID_CUT`, and the ASK equivalents (`:274`, `:287`, `:289`, `:291`, `:296`, `:309`, `:311`, `:313`).

### 3.4 How acknowledgements and fills are handled

**Acknowledgements are never treated as fills.** The REST response `code == "0"` only sets an action label (`:286-289`); it never touches inventory or the trade counter. The strategy's fill path is exclusively `on_real_fill` (`live_cluster/as_nautilus_strategy.py:159-193`), which:

- rejects non-positive `fill_sz` or `fill_px` (`:166-167`);
- computes `notional_usd = fill_px * (fill_sz * self.ct_val)` with `ct_val = 0.01` (`:30`, `:169`);
- applies the sign: `side == "buy"` → `inventory += fill_sz`; `side == "sell"` → `inventory -= fill_sz` (`:171-174`);
- increments `real_matched_trades`, adds `notional_usd` to `real_volume_usd`, adds `|fee|` to `real_fees_paid_usd` (`:176-178`);
- appends a record and trims to the last 100 (`:191-193`).

**Fill source filtering** is in `live_cluster/okx_ws_manager.py:215-237`: only `state in ["filled", "partially_filled"]` **and** `fillSz > 0` are accepted; each `tradeId` (falling back to `ordId`) is deduped through `known_fill_ids` (`:224-225`); the fill is appended to `unprocessed_fills` (`:226-237`). `pop_new_fills()` (`:266-270`) hands the batch to the caller and clears it.

**Reconciliation API exists but is unused.** `live_cluster/gateway_okx_client.py:152-161` (`get_order`) and `:163-169` (`get_fills`) are implemented; `get_fills` is never called by `run_live.py`. `AS_GRID_FULL_SPECIFICATION.md:262` prescribes it ("或者定期轮询 `GET /api/v5/account/bills` 流水账单") but the code does not do it. **Unclear from code** whether an external reconciler exists outside this repo.

**No `amend-order`.** `README.md:64-66` and `AS_GRID_FULL_SPECIFICATION.md:274` both prescribe amend-instead-of-repost, but `grep -rn "amend" --include=*.py .` returns nothing. The gateway exposes only `place_order`, `cancel_order`, `cancel_batch_orders` (`live_cluster/gateway_okx_client.py:106-143`). The queue-hold tolerance at `live_cluster/run_live.py:241` is the implemented substitute.

**No staleness gate.** `get_latest_book()` returns an `age` field (`live_cluster/okx_ws_manager.py:256`) and nothing consumes it. `docs/design/02-ml-training-loop.md:1033` requires "数据陈旧：quote_age_ms > 500 → 双侧禁止"; not implemented.

**No halt on error.** The whole loop body is wrapped in `try/except Exception` that only logs (`live_cluster/run_live.py:342-343`). A persistent failure means the strategy keeps quoting on stale `cached_gk_vol` / `cached_adx14` values.

---

## 4. OKX WebSocket manager and gateway client

### 4.1 Channels subscribed

`live_cluster/okx_ws_manager.py:36-37`: two URIs.

Public (`wss://ws.okx.com:443/ws/v5/public`), `:90-97`:
- `books5` for `self.inst_id` (default `BTC-USDT-SWAP`, `:30`)
- `trades` for `self.inst_id`

Private (`wss://ws.okx.com:443/ws/v5/private`), `:191-197`:
- `orders` with `instType="SWAP"`, `instId=self.inst_id`
- `account`

### 4.2 Connection and reconnect behavior

- Both connections live in one asyncio event loop in one daemon thread (`:70-84`), launched with `asyncio.gather(_public_ws_loop, _private_ws_loop)`.
- `ping_interval=20, ping_timeout=10` on both (`:89`, `:176`).
- Reconnect is a bare `while self.running:` with `try/except Exception` and `await asyncio.sleep(2)` (`:111-112` for public, `:212-213` for private). **No exponential backoff, no attempt counter, no jitter, no dead-letter.** A persistently failing endpoint produces one reconnect attempt every 2 s forever.
- Login failure (`code != "0"`) → sleep 5 s, `continue` (`:185-189`), re-entering the loop and reconnecting.
- **Global IPv4 monkeypatch** at `:10-17` (and identically at `live_cluster/gateway_okx_client.py:9-16`): `socket.getaddrinfo` is replaced to prefer `AF_INET`, so that the source IP matches an OKX API whitelist (`ARCHITECTURE_AND_EXECUTION_FLOW.md:9`, `AS_GRID_FULL_SPECIFICATION.md:234-236`).

### 4.3 OFI and micro-price

- Micro-price: `micro = (b1 * v_a1 + a1 * v_b1) / (v_b1 + v_a1 + 1e-9)` (`:123`).
- OFI: Cont-Kukanov-Stoikov per-side increments at `:127-142` (`delta_b` / `delta_a` / `ofi_step = delta_b - delta_a`).
- The 60 s window `recent_ofi_window` (`:57`) receives **two different quantities on one scale**: OFI steps from the book (`:145`) and signed trade sizes from `trades` (`:171`). `get_rolling_ofi()` (`:259-264`) then sums them. Whether that is meaningful is **unclear from code**; the legacy runner normalized OFI by depth before use (`live_cluster/legacy_run_live_v1.py:290`) whereas the live runner divides by a hardcoded 5.0 (`live_cluster/as_nautilus_strategy.py:72`).
- `get_latest_book()` (`:247-257`) returns `bid, ask, bid_sz, ask_sz, mid, micro, age`.

### 4.4 Gateway client: signing, order placement, rate limits, credentials

**Signing** (`live_cluster/gateway_okx_client.py:38-57`):
```
ts = time.strftime('%Y-%m-%dT%H:%M:%S.000Z', time.gmtime())
msg = f"{ts}{method}{request_path}{body_str}"
sig = base64.b64encode(hmac.new(api_secret, msg, sha256).digest())
```
with `request_path` including the query string (`:39-42`), and headers `OK-ACCESS-KEY`, `OK-ACCESS-SIGN`, `OK-ACCESS-TIMESTAMP`, `OK-ACCESS-PASSPHRASE` (`:53-56`). A browser User-Agent is spoofed (`:51`).

**Order placement** (`live_cluster/gateway_okx_client.py:106-130`): body carries `instId`, `tdMode`, `side`, `ordType`, `sz`, optional `px`, `clOrdId`, `tag`; POST to `/api/v5/trade/order`.

| Property | Value | Evidence |
|---|---|---|
| Post-only | Yes, `ord_type="post_only"` | `live_cluster/run_live.py:281`, `:303` |
| Reduce-only | **Not implemented.** No `reduceOnly` field anywhere | `live_cluster/gateway_okx_client.py:117-129` has no such key |
| Amend | **Not implemented** | `grep "amend" --include=*.py` → empty |
| Margin mode | `td_mode="cross"` (hardcoded) | `live_cluster/run_live.py:279`, `:301` |
| Batch cancel | Yes, capped at 20 | `live_cluster/gateway_okx_client.py:143` |
| Size | `str(strategy.lot_sz)` = `"0.01"` | `live_cluster/run_live.py:283`, `:305` |
| Client order id | `asb{ms}` / `asa{ms}`, last 32 chars | `live_cluster/run_live.py:276`, `:298` |

**Rate limits: not handled.** `_sign_and_request` catches `HTTPError`, parses the JSON body, and returns it (`:66-71`); any other exception becomes `{"code": "-1", "msg": str(e)}` (`:72-73`). There is no 429 detection, no retry, no backoff, no rate limiter. The caller's only handling is `if res_b.get("code") == "0"` → `BID_POST` else `BID_REJ(msg)` (`live_cluster/run_live.py:286-289`), so a rate-limit response is indistinguishable from a business rejection in the logs, and the next loop iteration retries immediately.

**Simulated trading** is a header: `headers['x-simulated-trading'] = '1'` (`:58-59`), driven by `OKX_SIMULATED_TRADING == "1"` (`live_cluster/run_live.py:130`).

**Credentials** (`live_cluster/run_live.py:43-58`): read from env vars `OKX_API_KEY`, `OKX_API_SECRET`, `OKX_API_PASSPHRASE`, `OKX_SIMULATED_TRADING`, `ACCOUNT_LABEL`; the file `config/accountbot3_credentials.env` is consulted **only if `OKX_API_KEY` is empty** (`:51`). The file is not present in this repo snapshot.

**Security defect, present in the tree:** `live_cluster/cron_hot_monitor.py:22-23` hardcodes a live Telegram bot token and chat id; `:55-57` hardcodes an OKX API key, secret, and passphrase. The same Telegram token appears at `live_cluster/cron_accountbot3_ml_guard.py:27-28`. These are live credentials committed to source.

---

## 5. The risk stack

Four separate risk mechanisms exist. Only two of them are wired into the running service.

### 5.1 `src/as_risk_guard.py` — `AvellanedaRiskGuard.evaluate_risk` (imported only by the test)

| Gate | Trigger | Action | Lines |
|---|---|---|---|
| Max drawdown | `(peak − current)/peak >= max_dd_pct` (default 0.08) | `is_halted = True` (sticky), `halt: True`, reason `MAX_DRAWDOWN_BREACH` | `src/as_risk_guard.py:33-38` |
| Max notional | `abs(inventory_btc * mid_price) >= max_inventory_notional` (default 250,000) | `safe: False`, `halt: False`, reason `MAX_NOTIONAL_REACHED` | `:40-42` |
| Vol surge | `current_vol >= median_vol * vol_surge_th` (default 2.2) | Reports `vol_surge: True` and reason `VOLATILITY_EXPANSION`; **does not change `safe` or `halt`** | `:44-49` |

Note the vol-surge gate only *labels*. It has no action.

### 5.2 `src/grid_risk_controller.py` — `GridRiskController.check_safety_guards` (zero importers)

| Gate | Trigger | Action | Lines |
|---|---|---|---|
| Vol surge | `current_vol > median_vol * 2.5` | `safe_to_trade = False`, warning `VOLATILITY_SURGE: Spread widened, new quotes paused` | `src/grid_risk_controller.py:39-41` |
| Margin overload | `margin_used / (total_equity + 1e-8) >= 0.65` | `safe_to_trade = False`, warning `MARGIN_OVERLOAD` | `:42-43` |
| Strong trend | `adx_value >= 30.0` | Warning `STRONG_TREND_{dir}` only; `safe_to_trade` stays `True` | `:44-46` |

Note the ADX cutoff here is **30.0**, whereas both pricing engines use **28.0** (`live_cluster/as_nautilus_strategy.py:124`, `src/as_ml_engine.py:103`, `src/run_2year_asgrid_backtest.py:142`).

### 5.3 `live_cluster/as_dynamic_risk.py` — equity-tier parameter scaling

Not a gate but a parameter source. `compute_adaptive_as_parameters(equity_usd)` (`:7-62`):

| Tier | Equity | gamma | kappa | drift_alpha | toxic_beta | max_inventory | lot_sz | min_spread_bps |
|---|---|---|---|---|---|---|---|---|
| MICRO_ACCOUNT | ≤ 100 | 0.35 | 2.1346 | 0.5563 | 0.9544 | 0.03 | `"0.01"` | 4.5 |
| SMALL_ACCOUNT | ≤ 1,000 | 0.20 | 2.1346 | 0.5563 | 0.9544 | 0.15 | `"0.01"` | 4.0 |
| MEDIUM_ACCOUNT | ≤ 10,000 | 0.10 | 2.1346 | 0.5563 | 0.9544 | 0.80 | `"0.05"` | 3.5 |
| INSTITUTIONAL_ACCOUNT | > 10,000 | 0.0451 | 2.1346 | 0.5563 | 0.9544 | 5.00 | `"0.10"` | 3.0 |

**Callers:** `live_cluster/legacy_run_live_v1.py:59,138` and `tests/test_012_components_smoke.py:102-104`. The production runner hardcodes its parameters instead (`live_cluster/run_live.py:154-159`: gamma 0.35, max_inventory 0.05, min_spread_bps 9.0, lot 0.01) and never calls this module.

**Documentation conflict:** `AS_GRID_FULL_SPECIFICATION.md:287` specifies `γ = 3.00` and `min_spread_bps = 10.0` for the ≤100 USDT tier; `LESSONS_LEARNED.md:24-25` likewise prescribes `γ = 3.00` and `max_inventory = 0.05`. The code says 0.35 / 0.03 / 4.5. The code's own comment explains the change: "γ must NOT be set to extreme 3.0 (which destroys spread and triggers self-harm pricing)" (`live_cluster/as_dynamic_risk.py:15-16`) and "废除自杀式 3.0" (`live_cluster/as_nautilus_strategy.py:23`). `docs/design/01-data-pipeline-and-symbol-selection.md:1139` lists the `min_spread_bps` caliber conflict as an open item. **The spec is stale; the code is current.**

### 5.4 `live_cluster/as_nautilus_strategy.py` — the gates that actually run

In `compute_quotes` (`:55-157`), evaluated in order:

| # | Gate | Trigger | Action | Lines |
|---|---|---|---|---|
| 1 | Vol-surge spread expansion | `sig > 2.0 * vol_median` | `base_half_spd *= 2.0`; `vol_surge_count += 1` | `:86-89` |
| 2 | Fee hurdle (floor) | always | `base_half_spd = max(min_half_spd, base_half_spd)`, `min_half_spd = mid·(min_spread_bps·0.5/1e4)` | `:81-83` |
| 3 | Delta floor | always | `delta_bid, delta_ask >= min_half_spd * 0.8` | `:102-103` |
| 4 | Maker guarantee | always | `bid_px = min(bid_px, mid − min_half·0.5)`; `ask_px = max(ask_px, mid + min_half·0.5)` | `:109-110` |
| 5 | Inventory bound | `inventory >= max_inventory` / `<= -max_inventory` | `allow_bid = False` / `allow_ask = False` | `:112-113` |
| 6 | Toxicity down | `ofi_norm < -1.0 and ma20_dev < -0.6 and sig > vol_median` | `allow_bid = False`; `adverse_mitigations += 1` | `:92`, `:115-117` |
| 7 | Toxicity up | `ofi_norm > 1.0 and ma20_dev > 0.6 and sig > vol_median` | `allow_ask = False`; `adverse_mitigations += 1` | `:93`, `:119-121` |
| 8 | ADX trend | `adx14 >= 28.0` and `trend_dir < 0` / `> 0` | cut bids (strong downtrend) / cut asks (strong uptrend) | `:124-128` |
| 9 | Post-fill cooldown | `cooldown_bid` / `cooldown_ask` (5 s) | cut that side | `:131-134` |

Toxicity also **reshapes** rather than only blocks: `delta_ask = base·(1.5 if is_toxic_up else 1.0)` and `delta_bid = base·(1.5 if is_toxic_down else 1.0)` (`:99-100`).

### 5.5 The orchestration gates in `live_cluster/run_live.py`

| Gate | Trigger | Action | Lines |
|---|---|---|---|
| Post-fill cooldown | inventory direction change | 5 s lock on that side | `:180`, `:194-204` |
| Queue-hold tolerance | `|px − target| <= max(1.5, mid·0.0001)` | keep order, no cancel | `:241`, `:254`, `:259` |
| Cancel-on-disallow | side not allowed, or drift beyond tolerance | batch cancel | `:257`, `:262`, `:264` |
| Shutdown cleanup | SIGTERM/SIGINT | cancel all pending, stop WS | `:349-358` |
| Exception containment | any exception in loop body | log and continue | `:342-343` |

**Absent from the running path:** the entire `src/as_risk_guard.py` gate set (drawdown breaker, max-notional), the entire `src/grid_risk_controller.py` gate set (margin overload), the equity-tier scaler, any quote-staleness gate, any data-loss / WS-disconnect gate, and any per-side notional cap. `docs/design/04-live-ops-capital-and-monitoring.md:639+` (alert levels and runbook) is a design, not an implementation.

---

## 6. The ML pieces

### 6.1 What the models predict

From `kaggle_trainer/trainer.py:41-49`, horizon `H = 1` (the next 1-minute bar):

```python
fwd_ret = (close.shift(-H) - close) / max(atr14, 0.05)
fwd_min = (low.shift(-H)  - close) / max(atr14, 0.05)
fwd_max = (high.shift(-H) - close) / max(atr14, 0.05)
y_toxic_down = (fwd_min <= -1.8)      # crash >= 1.8 ATR below
y_toxic_up   = (fwd_max >=  1.8)      # surge >= 1.8 ATR above
y_drift = clip(fwd_ret, -5.0, 5.0)
```

Three models:
- `bst_drift` — LightGBM **regression** on `y_drift` (ATR-normalized 1-bar forward return). `kaggle_trainer/trainer.py:56-57`.
- `bst_tox_down` — LightGBM **binary** on `y_toxic_down`. `:61-62`.
- `bst_tox_up` — LightGBM **binary** on `y_toxic_up`. `:65-66`.

The model artifact headers confirm the shapes: `checkpoints/lgb_drift_model.txt` → `objective=regression`, `max_feature_idx=6`; `checkpoints/lgb_tox_down_model.txt` and `..._tox_up_model.txt` → `objective=binary sigmoid:1`.

The spec's label definitions use `H = 5` (`AS_GRID_FULL_SPECIFICATION.md:181-187`); the shipped trainer uses `H = 1`. `LESSONS_LEARNED.md:86-90` records this as an intentional fix ("预测目标调整为微观 H=1（下一根 1m Bar）").

### 6.2 Feature list

7 features, `kaggle_trainer/trainer.py:51`:

```python
X = np.column_stack([p_vol, gk_vol, atr14, bar_ofi, f_dev, s_r1, vol_accel])
```

| # | Name | Definition | Source |
|---|---|---|---|
| 0 | `p_vol` | Parkinson volatility, annualised, `min 0.08` | `kaggle_trainer/trainer.py:34-39` (computed upstream); `AS_GRID_FULL_SPECIFICATION.md:135-139` |
| 1 | `gk_vol` | Garman-Klass volatility, annualised, `min 0.08` | `AS_GRID_FULL_SPECIFICATION.md:141-145` |
| 2 | `atr14` | ATR(14), `min 0.5` | `AS_GRID_FULL_SPECIFICATION.md:147-150` |
| 3 | `bar_ofi` | OFI/LOB imbalance, clipped to [-3, 3] | `AS_GRID_FULL_SPECIFICATION.md:163-170` |
| 4 | `f_dev` | `(C − MA20) / max(ATR14, 0.05)` | `AS_GRID_FULL_SPECIFICATION.md:152-154` |
| 5 | `s_r1` | 1-bar micro return `(C_t − C_{t−1}) / C_{t−1}` | `AS_GRID_FULL_SPECIFICATION.md:156-157` |
| 6 | `vol_accel` | `V / max(MA20(V), 1e-9)`, clipped to [0.01, 50] | `AS_GRID_FULL_SPECIFICATION.md:159-161` |

The saved boosters carry `feature_names=Column_0 Column_1 Column_2 Column_3 Column_4 Column_5 Column_6` — names were not preserved at save time, so **the feature order is an implicit contract enforced only by array position**. The `feature_infos` ranges in the artifact header match the trainer's data ranges, e.g. `Column_2` ∈ [0.1128, 735.16] (ATR) and `Column_6` ∈ [0.01, 9.905] (vol_accel).

### 6.3 Training loop

`kaggle_trainer/trainer.py`:
- Data is embedded as base64+gzip in the source (`:16 RAW_B64`), decoded at `:17-18` into a `(N, 9)` float32 array.
- Feature engineering is causal: `rolling(20, min_periods=1).mean()`, no `.bfill()` (`:33-39`). This is the fix recorded at `LESSONS_LEARNED.md:85-89`.
- Split: `valid_len = int(n * 0.70)`; models train on `X[:valid_len]` only (`:54`, `:55`, `:60`, `:65`). **The held-out 30 % is never scored inside the trainer** — the "out_of_sample_metrics" in the checkpoint JSON come from a separate Numba path, and the trainer's own log prints only training-set statistics (`:73`).
- Hyperparameters: drift → `num_leaves=15`, `lr=0.08`, `num_boost_round=50`, metric rmse (`:56-57`). Toxic → `num_leaves=12`, `lr=0.08`, `num_boost_round=40`, metric auc (`:61`, `:65`). `AS_GRID_FULL_SPECIFICATION.md:194-215` additionally specifies `max_depth=4`, `min_data_in_leaf=50/30`, `n_jobs=2`; the shipped trainer omits `max_depth` and `min_data_in_leaf`.
- No walk-forward, no purge/embargo, no block-bootstrap CI, no label-shuffle test in the trainer. These are demanded by `docs/design/02-ml-training-loop.md:574` (embargo 420 s), `docs/design/00-methodology-master.md:264` (block bootstrap 95 % CI), and `:245` (shuffle test).
- Then: predict over the full set (`:69-71`), Numba-JIT genetic search over (gamma, kappa, alpha_d, beta_tox) (`:76-120`), and checkpoint export.

**Trainer log header** (`checkpoints/btc-as-lob-mm-trainer.log`):
```
Loaded 18181 sampled high-frequency micro bars on Kaggle.
ML models trained successfully. Drift std: 0.4929, ToxDown mean: 0.6910
```
and the exported `out_of_sample_metrics`:
```
oos_bars_count: 5455
total_return_pct: -5.03
max_drawdown_pct: 19.27
total_trades: 858
calmar_ratio: -0.26
```

Two observations a designer must carry:
1. **The shipped models are OOS-negative**: −5.03 % return, 19.27 % drawdown, Calmar −0.26.
2. **`ToxDown mean = 0.6910` exceeds the 0.65 circuit-breaker threshold** (`src/as_ml_engine.py:91`, `live_cluster/legacy_run_live_v1.py:380`, `src/run_2year_asgrid_backtest.py:134`). If these boosters were wired into the live path, the bid breaker would fire on roughly 69 % of bars. This is consistent with the audit finding at `as_grid_development_full_history.html:5074`: "在强劲的单边大牛市中…`pred_tox_d` 触发的概率高达 43.36%，几乎与 `pred_tox_up`（44.50%）完全持平".

### 6.4 Drift guard

**Implemented (weakly):** `live_cluster/cron_accountbot3_ml_guard.py`:
- Feature-range validity (`:101-107`): `gk_vol ∈ [0.05, 2.50]`, `|ofi_norm| ≤ 3.5`, `|ma20_dev| ≤ 5.0`, `|mu_pred| ≤ 3.0`. `ml_healthy = all(...)` (`:107`).
- Checkpoint presence (`:109-112`): the three `.txt` files must exist. **Existence only — no hash, no load, no prediction.** This is the sole use of the checkpoints in the entire running system.

**Specified but not implemented:** PSI drift monitoring with a 0.10 / 0.25 yellow/red split and the 10-bucket formula (`docs/design/04-live-ops-capital-and-monitoring.md:597`, `:605-613`), KS on prediction distributions (`:598`), prediction-mean shift (`:599`), live-vs-backtest two-sample KS (`:600`), and the `δ*_std_24h < 0.2 bps` model-degeneration sentinel (`docs/design/02-ml-training-loop.md:1063-1066`).

**Checkpoint versioning is declared unsafe by the author:** `docs/design/00-methodology-master.md:280` — "`checkpoints/lgb_*.txt`（2026-10-25 旧权重）| **必须重训**：特征逻辑已改（`.bfill()` → 因果，H=5 → H=1）".

**Artifact inconsistency:** `checkpoints/as_mm_checkpoint.json` reports `gamma_risk_aversion: 0.0422, kappa: 1.8285, drift_alpha: 0.599, toxic_beta: 1.0982` (AlphaGPT-evolved, per its `model_name`), while `checkpoints/btc-as-lob-mm-trainer.log` exported `gamma 0.0451, kappa 2.1346, drift_alpha 0.5563, toxic_beta 0.9544` (certified Kaggle baseline), and `live_cluster/as_dynamic_risk.py:56-57` uses the latter values as the institutional tier. The live service uses **neither** — it hardcodes `gamma=0.35` at `live_cluster/run_live.py:158`.

### 6.5 How a prediction blocks or reshapes a quote

| Path | Reshape | Block |
|---|---|---|
| `src/as_ml_engine.py:73-74` | `delta_ask = base·(1 + β·p_toxic_up) − inv_bias`; `delta_bid = base·(1 + β·p_toxic_down) + inv_bias` | `p_toxic_down >= 0.65` → `allow_bid = False`; `p_toxic_up >= 0.65` → `allow_ask = False` (`:91-94`) |
| `live_cluster/legacy_run_live_v1.py:356-357` | same shape | `:380-383` |
| `live_cluster/as_nautilus_strategy.py:99-100` | `×1.5` on the toxic side | `:115-121` (rule-derived, not model-derived) |
| `src/run_2year_asgrid_backtest.py:114-115` | `base·(1 + β·p_tox)` | `:134-139`, and `adverse_mitigations` incremented on each cut |

The drift prediction enters only through the reservation price: `+ alpha_drift · mu_pred · (mid · c)` with c = 0.0005 (`src/as_ml_engine.py:43`), 0.0005 (`src/run_2year_asgrid_backtest.py:97`), 0.0003 (`live_cluster/as_nautilus_strategy.py:75`), and 0.0005 in the legacy runner (`live_cluster/legacy_run_live_v1.py:343`).

**Summary of the ML reality:** in the code that runs, the "ML" is a pair of linear/clip expressions (`live_cluster/as_nautilus_strategy.py:72-75`) and a three-clause rule (`:92-93`). The boosters exist as artifacts, are loaded only by an orphaned runner, and were trained on a 18,181-bar sample whose own OOS result is negative.

---

## 7. Ops machinery

### 7.1 `live_cluster/cron_hot_monitor.py` — the performance observer

- **Cadence:** docstring says "Polls VPS A-S ML Grid every 5 minutes" (`:4`); the install command in `AS_GRID_FULL_SPECIFICATION.md:378` is `*/10 * * * *`. The docstring and the crontab disagree.
- **Inputs:** `03_as_grid_status.json` and `03_as_grid_fills.json` and `monitor_perf_state.json` under `/opt/nautilus_cluster/logs` (`:16-20`).
- **Alerts on / reports:** actual fills since last update (`:96-97`), turnover `delta_trades × 0.01 × mid_px` (`:100-101`), PnL since update `equity − initial_equity` (`:104`), current equity (`:68`), unrealized PnL and net position from the REST API (`:69-73`), reservation price and the ML drift/toxicity block from the status file (`:122-126`), and a win rate.
- **The win rate is not a win rate.** `:113-118` counts the fraction of *consecutive fill pairs whose side differs* and calls it `win_rate`. That is a direction-change rate, not a round-trip PnL win rate. Default when the fills file is missing: **88.5** (`:107`).
- **Calmar is hardcoded to 28.4** (`:108`) and never computed.
- **The footer hardcodes `gamma=3.0`** (`:149`) while the deployed code uses 0.35 (`live_cluster/run_live.py:158`).
- **Persisted state:** `monitor_perf_state.json` with `initial_equity` and `prior_trades_count` (`:88-94`). It is written **only when the file does not yet exist** (`:88`, `:91-94`), so `prior_trades_count` is never updated afterwards and `delta_trades` (`:97`) is computed against a stale baseline forever.
- **Sends Telegram every cycle**, unconditionally (`:151`) — not an alert-on-anomaly design.
- **Credential defect:** live Telegram token and chat id at `:22-23`; live OKX api_key / api_secret / passphrase at `:55-57`.
- **File mismatch:** it reads `03_as_grid_*` (`:18-19`) while the running service writes `07_as_grid_*` (`live_cluster/run_live.py:37-38`). It therefore observes a different service's files, or files that no longer exist.

### 7.2 `live_cluster/cron_accountbot3_ml_guard.py` — the compliance watchdog

- **Container liveness:** `docker inspect nautilus_vps_007_accountbot3` for `Running, Restarting, StartedAt` (`:44-53`).
- **Heartbeat:** parses `status_data["timestamp_utc"]` and computes lag; alive if `lag <= 60.0` s (`:76-85`).
- **ML health:** the four feature-range checks (`:101-107`) plus checkpoint-file existence (`:109-112`).
- **Decision-logic alignment — four goals:**
  1. Fee hurdle: `spread_bps >= 8.5` (`:122-124`). Note this is **8.5**, while the strategy enforces 9.0 (`live_cluster/as_nautilus_strategy.py:27`) and the design doc mandates 9.0 (`docs/design/02-ml-training-loop.md:1026`).
  2. Strict maker: `bid_quote < mid` and `ask_quote > mid` (`:127`).
  3. Inventory bound: `abs(inventory) <= 0.05001` (`:130`).
  4. Queue-hold vs cancel churn: merely *observes* that the strings `QUEUE_HOLD` and `POST` appear in the actions list (`:133-134`). It does not fail on churn.
- **Compliance score:** six booleans / 6 × 100 (`:137-144`). `HEALTHY_OPTIMAL` at ≥ 83.3, `DEGRADED` at ≥ 50, else `CRITICAL` (`:146`).
- **Alerts:** Telegram **only when status ≠ HEALTHY_OPTIMAL** (`:222-230`). This is the correctly-designed one of the two.
- **Persists:** `accountbot3_ml_health.json` under `/opt/nautilus_cluster/logs` (`:24`, `:190-195`), with runtime liveness, ML diagnostics, decision alignment, and real trade performance blocks (`:148-187`).
- **Reads `07_as_grid_*` files** (`:21-23`), matching the running service (`live_cluster/run_live.py:37-38`). The file naming is consistent here and inconsistent in `cron_hot_monitor.py`.

### 7.3 What neither watchdog does

Neither reads P&L per fill, computes markouts, tracks adverse selection, measures `e` (net capture in bp), or enforces a drawdown kill switch. `docs/design/04-live-ops-capital-and-monitoring.md:590-613` specifies all of that (L1.1–L3.12) and `:623-633` explicitly lists the missing code as "当前缺失，必须补". `docs/design/00-methodology-master.md:177` names the single most important alert: "`e_rolling_100 ≤ 0` ⇒ 冻结加仓" — **not implemented**.

---

## 8. Backtest fidelity claim and headline numbers

### 8.1 What the code claims

`src/run_2year_asgrid_backtest.py:7-13` lists five "Execution & Market Microstructure Rules":
```
0. Explicit Maker 0.02% (2 bps) & Taker 0.05% (5 bps) fee on full notional.
1. Smooth inventory skew (no discrete jump/cross mid-price).
2. ADX(14) macro-trend directional gating.
3. Post-fill cooldown.
3. Volatility surge protection (2.5x spread expansion on GK-vol spikes).
5. FIFO roundtrip matching to track Win Rate, Profit Factor, and Win/Loss ratio.
```
and `reports/ASGRID_2YEAR_BENCHMARK_REPORT.md` calls it "过去2年高保真回测报告" (high-fidelity backtest).

### 8.2 What the fill model actually is

`src/run_2year_asgrid_backtest.py:159-161` and `:190-192`:

```python
if allow_bid and l <= bid_p:
    fill_p = bid_p; notional = fill_p * lot_size; fee = notional * maker_fee
    cash -= (notional + fee); q += 1.0
```

A buy fills in full if the bar's **low** touches the bid. A sell fills in full if the bar's **high** touches the ask (`:190-205`). Consequences:

- **No queue position.** Zero modeling of volume ahead at the price level.
- **No partial fills.** A 1-minute bar is treated as an unlimited liquidity source at one price.
- **Both sides can fill in the same bar** (`:159` then `:190`, no mutual exclusion), so a bar with a wide range produces two fills against each other at the extremes.
- **No latency.** No order-rejection, no cancel/repost race.
- **No size at level.** `lot_size=0.05` BTC is filled regardless of book depth.
- **Taker fee is defined (0.0005) but never charged** — `src/run_2year_asgrid_backtest.py:319` passes `taker_fee=0.0005` into the simulation, but the parameter does not appear inside `run_2year_simulation_numba`'s body (`:31-236`). Every fill is booked at `maker_fee`.
- **The "ML" inputs are surrogate formulas**, `src/run_2year_asgrid_backtest.py:274-278`:
  ```python
  pred_drift = clip(-0.45*f_dev + 0.35*ofi_norm - 0.20*r1, -4, 4)
  z_down = 1.8*(gk/vol_med) - 1.2*ofi_norm + 0.8*vol_accel - 2.5
  pred_tox_d = sigmoid(clip(z_down, -10, 10))
  z_up = 1.8*(gk/vol_med) + 1.2*ofi_norm + 0.8*vol_accel - 2.5
  pred_tox_u = sigmoid(clip(z_up, -10, 10))
  ```
  The trained boosters are not used.

The author's own audit says this plainly. `as_grid_development_full_history.html:5061-5063`:
> "**缺少订单排队（Queue Position）模型**：只要 1 分钟 K 线的 Low 触及买价即假定全额成交，极大夸大了 Maker 成交概率。……**缺少逆向选择惩罚**……**低价差失血被隐藏**"

And `docs/design/03-queue-aware-backtest-engine.md:16` states the plan is to build a queue-aware engine; `docs/design/00-methodology-master.md:282` reclassifies the artifact:
> "`src/run_2year_asgrid_backtest.py`（+68.19%）| **降级为参数化折价模型**（Tier-2），不再作为上线依据 | 队列感知引擎（Tier-1）"

### 8.3 Headline numbers, exactly as recorded

`reports/asgrid_2year_metrics.json` (2-year, 2024-02-14 10:04:00 → 2026-02-14 10:04:00):

| Metric name | Value |
|---|---|
| `initial_capital` | 100000.0 |
| `final_equity` | 168191.79 |
| `net_profit` | 68191.79 |
| `total_return_pct` | 68.19 |
| `cagr_pct` | 29.62 |
| `max_drawdown_pct` | 4.1 |
| `sharpe_ratio` | 3.22 |
| `sortino_ratio` | 5.87 |
| `calmar_ratio` | 7.22 |
| `total_trades` | 223690 |
| `buy_trades` | 111848 |
| `sell_trades` | 111842 |
| `total_roundtrips` | 111842 |
| `win_trades` | 49825 |
| `loss_trades` | 62017 |
| `win_rate_pct` | 44.55 |
| `profit_factor` | 1.16 |
| `win_loss_ratio` | 1.44 |
| `mean_win_usd` | 10.13 |
| `mean_loss_usd` | 7.04 |
| `maker_fee_paid` | 192574.11 |
| `total_notional_volume` | 962870544.55 |
| `adx_blocked_bids` | 282230 |
| `adx_blocked_asks` | 282127 |
| `adverse_mitigations` | 920850 |
| `vol_surge_events` | 95766 |

`reports/ASGRID_2YEAR_BENCHMARK_REPORT.md` states the bar count as **1,048,823 根 1m 高频连续 K 线** and the daily turnover as **~$1,315,396.92**. Note the arithmetic: $962,870,544.55 over ~730 days is $1.32 M/day, i.e. ~$15.4k per minute, on a $100k account — 9.6× the account per day, at 2 bps maker fee on both sides.

`reports/asgrid_orig_v2_metrics.json` (3.12 years, 2023-01-01 → 2026-02-14):

| Metric name | Value |
|---|---|
| `initial_capital_usd` | 100000.0 |
| `final_equity_usd` | 157884.41 |
| `net_profit_usd` | 57884.41 |
| `total_return_pct` | 57.88 |
| `cagr_pct` | 15.74 |
| `max_drawdown_pct` | 5.89 |
| `sharpe_ratio_annualized` | 2.04 |
| `sortino_ratio` | 3.5 |
| `calmar_ratio` | 2.67 |
| `total_trades` | 1442486 |
| `buy_trades` | 721248 |
| `sell_trades` | 721238 |
| `fifo_round_trips` | 721238 |
| `win_rate_pct` | 47.21 |
| `profit_factor` | 1.03 |
| `avg_win_usd` | 5.2 |
| `avg_loss_usd` | 4.5 |
| `payoff_ratio` | 1.16 |
| `total_maker_fee_paid_usd` | 950249.85 |
| `total_volume_usd` | 4751249239.43 |

`reports/asgrid_rect_v2_metrics.json` (3.12 years, "rectified"):

| Metric name | Value |
|---|---|
| `initial_capital_usd` | 100000.0 |
| `final_equity_usd` | 471385.11 |
| `net_profit_usd` | 371385.11 |
| `total_return_pct` | 371.39 |
| `cagr_pct` | 64.27 |
| `max_drawdown_pct` | 1.37 |
| `sharpe_ratio_annualized` | 10.17 |
| `sortino_ratio` | 39.89 |
| `calmar_ratio` | 47.01 |
| `total_trades` | 773340 |
| `buy_trades` | 386675 |
| `sell_trades` | 386665 |
| `taker_unwinds` | 0 |
| `fifo_round_trips` | 386665 |
| `win_rate_pct` | 50.78 |
| `profit_factor` | 1.34 |
| `avg_win_usd` | 7.52 |
| `avg_loss_usd` | 5.81 |
| `payoff_ratio` | 1.29 |
| `total_fee_paid_usd` | 512990.06 |
| `total_volume_usd` | 2564950309.41 |
| `adverse_selection_mitigations` | 144153 |
| `volatility_surge_events` | 145274 |

**These three reports are mutually inconsistent** (57.88 % over 3.12 y vs 68.19 % over 2 y vs 371.39 % over 3.12 y, on the same data and the same nominal fee). `reports/ASGRID_RECT_V2_BENCHMARK_REPORT.md` documents the generating script as **not present in this repo** (there is no `src/*rect*` or `src/*orig*` file). The reproducible one is the 2-year run.

### 8.4 The measured live baseline, which contradicts all of the above

`docs/design/00-methodology-master.md:59-70`, the author's own 【实测】 table for the real `accountbot3` OKX account:

| Item | Value |
|---|---|
| 实盘账户 | `accountbot3`, OKX real BTC-USDT-SWAP, 30 USDT |
| 单笔最小名义 | 0.01 张 ≈ 8.08 USDT = 27 % of equity |
| Maker 比例 | 99.5 % |
| 手续费 | 0.3269 USDT over 10.38 h |
| **净捕获率 e** | **−0.55 bp/名义** |
| **逆向选择成本 a** | **≈ 3.05 bp/名义 (吃掉 67.8 % 报价半价差)** |
| 报价半价差 δ | 4.5 bp (总价差 9.0 bp 门槛) |
| 价差捕获比例 φ | ≈ 1.0 |
| 网络 RTT | 45–75 ms |
| 事件循环抖动 | 10–50 ms |
| OKX 最优价档位生命周期 | 中位 1.73 s，每 3.8 秒换一次最优价 |
| 队列周转 | 买一档平均约 16 秒被清空一次 (219 次/小时) |

And `docs/design/00-methodology-master.md:74`:
> "`e = −0.55 bp` ⇒ 现在的首要任务不是训练模型，是**把 a 从 3.05 压到 2.5 以下**。"

This is the number a designer should plan against. The live strategy loses 0.55 bp per notional traded; the backtest claims +29.62 % CAGR on the same instrument. **A port to Polymarket inherits the live result, not the backtest result.**

---

## 9. Assumptions that break for a Polymarket binary option

### 9.1 Price bounded in (0, 1)

| Break | Citation |
|---|---|
| The base half-spread in the grid engine is an **absolute price quantity**, not proportional. `(1/γ)·ln(1+γ/κ)` with γ=0.1, κ=1.5 = **0.6454**. On a 0.5-cent token that is a 129 % half-spread; the `max(0.0005, …)` floor is meaningless against it. | `src/avellaneda_stoikov_engine.py:63`, `:72` |
| The `0.0005` floor and the `max(0.0005, …)` clamps are absolute price units. On a tick of 0.001 they are half a tick; on 0.01 they are 5 % of a tick. | `src/avellaneda_stoikov_engine.py:72` |
| The reservation price `r` can leave `[0,1]`. There is **no clamp to `[0,1]` anywhere in the tree** — `r` is only ever bounded by the maker guarantee relative to mid (`mid ± min_half·0.5`), which on a near-0 or near-1 token can put the bid below 0 or the ask above 1. | `live_cluster/as_nautilus_strategy.py:109-110`; `src/as_ml_engine.py:84-85` |
| `round(..., 1)` rounds to **one decimal place**. On a probability in (0,1) that is 10-cent granularity; on a 0.01 tick it is a whole tick; on a 0.001 tick it is 10 ticks. | `live_cluster/as_nautilus_strategy.py:105-106`; `src/as_ml_engine.py:80-81` |
| The fee hurdle is denominated in **bps of mid**. A 9 bps hurdle on a 0.50 token is 0.00045 = less than half a 0.001 tick — the floor becomes unattainable or meaningless depending on tick. The correct unit for a binary is cents of the token. | `live_cluster/as_nautilus_strategy.py:82`; `src/run_2year_asgrid_backtest.py:102` |
| The drift coefficient `mid·0.0003` and the skew coefficient `mid·0.0008` are proportional to price, so a token at 0.02 gets a skew scaled to 2 % of the price. The correct scaling for a probability is absolute (in probability units), not proportional. | `live_cluster/as_nautilus_strategy.py:75`, `:77` |

### 9.2 Terminal settlement / expiry at a known timestamp

| Break | Citation |
|---|---|
| **The horizon term does not exist in the production formula.** `live_cluster/as_nautilus_strategy.py:77` has no `(T−t)` factor; the skew is constant for the life of a position. | `live_cluster/as_nautilus_strategy.py:77` |
| `self.T` is assigned in both engines and **never read**. `t_left` defaults to 1.0 and is **never passed by any caller**. `(T−t) ≡ 1.0` constant. | `src/avellaneda_stoikov_engine.py:43`, `:57`, `:67`; `src/as_ml_engine.py:27`, `:42` |
| The author's documented substitution: "(T − t) … **（实盘中离散化为常数阻尼项）**". | `AS_GRID_FULL_SPECIFICATION.md:43` |
| The author's design-doc restatement uses a fixed `T` in seconds, not a shrinking horizon. | `docs/design/02-ml-training-loop.md:1072`, `:1291` |
| **The theoretical justification inverts.** The author cites GTL (2012): A-S's closed form is only a first-order expansion valid as `t → T`, and for `T−t ≫ 0` the optimal quotes are *time-independent*. That licenses freezing the horizon for a perpetual. For a binary with a fixed expiry, `(T−t)` is exactly the term that drives end-of-life inventory liquidation. | `as_grid_development_full_history.html:4973`, `:5009-5010` |
| **There is no expiry machinery at all**: no timer, no "cancel all and settle" branch, no settlement price fetch, no expiry-driven skew ramp. `grep -rn "到期\|expiry\|expire\|settle"` over the Python tree returns nothing. The only expiry language in the repo is in a design table about *other* venues' settlement mechanisms. | `docs/design/01-data-pipeline-and-symbol-selection.md:335`, `:1123` |
| The one place the author writes a horizon-correct formula is the *research log*, and it is not in any engine: `$r^*(s,q,t) = s + \frac{\mu}{\gamma\sigma^2} - q\gamma\sigma^2(T-t)$`. | `as_grid_development_full_history.html:5088` |
| The 2-year backtest has no expiry handling either, and its horizon of 2 years is not modelled at all. | `src/run_2year_asgrid_backtest.py:96` |

### 9.3 No shorting (sell = buy the complement token)

| Break | Citation |
|---|---|
| Inventory is a **signed linear count of contracts**, negative for short. `self.inventory` decreases on a sell. A Polymarket "sell YES" is not a short in this model's terms — it is a long NO, and its risk is bounded at 1, not unbounded below. | `live_cluster/as_nautilus_strategy.py:42`, `:171-174`; `src/avellaneda_stoikov_engine.py:49` |
| `allow_ask = (self.inventory > -self.max_inventory)` explicitly permits a **negative inventory** (a naked short) and the symmetric skew lets the reservation price tilt upward to encourage it. | `live_cluster/as_nautilus_strategy.py:113`; `src/as_ml_engine.py:99-100`; `src/avellaneda_stoikov_engine.py:106-107` |
| The grid engine's defensive-mode branch treats `inventory < 0` as the short case to be unwound. | `src/avellaneda_stoikov_engine.py:106-107`, `:111-112` |
| The backtest books a sell as `q -= 1.0` and allows `q` down to `−10` (−0.5 BTC). On a binary, inventory below the minimum token count is not a short but an *arbitrage-free* dual position, and the P&L geometry is different (bounded, not linear). | `src/run_2year_asgrid_backtest.py:164`, `:198`, `:306` |
| The maker guarantee `ask_px = max(ask_px, mid + min_half·0.5)` protects against crossing the book. On Polymarket, "crossing" also means consuming the *complement* token's book, which the model does not represent at all. | `live_cluster/as_nautilus_strategy.py:110` |

### 9.4 Tick size 0.01 or 0.001

| Break | Citation |
|---|---|
| `round(px, 1)` is one decimal place — 0.1 in the venue's own quote unit for OKX. The repo's tick is documented as "OKX tick = 0.1 USDT". | `src/as_ml_engine.py:80-81`; `live_cluster/as_nautilus_strategy.py:105-106`; `docs/design/02-ml-training-loop.md:1027` |
| There is **no tick-rounding helper**; rounding is hardcoded to 1 decimal in three places. | `src/as_ml_engine.py:80-81`; `live_cluster/as_nautilus_strategy.py:105-106`; `live_cluster/legacy_run_live_v1.py:363-364` |
| The price tolerance for queue-hold is in **USDT** (`max(1.5, mid_px * 0.0001)`), i.e. an absolute currency amount. A 1.5-cent minimum tolerance is 150 ticks on a 0.01-tick market and 1,500 ticks on a 0.001-tick market — the queue would never be refreshed. | `live_cluster/run_live.py:241` |
| The fee hurdle is a fraction of mid, so its conversion to ticks varies with the token price. The repo itself flags the hardcoded-constant problem: "我们当前的「≥9.0 bps 总价差门槛」是硬编码常数，应升级为「按名义额动态计算门槛」". | `docs/design/05-portable-open-source-survey.md:379` |

### 9.5 Maker-only

| Break | Citation |
|---|---|
| Post-only is enforced and maps cleanly: `ord_type="post_only"` on both sides, and the rejection path is handled (`BID_REJ(msg)`). Polymarket's CLOB carries a `post_only` flag per order, so this is the most portable piece of the execution stack. | `live_cluster/run_live.py:281`, `:303`, `:286-289` |
| The author treats post-only as a hard red line: "**铁律**：所有做市报文必须显式指定 `ord_type = "post_only"` … 交易所撮合引擎将直接撤销该单，确保做市商永远只赚取流动性价差与返佣". | `AS_GRID_FULL_SPECIFICATION.md:264-270`; `README.md:60-62`; `LESSONS_LEARNED.md:74-75` |
| **Reduce-only has no analogue and no implementation.** `grep reduceOnly` over the Python tree returns nothing; OKX's `reduceOnly` field is not part of the body built at `live_cluster/gateway_okx_client.py:117-129`. On Polymarket there is no reduce-only; exiting inventory means buying the complement, which the model cannot express. | `live_cluster/gateway_okx_client.py:117-129` |
| `td_mode="cross"` is hardcoded and has no Polymarket analogue. | `live_cluster/run_live.py:279`, `:301` |
| The `x-simulated-trading` header and the demo/live switch have no Polymarket analogue (Polymarket has a separate testnet host). | `live_cluster/gateway_okx_client.py:58-59`; `live_cluster/run_live.py:130` |

### 9.6 Polymarket-specific facts the repo already knows

- `docs/design/05-portable-open-source-survey.md:206` lists `polymarket` among NautilusTrader's exchange connectors.
- `docs/design/05-portable-open-source-survey.md:397` lists it among the 21 live adapters: "21 个适配器，含 `okx`、`hyperliquid`、`lighter`、`databento`、`tardis`、`bybit`、`binance`、`kraken`、`deribot`、`dydx`、`polymarket`、`kalshi` 等。"
- `docs/design/05-portable-open-source-survey.md:367` lists Polymarket among Hummingbot's connectors.
- `docs/design/05-portable-open-source-survey.md:234` records that `mileswangs/pm-hftbacktest` (★131) is a Polymarket HFT backtest, and rejects it: "**放弃**：Polymarket 与我们的 OKX/HIP-3 场景无关". **That verdict was written for an OKX/perp context; for a Polymarket port it no longer holds, and this is the single most relevant reusable asset in the repo for a designer.**
- `docs/design/05-portable-open-source-survey.md:605` lists `mileswangs/pm-hftbacktest` in the "maturity insufficient / wrong direction" rejection table.

---

## 10. `LESSONS_LEARNED.md` — what generalizes to any market-making port

The document's own scope statement, `LESSONS_LEARNED.md:3`:
> "本文档记录 Strategy 012 (Avellaneda-Stoikov ML Grid) 在高频回测与 OKX 实盘（accountbot3 30 USDT 微账户）运行中暴露的五大核心缺陷与工程整改方案，杜绝未来部署重犯相同错误。"

All five are venue-independent. The author's own wording follows.

### 10.1 Capital-scale mismatch (`:7-26`)

Failure (`:10-13`):
> "初始本金仅 30.0 USDT，杠杆倍数 3x；实盘在短时间内累积多头持仓达 **0.11 张 BTC-USDT-SWAP 合约**（约 \$89.10 USD 名义敞口）；占用初始保证金 **29.70 USDT**，可用资金降至 **0.25 USDT**（保证金占用率 99.1%）；触发 OKX 交易限制，买单全部被拒（`BID_REJ(All operations failed)`），系统丧失双向做市能力。"

Root cause (`:16-20`):
> "原版代码沿用了 Kaggle 离线以 100,000 USDT 训练的**机构级参数**（$\gamma=0.0451$）；机构账户规模庞大，单位库存引起的保留价格向下偏置微乎其微：$$\text{skew} = q \cdot \gamma \cdot \sigma^2 \cdot S \cdot c$$ 在 $q=0.05$ 时偏置仅有几美分，导致策略完全不急于降库存；结合缺少小额硬风控上限，多头持续累积直至耗尽保证金。"

The generalizable statement: **the skew produced by a parameter set is a function of account size, so the same γ means different things at different scales.** A Polymarket port with a $200 account quoting a 0.55 token has the same problem with different numbers.

### 10.2 Phantom trade accounting (`:30-44`)

Failure (`:33-34`):
> "实盘运行日志中频繁出现上万笔交易记录，但交易所实际成交记录仅寥寥数笔；产生了虚假的高额名义流水与手续费统计。"

Root cause (`:37-39`):
> "旧代码在向 OKX 下达 Post-Only 限价单后，直接以 API 响应 `code == "0"` 判定为成交并写入 `recent_fills`；`code == "0"` 仅代表交易所系统接收并挂单成功，并未发生撮合；2 秒后下一轮循环执行全额撤单，未撮合的挂单被取消，虚增了海量伪流水。"

Fix (`:42-44`):
> "彻底剥离报单确认与成交核算；接入 OKX 私有 WebSocket `orders` 频道与 `/api/v5/trade/fills` 补差核验；只有当交易所推送 `state in ["filled", "partially_filled"]` 且 `fillSz > 0` 时，才执行成交记账。"

Reinforced in the spec at `AS_GRID_FULL_SPECIFICATION.md:260-262`:
> "**历史严重缺陷**：代码中曾因将 `client.place_order` 返回 `code == "0"`（仅代表报单成功被交易所接收）直接累加进 `matched_trades += 1`，导致统计出 7.8 万笔虚假成交。**真理口径**：**成交判定必须且仅能以成交账单为准**。"

This is the most universally applicable lesson. It is implemented correctly in the current code (`live_cluster/okx_ws_manager.py:223-237`).

### 10.3 Queue-priority destruction (`:48-61`)

Failure (`:51`):
> "策略长时间挂单却极难成交，或一旦成交往往是被大单深度击穿。"

Root cause (`:54-56`):
> "每次主循环（约 1~2 秒）无脑对所有挂单执行批量撤销并重新挂单；交易所撮合引擎遵循价格优先与时间优先 (FIFO)；频繁撤单重挂使订单永远位于排队队列的最末端，彻底丧失 Maker 被动成交权。"

Fix (`:59-61`):
> "增加**队列感知挂单保持机制 (Queue Priority Preservation)**；轮询新计算的最优报价：若当前已有挂单且价格偏离 $\le 1.0\text{ USD}$，保留该订单（`BID_QUEUE_HOLD` / `ASK_QUEUE_HOLD`），绝不撤销；仅在价格偏离超标或触发毒性熔断时才撤单。"

The tolerance is venue-relative in the doc (1.0 USD) but currency-absolute in the code (`max(1.5, mid·0.0001)`, `live_cluster/run_live.py:241`). On Polymarket it must be in ticks.

### 10.4 Taker crossing (`:65-75`)

Failure (`:68`):
> "在行情剧烈跳空时，挂出的限价单意外被当作 Taker 吃单撮合，扣除 0.05% 高额手续费。"

Root cause (`:71`):
> "报单使用了普通的 `ord_type="limit"`，一旦报价穿透对手盘买一/卖一，将直接以市价吃单撮合。"

Fix (`:74-75`):
> "全流程强制 `ord_type="post_only"`；若订单穿透对手盘，交易所直接拒绝并返回，坚决不交纳 Taker 惩罚性费率。"

### 10.5 Feature lookahead and horizon mismatch (`:79-90`)

Failure (`:82`):
> "Kaggle 训练集上收益极高，但样本外测试集收益为负（-5.03%）。"

Root cause (`:85-86`):
> "`trainer.py` 中对 `rolling(20)` 调用了 `.bfill()`，使得前 20 根 Bar 的历史数据被未来的均值填充，产生了前瞻泄漏；预测目标采用未来 5 根 Bar（整整 5 分钟后）的价格漂移，无法有效指导秒级高频撤单。"

Fix (`:89-90`):
> "彻底剔除 `.bfill()`，统一采用纯因果的 `rolling(20, min_periods=1).mean()`；预测目标调整为微观 $H=1$（下一根 1m Bar）与实时 Tick OFI 动态更新。"

Note the OOS figure (−5.03 %) matches the shipped `checkpoints/btc-as-lob-mm-trainer.log` exactly. The defect was diagnosed and fixed in the trainer, but **the shipped weights in `checkpoints/` are dated 2026-10-25 and the author marks them "必须重训"** (`docs/design/00-methodology-master.md:280`).

### 10.6 Two lessons the author adds later but that are not in `LESSONS_LEARNED.md`

These live in the design docs and are the most operationally relevant to a port:

- `docs/design/00-methodology-master.md:177`: "**最重要的一条告警**：`e_rolling_100 ≤ 0` ⇒ 冻结加仓。其余都是辅助。"
- `docs/design/00-methodology-master.md:78`: "`单笔 = 27% 权益` ⇒ 30U 上不存在「精细做市」，只存在「测量账户」。"
- `docs/design/00-methodology-master.md:69`: "OKX 最优价档位生命周期 | 中位 1.73 秒，每 3.8 秒换一次最优价" and `:70` "队列周转 | 买一档平均约 16 秒被清空一次（219 次/小时）" — these are the numbers that set the minimum viable loop cadence.
- `AS_GRID_FULL_SPECIFICATION.md:400`: "| **实盘胜率很高但总资金持续微跌** | 产生大量被动换手，但价差毛利无法击穿交易所双边手续费 | 启用 `asgrid-arb` 方案，强制锁定基础价差 $\ge 10.0\text{ bps}$，彻底阻断无效超高频磨损。|" — the failure mode of a market maker whose only edge is volume.

---

## 11. What a designer should reuse, and what should not be carried over

**Reusable as-is (venue-neutral):**
- The execution discipline: post-only, queue-hold tolerance, batch cancel, strict fill accounting from a private feed, fill dedup. `live_cluster/okx_ws_manager.py:215-237`, `live_cluster/run_live.py:240-313`.
- The risk-gate *shape*: fee hurdle, inventory bound, toxicity block, ADX trend block, post-fill cooldown — as a five-stage clamp applied after pricing. `live_cluster/as_nautilus_strategy.py:81-134`, mirrored in `docs/design/02-ml-training-loop.md:1025-1035`.
- The degradation ladder concept: model → analytic A-S → stop quoting, with the clamp layer unchanged. `docs/design/02-ml-training-loop.md:1046-1056`.
- The OFI feature set and the Cont-Kukanov-Stoikov implementation. `live_cluster/okx_ws_manager.py:114-162`.
- The three-layer monitoring architecture and the "one Python daemon + JSON files + Telegram" constraint (no Prometheus on a 1-core box). `docs/design/04-live-ops-capital-and-monitoring.md:513`, `docs/design/00-methodology-master.md:176`.

**Must be rewritten, not ported:**
- The reservation-price and spread formulas (§2). Four variants exist and none agrees. The unit system must move from "price × bps" to "probability × cents".
- The fill model (§8.2). Bar-touch is not a fill model.
- The ML wiring (§0, §6). The boosters are OOS-negative, the live path does not use them, and the backtest used a surrogate.

**Must be added, which does not exist anywhere in the repo:**
- A shrinking `(T−t)` term driven by a known expiry, with an end-of-life forced-flattening branch.
- A `[0,1]` price clamp and a tick-rounding helper parameterized by the market's tick size.
- A complement-token inventory model replacing the signed-linear one.
- The `e_rolling_100 ≤ 0` freeze (`docs/design/00-methodology-master.md:177`), the markout buffer, and the per-fill net-bps accounting (`docs/design/04-live-ops-capital-and-monitoring.md:623-633`).

**Must be removed before any deployment:**
- The hardcoded Telegram token and OKX credentials in `live_cluster/cron_hot_monitor.py:22-23`, `:55-57` and `live_cluster/cron_accountbot3_ml_guard.py:27-28`.
