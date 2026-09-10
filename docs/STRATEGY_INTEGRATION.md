# 策略编辑与迁移边界 / Strategy editing and migration boundaries

最新状态 / Latest: Median与固定Range EMA/Median桌面模拟已启用，见[Median公共行情](MEDIAN_DESKTOP.md)及[固定Range策略](RANGE_DESKTOP.md)。Slope与Auto本轮不加入；下方保留迁移过程中的阶段记录。 / Median and fixed Range EMA/Median desktop paper modes are enabled; see [Median public feed](MEDIAN_DESKTOP.md) and [fixed Range strategies](RANGE_DESKTOP.md). Slope and Auto are intentionally deferred; milestone history follows.

MTF编辑阶段验证 / MTF editor verification: 138 tests passed (27.29s); native synthetic desktop acceptance passed 650 attempts / 38 injected failures (18.77s). Strategy-page screenshot inspected. Local evidence: `runtime/desktop-acceptance/1788990536967810400/`. These are accelerated offline checks, not real-market or live-order acceptance.

## 当前可运行 / Available now

主仓库桌面新增“策略”标签页，可选现有MTF EMA默认配置或自定义配置。算法不变：5m趋势EMA与ATR过滤、1m EMA交叉入场、趋势反转/交叉/固定止损退出。提供8个参数编辑，运行及等待停止期间锁定。周期范围1–200（ATR至少2、快线必须小于慢线），不超过现有240根行情窗口；比例输入六位小数，0.004表示0.4%，不是0.004%。自定义参数仅允许paper，quote/live-confirmed沿用默认配置，不扩展真实执行能力。

The authoritative repository now has a Strategies tab with default/custom MTF EMA settings. The existing algorithm is unchanged: 5m EMA trend/ATR filters, 1m EMA crossover entries, and trend/crossover/fixed-stop exits. Eight editable inputs are locked while running or stopping. Periods are limited to 1–200 (ATR at least 2; fast below slow), within the existing 240-candle feed window. Fraction inputs have six decimal places: 0.004 means 0.4%. Custom settings are paper-only; quote/live-confirmed retain the default configuration and existing execution restrictions.

“保存参数”包含策略参数。预设格式升级到v2；完整v1文件在内存中补入历史默认MTF EMA，不自动写回文件，显式保存才升级。未知或不完整格式拒绝读取。加载不启动、不恢复买入、不改写账本。

Save settings includes strategy parameters. Preferences are now v2. An exact v1 schema is migrated in memory using historical MTF EMA defaults; disk content changes only after explicit save. Unknown/incomplete schemas are rejected. Loading never starts the engine, resumes entries or rewrites the ledger.

## 持仓参数 / Open-position parameters

模拟状态保存实际MTF EMA参数。已有持仓时，重启参数必须匹配，否则在访问行情/钱包之前拒绝初始化并提示恢复原参数。平仓后可以改参，使用同一账本，保留累计损益、风控暂停、开仓次数和最后已处理K线，不靠新建策略文件绕过风控。旧状态缺少策略信息时只允许历史默认参数接管已有持仓；此规则基于本主仓库此前GUI仅运行默认MTF EMA，不声称能还原外部自定义策略。如果旧状态来自自定义脚本，应先核对，不能据此认定其参数。

Paper state stores the actual MTF EMA configuration. Restarting an open position with different parameters fails before market/wallet access and asks for the original settings. After closing, parameters may change on the same ledger while retaining PnL, risk latches, entry counters and the last processed candle. Legacy held states without strategy metadata only permit historical defaults, based on this repository's previous default-only GUI; this does not reconstruct externally customized strategies. Review any legacy state created by a custom script before use.

此保护针对内置MTF EMA；程序化注入的其他策略尚不提供通用参数身份保护。当前不是多策略并发，也没有参数历史版本管理器。

This guard covers built-in MTF EMA, not arbitrary programmatically injected strategies. Concurrent multi-strategy sessions and a parameter version-history manager are not implemented.

## 历史阶段：Median为何当时未启用 / Historical phase: why Median was initially disabled

已核对相邻开发目录的`strategy/runtime.py`、`app/paper_session.py`以及`docs/desktop-paper-m1.md`：原固定Median以逐笔成交价计算滚动中位数，低于中位数×(1−偏离率)买入，高于中位数×(1+偏离率)卖出。`tp`是中位数偏离门槛，不是持仓收益止盈率。原实现维护逐笔成交ID连续性、预热和断线恢复；当前主仓库以1m收盘K线时间去重，两者不能直接等同。界面将Median、Range/Slope/Auto标记为不可选的待迁移项，没有伪装为已经可交易。

Inspection of the adjacent development tree's `strategy/runtime.py`, `app/paper_session.py` and `docs/desktop-paper-m1.md` confirms that fixed Median uses rolling trade prices: BUY below median × (1 − deviation), SELL above median × (1 + deviation). Its `tp` is a median-deviation threshold, not a position-profit target. The source maintains trade-ID continuity, warmup and reconnect handling; the current repository deduplicates by closed 1m candle time. These are not interchangeable. Median and Range/Slope/Auto are shown as disabled pending entries, not executable strategies.

