# Nov7任务收口清单（Nov8恢复执行）

最新运行证据（Nov8 02:20 Berlin）：卡住的Gateway经现有唯一owner受控修复启动后，上游与全账户回读恢复；独立READBACK_COMPLETE通过，真实恢复消息983获群回执。已有认证配置通过，当前无需本人重复登录。行情尚无新鲜报价/连续K线证据，休市门禁保持。

状态必须区分：代码/离线通过、已部署、真实在线通过、待本人认证/参数。目标没有缩减成“服务进程在跑”。用户最后要求按需搜索群里的机器人消息与工作记录，不新增整群档案。

| 工作项 | 当前证据与剩余验收 | 本人参与 |
|---|---|---|
| 云连接/API/行情 | Nov8 02:09、02:15 Berlin：SSH正常，Gateway与监测/通知/秘书服务active；上游未恢复，独立采集AUTH_OR_CONNECTION_REQUIRED，报价为空，API重连4次耗尽（修复前）。Nov7 07:09:54首次1100，07:10:09回读故障；无1101/1102恢复记录 | 02:20已完整回读；暂不需再次登录。不在聊天发凭据 |
| 自动恢复 | 修复“上游断开时跳过API心跳超时”条件；API心跳新鲜则保留socket，心跳超时走原持久退避/预算。预算不重置，Gateway不为验收重启 | 无需批准修复；02:20已恢复；持续运行及休市后行情另验 |
| 群内历史搜索 | /search及模型telegram_search接本机按需用户搜索，精确der+机器人ID；无消息镜像、发送、已读回执或下载。缺会话明确NEEDS_OWNER_USER_SESSION。Telethon接口代码及假客户端测试不等于真实接通 | 需要审核并授权新的Telegram用户会话，见TELEGRAM_SEARCH.md |
| 工作记录查询 | /work、/searchlog直接查现有秘书记录与本机器人outbox/回执；模型search_records有分页/大小/SQL预算，结果仅owner私聊 | 无需本人；不得冒充全部机器人群历史 |
| Telegram职责与隐私 | 日报公开群发；私密查询/秘书/风险/控制只给owner；精确ID、转发/匿名/机器人拒绝；短通知+折叠详情+同事件卡+本地未读与偏好；真实私聊954/message43已核验。953原始说明UNKNOWN保留，不重发 | 旧群里的私人对话不会自动隐藏；不删除历史证据 |
| 日报 | Nov8 09:00:06北京/02:00:06柏林，群message156接收的是缺报告警，included_reports为空，今日新日报未生成。新增content_state和daily_report_server_accepted，避免把告警送达说成日报送达 | 02:20新鲜完整快照已生成当日CJK-v4，现有一次补报逻辑发送986成功；不重发UNKNOWN |
| 新闻/SEC/宏观 | Fed成功；AAPL/META/MSFT/NIO/PFE/T/NVDA SEC成功；BLS API时间序列缓存有数据，BLS RSS403按退避；IBKR新闻受连接阻断，不能据此判无订阅；Reuters等未核验API，Similarweb仅限定免费网页 | 需要付费订阅/账号权限时另列，不购买昂贵服务来做绿状态 |
| 审计库 | 已切换79现用表、98历史表保全原库；每表内容/rowid/schema/索引/FK验证及四库恢复证据在AUDIT_REORGANIZATION.md。当前活库约2.59MB，保留1.86GB来源档案与每日备份 | 无删除或重新迁移；异地备份目标尚未指定 |
| 持仓保护 | 最后完整清单AAPL17/META100/MSFT13/NIO200/PFE8/T3，已核验时PFE有8股SELL STP GTC 23.01；断连后均不能当作当前确认，现有单不撤不改 | 当前仅整理。需另行批准保护/持仓纳入策略或处理方式 |
| 绩效T0/资金 | 事实采集已有tracking epoch，策略绩效T0仍草案。现金不透支、必要现金换汇已获授权；当前负USD读数陈旧，无换汇订单、无策略启动 | T0须新鲜NAV/现金/FX/费用及策略范围；明确费预留 |
| 参考/日志/部署 | 新增官方Telegram搜索、Telethon迁移源、TDLib权衡；沿用SQLite/LEAN、IBAutomater、Healthchecks、IBKR官方资料。linked-worktree完整测试+gitleaks后Git部署；留可回查本机与云审计 | 不自动追上游main，不复制他人源码代替许可审查 |

## 自动交易还差哪些门

已通过或授权：自有现金/不新增透支政策、必要现金换汇授权、当前不存在UNKNOWN订单操作或未结order_requests、有效数值文档格式。旧NVDA有限试验已完成3/3且关闭，不可重置。

未通过的运行条件：IBKR完整新鲜回读、USD可用现金+买单资金预占+费用预留、新鲜真实bid/ask、连续完整K线、实际可交易时段、全部持仓和外部挂单纳入风险、保护覆盖与新成交核对。周末休市不解释认证失败，也不允许伪造新鲜行情。

