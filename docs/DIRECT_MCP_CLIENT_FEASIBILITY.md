# 自建 MCP 客户端可行性核查 / Direct MCP Client Feasibility

状态：**只读调查；尚未批准或启用架构变更**。日期：2026-09-23。

Status: **Read-only investigation; no architecture change authorized or enabled**. Date: 2026-09-23.

## 结论 / Finding

MCP 协议并不要求通过 Codex 对话窗口。bStock 桌面程序原则上可以实现 Streamable HTTP MCP 客户端，自己连接币安 MCP。现有“程序生成无凭据请求 → Codex 宿主调用 MCP”的模式，是此前独立 OAuth 客户端尝试未获币安接纳后采用的已验证退路，不是 MCP 的技术必然要求。当前产品代码没有独立网络/OAuth 传输；不能把已有 Codex OAuth 授权复制给 bStock。

The MCP protocol does not require a Codex chat window. In principle, bStock can implement a Streamable HTTP MCP client and connect to Binance itself. The current credential-free handoff to Codex is a working fallback after the earlier standalone OAuth attempt was not admitted by Binance, not a protocol requirement. The product currently has no independent network/OAuth transport; it must not copy Codex's OAuth credentials.

## 已验证事实 / Verified evidence

1. 2026-09-23 对 `https://agent.binance.com/mcp/agentic` 发起**无凭据、只含 `initialize`** 的 POST，返回 `401 Unauthorized`，并给出 `WWW-Authenticate: Bearer resource_metadata="https://agent.binance.com/.well-known/oauth-protected-resource/gateway-mcp"`。没有发起账户读取或写操作。这说明该端点的 MCP 握手也需要授权；“公开行情数据”不等于此端点的协议握手免授权。
2. 上述公开资源元数据返回 `resource=https://agent.binance.com/mcp/agentic`，授权服务器为 `https://agent.binance.com`。公开授权服务器元数据声明授权码 + PKCE S256、`client_id_metadata_document_supported=true`；未发起 OAuth 授权请求。
3. 历史实现使用公网 client-metadata URL、浏览器 OAuth 回调和独立 HTTP MCP 传输；仓库的 [归并记录](CONSOLIDATION.md)记载它遭遇“当前 Agent 暂时不支持”，随后撤回。**无法仅凭该错误判定所有自建客户端都不被支持。**
4. 历史默认 client-metadata URL 指向 `@oauth-client-v1` 标签；当前公开 URL 返回 404，且本地没有该标签。这是**当前**可复现的配置缺陷；没有证据证明它就是当时授权被拒的唯一原因。不能重用这一失效身份尝试登录。
5. 币安[官方 MCP 文档](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic)列出支持的客户端及 `Other` 入口，并要求每笔交易、撤单和划转先由用户确认。币安[官方博客](https://www.binance.com/en/square/post/360313703798060)提及 user-developed agents。两处信息支持继续核查，但不构成 bStock 自建身份已经获准或零确认交易获准的证明。

1. An unauthenticated `initialize` POST to the Binance MCP endpoint returned `401 Unauthorized` and a protected-resource metadata URL. No account or write tool was called. Transport-level authorization is required even though some underlying market data is public.
2. Public resource metadata points to the same MCP endpoint and `https://agent.binance.com` as authorization server. Public server metadata advertises authorization-code + PKCE S256 and client-ID metadata documents. No OAuth authorization was started.
3. The former standalone transport used a public client-metadata URL and loopback OAuth callback. [Consolidation notes](CONSOLIDATION.md) record Binance's “current Agent unsupported” response. That single failure does **not** prove all custom clients are disallowed.
4. The former default metadata URL under `@oauth-client-v1` currently returns 404, and that tag is absent locally. This is a reproducible **current** configuration defect, not proven to be the sole cause of the earlier rejection. Do not retry login with that broken identity.
5. Binance's [MCP developer guide](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic) lists supported clients and an `Other` entry, and requires user confirmation before trades, cancels, and transfers. Its [official blog](https://www.binance.com/en/square/post/360313703798060) mentions user-developed agents. Neither source proves admission of this bStock identity or permits zero-confirmation trading.

## 最小验证门槛 / Minimal validation gates

以下是**候选方案，不是已获批准的实施计划**。若用户明确批准自建 MCP/OAuth 身份及一次账户只读授权，再逐关进行：

1. 准备由项目控制、公开可读取且内容一致的 HTTPS client-metadata 文档；先从外部核对 `200`、JSON、client ID、redirect URI。不能借用 Codex client ID 或 Token。
2. 仅申请完成只读试验所需的权限；授权页必须选择**已有** Agentic 子账户。若界面要求创建新账户或扩大权限，立即停止并请用户决策。
3. 首次授权后只运行 `initialize`、`tools/list` 和有限账户只读调用；验证原账户指纹、凭据保存/刷新策略、会话恢复和撤销。不得调用下单、撤单或转账工具。
4. 只有通过独立安全评审及用户另行批准后，才考虑真实写入。官方逐笔确认要求依然适用；自建客户端不自动获得无人确认交易能力。

The following are **proposed gates, not approved implementation**. Only after explicit permission for a project-owned MCP/OAuth identity and a one-time read-only account authorization: verify public HTTPS client metadata; select the **existing** Agentic sub-account with minimal scopes; run only initialize, tools/list, and bounded account reads; verify account fingerprint, token lifecycle, recovery, and revocation. Stop if Binance requests a new account or broader permission. No order/cancel/transfer call until a separate decision and security review. A direct client does not bypass Binance's per-action confirmation requirement.

## 当前决定 / Current decision

保留现有 Codex MCP 连接与本地桥接。未创建 API Key、Agentic 账户或 OAuth 授权；未读取私人账户、下单或更改运行器。依据[产品基准](AUTONOMOUS_TRADING_PRODUCT_BASELINE.md)和[收尾计划](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md)，更换客户端身份/认证路线前需用户明确批准。本核查只澄清可行性，不能视作批准。

Keep the existing Codex MCP connection and local bridge. No API key, Agentic account, OAuth grant, private account read, order, or runner change occurred. The [product baseline](AUTONOMOUS_TRADING_PRODUCT_BASELINE.md) and [closeout plan](MCP_AGENTIC_CLOSEOUT_MASTER_PLAN.md) require explicit operator approval before changing client identity or authentication. This investigation is not that approval.
