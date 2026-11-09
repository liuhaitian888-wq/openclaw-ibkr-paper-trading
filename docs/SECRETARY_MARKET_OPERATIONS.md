# 秘书主动运营、市场提醒和工程周报

2026-11-09；本页描述行为与证据边界，部署状态见文末实际验收，不以源码存在代替运行。

## 开闭市提醒

`reporting/market_clock.py`由既有cloud secretary-inbox每分钟观察一次，经既有notification outbox投递。单一输入owner、单一通知sender；无新增IB订阅、无模型费用。通知只发owner私聊；`/notify calendar off`可关闭一般时段提醒，日历失效仍保留事件与健康降级。`/hours`随时查看当前状态。

|场所|当地时区|常规阶段|
|---|---|---|
|Nasdaq|America/New_York|04:00盘前；09:30常规；16:00盘后；20:00闭市|
|NYSE主市场Tape A|America/New_York|06:30委托排队、不是成交；09:30常规；16:00闭市|
|米兰ETFplus/EQQQ|Europe/Rome|07:30开盘竞价；09:04起连续交易；17:30收盘竞价；17:35起闭市，竞价结束有最多30秒随机窗口|

EQQQ绑定来自原生IB合约18706552、BVME.ETF、EUR。仅借用合约/场所信息，不把另一连接账户的仓位复制进Paper账户。其他同名EQQQ并非同一基金；不推断伦敦/瑞士/美国或Xetra时段。NYSE Arca等不同场所不能套用NYSE Tape A的开盘前安排。ETFplus没有在本功能中虚构盘后交易。

所有提醒显示柏林时间与交易所当地时间，使用zoneinfo处理美欧切换日期差异。半日市使用单独阶段；闭市时列出连续休市日期、原因和下一已核验开市。凌晨/周末为当前非交易时段；初次启用发当前状态，重启只发当前变化，不回放过期阶段。分钟观察可能合并短于一分钟的随机竞价窗口；提示明确随机窗口，不宣称精确撮合时刻。临时停牌、市场级熔断、订单资格、可交易性与API故障需独立实时证据；本日历不是这些信号的替代物。

### 来源与更新

配置`config/market_awareness_calendar.json`保存核验日期、URL和明确覆盖区间；每条通知带内容SHA256。假日表覆盖2026-01-01至2026-12-31。Nasdaq当前阶段规则只核验至2026-12-05，因官方计划12月6日启用夜盘，不能机械沿用至年底。到期一次提示未知，停止宣称未核验的开市时间；不会自动使用普通工作日规则掩盖过期。到期前14天有一次私人更新提醒；每周工程复盘包含当前截止日期，需要提前核验下一年。

