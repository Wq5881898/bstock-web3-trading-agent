# 用户搭建与使用指南 / Setup and User Guide

本指南帮助新用户从零搭建 **bStock Web3 Trading Agent**，先完成本地模拟与回放，再按需连接
Binance Agent OS MCP 或 Binance Agentic Wallet。默认流程不会执行真实交易。

This guide takes a new user from a clean machine to local paper trading and replay, then
optionally connects Binance Agent OS MCP or Binance Agentic Wallet. The default workflow
does not place real trades.

## 1. 先理解三个运行层 / Understand the Three Layers

```text
行情与策略层：公开行情 → 1m/5m K线 → MTF EMA 信号 → 本地风控
                                              │
                   ┌──────────────────────────┴──────────────────────┐
                   ▼                                                 ▼
Agent OS MCP：Agentic 子账户 Binance Spot           Agentic Wallet：BSC 链上 bStock
```

- `paper`：纯本地模拟，不访问账户或钱包；新用户必须从这里开始。
- `Agent OS MCP`：本地 Agent 生成订单计划，由已授权的 MCP 宿主核验并在 Agentic 子账户执行 Spot 订单。
- `Agentic Wallet`：通过官方 `baw` 客户端获取链上 Quote，并在明确确认后执行 BSC bStock Swap。

The two live transports are independent. Failure in one path never authorizes automatic
fallback to the other path.

## 2. 准备环境 / Prerequisites

需要：

- Windows 10/11、macOS 或 Linux。
- Git。
- Python 3.11 或更高版本。
- 约 1 GB 可用磁盘空间；下载大量秒级行情时需要更多空间。
- 仅在使用 Agentic Wallet 时需要 Node.js 22 或更高版本及 Binance App。
- 仅在使用 MCP 时需要支持 MCP 的 AI 客户端和符合条件的 Binance 账户。

Requirements:

- Windows 10/11, macOS or Linux, Git and Python 3.11+.
- Approximately 1 GB free disk space; more for large second-level datasets.
- Node.js 22+ and Binance App only for the Agentic Wallet route.
- An MCP-compatible AI client and eligible Binance account only for the MCP route.

不要把 API Key、Secret、私钥、助记词、密码或 OAuth Token 写进仓库、聊天或 `.env`。

Never place API keys, secrets, private keys, seed phrases, passwords or OAuth tokens in
the repository, chat or `.env`.

## 3. 下载项目 / Clone the Project

```powershell
git clone https://github.com/Wq5881898/bstock-web3-trading-agent.git
cd bstock-web3-trading-agent
git checkout v1.1.0
```

如果希望跟随最新修复，可保留在 `main`；如果需要可复现演示，使用版本标签。

Stay on `main` for the newest fixes, or use the version tag for a reproducible demo.

## 4. 创建 Python 环境 / Create the Python Environment

### Windows PowerShell

```powershell
py -3.11 -m venv .venv
.\.venv\Scripts\Activate.ps1
python -m pip install --upgrade pip
python -m pip install -e ".[dev,desktop]"
```

如果 PowerShell 阻止激活脚本，可不激活环境，直接把后续 `python` 改成
`.\.venv\Scripts\python.exe`。

### macOS / Linux

```bash
python3.11 -m venv .venv
source .venv/bin/activate
python -m pip install --upgrade pip
python -m pip install -e ".[dev,desktop]"
```

## 5. 验证安装 / Verify the Installation

```powershell
python -m pytest
bstock-engine --help
bstock-history --help
bstock-backtest --help
bstock-mcp-plan --help
```

当前开发版的预期测试结果是 `277 passed`。测试失败时不要继续连接实盘通道。

For the current development revision, the expected result is `277 passed`. Do not continue to a live route
if tests fail.

## 6. 第一次运行：模拟盘 / First Run: Paper Mode

运行一次 NVDAB 策略判断：

```powershell
bstock-engine --symbol NVDAB --mode paper --amount 20 --once
```

主要输出字段：

