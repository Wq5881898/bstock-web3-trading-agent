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
- `bstock-mcp-cycle --verified-snapshot <新鲜回执>`：在现有权益基线和完整成交账本上重算 BTCUSDT 策略，把信号交给持久会话，最多生成一个无凭据候选；不调用 MCP 写工具。
- `bstock-mcp-host-cycle --request <读取请求>`（脱敏JSON由标准输入提供）：已有账户绑定下，在一个本地进程内严格导入宿主回执并运行上述策略周期，减少15秒回执窗口内的文件交接耗时；仍需Codex宿主完成MCP读取和提供脱敏JSON。
- `bstock-mcp-plan --symbol BTCUSDT --amount 100 --verified-snapshot runtime\mcp\latest-verified-snapshot.json`：仅在账户快照新鲜且策略产生有效信号时写schema v3候选计划；不能直接下单。
- 桌面“账户”页只导出读取请求，不弹出Binance登录页。
- `mcp_spot_snapshot.py`、账本和风控模块严格校验宿主返回的脱敏结果。
- 本地没有API Key回退；如MCP无法满足无人值守要求，必须另行讨论并明确批准其他接口。

- `bstock-mcp-request --symbol BTCUSDT` writes a short-lived, read-only, credential-free reconciliation request.
- `bstock-mcp-import` verifies a Codex receipt and writes a local verified snapshot; first-account fingerprint enrollment must be explicit.
- `bstock-mcp-cycle --verified-snapshot <fresh receipt>` re-evaluates the BTCUSDT strategy against the established equity baseline and complete fill ledger, then hands the signal to the durable session for at most one credential-free candidate. It never calls a private MCP write tool.
- `bstock-mcp-host-cycle --request <read request>` consumes sanitized JSON on stdin, verifies it, and runs the same cycle in one local process against an already-enrolled account. Codex must still perform the MCP reads and supply the JSON; this reduces handoff delay within the 15-second freshness window.
- `bstock-mcp-plan --symbol BTCUSDT --amount 100 --verified-snapshot runtime\mcp\latest-verified-snapshot.json` writes a schema-v3 candidate only with fresh account evidence and an actionable signal; it is not directly dispatchable.
- The desktop Account tab exports a request and never opens Binance login.
- Snapshot, ledger and risk modules strictly validate sanitized host results.
- There is no API-key fallback. Any alternative requires a separate decision and explicit approval.

## Codex宿主执行规则 / Codex host rules

读取请求到达后，Codex必须使用当前已经授权的Binance MCP连接，核对所选Agentic账户、余额、挂单、完整成交/订单分页、手续费、交易规则和盘口。候选计划必须重新检查时效、账户指纹、余额、交易规则和最终参数；确认被消费并且本地日志原子进入`SUBMITTING`后，才允许生成最多15秒的单次提交票据。任何失败都关闭本次动作，不创建新账户、不重新走项目OAuth，也不静默切换到Agentic Wallet或API。

For a read request, Codex uses the already-authorized Binance MCP connection and verifies the selected Agentic account, balances, open orders, complete fill/order history, commission, exchange rules and book. A candidate must be revalidated against freshness, account fingerprint, funds, rules and final arguments. Only consumed confirmation plus durable `SUBMITTING` may produce a one-shot ticket valid for at most 15 seconds. Failure never creates an account, starts project OAuth or silently falls back to Wallet/API.

**后台宿主限制 / Headless-host limit.** 2026-09-23 本机只读测试确认 Codex CLI 配有现有MCP，但非交互模式的默认审批策略拒绝通用 `tool_execute`；该工具既可转发读取也可转发写入，因此不能为自动读取而整体放行。当前的单次真实策略周期由交互式 Codex 宿主完成，尚不是无人值守服务。/ The local Codex CLI has the existing MCP configured, but its non-interactive default approval policy rejected generic `tool_execute`. Because that dispatcher can forward both reads and writes, blanket approval is unsafe. The verified live strategy cycle used the interactive Codex host, not an unattended service.

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
7. 若要让当前策略会话处理这次刷新，优先把脱敏JSON直接交给 `bstock-mcp-host-cycle --request runtime\desktop\mcp\btcusdt-read-request.json --binding-file runtime\desktop\mcp\account-binding.json --verified-snapshot runtime\desktop\mcp\btcusdt-verified-snapshot.json --runtime-dir runtime\desktop\mcp` 的标准输入。原有 `bstock-mcp-import` 加 `bstock-mcp-cycle` 两步方式仍可用，但真实读取后分开交接曾超过15秒而被安全拒绝。任何路径都不得重写实际观察时间以绕过时限。命令可能返回 `HOLD`、`BLOCKED` 或候选文件；候选仍须经过逐笔确认和一次性票据，绝不直接下单。

1. Run `bstock-mcp-request --symbol BTCUSDT` or export a request from the desktop.
2. The current Codex task consumes the JSON through the existing Binance MCP connection and fully paginates fills/orders.
3. Codex computes `sha256(bytes.fromhex(salt) + str(uid).encode("ascii"))`, then removes `uid` from the persisted receipt.
4. Codex writes the strict receipt to the `*-host-receipt.json` path shown by the desktop. No UID, token, API key, password, private key or seed phrase is allowed.
5. The user verifies the existing Agentic account in Binance and explicitly runs the first import with `--enroll-account`.
6. Later imports omit enrollment. The desktop rejects changed account fingerprints, expired/mismatched requests, incomplete pagination, missing tools, credential/UID leakage and balances not explained by fills.
7. To feed a refresh into the durable session, prefer handing the sanitized JSON on stdin to `bstock-mcp-host-cycle` with the existing request, binding, verified-snapshot, and runtime paths. The two-step import plus `bstock-mcp-cycle` remains available, but one live handoff exceeded 15 seconds and correctly failed closed. Never alter the actual observation time to extend the window. A candidate still requires per-order confirmation and a one-shot ticket; this command never submits it.

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

历史上已经通过Codex宿主完成真实只读核对和一笔约10 USDT的BTC买入。2026-09-21又使用当前代码的新回执格式完成一次真实`BTCUSDT`只读闭环：无凭据请求、7项MCP读取、完整分页、内存指纹计算、UID删除、显式首次绑定和本地严格导入全部通过。2026-09-23同进程导入/周期入口在真实七项MCP只读刷新后返回策略`HOLD`、持久会话`RUNNING`，没有候选或订单；本地公开行情需有网络访问权限。自动持续唤醒MCP及策略到真实订单的编排仍需单独验收。

The existing Codex-hosted path previously completed live read reconciliation and an approximately 10-USDT BTC buy. On 2026-09-21, the current receipt format completed a live `BTCUSDT` read loop: credential-free request, seven MCP reads, complete pagination, in-memory fingerprint derivation, UID removal, explicit first binding and strict local import. On 2026-09-23, the same-process import/cycle returned strategy `HOLD` and durable session `RUNNING` after a fresh live seven-read MCP snapshot, with no candidate or order. The local public-candle feed needs network access. Continuous MCP wake-up and strategy-to-real-order orchestration remain separate acceptance.
