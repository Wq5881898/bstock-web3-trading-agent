# 当前收尾状态 / Current closeout status

产品收尾目标和验收优先服从[自动交易产品基准](AUTONOMOUS_TRADING_PRODUCT_BASELINE.md)。逐笔确认、票据和桌面演练是诊断安全组件，不是最终业务流程。

Closeout is governed by the [Autonomous Trading Product Baseline](AUTONOMOUS_TRADING_PRODUCT_BASELINE.md). Per-order confirmation, tickets and desktop rehearsal are diagnostic safety components, not the final product flow.

## 已完成 / Delivered

- 统一策略注册表和Spot/Web3/Futures适用标签；MTF、Median和Range家族共用接口，Slope未加入。
- 公共行情、历史下载/聚合/回放、桌面模拟盘、K线展示、参数编辑和持久化。
- 默认单笔100、累计亏损10停买、卖出继续等待策略信号、手动恢复等本地风控。
- Spot成交账本、权益风险、执行互斥、确定性客户端订单ID和UNKNOWN只查单恢复。
- 现有Codex Binance MCP宿主的无凭据读取请求与订单计划交接。
- 脱敏宿主回执、显式首次账户指纹登记、后续账户漂移拒绝和桌面导入。
- 新回执格式已对既有Agentic账户完成一次真实BTCUSDT只读闭环；7项读取、完整分页、脱敏和严格导入均通过。
- 已读取并验证真实`spot.newOrder/spot.getOrder` schema；修复JSON number金额适配和条件查询字段兼容，未调用写工具。
- 订单候选计划升级为严格schema v3：绑定已登记账户和稳定信号指纹，不能直接提交；确认后先原子写入SUBMITTING，再生成最多15秒的单次提交票据。
- 新增严格终态/UNKNOWN执行回执：终态必须完成查单和7项只读刷新、完整分页及订单/成交/余额交叉核对；先幂等同步成交账本，再推进执行日志。
- Agentic Wallet作为彼此独立的BSC执行通道，不作为MCP失败时的自动回退。

- Unified strategy registry with Spot/Web3/Futures tags; MTF, Median and Range share one interface, with Slope excluded.
- Public data, history/aggregation/replay, desktop paper trading, candles, editable settings and persistence.
- Local controls including 100-unit entries, cumulative-loss 10 BUY latch, strategy-led exits and manual resume.
- Spot ledger/equity risk, execution lock, deterministic client IDs and lookup-only UNKNOWN recovery.
- Credential-free handoff to the existing Codex Binance MCP host.
- Sanitized host receipts, explicit first fingerprint enrollment, account-drift rejection and desktop import.
- The new receipt format completed one live BTCUSDT read loop against the existing Agentic account; all seven reads, complete pagination, sanitization and strict import passed.
- Live `spot.newOrder/spot.getOrder` schemas were read and validated; JSON-number amount adaptation and conditional lookup compatibility were fixed without invoking a write tool.
- Candidate plans now use strict schema v3, bind the enrolled account plus a stable signal fingerprint, and cannot be submitted directly; confirmation durably enters SUBMITTING before a ≤15-second one-shot ticket is emitted.
- Strict terminal/UNKNOWN execution receipts now require lookup plus all seven read refreshes, complete pagination and order/fill/balance cross-reconciliation; the fill ledger is synchronized idempotently before the execution journal advances.
- Agentic Wallet remains an independent BSC transport, never an automatic MCP fallback.

## 已纠正 / Corrected

此前误把桌面程序设计成新的Binance OAuth Agent。真实授权证明Binance不支持该自建Agent身份，而现有Codex MCP宿主早已成功连接并使用Agentic账户。错误的OAuth、回调监听、Client Metadata、Pages和直接HTTP入口均已撤下；这次纠正没有访问账户或提交订单。详见[MCP宿主桥接](MCP_HOST_BRIDGE.md)。

The desktop was previously and incorrectly treated as a new Binance OAuth Agent. Live authorization showed that identity was unsupported, while the existing Codex MCP host had already connected to and used the Agentic account. OAuth/callback/client-metadata/Pages/direct-HTTP entry points were removed. This correction accessed no account and placed no order. See [MCP host bridge](MCP_HOST_BRIDGE.md).

## 尚待验收 / Remaining acceptance

1. 决定满足`AUTO-002`的长期执行宿主；当前Codex MCP宿主要求非GET操作逐笔确认。
2. 一次启动后的策略信号、风控、自动下单/平仓、终态和账本回写闭环。
3. 单标的24小时小额实盘、断线和恢复验收。
4. 多币种、Futures和其他外围功能不属于本次收尾阻塞项。

1. Select a long-running execution host that can satisfy `AUTO-002`; the current Codex MCP host requires confirmation before non-GET operations.
2. Complete the once-started signal/risk/automatic entry-exit/terminal/ledger loop.
3. Pass a 24-hour small single-symbol live, disconnect and recovery acceptance run.
4. Multi-symbol, Futures and other peripheral work do not block this closeout.

API Key路线不在当前授权范围。若MCP无法满足`AUTO-002`，必须停止并先讨论、取得用户明确允许；不能把产品目标降级为逐笔确认。

The API-key route remains unauthorized. If MCP cannot satisfy `AUTO-002`, stop and obtain explicit approval before proceeding; do not downgrade the product to per-order confirmation.
