# bStock 阶段性收口 / bStock Milestone Closeout

> 2026-09-24。此处的“收口”仅指当前仓库的对话式 MCP 助手、离线安全资产与 Alpha2 移交完成；**不代表原定持续自动实盘目标完成**。/ This milestone closes the conversational MCP assistant and offline safety-asset handoff, not the original continuous live-trading objective.

## 为什么降级 / Why the scope was reduced

原定产品是“一次启动、持续监控行情与策略、按风控产生信号、经 MCP 逐笔确认并完成真实买卖与恢复”。当前代码实现了其中的策略、候选、风控和故障恢复的离线或单次环节，却没有把观察器、新鲜账户读取、确认、下单、成交对账和下一轮运行接成持续闭环。现有非交互 Codex 宿主对通用 `tool_execute` 的审批边界也未解决：该入口既能转发读取也能转发写入，不能为自动读取而无条件授权。**这不是“只差一次配置”或“测试已通过即可自动交易”。**

因此本项目未达到原始主目标，是一次明确的范围降级，而不是把原目标改名为已完成。对话式下单本身主要依靠已有 MCP 及账户授权，本仓库对这种一次性操作的增量有限；投入最多、可复用价值更高的资产是 K 线/策略信号、风险、成交账本和订单恢复契约，已经形成面向 Alpha2 的移交材料。用户已告知 Alpha2 的代码吸收完成；本仓库未在此文件中替 Alpha2 声称其真实交易验收通过。

The original product was a once-started, continuous market/strategy/risk loop that would confirm each MCP trade and reconcile it before the next cycle. The repository has offline and one-shot components, but has not connected observation, fresh private reads, confirmation, execution, reconciliation, and continuation into one durable loop. The non-interactive Codex host's generic `tool_execute` approval boundary is unresolved: it can forward both reads and writes, so blanket approval is not a safe shortcut. This is a substantive shortfall, not a configuration-only issue.

The project therefore missed its original primary objective and explicitly reduced scope. Conversational one-off trading relies largely on the existing MCP authorization, so this repository adds comparatively little to that particular workflow. Its more substantial reusable work is market/strategy signals, risk, fill accounting, and order-recovery contracts, documented for Alpha2. The operator reports that Alpha2 has absorbed code; that report is not a claim that Alpha2 has passed live-trading acceptance.

## 已交付 / Delivered

- 现有 Codex MCP 宿主和既有 Agentic 子账户的人工逐笔交互路径；本项目不保存 OAuth Token 或 API Key，也不自动改用其他交易接口。历史人工确认交易不能记为策略自动成交。
- `BTCUSDT` 公共 K 线观察、策略候选、账户回执严格导入、权益基线和成交账本、一次性提交票据及不确定结果的只查单恢复契约；其中许多环节已由离线测试覆盖，真实订单仍须经宿主按笔确认。
- 单次宿主读取后的策略周期；测试过新鲜回执到 `HOLD` / `RUNNING` 的真实只读路径，但不等于持续运行或策略实盘交易。
- 面向 Alpha2 的[经验库](ALPHA2_TRANSFER_KNOWLEDGE_BASE.md)、[Spot 安全资产移交](ALPHA2_LIVE_SPOT_SAFETY_HANDOFF.md)与[实施提示](ALPHA2_LIVE_SPOT_SAFETY_IMPLEMENTATION_PROMPT.md)。Alpha2 应保留自身统一策略引擎，吸收契约和故障测试，而非复制本仓库的 MCP 文件交接。

The existing Codex-hosted Agentic account has a per-action conversational path. Offline contracts cover public BTCUSDT candles, candidate generation, strict receipts, equity/fill accounting, one-shot tickets, and lookup-only recovery. A single live read-only cycle reached `HOLD` / `RUNNING`. The Alpha2 handoff transfers safety principles and tests, not a second strategy engine.

## 未交付 / Not delivered

1. 观察信号自动唤醒 MCP 宿主、连续只读刷新、逐笔确认、成交导入后继续下一轮的完整编排。非交互 Codex 宿主对通用 `tool_execute` 的审批边界仍未解决；不能为了自动读取而无条件放行可转发写操作的工具。
2. 策略驱动的真实 BUY/SELL、完整故障演练和 24 小时监督验收。人工交易、离线测试和只读单次周期都不能替代这些验收。
3. 无人确认交易、合约、多标的、Telegram 或云端常驻服务；这些不是本次发布能力。

Continuous host orchestration, strategy-driven live BUY/SELL, full failure drills, and 24-hour supervised acceptance remain open. No unattended writes, futures, multi-symbol execution, Telegram, or hosted daemon is claimed.

## 发布与后续边界 / Release and next boundary

- 本地验收：完整 `pytest -q` 通过；wheel 构建成功；`bstock-mcp-cycle`、`bstock-mcp-host-cycle`、`bstock-mcp-risk` 的 CLI 帮助入口通过；准备提交的源码/文档未发现密钥、Token 或邮箱模式。以上均不是策略实盘验收。
- 本次只发布代码、测试和脱敏文档；`runtime/`、账户回执、余额、订单/成交 ID 和所有凭据保持本地且不得进入 Git。
- Alpha2 是后续确定性策略实盘路径的主要吸收方。本仓库可继续作为对话式 MCP 操作与安全契约参考，但不在这里绕过 MCP 审批门禁，也不默认切换到 API Key、Wallet 或新 OAuth 客户端。
- 若将来恢复原持续自动交易目标，须先单独决定接口与授权主体，再按[收尾总计划](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md)完成剩余 Phase 4 验收；当前阶段性收口不把该阶段标为完成。

Only sanitized code, tests, and documentation belong in Git. Any future continuous runner needs a separate transport/authorization decision and the remaining Phase 4 evidence. This milestone does not mark Phase 4 complete.
