# 固定Range策略与桌面模拟 / Fixed Range strategies and desktop paper mode

## 当前范围 / Scope

桌面策略页现已提供固定 **Range EMA/Median**、**Range Median EMA/P90防御**、**Range EMA Guarded**、**Range Auto**、**Range Guarded Auto** 与 **Range Median Adaptive**。它们都仅支持`paper`，消费Binance公共`aggTrades`逐笔成交，并按价格移动幅度生成Range bar；不会用分钟K线冒充Range bar，也不会访问账户、MCP或发送真实订单。按产品决策，Slope仍不加入。

The Strategies tab now offers fixed **Range EMA/Median**, **Range Median EMA/P90 Guarded**, **Range EMA Guarded**, **Range Auto**, **Range Guarded Auto** and **Range Median Adaptive**. All are paper-only and build price-movement bars from Binance public `aggTrades`. Minute candles are never substituted for Range bars, and these modes do not access an account, MCP or real orders. Slope remains excluded by product decision.

## Range bar语义 / Range-bar semantics

`range_bps`可选5、10、20、30、50、75、100或150 bps，默认20 bps。首次成交建立未完成bar；价格越过相对当前开盘价的固定比例时才收盘。一次跳价可以完成多根bar，越过的中间bar标记为合成价格路径，但不伪造新的市场成交。触发成交的成交量归入最后新建的未完成bar，已完成bar仅保留触发前累积成交量，与原alpha2实现一致。

`range_bps` supports 5, 10, 20, 30, 50, 75, 100 and 150 bps; the default is 20 bps. The first trade opens a partial bar. A bar closes only after price crosses the configured fraction from its current open. One jump may close several bars; intermediate bars describe the crossed price path but do not invent market trades. The triggering trade's volume belongs to the new partial bar, matching the alpha2 implementation.

每一页必须满足聚合成交ID连续、时间不倒退。Range首次请求使用接口单页上限1000笔预热；首次页、显式追赶页、未来或超过5秒的成交只用于预热，不触发买卖。缺口、冲突重放、无效数值或单笔异常跨越超过1000根bar会失败关闭并锁住买入；原策略卖出仍可执行。游标、未完成bar、最近60根完成bar、递归EMA、最后已评估代次、账本和风控在同一SQLite事务中提交。

Every page requires contiguous aggregate-trade IDs and nondecreasing timestamps. The initial Range request uses the endpoint's 1,000-trade maximum for warmup; the first page, explicit catch-up pages, future trades and trades older than five seconds only advance warmup state. Gaps, a conflicting latest replay, invalid numbers or an abnormal tick crossing over 1,000 bars fail closed and latch BUYs; valid strategy exits remain eligible. Cursor, partial bar, latest 60 completed bars, recursive EMAs, consumed generation, funds and risk commit in one SQLite transaction.

## 策略 / Strategies

- **Range EMA**：默认20 bps、EMA 15/45、买卖阈值0。至少完成45根Range bar后，只在新完成bar上评估；快线高于慢线×(1+买入阈值)买入，快线不高于慢线×(1−卖出阈值)卖出。
- **Range Median**：默认20 bps、窗口20、偏离0.003。可选窗口5、10、20、30、40或60；只使用已完成Range bar收盘价。收盘价低于中位数×(1−偏离)买入，高于中位数×(1+偏离)卖出。

- **Range EMA:** defaults to 20 bps, EMA 15/45 and zero entry/exit thresholds. It warms through 45 completed Range bars and evaluates only a newly completed generation. BUY requires fast above slow × (1 + entry threshold); SELL requires fast at or below slow × (1 − exit threshold).
- **Range Median:** defaults to 20 bps, window 20 and deviation 0.003. Windows are 5, 10, 20, 30, 40 or 60, using completed Range-bar closes only. BUY is below median × (1 − deviation); SELL is above median × (1 + deviation).

