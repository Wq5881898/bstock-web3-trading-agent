# 模拟累计亏损风控 / Paper cumulative-loss control

追加规则后的复验：100项完整测试通过；原生桌面合成验收651轮，含38次故障注入，耗时13.42秒，结果通过。截图已检查新增参数栏与K线显示。证据：`runtime/desktop-acceptance/1788986378789394200/report.json`（本地生成，不提交运行数据）。以下93项为上一阶段记录。

Revalidation after the additional controls: all 100 tests passed. Native desktop synthetic acceptance passed 651 attempts with 38 injected failures in 13.42 seconds; the limits row and candle chart were visually checked. Local evidence: `runtime/desktop-acceptance/1788986378789394200/report.json` (generated runtime data, not committed). The 93-test result below records the preceding phase.

验证：93项完整测试通过，覆盖亏损停买但信号卖出继续、重启/跨日锁定、恢复时保留基准以及非阻塞去重提示。桌面合成刷新验收651轮/38次故障通过（约12.41秒加速测试，不是长时真实行情）。Windows offscreen提示框测试出现原生崩溃，原生Windows平台复验通过；GUI测试改用平台原生后端及会话级QApplication。

Verification: 93 tests passed, covering BUY-only loss latches, continued signal exits, restart/rollover persistence, baseline-preserving resume and nonmodal deduplication. Synthetic desktop acceptance passed 651 attempts/38 injected failures in about 12.41 seconds, not a long-duration market test. Windows offscreen message-box tests crashed natively; the same tests passed on the native Windows backend. GUI tests now use platform-appropriate rendering and a session-lived QApplication.

本仓库新增paper专用日累计亏损控制，默认10，可在桌面启动前修改。按UTC日累计净值变化计算：现金+持仓数量×最近已收盘1m价格，包含浮动损益与实际模拟手续费。跨日基准采用上一轮净值；没有精确午夜价格时不声称获得了精确午夜估值。此为本地模拟账本数值，不涉及真实USDC/USDT换算或账户资金流。

The paper-only daily loss limit defaults to 10 and is editable before desktop startup. UTC daily equity uses cash plus quantity times the latest closed 1m price, including unrealized PnL and simulated fees. Rollover uses the prior observation as baseline, not an exact midnight valuation. These are local simulated units, not actual USDC/USDT conversion or account cash-flow reconciliation.

触发只停止新买入，不强制卖出。原策略卖出和止损保持可执行，需有效行情和新信号。暂停原因与基准保存到状态文件，跨重启、跨日不自动恢复。手动恢复仅在新鲜估值下检查；仍触及日亏损阈值则拒绝释放。恢复不重置当日基准。该阈值不是最终损失上限。

Breaches stop BUYs only, without forced selling. Strategy SELL/stop decisions remain eligible with valid data and new signals. Pause reason/baseline persist across restarts and UTC rollover. Manual resume checks a fresh valuation and cannot bypass an active daily loss breach or reset the daily baseline. The threshold is not a guaranteed final-loss cap.

桌面新增暂停/恢复按钮、买入锁状态和非阻塞去重提示。命令在引擎所属线程下一轮执行；不会撤销已经进行中的模拟评估。暂停指令先落盘，恢复请求等待有效行情。本轮控制只支持paper，不用于quote或live-confirmed。原有链上确认规则不变。

Desktop adds pause/resume buttons, latch status and nonmodal transition alerts. Commands run on the owning engine thread at the next evaluation and do not undo an in-progress simulated evaluation. Pause is persisted; resume waits for valid data. Controls apply only to paper, not quote/live-confirmed; existing wallet confirmation rules are unchanged.

## 追加规则 / Additional controls

本仓库已接入模拟连续亏损3次暂停、每日20次新开仓、开仓间隔60秒、持仓成本上限100。次数只在实际模拟买入时累加，亏损按含双边手续费的平仓净损益判断；盈利或零损益平仓清零连续亏损次数。成本上限按投入资金而非持仓市值计算，当前仍为单仓不加仓模式。

Paper controls now include a three-loss streak latch, 20 daily BUY fills, 60-second entry spacing and a 100 cost cap. Only simulated BUY fills increment entry count. Streak losses use fee-inclusive realized PnL; non-losing closes reset the streak. The cap limits invested cost, not mark-to-market value; pyramiding remains unsupported.

次数、连亏和最后开仓时间持久保存。UTC跨日清零当天开仓次数，但保留暂停和连亏；手动恢复在当日净亏损和次数允许时清零连亏，不重置净值基准。冷却是自动到期的临时买入资格，不锁死会话，也不限制卖出。

Counters and last entry time persist. UTC rollover resets daily entry count while retaining pauses and streaks. Manual resume can acknowledge/reset a streak only when daily loss/count permit, without resetting equity baseline. Cooldown expires automatically and never blocks exits.

桌面默认模拟单笔100；新增参数在启动前可编辑，运行时锁定。CLI历史单笔默认20未改变。桌面参数本身尚未保存为用户预设，重启应用后需检查设置；风险状态不会因此清零。旧文件没有新增计数器时从0开始，不宣称恢复了其缺失的历史次数。

Desktop entry budget now defaults to 100; additional limits are editable before start and locked while running. The CLI's historical 20 default is unchanged. Desktop preferences are not yet persisted, so review them on application restart; persisted risk state is not reset. Missing legacy counters start at zero, without claiming reconstruction of unavailable history.

后续更新：单组桌面参数持久化已完成，详见[参数保存说明](DESKTOP_SETTINGS.md)；上方“尚未保存”为上一阶段记录。未完成：真实资金流调整、账户级实盘风控、多策略账户归并及多策略预设管理。旧模拟持仓成本不完整时仍按前次兼容性说明要求核对。

Follow-up: single-set desktop input persistence is now implemented; see [Desktop preferences](DESKTOP_SETTINGS.md). The earlier non-persistence note records the preceding phase. Still pending: actual cash-flow adjustment, account-level live controls, multi-strategy account consolidation and multi-strategy preset management. Legacy paper positions with missing cost remain subject to the prior review requirement.
