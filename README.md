# bStock Web3 Trading Agent

[中文](#项目简介--overview) · [English](#project-overview-english)

## 项目简介 / Overview

这是一个面向 Binance bStock 的独立、安全优先量化交易代理，为
**Binance Agent OS Mini Hackathon — Track A** 构建。

项目将 Binance bStock 市场数据转换为本地 1 分钟/5 分钟 EMA 交易信号，支持确定性历史回放、
模拟盘监控，并可把经过用户确认的订单路由到两条彼此独立的执行通道：

- **Binance Agent OS MCP**：通过 OAuth 选择的 Agentic 子账户执行 Binance Spot 订单。
- **Binance Agentic Wallet (`baw`)**：在 BSC 上执行 bStock 报价和链上交易。

本项目已经从原研究系统中独立出来，运行时不依赖原系统模块。默认模式为模拟盘，
不会自动调用 MCP、钱包或执行真实交易。

## 核心功能 / Key Features

- Binance 公共 bStock 目录、合约地址和实时市场状态发现。<br>
  Public Binance bStock catalog, contract-address and live market-status discovery.
- 支持断点续传的 Binance bStock Spot 秒级历史数据，以及 1m/5m K 线聚合。<br>
  Resumable Binance bStock Spot one-second history with 1m/5m candle aggregation.
- 本地多周期策略：5 分钟 EMA 判断趋势，1 分钟 EMA 产生执行信号。<br>
  Local multi-timeframe strategy: 5m EMA trend confirmation plus 1m EMA execution.
- 确定性历史回放、模拟交易和独立 PyQt 桌面监控窗口。<br>
  Deterministic replay, paper trading and a standalone PyQt desktop monitor.
- 本地 `paper`、Agentic Wallet `quote` 和 `live-confirmed` 模式。<br>
  Local `paper` plus Agentic Wallet `quote` and `live-confirmed` modes.
- 为 OAuth Agentic 子账户生成不含凭据的 Agent OS MCP Spot 订单计划。<br>
  Credential-free Agent OS MCP Spot plans for an OAuth-selected Agentic sub-account.
- 通过官方 `baw --json` 接入 Binance Agentic Wallet。<br>
  Binance Agentic Wallet integration through the official `baw --json` interface.
- 对资格名单、余额、往返成本、Quote 时效、重复确认、未决订单、状态损坏和未完成 K 线实行失败关闭。<br>
  Fail-closed controls for eligibility, balances, round-trip cost, stale quotes,
  duplicate confirmations, pending orders, corrupted state and incomplete candles.
- 未决订单原子化记录，并支持进程重启后的订单状态恢复。<br>
  Atomic pending-order journaling and restart reconciliation.

## 本轮新增功能 / Latest Development Update

这一轮重点是本地桌面、模拟风控和策略迁移基础，不是无人值守实盘发布。<br>
This update focuses on the local desktop, paper-risk controls and strategy migration;
it is **not an unattended live-trading release**.

| 模块 / Module | 新增能力 / Added capabilities | 状态 / Status |
| --- | --- | --- |
| 桌面监控 / Desktop | 后台单线程评估、等待安全停止、状态窗口互斥、非阻塞风控弹窗、模拟账户及逐笔策略最近100笔成交 / Single-worker evaluation, safe-stop waiting, per-state locking, nonmodal alerts, paper account and latest 100 tick-strategy fills | 可用 / Available |
| K线页 / Candles | 1m/5m已收盘K线、UTC时间、失败后历史数据标记 / Closed 1m/5m candles, UTC timestamps and historical-data markers after failures | 可用 / Available |
| 模拟风控 / Paper risk | 日累计净值亏损、连亏次数、每日开仓次数、冷却和持仓成本上限 / Daily equity loss, loss streak, daily entries, cooldown and position cost cap | MTF、Median、Range模拟可用 / Available in MTF, Median and Range paper modes |
| 参数保存 / Preferences | 保存/读取标的、模式、风控和MTF/Median/Range参数；重启不自动运行 / Save/load symbol, mode, risk and MTF/Median/Range inputs; never auto-start on restore | v4，可用 / v4, available |
| 策略页 / Strategies | MTF EMA默认/自定义、逐笔Median、固定Range EMA/Median / Default/custom MTF EMA, tick Median and fixed Range EMA/Median | 全部仅模拟改参 / Editing is paper-only |
| Median | 公共逐笔分页、SQLite事务模拟账本、重启停买和桌面参数 / Public trade pagination, transactional SQLite paper ledger, restart BUY latch and desktop inputs | 桌面模拟可用；真实行情成交尚待验证 / Desktop paper available; public-market fills remain unverified |
| Fixed Range | 逐笔构造价格区间bar、EMA/Median、事务恢复及独立桌面参数 / Tick-built price-range bars, EMA/Median, transactional recovery and isolated desktop inputs | 桌面模拟可用；Slope本轮不加入 / Desktop paper available; Slope intentionally deferred |
| 独立MCP基础 / Standalone MCP foundations | PKCE/state、本机回调、发现协议和固定端点HTTP/SSE / PKCE/state, loopback callback, discovery protocol and pinned HTTP/SSE | 基础模块；授权与账户连接未完成 / Foundations only; authorization/account integration incomplete |

### 默认模拟风控 / Default Paper Controls

- 桌面单笔金额100，持仓成本上限100；CLI历史单笔默认20保持不变。<br>
  Desktop entry budget and position cost cap: 100 each; historical CLI entry default remains 20.
- UTC日累计净值亏损阈值10，包含模拟手续费和持仓浮动损益；连续亏损3笔、每日最多20次开仓、开仓冷却60秒。<br>
  UTC daily equity-loss threshold: 10, including simulated fees and unrealized PnL;
  three losing closes, 20 daily entries and a 60-second entry cooldown.
- 风控暂停只停止买入，不强制清仓；卖出继续等原策略信号。暂停跨重启、跨日保留，需要手动恢复。<br>
  Risk latches block BUYs without forced liquidation; SELLs still follow strategy signals.
  Latches survive restarts/day rollover and require manual resume.
- 恢复不重置当日净值基准，也不能绕过仍触及的日亏损或开仓次数限制。亏损阈值不保证最终损失不超过10。<br>
  Resume preserves the daily baseline and cannot bypass active daily loss/count limits.
  The threshold does not guarantee a maximum final loss of 10.

桌面参数在启动前编辑并显式保存。账本、暂停状态和参数文件相互独立；加载参数不会清除风险历史。
当前K线展示使用与策略相同的快照，不会额外调用钱包或下单。<br>
Edit and explicitly save desktop inputs before starting. Preferences are separate from
ledger/risk state; loading them does not clear risk history. Charts share the strategy's
market snapshot and do not trigger additional wallet calls or orders.

### 验证与尚未完成 / Verification and Remaining Work

- 本地Python 3.11完整回归：**256项通过**。原生桌面合成验收：650轮刷新，包含38次故障注入。<br>
  Local Python 3.11 regression: **256 passed**. Native synthetic desktop acceptance:
  650 refresh attempts with 38 injected failures.
- Median完成200轮/400笔模拟成交，多次重启与重复重放、事务失败回滚、并发旧写入方拒绝测试。<br>
  Median completed 200 rounds/400 simulated fills with repeated restores/replays,
  transaction rollback and stale-writer rejection tests.
- 上述为离线/加速验证，不代表长时间真实行情或真实账户验收。<br>
  These are offline/accelerated checks, not sustained real-market or real-account acceptance.
- Median已接公共NVDAB逐笔行情和桌面；两轮读取成功，但数据不新鲜，因此未触发模拟成交。见[Median桌面说明](docs/MEDIAN_DESKTOP.md)。<br>
  Median public NVDAB feed and desktop are connected; two reads succeeded but stale ticks produced no paper fills. See [Median desktop notes](docs/MEDIAN_DESKTOP.md).
- **尚未完成**：持续真实行情与成交验收、完整历史成交UI、Slope/Auto迁移、
  独立OAuth Token交换/安全存储、MCP账户核对及无人值守执行验收。<br>
  **Pending**: sustained public-market/fill acceptance, a complete history UI,
  Slope/Auto migration, standalone OAuth token exchange/secure storage,
  MCP account reconciliation and unattended-execution acceptance.

技术说明 / Technical notes:
[模拟风控 / Paper risk](docs/PAPER_RISK.md) ·
[参数保存 / Preferences](docs/DESKTOP_SETTINGS.md) ·
[策略编辑 / Strategy editing](docs/STRATEGY_INTEGRATION.md) ·
[Median事务账本 / Median ledger](docs/MEDIAN_PAPER.md) ·
[固定Range策略 / Fixed Range strategies](docs/RANGE_DESKTOP.md) ·
[MCP归并边界 / MCP integration boundaries](docs/CONSOLIDATION.md).

## 系统架构 / Architecture

```text
Binance 公共 bStock API ──► 标的目录 / 市场状态
Binance Spot K 线 ─────────► 秒级历史 ─► 1m / 5m K 线
                                         │
                                         ▼
                                  本地 MTF EMA 策略
                                         │
                      ┌──────────────────┼────────────────────┐
                      ▼                  ▼                    ▼
                    模拟盘        Agent OS MCP 计划     Wallet 报价/实盘
                                         │                    │
                                         ▼                    ▼
                              Agentic 子账户 Spot      Agentic Wallet (BSC)
```

MCP 桥接层会把 OAuth 和账户凭据留在 Agent OS 宿主中。本地程序只生成短时有效、需要一次性确认的
`spot.newOrder` 计划；宿主必须在下单前重新检查账户、交易对、手续费、余额和最终订单内容。

Agentic Wallet 是独立的链上执行通道，具有自己的余额、Quote、滑点、Gas 和确认检查。两条通道不共享
凭据；任何一条通道失败时，都不会静默切换到另一条通道。

The MCP bridge keeps OAuth and account credentials inside the Agent OS host. Local code
only emits a short-lived, one-time-confirmed `spot.newOrder` plan. Before dispatch, the
host must revalidate the account, symbol, commission, balance and final order. Agentic
Wallet remains a separate on-chain route with its own balance, quote, slippage, gas and
confirmation checks. The transports never share credentials or silently fall back to one
another.

## 快速开始 / Quick Start

需要 Python 3.11 或更高版本。<br>
Python 3.11 or later is required.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,desktop]"
.venv\Scripts\python -m pytest
```

### 运行一次模拟策略 / Run One Paper Evaluation

```powershell
bstock-engine --symbol NVDAB --mode paper --amount 20 --once
```

### 启动桌面监控 / Launch the Desktop Monitor

```powershell
bstock-desktop
```

窗口包含“监控 / Monitor”“K线 / Candles”“策略 / Strategies”和“账户 / Account”。选择MTF EMA、逐笔Median、固定Range EMA或Range Median，检查金额与风控，再点击启动。各逐笔策略使用独立模拟资金；GUI没有真实下单开关。<br>
The window has Monitor, Candles and Strategies tabs. Select default/custom MTF EMA,
tick Median, fixed Range EMA or Range Median, review budget/risk inputs, then start.
Each tick strategy uses separate simulated funds; the GUI has no live-order switch.

本地合成桌面验收（不连接账户，结果保存在被Git忽略的`runtime/`目录）：<br>
Local synthetic desktop acceptance (no account connection; output stays in git-ignored `runtime/`):

```powershell
.venv\Scripts\python scripts/local_desktop_acceptance.py
```

### 生成 Agent OS MCP 订单计划 / Create an Agent OS MCP Plan

```powershell
bstock-mcp-plan --symbol NVDAB --amount 20
```

如果策略返回 `hold`，程序不会创建订单计划。只有可执行的 `buy` 或 `sell` 信号才会在
`runtime/mcp/` 下生成短时有效的 JSON 计划。该文件本身不会调用 MCP，也不会执行交易。

If the strategy returns `hold`, no order plan is created. Only an actionable `buy` or
`sell` signal produces a short-lived JSON plan under `runtime/mcp/`. The file cannot call
MCP or place an order by itself.

详细流程请参阅 [Agent OS MCP 双执行通道说明](docs/AGENT_OS_MCP.md)。<br>
See [Agent OS MCP dual-execution guide](docs/AGENT_OS_MCP.md) for the complete workflow.

### 下载、聚合并回放历史数据 / Download, Aggregate and Replay History

```powershell
bstock-history --symbol NVDAB --days 3
bstock-backtest --data kline_history\bstock\NVDAB\<window>\klines_1m.parquet
```

完整的安装、模拟盘、MCP、Wallet 和故障排查步骤见
[用户搭建与使用指南](docs/USER_GUIDE.md)。<br>
See the [setup and user guide](docs/USER_GUIDE.md) for installation, paper mode, MCP,
Wallet and troubleshooting.

短视频和评审演示步骤见 [演示指南](docs/DEMO.md)。<br>
See the [demo guide](docs/DEMO.md) for a concise judging and video flow.

## 实盘安全机制 / Live-Execution Safety

`paper` 是默认模式；`quote` 只获取报价，不提交交易。Agentic Wallet 的 `live-confirmed` 模式在每一笔
真实交易前都必须满足：

1. Agentic Wallet 会话处于连接状态。<br>
   The Agentic Wallet session is connected.
2. 操作者提供当前有效、合约地址完全匹配的资格名单 JSON。<br>
   A current operator-verified eligibility JSON exactly matches the contract.
3. Quote 仍在有效期内，且预计收益能够覆盖往返交易成本和安全余量。<br>
   The quote is fresh and expected edge covers round-trip cost plus the safety margin.
4. 钱包余额充足，标的实时市场状态为 `TRADING`。<br>
   Wallet balance is sufficient and live market status is `TRADING`.
5. 用户输入专门为该订单计划生成的一次性随机确认码。<br>
   The operator enters the one-time random confirmation generated for that exact plan.

MCP 通道还要求宿主在逐笔确认前重新查询 Agentic 子账户、Spot 规则、余额、手续费和最终订单参数。
生成 MCP JSON 计划不等于授权交易。

The MCP path additionally requires the host to re-query the Agentic sub-account, Spot
rules, balances, commission and final order parameters before per-order confirmation.
Creating an MCP JSON plan is not authorization to trade.

获得订单 ID 后，程序会先原子化保存，再查询终态。超时或重启不会导致静默重复下单。项目不会保存
私钥、助记词、Binance 密码、钱包会话凭据或 MCP OAuth Token。

Once an order ID exists, it is atomically journaled before terminal-status polling. A
timeout or restart cannot silently create a duplicate order. The project never stores
private keys, seed phrases, Binance passwords, wallet-session credentials or MCP OAuth
tokens.

Agentic Wallet 实盘命令示例（仍然会停下来要求逐笔确认）：<br>
Example Agentic Wallet live command (still pauses for per-order confirmation):

```powershell
bstock-engine --symbol NVDAB --mode live-confirmed --amount 20 `
  --eligibility-file .\eligible-current.json --once
```

