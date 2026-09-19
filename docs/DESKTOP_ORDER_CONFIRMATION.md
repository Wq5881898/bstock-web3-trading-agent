# 桌面逐笔确认 / Desktop per-order confirmation

## 当前实现 / Current implementation

桌面现已具备非模态真实Spot订单确认弹窗，但没有启用真实提交入口。只有经过`ConfirmedSpotExecutor.preview()`准备的严格预览才能传入弹窗，内容必须包括绑定账户、完整MARKET订单参数、一次性确认短语和不超过15秒的到期时间。

The desktop now contains a nonmodal live-Spot confirmation dialog, but no live submission entry point is enabled. It accepts only a strict preview produced by `ConfirmedSpotExecutor.preview()`: bound account, complete MARKET arguments, a one-time phrase and an expiry no more than 15 seconds away.

弹窗以纯文本显示：

- Agentic账户引用；
- 币对、BUY/SELL方向与MARKET类型；
- 精确`quoteOrderQty`或`quantity`；
- 确定性客户端订单ID；
- 一次性确认短语和剩余秒数。

The dialog displays the Agentic account reference, symbol, side, MARKET type, exact quote/base amount, deterministic client order ID, one-time phrase and remaining seconds as plain text.

用户必须完整输入一次性短语，确认按钮才可用。确认只发出一次事件；取消、窗口关闭、程序退出或到期都发出取消事件，不能复用本次预览。真正执行器仍会再次使用常数时间比较、检查到期时间、账户风险、市场规则、跨进程锁和日志状态，因此GUI不是唯一安全边界。

The user must type the exact one-time phrase. Confirmation emits once; cancel, close, application exit or expiry cancels the preview, which cannot be reused. The executor independently rechecks the phrase, expiry, account risk, market rules, process lock and journal state, so the GUI is not the sole safety boundary.

## 尚未接线 / Not wired yet

账户页明确显示“submission disabled”。当前确认弹窗只能由经过测试的注入方法调用，没有按钮从模拟/报价监控直接生成真实订单，也没有在GUI线程中执行网络调用。完整接线仍需：

1. 项目OAuth Client Metadata公网可用；
2. 同一短期OAuth会话通过真实`tools/list` schema门禁；
3. 完整账户/成交/订单/盘口/规则/资金流水对账；
4. 策略信号转换为统一`OrderIntent`并通过风险策略；
5. 后台线程预览，GUI确认，后台线程复核并提交；
6. 成交后重新读取并更新账本，UNKNOWN仅查单。

The Account tab explicitly says submission is disabled. No button converts a paper/quote monitor event into a live order, and no network operation runs on the GUI thread. Full wiring still requires public client metadata, first live schema acceptance in the same short-lived OAuth session, complete account reconciliation, signal-to-intent risk checks, background preview/submit, and post-fill reconciliation with lookup-only UNKNOWN recovery.

本模块不会保存确认短语、Token、账户资料或订单预览，也不会在日志输出这些内容。

The module persists and logs none of the phrase, token, account data or order preview.
