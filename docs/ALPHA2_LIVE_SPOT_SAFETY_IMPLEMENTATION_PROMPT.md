# 给 Alpha2 项目窗口的实施提示 / Alpha2 Implementation Prompt

> 这是交接提示，不是对当前窗口或 Alpha2 的自动实施授权。请在 Alpha2 项目窗口先讨论/确认目标阶段与执行接口；没有批准前只做只读核查和离线实现。

可复制以下内容到 `D:\projectQ\alpha2` 的项目对话：

```text
请先完整阅读 D:\Agentic Wallet\bstock-web3-engine\docs\ALPHA2_LIVE_SPOT_SAFETY_HANDOFF.md，并只读核对本项目当前分支、git status、StrategyRegistry、PaperTradingSession、SpotExecutionAdapter、Repository 与测试。另一个窗口正在维护 Alpha2；保留所有既有改动，不 reset/checkout/覆盖。

目标不是复制 bStock 的 MCP 客户端或第二套策略引擎，而是让 Alpha2 现有策略决策在未来有一个安全、独立的 Spot 实盘执行边界。先给出差距清单、具体接口/数据模型、测试计划和分阶段提交范围。明确区分：已有 paper 行为；本仓库 HEAD 的离线安全契约；bStock 尚未提交的实验；Alpha2 尚未实现的实盘能力。

优先 P0/P1：冻结 32 类策略的代表性 golden 决策；明确“会话累计权益亏损”而非 UTC 日亏损；设计 LiveFill/EquityBaseline/OrderIntent/ExecutionJournal 的传输无关契约和离线故障测试。不得直接改策略公式、复制 runtime/、创建 API Key/账户、复用 Codex OAuth、调用私有下单接口或提交真实订单。Alpha2 的 SpotExecutionAdapter 目前只是骨架，不能当作已验收执行器。

若需要进入 P2/P3/P4，先逐阶段报告测试和阻塞。P3 最多只读影子运行。P4 前必须让我明确决定目标产品、账户、授权接口和真实交易权限；Binance MCP/API/Wallet 不可静默切换。每笔真实操作仍需符合所选接口的授权与确认规则。

重点验收：同一策略事件/重新报价/重启不重复下单；SUBMITTING 前落盘；未知结果只查单；部分成交后取消仍记已成交；基础/报价/第三资产手续费；完整成交分页与余额核对；会话亏损停 BUY、合法 SELL 继续、手动恢复不重置风险；过期账户快照不消耗可重评的闭合事件。优先把这些变成 Alpha2 自己的测试，不照搬 bStock 的 15 秒文件协议。
```

源文件和测试、已知限制以及 P0–P4 验收矩阵均见[移交主文档](ALPHA2_LIVE_SPOT_SAFETY_HANDOFF.md)。
