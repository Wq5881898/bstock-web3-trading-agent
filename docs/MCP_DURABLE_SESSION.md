# MCP 持久化策略会话 / Durable MCP Strategy Session

`mcp_session.py`实现 `MCP-AUTO-001/004/005/007/008` 的本地持久化核心。它接收统一策略产生的 `SignalDecision` 和已经由支持宿主核对的 `McpReconciliationEvidence`，只生成无凭据 MCP 候选文件；模块没有网络客户端、OAuth、API Key 或订单提交方法。

`mcp_session.py` implements the local durable core for `MCP-AUTO-001/004/005/007/008`. It consumes unified `SignalDecision` values and host-verified `McpReconciliationEvidence`, then emits credential-free MCP candidate files only. It has no network client, OAuth, API key, or submission method.

## 固定绑定 / Immutable binding

会话创建时固定：

- 已登记 Agentic 账户的本地引用和 SHA-256 指纹；
- Spot 标的；
- 统一策略 ID 和策略配置摘要；
- 风控配置摘要。

恢复时任一绑定不同都会拒绝加载。状态文件不保存 UID、Token、密码或 API Key。

The session binds the enrolled Agentic account reference/fingerprint, Spot symbol, unified strategy ID/config digest, and risk-config digest. Any drift rejects restore. The state stores no UID, token, password, or API key.

## 状态和故障恢复 / State and recovery

```text
STOPPED -> STARTING -> RUNNING <-> BUY_PAUSED
                         |
                         v
              WAITING_CONFIRMATION
                         |
            reject/expire/cancel -> RUNNING or BUY_PAUSED

stop with pending candidate -> STOPPING -> STOPPED
interrupted durable transition -> RECOVERY_ONLY
```

- 所有状态使用临时文件、`fsync`和原子替换写盘。
- 同一策略 ID + 稳定事件时间最多生成一个候选。
- 候选先持久化 `RESERVING`，再原子写候选文件，最后标记 `READY`。
- 在 `RESERVING` 中崩溃或写盘失败会进入 `RECOVERY_ONLY`，不会重复生成。
- 风控达到默认累计亏损 10 USDT 后进入 `BUY_PAUSED`；BUY 被拒绝，SELL 候选仍可生成。
- 手动恢复会重新检查新鲜账户快照，不能绕过仍然有效的亏损、次数或连亏限制。
- 有待确认候选时停止进入 `STOPPING`，候选明确取消/拒绝/过期后才进入 `STOPPED`。

- State uses temp-file writes, `fsync`, and atomic replacement.
- One strategy ID plus stable event time can create at most one candidate.
- Candidate creation persists `RESERVING`, atomically writes the candidate, then marks it `READY`.
- A crash/write failure during `RESERVING` enters `RECOVERY_ONLY` and cannot regenerate the action.
- The default 10-USDT cumulative-loss latch blocks BUY while allowing SELL candidates.
- Manual resume rechecks a fresh account snapshot and cannot bypass active limits.
- Stop with a pending candidate enters `STOPPING` and reaches `STOPPED` only after explicit cancellation/rejection/expiry.

## 当前边界 / Current boundary

这是持久化协调核心，不是联网交易程序。后续 Phase 2 才把候选与现有逐笔确认、一次性提交票据、MCP 宿主调用和终态回执串成闭环。总体计划批准不等于任何真实订单批准。

This is a durable coordination core, not a networked trader. Phase 2 connects candidates to the existing per-action confirmation, one-shot ticket, MCP host call, and terminal receipt flow. Approval of the overall plan is not approval of a real order.