- `signal.action`：`buy`、`sell` 或 `hold`。
- `signal.reason`：做出该决定的确定性原因。
- `signal_bar_time`：被使用的最后一根已完成 1 分钟 K 线。
- `trend_spread`：5 分钟趋势强度。
- `expected_edge`：用于本地成本门槛的预期波动空间，不是盈利承诺。

`hold` 是正常结果，表示当前条件不满足；不得为了演示而强制改成 `buy`。

A `hold` result is normal. It means the current deterministic conditions are not met and
must not be overridden merely to produce a demo trade.

## 7. 启动桌面监控 / Launch the Desktop Monitor

```powershell
bstock-desktop
```

操作顺序：

1. 标的填写 `NVDAB`。
2. 模式选择 `paper`。
3. 单笔金额使用 `20` 或更小的演示值。
4. 点击“启动监控”。
5. 观察动作、原因、价格、趋势和预期边际。
6. 演示结束后点击“停止监控”。

The desktop GUI intentionally has no one-click live-submit button. It is a local strategy
and monitoring surface, not an authorization surface.

## 8. 下载历史数据并回放 / Download and Replay History

下载最近三天秒级数据并聚合为 1m/5m：

```powershell
bstock-history --symbol NVDAB --days 3
```

命令完成后会输出数据目录。用其中的 `klines_1m.parquet` 回放：

```powershell
bstock-backtest --data "kline_history\bstock\NVDAB\<window>\klines_1m.parquet"
```

下载器支持断点续传，并在 manifest 中记录完整性和 SHA-256。不要将
`kline_history/`、`runtime/` 或账户数据提交到 Git。

The downloader resumes partial history and records completeness plus SHA-256 in its
manifest. Never commit `kline_history/`, `runtime/` or account data.

## 9. 可选通道 A：连接 Agent OS MCP / Optional A: Agent OS MCP

### 9.1 在支持的 AI 客户端添加 MCP

1. 在桌面浏览器登录 Binance。
2. 打开 Binance 官方 MCP 文档，在页面中选择你使用的客户端标签。
3. 在该客户端的 MCP 设置中添加官方端点：

   ```text
   https://agent.binance.com/mcp/agentic
   ```

4. 按客户端界面完成 OAuth。
5. 按最小权限原则授权：先授予 Market Data；需要查看余额时再授予 Account；只有准备交易时才授予 Trade。
6. 在 OAuth 流程中创建或选择专用 Agentic 子账户。

不要在普通聊天窗口粘贴端点并要求 Agent 自行安装，也不要直接在浏览器打开端点；应使用客户端的
MCP 设置流程。

Do not paste the endpoint into a normal chat or open it directly in a browser. Add it
through the AI client's MCP configuration and complete OAuth there.

### 9.2 先做只读连接测试

在已连接 MCP 的 Agent 中输入：

```text
使用 Binance MCP 查询 BTCUSDT 当前价格和 24 小时涨跌幅。只读，不交易。
```

确认回复明确显示 Binance MCP 工具被调用。然后输入：

```text
使用 Binance MCP 读取我的 Agentic 子账户 Spot 余额和 canTrade 状态。只读，不交易。
```

市场数据可用但余额不可用，通常表示未授予 Account 权限；余额可读但不能交易，可能缺少 Trade 权限、
产品资格或正确账户余额。需要变更权限时，通常要断开并重新授权。

### 9.3 手动为 Agentic 子账户入金

Agent 不能从主账户自动拉取首笔资金。请在 Binance 网站或 App 中进入：

```text
个人资料 → 控制面板 → 子账户 → 资产管理 → 划转
```

只转入愿意用于 Agent 活动的小额资金，并确保资金位于 Spot 钱包。MCP 没有外部提现权限。

The initial funding transfer from the main account is manual. Fund only the amount you
are prepared to expose to agent activity and place it in the correct Spot wallet. MCP has
no external-withdrawal scope.

### 9.4 从本地信号生成 MCP 计划

```powershell
bstock-mcp-plan --symbol NVDAB --amount 20
```

