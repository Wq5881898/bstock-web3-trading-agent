# 对话式交易助手收尾 / Conversational Trading Assistant Closeout

> 状态 / Status: **助手级阶段一完成（文档、项目 Skill、离线回归、MCP 公开只读冒烟）；尚未宣称 Skill 新任务激活或新的真实订单验收。** 此里程碑不替代[持续自动交易产品基准](AUTONOMOUS_TRADING_PRODUCT_BASELINE.md)，也不批准更换账户、OAuth、MCP 或 API 路线。 / **Assistant milestone 1 complete** for documentation, repository Skill, offline regression and public read-only MCP smoke. Fresh-task Skill activation and new live-order acceptance are not claimed. This milestone does not replace the autonomous-trading baseline or approve a transport/account change.

## 1. 要交付的能力 / Intended capability

用户在当前已授权的 Codex 对话中发出一次明确请求，例如“查询 Agentic Spot 余额”“给我看 BTCUSDT 最近 K 线”或“用 50 USDT 市价买入 BTC”。助手识别产品、账户、币对、方向、订单类型与计价单位，读取实时证据，展示精确订单摘要；只有用户对**这一笔**明确确认后才通过现有 Binance Agent OS MCP 提交一次，随后查订单终态、成交、手续费及余额。读不到、说不清、校验失败或结果不确定时停止写入并查单，不猜测成功或失败。

In the already-authorized Codex conversation, the user requests a bounded read or a single Spot trade. The assistant resolves account, product, symbol, side, order type and sizing unit; reads current evidence; presents an exact order summary; submits at most once only after confirmation for that specific action; then verifies terminal order, fills, fees and balances. Missing evidence or ambiguous outcome fails closed and triggers lookup, never an inferred retry.

这是一种**人工发起、逐笔确认**的助手，不是“启动一次就连续无人值守交易”的服务。Skill 只是可选的可复用操作规范；它不能替代 MCP 授权、订单状态管理或 Binance 的确认要求。新闻和情绪指标是可选的研究输入，不是助手级交易闭环的依赖，也不能单独构成交易信号。

This is a user-initiated, per-action-confirmed assistant, not a continuously unattended trader. A Skill is optional reusable workflow guidance, not an authorization or execution transport. News and sentiment are optional research inputs, not prerequisites or standalone trading signals.

## 2. 当前证据与缺口 / Evidence and gaps

| 能力 / Capability | 当前证据 / Current evidence | 判定 / Assessment |
|---|---|---|
| 已有授权和账户 / Existing authorization and account | [真实只读验收](MCP_LIVE_ACCEPTANCE_20260922.md)验证现有 `binance-agent-os` 与既有 Agentic Spot 子账户；无需新账户或 API Key。 / Existing host and Agentic Spot account were read successfully. | 已验证；授权是否仍有效需每次实际调用时判断。 / Verified historically; current validity must be checked at use time. |
| 单次对话真实交易 / One-shot conversational trade | [宿主桥接](MCP_HOST_BRIDGE.md)记录历史约 10 USDT BTC 买入；[收尾总计划](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md)记录 2026-09-22 用户确认的手动市价 SELL 已成交并对账。 / Historical buy and confirmed manual sell are recorded. | 助手级路径已有真实先例；手动 SELL **不是**策略 SELL 验收。 / Real precedent, not autonomous strategy acceptance. |
| 严格读取与回执 / Strict reads and receipts | 七项只读、完整分页、账户指纹、脱敏回执及严格导入已经真实/离线验收；相关 59 项聚焦测试在 2026-09-23 通过。 / Seven-read reconciliation and strict import; 59 focused tests passed. | 可复用安全模块；并非每个对话命令都必须走整套本地文件交接。 / Reusable guardrails, not mandatory file handoff for every chat request. |
| 当前桌面程序直接 MCP / Direct desktop MCP | 桌面程序只生成无凭据文件；[归并记录](CONSOLIDATION.md)说明独立 OAuth 身份未获批准。 / Desktop is not a direct authorized MCP client. | 未实现；不是助手级闭环阻塞项。 / Not implemented and not a blocker for Codex-hosted assistant. |
| 常驻无人值守执行 / Unattended execution | 非交互 Codex 宿主的通用 MCP 分发工具审批受限；观察器仍为 `OBSERVE_ONLY`。 / Headless generic dispatcher approval is blocked; observer is observe-only. | 不在本里程碑，不能宣称完成。 / Outside this milestone; do not claim complete. |
| 新闻 MCP / News MCP | 本仓库没有已验收、来源明确且可复现的新闻 MCP 数据闭环。 / No accepted reproducible news feed in this repository. | 可选后续；不得写进当前已交付能力。 / Optional future work, not delivered. |
| Codex Skill 包装 / Packaged Skill | 已有项目内 [Skill 草案](../.agents/skills/binance-spot-assistant/SKILL.md)，但尚未在新任务中做激活和真实 MCP 行为验收。 / A project-local Skill draft exists, but activation and MCP behavior have not been accepted in a fresh task. | 便利性工作，不是调用现有 MCP 的前提；不能把草案称为已安装产品。 / Convenience packaging, not a prerequisite or an installed-product claim. |

