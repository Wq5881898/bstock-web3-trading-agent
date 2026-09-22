# MCP + Agentic 自动交易收尾总计划
# MCP + Agentic Trading Closeout Master Plan

> 状态 / Status: **已由用户确认；后续工作必须严格按阶段和验收编号执行。 / Approved by the operator; remaining work must follow the phases and acceptance IDs below.**
>
> 适用日期 / Effective draft date: 2026-09-22

## 1. 为什么需要这份文件 / Why this file exists

本文件用于消除当前仓库中互相冲突的两套路线，并成为后续工作的唯一计划入口：

1. 已验证路线：现有 Codex 宿主持有 Binance Agent OS MCP 授权，并连接现有 Agentic 子账户；本地项目不保存 API Key、OAuth Token 或账户密码。
2. 错误扩展路线：后续文档和代码把独立 Binance Spot API 描述成已经获得批准的主路线。这与既有 MCP 文档及用户最新纠正冲突。
3. 官方能力边界：Binance Agentic MCP 支持读取和交易，但每一个非只读动作（下单、撤单、子账户内划转）都必须先由用户确认。

This document removes the repository's conflicting execution directions and becomes the single entry point for remaining work:

1. Verified path: the existing Codex host owns the Binance Agent OS MCP authorization and is connected to the existing Agentic sub-account. The local project stores no API key, OAuth token, or account password.
2. Incorrect expansion: later code and documentation described a separate Binance Spot API route as approved. That conflicts with the established MCP documents and the operator's latest correction.
3. Official boundary: Binance Agentic MCP supports reads and trading, but every non-read action (order, cancel, or internal transfer) requires operator confirmation first.

官方资料 / Official source: <https://developers.binance.com/en/docs/agent-native/mcp-server/agentic>

## 2. 冻结后的产品目标 / Frozen product goal

用户发出一次启动命令后，本地服务持续执行以下工作，直到用户手动停止：

- 拉取公开行情和 K 线；
- 运行统一策略引擎并产生 `BUY`、`SELL` 或 `HOLD`；
- 应用本地风险策略、累计亏损闩锁、幂等和恢复规则；
- 对有效交易信号生成无凭据、限时、绑定账户指纹的 MCP 候选动作；
- 通过已经授权的 Codex MCP 宿主读取现有 Agentic 子账户并完成下单前核对；
- 对每一笔真实写操作弹窗提醒并取得 Binance/Codex 要求的明确确认；
- 确认后由 MCP 执行，随后查询终态、同步成交和手续费账本；
- 累计亏损达到默认 10 USDT 后停止新的买入；合法卖出信号继续产生，但真实卖出仍须逐笔确认；
- 只有用户手动恢复才重新允许买入。

After one start command, the local service continuously performs the following until the operator stops it:

- fetch public market data and candles;
- run the unified strategy engine and produce `BUY`, `SELL`, or `HOLD`;
- enforce local risk, cumulative-loss latch, idempotency, and recovery rules;
- produce a credential-free, expiring, account-bound MCP candidate for an actionable signal;
- use the already-authorized Codex MCP host to read and preflight the existing Agentic sub-account;
- display a desktop alert and obtain the explicit confirmation required by Binance/Codex for every real write;
- execute through MCP after confirmation, then resolve terminal state and reconcile fills and fees;
- pause new buys at the default 10 USDT cumulative-loss threshold while continuing to emit valid sell signals; real sells still require confirmation;
- resume buys only after a manual operator action.

这是一套**持续自动监测、自动决策、自动风控、逐笔确认执行**的 MCP 产品。官方 MCP 当前不能被描述成“完全无人确认的真实自动下单”。

This is a **continuously monitored, strategy-driven, risk-controlled, per-order-confirmed MCP product**. The official MCP cannot currently be represented as fully unattended real-order execution.

## 3. 不可变架构 / Immutable architecture

```text
Binance public market data
        |
        v
local candle pipeline -> unified strategy engine -> local risk/session state
        |                                              |
        +----------------------------------------------+
                                                       v
                                      credential-free MCP candidate
                                                       |
                                                       v
                                  desktop alert + explicit confirmation
                                                       |
                                                       v
                              existing authorized Codex MCP host
                                                       |
                                                       v
                                      Binance Agent OS MCP
                                                       |
                                                       v
                                      existing Agentic sub-account
                                                       |
                                                       v
                                terminal lookup + local reconciliation
```

固定规则 / Fixed rules:

