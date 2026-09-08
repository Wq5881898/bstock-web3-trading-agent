# V1 独立迁移说明

## 来源与边界

V1 从 `D:\projectQ\alpha2` 的 `codex/bstock-spot-adapter` 分支提取 bStock 专用能力，
重新组织为独立包 `bstock_web3`。本仓库没有 Git submodule、路径依赖或
`alpha2.*` import，也不连接 Alpha2 的数据库、运行目录和配置。

迁移的设计与能力：

- `alpha2.bstock.catalog`：bStock 目录和市场状态；
- `alpha2.data.providers.binance_spot`：公共 Spot K 线 REST 逻辑；
- `alpha2.bstock.market_data`：已闭合 1m/5m 多周期快照；
- `alpha2.bstock.strategy`：MTF EMA 信号；
- `alpha2.bstock.wallet`：`baw --json` 钱包适配；
- `alpha2.bstock.engine`：paper/quote/live-confirmed 状态机和安全闸门；
- `alpha2.bstock.history`：1s 下载、断点恢复和 1m/5m 聚合思想；
- `alpha2.bstock.desktop`：独立监控窗口的交互与安全语义。

## 有意未迁移

Alpha2 的全量策略目录、Range Bar/Feature Pipeline、账户数据库、旧交易界面和
Binance Alpha/普通币现货执行器没有进入 V1。这些模块耦合于 Alpha2 内部模型，
复制它们会破坏“独立项目”边界。V1 当前只保证 MTF EMA 策略可以独立采集、回测、
模拟、报价和受控实盘。

## 后续合并原则

如果未来需要把研究成果回灌 Alpha2，应通过明确的接口或独立发布包合并，不能把
本仓库运行目录直接复制回 Alpha2。合并前分别运行两个仓库的测试，并在独立分支做
cherry-pick 或适配提交。

## 安全说明

- 钱包连接由官方 `baw` 管理；本项目不读取或保存私钥。
- eligibility 文件必须由操作者从当前官方活动页独立核验。
- 实盘每笔都需要随机确认码，确认码只对生成它的短时 Quote 有效。
- 历史回测不构成收益保证，也不授权自动实盘。

## V1.0.1 验收修正

- 状态文件不存在时允许创建新模拟状态；状态文件存在但损坏、字段非法或持仓与
  入场价矛盾时，程序会明确报错并停止，不再静默重置为空仓。
- 引擎配置拒绝零金额、负金额和非法费用/Quote 时效参数。
- 新增 Quote 过期、错误确认码、状态损坏、参数边界和未闭合 K 线测试。

## V1.0.2 订单恢复加固

- 链上提交拿到 `orderId` 后立即原子写入状态文件，再进入结果轮询。
- 状态查询临时失败或超时时保留 `PENDING`，重启后只查询原订单，不重复下单。
- 存在未决订单时禁止提交第二笔交易；已经使用过的逐笔确认码不能重复使用。
- 成交记账与清除未决状态合并成一次原子保存，避免断电窗口导致重复记账。
- 公共 K 线接口增加有界指数退避重试。

