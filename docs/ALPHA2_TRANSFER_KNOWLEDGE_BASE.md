# bStock 项目向 Alpha2 回传的经验库 / Lessons for Alpha2 and Other Projects

> 2026-09-23，只读核对 `D:\projectQ\alpha2` 后整理。本文是**迁移知识与验收清单，不是修改 Alpha2 的授权**；不复制运行目录、账户文件、OAuth Token、API Key、UID、余额或订单记录。Alpha2 当前工作树有其他窗口的未提交改动，实施须由 Alpha2 窗口自行评估、分支化和测试。 / Curated after read-only inspection of Alpha2. This is a transfer guide, not permission to edit Alpha2 or copy credentials/runtime state. Its current worktree has unrelated changes.

针对尚未进入 Alpha2 Spot 实盘链路的订单恢复、成交账本、权益风控和故障测试，另见[真实 Spot 安全资产移交主文档](ALPHA2_LIVE_SPOT_SAFETY_HANDOFF.md)与[可复制到 Alpha2 窗口的实施提示](ALPHA2_LIVE_SPOT_SAFETY_IMPLEMENTATION_PROMPT.md)。两者区分已提交源码、未提交实验和 Alpha2 现有骨架；不授权真实下单。 / For remaining live-Spot safety assets and their acceptance gates, use the detailed handoff and implementation prompt; neither authorizes live orders.

## 1. 首先保留正确的系统边界 / Keep the boundaries

```text
行情源 / market feed -> 规范化事件 / normalized event
  -> 统一策略 / strategy -> 风控与持仓 / risk and position
  -> 交易意图 / intent -> 产品执行适配器 / venue adapter
  -> 终态、成交、费用 / order, fills, fees -> 持久账本 / durable ledger
```

AI/对话 Skill 可以解释状态、接受明确的操作命令、协助人工确认，但不应取代确定性的 K 线处理、策略状态机和订单恢复。MCP 是一种可选执行/数据接口，不是策略核心。Alpha2 已有统一策略注册表和模拟盘引擎；本项目应回传**契约与故障经验**，而不是再塞进第二套并行策略引擎。[既有回迁设计](ALPHA2_UNIFIED_STRATEGY_BACKPORT_PLAN.md)提供历史实现建议，但应以 Alpha2 当前代码和测试为准。

An assistant Skill is an operator interface, not a substitute for deterministic trading state. Transfer contracts and failure lessons, not a second parallel strategy engine.

## 2. 可迁移知识索引 / Transfer map

