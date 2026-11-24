# Polymarket Platform Capability Report — for a small-capital pure maker

**Research date:** 2026-11-21 (local Asia/Shanghai). All live observations below were taken between 2026-11-20T16:36Z and 2026-11-20T17:10Z UTC.

**Clock caveat that changes one of the task's premises:** the task states the 2026-11-20 23:59 UTC fee/rebate change is "already in effect as of today, 2026-11-21". That is **not** true at the moment of observation. The CLOB server clock said `2026-11-20T16:40Z` (`GET https://clob.polymarket.com/time` → `1795192819` = 2026-11-20T16:40:19Z). Local workstation time was `2026-11-21 00:42 CST` (Asia/Shanghai, UTC+8), i.e. the same instant. The change takes effect at **2026-11-20T23:59Z**, roughly seven hours after observation. The live fee schedules observed still match the **old** tables (e.g. crypto taker coefficient `0.07` on the Gamma market object and in `clob-markets` `fd.r`, and crypto maker rebate pool 20%). See §1.

Everything below is either (a) quoted from the official docs with the page URL, or (b) marked **LIVE** with the exact command and observed output. Anything not verifiable from either source is marked **UNVERIFIED** with what would verify it.

---

## 1. Fee and rebate rules

### 1.1 Current (pre-change) rules — what was live at observation time

Source: https://docs.polymarket.com/trading/fees.md and https://docs.polymarket.com/programs/maker-rebates.md (both carry a banner: "Upcoming changes — November 20, 2026 at 23:59 UTC. The current rules below apply until then.")

Taker fee formula (identical before and after the change):

```text
fee = shares × feeRate × price × (1 − price)
```

`shares` = filled quantity, `price` = fill price in dollars, `feeRate` = category coefficient. Makers pay **no** platform trading fee (both pages state this).

**LIVE** — Gamma market object for the active `btc-updown-5m-1795278600` market:

```bash
curl -s "https://gamma-api.polymarket.com/markets/slug/btc-updown-5m-1795278600"
```

```json
"feeSchedule": {"exponent": 1, "rate": 0.07, "takerOnly": true, "rebateRate": 0.2},
"feeType": "crypto_fees_v2",
"makerBaseFee": 1000, "takerBaseFee": 1000, "makerRebatesFeeShareBps": 10000,
"feesEnabled": true
```

**LIVE** — same market via CLOB:

```bash
curl -s "https://clob.polymarket.com/clob-markets/0x1b45ab9e241e496e9a8fa7816857fed551430dbd30ef6b19a84e388abc9a2e39"
```

```json
{"r":{"mi":50,"ma":4.5,"moas":30},"t":[...],"c":"0x1b45ab...","mos":5,"mts":0.01,
 "mbf":1000,"tbf":1000,"ao":true,"aot":"2026-11-20T16:36:43Z","itode":true,
 "fd":{"r":0.07,"e":1,"to":true},"v":"v1"}
```

Decoding against the OpenAPI spec (`https://docs.polymarket.com/api-spec/clob-openapi.yaml`): `r` = rewards config (`mi` min size, `ma` max spread, `moas` min order age seconds), `mos` = minimum order size = 5, `mts` = minimum tick size = 0.01, `mbf`/`tbf` = maker/taker base fee in bps, `itode` = taker-order-delay enabled, `fd` = fee curve (`r` rate 0.07, `e` exponent 1, `to` taker-only), `v` = market protocol version `v1`.

