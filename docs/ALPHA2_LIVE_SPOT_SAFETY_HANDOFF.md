# Alpha2 真实 Spot 安全资产移交 / Live Spot Safety Handoff

> 2026-09-23。面向 `D:\projectQ\alpha2` 及其他确定性交易系统的**设计与测试移交**，不是直接复制代码或启用实盘的授权。本文件只修改 bStock 仓库；Alpha2 当前由另一工作窗口维护，已有未提交改动。执行接口、账户、权限及任何真实订单均需另行决策。 / Design and test handoff only; no live-trading authorization or Alpha2 code change.

## 1. 移交结论与证据状态

Alpha2 已在提交 `710675f` 落地统一策略契约、注册表、多市场/产品标签和插件，见其 `src/alpha2/strategy/{contract,definition,registry}.py` 与 `docs/unified_strategy_registry_phase4_completion.md`。其 `app/paper_trading_session.py` 仍使用 `PaperSimulationEngine`；`execution/spot.py` 有注入式 `SpotExecutionAdapter`，但在当前源码中只被导出和单测使用，未发现接入 Spot 持续实盘会话。**不要再回迁一套策略引擎，也不要把纸面成交当作交易所成交。**

本移交的四类可复用资产是：①提交不确定性和幂等；②真实成交、手续费、持仓成本账本；③账户权益与 BUY 暂停风控；④行情事件与账户快照的新鲜度/恢复故障测试。它们目前主要是本仓库的离线模块和有限 MCP 宿主验收，**不是 Alpha2 已有的生产级 Spot 实盘能力**。`HEAD` 指本仓库已提交源码；`WORKTREE` 指尚未提交的实验，不作为稳定依赖。

| 资产及状态 | 参考源码与测试 | 可吸收的原则 | 当前限制 |
|---|---|---|---|
| `HEAD` 订单准备/日志 | `src/bstock_web3/execution_safety.py`、`execution_lock.py`；`tests/test_execution_safety.py`、`test_execution_lock.py` | 事件身份、单写入方、先记录 `SUBMITTING`、`UNKNOWN` 只查单 | 模块本身不发送订单；其 JSON 日志原子替换但未显式 `fsync`，不能直接宣称断电持久性 |
| `HEAD` Spot 成交账本 | `src/bstock_web3/spot_accounting.py`；`tests/test_spot_accounting.py` | 逐成交 ID 幂等、基础/报价手续费、部分成交、平均成本、完整分页 | 第三资产（如 BNB）非零手续费会拒绝；`history_complete=True` 只是调用方声明，需外部验证 |
| `HEAD` 权益/策略风控 | `src/bstock_web3/spot_equity_risk.py`、`automation_policy.py`；`tests/test_spot_equity_risk.py`、`test_automation_policy.py` | 保守估值、资金流调整、BUY 锁存、SELL 保留、手动恢复 | `SpotEquityRiskLedger` 是 **UTC 日亏损**；策略字段 `daily_equity_loss` 与产品文案“会话累计亏损”口径不一致，迁移前必须冻结新定义 |
| `HEAD` 观察器；`WORKTREE` 新鲜度修正 | `src/bstock_web3/spot_observer.py`；`tests/test_spot_observer.py` | 闭合事件去重、账户证据过期时不能生成可执行动作、重启可重评 | “过期快照不消耗事件、旧动作改写 HOLD”在当前未提交工作树中；不得标作已发布能力 |
| `WORKTREE` 会话权益实验 | `src/bstock_web3/mcp_equity_guard.py`、`tests/test_mcp_equity_guard.py` | 人工确认基线、完整成交解释余额变动、未知划转失败关闭 | 尚未提交且绑定 MCP 回执；仅借鉴测试思想，不直接复制到 Alpha2 |

先核对这些源码与目标分支的实际差异；本项目的已有[经验总表](ALPHA2_TRANSFER_KNOWLEDGE_BASE.md)是索引，不代表表内每项都已在 Alpha2 实施。

## 2. Alpha2 建议的最小集成边界

保持 Alpha2 的一个策略注册表和原有 Provider。新增**独立的真实执行路径**，不要在 `PaperSimulationEngine` 中塞交易所返回，也不要让策略插件调用网络：

