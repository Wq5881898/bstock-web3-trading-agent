# Median事务模拟账本 / Transactional Median paper ledger

后续更新 / Follow-up: 公共行情、桌面选择与受控数据恢复已接通，见[Median桌面说明](MEDIAN_DESKTOP.md)。下方是初次事务账本阶段记录，不代表当前界面仍禁用。 / Public feed, desktop selection and controlled data recovery are now integrated; see [Median desktop](MEDIAN_DESKTOP.md). The initial ledger-stage record below is historical.

阶段验证 / Milestone validation: **201 tests passed in 38.40s**; source compilation and whitespace checks passed. No account authorization or real orders. 未授权账户、未执行真实订单。

## 本轮交付 / Delivered

`MedianPaperSession`消费已验证的逐笔数据页，按原Median偏离门槛计算模拟买卖。沿用上一阶段的逐笔窗口与当前价格入样规则，不改成分钟K线，不额外增加固定持仓止损。默认模拟本金1000、单笔100、成本上限100、日净值累计亏损10、连亏3次、每日20次买入、开仓冷却60秒、双边模拟手续费各0.1%。这些是模拟单位和假设，不是真实账户余额或费率。

`MedianPaperSession` consumes validated aggregate-trade pages and simulates fills using the original Median deviation rules. It retains current-tick-inclusive rolling trade prices, not minute candles, and adds no fixed position stop. Defaults: 1,000 paper capital, 100 entry budget/cost cap, 10 daily equity-loss threshold, three losing closes, 20 daily BUY fills, 60-second entry spacing, and 0.1% simulated fees per side. These are simulated units/assumptions, not actual balances or fee tiers.

## 同一事务 / One transaction

逐笔游标、200笔指标窗口、账户资金/持仓、手续费、已实现损益、日基准、风险暂停和成交记录在同一个SQLite事务提交。只有数据库提交成功才发布新的内存状态。坏数据页不消费有效前缀，但会独立持久化数据缺口暂停。事务失败回滚成交与状态；相同数据重放由游标去重，成交表的trade_id主键提供第二层约束。

Cursor, 200-trade feature buffer, cash/position, fees, realized PnL, daily baseline, risk latch and fill records commit in one SQLite transaction. New in-memory state is published only after commit. Invalid pages do not consume valid prefixes, but persist a data-gap latch separately. Transaction failure rolls back fills and state; replay is deduplicated by cursor and additionally constrained by the fill table's trade-ID primary key.

通过数据库修订号拒绝另一个旧窗口/进程覆盖新状态；SQLite写事务串行化写入。不支持多个线程共享同一个会话对象。旧写入方收到冲突后必须重新打开并核对，不自动覆盖或重试下单。现阶段仅模拟数据库记账，不涉及外部订单的恰好一次承诺。极端断电后的耐久性仍取决于SQLite、文件系统和存储设备。

Revision checks reject stale writers while SQLite serializes write transactions. A session object belongs to one thread. A conflicting writer must reopen/review, not overwrite or automatically retry orders. This is local paper accounting, not an exactly-once guarantee for external trades. Power-loss durability still depends on SQLite, the filesystem and storage hardware.

## 风控与恢复 / Risk and recovery

日亏损按UTC日净值（现金+持仓市值，含模拟手续费和浮亏）计算；跨日使用上一有效估值作为新基准，不声称拥有精确午夜估值。触发只停买，卖出等原信号。跨日不清暂停，手动恢复不重置当日基准，不绕过仍触及的日亏损/次数限制；连亏确认恢复后清零。冷却不影响卖出。文件保存持仓成本和双边费用，加载核对现金+成本≈本金+已实现损益，仅容许Decimal舍入尾差。

UTC daily loss uses equity (cash plus marked position, including fees/unrealized PnL); rollover uses the prior valid observation, not an exact midnight valuation. Breaches block BUYs only; SELLs wait for the original signal. Rollover does not clear pauses. Manual resume preserves the daily baseline and cannot bypass active daily loss/count limits; acknowledgement clears the loss streak. Cooldown never blocks exits. Restore verifies cash + position cost ≈ initial capital + realized PnL, allowing only Decimal rounding dust.

普通手动暂停/日亏损/次数/连亏可在最新已接收成交5秒内手动检查恢复，无新成交生成。数据缺口的恢复标记故意暂不开放解除，需要下一阶段补数据核对和受控恢复流程。陈旧/未来数据只预热；恢复有效数据后可产生卖出，但不会自动解除数据缺口停买。

Ordinary manual/loss/count/streak pauses can be checked for manual resume within five seconds of the latest accepted trade, without generating a fill. Data-gap recovery remains deliberately blocked until the next reconciliation/controlled-recovery workflow. Stale/future ticks warm only; current data can generate exits without automatically clearing the data-gap BUY latch.

重启要求标的、Median和风控参数完全匹配，即使平仓也不自动迁移参数；避免换预设时无意重置历史风险。暂不支持从MTF账本迁仓、多策略共享资金、真实划转或已在其他项目中的模拟状态自动导入。

Restart requires identical symbol, Median and risk settings, even when flat; parameter migration is not automatic, avoiding accidental risk-history resets. MTF position migration, shared multi-strategy capital, actual cash flows and automatic import of other projects' paper state are unsupported.

## 验证和剩余工作 / Verification and remaining work

定向覆盖买卖闭环、重启与重复重放、浮亏停买且不强平、手动恢复、跨日次数/暂停、冷却、连亏、数据缺口、坏状态、两个写入方冲突和SQLite触发器注入的事务失败。另跑200轮/400笔模拟成交，逐笔重复重放并多次重启，核对唯一成交、累计手续费与损益。测试放宽部分计数/日亏损限制以完成连续账本压力回归，产品默认值不变。

Targeted tests cover round trips, restart/replay, unrealized-loss BUY pauses without forced exits, manual resume, day rollover, cooldown, streaks, gaps, corrupt state, competing writers and SQLite-trigger-injected transaction failure. A 200-round/400-fill run replays each tick and repeatedly restores, checking unique fills, fees and PnL. That stress test explicitly widens count/loss limits to isolate accounting continuity; product defaults are unchanged.

**仍未启用桌面Median。**还需真实公共逐笔行情分页、断线补齐、数据恢复确认、会话工作线程及桌面事件展示。当前模块没有HTTP、OAuth、MCP调用或真实交易。下一步是把公共行情读入这个模拟会话，再通过界面验收；MCP真实执行仍是另一项未完成任务。

**Desktop Median remains disabled.** Public trade pagination, reconnect catch-up, recovery acknowledgement, worker integration and desktop event rendering remain pending. This module performs no HTTP, OAuth, MCP calls or real trades. Next: connect public data to this paper session and verify the UI. MCP live execution remains a separate unfinished task.
