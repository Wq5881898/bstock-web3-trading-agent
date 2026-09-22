# 自动交易产品基准 / Autonomous Trading Product Baseline

> 本文档是本项目产品目标的最高优先级来源。README、用户指南、技术设计或代码与本文冲突时，以本文为准，冲突内容必须纠正，不能静默降低产品目标。
>
> This is the highest-priority product source of truth. Conflicting README, guide, design or implementation text must be corrected; the product goal must never be silently downgraded.

## 唯一主目标 / Single primary objective

用户选择单一标的、统一策略和风险参数，发出一次启动命令。此后程序持续获取行情、产生策略信号、核对绑定的Spot账户、自动买入或卖出、查询订单终态并更新账本，直到用户发出结束命令。原目标优先使用Agentic账户；当前MCP宿主不支持无人值守写操作后，经用户明确批准，另建独立API账户路线，不得假称二者是同一账户。

The operator selects one symbol, a registered strategy and risk settings, then issues one start command. The process continuously reads market data, evaluates signals, reconciles the bound Spot account, buys or sells automatically, resolves terminal order state and updates its ledger until the operator issues stop. The original preference is the Agentic account; after the current MCP host proved unsuitable for unattended writes, the operator separately approved an independent API-account route. These accounts must never be represented as identical without verification.

逐笔人工确认不是主产品流程，只允许作为诊断和最小金额验收模式。启动授权必须绑定实际执行账户指纹、单一标的、策略配置和风险配置；它不是无限账户授权。

Per-order confirmation is diagnostic/minimum-size acceptance mode only, not the product path. The start authorization is bound to the actual execution account fingerprint, one symbol, strategy configuration and risk configuration; it is not unrestricted account authority.

## 已确定的MVP范围 / Fixed MVP scope

- Binance Spot；MCP优先。2026-09-22用户已明确批准单独实现API自动执行路线；仍不自动在MCP、API或Agentic Wallet之间切换；
- 单标的、单策略、单持仓；多币种和Futures不阻塞MVP；
- 默认单笔预算100 USDT，累计权益亏损10 USDT后锁定新买入；
- 最大持仓成本、每日开仓次数、连亏次数和开仓冷却继续使用现有风控；
- BUY暂停后，已有持仓仍按原策略SELL信号自动退出；
- 风控恢复必须由用户明确发出，不重置仍然有效的风险数字；
- 用户结束时不强制清仓：停止接受新策略动作，先核对未决订单，再退出；
- 网络故障自动退避重连；订单结果不确定时只按确定性客户端订单ID查单，绝不重发；
- 意外进程重启进入安全恢复状态，不自动新开仓；用户明确恢复后继续。

- Binance Spot; MCP first. On 2026-09-22 the operator explicitly approved a separate API-backed autonomous route; there is still no silent MCP/API/Agentic Wallet fallback;
- one symbol, one strategy and one position; multi-symbol and Futures do not block MVP;
- default 100-USDT order budget and a 10-USDT cumulative equity-loss BUY latch;
- retain the existing position-cost, daily-entry, losing-streak and cooldown controls;
- after a BUY latch, an existing position still follows automatic strategy SELL signals;
- resume is explicit and never resets active risk measurements;
- stop does not force liquidation: stop accepting new strategy actions, reconcile any in-flight order, then exit;
- retry network reads with backoff; an uncertain order is lookup-only by deterministic client order ID and is never resubmitted;
- an unexpected process restart enters safe recovery and cannot open a new position until explicit resume.

## 必须通过的验收 / Required acceptance

