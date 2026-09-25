# 自动交易产品基准 / Autonomous Trading Product Baseline

> **历史目标，未交付 / Historical target, not delivered.** 2026-09-25 阶段性范围已降级，当前发布状态以 [README](../README.md) 和[阶段收口记录](STAGE_CLOSEOUT_20260924.md)为准。以下仍保存原始验收目标，不能据此声称持续自动实盘已实现。/ The current release scope has been reduced; this document preserves the original acceptance target, not shipped capability.
>
> 原实施期间，本文档与[收尾总计划](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md)共同构成最高优先级产品依据。后续如恢复原目标，仍不能自行改变账户、认证或执行接口，须重新取得明确决策。
>
> During the original implementation, this document and the [closeout master plan](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md) were the primary product sources. Resuming that goal or changing account, authentication, or transport requires a new explicit decision.

## 唯一主目标 / Single primary objective

用户选择单一标的、统一策略和风险参数并发出一次启动命令。程序持续拉取行情、运行策略和风控、生成真实交易候选并维护会话，直到用户停止。所有真实订单通过现有 Codex `binance-agent-os` MCP 连接和现有 Agentic 子账户执行；按照 Binance Agentic MCP 规则，每一个非只读动作必须先取得用户当笔确认。

The operator selects one symbol, a unified strategy and risk settings, then issues one start command. The service continuously reads markets, evaluates strategy and risk, emits real-trade candidates, and maintains its session until stopped. Every real order uses the existing Codex `binance-agent-os` MCP connection and existing Agentic sub-account; under the Binance Agentic MCP contract, every non-read action requires explicit per-action confirmation.

持续自动化的范围是行情、策略、风控、候选生成、状态恢复和终态对账。官方 MCP 当前不提供零确认的真实写操作，因此“完全无人确认下单”不属于本版本验收。

Continuous automation covers market data, strategy, risk, candidate generation, recovery, and terminal reconciliation. The official MCP does not currently expose zero-confirmation writes, so fully unattended real ordering is not an acceptance claim for this release.

## 已确定的 MVP 范围 / Fixed MVP scope

- Binance Agentic 子账户 Spot，且只通过现有 Codex MCP 宿主执行；
- 不创建 API Key、不新建账户、不重做 OAuth、不静默回退到 REST API 或 Agentic Wallet；
- 单标的、单策略、单持仓；多标的和 Futures 不阻塞 MVP；
- 默认单次买入预算 100 USDT，累计权益亏损达到 10 USDT 后锁定新买入；
- BUY 暂停后继续产生合法 SELL 信号；真实 SELL 同样要求当笔确认；
- 风控恢复必须由用户明确发出，不重置仍然有效的风险数字；
- 停止时不强制清仓：拒绝新策略动作，核对未决动作后退出；
- 网络或订单结果不确定时失败关闭；`UNKNOWN` 只按确定性客户端订单 ID 查单，绝不重发；
- 意外重启进入恢复状态，不自动新开仓。

- Binance Agentic Spot through the existing Codex MCP host only;
- no API key, new account, custom OAuth, silent REST API fallback, or Agentic Wallet fallback;
- one symbol, one strategy, and one position; multi-symbol and Futures do not block the MVP;
- default 100-USDT entry budget and a 10-USDT cumulative equity-loss BUY latch;
- valid SELL signals continue while BUY is paused; a real SELL still requires per-action confirmation;
- resume is explicit and never resets active risk measurements;
- stop does not force liquidation: reject new strategy actions, reconcile in-flight work, then exit;
- failures close safely; `UNKNOWN` is lookup-only by deterministic client order ID and is never resubmitted;
- unexpected restart enters recovery and cannot automatically open a new position.

## 必须通过的验收 / Required acceptance

