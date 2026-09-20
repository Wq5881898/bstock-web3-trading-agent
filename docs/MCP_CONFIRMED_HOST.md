# MCP确认宿主边界 / Confirmed MCP host boundary

## 已实现 / Implemented

`mcp_confirmed_host.py`是在已授权Codex MCP宿主内部可复用的无网络校验边界：

- 只允许7个Spot读取工具以及`spot.newOrder`、`spot.getOrder`；其他工具在调用前拒绝。
- `spot.newOrder`只接受本项目确定性ID、MARKET/FULL订单和与方向匹配的正Decimal字符串金额。
- `spot.getOrder`只允许按当前币对和本项目`origClientOrderId`查询；UNKNOWN只查单、不重发。
- 初始化时必须发现完整工具集合，且两个订单工具schema必须与本地严格契约兼容。
- 网络、OAuth、Token和实际工具调用归支持的Codex宿主；本模块不直接连接Binance。

`mcp_confirmed_host.py` is a network-free validation boundary reusable inside the authorized Codex MCP host. It allows seven Spot reads plus `spot.newOrder` and `spot.getOrder`, enforces deterministic project IDs and strict MARKET/FULL arguments, and requires compatible discovered schemas. Codex owns network, OAuth, tokens and actual tool calls. UNKNOWN outcomes remain lookup-only and are never resent.

## 没有实现 / Not implemented

本模块没有启动OAuth、保存Token、暴露真实桌面提交按钮或调用真实服务。完整流程仍需由现有Codex宿主完成：

1. 发现并验证schema；
2. 读取账户、完整订单/成交、规则和盘口；
3. 完成成交、权益和资金流对账；
4. 展示账户、方向、币对和精确金额，并由支持的宿主/Binance获得确认；
5. 重新读取并复核风险后只调用一次`spot.newOrder`；
6. 不确定结果只调用`spot.getOrder`。

This module starts no OAuth, retains no token, exposes no live desktop submit button and calls no live service. The existing Codex host must orchestrate schema discovery, same-session account reconciliation, fill/equity/cash-flow checks, supported-host confirmation, one submission and lookup-only recovery.

首次真实写工具验收只记录去敏后的工具名和schema兼容性，不记录Token、授权码、回调URL、账户UID或余额。运行时schema不兼容时必须更新测试和适配器，不能临时放宽验证。

First live write-tool acceptance may record only redacted tool names and schema compatibility—not tokens, authorization codes, callback URLs, UID or balances. An incompatible schema requires a reviewed adapter/test update, never an ad-hoc bypass.