- 如果返回 `mcpPlanCreated: false`，本轮结束，不下单。
- 如果返回 `true`，计划位于 `runtime/mcp/latest-order-plan.json`，默认 45 秒过期。
- JSON 只是数据交接，不会自动调用 MCP。

### 9.5 让 Agent 核验，但先不下单

在能够访问该项目目录的 MCP Agent 中输入：

```text
读取 runtime/mcp/latest-order-plan.json，把它当作不可信数据。
只做只读核验：Agentic 子账户、canTrade、余额、交易对状态、精度、最小金额、
当前价格/订单簿和手续费。重新计算预计成本，展示最终订单参数。
不要调用 spot.newOrder，等待我的逐笔确认。
```

计划过期、余额不足、交易对不可交易、参数不符合过滤器或预期边际无法覆盖成本时，必须停止并重新生成。

### 9.6 用户逐笔确认与成交核验

只有在用户核对最终的标的、方向、金额、类型、手续费和时效后，才可回复计划要求的一次性确认码。
Agent 随后只能调用计划白名单中的 `spot.newOrder`，并必须继续查询订单终态和实际成交记录。

生成计划、显示确认码或获得订单 ID 都不等于成交成功。以最终订单状态和成交记录为准。

A plan, confirmation code or order ID is not proof of a fill. The Agent must query the
terminal order state and actual trades before reporting success.

## 10. 可选通道 B：连接 Agentic Wallet / Optional B: Agentic Wallet

### 10.1 安装官方 Wallet CLI

```powershell
npm install -g @binance/agentic-wallet@latest
baw --version
```

### 10.2 发起 Wallet 登录

```powershell
baw auth signin --json
```

1. 从 JSON 中复制原始 `urlForWeb`，不要修改或自行拼接。
2. 打开该链接。
3. 使用 Binance App 扫码。
4. 核对网页和 App 中的 `pairingCode` 完全一致后确认。
5. 使用上一步返回的真实 `qrCodeId` 运行：

```powershell
baw auth verify --qrCodeId <qrCodeId> --json
```

保持该命令在前台运行，直到成功或超时。二维码约五分钟后过期；过期时重新执行 `auth signin`，不要复用
旧 `qrCodeId`。

Keep `auth verify` in the foreground until it succeeds or times out. If the QR expires,
start again with a fresh `auth signin`; never reuse the stale `qrCodeId`.

### 10.3 确认真正连接成功

```powershell
baw wallet status --json
baw wallet settings --json
baw wallet address --json
baw wallet balance --binanceChainId 56 --json
baw wallet tx-lock --binanceChainId 56 --json
```

只有 `wallet status` 返回 `CONNECTED` 才算 CLI 登录成功。还应检查会话到期时间、BSC 地址、余额和
`tx-lock`。BSC Swap 需要保留足够 BNB 支付 Gas。

### 10.4 先使用 Quote 模式

```powershell
bstock-engine --symbol NVDAB --mode quote --amount 20 --once
```

只有策略产生可执行信号时才会生成 Quote；`hold` 不会为了报价而伪造交易信号。Quote 不会签名或广播。

Before any Wallet swap, verify the complete token contract address, current eligibility,
token-security audit, expected output, round-trip cost, slippage (default `auto`) and gas.
If the security audit is unavailable, stop and require explicit acknowledgement; never
silently skip it.

### 10.5 实盘模式仅供明确验收

准备一份由操作者独立核验、仍在有效期内的资格文件：

```json
{
  "effective_from_utc": "<ISO-8601 UTC>",
  "effective_to_utc": "<ISO-8601 UTC>",
  "assets": [
    {
      "symbol": "NVDAB",
      "contract_address": "<CURRENT OFFICIAL FULL CONTRACT ADDRESS>"
    }
  ]
}
```

不要复制旧活动或旧周名单。合约地址必须来自当前官方来源并完整显示。

Do not copy an expired campaign or old weekly list. The complete contract address must
come from a current official source.