| ID | 验收条件 / Acceptance criterion |
|---|---|
| MCP-AUTO-001 | 一次启动建立持久化会话；账户指纹、标的、策略版本和风险配置不可漂移。 / One start creates a durable session with immutable account fingerprint, symbol, strategy version, and risk configuration. |
| MCP-AUTO-002 | 行情、策略和风控持续自动运行；每个真实非只读动作必须逐笔明确确认。 / Market, strategy, and risk loops run continuously; every real non-read action requires explicit per-action confirmation. |
| MCP-AUTO-003 | 每笔动作前核对新鲜账户、余额、挂单、成交、规则、手续费和盘口。 / Every action uses fresh account, balance, open-order, fill, rule, commission, and book data. |
| MCP-AUTO-004 | 累计亏损达到 10 USDT 后进入 `BUY_PAUSED`，禁止 BUY 但继续合法 SELL 信号。 / A 10-USDT cumulative loss enters `BUY_PAUSED`, blocking BUY while allowing valid SELL signals. |
| MCP-AUTO-005 | 同一策略事件和订单身份不可重复提交；`UNKNOWN` 只查单。 / A signal/order identity cannot be resubmitted; `UNKNOWN` is lookup-only. |
| MCP-AUTO-006 | 成交、手续费、持仓成本和权益可靠写入账本后才能处理下一动作。 / Fills, fees, position cost, and equity are durably reconciled before the next action. |
| MCP-AUTO-007 | 用户停止后拒绝新策略动作；未决动作核对完成后进入 `STOPPED`。 / Stop rejects new strategy actions and reaches `STOPPED` after in-flight reconciliation. |
| MCP-AUTO-008 | 断网、限流、MCP 错误、过期确认和进程重启均失败关闭，不重复订单。 / Disconnects, rate limits, MCP failures, expired confirmations, and restarts fail closed without duplicate orders. |
| MCP-AUTO-009 | 完成至少 24 小时小额单标的监督运行，包含一笔经确认的策略 BUY 和一笔经确认的策略 SELL。 / Complete at least 24 hours of supervised small single-symbol operation with one confirmed strategy BUY and one confirmed strategy SELL. |
| MCP-AUTO-010 | 全流程不创建或使用 API Key，不新建账户，不切换执行通道。 / The full flow creates or uses no API key, creates no account, and switches no execution transport. |

## 状态机 / Session lifecycle

```text
STOPPED --用户启动--> STARTING --只读核对通过--> RUNNING
                                                |      |
                                       风控触线 |      | 用户停止
                                                v      v
                                           BUY_PAUSED  STOPPING
                                                |      |
                                           用户恢复    | 核对未决动作
                                                v      v
                                             RUNNING  STOPPED

BUY/SELL 候选 -> WAITING_CONFIRMATION -> CONFIRMED -> SUBMITTING -> 终态/账本
                                       \-> REJECTED/EXPIRED -> 本次动作结束
任何不确定订单 -> RECOVERY_ONLY -> 只读查单/对账 -> 原状态或人工处理
```

## 已验证事实与剩余工作 / Verified facts and remaining work

- 现有 `binance-agent-os` MCP 连接、Agentic Spot 账户读取、七项只读核对和完整分页已经验证。
- 历史上已通过该宿主完成约 10 USDT BTC 买入；当前代码仍需完成策略到逐笔确认 MCP 订单的持续编排验收。
- Binance 官方说明 Agentic MCP 不把 API Key 放在设备上，并要求每一笔交易、撤单或划转先确认。
- 剩余工作严格遵循[收尾总计划](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md)的 Phase 1 至 Phase 5。

- The existing `binance-agent-os` connection, Agentic Spot reads, seven-part read preflight, and complete pagination have been verified.
- The host previously completed an approximately 10-USDT BTC buy; current code still needs sustained strategy-to-confirmed-MCP-order orchestration acceptance.
- Binance documents that Agentic MCP keeps API keys off-device and requires confirmation before every trade, cancel, or transfer.
- Remaining work follows Phases 1 through 5 of the [closeout master plan](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md).

官方资料 / Official source: <https://developers.binance.com/en/docs/agent-native/mcp-server/agentic>

## 变更纪律 / Change control

- 每个后续提交必须注明关闭的 `MCP-AUTO-xxx`；没有对应项的功能不进入收尾。
- “继续”“可以”“按计划”只授权既定路线，不授权更换账户、认证或执行接口。
- 任何 MCP/API/Wallet/OAuth/账户路线变化必须先形成决策记录，并取得用户明确批准。
- 不新增策略、UI 美化、多标的、Futures 或 Telegram；只完成最小必要界面和主闭环。
- 每轮报告必须说明验收 ID、测试证据、剩余阻塞和下一阶段。

- Every remaining commit names the `MCP-AUTO-xxx` criterion it closes; unrelated work does not enter closeout.
- “Continue”, “okay”, and “follow the plan” authorize only the established path, not an account, authentication, or transport change.
- Any MCP/API/Wallet/OAuth/account change requires a decision record and explicit operator approval first.
- No new strategy, UI polish, multi-symbol, Futures, or Telegram work; only the minimum UI and core loop are in scope.
- Every progress report states the acceptance IDs, test evidence, remaining blocker, and next phase.
