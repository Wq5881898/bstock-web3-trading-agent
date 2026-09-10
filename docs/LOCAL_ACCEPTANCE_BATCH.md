# 本地验收批次 / Local acceptance batch

## 范围与结论 / Scope and result

唯一交付目录仍为bstock-web3-engine。此次优先处理归并后的数值、账务、恢复和桌面稳定性，不追加第二套策略UI，也不启用真实订单。没有修改已有运行账户文件，没有推送GitHub。

The authoritative checkout remains bstock-web3-engine. This batch prioritizes numeric, accounting, recovery and desktop integrity rather than another strategy UI or live execution. Existing runtime account files were not modified and GitHub was not pushed.

## 修复 / Fixes

- 引擎金额、费用、Quote时效和策略周期/比例拒绝非法或非有限值。
  Engine amounts, fees, quote ages and strategy periods/fractions reject invalid/non-finite inputs.
- 状态文件验证非有限金额、孤立未决字段、时区、仓位与成本一致性；损坏文件不自动重置。
  State validation checks finite amounts, orphan pending fields, timezone and position/cost consistency without resetting corrupt files.
- 新保存状态绑定标的和模式，拒绝跨标的/模式复用。旧文件缺少绑定信息时暂兼容，首次保存补写；无法据此证明旧文件历史归属。
  Newly saved states bind symbol/mode. Legacy unbound files remain readable and bind on save; this cannot establish their historical ownership.
- 模拟买入保存含买入手续费的实际支出成本，卖出已实现盈亏与现金变化一致。拒绝重复买入覆盖仓位、空仓卖出、零资金买入；保存失败回滚模拟成交内存状态。
  Paper buys retain fee-inclusive spend as cost. Realized PnL matches cash changes after sells. Position-overwriting BUYs, flat SELLs and zero-cash entries are rejected; failed saves roll back in-memory paper fills.
- 重复及更早信号时间不重放；过旧1m行情不进入引擎策略执行，MTF还检查1m/5m周期时效。OHLCV拒绝非有限、错序、重复、价格矛盾及时间未对齐数据。不填补缺失时段。
  Duplicate/older bars are not replayed. Stale 1m data is blocked before engine strategy execution; MTF checks both timeframe ages. OHLCV validation rejects invalid, unordered, duplicate, inconsistent or misaligned bars; gaps are not synthesized.
- 界面恢复成功后清除旧错误状态，过期行情图表标记为历史快照。
  Successful evaluation updates previous error status; stale charts remain visibly historical.

## 兼容性注意 / Compatibility warning

旧模拟持仓若没有paper_entry_cost，不能可靠恢复含费成本。本轮选择拒绝自动模拟卖出记账并保留原状态，要求操作者核对，而不是推算并冒充准确成本。未建立迁移向导；不能直接宣称所有旧模拟会话可无缝恢复。此限制只涉及本地paper记账，不改变钱包执行规则。旧历史已实现盈亏也未回算。

Legacy paper positions without paper_entry_cost have unverifiable fee-inclusive cost. Automatic paper SELL bookkeeping fails closed and preserves the position pending review; no migration wizard or seamless legacy compatibility is claimed. This affects local paper accounting only, not wallet execution. Historical realized PnL has not been recalculated.

## 验证证据 / Verification

- 完整测试90项通过。 / Full suite: 90 passed.
- 2,000轮加速模拟成交评估，逐轮重复信号检查，每137轮恢复引擎，最后核对现金、已实现损益和双边手续费一致。
  2,000 accelerated paper evaluations with duplicate-bar checks, restarts every 137 iterations and final cash/PnL/two-sided-fee reconciliation.
- 原生Windows桌面650轮加速刷新，38次故障注入，正常停止解锁，表格500行和日志上限验证，截图已检查。约12.56秒，不是650分钟真实行情。
  Native Windows desktop: 650 accelerated refresh attempts, 38 injected failures, orderly stop/unlock, bounded table/log checks and inspected screenshots. About 12.56 seconds, not 650 minutes of real market data.
- pip check通过、源文件编译通过。 / Dependency and source compilation checks passed.
- 隔离构建wheel成功，并以隔离Python路径直接从wheel导入引擎、MCP传输和图表模块。最初禁用隔离构建因本地缺wheel失败，未改运行依赖，使用pyproject声明的隔离构建后通过。不是完全无依赖的新电脑安装验收。
  Isolated wheel build succeeded, followed by direct engine/transport/chart imports from the wheel under isolated Python paths. The initial non-isolated build lacked wheel; declared isolated build dependencies resolved it without changing runtime dependencies. This is not a clean-machine dependency installation test.

复验 / Reproduce:

```powershell
& .\.venv\Scripts\python.exe -m pytest
& .\.venv\Scripts\python.exe scripts/local_desktop_acceptance.py
& .\.venv\Scripts\python.exe -m pip check
```

桌面脚本只注入假引擎，不调用网络、钱包或账户。输出在gitignore忽略的runtime/desktop-acceptance目录。

The desktop script injects a fake engine and makes no network, wallet or account calls. Reports live under ignored runtime/desktop-acceptance.

## 剩余 / Remaining

本次未完成多策略/参数编辑归并、累计亏损停买与手动恢复在本仓库的完整接线、旧持仓成本迁移向导、独立MCP Token交换与授权UI、真实账户核对、实盘支持方式验证。长时间真实公开行情测试和全部执行器的跨进程锁也仍待做。不得把本次本地验收称作整体产品完成或实盘可用。

Multi-strategy/editor consolidation, full cumulative-loss/manual-resume wiring in this repository, legacy-cost migration, independent MCP token exchange/consent UI, account reconciliation and supported live automation remain outstanding. Sustained real public-market testing and cross-process locking across all executors also remain. This batch is not full product or live-readiness acceptance.
