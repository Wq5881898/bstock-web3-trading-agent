# 原型收尾与实盘验收 / Prototype closeout and live acceptance

## 已交付 / Delivered

- 单一策略注册表、便携运行时、产品兼容标签，包含MTF、Median和Range家族；不包含Slope。
- 桌面模拟监控、策略参数编辑/保存、真实公共K线显示及模拟账户/成交展示。
- 累计亏损停买、信号卖出继续、手动恢复及非阻塞提示。
- MCP只读白名单、分页、账户对账模块、一次性OAuth CLI和桌面读取入口。
- 离线执行风控、执行锁、确定性订单ID与状态日志；这些不构成真实下单适配器。
- 写盘失败回滚内存状态、拒绝日志时间倒退、读取失败不显示旧账户余额。
- 共用的Spot成交成本算法和独立持久化账本：成交ID幂等、基础/报价手续费、部分卖出盈亏、完整历史校验、锁与写盘失败回滚；尚未接真实宿主和权益风险基准。
- Spot权益风险账本：明确确认期初基准，按买一价估值，以完整资金流水抵消入金/出金，并从完整成交推导开仓和连亏计数；真实MCP资金流水来源及桌面编排尚未完成。
- 独立MCP确认会话边界：仅允许Spot读取、下单和按客户端ID查单，双层验证参数并在初始化时检查运行时schema；OAuth/桌面编排和首次真实schema验收尚未完成。
- 桌面逐笔确认弹窗：显示账户、方向和精确金额，要求一次性短语并在15秒过期，关闭程序自动取消；真实会话和策略事件尚未连接，提交入口保持禁用。
- MCP schema验收CLI：一次性OAuth后只执行initialize/tools-list，严格校验写工具schema并返回指纹，关闭会话；不读账户、不调用订单工具。

Delivered: a unified tagged strategy library, editable desktop paper trading, public candles, BUY-only loss latches and manual resume, allowlisted MCP reads, reconciliation, memory-only OAuth CLI/desktop wiring, offline execution safety, persistence rollback and stale-account-view prevention.

Also delivered: shared Spot fill-cost replay and a standalone persisted ledger with fee-aware realized PnL, idempotent fill IDs, complete-history validation and failure-safe locking/persistence. Live-host wiring and equity-risk baselines remain pending. See [Spot fill ledger](SPOT_FILL_LEDGER.md).

## 两条验证路径不要混淆 / Keep the two verification paths separate

已通过的真实账户读取与早期小额BTC购买由外部已登录MCP宿主完成。它们不证明本项目的独立桌面OAuth和下单执行器已验收。

Historical account reads and the earlier small BTC purchase used an externally authenticated MCP host. They do not validate this project's standalone desktop OAuth or order executor.

GitHub推送是代码发布。公网Client Metadata是独立OAuth客户端身份的发布；两者互不等同。当前默认由jsDelivr从公开仓库分发身份JSON，不再要求开启GitHub Pages。

A GitHub push publishes code. Public Client Metadata publishes the standalone OAuth client identity; these are separate operations. The default identity JSON is now distributed from the public repository by jsDelivr, so GitHub Pages is not required.

## 实盘前必须完成 / Required before live use

1. 项目自己的HTTPS Client Metadata可访问，内容与本机回调匹配。默认使用jsDelivr公开URL，首次使用前验证200/JSON及自标识一致；Pages仅为可选替代。不得借用其他客户端身份。
2. 用户在浏览器完成独立项目OAuth，只读取账户并确认Agentic UID、余额、权限、历史订单及成交；确认没有重复创建/选错账户。
3. 开发人工确认MCP写适配器，将策略意图、账户级风险、精度/最小金额规则、逐笔确认、执行日志、跨进程锁和查单恢复贯通。当前只读Token在读取后关闭，不能直接拿只读按钮作交易连接。
4. 离线故障注入覆盖确认过期、拒绝、部分成交、超时、崩溃及重启。未知提交结果只查单，不自动重发。
5. 用户另外批准最小金额真实订单后，核验买卖终态、手续费和资金账本；随后观察持续真实行情与恢复行为。

Before live use: publish the project's client identity, complete user-driven standalone read-only OAuth acceptance, implement a per-order-confirmed write adapter, test its failure/recovery paths offline, and obtain separate authorization for minimal live-order acceptance.

不能将当前版本称为完全无人值守实盘。MCP写操作仍按官方逐笔确认要求执行；API Key替代路线未启用，需另行讨论和批准。当前轮次未授权账户或发送真实订单。

This revision is not unattended live trading. MCP writes remain subject to the official per-action confirmation policy. An API-key alternative is disabled and requires separate discussion and approval. No account authorization or live order was performed in this closeout.

## 本轮证据 / Evidence

最新公网身份更新：jsDelivr Client Metadata已验证HTTP 200、`application/json`和自标识一致；GitHub Pages不再必需。完整回归443项通过（65.35秒）。首次Binance OAuth/schema发现仍需用户本人确认授权。

