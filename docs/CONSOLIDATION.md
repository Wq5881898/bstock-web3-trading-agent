# 项目归并状态 / Project consolidation

## 唯一交付仓库 / Authoritative delivery repository

https://github.com/Wq5881898/bstock-web3-trading-agent

本地目录为bstock-web3-engine。相邻binance-agent-os-trading-agent是此前误分叉的开发工作目录，不作为第二个交付项目；保留其代码供后续审查迁移，不删除、不覆盖。已有README、MIGRATION、desktop及桌面测试的未提交修改原样保留。

The local bstock-web3-engine checkout is authoritative. The adjacent binance-agent-os-trading-agent folder is an unintended development fork, retained as migration evidence rather than a second deliverable. Existing uncommitted README, migration, desktop and desktop-test changes are preserved.

## 已适配 / Adapted

独立授权与发现基础模块oauth_flow、oauth_callback、mcp_discovery、mcp_http及四组测试已经适配为bstock_web3内部导入，无相邻项目运行时依赖。完整本地测试47项通过。

The oauth_flow, oauth_callback, mcp_discovery and mcp_http modules plus four test groups now use internal bstock_web3 imports, with no runtime dependency on the adjacent project. Full local suite: 47 passed.

这四个模块分别提供离线PKCE/state、短期本机回调、只读目录协议和固定端点HTTP/SSE传输。测试使用虚构Token、假HTTP传输和本机回调，未访问真实账户。它们尚未接入CLI或桌面授权流程，也没有Token交换和系统凭据存储，不等于已经完成独立授权。

These modules provide offline PKCE/state, loopback callbacks, discovery protocol and pinned HTTP/SSE transport. Tests use fictitious tokens, fake HTTP and local callbacks, not real accounts. CLI/UI integration, token exchange and OS credential storage are absent; independent authorization is not established.

现有mcp_bridge仍是需宿主核验与逐笔确认的订单计划桥。不会把确认机制删除，也不会通过新传输执行tools/call。用户目标仍是MCP优先，API替代路线须重新商讨和明确允许。

The existing mcp_bridge remains a host-validated, per-order-confirmed plan bridge. Its controls are unchanged; the new transport cannot execute tools/call. MCP remains the user's preferred route; any API replacement requires renewed discussion and explicit permission.

## 剩余归并 / Remaining consolidation

1. 凭据存储、Token交换、授权UI及真实只读连接验收。
2. 将多策略纸面账户、Median/Range/Slope等能力适配到现有数据模型和桌面，不能直接替换当前bStock分钟策略或引入第二套运行目录。
3. 统一累计亏损、买入暂停、订单核对和账户级互斥；不将纸面成交状态冒充真实订单状态。
4. 统一双语说明、长时测试、许可证与敏感信息审查，选择性提交后发布。

1. Token storage/exchange, consent UI and real read-only acceptance.
2. Adapt multi-strategy paper accounts and Median/Range/Slope features to existing models/UI without replacing bStock minute-strategy semantics or introducing a second runtime tree.
3. Unify cumulative-loss controls, entry pause, order reconciliation and account-level ownership; paper fills are not exchange evidence.
4. Consolidate bilingual documentation, sustained testing, license/security review and selective commits before release.