```text
Spot Provider + closed event
  -> existing StrategyRegistry / StrategyPlugin decision
  -> intent mapper (account, symbol, event ID, side, frozen amount)
  -> live risk gate + fresh read-only account evidence
  -> durable execution journal -> authorized venue adapter
  -> lookup of order + complete fills + balances
  -> live fill/equity ledger -> next event
```

建议用 Alpha2 自己的 `StrategyContext.source_id`、`UnifiedStrategyDecision`、策略实例 ID/实现版本和闭合 bar/tick generation 构造**稳定事件身份**。`OrderIntent` 至少绑定账户身份、产品/市场、标的、策略实例与版本、事件 ID、方向、基础币数量或报价币预算、创建时间和参数快照。价格、滑点与余额用于下单前校验，但不能让一次重新报价悄悄生成同一信号的第二个订单身份。

Alpha2 的 `SpotExecutionAdapter` 只是可替换的 transport seam。先明确目标是 Agentic MCP、交易所 API、Alpha 账户还是其他接口；它们的账户身份、授权、字段名和查单语义不能互换。**本文不批准新建 API Key、复用 Codex OAuth、选择某个账户或执行真实写入。**若仍走币安 Agentic MCP，每笔写操作继续遵守其用户确认要求。不要复制本仓库的 15 秒文件票据、Codex 执行器、Agentic 账户绑定文件或任何 `runtime/` 数据。

## 3. 订单恢复契约：先持久化，再提交，未知只查询

对每一个被风控允许的策略事件，事务性预留唯一 `intent_id` 和一个由**冻结的事件/订单身份**推导的 `client_order_id`；同一事件再次到达只返回已有记录。目标接口若支持客户端订单 ID，映射和查询参数必须由该适配器按当期官方 schema 验证。**不能把交易所对客户端 ID 的开放订单唯一性误当成永久去重保证**：本地 journal 才负责跨重启的一次性语义。

```text
SIGNAL_SEEN -> RISK_APPROVED -> RESERVED -> SUBMITTING
                                          |              |
                              拒绝/过期取消        提交回执或不确定结果
                                                         v
                                              NEW / PARTIALLY_FILLED / UNKNOWN
                                                         |
                                   查单、查成交、查余额 -> RECONCILED / 人工处理
```

**在任何网络写入前**，把 `SUBMITTING` 与最终请求身份持久提交，并取得单写入方锁；数据库事务/检查点和崩溃语义由 Alpha2 自己实现及测试。网络超时、5xx、客户端进程崩溃、回执丢失、解析不全都进入 `UNKNOWN`，禁止自动重发原单或换 ID 再下单。先按 venue 支持的客户端 ID/订单 ID 查单，再核对成交、挂单和余额；短时查无结果不能无条件证明“未下单”，仍须保持隔离或人工裁决。`NEW`、`PARTIALLY_FILLED` 是未决状态；`CANCELED`/`EXPIRED` 也可能已有部分成交。只有终态和完整成交入账后，才允许下一笔冲突动作。

本仓库 `intent_fingerprint` 当前还包含 `reference_price` 与 `risk_day`；同一闭合策略事件若重新报价或跨日，可能得到不同指纹。**这段组合不应照抄**。Alpha2 应以不可变策略事件键为主，金额及方向一旦冻结即不修改；如需改变，作为新的用户/策略决策并明确取消旧意图。`ExecutionJournal` 的本地 JSON 替换未显式 `fsync`，不满足生产级断电证明；要通过故障注入确认先落盘、再网络写入的顺序。

