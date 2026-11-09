# 本轮工作与上游方法复查（持续更新）

核验日期2026-11-09，记录至22:49UTC合并部署原生验收。不是全部项目完成声明，也不是收益或法律合规认证。源码、离线验证、云端部署、原生券商结果分别列出。

## 已确认的实际成果

- 交易时段提醒已在原有Telegram通知路径运行；本日Nasdaq/NYSE开盘、常规收盘、ETFplus收盘竞价/闭市均有TELEGRAM_ACCEPTED。Nasdaq收盘后是POST，不能误报所有交易均结束；API/停牌/授权独立检查。EQQQ绑定原生18706552/BVME.ETF，不把其他连接账户仓位复制进Paper。
- 每周工程prompt、/weekly、/codex和22项私人菜单已部署；周报自然定时首次触发仍待观察。Codex自动化der-2每周日18:10柏林复盘，云端18:00出材料。Telegram任意消息自动注入桌面Codex仍未接通，当前可复制prompt诚实交接。
- 一次有持久记录、保留每日预算的Gateway登录恢复已完成新进程/API及独立Paper读回验收；没有循环重启或清空交易门禁。
- 五只旧仓补保护已原生CONFIRMED并独立核实完整覆盖；PFE旧保护保留。有限5/5额度用完，定时器完成后禁用，券商GTC单保留。具体价格、数量、permId与时间见SCOPED_PROTECTION_20261109.md。
- 当前revision4：单笔最多100股/2000USD/风险10USD，单标的250000USD、总敞口1500000USD。100股是上限，不要求每笔买100股；保护旧仓数量不机械套新增买单限额。
- 已原生确认自有EUR换汇和实际费用/现金；唯一FXscope已用完，未重置。重新读取USD现金2019.4231；21:04Z的2000USD会计换算参考约1782.0622EUR，不是可执行买卖价，也不能称一直实时有效。
- 新取得券商USD结算日表：11月9日-69788.66，11月12日累计2019.42306；未来累计金额不能相加或当作当前已结算现金。股票价值日匹配还未核验。

## 已部署的工程与仍待验收边界

持续准入、事务内资金/日预算预留、不可重放transport-start、精确原生绑定、费用版本与现金差额核销、按实际发生时区的买卖成交额、未成交承诺跨日保留、结算字段解析及门禁，均在linked worktree验证。UNKNOWN不靠FAILED改名释放；更正execId不直接相加；较晚现金RPC不能代替余额变化证明。完整测试与秘密扫描收据见CONTINUOUS_ENTRY_20261109.md及私有工程目录。这些工程代码已部署，但旧仓保护和只读采集通过不等于全自动策略已放行。

长周报交接另修：完整证据归档，Telegram发送文本保持完整任务/归档key/权限边界并列出省略数量，避免尾部被截断。此修复随217ac90部署；自然周报触发仍待观察。

## 五项目分别检查到什么程度

|项目|本轮核对证据|第三方方法/组件与边界|
|---|---|---|
|看der独立kander-cross-display|HEAD055c42e；本日独立OpenSpec维护上下文|README确认BetterDisplay虚拟屏、Sunshine服务端、Moonlight客户端；控制层不冒充自研编码器。Package.swift没有外部SwiftPM包声明；未重跑媒体验收。|
|看der后续OpenWorkspace|HEADaceaf93；Nov8含快捷键队列与断连回收提交，Nov9维护上下文|同样复用外部媒体栈；SwiftTesting6.1.3与SwiftSyntax601.0.1来自清单/锁文件，是测试工具链证据。ibflex/ib_async/Canary/healthchecks等review目录是参考材料，不等于嵌入了这些交易后端。|
|买der|当前云端c93ff60，保留deehub及秘书API准备的并行源码；保护、通知、Gateway和只读资金结果分别核对|官方IBSDK1051.1/protobuf5.29.5，既有ib_async2.1.0；QuantConnect IBAutomater已固定源适配；Telegram库/通知现有owner。资金/准入代码已部署，只读现金owner获准运行；正式交易仍暂停。|
|刷der|HEAD5181c50，本轮只读清单核对，未碰既有脏工作|package声明Zod、Electron、OpenClaw、TypeScript、tsx；版本范围不等于已安装锁定版本。wx-cli-readonly目录是本地适配/研究线索，不据此宣称连接器已部署或写消息已获许可。|
|der token|Git仍无首次提交；未暂存其整个源目录|pyproject声明PyYAML6.x，定位本地只读token可观测；本次没有读取原始Codex会话或生产SQLite。未宣称完成源码基线或运行验收。|

