# MCP确认写宿主边界 / Confirmed MCP host boundary

## 已实现 / Implemented

`mcp_confirmed_host.py`在原有只读传输之外新增一条独立、默认不使用的确认会话边界：

- 固定使用现有官方Agentic MCP资源地址、Bearer Token安全规则、无重定向/无自动重试、有界响应及会话ID校验。
- 会话仅允许原有7个Spot读取工具，加上`spot.newOrder`和`spot.getOrder`；提现、转账、撤单、合约、Margin及其他工具全部在网络请求前拒绝。
- `spot.newOrder`只允许由本项目确定性ID生成的MARKET/FULL订单。BUY必须且只能使用正Decimal字符串`quoteOrderQty`；SELL必须且只能使用`quantity`。
- `spot.getOrder`只能通过当前币对和本项目生成的`origClientOrderId`查询。UNKNOWN恢复仍然只查单，不重发。
- 初始化时必须从`tools/list`发现完整会话工具；两个订单工具的schema必须声明对象、所需属性、必填字段及字符串参数类型。缺失或不兼容会在执行器建立前失败关闭。
- 客户端层和HTTP层重复校验白名单与参数，避免绕过上层客户端直接调用传输。

The separate confirmed-session boundary inherits the pinned HTTP protections and permits only seven existing Spot reads plus `spot.newOrder` and `spot.getOrder`. It accepts only deterministic project client IDs, MARKET/FULL orders and one side-appropriate positive Decimal-string amount. Discovery must expose compatible object schemas before the client becomes ready. Both client and transport enforce the contract. Unknown submission outcomes remain lookup-only and are never resent.

## 没有实现 / Not implemented

本模块没有启动OAuth、没有保存Token、没有桌面按钮，也没有真实调用。它只是`ConfirmedSpotExecutor`所需`caller(name, arguments)`的安全实现。完整宿主仍需在同一短期OAuth会话中依次完成：

1. 发现并验证schema；
2. 读取账户、完整订单/成交、规则和盘口；
3. 完成成交/权益/资金流对账；
4. 桌面展示账户、方向、币对和精确金额，并获得本笔订单的一次性确认；
5. 重新读取并复核风险后调用一次`spot.newOrder`；
6. 不确定结果只调用`spot.getOrder`。

This module does not start OAuth, retain a token, expose a desktop button or call a live service. It only supplies the narrow callable required by `ConfirmedSpotExecutor`. A production host must orchestrate discovery, same-session account reconciliation, complete fill/equity/cash-flow checks, an exact per-order desktop confirmation, one submission and lookup-only recovery.

官方文档的自动读取在本轮返回空`202`，因此没有用抓取结果猜测schema。首次真实连接必须记录去敏后的工具名和schema兼容性结果；不记录Token、授权码、回调URL或账户余额。若运行时schema不兼容，应更新测试和适配器后重新发布，不能临时放宽验证。

The official documentation endpoint returned an empty HTTP 202 to the automated reader in this development round, so no schema was guessed from scraped content. First live discovery must record only redacted tool/schema compatibility—not tokens, authorization codes, callback URLs or balances. An incompatible runtime schema requires a reviewed adapter/test update, never an ad-hoc validation bypass.
