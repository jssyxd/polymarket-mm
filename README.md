# polymarket-mm

Polymarket 二元期权市场的**做市（maker）服务**：双边挂买单赚取流动性奖励与价差，成交后把完整套数合并回 pUSD 继续报价。

实盘运行在 VPS 上（`pmm-mm.service` + `pmm-merge.timer`），一个进程负责报价、下单、撤单和心跳。

---

## 它做什么

Polymarket 的奖励规则是：在奖励市场里，**挂单价落在中点附近的一个带宽内、且单笔至少 `min_size` 股**，按「离中点越近、规模越大」加权分配每天的资金池。

本服务据此只做一件事：**在中点两侧各挂一张买单（不做卖单）**。

- 两张买单的价格之和恒小于 1，因此一旦都成交就持有一个完整套数（Yes + No）。
- 完整套数在链上 `merge` 回 1 pUSD。所以这套策略的回款不是靠卖出，而是靠**合并**。
- 不做卖单的原因是卖单需要先持有对应代币；买单结构让启动资金只需要一份，而不是两份。

```
            中点 mid
   ────────────┼────────────
   BUY up @ mid-s      BUY down @ mid-s   (s ≤ 奖励带宽)
        成交一侧 → 持有单腿
        另一侧成交 → 完整套数 → merge → 1 pUSD
```

---

## 目录结构

```
src/pmm/
  data/         CLOB / Gamma / 数据 API 的读取（书籍、行情、奖励市场、余额）
  pricing/      概率空间的报价构造（Avellaneda–Stoikov 变体）
  core/         市场快照、配对库存、配额选择、风控闸门
  engine/       报价循环（cycle）、服务循环（runner）、自调参（self_tune）
  execution/    CLOB 适配器：下单、撤单、批量、心跳、日志、持仓读取、合并
  risk/         闸门栈（库存箱、硬止损、心跳）
  monitor/      监控与指标
tools/          CLI：run_mm.py（服务）、scan_pools.py（选品）、merge_pairs.py（合并）等
tests/          204 个测试
deploy/         部署脚本
docs/
  plan.md       整体方案（含阶段划分）
  decisions/    架构决策记录，按时间追加
  agents/       每个子智能体的任务简报（编排记录）
  conversation.html  完整开发对话实录（已脱敏）
```

---

## 快速开始

```bash
python3 -m venv .venv && .venv/bin/pip install -e .
python -m pytest -q                     # 204 passed

# 选品：算出资金能覆盖哪些奖励市场
PYTHONPATH=src .venv/bin/python tools/scan_pools.py --capital 23 --size 20

# 单轮预演（不发送任何订单）
PYTHONPATH=src .venv/bin/python tools/run_mm.py --dry-run --once

# 连续运行（纸面模式：只看不挂）
PYTHONPATH=src .venv/bin/python tools/run_mm.py --paper --interval 20

# 实盘
PYTHONPATH=src .venv/bin/python tools/run_mm.py --interval 20 --capital 23 --size 20
```

---

## 配置

所有凭据只从环境变量读取，代码里没有任何硬编码，`ExecutionConfig.__repr__` 与日志会遮蔽密钥。

| 变量 | 必填 | 说明 |
|---|---|---|
| `POLY_OWNER_PK` | 实盘订单 | 账户签名者 EOA 的私钥，订单由它签名 |
| `POLY_API_KEY` / `POLY_API_SECRET` / `POLY_API_PASSPHRASE` | 实盘 | CLOB L2 凭据（由 `POLY_OWNER_PK` 通过 L1 签名确定性派生） |
| `POLY_FUNDER` | 实盘 | 资金所在钱包地址（代理钱包或 Deposit Wallet） |
| `POLY_SIGNATURE_TYPE` | 建议 | `0` EOA / `1` POLY_PROXY / `2` GNOSIS_SAFE / `3` POLY_1271 |
| `POLY_RELAYER_API_KEY` / `POLY_RELAYER_ADDRESS` | 合并/赎回 | Relayer 凭据，用于 gasless 的 merge / redeem |
| `POLY_DRY_RUN` | — | `1` 只记录意图不下单（无 owner key 时默认 1） |
| `POLY_POST_ONLY` | — | 默认 1。穿越盘口的单会付 taker 费并破坏配对不变量 |
| `POLY_ENV_FILE` | — | 指向一个 `KEY=VALUE` 文件，真实环境变量优先 |

