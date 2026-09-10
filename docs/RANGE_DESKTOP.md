# 固定Range策略与桌面模拟 / Fixed Range strategies and desktop paper mode

## 当前范围 / Scope

桌面策略页现已提供 **Range EMA** 与 **Range Median**。两者都仅支持`paper`，消费Binance公共`aggTrades`逐笔成交，并按价格移动幅度生成Range bar；不会用分钟K线冒充Range bar，也不会访问账户、MCP或发送真实订单。本轮明确不加入Slope、自适应Range或后台自动选参。

The Strategies tab now offers **Range EMA** and **Range Median**. Both are paper-only and build price-movement bars from Binance public `aggTrades`. Minute candles are never substituted for Range bars, and these modes do not access an account, MCP or real orders. Slope, adaptive Range and background parameter selection are explicitly outside this iteration.

## Range bar语义 / Range-bar semantics

`range_bps`可选5、10、20、30、50、75、100或150 bps，默认20 bps。首次成交建立未完成bar；价格越过相对当前开盘价的固定比例时才收盘。一次跳价可以完成多根bar，越过的中间bar标记为合成价格路径，但不伪造新的市场成交。触发成交的成交量归入最后新建的未完成bar，已完成bar仅保留触发前累积成交量，与原alpha2实现一致。

`range_bps` supports 5, 10, 20, 30, 50, 75, 100 and 150 bps; the default is 20 bps. The first trade opens a partial bar. A bar closes only after price crosses the configured fraction from its current open. One jump may close several bars; intermediate bars describe the crossed price path but do not invent market trades. The triggering trade's volume belongs to the new partial bar, matching the alpha2 implementation.

每一页必须满足聚合成交ID连续、时间不倒退。首次页、显式追赶页、未来或超过5秒的成交只用于预热，不触发买卖。缺口、冲突重放、无效数值或单笔异常跨越超过1000根bar会失败关闭并锁住买入；原策略卖出仍可执行。游标、未完成bar、最近60根完成bar、递归EMA、最后已评估代次、账本和风控在同一SQLite事务中提交。

Every page requires contiguous aggregate-trade IDs and nondecreasing timestamps. The first page, explicit catch-up pages, future trades and trades older than five seconds only advance warmup state. Gaps, a conflicting latest replay, invalid numbers or an abnormal tick crossing over 1,000 bars fail closed and latch BUYs; valid strategy exits remain eligible. Cursor, partial bar, latest 60 completed bars, recursive EMAs, consumed generation, funds and risk commit in one SQLite transaction.

## 策略 / Strategies

- **Range EMA**：默认20 bps、EMA 15/45、买卖阈值0。至少完成45根Range bar后，只在新完成bar上评估；快线高于慢线×(1+买入阈值)买入，快线不高于慢线×(1−卖出阈值)卖出。
- **Range Median**：默认20 bps、窗口20、偏离0.003。可选窗口5、10、20、30、40或60；只使用已完成Range bar收盘价。收盘价低于中位数×(1−偏离)买入，高于中位数×(1+偏离)卖出。

- **Range EMA:** defaults to 20 bps, EMA 15/45 and zero entry/exit thresholds. It warms through 45 completed Range bars and evaluates only a newly completed generation. BUY requires fast above slow × (1 + entry threshold); SELL requires fast at or below slow × (1 − exit threshold).
- **Range Median:** defaults to 20 bps, window 20 and deviation 0.003. Windows are 5, 10, 20, 30, 40 or 60, using completed Range-bar closes only. BUY is below median × (1 − deviation); SELL is above median × (1 + deviation).

一次跳价完成多根bar时，只对最终代次评估一次，重启不会重放已消费信号。Range EMA、Range Median和逐笔Median各自使用独立SQLite文件和1000单位模拟本金；风险上限不在这些账本之间合并，因此它们不是账户级总风险控制。

When one jump closes multiple bars, only the final generation is evaluated once, and restart does not replay a consumed signal. Range EMA, Range Median and tick Median each use a separate SQLite file and 1,000-unit paper balance. Their limits are not consolidated, so they are not account-level risk controls.

## 桌面和恢复 / Desktop and recovery

预设格式为v4，保存MTF、逐笔Median与Range参数；完整v1/v2/v3文件仅在内存中迁移，除非人工点击保存，否则不改写。状态文件分别为`<symbol>_paper_range_ema.sqlite`和`<symbol>_paper_range_median.sqlite`。重开已有账本会保持/设置买入暂停，必须在行情连续且最新后人工恢复；恢复不清零累计亏损、次数或日基准。

Preferences schema v4 stores MTF, tick-Median and Range inputs. Exact v1/v2/v3 files migrate in memory and are not rewritten without an explicit Save. State files are `<symbol>_paper_range_ema.sqlite` and `<symbol>_paper_range_median.sqlite`. Reopening an existing ledger preserves/latches BUY pause and requires manual resume after contiguous fresh data. Resume never resets cumulative loss, counts or the daily baseline.

K线标签仍展示1m/5m时间K线，仅用于观察；Range信号只来自逐笔构造的Range bar。账户页展示相应SQLite模拟余额、持仓及最近100笔成交，不是Binance真实账户报表。

The Candles tab still displays 1m/5m time candles for observation only; Range signals come exclusively from tick-built Range bars. The Account tab shows that strategy's SQLite paper balance, position and latest 100 fills, not a Binance account statement.

## 验证边界 / Verification boundary

自动化覆盖精确多bar跳价、成交量归属、EMA/Median信号、预热与陈旧数据、冲突/缺口、损坏检查点、异常跳价上限、事务回滚、重启卖出、手动恢复、桌面参数保存和独立状态路径。原生桌面验收使用合成数据且不连接账户。仍需在活跃市场时段进行持续公共行情观察；在另行设计并明确授权MCP真实执行前，Range保持纯模拟。

Automated coverage includes exact multi-bar jumps, volume ownership, EMA/Median signals, warmup/staleness, conflicts/gaps, corrupt checkpoints, abnormal-jump limits, transactional rollback, restart exits, manual resume, desktop persistence and isolated state paths. Native desktop acceptance uses synthetic data without an account. Sustained public-feed observation during an active market remains pending; Range stays paper-only until MCP live execution is separately designed and explicitly authorized.

本轮证据：Python 3.11完整回归256项通过（46.58秒）；原生桌面650轮刷新、38次故障注入通过（13.36秒）。Range EMA/Median页面截图位于被Git忽略的`runtime/desktop-acceptance/1789070913827878300/`。这些数字是本地加速模拟，不是实盘验收。

This iteration passed 256 Python 3.11 tests in 46.58 seconds and a native-desktop run of 650 refreshes with 38 injected failures in 13.36 seconds. Range EMA/Median screenshots are under git-ignored `runtime/desktop-acceptance/1789070913827878300/`. These are accelerated local simulations, not live acceptance.
