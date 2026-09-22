# Spot API自动交易路线 / Autonomous Spot API route

状态：离线原型，**不是可宣称完成的实盘产品**。本轮没有读取API密钥、登录账户、转账或下单。

Status: offline prototype, **not a live-accepted product**. This work did not read API credentials, access an account, move assets or place orders.

## 已实现 / Implemented

- 环境变量密钥、固定Binance生产/测试网域名、HMAC签名、仅允许Spot读取和`POST /api/v3/order`；不含提现、划转或取消订单。`POST`不重试。 / Environment-only credentials, allowlisted production/testnet hosts, HMAC signing, narrow Spot reads and one order endpoint; no withdrawals, transfers or cancellations. POST is never retried.
- 单账户指纹、单标的、单MTF策略和风控配置的持久会话；重启进入`RECOVERY_ONLY`。 / Durable account-fingerprint/symbol/MTF/risk binding; restart enters `RECOVERY_ONLY`.
- 每笔下单前核对全量成交/订单分页、现货规则、手续费、盘口、余额、挂单和净值；不明资金变化失败关闭。 / Before each order: complete paginated fills/orders, Spot filters, commission, book, balances, open orders and equity; unexplained balance movements fail closed.
- 100 USDT预算、10 USDT累计权益亏损暂停BUY、SELL继续、手动恢复；确定性订单ID、`UNKNOWN`只查单。 / 100-USDT budget, 10-USDT cumulative equity-loss BUY latch, continued SELL, manual resume, deterministic client IDs and lookup-only UNKNOWN.
- 同一启动会话中MTF信号可连续触发BUY/SELL；必须先从成交历史验证上笔订单并写入账本，再接受下一笔。 / MTF signals can trigger successive BUY/SELL actions in one start; the prior order must appear in exchange fills and be persisted before another action.

## 运行形式 / Runtime shape

安装项目后，`bstock-auto run --testnet --state-dir <dedicated-directory>`在当前终端前台常驻；另一个终端使用`bstock-auto stop --state-dir <same-directory>`请求安全停止。重启后的恢复需要显式`--resume`；风控暂停恢复使用`bstock-auto resume-buys --state-dir <same-directory>`，仍会重新检查亏损指标。轮询默认60秒。

After installation, `bstock-auto run --testnet --state-dir <dedicated-directory>` remains in the foreground. From another terminal use `bstock-auto stop --state-dir <same-directory>`. Restart requires explicit `--resume`; a BUY latch requires `bstock-auto resume-buys --state-dir <same-directory>` and cannot bypass active loss limits. Polling defaults to 60 seconds.

生产环境必须显式改用`--live`，并由操作员在**专用账户**配置`BINANCE_API_KEY`与`BINANCE_API_SECRET`。请勿把密钥贴到聊天、配置文件或Git仓库。不要在现有有资金的Agentic账户上直接假设API权限可用；账户归属与余额必须先独立核验。测试网不等于原Agentic账户。

Production requires explicit `--live` and `BINANCE_API_KEY`/`BINANCE_API_SECRET` from a **dedicated account**. Never paste secrets into chat, config files or Git. Do not assume API credentials control the existing funded Agentic account; independently verify ownership and balances. Testnet is not the Agentic account.

## 尚未通过的产品验收 / Still unaccepted

1. 尚无真实API账户归属、权限、余额和密钥IP限制核验。 / No live API account ownership, permission, balance or key IP-allowlist verification.
2. 尚无完整常驻进程断网/限流/突然退出/停止请求故障注入，以及24小时小额BUY→策略SELL验收。 / No complete service-level disconnect/rate-limit/crash/stop fault injection or 24-hour small BUY→strategy SELL acceptance.
3. 常驻入口目前只接MTF；Median/Range虽在统一策略库中，仍需各自实时逐笔数据适配和恢复验收。 / The service currently wires MTF only; Median/Range are in the shared registry but need live trade-data adapters and recovery acceptance.
4. 原Agentic账户的MCP只读连接保留，但API路径不会复用其OAuth授权、身份或资金。 / The original Agentic MCP read connection remains; the API route does not reuse its OAuth authorization, identity or funds.

官方技术依据 / Primary technical references: [Binance Spot REST API](https://developers.binance.com/en/docs/products/spot/rest-api), [Spot trading endpoints](https://developers.binance.com/en/docs/binance-spot-api-docs/rest-api/trading-endpoints).
