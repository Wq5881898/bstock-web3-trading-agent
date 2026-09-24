# 桌面真实 MCP 票据流程 / Desktop Live MCP Ticket Flow

账户页现在提供一个**默认关闭**的“启用真实 MCP 票据”开关。它复用现有 Agentic 账户回执和逐笔确认弹窗，不创建账户、不重新 OAuth、不要求 API Key，也不在桌面进程中直接调用 MCP。

The Account tab now exposes an **off-by-default** “Enable live MCP ticket” switch. It reuses the existing Agentic account receipt and per-action confirmation dialog. It creates no account, starts no OAuth, requests no API key, and performs no direct MCP call from the desktop process.

界面的“演练累计亏损”仅影响演练，不再进入真实票据。真实票据现在要求通过 `bstock-mcp-risk` 对现有 Agentic 账户建立一次明确确认的权益基线；此后每次新鲜账户回执自动计算会话累计权益亏损。两次回执之间若 BTC/USDT 余额变化无法由完整成交历史解释，就失败关闭，须人工核查；不会自动假定转账为盈亏。权益基线尚未建立或已过期时，不能生成真实票据。该保护不等于持续 MCP 宿主编排已完成。

The UI's “rehearsal loss” affects rehearsal only and no longer enters a live ticket. Live tickets now require an explicitly confirmed baseline for the existing Agentic account through `bstock-mcp-risk`. Each fresh account receipt then computes cumulative session equity loss. If a BTC/USDT balance change cannot be explained by complete fills, the guard fails closed for manual review; it never silently treats a transfer as PnL. No baseline or a stale receipt means no live ticket. This guard does not complete continuous MCP-host orchestration.

首次设立基线时，在当前已授权 Codex 宿主完成七项只读刷新并严格导入新回执后，先预览，再由操作者确认基线（两个命令都不下单）。现有 BTCUSDT 会话已于 2026-09-23 建立基线，不应重复初始化；后续新鲜回执使用 `bstock-mcp-risk check` 核对累计亏损。

```powershell
bstock-mcp-risk preview --verified-snapshot runtime\desktop\mcp\btcusdt-verified-snapshot.json
bstock-mcp-risk initialize --verified-snapshot runtime\desktop\mcp\btcusdt-verified-snapshot.json --confirm-baseline 'CONFIRM BTCUSDT EQUITY BASELINE'
```

After the existing authorized Codex host refreshes all seven reads and imports a verified receipt, preview and then explicitly confirm the baseline with the commands above. Neither command submits an order. The receipt must be no older than 60 seconds; the order preflight still requires at most 15 seconds.

The current BTCUSDT session established its baseline on 2026-09-23. Do not initialize it again; use `bstock-mcp-risk check` with a new verified receipt to update cumulative loss.

## 操作顺序 / Operator sequence

1. 导出读取请求，让当前已授权的 Codex 任务通过现有 Binance MCP 完成七项读取。
2. 导入严格核验的脱敏账户回执。
3. 勾选真实 MCP 票据开关；加载当前策略候选。
4. 核对账户、标的、方向、类型和精确金额，在 15 秒内逐字输入确认短语。
5. 桌面先把执行日志推进到 `SUBMITTING`，再生成不含凭据的一次性票据。
6. 让当前已授权的 Codex 任务消费该票据一次，并把终态/UNKNOWN 回执写到界面显示的位置。
7. 点击“导入真实终态”；终态成交先写入本地成交账本，再推进执行日志。

1. Export a read request and let the already-authorized Codex task perform all seven reads through the existing Binance MCP connection.
2. Import the strictly verified sanitized account receipt.
3. Enable live MCP tickets and load the current strategy candidate.
4. Verify account, symbol, side, type, and exact amount; enter the exact confirmation phrase within 15 seconds.
5. The desktop durably enters `SUBMITTING`, then writes a credential-free one-shot ticket.
6. Give the ticket once to the already-authorized Codex task and place its terminal/UNKNOWN receipt at the displayed result path.
7. Import the live result; terminal fills commit to the local fill ledger before the execution journal advances.

## 关闭与故障 / Close and failure behavior

- 未确认候选在关闭窗口时自动取消，不产生票据。
- 已确认票据不能取消或重发；关闭窗口只释放本地锁，持久执行日志仍要求查单/导入结果。
- 错误确认、过期确认、账户/金额漂移和不完整回执全部失败关闭。
- `UNKNOWN` 只允许按确定性客户端订单 ID 查单。
- 总体项目批准不等于订单批准；每个真实订单仍需当笔确认。

- An unconfirmed candidate is cancelled on window close and creates no ticket.
- A confirmed ticket cannot be cancelled or resent. Closing releases the local lock while the durable journal still requires lookup/result import.
- Invalid/expired confirmation, account/amount drift, and incomplete receipts fail closed.
- `UNKNOWN` permits deterministic-client-ID lookup only.
- Project approval is not order approval; every real order still requires per-action confirmation.
