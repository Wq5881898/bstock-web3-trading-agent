# MCP逐笔确认执行器 / Per-order-confirmed MCP executor

## 本轮范围 / Scope

`mcp_confirmed.py`提供可离线验证的执行器，注入`caller(name, arguments)`后可表达`spot.newOrder`和`spot.getOrder`调用。[确认会话边界](MCP_CONFIRMED_HOST.md)提供工具白名单、双层参数校验及运行时schema门禁，但没有网络、OAuth或桌面下单接线。2026-09-21已通过现有Codex宿主只读取并验证这两个真实工具的schema；没有调用写工具。网络与认证仍归现有Codex宿主，不能称作生产下单适配器已完成。

The module supplies an offline-testable executor using an injected decoded MCP tool caller. It has no HTTP, OAuth or desktop submission wiring. On 2026-09-21, the existing Codex host read and validated the live schemas for both tools without invoking either write tool. Network and authentication still belong to Codex; this is not a completed production adapter.

## 固定顺序 / Fixed sequence

```text
Intent + reconciled evidence + verified symbol rules
  → risk checks + held execution lock
  → durable PREPARED + deterministic client order ID
  → exact account/order preview + one-shot confirmation (15 seconds)
  → fresh evidence + risk/amount revalidation
  → durable SUBMITTING
  → ≤15-second single-submission ticket (confirmation phrase omitted)
  → one injected or supported-host spot.newOrder call
  → SUBMITTED / FILLED / REJECTED
  → timeout or invalid result: UNKNOWN → spot.getOrder only
```

确认绑定的是执行器内保存的订单，外部修改返回的预览字典不会修改实际订单。错误确认不提交；正确确认被消费后，即使重新核对失败也不能复用。取消预览会丢弃确认；已经预留的同一策略信号不会再次准备。`USER_CONFIRMED`是新增的离线准备模式，不能免除逐笔确认；`UNATTENDED`仅保留为通用离线契约兼容值，不是MCP产品模式。

Confirmation binds to the executor's saved order. Mutating the returned preview cannot alter submission. Invalid confirmation never submits; an exact confirmation is consumed even if revalidation fails. Cancel discards confirmation but retains the signal reservation. `USER_CONFIRMED` is an offline preparation mode, not a confirmation bypass. Legacy `UNATTENDED` remains only for the venue-neutral offline contract, not the MCP product.

有未决`SUBMITTING/SUBMITTED/UNKNOWN`记录时禁止准备另一笔订单。重启的`SUBMITTING`先转`UNKNOWN`，按客户端订单ID查单；查单失败或查不到不能推断“未提交”，也不能重发。部分成交仍为`SUBMITTED`；取消/过期等终态使用日志`REJECTED`，但返回值保留已成交数量，绝不把撤销等同于零成交。

Any unresolved submission blocks new preparation. Restarted `SUBMITTING` becomes `UNKNOWN` and is looked up by client order ID. Failed/missing lookup never proves non-submission and never allows resending. Partial fills remain `SUBMITTED`. Canceled/expired terminal orders map to journal `REJECTED`, but returned executed amounts remain nonzero where applicable.

## 失败关闭规则与限制 / Fail-closed rules and limitations

- 必须是可交易Spot标的，支持MARKET和quoteOrderQty；验证LOT_SIZE及适用于市价的notional过滤器。
- SELL必须精确符合数量步长，不能静默向下取整。含dust或额外非零MARKET_LOT_SIZE过滤器时，先拒绝，等待宿主实现完整账户/过滤器核对。
- 金额在策略、风控和确认阶段始终使用Decimal字符串。真实MCP schema把`quantity`和`quoteOrderQty`声明为JSON number，因此只在最终宿主边界转换；只有JSON浮点文本可精确回到同一个Decimal时才允许，否则在调用前失败关闭。
- 当前SELL金额门槛估算使用策略参考价，不代表实时盘口/平均价格完整校验。手续费、价格偏移、free/locked资金、适用附加过滤器和实际成交记账仍必须在真实宿主接线阶段完成。
- 执行器返回订单结果但没有自动把成交写到账户资金账本。已新增[独立成交账本](SPOT_FILL_LEDGER.md)，支持部分成交、基础/报价手续费及成本回放；真实宿主接线、权益风险基准及转账调整仍待完成。仅靠返回FILLED不能宣告资金闭环完成。
- 日志是原子替换，不承诺断电级fsync持久性。写盘异常会阻止提交或保留SUBMITTING供查单，不自动重试。

The minimal rule gate rejects unsupported/dust cases instead of silently rounding. Live schema compatibility is now proven for `spot.newOrder` and lookup-only `spot.getOrder`: exact internal Decimal strings are converted to JSON numbers only at the final boundary, with lossy values rejected before a tool call. A real host must still validate book/average-price, fee/slippage, free versus locked funds and every applicable filter, and integrate fills into the account ledger. Atomic replacement is not a power-loss/fsync durability guarantee. No live-ready or closed-loop accounting claim is made.

## 验证 / Validation

当前完整回归424项通过，其中执行器离线测试覆盖确认/过期/消费、账户变化、余额/权限/亏损/未决/过期快照、锁失效、超时只查单、提交前落盘、重启恢复、部分成交、停买继续卖出、dust与金额规则、写盘失败、预览篡改、取消与订单身份不匹配；文件交接还覆盖账户/信号绑定、确认后原子SUBMITTING、15秒单次票据、风险元数据一致性、交易规则资产一致性、篡改/过期拒绝和确认短语不落盘。未执行真实订单。

The full suite currently passes 424 tests, covering the confirmed executor, live-schema numeric adaptation, risk/market identity consistency and the file-safe one-shot submission-ticket boundary. No live order was performed.

官方确认要求 / Official confirmation policy: [Binance MCP Server](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic).
