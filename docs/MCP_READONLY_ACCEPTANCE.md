# Agent OS MCP只读验收 / Agent OS MCP read-only acceptance

## 2026-09-12验收结果 / Acceptance result

已通过当前Codex宿主连接的Binance Agent OS MCP，对OAuth选择的Agentic子账户完成一次`BTCUSDT`只读核对。为避免公开仓库泄露账户信息，本文不记录UID、精确余额、订单ID或成交ID。

One read-only `BTCUSDT` reconciliation was completed through the Binance Agent OS MCP connected to the current Codex host and its OAuth-selected Agentic sub-account. UID, exact balances, order IDs and trade IDs are intentionally excluded from this public repository.

验证结果：

- `spot.getAccount`：账户为Spot，`canTrade=true`，BTC和USDT余额可读；
- `spot.getOpenOrders`：目标标的没有未决订单；
- `spot.myTrades`与`spot.allOrders`：此前约10 USDT的BTC市价买入可核对，订单终态为`FILLED`；
- 实际BTC余额等于买入数量减去BTC手续费；
- `spot.accountCommission`：标准maker/taker费率和折扣状态可读；
- `spot.exchangeInfo`：`BTCUSDT`为`TRADING`，支持Spot、市价单和`quoteOrderQty`，最小名义价值为5 USDT；
- `spot.tickerBookTicker`：最优买卖价可读且盘口未交叉；
- 本次仅执行GET/USER_DATA读取，没有调用`spot.newOrder`或任何写工具。

Verified results:

- `spot.getAccount`: Spot account, `canTrade=true`, readable BTC and USDT balances;
- `spot.getOpenOrders`: no pending order for the target symbol;
- `spot.myTrades` plus `spot.allOrders`: the earlier roughly 10-USDT BTC market buy reconciles to a terminal `FILLED` order;
- actual BTC balance equals bought quantity less the BTC-denominated commission;
- `spot.accountCommission`: standard maker/taker rates and discount state are readable;
- `spot.exchangeInfo`: `BTCUSDT` is `TRADING`, supports Spot market `quoteOrderQty`, and has a 5-USDT minimum notional;
- `spot.tickerBookTicker`: best bid/ask are readable and not crossed;
- only GET/USER_DATA reads were performed; neither `spot.newOrder` nor any write tool was called.

## 代码落地 / Code delivery

`mcp_spot_snapshot.py`按照真实返回结构将宿主提供的JSON转换为`McpReconciliationEvidence`。它强制核对预期账户UID、Spot账户类型、交易权限、完整分页成交、订单与成交关系、手续费后的实际base余额、quote可用余额、未决订单和盘口。单标的原型若出现无法解释的base余额、第三资产手续费或其他非零资产，会失败关闭，等待后续账户级风险账本支持。

`mcp_spot_snapshot.py` converts host-supplied JSON shaped like the real responses into `McpReconciliationEvidence`. It verifies the expected account UID, Spot account type, trading permission, complete paginated fills, order/fill linkage, fee-adjusted base balance, available quote balance, pending orders and book. The single-symbol prototype fails closed on unexplained base inventory, third-asset fees or another nonzero asset until account-level risk accounting supports them.

该模块不包含MCP客户端或`tools/call`。当前Codex宿主能够访问真实MCP，但公开Python项目仍需实现独立OAuth会话、工具发现/调用宿主以及分页器，才能从桌面程序自主取得这些JSON。API Key替代路线没有启用。

The module contains no MCP client or `tools/call`. The current Codex host can access the real MCP, but the public Python application still needs its own OAuth session, discovery/call host and paginator before its desktop process can obtain these JSON payloads. No API-key fallback is enabled.
