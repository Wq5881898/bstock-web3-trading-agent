# 项目归并状态 / Project consolidation

## 唯一交付仓库 / Authoritative repository

唯一交付仓库为 <https://github.com/Wq5881898/bstock-web3-trading-agent>，本地目录为`bstock-web3-engine`。相邻历史目录不是第二个交付项目，也不是运行时依赖。

The sole delivery repository is <https://github.com/Wq5881898/bstock-web3-trading-agent>; its local checkout is `bstock-web3-engine`. Adjacent historical folders are neither a second product nor runtime dependencies.

## MCP纠正 / MCP correction

已经验证可用的是Codex内现有`binance-agent-os`连接及其所选Agentic子账户。项目自己实现OAuth客户端的路线被Binance以“不支持当前Agent”拒绝，因此已从产品中撤下：

- 删除本机OAuth回调、Token交换、直接HTTP MCP传输和独立schema登录命令；
- 删除公网Client Metadata、GitHub Pages发布和桌面登录入口；
- 桌面和CLI只导出无凭据请求，交给现有Codex宿主执行；
- 保留工具参数/schema校验、账户结果对账、风控、账本和UNKNOWN只查单恢复。

The working path is the existing `binance-agent-os` connection in Codex and its selected Agentic sub-account. Binance rejected the repository's attempted standalone OAuth identity as an unsupported Agent, so that product path has been removed:

- loopback OAuth, token exchange, direct HTTP MCP transport and standalone schema-login commands are gone;
- public client metadata, Pages publishing and the desktop login entry are gone;
- desktop/CLI only export credential-free work items for the existing Codex host;
- schema/argument validation, reconciliation, risk, ledger and lookup-only UNKNOWN recovery remain.

完整边界见[MCP宿主桥接](MCP_HOST_BRIDGE.md)。API Key路线没有启用；任何替代接口必须重新讨论并明确批准。

See [MCP host bridge](MCP_HOST_BRIDGE.md). No API-key route is enabled; any alternative requires a separate decision and explicit approval.
