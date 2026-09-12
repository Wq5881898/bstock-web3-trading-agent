# 项目归并状态 / Project consolidation

## 唯一交付仓库 / Authoritative delivery repository

https://github.com/Wq5881898/bstock-web3-trading-agent

本地目录为bstock-web3-engine。相邻binance-agent-os-trading-agent是此前误分叉的开发工作目录，不作为第二个交付项目；保留其代码供后续审查迁移，不删除、不覆盖。已有README、MIGRATION、desktop及桌面测试的未提交修改原样保留。

The local bstock-web3-engine checkout is authoritative. The adjacent binance-agent-os-trading-agent folder is an unintended development fork, retained as migration evidence rather than a second deliverable. Existing uncommitted README, migration, desktop and desktop-test changes are preserved.

## 已适配 / Adapted

独立授权与发现基础模块oauth_flow、oauth_callback、mcp_discovery、mcp_http及四组测试已经适配为bstock_web3内部导入，无相邻项目运行时依赖。完整本地测试47项通过。

The oauth_flow, oauth_callback, mcp_discovery and mcp_http modules plus four test groups now use internal bstock_web3 imports, with no runtime dependency on the adjacent project. Full local suite: 47 passed.

授权基础现已提供PKCE/state、短期本机回调、仅内存Token交换、只读目录协议、固定端点HTTP/SSE传输、双层只读工具白名单和有界分页。独立客户端仍缺公网Client Metadata URL和桌面授权接线；Token不会持久化，重启必须重新登录。真实MCP只读账户验收已通过，但由当前Codex宿主完成，不等于独立桌面授权已经完成。

The authorization foundation now provides PKCE/state, loopback callbacks, session-only token exchange, discovery, pinned HTTP/SSE, defense-in-depth read allowlisting and bounded pagination. The standalone client still needs a public client-metadata URL and desktop consent wiring; tokens are not persisted and restart requires login. Real MCP account reads passed through the current Codex host, which does not establish standalone desktop authorization.

现有mcp_bridge仍是需宿主核验与逐笔确认的订单计划桥。不会把确认机制删除，也不会通过新传输执行tools/call。用户目标仍是MCP优先，API替代路线须重新商讨和明确允许。

The existing mcp_bridge remains a host-validated, per-order-confirmed plan bridge. Its controls are unchanged; the new transport cannot execute tools/call. MCP remains the user's preferred route; any API replacement requires renewed discussion and explicit permission.

## 剩余归并 / Remaining consolidation

1. 部署公网Client Metadata、接入授权UI，并以仅内存Token完成独立桌面只读连接验收。
2. 将多策略纸面账户、Median/Range/Slope等能力适配到现有数据模型和桌面，不能直接替换当前bStock分钟策略或引入第二套运行目录。
3. 统一累计亏损、买入暂停、订单核对和账户级互斥；不将纸面成交状态冒充真实订单状态。
4. 统一双语说明、长时测试、许可证与敏感信息审查，选择性提交后发布。

1. Deploy public client metadata, wire the consent UI and complete standalone desktop read-only acceptance with a session-only token.
2. Adapt multi-strategy paper accounts and Median/Range/Slope features to existing models/UI without replacing bStock minute-strategy semantics or introducing a second runtime tree.
3. Unify cumulative-loss controls, entry pause, order reconciliation and account-level ownership; paper fills are not exchange evidence.
4. Consolidate bilingual documentation, sustained testing, license/security review and selective commits before release.