共享OpenSpec1.16.1、dee流程、archify和五项目采集器属于研发工具链。它们不授予交易或消息发送权限。本次未因其他项目检查而启动第二个生产owner，未升级这些项目的依赖。

## 今天具体借鉴哪些方法

|来源|借鉴内容|实际使用程度|
|---|---|---|
|QuantConnect/LEAN CashBook与Risk Models|现金保留币种、Decimal换算、风险类别可组合|参考设计；会计换算使用本项目代码，未安装LEAN引擎或宣称其策略回测通过。|
|QuantConnect IBAutomater|登录/2FA/重启生命周期|既有固定源码适配，本轮恢复使用同一个systemd owner；原版权/Apache2许可证保留。|
|NautilusTrader|风险检查与执行/对账分层，订单状态与节流|本轮官方文档研究；未安装或复制执行引擎。|
|exchange_calendars|交易所session、时区和下一session概念|参考；提醒目前核对官方年表，未把通用XMIL当作ETFplus完整竞价规则，也未引入该包。|
|IBKR官方API/交易所/结算机构|原生订单、execId更正、明确费用字段、币种结算日；交易与银行假日区分|使用官方协议事实与精确回读；API返回、Telegram接受、完整交易生命周期分别验收。|
|OpenAI官方AppServer|秘书到Codex的工程交接可能性|只实测initialize ACK；没有创建付费模型turn，也没有宣称桌面任务已经接收。|

风控十类别、哪些是永久技术保障/可调策略限额/信息提醒，以及RTS6和SEC15c3-5适用范围，见RISK_CONTROL_REVIEW.md。止损不能替代身份、资金、幂等、对账或稳定运行。极端行情多标的规模化与放宽门禁按用户要求留待后续讨论。

## 剩余优先事项

1. P0：只读现金生产者已通过原生部署验收；继续补ACCOUNT/EXECUTIONS/AUDIT事实接线、股票价值日匹配和完整资金基线。负的当前已结算USD不能用普通现金正数覆盖。
2. P0：专属执行owner接入信号，连线前最后复核、真实部分成交保护与重启原生验收、旧仓inherited归属及最终T0事件。当前仍PAUSED/MAINTENANCE/SAFE_MONITOR_ONLY。
3. P1：今日日报outbox1094为UNKNOWN，旧953也UNKNOWN；不能自动重发。九个券商order操作CONFIRMED，未知通知不冒充未知订单，也不能隐藏通知不确定性。
4. P1：价值投资的质量/估值/安全边际、多标的PIT历史与危机回测、费用和样本外验证；现有分钟快慢线是工程候选，没有验证获利能力。
5. P1：秘书直接唤醒Codex的可审计桥接、首次自然周报、下一年度/12月Nasdaq23/5规则核验，以及完整许可证/NOTICE与连接器能力清单。

本表能供记录；后续原生事实变化须重新读取，不把当时保护/资金/会话状态说成永久成立。

22:13Z部署验收补充：只读现金原生回执约1.1秒新且epoch/connection/reconciliation匹配；CURRENCY_BOOK依赖仍WAITING_DEPENDENCY。paper-safety四次资源样本FD5–6、线程4、RSS约41MB，秘书FD9/线程2；短样本不等于长期无泄漏。工程通知outbox1202 TELEGRAM_ACCEPTED，手机显示未验证。

并行变更核对：云端已通过另一条经核验的Git部署前进到5df418d（deehub身份/公共路由）；本轮保留该源码及相关配置，未回退217ac90。故障锁及通知/订单不确定性分域是后续隔离候选，未据此启用新交易。

最新补充：c93ff60已原生验收，1147项完整隔离测试通过；文件故障锁、通知/交易不确定性分域、精确原生时间已上线。六仓保护和金融计数不变，Gateway未重启；账户基础健康/结算价值日/执行闭环未通过，仍暂停。秘书API仅为准备状态，实际密钥及模型接通验收另有阻塞，不能称全天候模型已运行。
