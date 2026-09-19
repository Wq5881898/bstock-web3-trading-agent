# MCP写工具schema验收 / MCP write-schema acceptance

## 用途 / Purpose

`bstock-mcp-schema`是首次真实连接前的独立验收命令。它完成项目Client Metadata校验、浏览器OAuth、Token交换、MCP初始化和`tools/list`，随后立即关闭Token和会话。

`bstock-mcp-schema` is a standalone acceptance command for the first real connection. It validates project client metadata, performs browser OAuth and token exchange, initializes MCP, calls `tools/list`, then immediately closes the token and session.

它不会调用任何`tools/call`，因此不会读取账户、余额、订单或成交，也不会下单。成功输出只包含协议版本、必需只读工具数量、`spot.newOrder`与`spot.getOrder`名称、两个写工具规范化schema的SHA-256指纹，以及明确的`readAccount=false`、`orderCalled=false`、`sessionClosed=true`。

It never invokes `tools/call`, so it reads no account, balance, order or fill and cannot submit an order. Success output contains only the protocol version, required read-tool count, the two write-tool names, a canonical write-schema SHA-256 fingerprint, and explicit no-read/no-order/session-closed flags.

## 命令 / Command

```powershell
cd "D:\Agentic Wallet\bstock-web3-engine"
.\.venv\Scripts\python.exe -m bstock_web3.mcp_schema_cli
```

如果浏览器未自动打开，可运行：

```powershell
.\.venv\Scripts\python.exe -m bstock_web3.mcp_schema_cli --no-browser
```

复制终端临时显示的Binance授权地址到同一台电脑的浏览器。回调监听只绑定`127.0.0.1`随机端口，最多等待300秒。不要把授权地址、回调地址、授权码或终端完整输出发布到GitHub或聊天；只保留最终成功JSON中的schema指纹。

If the browser does not open, use `--no-browser` and open the transient authorization URL on the same computer. The callback binds only to a random `127.0.0.1` port and waits at most 300 seconds. Never publish authorization/callback URLs, authorization codes or full terminal output; retain only the final success JSON schema fingerprint.

## 失败含义 / Failure meaning

- `OAuth client metadata unavailable`：默认jsDelivr身份文件不可访问或缓存尚未刷新。先验证公开GitHub文件、刷新CDN缓存并重试；GitHub Pages仅为可选替代。
- `Required confirmed-session MCP tools unavailable`：本账户授权范围或服务端工具集合不满足项目要求。
- `Incompatible confirmed MCP schema`：服务端schema与当前严格适配器不兼容。必须更新代码和测试；不得临时放宽验证。
- 超时/拒绝：重新运行命令产生新的PKCE/state；不要重用旧URL。

Metadata unavailability means the default jsDelivr identity file is unreachable or its cache has not refreshed. Verify the public GitHub file, purge the CDN cache and retry; GitHub Pages is only an optional alternative. Missing tools indicate insufficient scope/service capability. An incompatible schema requires a reviewed code/test update—not a bypass. Timeout/denial requires a fresh command and fresh PKCE/state URL.

此命令成功也不代表真实下单已验收。下一阶段仍需同一OAuth会话中的账户对账、资金流水验证、桌面逐笔确认和另行批准的最小金额订单。

Success does not establish live-order acceptance. Same-session account reconciliation, verified cash flows, desktop per-order confirmation and a separately approved minimum-size live order remain required.
