# Spot成交账本 / Spot fill ledger

## 范围 / Scope

`spot_accounting.py`提供纯本地成交回放和持久化检查点，没有网络、OAuth或下单功能。它与MCP账户对账共用一套持仓成本算法。实际宿主仍须核验Agentic UID、读取完整分页成交、对照余额和订单，再把结果送入账本；声明`history_complete=True`本身不是历史完整性的证明。

The local accounting module replays fills and persists checkpoints without network, OAuth or order submission. MCP position reconciliation shares its cost algorithm. The host must verify the Agentic UID, fetch all history pages, reconcile balances/orders and then sync the ledger. A caller's completeness flag is not independent proof of completeness.

## 规则 / Rules

- Decimal记账；按成交时间、成交ID稳定排序。重复ID、异常数字、错误币对、负数和无法解释的卖出拒绝入账。
- 买入基础币手续费扣除净持仓，报价币手续费增加成本；卖出基础币手续费增加出库数量，报价币手续费减少净收入。按移动平均成本计算已实现盈亏。
- BNB等第三资产非零手续费暂时拒绝，不能当作零费用。需要可靠汇率和独立资产流水后才能支持。
- 成交是唯一入账来源。部分成交后撤单仍记已发生的成交，不使用FILLED/CANCELED状态替代成交记录。
- 完整历史重放幂等；旧成交缺失或变更拒绝同步。文件绑定账户引用、币对和基础/报价资产，不能换账户复用。
- 跨进程锁保护读取/写入；先刷盘临时文件并原子替换，再更新内存。失败保留旧账本，允许再次同步。临时文件可被下次同步覆盖；不保证所有文件系统在断电时的目录持久性。

Decimal amounts, stable timestamp/ID ordering and strict validation prevent ambiguous accounting. Base/quote fees affect net quantity, cost and sale proceeds; realized PnL uses average cost. Nonzero third-asset fees fail closed. Actual fills, including partially filled canceled orders, are the source of truth. Complete-history replay is idempotent and rejects missing/changed prior fills. Account/instrument binding, an OS lock and replace-before-memory persistence protect checkpoints; directory durability under power loss is not guaranteed.

## 使用 / Usage

```python
from pathlib import Path
from bstock_web3.spot_accounting import SpotFillLedger

# trades must come from verified, complete MCP pagination, not order receipts.
with SpotFillLedger(Path("runtime/spot-fills.json"),
                    account_ref="verified-agentic-account",
                    symbol="BTCUSDT", base_asset="BTC", quote_asset="USDT") as ledger:
    result = ledger.sync(trades, history_complete=True)
    print(result.quantity, result.cost, result.realized_pnl)
```

文件包含账户引用和成交记录，只保存在本机runtime，不应加入公开GitHub；不保存Token、密钥或授权链接。账本路径不得指向其他程序的状态文件。

Checkpoint files contain account references and fills. Keep them local under runtime, never in the public repository, and never point a ledger at another application's state file. No token, key or authorization URL is stored.

## 尚未闭环 / Not yet closed-loop

已新增独立的[Spot权益风险账本](SPOT_EQUITY_RISK.md)，用UTC基准、买一价和净入金/出金生成权益亏损，并从本账本的完整成交推导开仓次数和连亏次数。但当前MCP宿主尚未接入经过验证的完整资金流水，桌面读取也只返回汇总，未自动把完整成交写入本账本；真实执行器与桌面接线仍待完成。不会因此开启无人值守或自动真实下单。

The separate [Spot equity-risk ledger](SPOT_EQUITY_RISK.md) now combines UTC baselines, best-bid valuation and net cash flows, while complete fills derive entry/loss-streak counters. The MCP host still lacks a verified complete cash-flow source, and the desktop returns only a reduced summary rather than persisting all fills. Live-executor and desktop wiring remain pending; this enables neither unattended trading nor automatic live orders.

## 测试 / Tests

24项新增离线测试覆盖基础/报价手续费、部分卖出、同时间排序、无效成交、重复ID、持久化/重启、账户错配、锁竞争、不完整历史、旧成交变化、写盘失败回滚及重试。不使用真实账户或订单。

24 new offline tests cover fees, partial sales, equal-timestamp ordering, invalid/duplicate fills, persistence/restart, identity mismatch, competing locks, incomplete/changed history and persistence-failure retry. No live account or order is used.
