# 统一策略与多交易场所架构 / Unified strategies and multi-venue execution

## 结论 / Decision

所有策略只实现一次。MTF EMA、逐笔Median、固定/防御/Auto/Adaptive Range统一注册在`strategy_registry.py`，通过`strategy_contract.py`接收规范化市场输入并输出`StrategyEvaluation`。策略不知道订单最终发往Binance Spot、Agent OS MCP、Agentic Wallet还是未来的Futures适配器。

Every strategy is implemented once. MTF EMA, tick Median and fixed/guarded/Auto/Adaptive Range are registered in `strategy_registry.py`. Through `strategy_contract.py`, they consume normalized market input and emit `StrategyEvaluation`. A strategy does not know whether execution will use Binance Spot, Agent OS MCP, Agentic Wallet or a future derivatives adapter.

```text
公共行情 / Market data
  ├─ 已收盘K线 / closed candles
  └─ 连续aggTrades / contiguous aggregate trades
                 │
                 ▼
统一策略注册表 + Regime/EntryGuard
Unified strategy registry + Regime/EntryGuard
                 │ StrategyEvaluation
                 ▼
统一风控和持仓锁定 / Shared risk and position lock
                 │ OrderIntent
       ┌─────────┼──────────┐
       ▼         ▼          ▼
 Agent OS MCP  Web3 Wallet  Futures adapter (future)
```

## 统一与差异 / Shared versus venue-specific

始终复用：指标、Range bar、信号、Auto候选选择、开仓参数锁定、Regime、FastDrop、累计亏损暂停、冷却、审计字段。交易场所适配器只负责产品符号、数量/精度、保证金与杠杆约束、报价、下单、撤单、终态和成交回报。

Always shared: indicators, Range bars, signals, Auto candidate selection, buy-time parameter locking, Regime, FastDrop, cumulative-loss latches, cooldowns and audit fields. A venue adapter owns only product symbols, size/precision, margin and leverage constraints, quote/submit/cancel, terminal status and fill reports.

`execution_contract.py`定义`SPOT`、`WEB3_SPOT`和`FUTURES`产品，以及统一的`OrderIntent`/`ExecutionReceipt`/`ExecutionAdapter`。当前策略均为long/flat：BUY映射为`OPEN_LONG`，SELL映射为`CLOSE_LONG + reduce_only`。未来若要做空，需要扩展统一目标仓位模型，不应复制现有策略。

`execution_contract.py` defines `SPOT`, `WEB3_SPOT` and `FUTURES` products plus common `OrderIntent`, `ExecutionReceipt` and `ExecutionAdapter` contracts. Current strategies are long/flat: BUY maps to `OPEN_LONG`, while SELL maps to `CLOSE_LONG + reduce_only`. Supporting shorts later requires extending the shared target-position model, not cloning strategies.

## Regime边界 / Regime boundary

`regime.py`是交易场所无关的完整核心状态机：使用已收盘1m/5m数据识别趋势、突破、震荡、紊乱和未知状态，包含进出确认迟滞、持久检查点以及30秒/2分钟FastDrop。Guard只阻止开仓，不能压制已有持仓的策略卖出。它从标准K线和逐笔结构读取数据，因此现货和合约可共用。

`regime.py` is the venue-neutral core state machine. It classifies trend, breakout, range, disorder and unknown conditions from closed 1m/5m data, with transition hysteresis, durable checkpoints and 30-second/2-minute FastDrop protection. Guards block entries only and never suppress a held position's strategy exit. Standard candle and tick inputs let Spot and Futures share it.

## 当前限制 / Current boundary

统一接口和Futures扩展点已经存在，但尚未实现或授权真实Futures适配器，也没有设置杠杆、保证金模式、强平距离或交易所合约精度。当前新增策略仍为模拟模式；真实执行继续遵循MCP优先，只有在MCP不能满足且经过明确讨论授权后才考虑API适配器。

The common interface and Futures extension point exist, but no real Futures adapter is implemented or authorized. Leverage, margin mode, liquidation distance and derivatives precision are not configured. The added strategies remain paper-only. Real execution remains MCP-first; an API adapter is considered only after MCP is shown insufficient and the user explicitly approves it.
