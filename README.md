# bStock Web3 Trading Agent

A standalone, safety-first quantitative trading agent for Binance bStocks. Built for the
**Binance Agent OS Mini Hackathon — Track A**.

The agent turns Binance bStock market data into local 1-minute/5-minute EMA signals,
supports deterministic historical replay and paper monitoring, and can route a
user-confirmed order through either Binance Agent OS MCP Spot or Binance Agentic Wallet
(`baw`). It is deliberately
separate from the original Alpha2 research system and has no `alpha2.*` runtime imports.

> 中文简介：这是一个独立的币股量化交易代理，具有本地策略、历史回测、模拟监控、
> Agentic Wallet 报价/交易适配和实盘安全闸门。默认只运行模拟盘，不会自动动用钱包。

## What it demonstrates

- Public Binance bStock catalog and live market-status discovery.
- Binance bStock Spot 1-second history with resumable download and 1m/5m aggregation.
- A local multi-timeframe strategy: 5m EMA trend confirmation plus 1m EMA execution.
- Deterministic historical replay and a standalone PyQt monitoring window.
- Local `paper` and Wallet `quote` / `live-confirmed` execution modes.
- Credential-free Agent OS MCP Spot order plans for an OAuth-selected Agentic sub-account.
- Binance Agentic Wallet integration through the official `baw --json` interface.
- Fail-closed controls for eligibility, balance, round-trip cost, stale quotes, duplicate
  confirmations, pending orders, corrupted state and incomplete candles.
- Atomic pending-order journaling and restart reconciliation.

## Architecture

```text
Binance public bStock APIs ──► Catalog / market status
Binance Spot K-lines ────────► 1s history ─► 1m / 5m bars
                                      │
                                      ▼
                              Local MTF EMA strategy
                                      │
                       ┌──────────────┼──────────────────────┐
                       ▼              ▼                      ▼
                     paper     Agent OS MCP plan       Wallet quote/live
                                      │                      │
                                      ▼                      ▼
                         Agentic sub-account Spot     Agentic Wallet (BSC)
```

The MCP bridge intentionally keeps OAuth and account credentials in the Agent OS host.
Local code emits a short-lived, one-time-confirmed `spot.newOrder` plan; the host must
revalidate the account, symbol, commission and final order before dispatch. The Wallet
bridge remains a separate on-chain path with its own balance, quote, gas and confirmation
checks. The two transports never share credentials or silently fall back to one another.

## Quick start

Python 3.11+ is required.

```powershell
py -3.11 -m venv .venv
.venv\Scripts\python -m pip install -e ".[dev,desktop]"
.venv\Scripts\python -m pytest
```

Run one paper evaluation:

```powershell
bstock-engine --symbol NVDAB --mode paper --amount 20 --once
```

Launch the standalone monitor:

```powershell
bstock-desktop
```

Create an Agent OS MCP Spot handoff from a live local strategy signal:

```powershell
bstock-mcp-plan --symbol NVDAB --amount 20
```

If the strategy says `hold`, no plan is created. An actionable signal produces a
short-lived JSON plan under `runtime/mcp/`; it does not call MCP or place an order by
itself. See [docs/AGENT_OS_MCP.md](docs/AGENT_OS_MCP.md).

Download and aggregate three days of history, then replay it:

```powershell
bstock-history --symbol NVDAB --days 3
bstock-backtest --data kline_history\bstock\NVDAB\<window>\klines_1m.parquet
```

See [docs/DEMO.md](docs/DEMO.md) for a short judging/demo flow.

## Execution safety

`paper` is the default. `quote` requests prices but does not submit a transaction.
`live-confirmed` requires all of the following before every real order:

1. An active Agentic Wallet session.
2. A current operator-verified eligibility JSON with an exact contract match.
3. A fresh quote and a passing expected-edge versus round-trip-cost gate.
4. Sufficient wallet balance and a live `TRADING` market status.
5. The one-time random confirmation code generated for that exact plan.

Once an order ID exists, it is atomically journaled. A timeout or restart queries that
same order and blocks duplicate submissions until reconciliation completes. The project
never stores private keys, seed phrases, Binance passwords or wallet session credentials.

Example live command (still stops for per-order confirmation):

```powershell
bstock-engine --symbol NVDAB --mode live-confirmed --amount 20 `
  --eligibility-file .\eligible-current.json --once
```

## Current release

- Version: `v1.1.0`
- Automated tests: 23
- Current strategy: MTF EMA 5m trend / 1m execution
- Tested modes: historical replay and paper monitoring
- Real execution: guarded Agentic Wallet adapter plus an Agent OS MCP host-handoff
  adapter; both require operator confirmation and small-size acceptance testing.

## Scope and disclaimer

This repository is an experimental hackathon prototype, not investment advice and not a
promise of profitability. Tokenized securities and digital assets involve substantial
risk and may be unavailable in some jurisdictions. Users are responsible for eligibility,
compliance and every confirmed transaction.

The extraction boundary and version-by-version safety changes are documented in
[docs/MIGRATION.md](docs/MIGRATION.md).

