# bStock Web3 Trading Agent

[中文](#项目简介--overview) · [English](#project-overview-english)

## 项目简介 / Overview

这是一个面向 Binance bStock 的独立、安全优先量化交易代理，为
**Binance Agent OS Mini Hackathon — Track A** 构建。

项目将 Binance bStock 市场数据转换为本地 1 分钟/5 分钟 EMA 交易信号，支持确定性历史回放、
模拟盘监控，并可把经过用户确认的订单路由到两条彼此独立的执行通道：

- **Binance Agent OS MCP**：通过 OAuth 选择的 Agentic 子账户执行 Binance Spot 订单。
- **Binance Agentic Wallet (`baw`)**：在 BSC 上执行 bStock 报价和链上交易。

本项目已经从原 Alpha2 研究系统中独立出来，运行时不依赖任何 `alpha2.*` 模块。默认模式为模拟盘，
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

## 当前版本 / Current Release

- 版本 / Version: `v1.1.0`
- 自动化测试 / Automated tests: `23 passed`
- 当前策略 / Strategy: 5m 趋势确认 + 1m 执行的 MTF EMA
- 已验证模式 / Verified modes: 历史回放、模拟盘监控 / historical replay and paper monitoring
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
