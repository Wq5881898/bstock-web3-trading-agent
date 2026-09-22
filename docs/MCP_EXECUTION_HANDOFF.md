# MCP文件化执行交接 / MCP file-safe execution handoff

## 目的 / Purpose

本边界把本地策略/风控进程与持有Binance Agent OS授权的Codex宿主分开。它不会创建OAuth客户端、保存Token或自行联网，也不会因为出现策略信号就直接生成可下单参数。

This boundary separates the local strategy/risk process from the Codex host that owns the existing Binance Agent OS authorization. It creates no OAuth client, stores no token and performs no network call. A strategy signal alone never creates dispatchable order arguments.

## 两类文件 / Two artifacts

1. `McpSpotOrderPlan` schema v3是短时候选计划。它绑定已登记账户、币对、策略ID、稳定事件时间、信号指纹、方向和候选金额；状态固定为`AWAITING_HOST_PREFLIGHT`。它没有最终客户端订单ID，不能直接传给`spot.newOrder`。
2. `McpSpotSubmissionTicket`是确认后的单次提交票据。只有新鲜账户证据、Spot规则、自动风控、跨进程锁和执行日志全部通过，用户的精确确认被消费，而且`SUBMITTING`已经原子落盘后才能生成。票据最多有效15秒，包含确定性客户端订单ID，但不包含确认短语、UID或凭据。

1. Schema-v3 `McpSpotOrderPlan` is a short-lived candidate bound to the enrolled account, symbol, registered strategy, immutable event time, signal fingerprint, side and candidate amount. Its status is `AWAITING_HOST_PREFLIGHT`; it has no final client order ID and cannot be passed directly to `spot.newOrder`.
2. `McpSpotSubmissionTicket` is the post-confirmation one-shot artifact. It can exist only after fresh evidence, Spot rules, policy, process lock and journal checks pass, the exact confirmation is consumed, and `SUBMITTING` is durably persisted. It lasts no more than 15 seconds and contains a deterministic client order ID, but no confirmation phrase, UID or credential.

## 固定顺序 / Required sequence

```text
统一策略信号
  → schema-v3候选计划（账户绑定 + 稳定信号指纹）
  → 7项MCP只读预检和完整分页
  → 账户指纹、余额、持仓、挂单、手续费、规则、盘口核对
  → OrderIntent + AutomationPolicy + ExecutionJournal PREPARED
  → 桌面逐笔确认弹窗（15秒、一次性短语）
  → 重新核对新鲜证据和精确金额
  → 原子写入 SUBMITTING
  → 最多15秒的单次提交票据
  → Codex宿主schema门禁并调用一次 spot.newOrder
  → 严格结果回写；不确定即 UNKNOWN
  → UNKNOWN只允许spot.getOrder(origClientOrderId)，禁止重发
  → 完整成交重读并同步成交/权益风险账本
```

The confirmation phrase never enters the ticket or durable logs. The host must validate the ticket expiry, exact tool, exact arguments, account binding and live tool schema immediately before the single call.

## 故障语义 / Failure semantics

| 状态 / State | 允许动作 / Allowed action |
|---|---|
| `AWAITING_HOST_PREFLIGHT` | 只读预检；不能下单 / read-only preflight only |
| `PREPARED` | 展示和消费当前确认；不能调用MCP写工具 / show and consume current confirmation only |
| `SUBMITTING` | 使用当前未过期票据调用一次；任何不确定性转`UNKNOWN` / one call with the current ticket; uncertainty becomes `UNKNOWN` |
| `UNKNOWN` | 仅按确定性`origClientOrderId`调用`spot.getOrder` / lookup by deterministic client ID only |
| `SUBMITTED` | 查询终态，不允许重发 / poll terminal state; never resubmit |
| `FILLED/REJECTED` | 终态；同一策略事件不能重新准备 / terminal; the same signal cannot be prepared again |

进程在`SUBMITTING`时崩溃，重启后必须先转`UNKNOWN`再查单。票据过期、宿主不可用、schema变化、回执不合法或账户指纹变化都不能推断“订单没有提交”，也不能静默切换API Key或Agentic Wallet。

If the process dies in `SUBMITTING`, restart changes it to `UNKNOWN` before lookup. An expired ticket, unavailable host, schema drift, invalid result or changed account fingerprint never proves that no order was submitted and never authorizes an API-key or Agentic Wallet fallback.

## 当前边界 / Current boundary

本轮完成候选计划、确认拆分、原子`SUBMITTING`、单次票据、票据读写和离线故障测试。尚未把桌面策略事件自动接到此流程，也没有调用真实`spot.newOrder`。下一阶段需要实现宿主终态回执导入、完整成交重读和账本同步，然后才能进行明确确认的最小金额真实验收。

This revision implements candidate plans, split confirmation/submission, durable `SUBMITTING`, one-shot ticket persistence and offline failure tests. Desktop strategy events are not yet wired to it and no live `spot.newOrder` was called. The next phase is strict host-result import, full fill refresh and ledger synchronization before any explicitly confirmed minimum-size live acceptance.
