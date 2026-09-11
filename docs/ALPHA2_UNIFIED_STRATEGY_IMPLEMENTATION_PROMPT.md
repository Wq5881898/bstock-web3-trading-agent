# 可复制到 Alpha2 工作窗口的实施 Prompt

```text
你现在在 D:\projectQ\alpha2 仓库工作。请先完整阅读：

1. D:\Agentic Wallet\bstock-web3-engine\docs\ALPHA2_UNIFIED_STRATEGY_BACKPORT_PLAN.md
2. D:\Agentic Wallet\bstock-web3-engine\docs\reference\alpha2_unified_strategy_contract_reference.py
3. D:\projectQ\alpha2\docs\binance_spot_mainstream_paper_trading_design.md
4. D:\projectQ\alpha2\docs\paper_trading_client_requirements.md
5. D:\projectQ\alpha2\src\alpha2\strategy\catalog.py
6. D:\projectQ\alpha2\src\alpha2\strategy\runtime.py
7. D:\projectQ\alpha2\src\alpha2\sim\models.py

目标：将统一策略契约、单一策略注册表、市场/产品兼容标签和插件factory实施到Alpha2，使Alpha、Spot、bStock以及未来Web3/Futures复用一套策略定义。不要从bstock-web3-engine复制出第二套生产Runtime；Alpha2的alpha2.strategy应成为规范所有者。

重要事实：Alpha与Spot目前已经共用StrategyCatalog、StrategyRuntime、Feature、Guard、PaperSimulationEngine和Repository；分开的是Provider、费率、配置与数据目录。不要错误地合并这些必须隔离的运行状态。bStock额外presets需要纳入统一注册/预设模型，但不应复制算法。

安全约束：
- 当前Alpha2工作树已有大量其他窗口的修改和未跟踪文件。先执行git status --short、git branch --show-current、git log -5 --oneline；列出与你任务重叠的文件。
- 禁止git reset --hard、checkout覆盖、clean或删除未知文件。
- 不提交或改写不属于本任务的变化。
- 不停止、重启或写入现有实时/模拟进程及其runtime配置。
- 不触发钱包、MCP授权、Quote、Spot/Web3/Futures真实订单。
- 如果目标文件存在无法安全区分的并行修改，停下来报告冲突，不要覆盖。

分阶段执行，第一轮只完成Phase 0和Phase 1：
1. 冻结现有32种策略类型和全部当前presets的清单。
2. 用现有StrategyRuntime建立golden parity fixtures，覆盖基础、Range、MTF、Guarded和Adaptive代表。
3. 新增strategy contract、StrategyDefinition和唯一StrategyRegistry。
4. 标签必须分成supported_markets(ALPHA/SPOT/BSTOCK)与supported_products(PAPER/SPOT/WEB3_SPOT/FUTURES)。
5. 首轮factory通过LegacyRuntimeAdapter调用现有StrategyRuntime，不改变公式、reason、version、freshness、锁定参数或Guard语义。
6. 保留StrategyCatalog和StrategyRuntime公开API；本轮不要一次性拆解巨型runtime.py。
7. 为全部现有策略类型登记元数据、required_features、factory和实现版本。
8. 为策略/产品不兼容建立UI筛选及运行时fail-closed校验。
9. 增加静态架构测试：Provider不定义策略，策略不依赖HTTP/MCP/钱包/DB/UI，执行器不生成信号，策略类型只有一个注册来源。
10. 跑相关测试和完整回归，报告实际测试数、失败及行为差异。

必须保留：
- Alpha与Spot独立的最后配置文件、费率、Provider、数据目录及运行记录。
- Auto推荐与买入时策略参数/版本/止损锁定。
- 持仓期间按锁定策略退出。
- Range/time generation去重、checkpoint/restart幂等。
- Guard只限制开仓、不压制卖出。
- Decimal资金、手续费和统计口径。

不要在首轮做：
- 策略公式优化或调参；
- 删除Slope或任何Alpha2现有策略；
- 接真实Futures；
- 删除legacy分支；
- 大规模移动文件。

完成首轮后先给出：修改文件、注册覆盖率、golden parity结果、完整测试结果、仍存在的差异、下一阶段建议。确认无行为变化后，再讨论Phase 2调用方迁移。
```
