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
- `bstock-mcp-import`：核对Codex回执并生成本地已验证快照；首次账户指纹必须显式登记。
- `bstock-mcp-plan --symbol NVDAB --amount 20`：仅在策略产生可执行信号时写订单计划。
- 桌面“账户”页只导出读取请求，不弹出Binance登录页。
- `mcp_spot_snapshot.py`、账本和风控模块严格校验宿主返回的脱敏结果。
- 本地没有API Key回退；如MCP无法满足无人值守要求，必须另行讨论并明确批准其他接口。

- `bstock-mcp-request --symbol BTCUSDT` writes a short-lived, read-only, credential-free reconciliation request.
- `bstock-mcp-import` verifies a Codex receipt and writes a local verified snapshot; first-account fingerprint enrollment must be explicit.
- `bstock-mcp-plan --symbol NVDAB --amount 20` writes an order plan only for an actionable strategy signal.
- The desktop Account tab exports a request and never opens Binance login.
- Snapshot, ledger and risk modules strictly validate sanitized host results.
- There is no API-key fallback. Any alternative requires a separate decision and explicit approval.

## Codex宿主执行规则 / Codex host rules

读取请求到达后，Codex必须使用当前已经授权的Binance MCP连接，核对所选Agentic账户、余额、挂单、完整成交/订单分页、手续费、交易规则和盘口。订单计划必须重新检查时效、账户、余额、交易规则和最终参数；由支持的宿主/Binance完成用户确认。任何失败都关闭本次动作，不创建新账户、不重新走项目OAuth，也不静默切换到Agentic Wallet或API。

For a read request, Codex uses the already-authorized Binance MCP connection and verifies the selected Agentic account, balances, open orders, complete fill/order history, commission, exchange rules and book. Before an order, the supported host revalidates freshness, account, funds, rules and final arguments and owns user confirmation. Failure never creates an account, starts project OAuth or silently falls back to Wallet/API.

## 读取回执闭环 / Read-receipt loop

1. 运行`bstock-mcp-request --symbol BTCUSDT`，或在桌面账户页点击“导出Codex读取请求”。
2. 让当前Codex任务读取JSON；按`required_tools`调用现有Binance MCP，并完整分页成交和订单。
3. Codex用请求中的算法计算账户指纹：`sha256(bytes.fromhex(salt) + str(uid).encode("ascii"))`。随后从持久化回执中删除`uid`。
4. Codex把严格格式的回执写到桌面提示的`*-host-receipt.json`位置。回执不得包含UID、Token、API Key、密码、私钥或助记词。
5. 首次使用时，用户检查Binance界面确认当前选择的是既有Agentic账户，然后显式登记：

```powershell
bstock-mcp-import `
  --request runtime\desktop\mcp\btcusdt-read-request.json `
  --receipt runtime\desktop\mcp\btcusdt-host-receipt.json `
  --binding-file runtime\desktop\mcp\account-binding.json `
  --output runtime\desktop\mcp\btcusdt-verified-snapshot.json `
  --enroll-account
```

6. 以后不再使用`--enroll-account`。桌面“导入Codex回执”会拒绝不同账户指纹、过期请求、不完整分页、缺失工具、UID/凭据泄露和无法由成交解释的余额。

1. Run `bstock-mcp-request --symbol BTCUSDT` or export a request from the desktop.
2. The current Codex task consumes the JSON through the existing Binance MCP connection and fully paginates fills/orders.
3. Codex computes `sha256(bytes.fromhex(salt) + str(uid).encode("ascii"))`, then removes `uid` from the persisted receipt.
4. Codex writes the strict receipt to the `*-host-receipt.json` path shown by the desktop. No UID, token, API key, password, private key or seed phrase is allowed.
5. The user verifies the existing Agentic account in Binance and explicitly runs the first import with `--enroll-account`.
6. Later imports omit enrollment. The desktop rejects changed account fingerprints, expired/mismatched requests, incomplete pagination, missing tools, credential/UID leakage and balances not explained by fills.

### 给Codex宿主的任务模板 / Codex-host task template

```text
读取指定的 bStock MCP read-request JSON。只使用当前已经授权的
binance-agent-os MCP连接，不创建账户、不重新OAuth、不交易。
按required_tools逐项读取；spot.myTrades和spot.allOrders必须完整分页。
使用account_binding.algorithm和salt对真实uid计算账户指纹，然后从回执删除uid。
回执严格使用READ_SPOT_SNAPSHOT_RESULT格式，completed_tools保持请求顺序，
pagination的trades_complete/orders_complete只有在确实完整时才能为true。
将脱敏回执写入用户指定的host-receipt路径。不要写入Token、API Key、密码、
私钥、助记词或授权码；失败时不要生成成功回执。
```

## 当前验收边界 / Current acceptance boundary

历史上已经通过Codex宿主完成真实只读核对和一笔约10 USDT的BTC买入；这些事实证明现有宿主链路可用。当前代码已完成无凭据请求、脱敏回执、显式首次绑定和本地严格导入，但尚未用新回执格式再次访问真实账户。自动策略到真实MCP订单的持续编排仍需单独验收。

The existing Codex-hosted path previously completed live read reconciliation and an approximately 10-USDT BTC buy. The repository now implements credential-free requests, sanitized receipts, explicit first binding and strict local import, but the new receipt format has not yet been exercised against the live account. Sustained strategy-to-live-order orchestration remains separate acceptance.
