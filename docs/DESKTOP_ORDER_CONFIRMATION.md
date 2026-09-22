# 桌面逐笔确认 / Desktop per-order confirmation

## 当前实现 / Current implementation

桌面账户页现已接通**只读演练**，但没有启用真实提交入口。只有先导入本次会话严格核验的Codex回执，再载入尚未过期的schema v3候选计划，才能由`ConfirmedSpotExecutor.preview()`生成确认弹窗。预览必须包含绑定账户、完整MARKET订单参数、一次性确认短语和不超过15秒的到期时间。

The desktop Account tab now wires a **read-only rehearsal**, while live submission remains disabled. A strictly verified Codex receipt from the current session and an unexpired schema-v3 candidate are both required before `ConfirmedSpotExecutor.preview()` can produce the dialog. The preview contains the bound account, complete MARKET arguments, a one-time phrase and an expiry no more than 15 seconds away.

弹窗以纯文本显示：

- Agentic账户引用；
- 币对、BUY/SELL方向与MARKET类型；
- 精确`quoteOrderQty`或`quantity`；
- 确定性客户端订单ID；
- 一次性确认短语和剩余秒数。

The dialog displays the Agentic account reference, symbol, side, MARKET type, exact quote/base amount, deterministic client order ID, one-time phrase and remaining seconds as plain text.

用户必须完整输入一次性短语，确认按钮才可用。确认只发出一次事件；取消、窗口关闭、程序退出或到期都发出取消事件，不能复用本次预览。真正执行器仍会再次使用常数时间比较、检查到期时间、账户风险、市场规则、跨进程锁和日志状态，因此GUI不是唯一安全边界。

The user must type the exact one-time phrase. Confirmation emits once; cancel, close, application exit or expiry cancels the preview, which cannot be reused. The executor independently rechecks the phrase, expiry, account risk, market rules, process lock and journal state, so the GUI is not the sole safety boundary.

确认演练成功后，程序只写入`REHEARSE_CONFIRMED_SPOT_ORDER`报告。该报告强制包含`dispatch_prohibited=true`、`required_tool=null`和`execution_phase=PREPARED`，与真实`McpSpotSubmissionTicket`类型不兼容；它不把日志推进到`SUBMITTING`，也不调用`spot.newOrder`。确认短语不会写入报告。

After a successful rehearsal confirmation, the app writes only a `REHEARSE_CONFIRMED_SPOT_ORDER` report. It requires `dispatch_prohibited=true`, `required_tool=null` and `execution_phase=PREPARED`, and is type-incompatible with a live `McpSpotSubmissionTicket`. It neither advances the journal to `SUBMITTING` nor calls `spot.newOrder`; the confirmation phrase is not persisted.

## 桌面演练步骤 / Desktop rehearsal flow

1. 在账户页导出Codex只读请求，由**现有已授权**Codex任务执行；本程序不发起OAuth。
2. 把脱敏宿主回执放到页面显示的位置，点击“导入Codex回执”。
3. 使用`bstock-mcp-plan`生成新候选；源码运行默认读取`runtime/mcp/latest-order-plan.json`。
4. 如需测试累计亏损闸门，设置“演练累计亏损”；它只参与演练，不是生产权益账本。
5. 点击“载入候选并演练”，在15秒内完整输入显示的一次性短语。
6. 检查`runtime/desktop/mcp/rehearsal/`中的报告；报告不可提交。

1. Export a Codex read request from the Account tab and have the **existing authorized** Codex task execute it; this app starts no OAuth.
2. Put the sanitized host receipt at the displayed location and import it.
3. Create a fresh candidate with `bstock-mcp-plan`; a source checkout reads `runtime/mcp/latest-order-plan.json` by default.
4. Optionally set Rehearsal loss to exercise the cumulative-loss gate; it is not a production equity ledger.
5. Select Load candidate rehearsal and type the exact one-time phrase within 15 seconds.
6. Inspect the report under `runtime/desktop/mcp/rehearsal/`; it is non-dispatchable.

## 尚未接线 / Not wired yet

账户页明确显示“submission disabled”。演练按钮不会把模拟/报价事件转换为真实订单，GUI线程也不执行网络调用。生产接线仍需：

1. 现有Codex宿主的Binance MCP授权仍然有效；
2. 支持的宿主通过真实`tools/list` schema门禁；
3. 完整账户/成交/订单/盘口/规则/资金流水对账；
4. 用真实Spot权益账本替代“演练累计亏损”输入；
5. 在另行批准实盘后，由Codex宿主消费真实单次提交票据；
6. 成交后导入终态回执更新账本，UNKNOWN仅查单。

The Account tab explicitly says submission is disabled. Its rehearsal button never converts a paper/quote event into a live order, and no OAuth/network operation runs in this process. Production wiring still requires a real Spot-equity ledger, separately approved Codex-host dispatch of a genuine one-shot ticket, and terminal-receipt import with lookup-only UNKNOWN recovery.

本模块不会保存确认短语、Token、原始账户快照或凭据。演练报告只保存脱敏账户引用、绑定指纹、最终订单参数和不可提交状态。

The module persists no phrase, token, raw account snapshot or credential. Its rehearsal report contains only the sanitized account reference, binding fingerprint, final order arguments and non-dispatchable state.