下一迁移顺序：逐笔行情读取与连续ID检查 → 因果预热和持久检查点 → 原固定Median运行时与当前风控衔接 → 合成信号/断线/重启/卖出回归 → 启用选择项。Range和Auto分别需要价格区间状态与后台选参状态；不改用分钟K线冒充原语义。未迁移目录保持原样，交付仍以本主仓库为准。

Next migration sequence: trade feed with ID continuity → causal warmup and durable checkpoints → original fixed Median runtime connected to current risk controls → synthetic signal/reconnect/restart/exit tests → enable the selector. Range and Auto additionally require price-range and background-selection state. Minute candles must not silently replace the original inputs. The adjacent tree remains untouched; this repository remains authoritative.

## Median离线前置模块 / Offline Median preparation

后续更新 / Follow-up: 已完成独立的事务模拟账本与买卖/恢复回归，见[Median事务模拟账本](MEDIAN_PAPER.md)。下方保留前置模块阶段记录；桌面Median仍未启用。 / A separate transactional paper ledger and fill/recovery tests are now implemented; see [Median paper ledger](MEDIAN_PAPER.md). The preparation-stage record below is historical; desktop Median remains disabled.

本轮完整回归 / Full regression after this addition: **183 passed in 24.74s**; source compilation passed. No real orders, account authorization or GitHub push. 无真实订单、账户授权或GitHub推送。

已新增`median_ticks.py`，消费聚合成交响应格式（a/T/p/q），无HTTP、OAuth或下单能力。保持当前逐笔价格参与中位数计算、严格低于/高于偏离门槛才发出信号的原语义。默认窗口20、双边偏离0.002，支持1–100逐笔窗口，保留最近200笔价格。该配置尚未接入桌面保存。

`median_ticks.py` consumes aggregate-trade shaped rows (a/T/p/q), with no HTTP, OAuth or order capability. It preserves current-tick-inclusive Median and strict below/above deviation comparisons. Defaults: 20 trades and symmetric 0.002 deviation; windows 1–100, retaining the latest 200 ticks. These settings are not yet part of desktop preferences.

首个非空批次只预热；后续超过5秒或未来时间戳的数据只更新指标，不发买卖信号。成交ID必须连续、时间不倒退，同毫秒不同ID分别处理；历史重复ID不重放信号，缓存范围内重复内容冲突拒绝。整页先验证后接收，坏尾部不会吃掉好前缀。缓存之前的旧ID不重放，但无法核对其历史内容是否改变。

The first nonempty page is warmup-only. Later ticks older than five seconds or future-dated update features without trade signals. IDs must be contiguous and timestamps nondecreasing; distinct IDs in the same millisecond are preserved. Replayed IDs emit no signals, and conflicting cached duplicates fail. Page acceptance is atomic, so a bad tail cannot consume its valid prefix. IDs older than retained history are ignored without verifying their original contents.

数据校验失败设置恢复标记，后续有效数据不自动解除买入暂停，卖出信号仍可产生。该阶段故意没有恢复按钮/API；未来接到账户风控后才提供受控手动恢复。错误后应保存检查点并停止/处理错误，不能当作成功跳过缺失数据。

Validation failures latch recovery-required state. Later valid data cannot auto-resume BUYs, while SELL signals remain possible. This stage deliberately exposes no recovery button/API; controlled manual recovery follows account-risk integration. On error, the future caller must save the checkpoint and handle/stop for the error, not silently skip missing trades.

检查点绑定标的与完整Median配置，验证格式、ID连续性与数值，以同目录临时文件原子替换；恢复不会重放已消费信号。它仅是指标检查点，不是成交账本。`accept_page`与`save`为分步调用：保存失败时旧文件不变，但内存已接收的数据不会自动回滚，调用方必须停下处理。正式接入时必须将逐笔游标、指标、风险及成交作为同一事务保存，不能据此声称具备下单恰好一次语义或完整故障恢复。

Checkpoints bind symbol and full Median settings, validate schema/ID continuity/numbers, and use same-directory atomic replacement. Restore does not replay consumed signals. This is a feature checkpoint, not a fill ledger. `accept_page` and `save` are separate: failed persistence preserves the old file but does not roll back accepted in-memory data; the caller must stop and handle failure. Production integration must commit cursor, features, risk and fills together. This module does not establish exactly-once orders or complete execution recovery.

离线覆盖：原始门槛语义、冷启动/陈旧/未来数据、重复与缺口、损坏检查点、保存失败、2000笔因果信号与多次恢复对照。仍未进行真实逐笔行情请求、账户接入或Median模拟买卖闭环；界面选择项仍禁用。

Offline coverage includes threshold semantics, cold/stale/future data, replay/gaps, corrupt checkpoints, persistence failures, and 2,000 causal ticks compared across repeated restores. Actual trade-feed requests, account integration and a Median paper-fill round trip remain pending; its desktop entry stays disabled.
