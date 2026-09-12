# MCP账户核对与幂等执行 / MCP reconciliation and idempotent execution

## 这一阶段交付了什么 / What this phase delivers

`execution_safety.py`补上了自动风控闸门和未来MCP执行宿主之间的离线安全契约。它本身没有MCP客户端、OAuth Token、`tools/call`或下单方法，不会访问账户或发送订单。

`execution_safety.py` adds the offline safety contract between the automated risk gate and a future MCP execution host. It has no MCP client, OAuth token, `tools/call` or submission method, and cannot access an account or place an order.

当前交付包括：

- MCP宿主核对证据：账户权限、余额、未决订单、成交记录四项读取必须全部完成；
- 默认`OBSERVE_ONLY`，只有明确绑定Agentic子账户、标的、产品和到期时间的`UNATTENDED`授权才能准备执行；
- 策略事件键、风险日、交易意图和精确下单量共同生成稳定指纹；
- 确定性`client_order_id`，同一策略事件只能准备一次；
- 强制落盘的原子JSON执行日志、启动自动恢复和严格状态迁移；
- 网络超时等不确定结果进入`UNKNOWN`，只能查单核对，禁止自动再次提交。

The delivery includes:

- MCP-host evidence requiring successful account, balance, open-order and fill reads;
- `OBSERVE_ONLY` by default, with preparation allowed only by an expiring `UNATTENDED` arming bound to the Agentic account, symbol and product;
- a stable fingerprint covering the strategy event, risk day, intent and exact order amount;
- a deterministic `client_order_id`, allowing one preparation per strategy event;
- a mandatory durable atomic JSON execution journal, automatic startup restore and strict phase transitions;
- `UNKNOWN` after an uncertain result: reconcile by read-only order lookup and never resubmit automatically.

## 未来宿主的固定顺序 / Required future host sequence

```text
策略事件 + 统一OrderIntent
        ↓
MCP只读查询 account / balances / open orders / fills
        ↓
McpReconciliationEvidence → AccountRiskSnapshot
        ↓
AutomationPolicy ALLOW/BLOCK
        ↓
ExecutionArming（账户、标的、产品、有效期）
        ↓
ExecutionJournal PREPARED
        ↓
先持久化 SUBMITTING
        ↓
未来才允许一次 MCP 下单调用
        ↓
SUBMITTED/FILLED/REJECTED；超时则 UNKNOWN → 只查单
```

`signal_key`必须来自不可变策略事件，例如已收盘K线的UTC开盘时间，或逐笔/Range策略消费到的最终成交ID。不能使用随机值，否则进程重启后无法识别同一信号；也不能只用价格，否则两个合法事件可能被误判为重复。BUY日志记录精确quote预算，SELL日志记录核对时的精确base持仓数量。

`signal_key` must identify an immutable strategy event, such as a closed candle's UTC open time or the final aggregate-trade ID consumed by a tick/Range evaluation. A random value defeats restart idempotency, while price alone can merge two legitimate events. BUY records persist the exact quote budget; SELL records persist the exact reconciled base position quantity.

## 状态规则 / State rules

- `PREPARED → SUBMITTING`必须发生在任何未来下单调用之前；
- `SUBMITTING → SUBMITTED/FILLED/REJECTED/UNKNOWN`；
- `SUBMITTED → FILLED/REJECTED/UNKNOWN`；
- `UNKNOWN`不能返回`PREPARED`或`SUBMITTING`，只能通过只读查单进入`SUBMITTED/FILLED/REJECTED`；
- `FILLED`和`REJECTED`为终态；同一指纹永远不重新准备。

`PREPARED → SUBMITTING` must be durable before any future order call. An uncertain submission can only be resolved by read-only reconciliation; it can never return to a submittable state. `FILLED` and `REJECTED` are terminal, and the same fingerprint is never prepared again.

## 仍未完成 / Still pending

当前仓库尚未实现生产MCP `tools/call`适配器、跨进程执行锁、Agent OS工具名/参数的运行时发现映射、真实Agentic子账户对账或无人值守实盘验收。现有`mcp_bridge.py`逐笔人工确认演示通道保持不变。任何API Key交易替代路线仍需先与用户讨论并取得明确允许。

The repository still has no production MCP `tools/call` adapter, cross-process execution lock, runtime mapping of discovered Agent OS tool names/arguments, real Agentic-account reconciliation or unattended live acceptance. The existing per-order-confirmed `mcp_bridge.py` demonstration remains unchanged. An API-key trading fallback still requires prior discussion and explicit user approval.
