# 统一策略与多交易场所架构 / Unified strategies and multi-venue execution

## 结论 / Decision

所有策略只实现一次。MTF EMA、逐笔Median、固定/防御/Auto/Adaptive Range统一注册在`strategy_registry.py`，通过`strategy_contract.py`接收规范化市场输入并输出`StrategyEvaluation`。策略不知道订单最终发往Binance Spot、Agent OS MCP、Agentic Wallet还是未来的Futures适配器。

Every strategy is implemented once. MTF EMA, tick Median and fixed/guarded/Auto/Adaptive Range are registered in `strategy_registry.py`. Through `strategy_contract.py`, they consume normalized market input and emit `StrategyEvaluation`. A strategy does not know whether execution will use Binance Spot, Agent OS MCP, Agentic Wallet or a future derivatives adapter.

## 可移植策略库 / Portable strategy library

策略核心没有HTTP、MCP、钱包、数据库或桌面依赖。其他Python程序可直接安装本包，或连同包目录复制以下统一策略模块：`strategy.py`、`strategy_contract.py`、`strategy_registry.py`、`median_ticks.py`、`range_ticks.py`、`range_guard.py`、`range_auto.py`、`regime.py`。宿主程序只需提供规范化的K线快照或aggTrade行，并从统一运行时读取`StrategyEvaluation`。推荐安装包或复制整个策略模块集合，不要只复制某个具体策略文件，以免重新产生分叉。

The strategy core has no HTTP, MCP, wallet, database or desktop dependency. Another Python application can install this package, or copy the unified strategy module set together: `strategy.py`, `strategy_contract.py`, `strategy_registry.py`, `median_ticks.py`, `range_ticks.py`, `range_guard.py`, `range_auto.py` and `regime.py`. The host supplies normalized candle snapshots or aggregate-trade rows and consumes `StrategyEvaluation`. Install the package or copy the complete strategy set; do not fork an individual strategy file.

外部程序不需要构造`BStockEngineConfig`。统一注册表为每个策略保存配置类型、默认配置factory和runtime factory，可直接调用：

```python
from bstock_web3.strategy_registry import (
    build_portable_strategy_runtime,
    default_strategy_config,
)

config = default_strategy_config("range-median")
runtime = build_portable_strategy_runtime("range-median", "NVDABUSDT", config)
```

External applications do not need `BStockEngineConfig`. Every registry entry owns its config type, default-config factory and runtime factory. `build_portable_strategy_runtime(strategy_id, symbol, config)` is the standalone construction API; the old `build_strategy_runtime(engine_config, symbol)` remains only as this application's compatibility adapter.

2026-09-12安装级验收将项目构建为wheel、使用`--no-deps`安装到隔离目录，然后由没有项目开发依赖的干净Python 3.11进程以`-I`模式导入。全部9类策略均通过`default_strategy_config()`与`build_portable_strategy_runtime()`构建成功。验收产物位于被Git忽略的`runtime/portable-wheel-acceptance/20260912/`；该测试只验证策略库打包与构建，不读取行情或账户。

The 2026-09-12 installation acceptance built a wheel, installed it with `--no-deps` into an isolated directory, and imported it under `python -I` using a clean Python 3.11 installation without the project's development dependencies. All nine strategy types were constructed through `default_strategy_config()` and `build_portable_strategy_runtime()`. Ignored evidence lives under `runtime/portable-wheel-acceptance/20260912/`. This verifies packaging and strategy construction only; it accessed neither market data nor accounts.

## 产品标签 / Product tags

每个`StrategySpec`都带有`supported_products`，可使用`SPOT`、`WEB3_SPOT`、`FUTURES`任意组合。`compatible_strategy_ids()`用于界面筛选，`ensure_strategy_supports()`在生成执行意图前做强制校验。当前9个策略只使用价格/成交/K线并采用long/flat语义，因此都标记兼容三类产品；真实产品能否下单仍由对应执行适配器和授权决定。未来依赖资金费率、做空或合约持仓的策略应只标记`FUTURES`，无需复制注册表或执行器。

Every `StrategySpec` has `supported_products`, containing any combination of `SPOT`, `WEB3_SPOT` and `FUTURES`. `compatible_strategy_ids()` filters user interfaces, while `ensure_strategy_supports()` enforces compatibility before an execution intent is created. All nine current strategies use only price/trade/candle inputs and long/flat semantics, so they are tagged for all three products; actual order availability still depends on the corresponding adapter and authorization. A future strategy that requires funding, shorts or derivatives positions should be tagged `FUTURES` only, without cloning the registry or executor.

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
