# Binance 交易所 Spot 长期观察 / Binance Exchange Spot Observer

## 为什么增加这一层 / Why this layer exists

2026-09-22 的真实只读核对确认：现有 bStock 策略链能够读取 `NVDAB`，但 Binance Agent OS 的交易所 `spot.exchangeInfo(symbol=NVDAB)` 返回无效标的。此前“策略观察 NVDAB”和“MCP 买入 BTC”是两段不同标的的成功实验，不能视为同一条自动交易闭环。

Live read-only validation on 2026-09-22 confirmed that the existing bStock strategy path can read `NVDAB`, while Binance Agent OS exchange `spot.exchangeInfo(symbol=NVDAB)` rejects it as an invalid symbol. The earlier NVDAB strategy observation and MCP BTC purchase were successful experiments on different instruments, not one automated trading loop.

当前 MCP 原型因此固定为 `BTCUSDT`：公开交易所 K 线 → 统一 MTF 策略 → 只观察信号。NVDAB 仍保留在 bStock/Web3 与 Agentic Wallet 通道，绝不静默切换。

The MCP prototype is therefore fixed to `BTCUSDT`: public exchange candles → unified MTF strategy → observe-only signal. NVDAB remains on the bStock/Web3 and Agentic Wallet path, with no silent fallback.

## 安全边界 / Safety boundary

`bstock-spot-observe`：

- 只调用 Binance 公开 `exchangeInfo` 和 K 线接口；
- 可读取本地已经严格验证、账户指纹匹配的脱敏回执以构造持仓视图；
- 每根闭合 K 线最多求值一次，重启后保持去重；
- 原子保存状态、最新观察和最新非重复 BUY/SELL 证据；
- 所有输出固定包含 `mode=OBSERVE_ONLY`、`execution_eligible=false`、`transport=null`；
- 持仓快照超过15秒时明确标记不新鲜；
- 不调用 MCP、不生成提交票据、不访问 API Key、不下单。

`bstock-spot-observe`:

- calls only public Binance `exchangeInfo` and candle endpoints;
- may read a locally verified sanitized receipt whose account fingerprint matches, solely to construct the position view;
- evaluates each closed candle at most once and preserves deduplication across restarts;
- atomically saves state, the latest observation, and the latest non-duplicate BUY/SELL evidence;
- always emits `mode=OBSERVE_ONLY`, `execution_eligible=false`, and `transport=null`;
- marks a position snapshot stale after 15 seconds;
- never calls MCP, creates a submission ticket, accesses an API key, or submits an order.

## 当前验收 / Current acceptance

真实公开 `BTCUSDT` 1m/5m K 线已进入统一 MTF 策略。使用本地已验证的既有 BTC 持仓视图后，观察器在连续闭合 K 线上产生 `SELL / five_minute_trend_reversed`，重复轮询被去重。由于账户持仓快照过期，这些信号明确不可执行，且没有生成订单候选。

Real public `BTCUSDT` 1m/5m candles now feed the unified MTF strategy. With the locally verified existing BTC position view, the observer produced `SELL / five_minute_trend_reversed` on successive closed candles and deduplicated repeated polls. Because the position snapshot was stale, the signals were explicitly non-executable and no order candidate was created.

## 下一道门 / Next gate

策略信号转为 MCP 候选前，当前 Codex 宿主必须重新完成七项只读预检，并提供不超过15秒的新鲜账户证据。真实订单仍需当笔确认。长期观察成功不等于交易授权。

Before a strategy signal can become an MCP candidate, the current Codex host must repeat all seven read-only preflight calls and provide account evidence no older than 15 seconds. A real order still requires per-action confirmation. Successful long-running observation is not trading authorization.