未通过的工程条件：canonical持仓生命周期与策略归属对账；持续signal→approved executor→部分成交保护→重启对账完整执行验收；T0事件与会计口径。已完成的三笔有限测试不替代这些条件。正式production manifest、策略execution_approved及PAUSED/MAINTENANCE仍禁止执行，不能仅因网络恢复解除。

## 需要你一次提供/批准的参数

| 参数或批准 | 当前值/状态 | 需要明确的内容 |
|---|---|---|
| 策略与执行标的 | 仅MONITOR_ONLY：classic_conservative_trend，PFE/BAC/KO；研究/持仓公司不是自动批准的交易池 | 批准具体版本、标的、执行时段及是否沿用现有1股、60秒bar/2快3慢等配置 |
| /qmax | 模板1，revision0未作owner override | 单笔股数上限 |
| /omax | 模板200 USD | 单笔金额上限 |
| /rmax | 模板10 USD | 单笔风险上限 |
| /smax | null | 单股持仓敞口上限USD（包含已有及外部敞口） |
| /gmax | null | 账户总敞口上限USD |
| 费用/FX预留 | fee_reserve_usd=null | 每笔/合计资金预留与FX费用边界；不能按0处理未知费用 |
| 既有持仓 | 上述6项，当前不可新鲜确认 | 只观察、纳入指定策略或具体保护处理；当前没有卖出或撤单授权 |
| T0 | 未激活 | 指定策略、基准币种/FX口径、费用/现金流归因、起算事件；不得把旧持仓和旧盈亏抹掉 |
| 最终启用 | 未批准，仍PAUSED/MAINTENANCE | 上述真实验收完成后，批准精确部署身份与解除范围；现在不请求空白批准 |

之前已批准的现金政策和必要换汇无需重复确认。参数不齐时继续研究与事实采集，但不新增交易。

## 上网研究清单与结论

1. IBKR状态页和1100/1101/1102/2110语义，QuantConnect/IBAutomater维护/登录失败处理：官方维护窗口不是证明本账户已恢复，vendor整个周六reset guard不能变成业务许可。
2. Telegram messages.search、Bot API与bot-to-bot边界；Telethon官方sessions/iter_messages与当前Codeberg源；TDLib官方searchChatMessages：选无整群镜像的用户会话搜索，未授权前明确未接通。
3. Healthchecks官方ping/fail和心跳period/grace，与本项目原生回执语义分开。已有演练不重复。
4. SEC官方EDGAR/API Fair Access，Fed RSS、BLS API与限额：用官方数据，403/退避/缓存/无订阅/未核验分别标记，不绕过限制。
5. SQLite backup/VACUUM/foreign_key_check、LEAN live reconciliation：保全来源、冷热分层、恢复验证；不按表名或年龄删除证据。
6. JeffPu/ibkr-dashboard、TrishkaV/PortfolioHelper、promobase/ibkr-web-api、caronc/apprise：预览、持久状态、FYI分类与通道边界。仅参考设计，FYI未接通，Apprise未安装。

仓库URL统一在UPSTREAM_REPOSITORIES.json/.md，证据与更新策略独立记录；GitHub仓库归档不等于项目停止维护，需跟随官方迁移声明。

## 本轮修复实际记录

Gateway不是为了演练下线：GUI卡在Restart in progress/Shutdown API，旧Java进程未更换，日志自00:45 Berlin停止推进；修复前1247FD/963线程/RSS约972MB，低于FD软限70%但线程数量异常，不能声称泄漏根因已修复。现有owner受控启动后新Java代际1378654，02:20常驻fresh四end与独立READBACK_COMPLETE通过。API预算按既有代际变化与稳定60秒完整回读规则恢复，不是人工重置；旧3/3交易试验和全局门禁哈希一致。native恢复983（群message157）、API恢复982等均TELEGRAM_ACCEPTED。

02:20:43准备了当日日报，源快照02:20:22，现有补报986成功；原980缺报告警保留。资源和gate哈希前后证据：云runtime/gateway-recovery/20261108T011830Z。自动化本身尚不能处理这类卡住shutdown；本轮实际修复成功不等于已验证无人值守恢复所有卡死场景。

Nov8 02:25新增真实数据：连接恢复后的IBKR新闻读取均完成身份核验，META与NVDA返回可用新闻；其余公司本次无可用新闻不能推断无订阅，实时新闻流仍未验证。一次只读USD ledger确认余额-69788.66；发现base EUR现金行仍缺，因此增加显式base ledger读取。T0草案已写runtime/performance-start-proposal.json（approved=false/performance_t0=null），没有重设统计起点。工作/通知检索上线只读探针各返回2条，明确不冒充Telegram全群历史。
