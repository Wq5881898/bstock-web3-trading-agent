# Median公共行情与桌面 / Median public feed and desktop

## 已接通 / Connected

策略页现在可以选择 **Median · 逐笔模拟 / Tick paper**，编辑窗口（1–100笔）与买入/卖出偏离比例。仅支持paper，不提供真实下单。当前配置v4同时保存MTF、Median及Range参数，兼容完整v1/v2/v3格式；重启窗口不会自动运行。Median不使用MTF的EMA/ATR/止损参数。

The Strategies tab now enables **Median · Tick paper**, with a 1–100-trade window and entry/exit deviation fractions. Paper only; no live orders. Preferences v4 stores MTF, Median and Range inputs, reading exact v1/v2/v3 schemas compatibly. Window restart never auto-starts. Median does not use MTF EMA/ATR/stop inputs.

选择Median后，使用同运行目录下独立的`<symbol>_paper_median.sqlite`模拟账本和状态锁；不接管MTF仓位，不共享MTF模拟资金。首次本金1000，每个账本分别风控，不能把它当作真实账户级总风险上限。SQLite重开严格核对标的、策略和风控参数；不匹配时恢复原设置，不能自动修改既有账本。

Median uses a separate `<symbol>_paper_median.sqlite` ledger and state lock in the runtime directory. It neither adopts MTF positions nor shares their paper funds. Each ledger starts with 1,000 and has independent risk controls, not an aggregate real-account risk limit. SQLite restore strictly checks symbol, strategy and risk settings; restore original inputs on mismatch rather than modifying the ledger automatically.

## 数据与恢复 / Data and recovery

公共读取使用固定`data-api.binance.vision`主机的`GET /api/v3/aggTrades`，不传账户凭证，不跟随重定向，不是将MCP下单改成API下单。按官方接口定义，`fromId`包含起始ID，单页最多1000，未指定游标时返回最近成交：[官方聚合成交文档](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)。首次读取最多200笔预热；之后从已提交ID+1继续。每轮最多3页，满页只补指标不补做历史交易；非满页仍须满足5秒新鲜度才能生成模拟成交。返回错误起点、跳号、倒序或非法数值时拒绝消费。

