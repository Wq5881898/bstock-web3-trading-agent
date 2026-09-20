# Codex MCP宿主桥接 / Codex MCP host bridge

## 已确认的正确边界 / Confirmed boundary

本项目不再把自己实现成一个新的Binance OAuth客户端。已经跑通并持有现有Agentic子账户授权的是Codex中的`binance-agent-os` MCP连接。真实链路固定为：

```text
公共行情 -> 本地统一策略 -> 本地风控 -> 无凭据请求/订单计划
                                      -> 已授权Codex宿主
                                      -> Binance Agent OS MCP
                                      -> 现有Agentic子账户
```

This project no longer attempts to become a new Binance OAuth client. The working authorization is the existing `binance-agent-os` MCP connection owned by Codex. The repository produces credential-free work items; Codex owns MCP authentication and calls.

## 两项纠正 / Two corrections

1. 人工创建的普通Virtual Sub不是MCP Agentic账户，不作为本项目MCP目标。账户选择由Binance授权给支持的宿主完成；本地文件不保存UID或登录凭据。
2. 桌面程序不再启动OAuth、监听`127.0.0.1`回调、发布Client Metadata或直接向MCP端点发送Token。此前出现“当前Agent暂时不支持”的独立客户端路线已经撤下。

1. A manually created Virtual Sub is not the MCP Agentic account and is not targeted by this bridge. Binance binds the account to the supported host; local artifacts contain no UID or login credential.
2. The desktop no longer starts OAuth, listens for a loopback callback, publishes client metadata or sends tokens directly to the MCP endpoint. The rejected standalone-client route has been removed.

## 本地程序做什么 / What local code does

- `bstock-mcp-request --symbol BTCUSDT`：只写一个限时、只读、无凭据的账户核对请求。
- `bstock-mcp-plan --symbol NVDAB --amount 20`：仅在策略产生可执行信号时写订单计划。
- 桌面“账户”页只导出读取请求，不弹出Binance登录页。
- `mcp_spot_snapshot.py`、账本和风控模块严格校验宿主返回的脱敏结果。
- 本地没有API Key回退；如MCP无法满足无人值守要求，必须另行讨论并明确批准其他接口。

- `bstock-mcp-request --symbol BTCUSDT` writes a short-lived, read-only, credential-free reconciliation request.
- `bstock-mcp-plan --symbol NVDAB --amount 20` writes an order plan only for an actionable strategy signal.
- The desktop Account tab exports a request and never opens Binance login.
- Snapshot, ledger and risk modules strictly validate sanitized host results.
- There is no API-key fallback. Any alternative requires a separate decision and explicit approval.

## Codex宿主执行规则 / Codex host rules

读取请求到达后，Codex必须使用当前已经授权的Binance MCP连接，核对所选Agentic账户、余额、挂单、完整成交/订单分页、手续费、交易规则和盘口。订单计划必须重新检查时效、账户、余额、交易规则和最终参数；由支持的宿主/Binance完成用户确认。任何失败都关闭本次动作，不创建新账户、不重新走项目OAuth，也不静默切换到Agentic Wallet或API。

For a read request, Codex uses the already-authorized Binance MCP connection and verifies the selected Agentic account, balances, open orders, complete fill/order history, commission, exchange rules and book. Before an order, the supported host revalidates freshness, account, funds, rules and final arguments and owns user confirmation. Failure never creates an account, starts project OAuth or silently falls back to Wallet/API.

## 当前验收边界 / Current acceptance boundary

历史上已经通过Codex宿主完成真实只读核对和一笔约10 USDT的BTC买入；这些事实证明现有宿主链路可用。此次纠正没有再次读取账户、没有改动Agentic账户、没有下单。自动策略到真实MCP订单的持续编排仍需单独验收。

The existing Codex-hosted path previously completed live read reconciliation and an approximately 10-USDT BTC buy. This correction performs no account read, account mutation or order. Sustained strategy-to-live-order orchestration remains a separate acceptance task.
