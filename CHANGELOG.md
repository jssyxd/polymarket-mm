# CHANGELOG

本文件记录**实盘过程中真实踩到的坑**：症状、根因、修复，以及下次判断的依据。只写已经验证过的事实。

---

## [0.5.0] — 2026-11-24 · 结算回款闭环

### 新增

- `pmm.execution.redeem` + `tools/redeem.py` + `pmm-redeem.timer`（每 30 分钟）：对已结算、标记价 ≥0.5、数量 ≥5 的赢家走 relayer 赎回；输家不处理（赔付为 0，白花一笔交易）。
- 赎回写入 journal（`kind="redeem"`，按 1.00/股结算），`compute_pnl` 与 merge 同样处理。

#### 14. 结算不会自动回款

- **症状**：9 月结算的 18 个仓位，两个月后仍躺在账户里。
- **根因**：交易所只在调用 `redeemPositions` 时支付，没有自动赎回。
- **修复**：定时赎回，并把赔付记入账本，否则"已实现盈亏"永远是 0、库存永远虚高。
- **教训**：资金链条上每一跳都要有对应的定时任务：成交 → 合并 → 赎回。少任何一环，钱就停在半路。

## [0.4.0] — 2026-11-23 · 资金提前回收

### 新增

- `pmm.execution.rescue` + `tools/rescue.py` + `pmm-rescue.timer`（每 5 分钟）：单腿价 ≥0.97 且距结算 ≥1 天时，在对手方最低价挂 post-only 买单，补齐套数后交给 merge。
- 实盘成交写 journal：`pmm.execution.trades`，每轮从交易所 trade 列表取**属于自己 maker 订单**的那一条，按 `fill_id` 幂等。

### 坑

#### 10. 交易所对 BUY 有 $1 最小名义额，1¢ 买单常常下不出去

- **症状**：57 股 × 1¢ = $0.573，下单被拒：`invalid amount for a marketable BUY order ($0.5732), min size: $1`。
- **根因**：最小限制不是只有 5 股，还有 **$1 名义额**。
- **修复**：最便宜的可接受价是 `max(tick, 1/size)`；20 股 → 5¢，200 股 → 0.5¢。
- **教训**：小仓位的"补齐套数"根本不经济。$1 的固定成本对 20 股是 5%，对 200 股是 0.5%。奖励市场现在普遍要 200 股，恰好落在划算的一侧。

#### 11. 补腿价高于对手方公允价值时，合并是亏的

- **症状**：伦敦 Yes 已 0.9955，补 NO 最低要 1.75¢，而 NO 标记只有 0.45¢。
- **根因**：合并给 1.00 是确定的，但花 1.75¢ 买 0.45¢ 的东西，等于用 1.3¢ 买"提前结算"。
- **修复**：要求 `补腿价 ≤ 1 - 持仓价`，即只在**套利**成立时补腿；否则等结算。
- **教训**：`merge` 的 1.00 不是免费的。只有当买入成本低于市场对那条腿的定价时才赚。

#### 12. tick 不是全局 0.01

- 同一批市场里有 `tick_size = 0.001`，价格必须按**该 token 自己的** tick 取整，否则最低价算错（0.005 会被当成不合法的 0.01）。

#### 13. 接近 1 的市场没有可挂的被动卖价

- **症状**：伦敦/米兰赢家标记 0.9995，`POLY_HARVEST=1` 却两笔都不下单。
- **根因**：买一已是 **0.999**，tick 0.001，网格上限 `1 - tick = 0.999`。卖单挂在买一之下就是穿越（post-only 拒单），挂在之上需要 ≥1.000（非法）。
- **修复**：价格取 `max(0.99, best_bid + tick)`，超过网格上限时**明确 skip** 并给出原因，而不是发一张注定被拒的单。
- **另一条路更差**：吃买一（taker）在温度盘是 10% 费率，57 股卖 0.999 实际到手约 51.5，低于等结算的 57.33。
- **教训**：`0.99 卖出` 这个方案只在"买一低于 0.99 且还有空间"时成立。市场走到 0.999 时，唯一划算的出口就是等结算。

