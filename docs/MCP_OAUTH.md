# 独立MCP OAuth / Standalone MCP OAuth

## 当前实现 / Current implementation

项目已经包含PKCE/state、本机随机端口回调、固定Binance元数据校验、授权码Token交换和仅内存`AccessGrant`。Token请求固定发送到`https://accounts.binance.com/oauth-agentic/token`，禁止重定向、代理/netrc继承、超大响应和错误内容回显。Token不写入仓库、`.env`或运行目录；关闭程序或重启后必须重新登录。

The project now includes PKCE/state, a random-port loopback callback, pinned Binance metadata validation, authorization-code exchange and a session-only `AccessGrant`. Token requests are pinned to `https://accounts.binance.com/oauth-agentic/token`, with redirects, inherited proxy/netrc credentials, oversized responses and server-error echoing disabled. Tokens are never written to the repository, `.env` or runtime directory; restarting requires authentication again.

## 仍需提供的Client Metadata URL / Required client metadata URL

Binance声明`client_id_metadata_document_supported=true`，因此`client_id`不是任意名称，而是Binance服务器可以读取的公网HTTPS JSON地址。仓库已提供GitHub Pages部署，目标地址为`https://wq5881898.github.io/bstock-web3-trading-agent/oauth/bstock-web3-agent.json`；JSON中的`client_id`等于该文件自身URL。首次部署完成并验证200/JSON前不得启动项目授权。不要使用Codex或其他客户端拥有的metadata URL。[通用模板](oauth-client-metadata.example.json)仅供更换域名时参考。

Binance advertises `client_id_metadata_document_supported=true`, so `client_id` is a public HTTPS JSON URL retrievable by Binance, not an arbitrary name. The repository now contains a GitHub Pages deployment targeting `https://wq5881898.github.io/bstock-web3-trading-agent/oauth/bstock-web3-agent.json`, whose `client_id` is its own URL. Project authorization must not begin until the first deployment returns HTTP 200 JSON. Do not reuse metadata owned by Codex or another client. The [generic template](oauth-client-metadata.example.json) is only for a future domain change.

本机回调metadata登记不带端口的`http://127.0.0.1/callback/bstock-web3-trading-agent`；实际运行时使用相同host/path和随机端口。这与已成功的Codex native-client格式一致，但仍需在首次项目登录时由Binance实际验收。

The native metadata registers the portless loopback path; runtime uses the same host/path with a random port. This matches the shape of the successfully used Codex native client, but Binance must still validate the project's own document during its first login.

## 产品边界 / Product boundary

Binance官方MCP说明明确要求每次订单、撤单和内部转账在执行前由用户确认。因此MCP路线的最终形态是自动行情、自动策略、自动风控和自动生成订单，桌面弹窗由用户确认后才提交；不能宣称为完全无人值守实盘。完全无人值守若仍是硬需求，只能在后续单独讨论并明确批准其他官方接口，当前没有启用API Key路线。

The official Binance MCP guide requires user confirmation before every order, cancellation and internal transfer. The MCP product can automate market data, strategy, risk and order preparation, but submission remains user-confirmed in the desktop UI; it cannot be presented as fully unattended live trading. If unattended execution remains mandatory, another official interface requires a separate discussion and explicit approval. No API-key route is enabled.

## 一次性只读验证 / One-shot read-only verification

安装项目后可运行`bstock-mcp-read --symbol BTCUSDT`。命令按以下固定顺序执行：验证项目Client Metadata、启动随机端口本机回调、显示并打开Binance授权页、交换仅内存Token、初始化MCP、发现七个只读Spot工具、读取账户/挂单/成交/订单/手续费/规则/盘口，最后关闭传输并清除其Token副本。终端只输出裁剪后的账户摘要，不输出Token、授权码、完整MCP响应或服务端错误正文。

After installation, run `bstock-mcp-read --symbol BTCUSDT`. It validates the project metadata, binds a random-port loopback callback, displays and opens Binance authorization, exchanges a memory-only token, initializes MCP, discovers the seven allowlisted Spot readers, collects the bounded snapshot, and closes the transport. Terminal output is a reduced account summary; it never prints the token, authorization code, complete MCP payloads or server-controlled error bodies.

桌面“账户 / Account”页也提供“连接并只读一次”。授权等待、网络读取和取消均在单一后台线程执行；界面保持响应，关闭窗口会请求取消并等待资源安全释放。页面只显示裁剪后的账户快照与临时授权URL，没有下单按钮，不会把Token写入参数、日志或运行目录。

The desktop Account tab also provides “Connect & read once.” Authorization waiting, network reads and cancellation run on one background worker; the UI remains responsive, and window close requests cancellation before releasing resources. The tab shows only a reduced account snapshot and temporary authorization URL. It has no order button and never writes the token to preferences, logs or runtime files.

本轮离线验证：Python 3.11完整回归338项通过，源码编译与依赖检查通过。默认公网metadata尚不可用时，命令和桌面入口都会在浏览器授权和Token交换前失败关闭；这不是一次真实账户登录验收。

Offline validation for this revision: 338 Python 3.11 tests passed, with source compilation and dependency checks also passing. Both CLI and desktop entry fail closed before browser authorization or token exchange while public metadata is unavailable; this is not a live account-login acceptance.

官方资料 / Official reference: [Binance MCP Server](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic).
