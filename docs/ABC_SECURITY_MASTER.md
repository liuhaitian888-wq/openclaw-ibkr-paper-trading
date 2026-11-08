# ABC证券总名单：根因、维护与LEAN原理

核查日期：2026-11-08。当前许可仍按PRODUCTION.md；目录更新不是策略、账户、行情或交易权限批准。

## 为什么之前只有3条？

本轮云端只读核查：

| 数据源 | 条数／时间 | 实际用途 |
| --- | --- | --- |
| data/security_master.csv | 13,024；旧快照2026-07-11 | 上市证券参考主档，未接入秘书总名单数据库查询 |
| data/us_equity_universe.csv | 71 | 旧策略种子名单，不能冒充全市场 |
| trading_audit.sqlite3 → canonical_pool_state | PFE、BAC、KO共3条，均MASTER_UNIVERSE；2026-10-27 | 已进入运行状态机的候选；source为Existing CSV MONITOR_ONLY; fundamentals as-of unverified |
| 上一版秘书/universe | 只查canonical_pool_state，再加私人关注 | 因此只展示3条；这是查询接线不完整，不是ABC只允许3只股票 |

run_autonomous_trading_agent.sync_canonical_pool_state只为运行候选upsert状态，不会把完整证券主档全部导入。当前自动执行暂停，不能为了补总名单启动Mode9。上一轮把该入口叫作总名单不准确，本轮修正。

此前每6小时机制实际执行过，但返回NO_OBSERVED_SYMBOLS、没有可抽样的行情标的；这不等于实时行情权限已核验通过。

## 现在总名单怎样维护？

从Nasdaq Trader官方[nasdaqlisted与otherlisted字段定义](https://www.nasdaqtrader.com/trader.aspx?id=symboldirdefs)取得两份完整文件。来源固定HTTPS，保留原文件、SHA-256、源生成时间、采集时间、独立刷新批次；不会把下载时间写成报价时间或源生成时间。

| 源上市市场 | 目录归类 | 权限 |
| --- | --- | --- |
| NASDAQ | Network C | 当前实时／Paper共享待核验 |
| NYSE | Network A | 当前实时／Paper共享待核验 |
| NYSE American、Arca、Cboe BZX、IEX | Network B | 当前实时／Paper共享待核验 |
| 当前官方字段说明未解释的交易所代码 | UNKNOWN | 网络分类及实时权限均待核验，不猜测 |

这是按上市市场及ABC订阅范围做的目录归类；不等于该账户已取得每个产品／合约的完整权限。保留源ACT、CQS、Nasdaq符号，不自动把它们当IBKR合约身份，conId仍须独立核对。

排除源明确标记的测试证券；ETF按官方字段识别，普通股／普通股份按名称提示分类，优先股、权证、权利及无法确认的品种列OTHER，分类不是券商合约验收。美国上市证券包括外国发行人，不能据上市地把发行人国家写成美国；不覆盖OTC全市场、期权或期货。

2026-11-08取回的两份源文件生成标记均1106202621:31：排除37项测试证券，保留13,239项，其中Network A 2,882、B 4,733、C 5,602，共13,217项ABC范围证券；另22项UNKNOWN保留待分类。数量是本次快照，不是永远不变的市场总数。

## 数据库与刷新安全

权威参考目录现在为既有agent_secretary.sqlite3中的market_security_master；原始CSV保留为历史种子，不静默改写其时间或回填财务指标。新表security_master_current记录当前参考版本，security_master_refreshes保存每次STARTED/SUCCEEDED/FAILED及来源；仍使用已有秘书库及其备份/只读schema/query接口，不新建数据库服务。

scripts/refresh_security_directory.py由生产主工作区的独立有界systemd oneshot拥有，每天08:10 Europe/Berlin（最多随机延后120秒）维护。它只下载两份公开目录，不接IBKR、不订阅报价。现有秘书inbox不承担网络下载，避免阻塞快速控制。启动复用批准monitoring manifest与内核锁，重复刷新owner会被拒绝。

两份源一起验证、事务发布；空响应、HTML、缺字段、重复源身份、日期回退、未来／超过14天源、单源不足1000条、全量突减超过20%均拒绝发布，保留上次成功目录及失败状态。新快照不再出现的条目设active=0并保留原始证据，不能只凭缺失认定永久退市。相同内容指纹与刷新发生身份分开保存。快照保留，不自动删除旧资料。

该目录不写canonical_pool_state，不把13,000多项自动晋级，不创建实时订阅。/eligible继续只显示真实已记录的合格及更高层候选；没有这些验证时可为空。

## 秘书查看与筛选

| 命令 | 结果 |
| --- | --- |
| /universe | 完整ABC范围参考目录，分页12项 |
| /universe network=A | NYSE／A网络 |
| /universe network=C type=STOCK | NASDAQ普通股／普通股份 |
| /universe network=B type=ETF | B网络ETF |
| /universe permission=PENDING | 实时权限待核验；不以订阅声明或上市地直接认定已授权 |
| /universe q=Apple | 名称或原始代码的字面匹配 |
| /universe network=UNKNOWN | 当前映射不能确认的22项 |
| /eligible | 真实运行候选的合格状态，不由目录批量生成 |

筛选可组合。下一页命令保留筛选条件，用稳定源身份续页；通用只读SQL仍限100行／100ms。每页叠加已有安全owner的实际报价状态，不为翻页发券商请求。刚发布的全部参考目录实时权限默认PENDING；本人套餐声明、Paper共享、实际报价与合约身份仍分别保存。

## LEAN的idea是什么？

LEAN将“大范围选谁”和“为入选股票接收什么行情”分开。以美股基本面Universe为例：先用定期更新的价格、成交额、基本面等选股数据缩小范围，选择函数返回股票；引擎据此增减订阅、触发证券变化事件，再让策略消费所需频率的数据。持仓、挂单或其他仍有需求的订阅不应只因退出选股名单就被立即丢弃。它不仅能用于美股，也有ETF成分、期权／期货合约等Universe形式。

这个模式不专属于IBKR的ABC，也不是把ABC变成无限线路。ABC是市场数据授权范围，LEAN订阅还包含证券、Trade/Quote类型、Tick/Second/Minute/Daily分辨率及数据源等配置。

关键前提是“宽范围选股数据从哪里来”：使用QuantConnect Cloud时可以由其Universe数据集提供；本地部署需要相应数据或自备源。IBKR的A/B/C Level 1套餐并不会因此自动附送完整基本面选股数据库。仅安装LEAN、ib_async或改成异步都不能取消IBKR账户线路限制。

LEAN还支持将数据提供方与执行券商分开：外部数据源承担广覆盖行情，IBKR承担订单与账户；经第三方数据源取得的订阅不占IBKR行情线路，但外部源本身仍有授权、覆盖与容量边界。本项目本轮只接公开证券目录，没有购买或部署QuantConnect数据源或LEAN引擎。证券目录没有价格／成交量，不能凭它直接筛出高成交额股票。

官方来源（2026-11-08）：[Universe机制](https://www.quantconnect.com/docs/v2/writing-algorithms/universes/key-concepts)、[基本面Universe](https://www.quantconnect.com/docs/v2/writing-algorithms/universes/equity/fundamental-universes)、[IB数据源与混合数据提供方](https://www.quantconnect.com/docs/v2/cloud-platform/datasets/interactive-brokers)、[本地IB部署所需Universe数据](https://www.quantconnect.com/docs/v2/lean-cli/live-trading/brokerages/interactive-brokers)。
