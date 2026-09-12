# 自动交易风控契约 / Automated execution policy

## 当前交付 / Current delivery

`automation_policy.py`实现交易场所无关、但不具备下单能力的自动执行闸门。它接收统一`OrderIntent`和由MCP/交易场所完成核对的`AccountRiskSnapshot`，只返回`ALLOW/BLOCK`。模块不包含HTTP、OAuth、MCP `tools/call`、API Key或钱包调用，因此本阶段不会触发真实交易。

`automation_policy.py` is a venue-neutral authorization gate with no order transport. It consumes a common `OrderIntent` plus an `AccountRiskSnapshot` already reconciled by the MCP/venue host and returns only `ALLOW/BLOCK`. It contains no HTTP, OAuth, MCP `tools/call`, API key or wallet operation, so this phase cannot place a real order.

## 已确定默认值 / Agreed defaults

- 单笔预算 / order budget: `100` quote units;
- 日累计净值亏损 / daily cumulative equity loss: `10` quote units;
- 最大持仓成本 / maximum position cost: `100`;
- 每日最多开仓 / daily entries: `20`;
- 连续亏损 / consecutive losing exits: `3`;
- 开仓冷却 / entry cooldown: `60s`;
- 账户快照最大年龄 / account snapshot age: `15s`.

触发累计亏损、次数或连亏门槛后锁定新买入；持仓卖出仍然等待并执行原策略SELL信号。卖出不会被BUY风险锁压制，但仍要求账户快照新鲜、已核对、账户可交易、无未决订单且确有持仓。

Cumulative loss, count or losing-streak thresholds latch new BUYs. An existing position continues to wait for and follow the strategy's SELL signal. A BUY latch never suppresses the exit, but the exit still requires a fresh reconciled tradable account, no pending order and an actual position.

## 人工恢复和通知 / Manual recovery and notification

暂停跨进程重启持久化。只有显式人工恢复才能清除；恢复不会重置风险数字，若当前日累计亏损、次数或连亏仍触线，恢复失败关闭。`notify_operator`只在首次进入暂停时返回true，可供桌面非阻塞弹窗去重；Telegram仍未接入。

The latch survives process restart and clears only after an explicit manual-resume request. Resume does not reset risk values and fails closed while loss/count/streak limits remain active. `notify_operator` is true only on the first latch transition for a deduplicated nonmodal desktop popup. Telegram remains out of scope.

## MCP接线边界 / MCP wiring boundary

下一阶段的MCP宿主适配器必须先查询Agentic子账户、交易权限、余额、持仓、未决订单和成交，形成新鲜快照；通过闸门后才能提交，并以客户端订单ID实现幂等，随后查询终态。当前没有生产适配器调用此闸门，也没有取消逐笔确认或启用无人值守实盘。

The next MCP-host adapter must first query the Agentic sub-account, permissions, balance, position, pending orders and fills to construct a fresh snapshot. Only an allowed decision may be submitted, with client-order-id idempotency followed by terminal reconciliation. No production adapter currently calls this gate, and per-order confirmation has not been removed or unattended live trading enabled.
