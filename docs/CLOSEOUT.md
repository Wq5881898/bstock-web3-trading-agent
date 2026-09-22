# 当前收尾状态 / Current Closeout Status

收尾范围服从[自动交易产品基准](AUTONOMOUS_TRADING_PRODUCT_BASELINE.md)和[MCP + Agentic 收尾总计划](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md)。当前唯一真实交易主链是：现有 Codex Binance MCP 宿主 → 现有 Agentic 子账户。每个真实非只读动作按照 Binance Agentic MCP 规则逐笔确认。

Closeout follows the [product baseline](AUTONOMOUS_TRADING_PRODUCT_BASELINE.md) and [MCP + Agentic master plan](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md). The only real-trading path is the existing Codex Binance MCP host to the existing Agentic sub-account. Every real non-read action is confirmed individually under the Binance Agentic MCP contract.

## 已完成 / Delivered

- 统一策略注册表和 Spot/Web3/Futures 适用标签；MTF、Median 和 Range 家族共用接口，Slope 未加入。
- 公共行情、历史下载/聚合/回放、桌面模拟盘、K 线展示、参数编辑和持久化。
- 默认单次 100 USDT、累计亏损 10 USDT 停买、SELL 信号继续和手动恢复等本地风控。
- Spot 成交账本、权益风险、执行互斥、确定性客户端订单 ID 和 `UNKNOWN` 只查单恢复。
- 现有 Codex Binance MCP 宿主的无凭据读取请求、订单候选计划和严格宿主回执。
- 既有 Agentic 子账户完成一次真实 BTCUSDT 七项只读闭环、完整分页、脱敏和严格导入。
- 真实 `spot.newOrder`/`spot.getOrder` schema 已读取验证，没有在该次验收调用写工具。
- 候选计划、逐笔确认、短时一次性提交票据、终态/UNKNOWN 回执和账本优先导入已完成离线验收。
- Agentic Wallet 保持独立 BSC 通道，绝不作为 MCP 失败回退。

- Unified strategy registry with Spot/Web3/Futures tags; MTF, Median, and Range share one interface, with Slope excluded.
- Public market data, history/aggregation/replay, desktop paper trading, candles, editable settings, and persistence.
- Local risk controls: default 100-USDT entries, 10-USDT cumulative-loss BUY latch, continued SELL signals, and manual resume.
- Spot fill ledger, equity risk, execution lock, deterministic client order IDs, and lookup-only `UNKNOWN` recovery.
- Credential-free read requests, candidate order plans, and strict host receipts for the existing Codex Binance MCP host.
- One live seven-part BTCUSDT read loop against the existing Agentic sub-account, with complete pagination, sanitization, and strict import.
- Live `spot.newOrder`/`spot.getOrder` schemas were validated without calling a write tool in that acceptance run.
- Candidate, per-order confirmation, expiring one-shot ticket, terminal/UNKNOWN receipt, and ledger-first import flows passed offline acceptance.
- Agentic Wallet remains an independent BSC route and never serves as MCP fallback.

## 已纠正 / Corrected

1. 自建 Binance OAuth Agent 路线此前已撤回；本地程序不会重新登录、监听回调或持久化 MCP Token。
2. 独立 Binance Spot API 自动下单原型被错误描述为已获批准。该路线现已从产品入口、文档和当前源码中撤回；不创建或使用 API Key。
3. 原“零确认真实写入”验收与 Binance Agentic MCP 官方规则冲突，已改为持续自动监测/决策/风控，加逐笔真实写操作确认。

1. The custom Binance OAuth Agent path was already removed; the local application does not reauthenticate, listen for callbacks, or persist MCP tokens.
2. A separate Binance Spot API auto-order prototype was incorrectly represented as approved. It is removed from product entry points, active documentation, and current source; no API key is created or used.
3. The old zero-confirmation write criterion conflicts with the official Binance Agentic MCP contract. Acceptance now covers continuous market/strategy/risk automation plus per-action confirmation for real writes.

## 尚待完成 / Remaining

1. `MCP-AUTO-001/004/005/007/008` 的持久化候选会话和故障注入已经通过离线验收。
2. `MCP-AUTO-002/003/006` 的候选、宿主预检、当笔确认、一次性票据、终态/UNKNOWN和账本导入已完成离线闭环；桌面操作接线及真实宿主验收仍待完成。
3. `MCP-AUTO-009`：完成一笔经确认的策略 BUY、一笔经确认的策略 SELL，以及 24 小时小额监督运行。
4. `MCP-AUTO-010`：保持 MCP-only 架构守卫持续通过。
5. 多标的、Futures、Telegram 和其他外围功能不属于本次收尾阻塞项。

1. The durable candidate session and fault injection for `MCP-AUTO-001/004/005/007/008` pass offline acceptance.
2. The candidate, host preflight, per-action confirmation, one-shot ticket, terminal/UNKNOWN, and ledger import flow for `MCP-AUTO-002/003/006` passes offline; desktop wiring and real-host acceptance remain.
3. `MCP-AUTO-009`: one confirmed strategy BUY, one confirmed strategy SELL, and a 24-hour supervised small-balance run.
4. `MCP-AUTO-010`: keep the MCP-only architecture guard passing.
5. Multi-symbol, Futures, Telegram, and peripheral work do not block this closeout.

所有真实账户动作都必须在执行当笔单独确认；总体计划批准不等于订单批准。

Every real-account action requires a separate confirmation at execution time; approval of the overall plan is not approval of an order.
