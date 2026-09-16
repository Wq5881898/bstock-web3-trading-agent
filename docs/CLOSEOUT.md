# 原型收尾与实盘验收 / Prototype closeout and live acceptance

## 已交付 / Delivered

- 单一策略注册表、便携运行时、产品兼容标签，包含MTF、Median和Range家族；不包含Slope。
- 桌面模拟监控、策略参数编辑/保存、真实公共K线显示及模拟账户/成交展示。
- 累计亏损停买、信号卖出继续、手动恢复及非阻塞提示。
- MCP只读白名单、分页、账户对账模块、一次性OAuth CLI和桌面读取入口。
- 离线执行风控、执行锁、确定性订单ID与状态日志；这些不构成真实下单适配器。
- 写盘失败回滚内存状态、拒绝日志时间倒退、读取失败不显示旧账户余额。

Delivered: a unified tagged strategy library, editable desktop paper trading, public candles, BUY-only loss latches and manual resume, allowlisted MCP reads, reconciliation, memory-only OAuth CLI/desktop wiring, offline execution safety, persistence rollback and stale-account-view prevention.

## 两条验证路径不要混淆 / Keep the two verification paths separate

已通过的真实账户读取与早期小额BTC购买由外部已登录MCP宿主完成。它们不证明本项目的独立桌面OAuth和下单执行器已验收。

Historical account reads and the earlier small BTC purchase used an externally authenticated MCP host. They do not validate this project's standalone desktop OAuth or order executor.

GitHub推送是代码发布。公网Client Metadata是独立OAuth客户端身份的发布；两者互不等同。只做模拟盘或使用外部MCP宿主时，不需要为代码发布开启GitHub Pages。

A GitHub push publishes code. Public Client Metadata publishes the standalone OAuth client identity; these are separate operations. Paper mode and an external MCP host do not require Pages merely to publish the code.

## 实盘前必须完成 / Required before live use

1. 项目自己的HTTPS Client Metadata可访问，内容与本机回调匹配。可使用现有Pages部署；需要仓库管理员在Settings → Pages选择GitHub Actions。不得借用其他客户端身份。
2. 用户在浏览器完成独立项目OAuth，只读取账户并确认Agentic UID、余额、权限、历史订单及成交；确认没有重复创建/选错账户。
3. 开发人工确认MCP写适配器，将策略意图、账户级风险、精度/最小金额规则、逐笔确认、执行日志、跨进程锁和查单恢复贯通。当前只读Token在读取后关闭，不能直接拿只读按钮作交易连接。
4. 离线故障注入覆盖确认过期、拒绝、部分成交、超时、崩溃及重启。未知提交结果只查单，不自动重发。
5. 用户另外批准最小金额真实订单后，核验买卖终态、手续费和资金账本；随后观察持续真实行情与恢复行为。

Before live use: publish the project's client identity, complete user-driven standalone read-only OAuth acceptance, implement a per-order-confirmed write adapter, test its failure/recovery paths offline, and obtain separate authorization for minimal live-order acceptance.

不能将当前版本称为完全无人值守实盘。MCP写操作仍按官方逐笔确认要求执行；API Key替代路线未启用，需另行讨论和批准。当前轮次未授权账户或发送真实订单。

This revision is not unattended live trading. MCP writes remain subject to the official per-action confirmation policy. An API-key alternative is disabled and requires separate discussion and approval. No account authorization or live order was performed in this closeout.

## 本轮证据 / Evidence

本地Python 3.11完整回归342项通过；源码编译与依赖检查通过。新增测试验证日志写盘故障后的内存/磁盘一致性、时间倒退拒绝与MCP重试失败后旧余额清除。真实OAuth、真实订单与持续实盘不在离线回归的证明范围内。

342 local Python 3.11 tests passed, with source compilation and dependency checks. New tests cover journal persistence failures, clock rewind and removal of stale account balances after a failed retry. Offline regression does not establish live OAuth, order or sustained-market acceptance.
