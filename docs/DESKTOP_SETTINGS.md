# 桌面参数保存 / Desktop preferences

最新格式 / Latest schema: v6同时保存MTF/Median、固定/防御/Auto/Adaptive Range参数，兼容读取完整v1至v5文件；见[Median桌面说明](MEDIAN_DESKTOP.md)与[Range策略](RANGE_DESKTOP.md)。 / v6 persists MTF/Median plus fixed, guarded, Auto and Adaptive Range inputs and reads exact v1–v5 files; see [Median desktop](MEDIAN_DESKTOP.md) and [Range strategies](RANGE_DESKTOP.md).

后续更新 / Follow-up: v2现在包含可编辑的MTF EMA参数，并兼容读取完整v1预设；见[策略编辑说明](STRATEGY_INTEGRATION.md)。下文为初次参数保存阶段记录。 / v2 now includes editable MTF EMA parameters and reads exact v1 presets compatibly; see [Strategy editing](STRATEGY_INTEGRATION.md). The initial phase record follows.

最新验证 / Latest validation: **283 tests passed**. Native synthetic desktop acceptance: **650 attempts, 38 injected failures, 13.41s**, passed. Local report: `runtime/desktop-acceptance/1789101345204910200/report.json`. This accelerated fixture is not a long-duration real-market test. 验证未授权账户或下真实订单 / Validation did not authorize an account or place real orders.

桌面提供“保存参数”和“读取已保存参数”。修改后需要点击保存；启动、停止或关闭窗口不会隐式覆盖文件。再次打开应用时读取已保存参数，但始终停止，必须人工点击启动。当前保存一组参数，不是多策略预设管理器；策略仍为现有MTF EMA。

Use **Save settings** after editing, or **Load settings** to restore the saved inputs. Start, stop and close do not implicitly overwrite preferences. Application startup restores saved inputs but never starts monitoring automatically. This is one saved input set, not a multi-strategy preset manager; the existing MTF EMA strategy is unchanged.

## 内容和位置 / Contents and location

保存标的、paper/quote模式、单笔金额、日累计亏损阈值、持仓成本上限、每日开仓次数、连亏次数和冷却秒数。`preferences.json`与桌面状态文件同目录；可由`BINANCE_AGENT_RUNTIME_DIR`指定。文件不包含API Key、OAuth Token、账户信息、持仓、累计损益、暂停原因或恢复指令。不要把运行目录提交GitHub。

Saved fields are symbol, paper/quote mode, order budget, daily loss limit, cost cap, daily entry limit, loss streak limit and entry cooldown. `preferences.json` lives alongside desktop state files, optionally under `BINANCE_AGENT_RUNTIME_DIR`. It contains no API keys, OAuth tokens, account details, positions, PnL, pause reasons or resume commands. Do not commit runtime directories.

运行期间及等待停止期间禁止保存和读取。读取参数不会改动账本或解除风控暂停。调整风控阈值会影响下一次手动启动后的判断，因此启动前应核对数值；本功能不提供阈值修改审计历史。

Save/load are disabled while running or waiting for shutdown. Loading does not alter the ledger or clear risk latches. Changed thresholds affect checks after the next manual start, so review inputs first. Threshold edit audit history is not implemented.

## 异常与限制 / Failures and limitations

字段、版本、数值范围和小数精度严格校验；拒绝实盘模式、额外字段、缺失字段、重复键、非有限数值及超过8KB的文件。读取失败时保留当前输入并显示提示，不自动启动、不重写坏文件。写入使用同目录临时文件、flush/fsync和原子替换；替换失败保留旧预设。多窗口各自加载一份，显式保存最后成功者生效；没有跨窗口预设合并或编辑锁。账户状态锁不因此改变。

Strict validation covers schema version, exact fields, numeric ranges and decimal precision. Live mode, extra/missing fields, duplicate keys, nonfinite numbers and files above 8KB are rejected. Read failures preserve current inputs and display a warning, without auto-starting or rewriting the bad file. Writes use a same-directory temporary file, flush/fsync and atomic replacement; failed replacement preserves previous settings. Multiple windows hold independent copies; the last successful explicit save wins, with no preference merge/edit lock. Session-state locking remains unchanged.

测试涵盖保存/读取、非法输入、损坏文件、替换失败、按钮锁定、重启不启动引擎以及账本保持原样。所有测试为本地模拟，不验证真实交易权限。

Tests cover round trips, invalid inputs, corrupt files, replacement failures, disabled controls, no engine startup on restore, and unchanged ledger contents. These are local simulated checks, not live-trading authorization tests.