| ID | 验收条件 / Acceptance criterion |
| --- | --- |
| AUTO-001 | 一次启动后进入持久化`RUNNING`会话；账户、标的、策略和风险配置不可漂移。 / One start creates a durable `RUNNING` session with immutable account, symbol, strategy and risk bindings. |
| AUTO-002 | `RUNNING`中连续多笔BUY/SELL不请求逐笔确认。 / Multiple BUY/SELL actions run without per-order prompts. |
| AUTO-003 | 每笔订单前使用新鲜账户、余额、挂单、成交、交易规则、手续费和盘口数据重新风控。 / Every order uses fresh account, balance, open-order, fill, rule, commission and book data. |
| AUTO-004 | 累计亏损达到10后自动进入`BUY_PAUSED`，禁止BUY但不压制合法SELL。 / A 10-unit loss enters `BUY_PAUSED`, blocking BUY while allowing valid SELL. |
| AUTO-005 | 同一策略事件和订单身份不可重复提交；UNKNOWN只查单。 / A signal/order identity cannot be resubmitted; UNKNOWN is lookup-only. |
| AUTO-006 | 成交、手续费、持仓成本和权益先可靠写入账本，再允许下一笔。 / Fills, fees, position cost and equity are durably reconciled before the next order. |
| AUTO-007 | 用户结束后不再接受新策略动作；未决订单核对完成后进入`STOPPED`。 / Stop rejects new strategy actions and reaches `STOPPED` after in-flight reconciliation. |
| AUTO-008 | 断网、限流、MCP错误和进程重启均失败关闭，不产生重复订单。 / Disconnects, rate limits, MCP errors and restarts fail closed without duplicate orders. |
| AUTO-009 | 至少完成24小时小额单标的运行，并完成一次自动买入和一次策略自动卖出。 / Complete at least 24 hours of small single-symbol operation with one automatic BUY and one strategy-driven automatic SELL. |
| AUTO-010 | MCP不满足AUTO-002时停止开发并报告阻塞；未经用户明确批准不得启用API。 / If MCP cannot satisfy AUTO-002, stop and report the blocker; API requires separate explicit approval. |

## 状态机 / Session lifecycle

```text
STOPPED --用户启动--> STARTING --核对通过--> RUNNING
                                           |      |
                                  风控触线 |      | 用户结束
                                           v      v
                                      BUY_PAUSED  STOPPING
                                           |      |
                                      用户恢复    | 核对未决订单
                                           v      v
                                        RUNNING  STOPPED

任何不确定订单 -> RECOVERY_ONLY -> 只读查单/对账 -> 原状态或人工处理
```

## 当前执行通道决定与剩余验收 / Transport decision and remaining acceptance

2026-09-22只读核验确认：现有`binance-agent-os` MCP连接仍然有效，Agentic Spot账户`canTrade=true`，Spot账户、订单、成交和`spot.newOrder`工具均可见。但当前Codex MCP宿主的工具约束明确要求：执行任何非GET操作前必须向用户确认。因此这个宿主可以持续读取，不能直接满足`AUTO-002`的无人值守写操作。

Read-only verification on 2026-09-22 confirmed that the existing `binance-agent-os` connection is active, the Agentic Spot account reports `canTrade=true`, and account/order/fill/`spot.newOrder` tools are visible. However, the current Codex MCP host explicitly requires user confirmation before every non-GET operation. It can support sustained reads but cannot directly satisfy unattended write criterion `AUTO-002`.

用户已批准单独实现Binance Spot API自动执行路线。这个API凭据绑定的是签发它的交易所账户，**不能假定就是原来有资金的Agentic子账户**；首次运行前必须核验具体账户、权限、余额和资金归属。现有MCP授权和资金不作迁移、不自动回退。代码阶段的离线测试不等于实盘授权或24小时验收。

The operator approved a separate Binance Spot API execution route. API credentials bind to the exchange account that issued them; **they must not be assumed to access the previously funded Agentic subaccount**. Verify account, permissions, balance and funding before any live run. Existing MCP authorization and funds are not migrated or used as an automatic fallback. Offline code tests are not live authorization or 24-hour acceptance.

## 变更纪律 / Change control

- 每个后续提交必须注明关闭的`AUTO-xxx`；没有对应项的功能不进入收尾分支；
- 不新增策略、UI美化、多币种、Futures、Telegram或逐笔确认功能；
- CI必须包含“一次启动、多次自动信号、零确认回调”的端到端假宿主测试；
- 每轮报告只回答：关闭了哪个验收项、还剩哪个阻塞、是否更接近24小时闭环。

- Every remaining commit must name the `AUTO-xxx` criterion it closes;
- no new strategy, UI polish, multi-symbol, Futures, Telegram or per-order-confirmation work;
- CI must exercise one start, multiple automatic signals and zero confirmation callbacks against a fake host;
- every progress report states only which criterion closed, the remaining blocker, and progress toward the 24-hour loop.