### Plan B 基础设施（已启用，按条件触发）

- `_resting` 键加 `side`，同腿买卖不再互相覆盖。
- `QuoteIntent.kind`，报价默认 `quote`；`_payloads` 仅对 `kind="harvest"` 放行 SELL，并要求 post-only、价格 ≥0.99、size > 0。
- `pmm.execution.harvest.plan_harvests`：按 持有量 / 标记价 / 成本 / 已挂单 生成卖单计划。
- 生产者 `run_harvest` + `tools/harvest.py` + `pmm-harvest.timer`（每 10 分钟）已接线；`POLY_HARVEST` 默认 0，2026-11-24 已在实盘置 1。
- 触发条件：单腿 ≥0.99 且**买一 + tick ≤ 网格上限**；否则 skip 并说明原因。

---

## [0.3.0] — 2026-11-23 · 实盘上线

### 新增

- 资金守卫：`Runner._place` 每轮读交易所真实可用抵押品，买不起的腿丢弃并记 `order_skipped / insufficient_collateral`。
- 交易所持仓口径：`Runner._inventory` 实盘走 Data API v2 `/v2/positions`，journal 仅作兜底。
- 合并：`pmm.execution.merge` + `tools/merge_pairs.py` + `pmm-merge.timer`（每 3 分钟）。
- 归档：`docs/conversation.html`（脱敏对话实录）、`docs/agents/`（子智能体简报）。

### 坑

#### 1. 「必须迁移到 Deposit Wallet 才能下单」是错的

- **症状**：下单被拒，`400 maker address not allowed, please use the deposit wallet flow`；照字面理解去做了钱包迁移方案，账户的 Deposit Wallet 却从未部署。
- **根因**：maker/signer 配对不成立。v2 订单信封要求 `maker` 是资金钱包、`signer` 是 API key 所属地址，两者必须匹配 `signature_type`。
- **修复**：`signature_type=1` + `maker=代理钱包` + `signer=账户签名者`，一次通过。
- **教训**：交易所以「建议迁移」措辞报错时，先假设是自己的字段配对问题，而不是协议迁移问题。错的方向浪费了两天。

#### 2. 下单被拒的四连击，每一次报错都指向了错误的方向

| 客户端 | 版本 | sigtype | 报错 |
|---|---|---|---|
| py-clob-client 0.34.6 | v1 | 1 | `maker is required` |
| py-clob-client 0.34.6 | v1（手写 payload） | 1 | `maker is required` |
| py-clob-client-v2 | 1 | 0/1/2 | `invalid order version, please use the latest clob-client` |
| py-clob-client-v2 | 2 | 0/1/2 | `maker address not allowed, please use the deposit wallet flow` |
| py-clob-client-v2 | 2 | 3 | `the order signer address has to be the address of the API KEY` |

最后一条其实已经说出了答案：`signer` 必须等于 API key 的地址。把它和 `signature_type=1` 合起来用即可。
**教训**：错误信息里出现「the X has to be the address of Y」时，第一反应应该是「我的 X 现在是什么」，而不是「Y 需要另一个钱包」。

#### 3. 单腿成交吃掉了 85% 的预算

- **症状**：账户从 23.37 pUSD 掉到 3.77，盘口空了，循环却仍以为自己是空仓。
- **根因**：配对挂单只有一侧成交时，持仓变成方向性裸仓；而 `Runner._inventory` 从 **journal 的 fill 记录**推库存，实盘路径从不写 fill（只有纸面模式写）。风控箱因此永远看到 0 持仓。
- **修复**：实盘库存改读交易所 `/v2/positions`（按 token id 索引）。新增测试 `test_live_inventory_is_read_from_the_venue_not_the_journal`。
- **教训**：任何「账本」都必须来自权威来源。用本地推导的账本做风控，风控会在最需要它的时候失明。