Latest public-identity update: jsDelivr Client Metadata is verified as HTTP 200, `application/json` and exactly self-identifying; GitHub Pages is no longer required. 443 tests passed in 65.35 seconds. First Binance OAuth/schema discovery still requires the user's own authorization confirmation.

最新schema验收更新：完整回归442项通过（62.09秒）。新增8项测试覆盖无工具调用的一次性OAuth编排、关闭顺序、预取消、超时参数、浏览器失败回退及稳定schema指纹。公网Client Metadata和首次真实schema发现仍待用户参与。后文434/430/410/390/366/342项均为历史阶段证据。

Latest schema-acceptance update: 442 tests passed in 62.09 seconds. Eight new tests cover no-tool-call one-shot OAuth orchestration, close ordering, pre-cancellation, timeout validation, browser-failure fallback and stable schema fingerprints. Public client metadata and first live schema discovery still require user participation. The 434/430/410/390/366/342 counts below are historical milestones.

最新桌面确认更新：完整回归434项通过（65.84秒）。新增4项GUI测试覆盖预览严格校验、错误短语、单次确认、取消、过期和主窗口关闭。弹窗尚未连接真实OAuth/策略事件，账户页明确保持submission disabled。后文430/410/390/366/342项均为历史阶段证据。

Latest desktop-confirmation update: 434 tests passed in 65.84 seconds. Four GUI tests cover strict preview validation, wrong phrases, one-shot confirmation, cancellation, expiry and main-window close. The dialog is not connected to live OAuth/strategy events, and the Account tab explicitly keeps submission disabled. The 430/410/390/366/342 counts below are historical milestones.

最新确认会话更新：完整回归430项通过（56.56秒）。新增20项测试覆盖工具/schema发现、同会话只读、BUY/SELL精确参数、客户端订单ID、未知工具、缺失/不兼容schema和传输层绕过。OAuth/桌面编排、首次真实schema发现、资金流水来源及真实订单验收仍未完成。后文410/390/366/342项均为历史阶段证据。

Latest confirmed-session update: 430 tests passed in 56.56 seconds. Twenty new tests cover discovery/schema gates, same-session reads, exact BUY/SELL arguments, client IDs, unknown tools, missing/incompatible schemas and transport-bypass attempts. OAuth/desktop orchestration, first live schema discovery, a verified cash-flow source and live-order acceptance remain unfinished. The 410/390/366/342 counts below are historical milestones.

最新权益风控更新：完整回归410项通过（64.53秒）。新增权益基准、资金流调整、跨日/重启保护，以及由完整成交推导的开仓/连亏指标。经过验证的真实资金流水来源、MCP写transport/schema、桌面确认下单与真实验收仍未完成。后文390/366/342项均为历史阶段证据。

Latest equity-risk update: 410 tests passed in 64.53 seconds. UTC baselines, cash-flow adjustment, rollover/restart protection and fill-derived entry/loss metrics are now covered. A verified live cash-flow source, MCP write transport/schema, desktop confirmed submission and live acceptance remain unfinished. The 390/366/342 counts below are historical milestones.

最新账本更新：完整回归390项通过（62.21秒），其中新增24项成交账本测试。真实写transport/schema、权益基准与资金划转调整、完整成交宿主接线、桌面逐笔确认下单及真实验收仍未完成。后文366/342项为历史阶段证据，不是当前计数。

Latest ledger update: 390 tests passed in 62.21 seconds, including 24 new accounting cases. Live write transport/schema, equity/cash-flow risk, complete-fill host wiring, desktop confirmed submission and live acceptance remain unfinished. The 366/342 counts below are historical milestones.

后续执行器更新：已新增逐笔确认执行器的离线调用契约、最小Spot过滤器和超时/重启查单测试，详见[MCP确认执行器](MCP_CONFIRMED_EXECUTOR.md)。完整回归现为366项；上方实盘前清单仍然有效，真实写transport、schema匹配、手续费/盘口、资金账本及桌面接线尚未完成。下方342项是前一阶段证据。

Follow-up: an offline confirmed executor, minimal Spot filters and lookup-only recovery are implemented; full regression is now 366 tests. Live write transport/schema, fee/book checks, account accounting and desktop wiring remain pending. The 342-test evidence below records the preceding milestone.

本地Python 3.11完整回归342项通过；源码编译与依赖检查通过。新增测试验证日志写盘故障后的内存/磁盘一致性、时间倒退拒绝与MCP重试失败后旧余额清除。真实OAuth、真实订单与持续实盘不在离线回归的证明范围内。

342 local Python 3.11 tests passed, with source compilation and dependency checks. New tests cover journal persistence failures, clock rewind and removal of stale account balances after a failed retry. Offline regression does not establish live OAuth, order or sustained-market acceptance.