| 主题 / Area | 本项目可验证经验 / Evidence | Alpha2 吸收方式 / Adoption |
|---|---|---|
| 已闭合 K 线与数据新鲜度 / Closed candles and freshness | [公共行情](EXCHANGE_SPOT_OBSERVER.md)、`market_data.py`、`spot_observer.py`：不把未闭合 K 线或过期账户快照当新信号。 / Closed-bar and stale-snapshot guards. | 接在 Alpha2 现有 `data/providers/binance_spot.py` 与 `app/paper_trading_session.py` 入口；先固定 golden replay，再改变运行路径。 / Apply at existing feed/session seam after replay fixtures. |
| aggTrade、Median、Range / Tick strategies | [策略集成](STRATEGY_INTEGRATION.md)、[统一策略架构](UNIFIED_STRATEGY_ARCHITECTURE.md)、`median_ticks.py`、`range_ticks.py`、`range_guard.py`、`range_auto.py`：连续 ID、乱序/缺口、预热、参数锁定、恢复一致性。 / Gap/order/warmup/locked-parameter semantics. | Alpha2 已有自己的 Range/Median/注册表；对照行为和故障测试，**不要整包覆盖**。 / Compare behavior and tests; do not overwrite current implementations. |
| 策略与产品分离 / Strategy versus product | `strategy_contract.py`、`strategy_registry.py`、[统一策略架构](UNIFIED_STRATEGY_ARCHITECTURE.md)：策略输出决定，产品标签限制可用性；执行器才处理 Spot/Web3/Futures 规则。 / Strategy decisions precede product execution. | 保留 Alpha2 `strategy/registry.py` 为唯一注册入口；让 Alpha、Spot、bStock 与未来 Futures 共享定义但隔离行情/账户/费用。 / Keep one registry; separate venue-specific inputs and execution. |
| 模拟盘不是实盘 / Paper is not live | `engine.py` 和桌面模拟盘可复用信号/风控，但本项目真实 MCP 另有预检、确认、终态。 / A paper fill is not an exchange fill. | Alpha2 的 `app/paper_trading_session.py` 当前实例化 `sim/engine.py` 的 `PaperSimulationEngine`；实盘必须有独立执行适配与对账，不能把 `place_order` 字符串替换视作完成。 / Add an explicit execution seam and reconciliation; no simple function swap. |
| 账户绑定与授权 / Account binding and auth | [宿主桥接](MCP_HOST_BRIDGE.md)、[真实只读验收](MCP_LIVE_ACCEPTANCE_20260922.md)：现有 Codex MCP 身份、Agentic 子账户、无本地凭据；普通 Virtual Sub 不是同一账户。 / Auth belongs to host and account identity must be verified. | Alpha2 若采用任何实盘接口，应独立写明账户类型、授权主体、权限与撤销方式；不要复制此仓库的 Agentic 凭据或假定 Spot API Key 可操作同一账户。 / Write a fresh account/credential decision; copy no credentials. |
| 每笔预检 / Per-action preflight | [执行安全](MCP_EXECUTION_SAFETY.md)、`mcp_confirmed_host.py`：余额、挂单、成交、手续费、规则、盘口、工具 schema 和金额精度均需新鲜。 / Fresh account/rules/fee/book and schema validation. | 变成 Alpha2 交易意图到执行适配器之间的门禁；测试过滤器变更、余额不足和过期数据。 / Gate the intent-to-adapter boundary. |
| 幂等和 UNKNOWN / Idempotency and unknown orders | [执行交接](MCP_EXECUTION_HANDOFF.md)、`execution_safety.py`、`execution_lock.py`：确定性客户端订单 ID；提交前落盘；超时/崩溃后只查单，不重发。 / Durable submit state and lookup-only recovery. | 实盘适配器必选，不应污染策略公式；按交易所实际订单接口校验身份与查询语义。 / Required in any live adapter; verify venue semantics. |
| 成交与费用账本 / Fill and fee ledger | [Spot 成交账本](SPOT_FILL_LEDGER.md)、`spot_accounting.py`、`spot_equity_risk.py`：终态订单、完整成交分页、手续费资产、持仓成本与余额交叉核对。 / Reconcile terminal orders, fills, fees, cost and balances. | Alpha2 的 paper accounting 与 live accounting 分开输入、统一输出可审计状态；UNKNOWN 未解除前禁止下一单。 / Separate paper/live sources and block on unresolved orders. |
| 风控语义 / Risk semantics | [自动化风控](AUTOMATION_POLICY.md)：默认累计亏损 10 USDT 停 BUY、不自动清仓，合法 SELL 仍可进行，用户手动恢复。 / BUY latch is not an exit suppression. | 按账户/产品/会话定义亏损基线，加入暂停跨重启与同一账户不得重置规避的测试；不要直接套用 10 USDT 到不同资金规模。 / Parameterize per account/product; test durable latch. |
| 产品符号与成本 / Symbol and economics | [Spot 观察](EXCHANGE_SPOT_OBSERVER.md)确认 `NVDAB` 不是 Binance 交易所 Spot 有效标的；bStock/Web3 有 Gas、授权和 DEX 成本。 / Venue-specific symbol and cost. | NVDAB 保留 Web3/bStock 路线；Spot、Alpha、Futures 各自校验交易对、精度、费用。先用真实成本回放，不把模拟收益当实盘收益。 / Validate each product separately and replay real costs. |
| 真实执行研究 / Empirical execution research | Alpha2 原始交接 `docs/bstock_web3_handoff_20260903.md` 记录 NVDAB 20 USDC 买卖闭环在含授权和 Swap Gas 后约亏 0.5713 USD（约 -2.8564%）；当时 110 个有交易的策略计入 Gas 后均未盈利，且七个前向窗口未覆盖上涨状态。 / One small round trip lost about 2.8564% including Gas; no traded strategy was profitable after Gas in that historical replay. | 这些是**历史样本，不是未来收益估计**。先更新成本档案和独立前向验证，再讨论 Web3 自动实盘；保留旧 run，不回改研究结果。 / Treat as historical evidence, update cost profiles and forward validation before any live upgrade. |
| 安全发布 / Safe release | [产品基准](AUTONOMOUS_TRADING_PRODUCT_BASELINE.md)、[收尾总计划](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md)：路线更换需决策记录，Git 不存私有账户数据；本仓库离线测试 2026-09-23 为 505 passed。 / Explicit route decision and redacted evidence. | Alpha2 单独建立实盘验收与秘密扫描；保留目前脏工作树，不能从本项目直接 cherry-pick 整批改动。 / Separate acceptance and secret scan; preserve ongoing work. |

