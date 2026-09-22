# MCP 会话确认与结果闭环 / MCP Session Confirmation and Result Loop

`mcp_session_execution.py`把持久化策略候选与现有 MCP 安全组件连接起来，覆盖 `MCP-AUTO-002/003/005/006/008/010` 的离线交接边界。它不实现网络、OAuth 或 MCP 客户端；实际工具调用仍由当前已授权的 Codex Binance MCP 宿主完成。

`mcp_session_execution.py` connects durable strategy candidates to the existing MCP safety components and covers the offline handoff boundary for `MCP-AUTO-002/003/005/006/008/010`. It implements no network, OAuth, or MCP client; actual tool calls remain owned by the already-authorized Codex Binance MCP host.

## 严格流程 / Strict flow

```text
READY candidate
  -> fresh account/rules preflight
  -> exact per-order confirmation (15 seconds)
  -> durable SUBMITTING
  -> credential-free one-shot submission ticket
  -> existing Codex MCP host performs exactly one write
  -> terminal or UNKNOWN sanitized receipt
  -> complete fill ledger first
  -> execution journal and durable session state
```

关键保证 / Key guarantees:

- 候选的账户指纹、计划 ID、信号指纹、标的、方向和精确金额必须全部一致。
- 错误或过期确认不会生成票据。
- 正确确认被消费后先持久化 `SUBMITTING`，再写最多 15 秒有效的一次性票据。
- 票据不包含确认短语、UID、Token、API Key、密码或私钥。
- 票据写盘中断会把执行日志和会话转入只查单恢复，不允许重发。
- `UNKNOWN` 只能继续按确定性客户端订单 ID 查询；不能重新提交，也不能改走 API/Wallet。
- 终态导入要求七项完整读取和完整成交/订单分页；成交账本先成功写盘，执行日志和会话才推进。
- 用户停止时，如果票据已经产生，会话停在 `STOPPING`，直到终态或 UNKNOWN 被安全记录。

- Account fingerprint, plan ID, signal fingerprint, symbol, side, and exact amount must all match.
- Invalid or expired confirmation cannot create a ticket.
- Exact confirmation durably enters `SUBMITTING` before a one-shot ticket valid for at most 15 seconds is written.
- Tickets contain no confirmation phrase, UID, token, API key, password, or private key.
- Interrupted ticket persistence moves both journal and session to lookup-only recovery; resubmission is prohibited.
- `UNKNOWN` permits deterministic-client-ID lookup only and cannot switch to API/Wallet.
- Terminal import requires all seven reads plus complete trade/order pagination; the fill ledger commits before journal/session advancement.
- If stop is requested after ticket creation, the session remains `STOPPING` until terminal or UNKNOWN evidence is safely recorded.

## 验证边界 / Acceptance boundary

本阶段使用注入式假宿主和文件回执完成故障测试，没有访问 Binance 账户，也没有调用 `spot.newOrder`。真实调用只允许在 Phase 4 中由用户对当笔订单明确确认后执行。

This phase uses an injected fake host and file receipts for fault testing. It accessed no Binance account and called no `spot.newOrder`. A real call is allowed only in Phase 4 after explicit confirmation for that specific order.