- [Nasdaq夜盘变更公告](https://www.nasdaqtrader.com/TraderNews.aspx?id=ETA2026-56)：预计12月6日启动，当前提醒未冒充已启用；有效期前需确认实际启用和假日跨日规则。
- [Nasdaq假日日历](https://www.nasdaq.com/market-activity/stock-market-holiday-schedule)：2026休市日与11月27日、12月24日13:00提前收市。
- [NYSE分场所时段](https://www.nyse.com/trade/hours-calendars)：Tape A的委托排队不等于盘前撮合。
- [Nasdaq FIX时段规范](https://www.nasdaqtrader.com/content/technicalsupport/specifications/TradingProducts/fixactspec.pdf)：核对普通日及半日市盘后阶段；未来全球时段计划不能当作当前已开放。
- [米兰2026官方年历](https://www.borsaitaliana.it/borsaitaliana/calendario-e-orari-di-negoziazione/tradingcalendar-2026.en.pdf)及[Euronext日期表](https://www.euronext.com/en/trading/trading-hours-holidays)：休市与仅TAH关闭分别处理，6月2日等非TAH日期不误报ETFplus休市。
- [ETFplus阶段](https://www.borsaitaliana.it/etc-etn/perintermediari/negoziazionietipologiadordini/negoziazioneetipologiadordini.en.htm)：竞价窗口及连续交易。
- [exchange_calendars](https://github.com/gerrymanoim/exchange_calendars)：研究了现成交易所session查询方法；本次未引入pandas依赖，也未把其XMIL通用股票时段替代ETFplus。2027米兰已公布规则变化，半日具体时间需继续核验，不能机械延用2026闭市日。

更新步骤：阅读新年度官方年历和场所阶段、人工核对版本差异，更新manifest与回归样例，在linked worktree完整测试后经Git部署。不得由网页文本直接执行代码或扩大交易权限。

## 周报和主动研究

每周日18:00 Europe/Berlin生成私人`ENGINEERING_WEEKLY`，最近7天最多16条归档索引、运行状态计数与可修改Codex prompt。相同ISO周只生成/入队一次，周一不补发过期周报。`/weekly`按需预览不冻结周末证据；已生成本周周报则返回原件。现有财务周报独立保留。

原生Codex自动化`der-2`：周日18:10复盘同一周档案，允许已有授权范围内的离线工程修复，保留PAUSED/MAINTENANCE及部署边界。它是本机应用自动化，不保证Mac离线时准时执行；云端Telegram周报不依赖这次本机唤醒。创建自动化不代表已观察一次定时运行。

自主研究每6小时沿用既有预算与UNKNOWN阻断，优先质量、估值、安全边际、持仓和组合风险、保护校准、多标的危机回测。旧MA2/3仅为Paper执行候选，不等于已验证价值投资收益。没有PIT、复权/退市数据、费用、样本外就报告缺口，不能编造几百年ETF/公司历史。

`/codex 需求`记录原生owner指令的父事件并返回可复制提示；`/engineering`看共享提案箱。秘书模型提出的问题继续为MODEL证据，无原生owner权限冒充。现在共享归档和prompt可用；尚未验收任意Telegram消息自动注入当前桌面聊天。官方[Codex App Server](https://learn.chatgpt.com/docs/app-server)提供thread/turn API；接入还需本机有界消费者、固定目标、启动前保留STARTED、异常UNKNOWN对账及实际turn接受/完成回执。不能把归档成功说成Codex已接收。

## 实际验收

Linked worktree完整套件1054项/80.411秒/OK；FD回归300轮恒5，恢复320轮FD4、线程1→1；gitleaks与OpenSpec全部5项strict PASS。Git整合、云端身份与真实Telegram回执待追加。股票全自动P0、五只继承仓原生保护回读与完整executor验收继续独立跟踪，不能由本提醒功能宣布完成。

本机能力探测：Codex CLI 0.167.0-alpha.3.2，官方App Server stdio `initialize`实际返回ACK；探测拥有并关闭其子进程/管道，无thread/turn创建、无付费推理。这只证明协议入口可用，仍不等于Telegram消息已进入桌面会话。

云端实际：源码02d264b部署到既有分支codex/ibkr-cloud-paper；仅优雅重启inbox与notification两个既有owner。监测、Gateway和有限保护scope身份逐项验证，保护scope只更新commit，原到期/数量/预算不变；7个核心依赖逐字节一致，health差异只增加两个opt-in通知模块并已复核。Gateway PID1450345未变，production.json/PAUSED/MAINTENANCE哈希不变，未发订单。私人22项菜单set/get一致，3条日历通知message137/138/139与上线说明message140均TELEGRAM_ACCEPTED；这是服务器接受，不证明手机已显示。周报真实归档预览2227字符；首次自然周日运行尚未发生。旧delivery UNKNOWN1原样保留、未重放；无新增未知券商订单。

部署验证中先被Git拒绝了一次错误提交号（未改源码），后续验证脚本需补repo导入路径；均已纠正并完成身份/门禁/进程与原生回执复核。备份、失败日志及最终收据保留于engineering/secretary-market-operations-20261109，不把失败尝试写成成功。