## 3. 助手级最小验收 / Minimum assistant acceptance

本里程碑按以下顺序验收，**不要求为了验收再下真实订单**；历史真实买卖证据可作为写入先例，新订单仍需单独、当笔授权。

1. 只读请求能明确显示来自现有 Binance MCP 的实时结果，并能区分 Agentic 子账户与主账户。/ Read-only request identifies the live MCP source and the intended Agentic account.
2. 模拟“用 50 USDT 市价买 BTC”的对话预演，正确解析为 `BTCUSDT`、Agentic Spot、`BUY MARKET`、`quoteOrderQty=50 USDT`；未获当笔确认时绝不调用写工具。/ Dry-run parsing is exact and performs no write without that order's confirmation.
3. 展示账户、标的、方向、类型、金额单位、余额、过滤器/最小名义金额、估算手续费与风险；数据过期或不一致则重新读取。市价成交数量和最终价格不能事先保证。/ Present exact scope and current preflight; refresh stale evidence and never promise final market fill price/quantity.
4. 当笔确认只适用于展示的订单；改动金额、方向、账户或标的必须重新确认。提交最多一次，记录本次客户端订单身份；不确定结果只查单。/ Confirmation binds one unchanged order; one submission maximum; unknown status is lookup-only.
5. 成交后读取订单、成交、手续费和余额并给出可核对的摘要；拒绝、过期、取消、部分成交与 UNKNOWN 不得被报告为“已成交”。/ Verify result before claiming a fill.
6. 中英双语说明真实边界、安装/使用条件和失效处置；不包含 Token、UID、精确余额或订单 ID。/ Bilingual public documentation with no secrets or private identifiers.

## 4. 最小剩余工作 / Smallest remaining work

- 将第 2–5 项做一次**不提交真实订单**的对话/假宿主预演，并保存脱敏验收记录。现有源码的安全契约可作为参考，但不要把一次性对话调用强迫接进 15 秒文件化策略会话。 / Rehearse the conversational workflow without a real order and save redacted evidence; do not force chat use through the time-sensitive strategy file handoff.
- 在新的项目任务中验证 `$binance-spot-assistant` 的触发、缺参、拒绝、过期与 UNKNOWN 行为；Skill 文件存在不等于当前任务已加载，也不需要为此重新授权 MCP。 / Test activation and failure handling in a fresh project task; a file on disk does not prove this task has loaded the Skill, and no new MCP authorization is implied.
- 公开发布前完成敏感信息扫描、README 能力边界核对和干净环境安装/只读冒烟。 / Before publication, scan for secrets, align README claims and perform install/read-only smoke checks.

本轮 2026-09-23 在项目虚拟环境运行完整测试：`505 passed in 50.68s`。这是离线代码回归，不是新的真实订单或 Skill 安装验收。/ The full project test suite passed 505 tests in 50.68 seconds on 2026-09-23. This is offline regression evidence, not a new live order or installed-Skill acceptance.

同日，现有 `binance-agent-os` MCP 的工具发现和 `spot.tickerPrice(symbol=BTCUSDT)` 公开只读调用成功；没有读取私有余额，也没有调用 `spot.newOrder` 或任何其他写工具。对“用 50 USDT 市价买 BTC”的无下单演练仅确认意图应为 Agentic Spot `BTCUSDT`、`BUY MARKET`、`quoteOrderQty=50 USDT`，且在真实账户预检和该笔确认前不得下单；这不是实际账户预检。项目 Skill 的基础 frontmatter 已手工验证；官方 `quick_validate.py` 因当前 Python 环境缺少 `PyYAML` 未能运行，不能将其记为已通过。

On the same date, discovery and a public `spot.tickerPrice(BTCUSDT)` read through the existing MCP succeeded. No private balance or write tool was called. The no-order 50-USDT example checked intent mapping only, not private-account preflight. Basic Skill frontmatter was checked manually; the bundled validator could not run because `PyYAML` is absent from the current Python environments.

## 5. 不在本里程碑 / Out of scope

24 小时策略运行、策略自动 BUY/SELL、无人确认真实下单、自建 MCP OAuth、API Key、Futures、链上钱包、Telegram、多币种和新闻驱动交易。它们分别属于[持续产品基准](AUTONOMOUS_TRADING_PRODUCT_BASELINE.md)、另行批准的接口决策或未来功能。/ Continuous strategy execution, zero-confirmation orders, new OAuth/API credentials, futures, on-chain wallet, Telegram, multi-asset and news-driven trading remain separate.

官方确认边界 / Official confirmation boundary: <https://developers.binance.com/en/docs/agent-native/mcp-server/agentic>.