官方 Spot 文档明确说明：`-1007 TIMEOUT` 或 5xx 可能是执行状态未知，应查询状态；`newClientOrderId` 是开放订单范围内的唯一性条件。具体字段与查询能力随**所选接口**核验，不能把 REST 示例当 MCP 参数表。[Spot 通用说明](https://developers.binance.com/en/docs/products/spot/rest-api)、[Spot 下单与查单参考](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/trade)。

## 4. 真实成交、费用与持仓成本契约

成交明细而非 `place_order` 的 ACK 或模拟撮合是记账来源。以 `venue/account/symbol/trade_id` 为幂等键，校验订单归属、成交时间、方向、基础币数量、报价币金额、`commission` 与 `commissionAsset`；稳定排序并拒绝旧成交缺失或内容改变。分页完整性必须由 adapter 的游标、时间范围与账户/订单交叉核对来证明，不能只传一个 Boolean。

参考本仓库平均成本规则：买入基础币手续费减少净入库数量；买入报价币手续费增加成本；卖出基础币手续费增加出库量；卖出报价币手续费减少收入。部分成交立即逐笔入账，即使随后撤单；每笔成交精确入账一次，再比较订单累计成交、账户总余额与本地持仓。账本写入失败不得将 journal 推进 `RECONCILED`，重启后先恢复账本再处理新信号。

本仓库会拒绝非零第三资产手续费（如 BNB），这适合失败关闭但**不等于生产可覆盖所有账户**。Alpha2 要么增加第三资产数量和时点汇率的审计流水，要么明确禁止此费用配置并阻止真实交易。也要独立处理历史起始持仓/成本、人工交易、转账和 dust；若无法解释账户差额，就暂停交易并请求人工核对。优先适配 Alpha2 现有持久层，不复制本项目整份 JSON 历史账本。

## 5. 权益亏损与 BUY 暂停：先统一口径

这里有两个不同的量，**移交前不能混称**：

- `spot_equity_risk.py`：UTC 日基线，跨日重建，净外部资金流调整；用于“日亏损”。
- 原产品目标：从操作者确认的会话基线起计算累计权益亏损；超过默认 10 USDT 锁住新 BUY，跨重启保留，SELL 仍按策略信号和其他安全门禁处理。未提交的 `mcp_equity_guard.py` 是无外部资金流假设下的实验，而非已发布的通用算法。

建议 Alpha2 先写独立决策记录，固定亏损窗口、账户范围、期初持仓/现金、是否按最高权益回撤、入金/出金如何调整、不同手续费资产如何计价、重启和手动恢复是否重置基线。若沿用原需求，候选公式为 `current_equity = quote_total + base_total × conservative_bid`、`adjusted_equity = current_equity - verified_net_external_flow_since_baseline`、`cumulative_loss = max(0, baseline_equity - adjusted_equity)`；这是**设计候选**，须经目标账户和费用模型验收，不能直接把本仓库的 `daily_equity_loss` 字段改名。

首次基线需操作者明确确认；重启不能自动重建较低基线以解除停买。`BUY_PAUSED` 只阻止新 BUY，不能压掉合法 SELL，但账户不新鲜、订单未决或余额不明时 SELL 仍可被全局安全门禁阻止。手动恢复不能清除仍达到阈值的数字。损失闩锁不是最大损失保证：跳价、手续费和已有持仓继续波动可能使实际损失超过阈值。资金流缺失、解释不了的余额变化、倒退时间和身份漂移均失败关闭。

## 6. 事件新鲜度与恢复

Alpha2 已有 Spot Provider、闭合 K 线/tick generation 和 checkpoint 逻辑，因此只移交**跨行情与账户的联合门禁**：

1. 未闭合或重复事件不得生成第二个意图；策略版本/参数及持仓锁定状态随事件持久化。
2. 账户余额、挂单、成交、手续费、交易规则、盘口分别有来源和观察时间；任何必需项过期，信号可展示但不可提交。
3. 账户证据过期时不得把该闭合事件永久标记为“已执行/已消费”；刷新后若事件仍在策略允许窗口，可用同一事件 ID 重算。旧的可执行候选要失效，不得等文件/界面再次显示时误执行。
4. 恢复后先查未决订单和成交，再恢复策略事件流。市场行情新鲜不代表账户证据新鲜；账户刷新也不延长已过期订单计划。

本仓库观察器的 15 秒阈值和文件路径是 MCP 手工交接的实现参数，**不是 Alpha2 应照抄的全产品 SLA**。生产阈值应按数据源、接口延迟、账户风险和实际运行测量确定，并有明确过期处理。

## 7. Alpha2 分阶段吸收与验收矩阵

建议在 Alpha2 自己的分支由其窗口实施；每阶段先冻结 golden 输入/输出，再接下一个边界：

| 阶段 | 仅允许的工作 | 退出条件 |
|---|---|---|
| P0 决策与基线 | 确定目标产品/账户/授权接口、会话累计亏损口径；记录现有 `StrategyRegistry`/paper golden 决策 | 不修改实盘配置；没有新账户、密钥或真实订单 |
| P1 纯离线账本/风控 | Alpha2 自己的 LiveFill、AccountEvidence、EquityBaseline、BUY latch；模拟和实盘账本分开 | 下表 F/R 用例通过，且同一策略 golden 决策不变 |
| P2 假 adapter 恢复 | 意图键、journal、锁、`SUBMITTING`、`UNKNOWN` 查单和终态导入；注入网络/磁盘/进程故障 | 下表 O 用例通过；零真实外部写入 |
| P3 只读影子运行 | 单 Spot 标的，实时行情和所选账户只读查询；显示“会拒绝/允许”原因，不提交 | 代表性事件、过期/重启、手续费和账户差额可审计 |
| P4 经另行批准的最小实盘 | 必须先明确选择并授权 transport 与账户，再经当笔适用的授权/确认进行小额 BUY/SELL | 订单终态、成交、余额、费用、亏损与断电恢复全部一致；否则停止扩大范围 |

| 编号 | 必需的离线/影子验收情形 |
|---|---|
| O1 | 同一闭合事件重复到达、重启重放、重新报价后仍只有一个冻结意图与客户端订单身份。 |
| O2 | `SUBMITTING` 持久化成功、网络调用前进程终止；恢复只查单，不自动提交。 |
| O3 | 调用超时/5xx/回执丢失、查单暂时无结果、订单后来出现；全过程没有第二次下单。 |
| O4 | 两进程争同一账户/事件，只有一个取得锁；磁盘写失败时不发生网络写。 |
| O5 | 部分成交后取消、拒绝、过期、`NEW`/`PARTIALLY_FILLED`/`FILLED` 和订单身份漂移分别正确处理。 |
| F1 | 基础币、报价币手续费分别调整数量/成本/收入；第三资产手续费无汇率时拒绝。 |
| F2 | 完整分页、重复/缺失/篡改成交、同毫秒不同成交 ID、历史起始持仓、人工交易或转账差额均有确定结果。 |
| F3 | 账本写失败不推进 journal；重启重复导入同一成交不双计，订单累计成交与余额可交叉核对。 |
| R1 | 会话基线跨重启保留，入金不伪装盈利、出金不伪装亏损；不完整资金流水失败关闭。 |
| R2 | 亏损达到阈值后 BUY 暂停且 SELL 策略事件仍可进入其他安全门禁；手动恢复不能绕过当前亏损。 |
| R3 | UTC 日亏损与会话累计亏损分别测试，跨日不错误清除累计闩锁。 |
| S1 | 未闭合/重复行情事件、过期账户快照、旧候选残留、刷新后同事件重评、重启先查单均失败关闭且不丢合法事件。 |

运行本仓库参考测试（只读、无账户连接）：

```powershell
.venv\Scripts\python -m pytest tests/test_execution_safety.py tests/test_execution_lock.py tests/test_spot_accounting.py tests/test_spot_equity_risk.py tests/test_automation_policy.py tests/test_spot_observer.py tests/test_mcp_execution_result.py
```

这些测试通过只证明**源仓库的离线契约**。Alpha2 必须有自己针对最终 adapter、持久层和运行路径的对应测试；不能用本仓库测试数量代替其验收。

## 8. 明确不移交与使用纪律

- 不复制 `runtime/`、真实订单/余额/成交、账户指纹、Token、OAuth 会话、API Key 或钱包凭据；不直接 `cherry-pick` 本仓库整批变更。
- 不复制 Codex MCP 文件票据、`tool_execute` 审批实验、对话 Skill、人工逐笔确认 UI；除非 Alpha2 明确选择同一交互模式。
- 不让策略插件依赖 Binance/MCP/数据库；不覆盖 Alpha2 更完整的 32 类型注册表和已有 Spot paper 会话。
- 不把当前 `ExecutionMode.UNATTENDED` 枚举理解为已被币安 MCP 授权的无人确认写入；模式能力必须由所选接口和用户决策证明。
- 不把 `spot_equity_risk.py` 的日亏损直接作为原需求的会话累计亏损，也不把未提交的 `mcp_equity_guard.py` 作为稳定发布模块。
- 文档和离线测试不构成下单授权。任何真实写入必须在 Alpha2 窗口另取明确的账户、接口、权限和单笔操作决定。

下一工作窗口可直接使用[实施提示](ALPHA2_LIVE_SPOT_SAFETY_IMPLEMENTATION_PROMPT.md)。