## 3. 给 Alpha2 的优先顺序 / Recommended order for Alpha2

1. **先冻结现有 paper 信号**：把 Alpha、Spot、bStock 的代表性 closed-bar/tick 输入做成 golden fixtures，保持策略版本与退出语义。/ Freeze current paper decisions with representative golden fixtures.
2. **明确实盘产品与账户决策**：一个产品、一种执行通道、一个受控账户；MCP、Spot API、Alpha 私有接口和 Web3 钱包不能被称为可互换的“同一账户”。任何 API Key 或 OAuth 路线都需用户另行明确批准。/ Decide product, transport and account explicitly before implementation.
3. **抽出执行边界**：`StrategyDecision -> RiskApproval -> OrderIntent -> ExecutionAdapter -> VerifiedExecutionReceipt`；模拟盘与真实执行共用决策，不共用虚构成交。/ Share decisions, not fake fills.
4. **先只读影子运行**：实时行情、信号、账户/规则查询、成本估算和拒单原因；无写权限。/ Run live-data shadow signals without trading.
5. **再做最小单标的真实闭环**：提交前门禁、明确确认或经批准的自动化授权模式、确定性 ID、终态/UNKNOWN 查单、成交/手续费入账、断电恢复。/ Only then test one symbol's order lifecycle under the chosen authorized transport.
6. **最后再扩产品**：多币种、Alpha、Futures、Web3 各自有不同精度、费用、权限和风险；不得靠复制一整套策略库扩展。/ Expand products through adapters and tags, not duplicate strategies.

## 4. 不应复制的东西 / Do not transplant

- `runtime/`、账户绑定文件、真实回执、风险基线和本地订单/成交文件；它们属于当前账户与会话。/ No runtime or account data.
- 当前 Codex OAuth 授权、旧失效 client metadata、自建 MCP 客户端实验或任何 API Key。/ No credentials or withdrawn OAuth experiments.
- 专为 Codex 文件交接设计的 15 秒候选/回执格式，除非 Alpha2 明确采用同一人工确认 MCP 宿主模型；原则是新鲜度与幂等，而非照抄时间常数。/ Transfer invariants, not the Codex-specific file protocol or its timing constant by default.
- `NVDAB` 作为 Binance 交易所 Spot 标的、手动 MCP 卖单作为策略自动卖出证据、或“505 个离线测试”等同真实实盘验收。/ Do not promote a venue mismatch or offline proof to live acceptance.
- 把提交工具返回的订单号当唯一终态依据：原始 bStock 真实卖出样本中，提交返回号与最近订单列表号不同，需用合约、数量、时间、实际到账和链上交易哈希交叉匹配；此案例属于 Web3，不应生搬到 Binance Spot 的订单语义。/ Do not assume one backend order identifier settles an on-chain trade; cross-reconcile venue-native evidence.

## 5. 给其他项目的最小吸收包 / Minimal reusable package

先复制**文档和测试思想**：统一策略契约、闭合事件/缺口用例、风控状态机、提交/UNKNOWN 故障注入、终态与费用对账。只有当目标项目的数据模型和依赖兼容且 golden parity 通过后，才复制或安装 `strategy.py`、`strategy_contract.py`、`strategy_registry.py` 及其所需的 Median/Range/Regime 模块；优先以包依赖或单一来源维护，避免策略分叉。验收必须在目标项目独立运行，原仓库通过不代表目标项目通过。

First reuse documentation and test invariants. Copy/install the portable strategy modules only after data-model compatibility and golden parity are proven; keep one source of truth and run the target project's own acceptance.

官方接口边界 / Official interface boundaries: [Binance Agentic MCP](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic), [Binance Spot REST](https://developers.binance.com/en/docs/products/spot/rest-api).