- **Range Auto**：并行维护10/20/30 bps（可编辑）Range EMA 8/21，按`abs(fast/slow−1)`选择强度最高者。只有选中候选出现未消费代次时才产生信号；买入时锁定为固定Range EMA参数，持仓期间不重新选择。
- **Range Median Adaptive**：默认并行20 bps/窗口20/偏离0.0035与30 bps/窗口60/偏离0.004，选择`(median−close)/close`最大的有效候选；买入时锁定固定Range Median参数。
- **Range EMA Guarded / Guarded Auto**：在固定EMA或Auto信号外增加只影响买入的30秒/2分钟快速下跌保护，以及完成分钟EMA15/45的下行代理。策略卖出不被Guard压制。缺少分钟上下文时遵循alpha2 EntryGuard边界：快速下跌数据仍检查，但不因缺少regime本身封锁。

- **Range Auto:** maintains editable 10/20/30-bps Range EMA 8/21 candidates in parallel and selects the largest `abs(fast/slow−1)`. It acts only on an unconsumed generation of the selected candidate, then locks that fixed Range EMA configuration for the open position.
- **Range Median Adaptive:** defaults to 20-bps/window-20/deviation-0.0035 and 30-bps/window-60/deviation-0.004 candidates, selecting the largest `(median−close)/close`; a BUY locks the corresponding fixed Range Median configuration.
- **Range EMA Guarded / Guarded Auto:** add BUY-only 30-second/2-minute FastDrop checks and a completed-minute EMA15/45 downtrend proxy around fixed EMA or Auto. Strategy exits are never suppressed. If minute context is unavailable, FastDrop remains active but missing regime context alone does not block, matching alpha2's EntryGuard boundary.

## 高振幅防御 / High-amplitude guarded Median

防御候选保持alpha2推荐默认：Range20、Median60、偏离0.2%，完成分钟EMA20/50入场守护，`clamp(P90振幅×3, 1%, 5%)`动态止损，并在买入时锁定。EMA20与EMA50连续下行时只封锁新买入；持仓仍保留原Median卖出。价格达到锁定止损后，仅在当前分钟EMA20低于EMA50时退出；止损后冷却900秒。可选的方向回撤门控、confirmed-down模式及更宽灾难止损也保留在配置模型中，但不是默认开启项。

The guarded candidate keeps alpha2's recommended defaults: Range20, Median60, 0.2% deviation, completed-minute EMA20/50 entry protection and a buy-time-locked `clamp(P90 amplitude × 3, 1%, 5%)` stop. Consecutively falling EMA20/50 blocks new entries only; held positions retain the original Median exit. The locked stop exits only while current EMA20 is below EMA50, followed by a 900-second cooldown. Optional directional-drawdown gates, confirmed-down mode and a wider catastrophe stop remain available in the configuration model but are disabled by default.

一次跳价完成多根bar时，只对最终代次评估一次，重启不会重放已消费信号。Range EMA、Range Median和逐笔Median各自使用独立SQLite文件和1000单位模拟本金；风险上限不在这些账本之间合并，因此它们不是账户级总风险控制。

When one jump closes multiple bars, only the final generation is evaluated once, and restart does not replay a consumed signal. Range EMA, Range Median and tick Median each use a separate SQLite file and 1,000-unit paper balance. Their limits are not consolidated, so they are not account-level risk controls.

## 桌面和恢复 / Desktop and recovery

预设格式为v6，保存MTF、逐笔Median、固定/防御/自动Range参数；完整v1至v5文件仅在内存中迁移，除非人工点击保存，否则不改写。每个策略使用`<symbol>_paper_<strategy>.sqlite`独立状态文件。重开已有账本会保持/设置买入暂停，必须在行情连续且最新后人工恢复；恢复不清零累计亏损、次数或日基准。

Preferences schema v6 stores MTF, tick-Median and fixed/guarded/automatic Range inputs. Exact v1–v5 files migrate only in memory until Save is explicitly clicked. Every strategy uses an isolated `<symbol>_paper_<strategy>.sqlite` state file. Reopening a ledger preserves/latches BUY pause and requires manual resume after contiguous fresh data. Resume never resets cumulative loss, counts or the daily baseline.

K线标签仍展示1m/5m时间K线，仅用于观察；Range信号只来自逐笔构造的Range bar。账户页展示相应SQLite模拟余额、持仓及最近100笔成交，不是Binance真实账户报表。