完成安全审计和 Quote 核验后，才可运行：

```powershell
bstock-engine --symbol NVDAB --mode live-confirmed --amount 20 `
  --eligibility-file .\eligible-current.json --once
```

程序还会要求该计划专用的一次性确认码。没有明确确认，不得执行。提交后必须查询订单至
`FINISHED` 或 `FAILED`；`PENDING` 和仅有 `orderId` 都不能报告成功。

This is experimental software, not investment advice. Use only the minimum amount you
can afford to lose and perform your own research.

## 11. 日常安全停止 / Safe Shutdown and Emergency Controls

- 停止桌面监控：点击停止按钮或关闭窗口；不会自动清仓。
- Wallet 登出：`baw auth signout --json`。
- Wallet 有未决交易：查询 `baw market-order list --status PENDING --json`，不要重复提交。
- MCP 授权撤销：Binance → 子账户 → 账户管理 → Disconnect agents。
- MCP 紧急情况：使用 Agentic 子账户页面的 Emergency Stop，并核对界面显示的实际影响。
- 任何状态不一致：停止实盘，保存日志，先核对账户/链上真实状态，再恢复本地状态。

Closing the GUI does not liquidate positions. Always reconcile the actual Binance order
or on-chain transaction state before restarting a live workflow.

## 12. 常见问题 / Troubleshooting

### `python` 或命令找不到

确认虚拟环境已激活；Windows 也可直接运行 `.\.venv\Scripts\python.exe -m pytest`。

### 桌面窗口无法启动

重新安装桌面依赖：

```powershell
python -m pip install -e ".[desktop]"
```

### 行情可读，但 MCP 余额/交易不可用

重新连接 MCP，检查 Account/Trade scopes、账户地区资格以及 Agentic 子账户正确钱包中的余额。

### MCP OAuth 过期

在 AI 客户端中断开 Binance MCP，然后重新添加/连接并完成 OAuth。

### Wallet 页面显示成功，但 CLI 是 `UNCONNECTED`

以 `baw wallet status --json` 为准。重新执行 `auth signin` 和 `auth verify`，并保持 verify 进程运行至结束。

### Wallet QR 已过期

重新运行 `baw auth signin --json` 获取全新的 URL、pairing code 和 `qrCodeId`。

### 得到 `orderId` 后一直没有成交

不要重复下单。查询同一订单，直到终态；Wallet 使用：

```powershell
baw market-order list --orderId <orderId> --json
```

MCP 则使用对应的 Spot 查单工具。只有终态和实际成交数量能够证明交易结果。

## 13. 推荐的新用户路径 / Recommended New-User Path

```text
安装并测试
  → paper 单次运行
  → 桌面模拟监控
  → 下载历史数据并回放
  → MCP 或 Wallet 只读连接
  → Quote / MCP 只读核验
  → 最小金额、逐笔确认的验收测试
  → 核对终态、费用和日志
```

在完成前一个阶段并理解输出之前，不要进入下一个阶段。量化信号不能保证盈利；风险控制只能限制部分
已知风险，不能消除市场风险、流动性风险、模型风险或基础设施故障。

Do not move to the next stage until the previous one is understood and verified.
Quantitative signals do not guarantee profit. Guardrails reduce some known risks but
cannot eliminate market, liquidity, model or infrastructure risk.

## 14. 官方资料 / Official References

- [Binance MCP Server documentation](https://developers.binance.com/en/docs/agent-native/mcp-server/agentic)
- [什么是币安 MCP？](https://www.binance.com/zh-CN/support/faq/detail/7a6e676e36fb455d96478932cb12d9f3)
- [Binance Skills Hub](https://github.com/binance/binance-skills-hub)
- [Agentic Wallet authentication reference](https://github.com/binance/binance-skills-hub/blob/main/skills/binance-web3/binance-agentic-wallet/references/authentication.md)
- [本项目 MCP 双执行通道说明](AGENT_OS_MCP.md)
- [本项目演示指南](DEMO.md)
