# 统一策略引擎回迁 Alpha2 设计 / Unified Strategy Backport Plan

## 1. 结论

可以回迁，但不应把 `bstock-web3-engine` 整套覆盖到 Alpha2，也不应在 Alpha2 内再放一份并行策略运行器。正确做法是把本项目已经验证的“统一契约、注册表、产品标签和执行边界”回迁为 Alpha2 `strategy/` 的公共基础设施，再用兼容适配器逐步接管 Alpha2 现有策略。

本设计只修改当前仓库中的文档和参考代码；没有修改 `D:\projectQ\alpha2`。

## 2. 对 Alpha2 现状的核查

截至核查时，Alpha2 当前工作树有大量已修改和未跟踪文件，分支为 `codex/bstock-spot-adapter`。另一个实施窗口必须保存这些工作，禁止 reset、checkout 覆盖或批量清理。

Alpha 与 Spot 并不是两套完整策略内核：

- 共用 `alpha2.strategy.catalog.StrategyCatalog`；
- 共用 `alpha2.strategy.runtime.StrategyRuntime`；
- 共用 Feature、Regime、Guard、`PaperSimulationEngine`、Repository 和统计；
- 分开的是行情 Provider、市场标识、费率、最后配置文件和数据目录；
- `alpha2.bstock.strategy_presets` 仍以附加预设存在；
- `StrategyRuntime` 通过大量 `if strategy_type` 分派32类策略，注册信息、指标要求、执行逻辑和UI规则仍有重复来源。

当前目录动态生成约421个共享预设，bStock另有22个附加预设，合计443个预设、32种策略类型。这些数字来自当前未提交工作树，不应当作稳定发布版本号。

因此回迁目标不是“合并 Alpha 策略和 Spot 策略代码”，而是：

1. 让所有市场只拥有一套策略定义和运行协议；
2. 把预设（参数实例）与策略实现（算法类型）分开；
3. 用标签声明适用市场和产品；
4. 保持 Alpha、Spot、bStock 各自运行配置与数据隔离；
5. 在不改变既有信号的前提下逐步拆解巨型 Runtime。

## 3. 目标模型

```text
Alpha Provider ─┐
Spot Provider  ─┼─> Normalized Market/Feature Context
bStock Provider ┘                  │
                                   ▼
                        Unified Strategy Registry
                        + StrategyPlugin contract
                        + locked-position params
                                   │ decision
                                   ▼
                         Shared Guard / Risk Policy
                                   │ intent
                    ┌──────────────┼──────────────┐
                    ▼              ▼              ▼
                  Paper        Binance Spot   Agent OS/Web3
                                                     │
                                              Futures (future)
```

### 3.1 必须区分的两组标签

不能只使用一个 `SPOT/FUTURES` 字段，因为 Alpha 行情来源和订单产品不是同一维度：

- `supported_markets`: `ALPHA`, `SPOT`, `BSTOCK`；
- `supported_products`: `PAPER`, `SPOT`, `WEB3_SPOT`, `FUTURES`。

例如：

- 一个纯价格EMA策略可以支持全部市场以及全部long/flat产品；
- 依赖Alpha特有数据的策略只标记`ALPHA`；
- 依赖资金费率、做空或合约持仓的策略只标记`FUTURES`；
- bStock策略若使用标准K线，不必标记为bStock专属；参数预设可以用`universe_tags={BSTOCK}`限制展示。

### 3.2 策略定义与策略预设分离

`StrategyDefinition`描述算法：

- `strategy_type`及实现版本；
- 输入类型；
- 支持市场/产品标签；
- 参数校验器；
- 所需指标；
- Runtime factory；
- 是否需要锁定入场参数和持久状态。

`StrategyPreset`只描述一个参数实例：名称、分类、参数、默认止损、适用资产标签。421/443是预设数量，不应生成421份算法对象代码。

### 3.3 输出契约不能直接照搬简化版

Alpha2当前`StrategyDecision`还包含`version`、`trailing_stop`、`strategy_type`、`strategy_params`和`entry_guard_allowed`。回迁时必须保留这些字段。参考代码中的`UnifiedStrategyDecision`以Alpha2语义为准，不能为了匹配本项目的较小`StrategyEvaluation`而丢字段。

参考实现：[alpha2_unified_strategy_contract_reference.py](reference/alpha2_unified_strategy_contract_reference.py)。

## 4. Alpha2建议文件结构

```text
src/alpha2/strategy/
├─ contract.py              # Context、Decision、Protocol
├─ definition.py            # StrategyDefinition、标签和参数Schema
├─ registry.py              # 唯一注册表、兼容性查询、factory
├─ presets.py               # 公共预设；原catalog.py兼容门面
├─ legacy_adapter.py        # 旧StrategyRuntime过渡适配器
├─ plugins/
│  ├─ ema.py
│  ├─ t3.py
│  ├─ median.py
│  ├─ range.py
│  ├─ mtf.py
│  ├─ breakout.py
│  ├─ ichimoku.py
│  └─ adaptive.py
└─ runtime.py               # 最终成为薄编排器，暂时保留旧入口
```