The Candles tab still displays 1m/5m time candles for observation only; Range signals come exclusively from tick-built Range bars. The Account tab shows that strategy's SQLite paper balance, position and latest 100 fills, not a Binance account statement.

## 验证边界 / Verification boundary

自动化覆盖精确多bar跳价、成交量归属、EMA/Median信号、预热与陈旧数据、冲突/缺口、损坏检查点、异常跳价上限、事务回滚、重启卖出、手动恢复、桌面参数保存和独立状态路径。原生桌面验收使用合成数据且不连接账户。仍需在活跃市场时段进行持续公共行情观察；在另行设计并明确授权MCP真实执行前，Range保持纯模拟。

Automated coverage includes exact multi-bar jumps, volume ownership, EMA/Median signals, warmup/staleness, conflicts/gaps, corrupt checkpoints, abnormal-jump limits, transactional rollback, restart exits, manual resume, desktop persistence and isolated state paths. Native desktop acceptance uses synthetic data without an account. Sustained public-feed observation during an active market remains pending; Range stays paper-only until MCP live execution is separately designed and explicitly authorized.

本轮证据：Python 3.11完整回归268项通过；原生桌面650轮刷新、38次故障注入通过（12.47秒）。固定、防御、Auto和Adaptive页面截图位于被Git忽略的`runtime/desktop-acceptance/1789078484391283800/`。这些数字是本地加速模拟，不是实盘验收。

Latest validation passed 268 Python 3.11 tests and 650 native-desktop refreshes with 38 injected failures in 12.47 seconds. Fixed, guarded, Auto and Adaptive screenshots are under git-ignored `runtime/desktop-acceptance/1789078484391283800/`. These are accelerated local simulations, not live acceptance.

2026-09-10公共行情复测：Range EMA与Range Median都成功读取NVDAB最新逐笔成交，游标前进、市场状态正常、K线页各返回239根。1000笔初始预热仅形成2根20 bps Range bar，未达到EMA的45根或Median的20根要求，因此0笔模拟成交；这是正常预热，不是放宽门槛的理由。报告位于`runtime/tick-public-smoke/range-ema-1789074677580056400/`和`range-median-1789074690040502200/`。

Public-feed recheck on 2026-09-10: both Range EMA and Range Median read current NVDAB aggregate trades successfully, advanced the cursor, observed an available market and returned 239 chart candles. The initial 1,000 trades formed only two 20-bps Range bars, below the 45-bar EMA and 20-bar Median warmups, so no paper fill occurred. This is expected warmup and not a reason to weaken thresholds. Reports are under the two git-ignored runtime paths listed above.

同日新增四种策略也完成各一轮NVDAB公共行情冒烟：EMA Guarded生成5根、Auto/Guarded Auto各并行保留22根、Median Adaptive并行保留8根Range bar；游标一致推进到938090，K线各239根，0笔模拟成交，且报告均明确`account_access=false`、`real_orders=false`。

The four added modes also completed one NVDAB public-feed evaluation each: EMA Guarded built 5 bars, Auto and Guarded Auto retained 22 parallel bars each, and Median Adaptive retained 8. All advanced consistently to cursor 938090 with 239 chart candles and zero paper fills; every report records `account_access=false` and `real_orders=false`.

可用以下命令进行最多20轮、有界的公共行情模拟观察；它只访问公开目录、市场状态、K线和逐笔成交，报告写入被Git忽略的`runtime/tick-public-smoke/`：

```powershell
.venv\Scripts\python scripts\tick_public_smoke.py --strategy range-ema --symbol NVDAB --evaluations 2
.venv\Scripts\python scripts\tick_public_smoke.py --strategy range-median --symbol NVDAB --evaluations 2
.venv\Scripts\python scripts\tick_public_smoke.py --strategy range-auto --symbol NVDAB --evaluations 2
.venv\Scripts\python scripts\tick_public_smoke.py --strategy range-guarded-auto --symbol NVDAB --evaluations 2
.venv\Scripts\python scripts\tick_public_smoke.py --strategy range-median-adaptive --symbol NVDAB --evaluations 2
```

Use these commands for a bounded public-feed paper observation of up to 20 evaluations. They access only public catalog/status/candle/trade endpoints and write reports under git-ignored `runtime/tick-public-smoke/`.