`POLY_ENV_FILE=/etc/pmm-mm/pmm.env` 是 VPS 上的部署形态。

---

## 账户类型与签名

账户是**遗留的 POLY_PROXY 钱包**（历史上通过邮箱/Google 登录创建）。实盘验证过的组合：

- `maker` = 代理钱包地址，`signer` = 账户签名者 EOA，`signature_type = 1`
- 订单走 **v2 订单信封**（`POST /orders`），交易所接受
- **不需要** Deposit Wallet、不需要 session key、不需要 Builder key

早期文档里「必须迁移到 Deposit Wallet 才能下单」的结论是错的，原因是 maker/signer 配对错误。
细节见 `docs/decisions/0011`。

---

## 资金门槛

一次配对报价在交易所同时冻结两张单的本金，因此成本约为 `size × (p_up + p_down)`，而 `p_up + p_down ≤ 0.99`。

| 每边份额 | 每个市场需要 | 奖励资格 |
|---|---|---|
| 5 股 | ~5 pUSD | 1500 个奖励市场里只有 9 个允许 `min_size ≤ 5` |
| **20 股** | **~20 pUSD** | 1088/1500，实践中可用的下限 |

结论：**每个市场按 20 pUSD 预算**。默认 `max_markets = 4`，即约 80 pUSD。

---

## 部署（VPS）

```bash
# 依赖
python3 -m venv /opt/pmm/.venv && /opt/pmm/.venv/bin/pip install -e /opt/pmm
python3 -m venv /opt/pmm/.venv-merge && /opt/pmm/.venv-merge/bin/pip install polymarket-client

# 配置
install -d /etc/pmm-mm && install -m 600 deploy/pmm.env.example /etc/pmm-mm/pmm.env

systemctl enable --now pmm-mm.service pmm-merge.timer
```

两个单元：

- `pmm-mm.service`：报价循环。**心跳必须在同一进程**——交易所的心跳一旦中断就会撤掉该 API key 的全部挂单，独立的心跳进程一挂就会带走整个盘口。
- `pmm-merge.timer`：每 3 分钟扫描一次持仓，把双腿齐全的市场合并回 pUSD。合并放在独立 venv（`.venv-merge`）里跑，避免升级依赖影响正在交易的进程。
- `pmm-rescue.timer`：每 5 分钟尝试用 1¢ 补腿把赢家凑成整套。
- `pmm-harvest.timer`：每 10 分钟在存在合法被动卖价时以 0.99 卖出赢家（`POLY_HARVEST=1` 才生效）。
- `pmm-redeem.timer`：每 30 分钟赎回已结算的赢家。<br>**这一步不能省**：交易所不会自动把已结算仓位转成 pUSD（9 月那 18 个仓位一直躺着就是证据）。

---

## 资金回收：两条腿，三个出口

单腿持仓会把资金锁到结算。系统按这个顺序回收：

| 顺序 | 触发 | 动作 | 回收 |
|---|---|---|---|
| 0 | 市场已结算、赢家腿 | `pmm-redeem.timer` 每 30 分钟 `redeem` | **1.00 / 股**（结算价） |
| 1 | 两条腿都持有 | `pmm-merge.timer` 每 3 分钟 `merge` | **1.00 / 套**（与结果无关） |
| 2 | 单腿，价格 ≥0.97，且距结算 ≥1 天 | `pmm-rescue.timer` 每 5 分钟在对手方最低价挂 post-only 买单 | 补齐套数 → 走 1 |
| 3 | 补不齐（未实现） | 99¢ 卖单（见下） | 0.99 / 股 |