不要在`data/providers/binance_spot.py`、`bstock/`或`execution/`中定义替代策略。Provider只标准化行情；执行器只处理产品规则和订单状态。

## 5. 分阶段实施

### Phase 0：冻结基线

1. 记录当前分支、`git status --short`和完整测试命令；
2. 不处理已有脏文件，不覆盖另一个窗口的修改；
3. 构建覆盖32种策略类型的固定fixture与golden decision结果；
4. 固定Auto推荐输入、随机种子、时间和本地策略payload。

### Phase 1：只加契约和注册表

1. 新增`contract.py`、`definition.py`、`registry.py`；
2. 注册全部现有策略类型的元数据；
3. factory先返回`LegacyRuntimeAdapter`；
4. `StrategyCatalog`继续保持公开API，但数据源改为registry + presets；
5. UI改为读取registry元数据，不再维护策略类型判断副本。

本阶段不得改变任何策略公式、阈值、Signal reason、version或freshness语义。

### Phase 2：调用方切到统一入口

按以下顺序迁移：

1. 离线单元测试与回放；
2. `PaperTradingSession`；
3. bStock optimized replay/backtest monitor；
4. 桌面UI；
5. 最后才考虑任何真实执行路径。

保留`StrategyRuntime.on_market()`兼容门面，内部转调registry runtime。禁止一次性修改所有调用方后再测试。

### Phase 3：逐族抽离实现

建议顺序：

1. EMA、T3、Median、Slope基础族；
2. Range及其Guarded/Auto/Adaptive；
3. MTF、Ichimoku、RSI、Z-Score、Breakout；
4. Auto、Median Auto、ADX/Resonance/FastDrop组合。

每迁移一族：旧实现与新插件对同一输入逐事件比对；通过后删除旧`if`分支。Slope在当前bStock项目被有意排除，但Alpha2原有Slope不能因回迁而删除。

### Phase 4：执行产品接入

策略只产出decision。统一Risk层结合`market/product`标签审批，然后生成订单intent。Paper、Spot、Agent OS/Web3、未来Futures分别实现执行适配器。Futures未获得单独授权前只能注册接口和paper实现。

## 6. 必须保持的状态语义

- Range generation和时间bar freshness不能重复触发；
- Auto推荐在买入时锁定`strategy_type/params/version/stop`；
- 持仓卖出读取锁定参数，不读取最新推荐；
- Guard只阻止新开仓，不压制策略卖出；
- 检查点必须包括generation、adaptive选择、EntryGuard和Regime状态；
- 恢复后重放相同事件不能产生重复订单；
- Decimal资金与费用口径不因策略接口迁移而改变。

## 7. 验收测试

### 行为等价

- 32种策略类型全部注册；
- 当前全部预设均能构建；
- 对冻结事件流，旧/新decision逐字段一致；
- `buy/sell/reason/version/trailing_stop/strategy_type/strategy_params/entry_guard_allowed`全部比较；
- 所需指标集合一致；
- Auto和Median Auto选择结果一致；
- Range、时间bar和逐笔freshness一致；
- 重启检查点前后结果一致。

### 市场隔离

- 同一规范输入经Alpha/Spot Provider后产生相同策略结果；
- 不兼容标签在UI筛选和Risk/Intent生成前都被拒绝；
- Alpha和Spot配置文件仍分别保存；
- 不混写行情、运行、费用和统计结果。

### 静态架构

- Provider不得导入具体策略插件；
- 策略插件不得导入HTTP、MCP、钱包、数据库或UI；
- 执行适配器不得计算指标或策略信号；
- 策略类型只在registry注册一次；
- 禁止新增第二个`StrategyRuntime`实现。

### 回归门槛

- Alpha2既有完整测试通过；
- 代表性Alpha、Spot、bStock回放结果在既定Decimal容差内一致；
- 无真实订单、无授权变化、无运行配置覆盖；
- 第一阶段至少影子运行，确认一致后才切换默认路径。

## 8. 风险与回滚

最大风险不是指标公式，而是freshness、Auto策略锁定、Guard授权、恢复去重和费用口径。建议设置临时开关`strategy_runtime_backend=legacy|registry`，默认`legacy`；golden parity通过后切`registry`，保留一个发布周期后再删除旧路径。任何决策差异必须先定位，不能用放宽断言解决。

## 9. 明确不做

- 本设计不修改Alpha2当前文件；
- 不把当前项目9种策略误当作Alpha2全部策略；
- 不合并Alpha与Spot的运行配置或历史数据；
- 不启用Futures真实交易；
- 不重写策略公式或趁重构调参；
- 不清理Alpha2脏工作树。