Current category table (https://docs.polymarket.com/trading/fees.md):

| Category | Taker fee rate | Maker fee rate | Maker rebate |
|---|---|---|---|
| Crypto | 0.07 | 0 | 20% |
| Sports | 0.05 | 0 | 15% |
| Finance | 0.04 | 0 | 25% |
| Politics | 0.04 | 0 | 25% |
| Economics | 0.05 | 0 | 25% |
| Culture | 0.05 | 0 | 25% |
| Weather | 0.05 | 0 | 25% |
| Other / General | 0.05 | 0 | 25% |
| Mentions | 0.04 | 0 | 25% |
| Tech | 0.04 | 0 | 25% |
| Geopolitics | 0 | 0 | — (fee-free) |
| Combos | 0.05 | 0 | 0% |

Fees are rounded to 5 decimals; the smallest fee charged is 0.00001 USDC/pUSD (fees page).

**LIVE** — cross-category check on the same endpoint set at observation time:

```bash
curl -s "https://gamma-api.polymarket.com/markets?closed=false&limit=60&order=volume24hr&ascending=false"
```

Observed `feeSchedule` values by category: politics `(0.04, rebate 0.25)`, politics_elections `(0.04, 0.25)`, sports_fees_v3 `(0.05, 0.15)`, crypto_fees_v2 `(0.07, 0.2)`, tech `(0.04, 0.25)`, finance `(0.04, 0.25)`, economics `(0.05, 0.25)`, culture `(0.05, 0.25)`. These match the pre-change table exactly. **They do not match the post-change table** (which would show crypto 0.05, politics 0.05, finance 0.05, tech 0.05). Live evidence that the change was not yet in force.

### 1.2 The change that takes effect 2026-11-20 23:59 UTC

Source: https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026.md

Taker fee coefficients after the change (these are **inputs to the formula, not flat percentages of trade value**):

| Category | Fee coefficient (after) |
|---|---|
| Crypto — BTC 5-minute and 15-minute up/down | 0.05 |
| Crypto — all other markets | 0.01 |
| All sports, incl. NFL and college football | 0.05 |
| Finance | 0.05 |
| Tech | 0.05 |
| Politics — elections | 0.05 |
| Politics — excluding elections and geopolitics | 0.01 |
| Economics | 0.01 |
| Culture | 0.01 |
| Weather | 0.01 |
| Mentions | 0.01 |
| Geopolitics | 0 |
| Combos | 0.05 |
| Other / General | 0.05 |

Geopolitics stays fee-free. Combos keep their own coefficient regardless of leg categories.

**Taker rebate tiers after the change** (page also states Bronze and Silver are removed, and accounts with <$200,000 in 30-day taker weighted volume earn **no** taker rebate):

| Tier | 30-day taker weighted volume | Rebate on taker fees paid |
|---|---|---|
| None | Under $200,000 | 0% |
| Gold | $200,000 → <$1M | 10% |
| Platinum | $1M → <$4M | 25% |
| Diamond | $4M → <$10M | 40% |
| Obsidian | $10M → <$75M | 50% |
| Onyx (new) | $75M and above | 60% |

Price weighting stays; category multipliers removed. Each fee-paying taker fill contributes `shares × price × (1 − price)` to weighted volume. The tier uses the sum over the last 30 days, and this differs from dollar trading volume (`shares × price`). One-time level-up bonuses end.

**Maker rebate tiers after the change** (this is the table a pure maker cares about most):

| Tier | 30-day maker weighted volume | Rebate on taker fees generated by your fills |
|---|---|---|
| None | Under $200,000 | 0% |
| Tier 1 | $200,000 → <$1M | 3% |
| Tier 2 | $1M → <$4M | 7% |
| Tier 3 | $4M → <$10M | 10% |
| Tier 4 | $10M and above | 15% |

Doc example: "a Tier 4 maker whose eligible fills generate $100 in taker fees earns $15 in maker rebates."

### 1.3 How maker weighted volume is computed — the 200k threshold

Per the change page, maker weighted volume uses **the same formula as taker weighted volume**: each eligible fill contributes `shares × price × (1 − price)`, summed over a rolling 30 days. "Maker fills count only toward your maker tier; taker fills count only toward your taker tier."

**What the $200,000 threshold means for a small account — the single most important fact in this report:**

- Before 2026-11-20 23:59 UTC, maker rebates came from daily per-market pools (crypto 20% of taker fees), allocated pro-rata by fee-equivalent share within each market. There was **no volume floor**. A small maker received a small share of the pool, and the payout floor was **$1 pUSD accrued** (https://docs.polymarket.com/programs/maker-rebates.md: "A minimum accrued rebate of $1 pUSD is required for a payout").
- After 2026-11-20 23:59 UTC, maker rebates are **tiered by maker weighted volume**, and the bottom tier is **Under $200,000 → 0%**. A maker below $200,000 of 30-day maker weighted volume earns **nothing** from maker rebates. The old pool mechanism and its $1 floor are replaced by the tier table.
- Note the units mismatch that makes this worse: maker weighted volume accrues as `shares × price × (1 − price)`, which is roughly a *fraction of share count*, not dollars. To reach $200,000 of it, at a typical 0.5 price (where `p(1−p) = 0.25`) you need on the order of 800,000 shares of maker fill volume, and the metric decays quadratically away from 0.5. **UNVERIFIED:** whether the platform literally compares that dimensionless quantity against a dollar-denominated threshold, or normalizes internally before comparison. The docs state the threshold as "$200,000" and the formula as `shares × price × (1 − price)`; I found no page that reconciles the two. What would verify it: the maker-tier response from a live account, or a Polymarket support answer.

**Live confirmation of the pre-change rebate read API** (the endpoint that reports what a maker was actually rebated):

```bash
curl -G "https://clob.polymarket.com/rewards/current" --data-urlencode "date=2026-11-19" --data-urlencode "maker_address=0xFeA4cB3dD4ca7CefD3368653B7D6FF9BcDFca604"
```

Actually the documented route is `/rebates/current`; observed:

```bash
curl -s "https://clob.polymarket.com/rebates/current?date=2026-11-19&maker_address=0xFeA4cB3dD4ca7CefD3368653B7D6FF9BcDFca604"
```

→ `null` (HTTP 200). That is the documented "no rows" response, and it confirms the endpoint is public and unauthenticated. Source: https://docs.polymarket.com/api-reference/rebates/get-current-rebated-fees-for-a-maker.md

---

## 2. Liquidity Rewards

Source: https://docs.polymarket.com/programs/liquidity-rewards.md (the change page explicitly states "Liquidity rewards remain unchanged").

### 2.1 Scoring formula

Variables (doc table):

| Var | Meaning |
|---|---|
| S | Order position scoring function |
| v | Max spread from midpoint (in cents) |
| s | Spread from size-cutoff-adjusted midpoint |
| b | In-game multiplier |
| m / m′ | Market / market complement (NO if m = YES) |
| n | Trader index |
| u | Sample index |
| c | Scaling factor (currently **3.0** on all markets) |
| Q_ne / Q_no | Point total for book one / book two for a sample |

Equations, verbatim:

1. Order scoring: `S(v,s) = ((v − s)/v)² · b`
2. First market side: `Q_one = S(v,Spread_m1)·BidSize_m1 + S(v,Spread_m2)·BidSize_m2 + … + S(v,Spread_m′1)·AskSize_m′1 + …`
3. Second market side: `Q_two = S(v,Spread_m1)·AskSize_m1 + … + S(v,Spread_m′1)·BidSize_m′1 + …`
4. Minimum score:
   - If midpoint ∈ [0.10, 0.90] (single-sided can score): `Q_min = max(min(Q_one, Q_two), max(Q_one/c, Q_two/c))` with `c = 3.0`
   - If midpoint ∈ [0, 0.10) or (0.90, 1.0]: `Q_min = min(Q_one, Q_two)` — **double-sided required**
5. Normalized: `Q_normal = Q_min / Σ_n (Q_min)_n` within a sample
6. Epoch: `Q_epoch = Σ_{u=1..1440} (Q_normal)_u` — the book is sampled **once per minute at a random offset**, so an epoch is one UTC day with up to 1,440 samples
7. Final: `Q_final = Q_epoch / Σ_n (Q_epoch)_n`, multiplied by the rewards available for the market

**Minimum order age** (doc): on most markets an order counts as soon as it rests. Markets with a taker delay are the exception — a resting order counts only after it has rested for the same delay. Sports with a scheduled game start: the delay applies only after the game starts. **Crypto and finance markets: the short taker delay on these markets does not set a minimum age; orders count as soon as they rest.** (Note: `clob-markets` for the up/down market returned `moas: 30`, a 30-second minimum order age — see §8, this is a live observation that sits in tension with the doc sentence. **UNVERIFIED** whether `moas` applies to the rewards clock or to something else.)

### 2.2 `rewards_min_size` and `rewards_max_spread` — definitions and units

- `rewards_min_size` — **shares**, not dollars. Doc: "Minimum order size, in shares, that can qualify for rewards" (https://docs.polymarket.com/market-data/market-details.md#liquidity-reward-settings). An order smaller than this does not score.
- `rewards_max_spread` — **cents**, not a fraction. The methodology table defines `v` as "Max spread from midpoint (in cents)" and the worked example uses "a max spread config of 3 cents" with a 1-cent and 2-cent spread. Live values are 2.5 / 3.5 / 4.5 / 6.5, consistent with cents.
- `rewards_max_spread` is measured from the **midpoint**, with the size-cutoff-adjusted midpoint used for `s`. Spread in the score is `Spread`, absolute distance from that adjusted midpoint.

### 2.3 Daily payout, competition factor, minimum payout

- Payout is **daily at midnight UTC**, distributed directly to maker addresses.
- Competition is **per market**: `Q_final` is your epoch score divided by the sum over all makers in that market, and the market's reward allocation is split accordingly. You only compete with makers in the same market.
- **Minimum payout: $1.** "Amounts below this will not be paid." (doc, Liquidity Rewards page). Same figure on the maker-rebates page for the pre-change program.
- The per-market allocation is the `rate_per_day` in the market's `rewards_config` (see §8).

### 2.4 Endpoint to list reward markets with their current rate per day

Two public, unauthenticated endpoints, both returning the reward config:

**`GET https://clob.polymarket.com/rewards/markets/multi`** — paginated (default page size 100, max 500), cursor via `next_cursor`; `next_cursor: "LTE="` marks the last page. Supports `q` (text), `tag_slug` (repeatable, OR), `event_id` (repeatable), `event_title`, `order_by` (incl. `rate_per_day`), `position` (`ASC`/`DESC`), and `min_*`/`max_*` numeric bounds (min exclusive, max inclusive, zero disables).

**LIVE** working example with rate-per-day sort:

```bash
curl -s "https://clob.polymarket.com/rewards/markets/multi?order_by=rate_per_day&position=DESC&page_size=100"
```

→ HTTP 200, `{"data":[…],"next_cursor":"MTAw","limit":100,"count":100}`. First record:

```json
{"condition_id":"0x2d3c4fc5cde6dfb43448402b912e41bd4453e3f030448ed026bff8f1a0bc072e",
 "market_id":"561263","market_slug":"will-eric-trump-win-the-2028-us-presidential-election",
 "question":"Will Eric Trump win the 2028 US Presidential Election?",
 "market_competitiveness":0,"rewards_config":[],
 "rewards_max_spread":4.5,"rewards_min_size":50,"spread":0.001,
 "tokens":[{"token_id":"67028631656597977031363620447645908995417871899828777750494099295092202422178","outcome":"Yes","price":0.0005}, …]}
```

**`GET https://clob.polymarket.com/rewards/markets/current`** — all current active reward configurations grouped by market.

**LIVE**:

```bash
curl -s "https://clob.polymarket.com/rewards/markets/current?next_cursor=NTAw"
```

→ HTTP 200, 500 rows per page, `next_cursor` walks the set. A row:

```json
{"condition_id":"0x0ab76d6fefb9dae337ac4918db30c3eb0f9119cf904ec8f7fa3b9c04622da04d0",
 "rewards_config":[{"asset_address":"0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB",
                    "start_date":"2026-11-08","end_date":"2500-12-31","rate_per_day":1.09,
                    "total_rewards":0,"id":0}],
 "rewards_max_spread":4.5,"rewards_min_size":20,
 "native_daily_rate":1.09,"total_daily_rate":1.09}
```

Full-scan observation: paging `/rewards/markets/current` to the end returned **7,812 markets**, all with a non-zero `native_daily_rate`, `next_cursor` terminating at `LTE=`.

**`GET https://clob.polymarket.com/rewards/markets/{condition_id}`** — raw rewards for one market (present and future configs).

**LIVE**: for the active BTC 5-minute up/down condition `0x1b45ab9e241e496e9a8fa7816857fed551430dbd30ef6b19a84e388abc9a2e39` → `{"data":[],"next_cursor":"LTE=","limit":100,"count":0}`. Same empty result for the SOL 5m condition `0x6ca8f1a3…`. **Interpretation: the crypto up/down markets currently carry reward *settings* (min size, max spread) but no active rate allocation.** This is the most consequential fact in §8.

Also note an inconsistency I observed between the two list endpoints: `/rewards/markets/multi` returned `asset_address: 0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (**USDC.e**) in the top-100-by-rate sample, while `/rewards/markets/current` returned `asset_address: 0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` (**pUSD**). Both endpoints are documented; the doc's own example shows pUSD in the `multi` response. **UNVERIFIED** which asset a given row is actually paid in. What would verify it: reading the `earnings`/`asset_address` on `/rewards/user/total` for a real account.

**Auth:** the reward *market list* endpoints are public. The *earnings* endpoints require CLOB L2 auth:
- `GET /rewards/user/total?date=…&maker_address=…&sponsored=…` (L2 headers; `sponsored=true` includes sponsored rewards, omitted/false = native only)
- `GET /rewards/user/percentages`
- `GET /rewards/user/earnings` (per market)

---

## 3. Public read APIs (no auth)

Base: `https://clob.polymarket.com`. All of these are unauthenticated.

**Markets** — `GET /markets`, `GET /sampling-markets`, `GET /simplified-markets`.

**LIVE**: `curl -s "https://clob.polymarket.com/markets"` → HTTP 200, `{"data":[{"enable_order_book":false,"active":true,"closed":true,"minimum_order_size":5,"minimum_tick_size":0.01,"condition_id":"0xb62f71ae…","question":"Will Benjamin Netanyahu remain prime minister of Israel through June 30, 2021?",…}]}`.
`GET /simplified-markets` → `{"data":[{"condition_id":"0xb62f71ae…","rewards":{"rates":null,"min_size":0,"max_spread":0},"tokens":[{"token_id":"4764842916…","outcome":"Yes","price":0,"winner":false},…]}]}`.

**Order book** — `GET /book?token_id=<token_id>`.

**LIVE** (BTC 5m up/down, token `83248222891022777466670229454169298190565662037552937851421619912481208498705`):

```bash
curl -s "https://clob.polymarket.com/book?token_id=83248222891022777466670229454169298190565662037552937851421619912481208498705"
```

```json
{"market":"0x1b45ab9e241e496e9a8fa7816857fed551430dbd30ef6b19a84e388abc9a2e39",
 "asset_id":"83248222891022777466670229454169298190565662037552937851421619912481208498705",
 "timestamp":"1795192839750","hash":"384b1b881f44410811c828922b2746d5559851fe",
 "bids":[{"price":"0.01","size":"102882.34"},{"price":"0.02","size":"17584.93"}, …],
 "min_order_size":"5","tick_size":"0.01","neg_risk":false,"last_trade_price":""}
```

**Best price** — `GET /price?token_id=<token_id>&side=BUY|SELL`.

**LIVE**: `curl -s "https://clob.polymarket.com/price?token_id=8324822…&side=BUY"` → `{"price":"0.5"}`.

**Midpoint** — `GET /midpoint?token_id=<token_id>` (average of best bid and best ask).

**LIVE**: `curl -s "https://clob.polymarket.com/midpoint?token_id=8324822…"` → `{"mid":"0.505"}`.

**Tick size** — `GET /tick-size?token_id=<token_id>` (also `GET /tick-size/{token_id}`).

**LIVE**: `curl -s "https://clob.polymarket.com/tick-size?token_id=8324822…"` → `{"minimum_tick_size":0.01}`.

**Fee rate** — `GET /fee-rate?token_id=<token_id>` (also `GET /fee-rate/{token_id}`). Returns `base_fee` **in basis points** per the OpenAPI schema (`example: 30`).

**LIVE**: `curl -s "https://clob.polymarket.com/fee-rate?token_id=8324822…"` → `{"base_fee":1000}`.

**All-in-one market params** — `GET /clob-markets/{condition_id}` (tokens, tick size, base fees, rewards, RFQ status, fee details). Observed output in §1.1.

**Reward markets** — §2.4.

**Server time** — `GET /time`. **LIVE** → `1795192819` (= 2026-11-20T16:40:19Z).

**Auth requirements, summary:** everything above is public. Anything touching your account — `/data/orders`, `/data/trades`, `/rewards/user/*`, `/order-scoring`, `/v1/user/rate-limit-tier` — needs CLOB L2 auth: headers `POLY_ADDRESS`, `POLY_API_KEY`, `POLY_PASSPHRASE`, `POLY_SIGNATURE`, `POLY_TIMESTAMP`, where the signature is `HMAC-SHA256(base64decode(secret), timestamp + METHOD + path + body)` base64url-encoded. Source: https://docs.polymarket.com/getting-started/api.md

**LIVE** — L2-protected endpoint rejects unauthenticated calls: `curl -s "https://clob.polymarket.com/v1/user/rate-limit-tier"` → HTTP 401 `{"error":"Unauthorized/Invalid api key"}`.

---

## 4. Trading endpoints, limits, heartbeat

### 4.1 Endpoints

| Operation | Route | Notes |
|---|---|---|
| Place one order | `POST /order` | EIP-712 typed data, signed with the wallet |
| Place a batch | `POST /orders` | **Max 15 orders per request**, processed in parallel; each order evaluated independently |
| Cancel one | `DELETE /order` | |
| Cancel multiple | `DELETE /orders` | **Max 1000 order IDs per request**; duplicate IDs auto-ignored |
| Cancel all | `DELETE /cancel-all` | |
| Cancel by market | `DELETE /cancel-market-orders` | |
| Get open orders | `GET /data/orders` | From 2026-12-14, `asset_id`-only requests return HTTP 400 |
| Order scoring status | `GET /order-scoring` | "Checks if a specific order is currently scoring for rewards" |
| Heartbeat (modern) | `POST /v1/heartbeats` | body `{"heartbeat_id": "..."}` |
| Heartbeat (legacy) | `POST /heartbeats` | |
| Rate-limit tier | `GET /v1/user/rate-limit-tier` | |

Sources: https://docs.polymarket.com/trading/place-orders.md, https://docs.polymarket.com/trading/manage-orders.md, and the per-endpoint API reference pages under https://docs.polymarket.com/api-reference/trade/.

### 4.2 Post-only

`postOnly: true` on the order (SDK: `postOnly: true` / `post_only=True`). A post-only order that would match immediately is **rejected, not executed**. Error: HTTP 400 `invalid post-only order: order crosses book` (https://docs.polymarket.com/resources/error-codes.md).

**LIVE** — post-only mode is a real operational state, not hypothetical. From the error-codes page: `post-only mode: only post-only orders and cancels are allowed`, with `code: "post_only_mode"` and `retry_after_seconds`, and the same retry delay in the `Retry-After` header. It occurs for **two minutes after a matching-engine restart**, when cancels still work but only maker-eligible post-only orders are accepted. Source: https://docs.polymarket.com/trading/matching-engine.md and https://docs.polymarket.com/resources/error-codes.md.

### 4.3 Order size and price tick rules

- **Minimum order size: 5 shares.** Live `mos: 5` / `min_order_size: "5"` on the up/down market. Doc: "the size must meet its minimum order size"; error `order {id} is invalid. Size ({size}) lower than the minimum: {min}`.
- **Tick size** must be respected; error `Price ({price}) breaks minimum tick size rule: {tick}`. The doc's precision table (https://docs.polymarket.com/trading/place-orders.md):

| Tick size | Price decimals | Size decimals | Amount decimals |
|---|---|---|---|
| 0.1 | 1 | 2 | 3 |
| 0.01 | 2 | 2 | 4 |
| 0.005 | 3 | 2 | 5 |
| 0.0025 | 4 | 2 | 6 |
| 0.001 | 3 | 2 | 5 |
| 0.0001 | 4 | 2 | 6 |

- Listen for the `tick_size_change` event on the market stream; the CLOB rejects a price that does not conform to the *current* tick size.
- `makerAmount` / `takerAmount` encoding: for a BUY, `makerAmount` = price × size USD, `takerAmount` = shares; for a SELL the reverse. Both are converted to six-decimal integers.
- Order types: GTC, GTD (expires one minute before the stated expiration; expiration must be at least 3 minutes ahead, so the minimum effective lifetime is ~2 minutes), FOK, FAK.
- GTD orders **expire one minute early** as a security threshold. Set `expiration = now + 60 + N` for an effective lifetime of N seconds.

### 4.4 Rate limits — two independent layers

**(a) Per-signer token buckets on order/cancel requests.** Source: https://docs.polymarket.com/api-reference/trading-rate-limits.md. Buckets are scoped to the **signer address**; order and cancel buckets are independent.

| Bucket | Request | Token cost |
|---|---|---|
| Order | `POST /order` | 1 |
| Order | `POST /orders` | number of orders in the batch |
| Cancel | `DELETE /order` | 1 |
| Cancel | `DELETE /orders` | number of submitted IDs |
| Cancel | `DELETE /cancel-all` | 1 + number of orders canceled |
| Cancel | `DELETE /cancel-market-orders` | 1 + number of matching orders canceled |

Volume tiers (30-day window, refreshed every three hours, eligibility follows the **maker wallet's** cumulative volume even when it differs from the signer):

| Tier | 30-day volume | Order rate (tok/s) | Order burst | Cancel rate (tok/s) | Cancel burst | Negative cancel balance |
|---|---|---|---|---|---|---|
| Standard | — | 40 | 60 | 80 | 120 | Yes |
| Copper | $30,000+ | 60 | 90 | 120 | 180 | Yes |
| Bronze | $50,000+ | 80 | 120 | 160 | 240 | Yes |
| Silver | $100,000+ | 200 | 300 | 400 | 600 | Yes |
| Gold | $500,000+ | 400 | 600 | 800 | 1,200 | Yes |
| Platinum | $2.5M+ | 450 | 675 | 900 | 1,350 | No |
| Diamond | $5M+ | 525 | 787 | 1,050 | 1,575 | No |
| Elite | $10M+ | 600 | 900 | 1,200 | 1,800 | No |

A small account sits at **Standard: 40 orders/s, 60 burst, 80 cancels/s, 120 cancel burst**. Batches are **all-or-nothing** on admission: a batch is admitted only if the bucket holds enough tokens for every entry, else the whole request is rejected. A batch whose cost exceeds the burst capacity can never be admitted — split it. `DELETE /cancel-all` debits 1 token up front, then 1 more per order actually canceled, which on Standard/Copper/Bronze/Silver/Gold can drive the balance negative and block further cancels until it refills. Warning mode began 2026-07-24 with live enforcement to be announced; responses carry `Poly-RateLimit-Remaining`, `Poly-RateLimit-Reset`, `Poly-RateLimit-Tier`, and `Poly-RateLimit-Warning`.

Note there is **no documented per-minute order cap**; the limits are token-bucket per-second rates with burst capacity. A burst of 60 orders is instantly available at Standard tier.

**(b) Cloudflare IP-based limits** (https://docs.polymarket.com/api-reference/rate-limits.md): general 15,000 req/10s on the CLOB; health check `/ok` 100 req/10s. Gamma: general 4,000/10s, `/events` 500/10s, `/markets` 300/10s, listing 900/10s. Data API v2: see page. These throttle (delay/queue) rather than reject.

### 4.5 Heartbeat / dead-man switch

This is the documented mechanism, and it is stricter than most people expect.

Source: https://docs.polymarket.com/trading/manage-orders.md#order-heartbeats and https://docs.polymarket.com/api-reference/trade/send-heartbeat.md.

- `POST /v1/heartbeats` with body `{"heartbeat_id": ""}` on the first call, then the **rotating ID returned by each successful response** on subsequent calls. Send **every 5 seconds**.
- The **first accepted heartbeat enables timeout cancellation for all open orders owned by that API key**, across markets and processes.
- After **10 seconds** without an accepted heartbeat, the server detects expiry on a **five-second scan** and queues a **best-effort cancel-all** attempt. Ten seconds is the expiry threshold, **not** a guaranteed cancellation time; queue delays, service failures, or uncancellable orders can delay or prevent it.
- **There is no disarm endpoint.** Stopping the loop or closing the client leaves the deadline active. A single test call with production credentials can put existing orders at risk.
- WebSocket keepalive does **not** refresh the deadline.
- A mismatched ID returns HTTP 400 `{"error_msg":"Invalid Heartbeat ID","heartbeat_id":"<expected>"}`; sign a new request with the expected ID and retry. A rejected send does not refresh the deadline.
- The legacy `POST /heartbeats` route shares the same registration and resets the expected modern ID to empty.
- Use **one coordinated sender per API key**; concurrent sends race over the rotating ID. Every accepted heartbeat covers all open orders for that key.
- Before shutdown: stop placing orders, cancel what you want removed, and **verify the cancellations** before stopping the heartbeat loop.

### 4.6 Taker delay on crypto/finance up-down markets

**LIVE**: `clob-markets` for the BTC 5m up/down market returned `"itode": true`. Doc (https://docs.polymarket.com/concepts/order-lifecycle.md): a marketable order is **held for 250 ms**, then validation runs again and it is matched or rested. The API waits for the hold and returns the final result. During the delay the order is pending and **cannot be canceled**. Check `itode` on `GET /clob-markets/{condition_id}` for a specific market.

---

## 5. Official clients

### 5.1 `py-clob-client` — archived, do not start new work here

- PyPI: `py-clob-client`, **latest 0.34.6** (uploaded 2026-02-19). Source: https://pypi.org/pypi/py-clob-client/json → `{"info":{"version":"0.34.6","requires_python":">=3.9.10"}}`. GitHub releases show v0.34.6 as the newest (2026-02-19).
- **The repository README says, verbatim: "This repository has been archived and is no longer maintained. The client is no longer functional and should not be used for new or existing integrations. Please migrate to our new unified SDK."** Source: https://raw.githubusercontent.com/Polymarket/py-clob-client/main/README.md (first lines).
- Its documented auth model: `ClobClient(HOST, key=PRIVATE_KEY, chain_id=137, signature_type=…, funder=FUNDER)`, then `client.set_api_creds(client.create_or_derive_api_creds())`. `signature_type`: **0** = EOA (MetaMask/hardware/direct key), **1** = email/Magic delegated signing, **2** = browser-wallet proxy. `funder` = the address that actually holds the funds (differs from the signer for proxy wallets).
- Public surface (from README): `get_ok()`, `get_server_time()`, `get_midpoint(token_id)`, `get_price(token_id, side=)`, `get_order_book(token_id)`, `get_order_books([BookParams])`, `get_last_trade_price(token_id)`, `create_order(OrderArgs)`, `post_order(signed, OrderType)`, `cancel(order_id)`, `cancel_all()`.

**Direct answer to the task's question about `py-clob-client`: it exists, its current version is 0.34.6, but upstream has archived it and declared it non-functional. Build on the unified SDK instead.**

### 5.2 The unified SDKs — what to use

**Python: `polymarket-client`** (PyPI), docs at https://docs.polymarket.com/getting-started/python.md, source https://github.com/Polymarket/py-sdk/.

- PyPI: `polymarket-client`, **latest 0.20.0**, `requires_python >= 3.11`, summary "Official Python client for Polymarket". Source: https://pypi.org/pypi/polymarket-client/json.
- Import surface: `from polymarket import AsyncPublicClient, PublicClient, AsyncSecureClient, SecureClient, Event, Market, OrderBook, PriceHistoryPoint, PolymarketError, RateLimitError, UserInputError`, plus domain types `ConditionId, EvmAddress, MarketId, PositionId, TokenId`, and `from polymarket.streams import MarketSpec, SportsSpec, UserSpec, CryptoTwapPriceSpec`.
- Client construction: `AsyncPublicClient()` (no credentials); `await AsyncSecureClient.create(private_key=…)` / `SecureClient.create(private_key=…)` for trading. Wallet + gasless setup continues in https://docs.polymarket.com/trading/wallets-auth.md.
- Realtime subscriptions are **async-only** (`subscribe()` on `AsyncPublicClient`/`AsyncSecureClient`).
- Precision: decimals are `Decimal`, timestamps are `datetime`.
- Relevant operations: `list_reward_markets(query=, order_by="rate_per_day", sort_direction="DESC", page_size=100)` → async paginator of `RewardMarket` with `rewards_min_size`, `rewards_max_spread`, `rewards_config[].rate_per_day`; `place_limit_order(asset_id, side, price, size, post_only=True, expiration=…)`; `send_order_heartbeat(heartbeat_id=…)` raising `OrderHeartbeatMismatchError`; `split_position(condition_id, amount)`, `merge_positions(...)`; `get_total_earnings_for_user_for_day(date=, sponsored=)`; `fetch_current_rebates` → `get_current_rebates(date=, maker_address=)`.

**TypeScript: `@polymarket/client`** — npm dist-tag `latest` = **0.20.0** (published 2026-11-20, per the npm registry `time.modified`). Also `beta` 0.3.0-beta.1, `next` 1.0.0-next.1. Source: https://registry.npmjs.org/@polymarket/client. Deps: `ky`, `ox`, `zod`, `it-merge`, `it-pushable`, `@msgpack/msgpack`, `@polymarket/types`, `@polymarket/bindings`. Docs: https://docs.polymarket.com/getting-started/typescript.md. A unified Rust SDK is in development.

Migration guide (from the old `@polymarket/clob-client-v2` / `@polymarket/builder-relayer-client` / `@polymarket/builder-signing-sdk` packages): https://docs.polymarket.com/migrate/clob-sdk-to-unified-sdk.md. It shows the old-style relayer call (`relayer.execute([tx], "Split position")`) and the new `client.splitPosition({conditionId, amount})`.

### 5.3 Auth model (unified SDK)

- **Wallet types** (https://docs.polymarket.com/trading/wallets-auth.md): **Deposit Wallet** (default for accounts created on/after 2026-05-04), **Proxy Wallet** (legacy, Magic Link/Google login), **Safe Wallet** (legacy, external signer), **EOA**.
- **Order signing `signature_type`** (place-orders doc): Deposit Wallet = **3**, Proxy Wallet = **1**, Safe Wallet = **2**, EOA = **0**. `maker_address` and `order_signer_address` differ for Proxy/Safe (maker = wallet, signer = account signer) and are identical for Deposit Wallet and EOA.
- **EIP-712 domain**: name `Polymarket CTF Exchange`, chainId 137. `version` **3** and `verifyingContract` `0xe3333700cA9d93003F00f0F71f8515005F6c00Aa` for V2 books (`version: "v2"`); **version 2** with verifyingContract `0xE111180000d2663C0091e4f400237545B87B996B` for CTF non-neg-risk, and `0xe2222d279d744050d28e00520010520000310F59` for CTF neg-risk.
- **CLOB L1/L2**: L1 is an EIP-712 `ClobAuth` signature (domain `ClobAuthDomain` v1, chainId 137) that creates or derives credentials via `POST /auth/api-key` or `GET /auth/derive-api-key`; L2 is HMAC-SHA256 over `timestamp + METHOD + path + body` using the base64-decoded secret.
- **Gasless**: a Relayer API key (created under polymarket.com → Settings → API Keys → Relayer API Keys) or a Builder API key authorizes gasless wallet operations. The Relayer only permits transactions that interact with the Polymarket Protocol and supported third-party contracts. Relayer base URL `https://relayer-v2.polymarket.com`, `POST /submit`, `GET /transaction?id=…`, `GET /nonce`, `GET /relayer`, `GET /deploy`, `GET /user/nonce`.

---

## 6. Binary options: 5-minute and 15-minute crypto up/down markets

### 6.1 How they are created and settled

**LIVE** — Gamma market object for the current window:

```bash
curl -s "https://gamma-api.polymarket.com/markets/slug/btc-updown-5m-1795278600"
```

```json
{"slug":"btc-updown-5m-1795278600","question":"Bitcoin Up or Down - November 21, 11:30AM-11:35AM ET",
 "outcomes":["Up","Down"],"conditionId":"0x1b45ab9e241e496e9a8fa7816857fed551430dbd30ef6b19a84e388abc9a2e39",
 "clobTokenIds":["83248222891022777466670229454169298190565662037552937851421619912481208498705",
                 "9272349125277418704236442036475617997013955873009002947496397721126575498056"],
 "cryptoMarketConfig":{"id":"btc-5m-twap-60","asset":"btc","duration":"5m","twapEnabled":true,"twapLookbackSeconds":60},
 "cryptoMarketConfigId":"btc-5m-twap-60",
 "resolutionSource":"https://data.chain.link/streams/btc-usd-twap-60s-streams",
 "resolutionMechanism":"oracle","eventStartTime":"2026-11-21T16:30:00Z","endDate":"2026-11-21T16:35:00Z",
 "startDate":"2026-11-20T16:38:08.92686Z","version":"v1","negRisk":false,
 "description":"This market will resolve to \"Up\" if the time-weighted average price (TWAP) of Bitcoin, generated by Chainlink, of the time range specified in the title is greater than or equal to the price at the beginning of that range. Otherwise, it will resolve to \"Down\". …"}
```

Mechanics (https://docs.polymarket.com/concepts/resolution.md, "Chainlink TWAP–Resolved Up-Down Markets"):

- Each market specifies an **asset pair, a start time, and a duration**.
- **The TWAP at the start sets the "price to beat."** When the duration ends, **the TWAP at that time sets the "final price."** Both come from the same **Chainlink TWAP stream**.
- **Resolves Up when final price ≥ price to beat; Down when lower.** Equal resolves Up. No UMA proposal/dispute process.
- The reference price source is the **Chainlink Data Streams** TWAP feed for the pair, e.g. `https://data.chain.link/streams/btc-usd-twap-60s-streams` (this exact URL is in the live market's `resolutionSource`).
- **Lookback window:** 5-minute crypto markets now resolve with a **60-second** Chainlink TWAP (changed from 30s at 00:00 UTC, per the changelog), and 15-minute / 4-hour markets use 60s. Live `cryptoMarketConfig` confirms `twapLookbackSeconds: 60` for the 5m market, id `btc-5m-twap-60`.
- Series exist per asset and duration. **LIVE**: `curl -s "https://gamma-api.polymarket.com/series?slug=btc-up-or-down-5m"` → `{"id":"10684","ticker":"btc-up-or-down-5m","recurrence":"5m","active":true,"volume24hr":12937443.23,"liquidity":3779701.33,"events":[…]}`. The event slug embeds the window start as a Unix timestamp: `btc-updown-5m-1795278600` — and `1795278600` = 2026-11-21T16:30:00Z, matching `eventStartTime`. Slug pattern is `{asset}-updown-{5m|15m}-{windowStartEpoch}`.
- Assets observed active in the 5m/15m families: BTC, ETH, SOL, XRP, DOGE, BNB, HYPE, ZEC.

### 6.2 Is the strike / open price published in market metadata?

**No.** The live market object contains **no** open-price, strike, "price to beat", or reference-price field. The full key set includes only `orderPriceMinTickSize`, `makerBaseFee`, `takerBaseFee`, `lastTradePrice`, `oneDay/oneHour/oneWeek/oneMonth/oneYearPriceChange` — none of which is the strike. The `cryptoMarketConfig` carries only `id`, `asset`, `duration`, `twapEnabled`, `twapLookbackSeconds`. The event object likewise has no open price.

**Where a bot can obtain it:**

1. **PolyBolt WebSocket, `prices.crypto.twap` topic.** Source: https://docs.polymarket.com/api-reference/wss/polybolt.md and https://docs.polymarket.com/market-data/chainlink-twap.md. Subscribe with `{topic:"prices.crypto.twap", symbol:"btcusd", provider:"chainlink"}`; the payload has `window_seconds: 60` and `timestamp`, and the value is already scaled (use it directly, no E18 scaling). **It requires your own Chainlink API key** (request form: https://institutional.polymarket.com/request-chainlink-api-key) and an authenticated `SecureClient` (CLOB L2 credentials on the socket open).
2. **The Chainlink stream directly**, at the `resolutionSource` URL on the market.

Because the TWAP window is 60 seconds and the market window is 5 or 15 minutes, the "price to beat" is the TWAP value at the window start, and the final is the TWAP at window end. A maker reconstructing them from the live stream should note the **60-second lookback means the value at the start instant already embeds 60 seconds of pre-window history** — so the bot's reconstruction of the exact on-chain reference is subject to Chainlink's own stream semantics, not just its own polling.

**UNVERIFIED:** whether Polymarket publishes the price-to-beat in any authenticated/private endpoint, or only via the on-chain resolution. The public docs and the market object say nothing about it. What would verify it: the ChainlinkReporterModule / on-chain resolution payload, or the Polymarket support team.

### 6.3 Live economics of these markets

**LIVE** (same market): `orderMinSize` 5, `orderPriceMinTickSize` 0.01, `rewardsMinSize` 50, `rewardsMaxSpread` 4.5, `itode: true` (250 ms taker delay), `fd.r = 0.07` (pre-change crypto coefficient), `v: "v1"` (CTF-era protocol).

---

## 7. CTF mechanics, collateral, gas

### 7.1 Addresses (Polygon mainnet, chainId 137)

Source: https://docs.polymarket.com/resources/contracts.md

| Contract | Address |
|---|---|
| Conditional Tokens (CTF) | `0x4D97DCd97eC945f40cF65F87097ACe5EA0476045` |
| CTF Exchange | `0xE111180000d2663C0091e4f400237545B87B996B` |
| Neg Risk CTF Exchange | `0xe2222d279d744050d28e00520010520000310F59` |
| Neg Risk Adapter (CTF neg-risk approvals) | `0xd91E80cF2E7be2e162c6513ceD06f1dD0dA35296` |
| PositionManager (Poly v2) | `0x006F54F7f9A22e0000CC2AB60031000000ae9fEF` |
| Router (Poly v2) | `0x12121212006e4CD160D18e3f00711DA5c3372600` |
| ExchangeV3 (Poly v2) | `0xe3333700cA9d93003F00f0F71f8515005F6c00Aa` |
| BinaryModule / NegRiskModule / CombinatorialModule (Poly v2) | `0x1000008dD9001B968442c1000017eaE6E0dA00Ba` / `0x200000900045e3B6259600682756002200028933` / `0x30000034706C7d8e12009DAB006Be20000c031A8` |
| CtfCollateralAdapter | `0xAdA100Db00Ca00073811820692005400218FcE1f` |
| NegRiskCtfCollateralAdapter | `0xadA2005600Dec949baf300f4C6120000bDB6eAab` |
| pUSD CollateralToken | `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` (impl `0xCe84E053301A82937F90ee2C2c1889cAb1db25dE`) |
| CollateralOnramp / CollateralOfframp | `0x93070a847efEf7F70739046A929D47a521F5B8ee` / `0x2957922Eb93258b93368531d39fAcCA3B4dC5854` |
| Deposit Wallet Factory / Beacon | `0x00000000000Fb5C9ADea0298D729A0CB3823Cc07` / `0x7A18EDfe055488A3128f01F563e5B479D92ffc3a` |
| Gnosis Safe Factory / Polymarket Proxy Factory | `0xaacfeea03eb1561c4e67d661e40682bd20e3541b` / `0xaB45c5A4B0c941a2F231C04C3f49182e1A254052` |
| AutoRedeemer | `0xa1200000d0002264C9a1698e001292D00E1b00af` |
| UMA Adapter / UmaCtfAdapter v3.1.0 | `0x6A9D222616C90FcA5754cd1333cFD9b7fb6a4F74` / `0x157Ce2d672854c848c9b79C49a8Cc6cc89176a49` |
| ChainlinkReporterModule (Poly v2) | `0xc12EC12E0000326890Ca5560dEf5EB5C22b16814` |

### 7.2 Collateral: pUSD, not USDC / USDC.e

The current deployment settles in **pUSD**, a 6-decimal ERC-20 wrapper over USDC backed on-chain (https://docs.polymarket.com/concepts/pusd.md). It is the collateral for all trading.

**LIVE** — token identity via `eth_call` on Polygon (`symbol()` / `name()` / `decimals()`):

| Address | symbol | name | decimals |
|---|---|---|---|
| `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB` (pUSD) | `pUSD` | `Polymarket USD` | 6 |
| `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174` (USDC.e) | `USDC` | `USD Coin (PoS)` | 6 |
| `0x3c499c542cef5e3811e1192ce70d8cc03d5c3359` (native USDC) | `USDC` | `USD Coin` | 6 |

USDC.e is **not** the trading collateral. It is the **deposit/withdrawal asset**: the `CollateralOnramp` wraps USDC.e → pUSD (`wrap(address _asset, address _to, uint256 _amount)`, `_asset` must be USDC.e; the caller must approve the **Onramp**, not the pUSD token), and `CollateralOfframp` unwraps pUSD → USDC.e. The docs also state you can deposit either native USDC or USDC.e and either is wrapped into pUSD. USDC.e lives at `0x2791Bca1f2de4661ED88A30C99A7a9449Aa84174`; native USDC at `0x3c499c542cef5e3811e1192ce70d8cc03d5c3359`.

**LIVE** — balances of the key contracts (pUSD / USDC.e / native USDC):

| Contract | pUSD | USDC.e | native USDC |
|---|---|---|---|
| Conditional Tokens `0x4D97…6045` | 14,831.10 | 183,571,677.90 | 17,553.19 |
| CTF Exchange `0xE111…996B` | 0.00 | 1,524.50 | 1,972.40 |
| CtfCollateralAdapter `0xAdA1…E1f` | 92.15 | 0.00 | 137.08 |

The CTF contract holds a large USDC.e balance, which is the historical CTF-collateral era; the **current** adapter path routes pUSD. The CtfCollateralAdapter holds pUSD and native USDC.

### 7.3 Which contract Polymarket's markets currently use

Two position systems coexist, and the docs give you a selector:

- A market whose `version` is **`"v2"`** uses **Polymarket Protocol V2** (PositionManager + Router + ExchangeV3).
- A **CTF** market (no `version` in the book response) uses the Conditional Tokens contract with the CTF Exchange; `neg_risk` selects which exchange.

**LIVE**: the current BTC 5m up/down market reports `"v": "v1"` in `clob-markets` and its `/book` response **omits `version`** and reports `"neg_risk": false`. Per the signing-domain table, that market signs against **CTF Exchange `0xE111180000d2663C0091e4f400237545B87B996B`, domain version `2`**. The split/merge target for such a market is the **CtfCollateralAdapter `0xAdA100Db00Ca00073811820692005400218FcE1f`** (CTF standard) or `0xadA2005600Dec949baf300f4C6120000bDB6eAab` (CTF negative-risk). The Polymarket V2 target is the **Router `0x12121212006e4CD160D18e3f00711DA5c3372600`**.

Source: https://docs.polymarket.com/trading/positions/manage.md (the target-selection table) and https://docs.polymarket.com/migrate/polymarket-v2/contract-integrations.md.

### 7.4 Are `mergePositions` / `splitPosition` callable by an EOA?

**Yes — confirmed on-chain.** The canonical Gnosis ConditionalTokens contract has no access control on `splitPosition` / `mergePositions`; both are `external` with only `require` checks on partition length and condition preparation (source: https://github.com/Polymarket/conditional-tokens-contracts/blob/master/contracts/ConditionalTokens.sol — `function splitPosition(IERC20 collateralToken, bytes32 parentCollectionId, bytes32 conditionId, uint[] calldata partition, uint amount) external` and the analogous `mergePositions`). Anyone holding the collateral and the outcome tokens can call them.

**LIVE** — scanned recent Polygon blocks for transactions to the CTF contract with these selectors and read the receipts:

- `0x72ce4275` = `splitPosition(address,bytes32,bytes32,uint256[],uint256)` (selector confirmed against 4byte.directory)
- `0x9e7212ad` = `mergePositions(address,bytes32,bytes32,uint256[],uint256)` (selector confirmed against 4byte.directory)

Observed gas (Polygon mainnet, `eth_getTransactionReceipt`):

| Selector | Op | gasUsed | gasPrice | POL cost | status |
|---|---|---|---|---|---|
| `0x72ce4275` | splitPosition | 294,731 | 276,965,185,504 | 0.08163 | 0x1 |
| `0x9e7212ad` | mergePositions | 337,420 | 284,942,906,016 | 0.09615 | 0x1 |
| `0x72ce4275` | splitPosition | 335,288 | 279,550,252,180 | 0.09373 | 0x1 |

Roughly **0.08–0.10 POL per split or merge** at the observed gas price (~277–285 gwei). `eth_gasPrice` at observation: `0x4132a075f8` = **279,999,000,000 wei ≈ 280 gwei**.

**LIVE** — caller types: `0x5c5454940c679b99513a67bf08af752b2011f1d2` has `eth_getCode` = `0x` (a plain EOA) and it successfully submitted `splitPosition`; `0x79439dabe03a26f630c4c2ab1293b5fd457129b4` has 48 bytes of code (a contract, i.e. a Deposit Wallet) and submitted `mergePositions`. So both plain EOAs and smart wallets do it directly.

**Call encoding for CTF (docs + ABI):**

```solidity
function splitPosition(address collateralToken, bytes32 parentCollectionId, bytes32 conditionId, uint256[] partition, uint256 amount);
function mergePositions(address collateralToken, bytes32 parentCollectionId, bytes32 conditionId, uint256[] partition, uint256 amount);
```

| Argument | Polymarket V2 | CTF |
|---|---|---|
| `conditionId` | 31-byte V2 condition ID | original 32-byte CTF condition ID |
| `collateralToken` | — | **pUSD `0xC011a7E12a19f7B1f670d46F03B03f3342E82DFB`** |
| `parentCollectionId` | — | 32 zero bytes |
| `partition` | — | `[1, 2]` |
| `amount` | 6-decimal base units | 6-decimal base units |

**Approvals needed:** approve pUSD to the position target (adapter or Router) for `amount` (existing allowance suffices), and for CTF neg-risk markets also approve pUSD and outcome tokens to the **Neg Risk Adapter `0xd91E80cF…`** — a different contract from `NegRiskCtfCollateralAdapter`; approving the latter does **not** grant the former.

**Split/merge economics (docs):** 1 pUSD → 1 YES + 1 NO; merging 1 YES + 1 NO → 1 pUSD; winning tokens redeem for $1.00 each after resolution.

### 7.5 Relayer / gasless path

**Yes.** https://docs.polymarket.com/api-reference/relayer/submit-a-transaction.md and https://docs.polymarket.com/trading/wallets-auth.md#execute-gasless-transactions. Relayer base URL `https://relayer-v2.polymarket.com`, `POST /submit` with `RELAYER_API_KEY` and `RELAYER_API_KEY_ADDRESS` headers, body type `WALLET` with `depositWalletParams.calls[]` (`target`, `value`, `data`). The Relayer only allows gasless transactions that interact with the Polymarket Protocol and supported third-party contracts. Poll `GET /transaction?id=…` until `STATE_CONFIRMED`.

**Important nuance:** the Relayer path uses a **Deposit Wallet** — you cannot relay from a plain EOA through it. A plain EOA can instead call the contracts directly and pay POL itself (confirmed above). The unified SDK's `splitPosition`/`mergePositions`/`setupTradingApprovals()` handle this routing; `setup_trading_approvals()` is documented as a **gasless** transaction for Deposit/Safe/Proxy wallets.

---

## 8. Market selection data (live, right now)

### 8.1 Crypto 5-minute and 15-minute up/down markets

**LIVE** — from `GET https://gamma-api.polymarket.com/markets?closed=false&limit=30&order=startDate&ascending=false` (all `active: true`, same window 2026-11-21T16:30Z→16:35Z / 16:45Z). All sixteen observed markets share the same settings:

| Market slug | Window (ET) | rewards_min_size | rewards_max_spread | rate_per_day | tick | min order size | taker delay |
|---|---|---|---|---|---|---|---|
| `btc-updown-5m-1795278600` | 11:30–11:35 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `btc-updown-15m-1795278600` | 11:30–11:45 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `eth-updown-5m-1795278600` | 11:30–11:35 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `eth-updown-15m-1795278600` | 11:30–11:45 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `sol-updown-5m-1795278600` | 11:30–11:35 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `sol-updown-15m-1795278600` | 11:30–11:45 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `xrp-updown-5m-1795278600` | 11:30–11:35 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `xrp-updown-15m-1795278600` | 11:30–11:45 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `doge-updown-5m-1795278600` | 11:30–11:35 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `doge-updown-15m-1795278600` | 11:30–11:45 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `bnb-updown-5m-1795278600` | 11:30–11:35 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `bnb-updown-15m-1795278600` | 11:30–11:45 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `hype-updown-5m-1795278600` | 11:30–11:35 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `hype-updown-15m-1795278600` | 11:30–11:45 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `zec-updown-5m-1795278600` | 11:30–11:35 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |
| `zec-updown-15m-1795278600` | 11:30–11:45 AM | 50 | 4.5 | **none** | 0.01 | 5 | yes (250 ms) |

**The `rate_per_day` cell is the critical one.** I checked each of these sixteen condition IDs against the reward endpoints:

```bash
curl -s "https://clob.polymarket.com/rewards/markets/0x1b45ab9e241e496e9a8fa7816857fed551430dbd30ef6b19a84e388abc9a2e39"
curl -s "https://clob.polymarket.com/rewards/markets/0x6ca8f1a3be6b9a323f757fb9c92be4421a2f53f275c0c2bb8c626b2e96536022"
```

→ `{"data":[],"next_cursor":"LTE=","limit":100,"count":0}` for both.

And the full `/rewards/markets/current` scan (7,812 markets) contained **zero** up/down condition IDs. And `GET /rewards/markets/multi?event_id=1432457` (the BTC 5m event) returns the market with `"rewards_config": []`.

**Conclusion: the crypto 5m/15m up/down markets carry reward *settings* (min size 50 shares, max spread 4.5 cents) but have NO active reward allocation at observation time. A maker quoting them earns no liquidity rewards.**

The docs corroborate the mechanism: the "Crypto TWAP Rewards" program ($1M across 5-minute, 15-minute, and 4-hour TWAP markets) carried an explicit note — "**This program has ended. The August allocation is no longer active.**" (https://docs.polymarket.com/programs/liquidity-rewards.md).

**UNVERIFIED:** whether a new crypto up/down reward allocation will be activated later (the market settings being populated is consistent with a program that can be switched on per market). What would verify it: watch `/rewards/markets/current` for these condition IDs, or the Polymarket announcements channels.

### 8.2 Highest rate-per-day markets overall

**LIVE** — `GET /rewards/markets/multi?order_by=rate_per_day&position=DESC&page_size=100`, sorted descending:

| rate_per_day | Market | min size | max spread | asset |
|---|---|---|---|---|
| 1000 | Will IShowSpeed finish GTA VI by November 20, 11:59 AM ET? | 20 | 6.5 | USDC.e |
| 1000 | Will Anthropic close below its IPO price by November 20, 2026? | 20 | 6.5 | USDC.e |
| 750 | Will the Fed increase interest rates by 25 bps after the December 2026 meeting? | 200 | 3.5 | USDC.e |
| 555 | Will Gadi Eizenkot be the next Prime Minister of Israel? | 200 | 5.5 | USDC.e |
| 400 | Will Kai Cenat finish his GTA VI marathon by November 25? | 20 | 6.5 | USDC.e |
| 390 | Will Benjamin Netanyahu be the next Prime Minister of Israel? | 200 | 5.5 | USDC.e |
| 375 | Will dcampion be the first of these Kick streamers to finish GTA VI by December 31, 2026? | 50 | 4.5 | USDC.e |
| 330 | Will Puma Shen win the next Taipei Mayor election? | 100 | 6.5 | USDC.e |
| 330 | Howard Lutnick out as Secretary of Commerce by December 31? | 100 | 6.5 | USDC.e |
| 320 | Will Chiang Wan-an win the next Taipei Mayor election? | 100 | 6.5 | USDC.e |
| 311 | Will Marine Le Pen win the 2026 French presidential election? | 100 | 6.5 | USDC.e |
| 300 | Will xQc finish GTA VI by November 22? | 50 | 6.5 | USDC.e |
| 300 | Will xQc finish GTA VI by November 22, 5:59 PM ET? | 20 | 6.5 | USDC.e |
| 300 | Will the Fed increase interest rates by 50+ bps after the December 2026 meeting? | 200 | 2.5 | USDC.e |
| 300 | Will Kai Cenat finish his GTA VI marathon by November 24? | 50 | 6.5 | USDC.e |
| 275 | US x Iran Effective Ceasefire by November 22? | 50 | 3.5 | USDC.e |
| 275 | Israel x Iran ceasefire continues through November 22? | 50 | 3.5 | USDC.e |
| 250 | Will there be no new be CEO of NVIDIA by December 31, 2028? | 200 | 4.5 | USDC.e |
| 200 | Will xQc finish GTA VI by November 23? | 50 | 6.5 | USDC.e |
| 200 | Will Kai Cenat finish his GTA VI marathon by November 28? | 50 | 6.5 | USDC.e |

Note the shape of this list: the top rates are **short-dated, high-uncertainty entertainment/sports/news markets with wide max spreads (6.5 cents)** and **small min sizes (20 shares)**. They are cheap to qualify in, but they are also the markets where a small maker is most likely to be adversely selected, and where the post-2026-11-20 change removes the maker rebate entirely (see §10).

Also note the `asset_address` inconsistency flagged in §2.4: this endpoint reported USDC.e for these rows, while `/rewards/markets/current` reported pUSD. The doc example for `/rewards/markets/multi` shows pUSD. Treat the payout asset as **UNVERIFIED** and read it from `/rewards/user/total` for your own account.

---

## 9. Constraints and traps for a maker

### 9.1 Post-only rejection rules

- A post-only order that would cross is **rejected with 400** (`invalid post-only order: order crosses book`), not filled as a taker. Error reference: https://docs.polymarket.com/resources/error-codes.md.
- Post-only is a *guarantee of maker status*, not a guarantee of a fill.
- **Matching-engine restarts put the whole venue into post-only mode for two minutes.** Non-post-only orders are rejected with `code: "post_only_mode"` and a `retry_after_seconds`; cancels still work. Source: https://docs.polymarket.com/trading/matching-engine.md. A maker that retries non-post-only will burn its whole order budget on rejections during that window.
- Order types FOK/FAK/market orders are taker instruments and are not usable as maker quotes.

### 9.2 Minimum order size

- **5 shares** per order on the up/down markets and on the sampled CTF-era market (live `mos: 5`, `min_order_size: "5"`).
- **UNVERIFIED:** the market-details doc describes `orderMinSize` as "Minimum order size in **USDC**" while the place-orders doc describes `min_order_size` as "the minimum number of **shares**". The live CLOB field and the error message ("Size ({size}) lower than the minimum") are share-denominated. What would verify it: the exact unit in the CLOB reference for one market with a non-5 minimum.
- A 5-share order at 0.50 = $2.50 notional. Liquidity-reward `rewards_min_size` (50 shares on the up/down markets, 20–200 elsewhere) is a **separate, larger** threshold — an order can be valid but score zero rewards.

### 9.3 Adverse selection on Up/Down markets

**The underlying is fully public, and the resolution inputs are deterministic.** The maker is quoting against a Chainlink TWAP whose value anyone can read, and the resolution is a mechanical comparison (final ≥ price-to-beat ⇒ Up). Consequences:

- The market's mid tracks the true probability that `final_TWAP ≥ price_to_beat` given the current TWAP, the remaining time, and the TWAP's own 60-second lookback. A maker quoting "symmetric around the mid" is quoting around an estimate that a well-informed trader can compute more precisely than the maker can, because the maker's own view of the underlying lags the Chainlink stream.
- The 250 ms taker delay (`itode: true`) buys a maker a 250 ms window on marketable orders; it does **not** protect a resting quote.
- **The price-to-beat is NOT in the market metadata** (§6.2), so a maker must reconstruct it from the TWAP stream to price correctly. That reconstruction (60-second lookback, exact Chainlink stream semantics) is itself an error source, and a maker with a slightly wrong strike prices the market wrong on both sides.
- The 5-minute window is brutal: 250 ms of taker delay on a 300-second life means the maker must cancel and requote within a quarter-second of any relevant move, on a market that re-opens every 5 minutes with a brand-new condition ID, new token IDs, and a fresh order book. `GTD` orders are unusable here: GTD expires one minute early and requires ≥3 minutes ahead, i.e. ≥2 minutes effective — longer than a 5-minute market's useful half-life.
- There is **no documented minimum resting time** protecting a maker from a stale quote, and no documented self-trade prevention for the **prediction** CLOB. Self-trade prevention is documented only under **Perps** (https://docs.polymarket.com/perps/learn-about-trading/self-trade-prevention.md), where it is on by default in CancelMaker mode. **UNVERIFIED** whether an equivalent STP exists for the predictions CLOB. The nearest prediction-side statement is that Polymarket reserves the right to remove rebates and tier status for activity that breaks the ToS, "including but not limited to wash trading, self-matching, or other inauthentic trading" (https://docs.polymarket.com/programs/taker-rebates.md).

### 9.4 Anti-wash and anti-manipulation rules a maker must respect

Documented, quote-able constraints:

- **ToS-based, no numeric limits published.** The programs pages reserve Polymarket's discretion to "adjust or remove rebates and tier status for activity that breaks our Terms of Service, including but not limited to **wash trading, self-matching, or other inauthentic trading**." The perps competition page states the same more bluntly: "**Manipulation of any kind disqualifies all associated accounts. This covers wash trading, self-trading, and multi-accounting.**"
- **No rebate on fee-free markets.** "Maker rebates are funded by taker fees, so fills on markets with a 0% taker fee (including markets temporarily made fee-free during a fee holiday) earn **no maker rebate**." Geopolitics is 0% and stays 0% after the change.
- **Combos earn no maker rebates** (explicit in the change page; the current fee table lists Combos maker rebate 0%).
- **Liquidity Rewards score manipulation.** The methodology explicitly says the program is designed to "discourage blatantly exploitative behaviors", and it rewards *balanced* quoting: single-sided liquidity scores at `Q/c` with `c = 3.0`, and outside the 0.10–0.90 midpoint band single-sided liquidity scores **zero**. Post-only + one-sided quoting is a way to lose rewards, not to farm them.
- **Minimum order age** exists on some markets (`moas: 30` observed live on the up/down market). Flashing orders in and out to game the sampler is exactly what this defeats.
- **Matching-engine restart post-only mode** means your quotes must be post-only to survive a restart window.

**UNVERIFIED:** no official page publishes numeric wash-trading thresholds, self-trade matching rules, or per-account market-making limits for the predictions CLOB. What would verify it: the Polymarket Terms of Service itself and https://polymarket.com/ (neither is part of docs.polymarket.com).

### 9.5 Operational traps

- **Heartbeat is a loaded gun.** One test call with production credentials arms cancel-all-on-deadline for every order on that API key, with no disarm. If your quoting loop and your heartbeat loop are separate processes, a heartbeat crash cancels your entire book.
- **Rate limit tier is by maker-wallet volume, not signer.** A maker wallet with volume gets a higher order rate even if orders come from a different signer. Tiers refresh every three hours.
- **Cancel-all can drive the cancel bucket negative** on Standard/Copper/Bronze/Silver/Gold tiers, blocking further cancels until refill. If your kill switch is cancel-all and the bucket is negative, your kill switch is stuck.
- **Batch admission is all-or-nothing.** A 15-order batch costs 15 tokens; if the bucket holds 14, the whole batch is rejected and none of the 15 is placed.
- **The 250 ms taker delay makes the order uncancellable during the hold.** On crypto up/down, a marketable order is pending and cannot be canceled for a quarter second.
- **Tick size can change.** Persist `tick_size` and update on the `tick_size_change` market-stream event; a stale tick size gets orders rejected.
- **GTD rounds down by a minute** and needs ≥3 minutes lead.

---

## 10. What a maker does NOT earn

Direct answers, each tied to a source.

1. **A maker does not earn a rebate on every fill.** Rebates are a function of (a) the tier your 30-day maker weighted volume puts you in, and (b) the taker fee your specific fill generated. Fills on fee-free markets generate no taker fee and therefore no rebate. Fills on Combos generate no rebate. Geopolitics and fee-holiday markets generate none.
2. **After 2026-11-20 23:59 UTC, a maker below $200,000 of 30-day maker weighted volume earns 0% of the taker fees its fills generate.** The old per-market pool (crypto 20%, sports 15%, finance/politics/economics/culture/weather/tech/mentions/other 25%) and its $1 payout floor are replaced by the tier table. This is the single largest change to a small maker's economics, and it is the reason a maker's strategy must stand on spread capture plus liquidity rewards rather than on rebates.
3. **A maker does not earn taker rebates.** Only taker fills earn taker weighted volume. Maker fills count only toward the maker tier.
4. **A maker does not earn anything for resting orders.** Resting liquidity has zero value until it is filled. A quote that never trades earns zero rebate and zero liquidity reward.
5. **A maker does not earn liquidity rewards for orders below `rewards_min_size`** (50 shares on the up/down markets; 20–200 elsewhere) **or outside `rewards_max_spread`** (2.5–6.5 cents observed), or for orders that have not yet satisfied the minimum order age where one applies.
6. **A maker does not earn liquidity rewards on the crypto 5m/15m up/down markets right now** — those markets have reward *settings* but no active rate allocation (live: `rewards_config: []`, absent from the 7,812-market `/rewards/markets/current` scan).
7. **A maker earns no liquidity rewards at all if it quotes only one side outside the 0.10–0.90 midpoint band** (`Q_min = min(Q_one, Q_two)` when the midpoint is <0.10 or >0.90 — double-sided is mandatory there), and single-sided quoting inside that band is penalized by `c = 3.0`.
8. **Below the payout floor, accrued rewards are not paid.** $1 minimum for liquidity rewards and, pre-change, $1 for maker rebates.
9. **A maker pays no platform fee.** The maker fee rate is 0 in every category, including Combos. That is a benefit, not an earning, but it means the maker's P&L is entirely spread capture minus adverse selection and inventory risk, plus whatever incentives the market config actually funds.
10. **A maker cannot count on the maker-rebate pool existing at all in the new regime.** The pools are gone; only the tier percentage applies, and the bottom tier is zero.

---

## Sources

Every URL used, with what it supports.

**Docs index and program pages**
- https://docs.polymarket.com/llms.txt — doc index used to discover all pages
- https://docs.polymarket.com/programs/fee-and-rebate-changes-november-2026.md — the 2026-11-20 23:59 UTC change: taker coefficient table, taker rebate tiers, maker rebate tiers, $200k thresholds, maker weighted volume formula, "combos and fee-free trades earn no maker rebates", liquidity rewards unchanged
- https://docs.polymarket.com/trading/fees.md — current fee formula, category table, maker fee = 0, fee precision
- https://docs.polymarket.com/programs/maker-rebates.md — current maker rebate pool model, per-category pool %, fee-curve weighting, $1 payout floor, fee-free exclusion, `/rebates/current` endpoint and SDK equivalents
- https://docs.polymarket.com/programs/taker-rebates.md — current taker wV formula, category weights, tier table, anti-wash / ToS rebate-removal clause
- https://docs.polymarket.com/programs/liquidity-rewards.md — full scoring methodology and equations 1–7, min order age rules, `rewards_min_size`/`rewards_max_spread` units, $1 minimum payout, Crypto TWAP rewards program (ended), reward-market listing endpoints
- https://docs.polymarket.com/programs/builders/overview.md, /fees.md, /tiers.md — referenced, not used for any claim
- https://docs.polymarket.com/programs/referral-program.md — referenced, not used

**Core concepts**
- https://docs.polymarket.com/concepts/resolution.md — UMA vs Chainlink TWAP resolution, price to beat, final price, Up ≥ price to beat rule
- https://docs.polymarket.com/concepts/order-lifecycle.md — post-only semantics, 250 ms taker delay and `itode`, order validity checks
- https://docs.polymarket.com/concepts/pusd.md — pUSD identity, decimals, onramp/offramp USDC.e wrapping, contract addresses
- https://docs.polymarket.com/concepts/markets-events.md, /concepts/prices-orderbook.md — referenced for identifiers and book semantics

**Market data**
- https://docs.polymarket.com/market-data/market-details.md — market object schema, `orderMinSize`, `orderPriceMinTickSize`, `rewardsMinSize` (shares), `rewardsMaxSpread`, `rewards.clobRewards`
- https://docs.polymarket.com/market-data/discover-markets.md — discovery and filtering
- https://docs.polymarket.com/market-data/chainlink-twap.md — Chainlink TWAP access, 60-second window, PolyBolt subscription, Chainlink API key requirement
- https://docs.polymarket.com/market-data/realtime-data.md — market stream and `tick_size_change` event
- https://docs.polymarket.com/api-reference/live-data/overview.md — PolyBolt supported symbols and providers
- https://docs.polymarket.com/api-reference/wss/polybolt.md — `prices.crypto.twap` payload shape, `window_seconds`, scaling

**Trading**
- https://docs.polymarket.com/trading/overview.md, /trading/quickstart.md — referenced for flow
- https://docs.polymarket.com/trading/place-orders.md — order types, GTD expiry rules, tick/size precision table, amount encoding, post-only, signing domains and `signature_type` table, batch, market orders
- https://docs.polymarket.com/trading/manage-orders.md — cancel results, order heartbeats (5s send, 10s expiry, no disarm), heartbeat FAQ
- https://docs.polymarket.com/trading/market-making.md — maker workflow, inventory management, kill switch, best practices
- https://docs.polymarket.com/trading/matching-engine.md — restart announcement channels, two-minute post-only mode, retry strategy
- https://docs.polymarket.com/trading/wallets-auth.md — wallet types, Deposit Wallet, Relayer/Builder API keys, gasless transactions, `setupTradingApprovals()`, approval flow
- https://docs.polymarket.com/trading/positions/manage.md — split/merge/redeem, target contract selection table, CTF ABI arguments, pUSD collateral, relayer batch submission, approvals
- https://docs.polymarket.com/trading/positions/how-positions-work.md — referenced for position identifiers
- https://docs.polymarket.com/getting-started/api.md — L1/L2 auth, header set, HMAC signing recipe, public vs authenticated endpoints, service base URLs

**API reference**
- https://docs.polymarket.com/api-reference/rate-limits.md — Cloudflare IP limits per service
- https://docs.polymarket.com/api-reference/trading-rate-limits.md — per-signer token buckets, tier table, batch admission rule, headers
- https://docs.polymarket.com/api-reference/account/get-rate-limit-tier.md — tier lookup route
- https://docs.polymarket.com/api-reference/trade/post-a-new-order.md — `POST /order`
- https://docs.polymarket.com/api-reference/trade/post-multiple-orders.md — `POST /orders`, max 15
- https://docs.polymarket.com/api-reference/trade/cancel-single-order.md — `DELETE /order`
- https://docs.polymarket.com/api-reference/trade/cancel-multiple-orders.md — `DELETE /orders`, max 1000
- https://docs.polymarket.com/api-reference/trade/cancel-all-orders.md — `DELETE /cancel-all`
- https://docs.polymarket.com/api-reference/trade/send-heartbeat.md — legacy `POST /heartbeats`, 10s expiry, five-second scan, no disarm
- https://docs.polymarket.com/api-reference/trade/get-order-scoring-status.md — `GET /order-scoring`
- https://docs.polymarket.com/api-reference/trade/get-user-orders.md — `GET /data/orders`, 2026-12-14 asset_id change
- https://docs.polymarket.com/api-reference/market-data/get-order-book.md — `GET /book`
- https://docs.polymarket.com/api-reference/market-data/get-market-price.md — `GET /price`
- https://docs.polymarket.com/api-reference/data/get-midpoint-price.md — `GET /midpoint`
- https://docs.polymarket.com/api-reference/market-data/get-tick-size.md — `GET /tick-size`
- https://docs.polymarket.com/api-reference/market-data/get-fee-rate.md — `GET /fee-rate`, `base_fee` in bps
- https://docs.polymarket.com/api-reference/markets/get-clob-market-info.md — `GET /clob-markets/{condition_id}`, field decoding
- https://docs.polymarket.com/api-reference/rewards/get-multiple-markets-with-rewards.md — `GET /rewards/markets/multi`, all query params
- https://docs.polymarket.com/api-reference/rewards/get-current-active-rewards-configurations.md — `GET /rewards/markets/current`
- https://docs.polymarket.com/api-reference/rewards/get-raw-rewards-for-a-specific-market.md — `GET /rewards/markets/{condition_id}`
- https://docs.polymarket.com/api-reference/rewards/get-reward-percentages-for-user.md — `GET /rewards/user/percentages`
- https://docs.polymarket.com/api-reference/rebates/get-current-rebated-fees-for-a-maker.md — `GET /rebates/current`
- https://docs.polymarket.com/api-reference/relayer/submit-a-transaction.md — `POST /submit`
- https://docs.polymarket.com/resources/error-codes.md — post-only crossing, tick/size errors, post_only_mode, insufficient balance/allowance, FOK/FAK errors
- https://docs.polymarket.com/resources/contracts.md — all contract addresses
- https://docs.polymarket.com/api-spec/clob-openapi.yaml — OpenAPI schema used to decode `clob-markets` fields and `base_fee` units

**SDKs and migration**
- https://docs.polymarket.com/getting-started/sdks-apis.md — SDK comparison
- https://docs.polymarket.com/getting-started/python.md — `polymarket-client` usage, client classes, `list_reward_markets`, `place_limit_order`, `send_order_heartbeat`, types
- https://docs.polymarket.com/getting-started/typescript.md — `@polymarket/client` usage
- https://docs.polymarket.com/migrate/clob-sdk-to-unified-sdk.md — migration path, old relayer calls vs new SDK methods
- https://docs.polymarket.com/changelog/sdks.md — SDK changelog
- https://docs.polymarket.com/changelog/predictions.md — 5-minute markets moved to 60-second Chainlink TWAP; 15-minute TWAP lookbacks

**Registry / source (non-doc, authoritative for versions and source code)**
- https://pypi.org/pypi/py-clob-client/json — `py-clob-client` 0.34.6, upload date 2026-02-19
- https://raw.githubusercontent.com/Polymarket/py-clob-client/main/README.md — archive notice, `signature_type` and `funder` semantics, public method list
- https://pypi.org/pypi/polymarket-client/json — `polymarket-client` 0.20.0, requires_python >= 3.11
- https://registry.npmjs.org/@polymarket/client — `@polymarket/client` latest 0.20.0, published 2026-11-20
- https://github.com/Polymarket/py-sdk/ — unified Python SDK repository
- https://github.com/Polymarket/conditional-tokens-contracts/blob/master/contracts/ConditionalTokens.sol — canonical CTF source: `splitPosition` / `mergePositions` are `external` with no access control
- https://raw.githubusercontent.com/Polymarket/polymarket-v2-external/main/src/collateral/CollateralToken.sol and .../abstract/CollateralErrors.sol — pUSD token implementation and custom errors
- https://www.4byte.directory/api/v1/signatures/ — selector confirmation for `splitPosition(address,bytes32,bytes32,uint256[],uint256)` = `0x72ce4275`, `mergePositions(address,bytes32,bytes32,uint256[],uint256)` = `0x9e7212ad`

**Live APIs queried (all read-only)**
- `https://clob.polymarket.com/time` → `1795192819`
- `https://clob.polymarket.com/book?token_id=…`, `/price?token_id=…&side=BUY`, `/midpoint?token_id=…`, `/tick-size?token_id=…`, `/fee-rate?token_id=…`, `/clob-markets/{condition_id}`, `/markets`, `/sampling-markets`, `/simplified-markets`
- `https://clob.polymarket.com/rewards/markets/multi` (with `order_by=rate_per_day&position=DESC&page_size=100`, `event_id=1432457`, `tag_slug=crypto`, `q=…`)
- `https://clob.polymarket.com/rewards/markets/current` (full 16-page scan, 7,812 markets)
- `https://clob.polymarket.com/rewards/markets/{condition_id}` (three up/down conditions)
- `https://clob.polymarket.com/rebates/current?date=…&maker_address=…` → `null`
- `https://clob.polymarket.com/v1/user/rate-limit-tier` → 401
- `https://gamma-api.polymarket.com/markets/slug/btc-updown-5m-1795278600`, `.../events/slug/btc-updown-5m-1795278600`, `.../markets?closed=false&limit=…&order=startDate&ascending=false`, `.../markets?closed=false&limit=…&order=volume24hr&ascending=false`, `.../events?closed=false&limit=…&tag_slug=crypto`, `.../series?slug=btc-up-or-down-5m`
- Polygon RPC (`https://polygon.drpc.org`, `https://1rpc.io/matic`) — `eth_call` on pUSD / USDC.e / native USDC / CTF, `eth_getCode`, `eth_getBalance` of contract balances, `eth_blockNumber`, `eth_getBlockByNumber`, `eth_getTransactionReceipt`, `eth_getLogs`, `eth_gasPrice`, `eth_estimateGas`
