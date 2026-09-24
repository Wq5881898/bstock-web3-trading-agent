# Binance 交易所 Spot 长期观察 / Binance Exchange Spot Observer

## 为什么增加这一层 / Why this layer exists

2026-09-22 的真实只读核对确认：现有 bStock 策略链能够读取 `NVDAB`，但 Binance Agent OS 的交易所 `spot.exchangeInfo(symbol=NVDAB)` 返回无效标的。此前“策略观察 NVDAB”和“MCP 买入 BTC”是两段不同标的的成功实验，不能视为同一条自动交易闭环。

Live read-only validation on 2026-09-22 confirmed that the existing bStock strategy path can read `NVDAB`, while Binance Agent OS exchange `spot.exchangeInfo(symbol=NVDAB)` rejects it as an invalid symbol. The earlier NVDAB strategy observation and MCP BTC purchase were successful experiments on different instruments, not one automated trading loop.

当前 MCP 原型因此固定为 `BTCUSDT`：公开交易所 K 线 → 统一 MTF 策略 → 只观察信号。NVDAB 仍保留在 bStock/Web3 与 Agentic Wallet 通道，绝不静默切换。

The MCP prototype is therefore fixed to `BTCUSDT`: public exchange candles → unified MTF strategy → observe-only signal. NVDAB remains on the bStock/Web3 and Agentic Wallet path, with no silent fallback.

## 安全边界 / Safety boundary

`bstock-spot-observe`：

- 只调用 Binance 公开 `exchangeInfo` 和 K 线接口；
- 每轮重新读取本地已经严格验证、账户指纹匹配的脱敏回执以构造持仓视图；
- 只有账户快照新鲜时才把闭合 K 线记为已处理，重启后保持去重；过期快照下的观察可在刷新后重算，不能变成订单候选；
- 原子保存状态、最新观察和最新非重复 BUY/SELL 证据；持仓证据过期或读取失败时以 `HOLD` 覆盖旧动作文件；
- 所有输出固定包含 `mode=OBSERVE_ONLY`、`execution_eligible=false`、`transport=null`；
- 持仓快照超过15秒时明确标记不新鲜；
- 已核验的交易规则用于区分可交易持仓与不可交易 dust；观察策略只使用可交易部分，原始余额和成本仍完整保留在回执与账本；
- 不调用 MCP、不生成提交票据、不访问 API Key、不下单。

`bstock-spot-observe`:

- calls only public Binance `exchangeInfo` and candle endpoints;
- re-reads a locally verified sanitized receipt whose account fingerprint matches on each poll, solely to construct the position view;
- marks a closed candle processed only with fresh account evidence and preserves deduplication across restarts; an observation with stale evidence may be re-evaluated after a refresh and cannot become an order candidate;
- atomically saves state, the latest observation, and the latest non-duplicate BUY/SELL evidence; stale or unreadable position evidence replaces any previous action file with `HOLD`;
- always emits `mode=OBSERVE_ONLY`, `execution_eligible=false`, and `transport=null`;
- marks a position snapshot stale after 15 seconds;
- uses verified exchange rules to separate tradable position from untradable dust for strategy evaluation, while preserving the raw balance and cost in the receipt and ledger;
- never calls MCP, creates a submission ticket, accesses an API key, or submits an order.

## 当前验收 / Current acceptance

真实公开 `BTCUSDT` 1m/5m K 线已进入统一 MTF 策略。使用本地已验证的既有 BTC 持仓视图后，观察器在连续闭合 K 线上产生 `SELL / five_minute_trend_reversed`，重复轮询被去重。由于账户持仓快照过期，这些信号明确不可执行，且没有生成订单候选。

2026-09-22 经用户逐笔确认的 `BTCUSDT` 手动市价 SELL 已由现有 Agent OS MCP 确认成交。这不是策略 SELL 验收。旧持仓回执不再代表成交后账户；观察器即使继续展示原始策略信号，也必须把动作文件置为 `HOLD / position_snapshot_not_fresh`，直到宿主提供新的严格核验回执。公开文档和 Git 提交不记录订单号、UID 或精确余额；本地忽略提交的运行日志保留对账信息。

Real public `BTCUSDT` 1m/5m candles now feed the unified MTF strategy. With the locally verified existing BTC position view, the observer produced `SELL / five_minute_trend_reversed` on successive closed candles and deduplicated repeated polls. Because the position snapshot was stale, the signals were explicitly non-executable and no order candidate was created.

On 2026-09-22, an operator-confirmed manual `BTCUSDT` market SELL was filled through the existing Agent OS MCP. It does not count as the strategy-SELL acceptance. The prior position receipt no longer represents the post-trade account; the observer must mark its action file `HOLD / position_snapshot_not_fresh` until the host supplies a newly verified receipt. Public docs and Git commits omit the order ID, UID, and exact balances; ignored local runtime records retain reconciliation details.

## 下一道门 / Next gate

策略信号转为 MCP 候选前，当前 Codex 宿主必须重新完成七项只读预检，并提供不超过15秒的新鲜账户证据。真实订单仍需当笔确认。长期观察成功不等于交易授权。

Before a strategy signal can become an MCP candidate, the current Codex host must repeat all seven read-only preflight calls and provide account evidence no older than 15 seconds. A real order still requires per-action confirmation. Successful long-running observation is not trading authorization.