## 当前代码状态 / Current Code Status

- 包版本 / Package version: `v1.1.0`（本轮为开发更新，未新建Release标签 / development update; no new release tag）
- 本地自动化测试 / Local automated tests: `256 passed`
- 桌面策略 / Desktop strategies: 可编辑MTF EMA、逐笔Median、固定Range EMA/Median / editable MTF EMA, tick Median and fixed Range EMA/Median
- 模拟账本 / Paper ledger: Median与Range使用逐笔/资金/风险事务保存 / Median and Range commit ticks, funds and risk transactionally
- 已验证范围 / Verified scope: 历史回放、本地模拟与合成桌面验收 / historical replay, local paper and synthetic desktop acceptance
- 执行适配器 / Execution adapters:
  - Agent OS MCP 宿主交接 / Agent OS MCP host handoff
  - Agentic Wallet 安全执行 / guarded Agentic Wallet execution
- 实盘前仍需人工确认并进行最小金额验收测试。<br>
  Live use still requires operator confirmation and minimum-size acceptance testing.

## 项目范围与免责声明 / Scope and Disclaimer

本项目是黑客松实验原型，不构成投资建议，也不承诺盈利。代币化证券和数字资产具有重大风险，并可能
在部分司法管辖区不可用。用户需要自行确认合规性、交易资格，并对每一笔确认执行的交易负责。

This repository is an experimental hackathon prototype, not investment advice and not a
promise of profitability. Tokenized securities and digital assets involve substantial
risk and may be unavailable in some jurisdictions. Users are responsible for compliance,
eligibility and every confirmed transaction.

代码提取边界和各版本安全变更记录见 [迁移文档](docs/MIGRATION.md)。<br>
See [migration notes](docs/MIGRATION.md) for extraction boundaries and versioned safety
changes.

---

## Project Overview (English)

bStock Web3 Trading Agent is a standalone, safety-first quantitative trading prototype
for Binance bStocks, built for the **Binance Agent OS Mini Hackathon — Track A**. It
combines public bStock data, local 1m/5m strategy signals, deterministic replay, paper
monitoring and two strictly separated execution bridges: Agent OS MCP Spot through an
OAuth-selected Agentic sub-account, and Agentic Wallet bStock swaps on BSC.

Paper mode is the default. No MCP call, wallet signature or real transaction is performed
without an actionable signal, fresh validation and explicit per-order confirmation.
