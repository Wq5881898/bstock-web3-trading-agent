# MCP 实盘验收记录（脱敏）/ MCP Live Acceptance Record (Sanitized)

> 日期 / Date: 2026-09-22  
> 范围 / Scope: Phase 4 step 1, `MCP-AUTO-003` and `MCP-AUTO-010` evidence  
> 结果 / Result: **通过 / PASS**

## 验收目标 / Acceptance objective

只使用当前任务中已经存在的 `binance-agent-os` MCP 授权，读取并核对既有 Agentic Spot 子账户。不得创建账户、重新 OAuth、创建或使用 API Key、转账、撤单或交易。

Use only the existing `binance-agent-os` MCP authorization in the current task to read and verify the existing Agentic Spot sub-account. Do not create an account, restart OAuth, create or use an API key, transfer funds, cancel an order, or trade.

## 证据 / Evidence

1. MCP 工具发现成功返回官方 Spot 账户只读工具。
2. `spot.getAccount` 成功读取既有 `SPOT` 账户；`canTrade` 为真。
3. 非零资产仅以类别记录：账户持有 USDT 与 BTC。精确余额和账户 UID 不进入 Git。
4. `spot.getOpenOrders(symbol=BTCUSDT)` 返回空列表。
5. 本次验收未调用任何非只读工具，未生成 Binance 订单、撤单或划转。
6. 执行通道保持为既有 Codex MCP → 既有 Agentic 子账户；无 API Key、无新账户、无 Wallet/REST 回退。

1. MCP discovery returned the official read-only Spot account tools.
2. `spot.getAccount` read the existing `SPOT` account successfully and reported `canTrade=true`.
3. Non-zero holdings are recorded by class only: USDT and BTC. Exact balances and account UID are not committed.
4. `spot.getOpenOrders(symbol=BTCUSDT)` returned an empty list.
5. No non-read tool was invoked; no Binance order, cancellation, or transfer was created.
6. The transport remained existing Codex MCP → existing Agentic sub-account, with no API key, new account, or Wallet/REST fallback.

## 尚未通过 / Not yet accepted

- 经策略产生并由用户当笔确认的一笔最小 BUY。
- 经策略产生并由用户当笔确认的一笔 SELL。
- 确认拒绝/过期、MCP 故障、重启恢复、停止和手动恢复的真实宿主演练。
- 24 小时小额单标的监督运行。

- One minimum strategy BUY with explicit per-action confirmation.
- One strategy SELL with explicit per-action confirmation.
- Live-host drills for rejection/expiry, MCP failure, restart recovery, stop, and manual resume.
- A 24-hour supervised small single-symbol run.

这些项目需要独立的当笔确认或经过的真实时间，不能由总体“继续”指令替代，也不能由离线测试冒充。

These items require separate per-action confirmation or elapsed live time. A general “continue” instruction cannot authorize them, and offline tests cannot substitute for them.
