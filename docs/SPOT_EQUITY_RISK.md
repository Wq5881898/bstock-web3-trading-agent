# Spot权益风险账本 / Spot equity-risk ledger

## 目的 / Purpose

`spot_equity_risk.py`把真实Spot账户的保守权益定义为：

```text
quote_total + base_quantity × best_bid
```

它使用买一价而不是卖一价估算持仓可变现价值，并用已验证的净资金流调整入金和出金，输出非负的UTC日累计权益亏损。`spot_accounting.fill_risk_stats`从完整成交历史推导当日开仓订单数、最近开仓时间和连续亏损卖出订单数。`build_local_risk_metrics`把两者合并成执行策略所需的`LocalRiskMetrics`。

Conservative equity is quote total plus base quantity valued at best bid. Verified net deposits/withdrawals are neutralized, producing a nonnegative UTC-day equity loss. Complete fills derive daily entry orders, last-entry time and consecutive losing sell orders. `build_local_risk_metrics` joins these verified values for the execution policy.

## 失败关闭规则 / Fail-closed rules

- 首次基准不会自动建立。操作者必须确认当前账户、完整资金流水和当前权益，显式传入`operator_confirmed=True`。
- 每次观察必须严格推进时间，并且`risk_day`必须等于时间戳的UTC日期。
- 资金流水要求稳定唯一ID、毫秒时间和报价币计价的有符号Decimal金额：流入为正，流出为负；零金额、重复ID、未来记录拒绝。
- 已记录资金流在后续完整历史中缺失或改变时拒绝更新。未知币种流转必须先按可审计汇率换算，不能猜测。
- 跨日时以前一次真实观察权益作为新基准；程序离线期间的市场跳空会被保守计入新日亏损，不会用重启后的当前值抹掉。
- 入金不会伪装成盈利，出金不会伪装成亏损。写盘成功后才更新内存，跨进程锁阻止两个执行宿主同时维护同一账本。
- 首次基准之前发生的损失无法恢复，因此首次确认只是从当前时刻开始监控，不证明当日早些时候没有亏损。

The first baseline requires explicit operator confirmation. Observation time must advance and match the UTC risk day. Cash flows require immutable IDs, timestamps and signed quote-valued Decimal amounts. Missing, changed, duplicate, future or ambiguous flows fail closed. Day rollover uses the last observed equity, conservatively including offline price gaps. Persistence completes before memory changes and an OS lock enforces one owner. The first baseline starts monitoring now; it cannot reconstruct losses earlier that day.

## 仍需宿主完成 / Host obligations

当前Agent OS只读白名单没有经过验证的完整资金划转历史来源。因此，生产宿主必须在以下两种方式之一得到验证后才能提供`history_complete=True`：

1. 发现并验证官方MCP资金流水读取工具及其完整分页；或
2. 冻结该专用Agentic子账户的人工转入/转出，并通过期初报价币余额、完整成交和当前总余额重建且核对每一笔变动。

Until a complete official transfer-history tool is discovered and schema-validated, a production host must either provide such verified pagination or enforce and independently reconcile a no-manual-transfer operating period. A caller-provided Boolean alone is not proof. The current desktop does not yet perform this orchestration.

本模块没有网络、OAuth、Token存储或下单能力，不会开启无人值守实盘。

This module has no network, OAuth, token storage or submission capability and does not enable unattended live trading.