Public GETs are pinned to `data-api.binance.vision/api/v3/aggTrades`, without account credentials or redirects; this is not an API-order fallback for MCP. The official endpoint defines inclusive `fromId`, a 1,000-row maximum and latest trades when no cursor is specified ([official documentation](https://developers.binance.com/en/docs/catalog/core-trading-spot-trading/api/rest-api/market)). The initial request warms up to 200 trades; subsequent requests continue from committed ID + 1. Each cycle reads at most three pages. Full pages are catch-up only; short pages still require five-second freshness for paper fills. Wrong cursors, gaps, reversed timestamps and invalid numbers are rejected.

Median默认每3秒启动一轮，工作线程单飞；不是低延迟交易引擎。HTTP限流遵守数字Retry-After，其他失败短暂退避。网络请求有连接/读取超时，但停止不强行打断正在进行的请求。公共行情错误或bStock市场状态不可用时持久化停买；补齐至非满页且最后成交新鲜后，用户再手动恢复，才允许清除数据恢复标记。市场状态仍通过bStock目录/状态适配，不因此支持任意BTC/ETH标的。

Median polls every three seconds on one worker; it is not a low-latency engine. Rate limits honor numeric Retry-After; other failures back off briefly. Connect/read timeouts apply, but stop does not interrupt an in-flight request. Public-feed failures or unavailable bStock market status persist a BUY pause. After contiguous catch-up reaches a short page and the last trade is fresh, explicit manual resume can clear recovery state. Catalog/status resolution remains bStock-specific; arbitrary BTC/ETH desktop support is not implied.

重开已有Median账本会暂停买入，但有效原策略卖出仍可执行。手动恢复不清零日基准，不绕过日亏损或当日开仓次数限制。恢复在新一轮行情核对后处理，不立即产生买入。数据缺口恢复还要求游标比本次错误（或重开待恢复状态）时前进；仅返回空页、旧尾部碰巧新鲜也不能解除暂停。若尚未追平或数据不新鲜，保持暂停。

Reopening an existing Median ledger pauses entries, while valid strategy exits remain eligible. Manual resume preserves the daily baseline and cannot bypass active loss/count limits. Resume is checked after a new feed cycle, never creating an immediate BUY. Gap recovery additionally requires cursor advancement after the error (or reopening recovery state); an empty response with a still-fresh old tail is insufficient. Incomplete/stale catch-up retains the pause.

K线每15秒刷新供展示，Median指标仍只使用逐笔价格；K线失败不会挡住有效逐笔卖出。每笔本轮模拟成交在监控表显示trade_id，完整成交保存在SQLite；表格不是完整历史查看器。后续分页出错前已提交的页仍在账本中，异常轮次可能未显示这些成交，不能用屏幕行数代替账本核对。

Charts refresh every 15 seconds for display; Median indicators use trade prices only. Chart failures do not block valid tick exits. Each returned simulated fill appears with trade_id; SQLite retains the complete audit, while the table is not a historical ledger viewer. Pages committed before a later page failure remain in SQLite even if that failed cycle does not display their fills. UI row counts are not a reconciliation source.

账户页显示当前模拟现金、持仓成本/数量、已实现损益、累计手续费、开仓和连亏次数。Median从SQLite载入最近100笔成交，重启后仍可查看；MTF只显示账户摘要和本次运行产生的事件，因为它尚无独立持久成交明细表。该页面是模拟账本视图，不是Binance账户余额或成交单。

The Account tab displays paper cash, position cost/quantity, realized PnL, cumulative fees, entries and loss streak. Median reloads the latest 100 SQLite fills across restarts. MTF shows its account summary and current-run events because it has no separate durable fill-history table yet. This is a paper-ledger view, not a Binance balance or trade statement.

SQLite在所属工作线程关闭，界面等关闭完成后才释放状态锁；关闭异常保留锁并提示。CLI不使用Qt状态锁，但Median数据库修订号仍拒绝旧写入方覆盖。

SQLite closes on its owning worker; the GUI releases the state lock only afterward. Cleanup failure retains the lock and shows an error. CLI does not use Qt locks, but Median database revision checks still reject stale writers.

## 验证 / Verification

- 最新完整本地回归（含Range）：256项通过，46.58秒。 / Latest full local regression (including Range): 256 passed in 46.58s.
- 原生合成桌面：651轮、38次故障注入通过，12.36秒，Median参数页和账户历史页截图已检查。 / Native synthetic desktop: 651 attempts, 38 injected failures, 12.36s; Median controls and account history were visually checked.
- 真实公共NVDAB读取两轮：已保存逐笔游标，显示239根已收盘1m K线；期间成交不新鲜，正确等待，无模拟成交。不是公共行情买卖闭环或长时间验证。 / Two public NVDAB evaluations persisted a trade cursor and displayed 239 closed 1m bars; trades were stale, so no paper fills occurred. This is not a public-market fill round trip or sustained acceptance.
- 公共读取证据 / Public-read evidence: `runtime/median-public-smoke/1789014178051671800/report.json`.
- 桌面证据 / Desktop evidence: `runtime/desktop-acceptance/1789067409823038600/`.

可复验 / Reproduce:

```powershell
.venv\Scripts\python -m pytest
.venv\Scripts\python scripts/local_desktop_acceptance.py
.venv\Scripts\python scripts/median_public_smoke.py
```

最后一条会读取公共网络行情，并在独立runtime目录使用模拟资金，不接账户或发送真实订单。尚缺长时间真实行情验收、完整成交历史UI、多策略账户级风险归并及MCP真实执行闭环。

The last command reads public network data and uses isolated simulated funds under runtime, without account access or real orders. Sustained market acceptance, a full history UI, multi-strategy account-risk consolidation and MCP live execution remain pending.
