# 当前收尾状态 / Current closeout status

## 已完成 / Delivered

- 统一策略注册表和Spot/Web3/Futures适用标签；MTF、Median和Range家族共用接口，Slope未加入。
- 公共行情、历史下载/聚合/回放、桌面模拟盘、K线展示、参数编辑和持久化。
- 默认单笔100、累计亏损10停买、卖出继续等待策略信号、手动恢复等本地风控。
- Spot成交账本、权益风险、执行互斥、确定性客户端订单ID和UNKNOWN只查单恢复。
- 现有Codex Binance MCP宿主的无凭据读取请求与订单计划交接。
- 脱敏宿主回执、显式首次账户指纹登记、后续账户漂移拒绝和桌面导入。
- 新回执格式已对既有Agentic账户完成一次真实BTCUSDT只读闭环；7项读取、完整分页、脱敏和严格导入均通过。
- 已读取并验证真实`spot.newOrder/spot.getOrder` schema；修复JSON number金额适配和条件查询字段兼容，未调用写工具。
- Agentic Wallet作为彼此独立的BSC执行通道，不作为MCP失败时的自动回退。

- Unified strategy registry with Spot/Web3/Futures tags; MTF, Median and Range share one interface, with Slope excluded.
- Public data, history/aggregation/replay, desktop paper trading, candles, editable settings and persistence.
- Local controls including 100-unit entries, cumulative-loss 10 BUY latch, strategy-led exits and manual resume.
- Spot ledger/equity risk, execution lock, deterministic client IDs and lookup-only UNKNOWN recovery.
- Credential-free handoff to the existing Codex Binance MCP host.
- Sanitized host receipts, explicit first fingerprint enrollment, account-drift rejection and desktop import.
- The new receipt format completed one live BTCUSDT read loop against the existing Agentic account; all seven reads, complete pagination, sanitization and strict import passed.
- Live `spot.newOrder/spot.getOrder` schemas were read and validated; JSON-number amount adaptation and conditional lookup compatibility were fixed without invoking a write tool.
- Agentic Wallet remains an independent BSC transport, never an automatic MCP fallback.

## 已纠正 / Corrected

此前误把桌面程序设计成新的Binance OAuth Agent。真实授权证明Binance不支持该自建Agent身份，而现有Codex MCP宿主早已成功连接并使用Agentic账户。错误的OAuth、回调监听、Client Metadata、Pages和直接HTTP入口均已撤下；这次纠正没有访问账户或提交订单。详见[MCP宿主桥接](MCP_HOST_BRIDGE.md)。

The desktop was previously and incorrectly treated as a new Binance OAuth Agent. Live authorization showed that identity was unsupported, while the existing Codex MCP host had already connected to and used the Agentic account. OAuth/callback/client-metadata/Pages/direct-HTTP entry points were removed. This correction accessed no account and placed no order. See [MCP host bridge](MCP_HOST_BRIDGE.md).

## 尚待验收 / Remaining acceptance

1. Codex宿主自动拾取请求/返回回执的持续编排。
2. 策略信号、风险闸门、宿主确认、最小订单、终态和账本回写的完整闭环。
3. 持续真实行情/断线恢复和桌面长时运行。
4. 多币种真实账户级风险；当前仍按单标的原型失败关闭。

1. Sustained orchestration for Codex to pick up requests and return receipts automatically.
2. Full signal/risk/host-confirmation/minimum-order/terminal-state/ledger loop.
3. Sustained live data, reconnect recovery and long-running desktop acceptance.
4. Multi-symbol live account risk; the current prototype remains fail-closed for one symbol.

任何API Key或其他无人值守接口都不在当前授权范围，必须先讨论并取得用户明确允许。

Any API-key or other unattended interface is outside current authorization and requires prior discussion and explicit user approval.
