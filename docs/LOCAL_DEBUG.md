# 本地调试 / Local debugging

## K线页 / Candle tab

新增1m/5m K线页，使用EngineEvent携带的同一策略行情快照，仅显示已收盘K线，最多240根，标注UTC采集时间。刷新失败或本轮无快照时保留旧图并标记historical；切换周期不会消除该标记。未添加额外行情请求或交易入口。合成行情窗口截图已检查，完整测试60项通过；真实持续刷新验收仍待完成。

The new 1m/5m candle tab renders the strategy snapshot carried by EngineEvent, with at most 240 closed bars and a UTC observation timestamp. Failed/missing updates retain a historical marker across interval changes. No extra requests or trading actions were added. Synthetic visual inspection and 60 tests passed; sustained real-market refresh remains unverified.

## 桌面交互补验 / Desktop interaction follow-up

新增可注入假引擎的窗口工厂和Qt交互测试：阻塞后台任务时界面仍响应、停止等待完成、异常显示、关闭收尾及锁释放。桌面现在用QLockFile保护同一状态路径，避免两个桌面窗口同时写入；CLI尚未使用该锁，这不构成全执行器或实盘账户级互斥。运行目录创建失败会在状态栏报告。

A window factory allows fake-engine Qt tests for responsiveness during a blocked task, stop/wait, exception display, close cleanup and lock release. QLockFile now protects each desktop state path against concurrent desktop writers. CLI does not use this lock; it is not universal executor or live-account ownership. Directory creation failures are shown in the status bar.

本轮完整测试59项通过；全部使用本地假行情，无授权或真实订单。 / Full suite: 59 passed, using local fixtures without authorization or live orders.

桌面行情评估已移到单工作线程，引擎在该线程构建并使用；UI线程只收取结果和刷新控件。同一时刻最多一轮，启动期间锁定标的、模式、金额。停止或关闭不再安排新轮次，但等待当前轮次结束；当前轮次可能仍产生模拟成交或报价，这不是即时取消，也不清仓。未添加真实交易按钮。

Desktop evaluation now uses a single background worker, which constructs and owns the engine. The UI collects results and renders widgets. Only one evaluation can be outstanding; symbol/mode/amount are locked while running. Stop/close waits for the current evaluation, which may still produce a paper fill or quote; it is not immediate cancellation or liquidation. No live-submit button was added.

日志显示最多1000块，事件表最多500行（仅显示限制，不是审计持久化）。标的路径仅接受1至32个ASCII字母或数字，模式仅paper/quote，拒绝路径穿越。错误配置在界面显示而不是启动线程。

The visible log is capped at 1,000 blocks and table at 500 rows; these are display bounds, not durable auditing. State names accept only 1–32 ASCII alphanumeric characters and paper/quote modes, rejecting traversal. Invalid configuration is shown before a worker starts.

已覆盖后台线程所有权、单飞、停止、异常后的再次评估与非法路径回归。完整长时行情压测、后台请求取消、进程级会话互斥及完整多策略归并仍待完成。未执行真实授权或交易。

Regression coverage includes thread ownership, single flight, stop, retry after evaluation failure and invalid paths. Sustained live-data testing, cancellation of in-flight requests, process-level ownership and full multi-strategy consolidation remain pending. No real authorization or trading was performed.