- 不创建新的普通 Virtual Sub 或 Agentic 子账户。
- 不重新实现 OAuth，不监听本地 OAuth 回调，不持久化 MCP Token。
- 不创建、读取或要求 Binance API Key。
- 不直接调用私有 Binance REST 下单接口。
- 不在 MCP、Spot API、Agentic Wallet 之间自动回退。
- Agentic Wallet 保持独立链上实验通道，不属于本项目 MCP Spot 自动交易主链。
- 当前原型保持单标的 Spot；多标的、合约仅保留接口扩展能力，不进入收尾范围。

Fixed constraints:

- Do not create another ordinary Virtual Sub or Agentic sub-account.
- Do not reimplement OAuth, listen for a local OAuth callback, or persist MCP tokens.
- Do not create, read, or request a Binance API key.
- Do not call private Binance REST order endpoints directly.
- Do not silently fall back among MCP, Spot API, and Agentic Wallet.
- Agentic Wallet remains an independent on-chain experiment and is not part of this MCP Spot execution path.
- Closeout remains single-symbol Spot; multi-symbol and futures stay extension points only.

## 4. 文档优先级与纠正清单 / Document precedence and correction list

### 4.1 保留并作为事实依据 / Retain as factual sources

| 文档 / Document | 保留内容 / Retained authority |
|---|---|
| `docs/MCP_HOST_BRIDGE.md` | 现有 Codex MCP、现有 Agentic 子账户、无本地凭据、无静默回退 |
| `docs/CONSOLIDATION.md` | 自建 OAuth 路线已撤回；API 替代路线必须另行明确批准 |
| `docs/MCP_READONLY_ACCEPTANCE.md` | 真实只读 MCP 闭环已通过 |
| `docs/MCP_EXECUTION_SAFETY.md` | 账户绑定、幂等、`UNKNOWN` 只查单、失败关闭 |
| `docs/MCP_EXECUTION_HANDOFF.md` | 文件交接、一次性票据、回执和恢复契约 |

### 4.2 必须纠正 / Must be corrected

| 文档 / Code | 冲突 / Conflict | 纠正 / Correction |
|---|---|---|
| `README.md` | 把 Binance Spot API 列为当前执行通道，并把逐笔确认降为诊断模式 | 删除 API 主路线描述；明确 MCP 逐笔确认是官方硬边界 |
| `docs/AUTONOMOUS_TRADING_PRODUCT_BASELINE.md` | 声称 API 路线已获批准；`AUTO-002` 要求零确认写操作 | 撤回该表述；用 MCP 可实现的确认式验收替换 `AUTO-002`/`AUTO-009` |
| `docs/CLOSEOUT.md` | 声称独立 Spot API 已被选择和批准 | 改回 MCP-only；记录错误路线已经撤回 |
| `docs/AUTONOMOUS_SPOT_API_CLOSEOUT.md` | 指导创建 API Key 并走私有 REST | 从当前产品文档索引移除，随后删除或归档为已撤销实验 |
| API 自动执行源码和测试 | 引入签名 REST 下单、API Key 配置和 `bstock-auto` | 从主产品删除；仅保留确实与传输无关且通过 MCP 需求复核的通用状态机逻辑 |

### 4.3 新优先级 / New precedence

用户确认后，优先级固定为：

1. 本总计划；
2. 修订后的 `AUTONOMOUS_TRADING_PRODUCT_BASELINE.md`；
3. `MCP_HOST_BRIDGE.md` 和 MCP 安全/交接文档；
4. README；
5. 其他历史说明。

任何下级文档与上级冲突时，必须停止实现并先修正文档，不能自行选择更方便的路线。

After operator approval, precedence is fixed as: this plan, the corrected product baseline, MCP host/safety/handoff documents, README, then historical notes. An implementation must stop on conflict instead of selecting a more convenient transport.

## 5. 修订后的验收基线 / Revised acceptance baseline