第 2 步为什么是**买**：卖赢家只有 0.99，卖输家只有 0.01，而输家恰恰是凑成整套的那一枚。合并给出确定的 1.00。

第 2 步还要过两道现实闸门：

- **交易所对 BUY 有 $1 最小名义额**。20 股按 1¢ 只有 $0.20，会被拒；最低可接受价是 `max(tick, 1/size)`，所以小仓位补腿不经济。
- **补腿价必须 ≤ 对手方自身标记价**（`1 - 持仓价`）。花 1.75¢ 买一个标记 0.45¢ 的腿，不如等结算；只有当补腿价低于其市场价时，合并才是套利。

### Plan B（99¢ 卖单兜底）— 基础设施已就位，**未启用**

当补腿不经济或长期不成交时，挂 post-only 卖单直接回款（回 0.99/股，折价 1%）。

已完成的改造（都有测试，但**没有任何代码路径会产生 harvest 意图**）：

| 项 | 状态 |
|---|---|
| `_resting` 键改为 `(condition_id, leg, side)` | ✅ 同一腿上的买单与卖单不再互相覆盖 |
| `QuoteIntent.kind`（`quote` / `harvest`） | ✅ 默认 `quote`，报价路径不可能意外发出卖单 |
| `Runner._payloads` 的 SELL 不变量 | ✅ 仅 `kind="harvest"` 允许 SELL；必须 post-only；价格 ≥0.99；size > 0 |
| `pmm.execution.harvest.plan_harvests` | ✅ 纯函数，按 持有量 / 标记价 / 成本 / 已挂单 生成计划 |

已启用（`POLY_HARVEST=1`，2026-11-24），触发条件：

1. 单腿、≥`min_size`、标记价 ≥0.99、在 0.99 卖出仍盈利；
2. 该 token 上没有已挂单；
3. **买一 ≥0.99**，且按悲观费率计算仍高于成本：`0.99 × (1 - fee_bps/1e4) > 成本`。

**优先顺序**：买一 ≥0.99 时先走 harvest（直接拿 0.999），rescue 让路——花 1¢ 补腿再合并的净收益（0.99）低于直接卖。`run_rescue` 会读取持有腿的买一，≥0.99 即跳过并记录原因。

费率闸门优先用**实测值**：成交后从 trade 记录读取 `fee_bps` 写入 `journal/fees.json`，harvest 先查它，查不到才退回市场配置。原因是市场元数据写着 1000 bps 的市场，实际成交收的是 0。

第 3 条是实测出来的：在 0.99 挂限价卖单会**穿价成交**，交易所按对手价给价格改善（2026-11-24 两笔分别成交于 0.999，`fee_bps = 0`）。所以限价是下限而不是目标价，买一才是实际成交价。

定时器 `pmm-harvest.timer` 每 10 分钟跑一次，`--dry-run` 可随时预演。

## 关键不变量

1. **只挂买单**。`Runner._payloads` 会拒绝任何非 post-only 或非 BUY 的意图。
2. **配对不变量**：`p_up + p_down ≤ 1 - tick`，否则同一次报价里两条腿会锁死亏损。
3. **资金守卫**：每轮向交易所读取真实可用余额，买不起的腿直接丢弃并记 `order_skipped`，不把注定被拒的单发出去。
4. **库存来自交易所**，不是日志。实盘成交不会写 journal，只有纸面模式会写；用 journal 推库存会让风控在真正需要时失明。
5. **奖励带宽是硬顶**：报价半价差被夹到 `max_spread` 以内，超出带宽的报价得分为 0。

---

## 测试

```bash
python -m pytest -q     # 204 passed
```

测试覆盖：报价构造与配对不变量、闸门栈、资金守卫、交易所持仓读取、合并逻辑、日志脱敏、指标。

---

## 相关文档

- `CHANGELOG.md`：实盘踩坑记录（含每次事故的根因与修复）
- `docs/plan.md`：整体方案与阶段划分
- `docs/decisions/`：架构决策记录
- `docs/conversation.html`：完整开发对话（已脱敏）