#### 4. 合并回款这一步压根不存在

- **症状**：配对成交后仓位只增不减，现金被吸干，最后连 20 股的配对都挂不起。
- **根因**：策略的资本模型假设「完整套数 merge 回 1 pUSD 完成回款」，但代码里没有 merge 调用。
- **修复**：`balanced_pairs()` 找出双腿齐全且 ≥5 股的市场，`merge_positions(amount="max")` 走 relayer + owner 签名；systemd 定时器每 3 分钟执行；单市场失败不影响其他市场。
- **教训**：资本模型里写下的每一步，都必须在代码里存在。写在文档里的「自我回款」不会自己发生。

#### 5. 赎回 18 个历史仓位，回收 0

- **症状**：18 个 `redeemable: true` 的仓位，按「回收资金」处理。
- **根因**：这些全是 9 月温度盘结算后的**输方**代币（`current_price = 0`），redeem 的赔付就是 0。
- **修复**：relayer 走通赎回（仓位 20 → 19 已验证），但收益为 0，只是清空持仓视图。
- **教训**：`redeemable` 只表示「可以赎回」，不表示「有东西可拿」。判断前先看 `current_price`。

#### 6. Data API v1 已下线，我读到的「没有持仓」是假的

- **症状**：`GET /positions` 返回空，据此判断账户无持仓。
- **根因**：v1 返回 `410 Data API v1 has been retired`，代码把非 200 当成空列表。
- **修复**：改用 `/v2/positions`、`/v2/value`。
- **教训**：把「请求失败」与「结果为空」混为一谈，会产生完全错误的结论。失败必须与空值区分。

#### 7. VPS 上的代码是旧快照

- **症状**：只覆盖两个文件后服务启动即 `ImportError: cannot import name 'QuoteIntent'`，VPS 上还叫 `RunnerOptions`。
- **根因**：`/opt/pmm` 落后于本地仓库，只同步单个文件会造成「新旧混装」。
- **修复**：整包同步 `src/ tools/ pyproject.toml`，旧源码留备份。
- **教训**：部署要先确认版本基线，增量拷贝只适用于确认过基线的目录。

#### 8. 10% 的 taker 费让「卖出换现金」变成坏主意

- **症状**：想卖掉单腿持仓换回现金。
- **根因**：温度盘 `fee_rate_bps = 1000`（10%），买一档深度只有 5 股。
- **结论**：卖出约回收 15.4 / 成本 19.6，直接亏 4.2；而市场当天结算、按面值赔付且免手续费，因此选择持有到期再 redeem。
- **教训**：先查 `fee_rate_bps` 再决定退出方式。maker 与 taker 的成本差一个数量级。

#### 9. SSH 与主机密钥

- 工作站 Clash TUN 会劫持到 VPS 的 22 端口（fake-IP），表现为 `Connection closed by ... port 22`。绕过：`ip rule add priority 8999 to 155.254.60.38/32 lookup main`。
- 主机密钥变更过一次，先核对 `hostname` 与 `uptime` 确认是同一台机器，再考虑忽略密钥指纹。

---

## [0.2.0] — 2026-11-22 · 只读可运行

- 报价循环、闸门栈、快照、选品、自调参、监控落地；纸面模式可连续运行。
- 交易所在「奖励带宽内」的报价得分为 0 的边界被固定为不变量：半价差被夹到 `max_spread`。
- 结论：`min_size` 通常是 20 股，5 股在 99.4% 的奖励市场里不合格。

## [0.1.0] — 2026-11-21 · 骨架

- 四个模块并行开发：数据层、定价、执行适配器、风控/监控；由 `herdr` 面板分派给不同子智能体。
- 首版测试 163 → 逐轮增补至今 204。