| ID | 必须通过的结果 / Required outcome |
|---|---|
| MCP-AUTO-001 | 一次启动建立持久化会话；账户指纹、标的、策略版本和风险配置不可漂移。 / One start creates a durable session with immutable account fingerprint, symbol, strategy version, and risk configuration. |
| MCP-AUTO-002 | 服务持续自动拉行情、跑策略和风控；真实非只读动作必须逐笔明确确认。 / Market, strategy, and risk loops run continuously; every real non-read action requires explicit per-action confirmation. |
| MCP-AUTO-003 | 每笔动作前核对新鲜账户、余额、挂单、成交、规则、手续费和盘口。 / Every action uses fresh account, balance, open-order, fill, rule, commission, and book data. |
| MCP-AUTO-004 | 默认单次买入预算 100 USDT；累计亏损 10 USDT 后进入 `BUY_PAUSED`，SELL 信号仍可继续。 / Default entry budget is 100 USDT; a 10 USDT cumulative loss enters `BUY_PAUSED` while valid SELL signals continue. |
| MCP-AUTO-005 | 同一策略事件和订单身份不可重复提交；`UNKNOWN` 只能查单，不得重下。 / Signal and order identities are idempotent; `UNKNOWN` is lookup-only and cannot be resubmitted. |
| MCP-AUTO-006 | 成交、手续费、持仓成本和权益可靠写入账本后才能处理下一笔动作。 / Fills, fees, cost basis, and equity must be durably reconciled before the next action. |
| MCP-AUTO-007 | 用户停止后拒绝新信号；未决动作核对完成后进入 `STOPPED`。 / Stop rejects new signals and reaches `STOPPED` after in-flight reconciliation. |
| MCP-AUTO-008 | 断网、限流、MCP 错误、过期确认和进程重启都失败关闭，不重复订单。 / Disconnects, rate limits, MCP failures, expired confirmations, and restarts fail closed without duplicate orders. |
| MCP-AUTO-009 | 完成至少 24 小时小额单标的监督运行，包含一笔经确认的策略 BUY 和一笔经确认的策略 SELL。 / Complete at least 24 hours of supervised small single-symbol operation with one confirmed strategy BUY and one confirmed strategy SELL. |
| MCP-AUTO-010 | 全流程不创建或使用 API Key，不新建账户，不切换执行通道。 / The full flow creates or uses no API key, creates no account, and switches no execution transport. |

原 `AUTO-002`（连续真实 BUY/SELL 零确认）与 Binance Agentic MCP 官方规则冲突，不能继续作为 MCP 路线的完成条件。它不是待修 Bug，而是当前接口不提供的能力。

The old `AUTO-002` (multiple real BUY/SELL actions with zero confirmation) conflicts with the official Agentic MCP contract. It is not an implementation bug; the interface does not currently expose that capability.

## 6. 全部后续工作 / Complete remaining work plan

### Phase 0 — 基线纠正和止损 / Correct the baseline and stop scope drift

交付 / Deliverables:

1. 修订 README、产品基准和 Closeout，删除“API 已批准”的错误表述。
2. 将 API Key/签名 REST 自动下单原型从当前主产品中移除；Git 历史保留，便于审计，不作为运行入口。
3. 更新命令入口和依赖，确保没有 `bstock-auto` 或私有 REST 下单入口。
4. 增加架构守卫测试：禁止新增私有 REST 下单、API Key 环境变量和静默执行通道回退。
5. 运行完整离线测试并确认工作树只包含本阶段预期变更。

Gate: `MCP-AUTO-010`，以及文档中不再存在“API 已批准/需要创建 API Key”的有效指令。

### Phase 1 — 收敛持久化运行器 / Converge the durable runner

交付 / Deliverables:

1. 复用现有 K 线、统一策略、风险和账本模块，建立单标的持久化会话。
2. 固定会话绑定：Agentic 账户指纹、Spot、标的、策略 ID/版本、参数、100 USDT 默认预算和 10 USDT 累计亏损阈值。
3. 实现 `RUNNING -> BUY_PAUSED -> STOPPING -> STOPPED` 及故障恢复；恢复默认需要人工动作。
4. 每个已闭合 K 线事件最多求值一次；同一信号指纹最多生成一个候选动作。
5. 本阶段只生成 MCP 候选，不调用任何真实写工具。

Gate: `MCP-AUTO-001/004/005/007/008` 的离线故障注入测试全部通过。

### Phase 2 — MCP 宿主交接闭环 / Complete the MCP host handoff

交付 / Deliverables:

1. 候选动作触发桌面弹窗，只通知一次并显示策略、标的、方向、金额、风控状态和过期时间。
2. 由当前已授权的 Codex 任务消费无凭据候选；不得发起新 OAuth 或创建账户。
3. MCP 宿主完成七项只读预检和完整分页；账户指纹或参数漂移立即失败关闭。
4. 用户明确确认后，生成短时单次提交票据并执行一次 MCP 写调用。
5. 导入脱敏终态回执，先同步成交/手续费账本，再推进会话状态。
6. 过期、拒绝或失败只终止本次动作；不会转向 API 或 Wallet。

Gate: `MCP-AUTO-002/003/005/006/008/010` 的离线端到端测试通过。

### Phase 3 — 界面和操作闭环 / Complete the operator UI

交付 / Deliverables:

1. 真实交易总开关默认关闭；启用时显示固定的 MCP + Agentic 账户边界。
2. 策略选择、参数、运行状态、风险状态、累计损益和手动恢复在同一运行页可见。
3. K 线标签页显示程序实际使用的 K 线和最新闭合事件。
4. 待确认动作、确认过期、拒绝、提交中、终态和 `UNKNOWN` 状态清晰可见。
5. 暂时只做桌面弹窗；Telegram 和其他通知不进入本轮。

Gate: UI 不得出现 API Key、创建账户、重新 OAuth 或“无人值守真实写入”的入口/承诺。

### Phase 4 — 实盘验收 / Live acceptance

严格顺序 / Strict order:

1. 用现有 MCP 授权读取并核对现有 Agentic 子账户，不转账、不交易。
2. 启动单标的监督运行，仅观察候选和弹窗，验证无重复、无漂移。
3. 经用户当笔确认，执行一笔最小金额策略 BUY；核对终态、余额、成交和手续费。
4. 经用户当笔确认，执行一笔策略 SELL；完成同样核对。
5. 执行故障恢复、过期确认、拒绝、停止和手动恢复测试。
6. 在小额资金下完成 24 小时监督运行。

Gate: `MCP-AUTO-001` 至 `MCP-AUTO-010` 全部有证据；任何真实订单仍由用户当笔决定。

### Phase 5 — 收尾发布 / Closeout and release

交付 / Deliverables:

1. README 双语更新为实际能力，不做超出官方 MCP 的承诺。
2. 发布一份脱敏验收报告，不包含 UID、精确余额、Token、订单 ID 或成交 ID。
3. 完整测试、打包/启动冒烟、Git 状态和公开仓库敏感信息扫描通过。
4. 提交并推送一个明确的 MCP-only 收尾版本。
5. 将多标的、合约、Telegram、完全无人确认执行列入未来路线，不夹带进当前收尾。

## 7. 明确不做 / Explicit non-goals

- 不创建 Binance API Key。
- 不用普通子账户替换 Agentic 子账户。
- 不重新授权或新建 MCP 连接，除非现有授权确实失效并由用户亲自决定。
- 不以 Agentic Wallet 作为 MCP 失败回退。
- 不实现合约、多标的、Telegram、云部署或额外策略优化。
- 不继续打磨与主验收无关的 UI、小功能或策略参数。
- 不在没有真实证据时宣称“无人值守实盘已完成”。

## 8. 防止再次偏离的执行纪律 / Anti-drift execution rules

1. 每次开始代码工作前，必须在进度消息中写明：`正在执行 Phase X / MCP-AUTO-YYY`。
2. 没有对应验收 ID 的修改不做；发现顺手优化时登记到未来列表，不立即实现。
3. “继续”“按计划”“可以”只授权推进已经确认的本计划，不授权更换账户、认证或交易接口。
4. 任何涉及 MCP、API、Wallet、OAuth、账户或凭据的路线变更，必须先形成单独决策记录，并获得用户明确写出接口名称的批准。
5. 基准文档不能凭推断改写“用户已批准”；批准证据必须引用明确的用户决定。
6. 每阶段只允许一个收敛提交；提交前提供验收 ID、测试证据、剩余阻塞和下一阶段。
7. 实盘步骤必须单独停下来取得当笔交易确认；文档或总体计划确认不等于订单确认。

## 9. 执行顺序摘要 / Execution order summary

```text
确认本计划
  -> Phase 0 撤回错误 API 路线并修正文档
  -> Phase 1 持久化策略/风控运行器
  -> Phase 2 MCP 候选、确认、执行和终态回执闭环
  -> Phase 3 最小必要界面
  -> Phase 4 小额真实监督验收
  -> Phase 5 双语文档、测试、脱敏报告和 GitHub 收尾
```

## 10. 当前进度 / Current progress

| 阶段 / Phase | 状态 / Status | 证据 / Evidence |
|---|---|---|
| Phase 0 | 已完成 / Complete | API Key/私有 REST 路线、入口和测试已撤回；MCP-only 架构守卫及完整回归通过 / API-key/private-REST route, entry point, and tests removed; MCP-only guard and full regression pass |
| Phase 1 | 已完成 / Complete | `MCP-AUTO-001/004/005/007/008` 持久化候选会话及故障注入测试通过 / durable candidate session and fault-injection tests pass |
| Phase 2 | 已完成 / Complete | `MCP-AUTO-002/003/005/006/008/010` 文件化确认、票据、终态/UNKNOWN及账本闭环通过 / file-safe confirmation, ticket, terminal/UNKNOWN, and ledger loop pass |
| Phase 3 | 已完成 / Complete | 现有策略/K线/账户页加默认关闭真实MCP票据开关、确认弹窗和终态导入 / existing strategy/candle/account UI plus off-by-default live MCP ticket, confirmation and result import |
| Phase 4 | 待执行 / Pending | `MCP-AUTO-009`；所有真实订单仍需当笔确认 / all real orders still require per-action confirmation |
| Phase 5 | 待执行 / Pending | 发布、脱敏验收与 GitHub 收尾 / release, sanitized acceptance, and GitHub closeout |
