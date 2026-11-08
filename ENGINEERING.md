# 工程主文件

本文件统一工程纲领、核心要点、运行约束与验收状态。PRODUCTION.md 是当前生产停写与启动门禁的操作事实来源；历史证据按原路径保留。

## 2026-11-06 下午接续：云端Paper闭环与日志核对

- VS Code已展示云Gateway原始UTC+柏林时间线：昨晚23:27:21初始化、00:45:26软重启、今晨08:01:35初始化。08:01是systemd stop/start，触发者尚未归因；不是本轮为检查而重启。
- 16:29UTC一次性报价检查再次10197，账户回读仍完整；用户确认退出Live后，16:32UTC实时报价恢复，不能由此推定其他设备身份或精确释放机制。
- **真实Paper三笔闭环通过**：撤单perm756941084；买入NVDA1@188.72/exec0000dc8f.6c030a11.01.01；平测试仓1@188.66/exec0000dc8f.6c030a31.01.01。16:33:40UTC独立回读原6持仓与PFE保护单不变、NVDA0/测试挂单0/UNKNOWN订单0/全球门禁哈希不变。预算3/3耗尽并关闭scope，自动策略未启用。详见docs/production-audit/PAPER_ACCEPTANCE_20261106.md。
- 新发现：旧NOTIFICATION_CHANNEL_TEST事件仍生成持续提醒，需阻止生成新提醒并保留原发送账本；一次性验收连接的10197应接入既有SymbolRecovery冲突账本，与常驻监测共用身份，不另外直发或伪造恢复。

## 每日开发进展

### 2026-11-05～06（柏林时间，云端）

- 用户确认下次优先级：先完成有限Paper下单、成交、撤单与平测试仓的真实闭环验收，再推进自动运行。连接中断与行情竞争（10197）须作为两个独立故障分别发Telegram告警，并分别凭真实恢复证据通知恢复；不以API重连成功代表行情恢复。

- 接入并加固QuantConnect IBAutomater：自动登录、软重启、单实例与私密凭证；真实恢复已留日志。
- 建立Paper账户期初基线与持仓/挂单追踪，保留原PFE保护单和历史证据。
- 10197竞争会话：已接入检测、告警和有界行情重订阅；API断线另走自动重连，不用重启强抢Live行情。无法枚举其他设备的新登录会话。
- 11月5日23:27左右自动登录成功，但10197当时仍在；11月6日00:19:44新鲜实时行情恢复。登录恢复与行情恢复是两项证据，具体竞争限制释放机制未知。
- Telegram已替代Brevo作为日报、故障、恢复及提醒的统一主通道；真实PNG报告获message_id2回执，故障链路尚未专门触发实测。
- 最后完整离线786项通过，secret scan通过，功能代码已Git同步并云部署b3e4eac。
- 未完成：正式Flex适配、09:00真实调度/故障恢复验收、健康通道依赖收口、有限Paper下单成交撤单闭环；自动交易仍关闭，本轮零试单。接续见HANDOFF_20261106_TELEGRAM_PAPER.md。

## 2026-11-05 IBAutomater直接集成与软重启验收

- 用户明确授权采用QuantConnect/IBAutomater并持久保存IBKR凭证。固定上游5751a0a9baef74a47515b8ce96a39308563d11d4，源码/许可证位于ops/ibautomater/upstream；复用上游C#进程/重启状态机和Java Agent Swing登录/IB Key流程，没有重写登录协议。
- 本地适配：复用现有DISPLAY=:99及Xauthority；去掉全局pkill java/Xvfb及替换桌面的脚本；Stop只结束其拥有的进程树且有超时；保留Read-Only API与订单警告原设置；明确当前安装路径；修正2FA定时执行器退出；凭证与agent配置私有0600。源码目录/runtime参数不携带密码。
- 凭证通过仅本机录入页录入，云端~/.config/openclaw/ibautomater-credentials.json为0600、Paper限定；临时录入服务在保存/转存后关闭。秘密未进入Git、聊天或控制器阶段日志。首次和周期性IB Key确认仍由用户完成，不绕过认证。
- 首次上线遇JavaNotFound：安装器.installer记录仍指向已消失的/tmp安装目录。增加优先检测/home/ibkr/Jts/jre/bin/java后，编译与752项完整离线suite通过，gitleaks通过。Java Agent采用Java11目标编译，C#为.NET10；云端仅安装官方Ubuntu .NET10运行时。
- 单一原ibkr-gateway.service经drop-in运行ops/cloud/gateway_automater.py；批准身份、release文件哈希与kernel实例锁均先校验。原Gateway配置已备份于state/deployment-evidence/ibautomater-20261105/before/。构建发布制品/opt/openclaw/ibautomater/releases/62c08a2，源码提交62c08a2ef7b387ca0e9bd8a230841f9da6927f26，发布批准runtime/gateway-automater-deployment.json。
- 09:47:09 UTC自动登录/配置初始化成功，4002恢复；09:47:53券商期初基线回读匹配。不是以进程存在替代认证成功。
- 原生软重启受控验收：2026-11-05T09:48:43.342244Z仅触发一次restart watcher，Gateway界面设置09:50 UTC；09:50:21.659684Z控制器发出SOFT_RESTART_COMPLETED，服务MainPID715454未变、NRestarts=0。09:50:45.452993Z当前基线匹配（6持仓、PFE系统保护单permId911411084保留，未修改），09:50:47.004451Z NVDA/AMZN/TSLA均data_type1且买卖报价恢复；探测连接和订阅已关闭。order_requests仍0。本次无需人工重新输入凭证。
- 证据runtime/gateway-softrestart-acceptance-20261105.json为VERIFIED。一次受控软重启通过，不等于真实跨日/周认证/手机竞争会话全部验收。手机完整交易会话仍可能竞争；未知订单结果不自动重放，PAUSED/MAINTENANCE及交易门禁保持。

## 2026-11-05 当前追踪基线与交付实况

- 用户授权从今天的券商实际账户/持仓/挂单建立期初基线，不要求恢复全部历史交易；旧本地记录退出当前视图但保留归档、备份与来源，不自动重放。已有持仓不生成虚构买入成交，历史盈亏缺失不补零。
- 云端首次期初快照：2026-11-04T23:19:33.148510Z，即2026-11-05 00:19:33 Europe/Berlin；PAPER DUQ503649，6个持仓、1张PFE保护单（permId911411084）。持久化回读CURRENT_BASELINE_MATCHED；PFE has_active_order=1，SYSTEM_OWNED且may_modify=false。当前事实匹配不授予交易权限。
- 期初快照永久保留于trading_audit.sqlite3的paper_readback_baselines；后续观测在paper_readback_observations、持仓当前视图在current_broker_positions，现有broker_orders保存订单事实；运行摘要runtime/broker-baseline.latest.json。首写前SQLite在线备份在state/baseline-backups/before-1a5edf201a17328f9dc55f0bc6ab1c0c866879abd130e23c68036ab69a36a244.sqlite3。109条旧请求仍在legacy_epoch_order_requests，未删除或重放。
- 若先前活动单从完整快照消失，仅记录缺失与待对账，不猜测撤单/成交；既有PFE保护单未取消。新订单验收须关联独立run、账户、合约、orderRef/orderId/permId/execId；发起、ACK、成交、撤单、落库时间分别保存，缺失明确标记。这是后续订单入口的验收契约，尚未宣称全部实现。
- Brevo已成为唯一云通知所有者：ibkr-notifications.service，runtime/BREVO_ALERTS_ARMED；旧EMAIL_ALERTS_ARMED与FEISHU_ALERTS_ARMED均撤下留证，避免嵌入旧邮件worker抢锁。原白底HTML→PNG邮件附件通道已部署，财务准备timer启用；09:00真实调度待观察。通知742的一封当前日报PNG取得SMTP_ACCEPTED，发起到确认约1.99秒，邮箱实收尚未查到，不重发。
- Chrome首次受256MB服务上限被OOM终止，未发出报表；确认无残留且主机可用约2.7GB后设512MB soft/768MB hard预算，后续渲染PREPARED。单实例、15秒渲染超时与子进程清理保留。
- Gateway系统服务Restart=always、jts.ini AutoRestart=1，PID651719保留；系统进程重拉有日志，原生每日免登录/跨日连续性仍未验收。
- 订单验收尚未发单；最新PFE/BAC/KO均REALTIME_STALE，常规交易时段外且有效实时bid/ask缺失。不能以期初对账通过替代行情、运行身份、测试范围、风控/订单闭环验收。
- 本批完整离线748项通过，gitleaks通过。外部独立心跳的未提交代码保留，未混入本批部署。

## 当前交付状态（2026-11-04）

- 已确认设计不等于已实现；已实现不等于已部署；已部署不等于真实验收。
- 本轮改动仅监测/报告，不授予交易权限，不删除历史证据。
- 长跑、周度认证与手机离线同步必须真实验证，禁止用模拟通过替代。

本轮已实现：持久分阶段提醒、上线一次当前故障摘要、实际发起/接口确认时间证据、仅明确未发送的3次DNS预检尝试、预计周度认证24小时/1小时提醒、09:00合并报告队列、当天一次补报、白底模板只读准备器。完整离线检查737项通过。云端部署与群内实收单独记录；生产数据库仍未发布，历史收益/成交覆盖缺失不得宣称完整。

验收证据：本次聊天工具记录和本机 `~/.codex/visualizations/2026/11/04/01a1a81f-ed8b-7e40-9266-2f5a0f899237/`。Gateway UI仍呈登录页而API已监听，未证实原生自动重启已启用；配置文件AutoRestart=1不能替代实际设置与跨日验收。Healthchecks现为邮件、5分钟周期/5分钟宽限；其Webhook超时自动重试与严格UNKNOWN不重放冲突，且当前飞书机器人启用签名，外部直连未部署。

### 2026-11-04 云端实际验收

- 固定 `/opt/openclaw/app` 已通过 Git 更新到 `fcfc982`；唯一飞书worker已启动；Gateway PID保持651719，交易PAUSED/MAINTENANCE保留。备份与部署身份位于云端 `~/.local/state/openclaw/deployment-evidence/cloud-monitoring-20261104-reviewed/`。
- 新通知已实际取得FEISHU_ACCEPTED，抽查发送至成功回执约1–1.5秒；不等于手机实收或服务端消息创建时间验收。
- 首次启用错误地给多个旧未关闭故障各发一条最新阶段提醒；这些发送记录保留。已补安装阶段基线与回归测试，禁止再次集中补旧提醒；修正完整离线738项通过。
- 云端原模板图片生成成功；飞书应用取token返回21001，图片上传未通过，报表准备/发送任务尚未armed。原有文字告警通道不受影响。
- 独立转发器已获用户选择；外部部署位置待明确，现有邮件兜底保留。不允许把同一Hetzner主机上的转发当作独立监控。
- Gateway原生自动重启、跨日免登录、手机离线后时间显示与09:00真实调度均未完成验收。不得标为全部交付。

# 云端监测与报告工程纲领（2026-11-04）

状态：用户确认的要求；实现与真实验收尚未完成。本文不解除 PAUSED / MAINTENANCE，不授权订单或重放历史发送。

## 连续运行

正常条件下，周内不需要每天手动登录 Gateway；周度认证提前告警。使用 IBKR 原生 Daily Auto Restart，遵守周度认证与会话限制，不保存或绕过二次认证。配置成功不代表连续运行验收成功，必须观察跨日重启、账户回读、行情、监测与通知连续性。额外客户端登录、断网、进程异常和认证请求单独记为事件。

## 重点检查目录

1. 云服务器：外部独立心跳、失联、磁盘与资源；不依赖 Mac、Codex 或远程桌面。
2. Gateway：进程、认证、API、正确 Paper 账户回读与行情分别判定。
3. 日报/周报/月报：沿用既有白底分格模板；期间、数据来源、截至时间、完整性、生成、计划发送、实际发送与确认均可追溯。缺报/过期需告警，缺失不补零。
4. 飞书链路：发送者健康、队列年龄、明确接受、明确未发送和结果未知；外部监控不得经过故障主机才能告警。

飞书仅发送告警和日报/周报/月报。开发进度、测试方法和执行说明在聊天中提供。

## 时间证据

保存 UTC 时间与明确显示时区，分别记录 scheduled_at、observed_at、queued_at、attempt_started_at、ack_received_at；有可信消息查询能力时另存 provider_message_id 与 provider_created_at。ack_received_at 是本机收到成功回执的时间，不是服务端创建时间，不是手机收到或用户阅读时间。手机离线后的同步不得改写原事件/发送时间。消息正文提供原始发生与发送时间供对照，客户端时间显示需真实离线手机测试。

正常网络条件下，故障发生到飞书确认目标 <=60秒；约定报告时刻到确认目标 <=60秒。外部主机心跳目标每60秒、失联告警目标 <=120秒，须包含服务商宽限期和检测相位验收，现有5分钟配置不满足。尚未获得服务端消息时间时不得宣称已完成服务端时间戳验收。时间同步失效必须标注，不隐藏负延迟。报告发送时区与日/周/月精确计划尚待核对旧约定。

## 去重、提醒与有限重试

每个故障发生实例有独立身份；首次、30分钟、2小时、24小时提醒，之后每24小时一次，按首次发现绝对时间计。每阶段只生成一条持久通知；恢复关闭该实例。断网跨过多个阶段只生成一次最新状态摘要，保留历史经过，不逐条补发。持续提醒是新阶段事件，不是重复发送旧消息。

发送前持久预留 STARTED；HTTP成功且业务成功才标为 FEISHU_ACCEPTED，永不自动重发。手机离线/未读不是重发理由。请求可能已到达服务端但超时、回执丢失、无效回执、发送后落库失败均为 UNKNOWN，重启后保留并要求对账，不自动重放。仅在证据证明请求未发出且依赖重新验证后才允许有限重试；最多尝试3次，按首次尝试起算0秒、15秒、45秒，次数与截止时间持久化，重启不重置。耗尽后停止本通知自动尝试，保留失败与后续摘要关联。明确永久拒绝停止，不能循环重试。发送者互斥锁、持久唯一键和事务保护避免并发重复；不以 BUY/SELL 拼接改变业务身份。

## 已确认与待决

已确认：本文件连续运行目标、三层与发送链路监测、分钟级目标、时间戳区分、飞书内容范围、30分钟/2小时/24小时/此后每天提醒、断网单次摘要、最多3次有限尝试。

2026-11-04 第二轮确认：日报每天、周报每周一、月报每月1日均为北京时间09:00；同日重叠合并一条通知，各报告的期间与数据完整性独立保留。先落实现有通道本地发送/成功回执时间与正文原始时间，服务端查询能力另行评估，缺失明确标注。周度认证预计到期前24小时、1小时各提醒一次，实际要求认证立即告警；无法可靠推定到期时刻时标为预计，不伪造确切到期时间。

2026-11-04 第三轮确认：09:00准时发送已有报告，明确列出缺失报告及原因；缺失报告当日恢复后只补发一次，注明原计划时间、实际补发时间和延迟，过日不自动补旧报告。上线时发送一次新生成的当前未解决故障摘要，不重放旧邮件或历史消息。初始通知和补报使用各自稳定身份，发送不确定时不得借补报身份重复发送。

待决/待事实核查：外部服务实际飞书通知集成和检测阈值；周度认证预计时刻的可靠来源；合并报表中数据期间与缺失标注的预览验收。不得默认扩大权限或宣称验收通过。

## 执行与验收

每项大测试前在聊天说明运行主机、代码路径/提交、方法、预期、影响、证据路径；执行中持续汇报。离线测试只在 linked worktree 使用 scripts/run_worktree_tests.py，不连接生产数据库。云端仅执行已说明的只读/受控验收。每项记录实现、部署、验收三种状态，禁止把接口接受当手机送达。断网、主机丢失、发送者停止、重启恢复、UNKNOWN、重复实例、缺报和跨时区都需要覆盖。

参考：IBKR General Third Party FAQ；飞书自定义机器人使用指南。现有 webhook 成功响应 data={}，不包含服务端消息时间，需独立验证能力。


## 既有系统核心与历史实施记录

# Paper 系统框架与业务通知实施计划

2026-11-04 用户确认补充纲领已合并到本文件前半部分。下文保留历史实施记录，其中旧 SMTP 状态不能代表当前飞书部署状态。

**Goal:** 复用现有系统，先建立明确的模块、接口和数据所有权，再接通可恢复的业务通知。
**Architecture:** Fast Path 保留身份、风险、意图持久化和幂等。Background Path 负责研究、复盘、通知、统计及常规对账；健康依赖唯一入口为 reporting.health，恢复复用 RecoveryCoordinator。
**Tech Stack:** Python、SQLite、IBKR Paper、systemd、SMTP。
**Spec:** IBKR-Paper-实施进度.md、2026-10-22-ibkr-cloud.md及原总需求附件。

## 边界

仅 Paper；PAUSED/MAINTENANCE保留；不得操作订单、发布交易库或自动启用交易。已有代码不表示生产验收通过。生产状态固定在用户state目录；开发只用linked worktree和隔离测试。

## 模块、接口及唯一所有者

| 模块/路径 | 接口/数据所有权 | 当前状态与下一验收 |
|---|---|---|
| AI研究 candidate_research.py、news_candidate_router.py | CandidateDraft/EvidenceItem → build_candidate_report；研究只产建议，Python audit_candidate 决定硬审核 | IN PROGRESS：已有实现，持续研究与时点数据验收TODO |
| 多来源池 pool_manager.py、pool_state.py | PoolMembership、compute_membership_deltas；来源成员关系与生命周期分离 | IN PROGRESS：来源/理由/分数已有；source_version、规则版本、有效起止、available_at统一契约TODO |
| 证券身份 security_master.py | 统一证券实体；同证券多来源不产生多执行身份 | IN PROGRESS：symbol到conId/市场/币种精确匹配及冲突测试待验收 |
| 策略 strategy.py、order_intents.py | 策略输出意图；route_synchronized_intents归并冲突 | IN PROGRESS：禁止来源池各自独立下单；跨来源防重待联合验收 |
| 风控 risk.py、position_protection.py | 现有风控唯一授权；组合敞口含持仓、活动挂单、未确认请求及外部订单 | IN PROGRESS：UNKNOWN/保护异常不得靠通知恢复；当前敞口与保护验收TODO |
| 订单 audit_writer.py、order_intent_router.py | 本地意图/幂等由现有writer拥有；Broker事实以IBKR为准 | IN PROGRESS：正式数据库未发布；不可将placeOrder返回当成交 |
| 券商 tws_paper.py、ibkr_streaming.py | Paper精确身份、回调/订单/成交/持仓同步 | IN PROGRESS：只读快照通过不代表持续连接；恢复后必须重新同步对账 |
| 健康 reporting/health.py、recovery.py | registry/resolver唯一依赖图；observations/events/jobs/operation_attempts由coordinator拥有 | DONE代码基础；生产持久化及恢复长跑TODO；不新增交易门禁 |
| 故障 reporting/incidents.py | 仅拥有incidents/event去重/通知outbox；不写交易状态 | IN PROGRESS本批基础；真实来源采集和SMTP接线TODO |
| 邮件 ops/cloud/alert_email.py | 独立worker唯一SMTP发送者；固定收件人；STARTED/UNKNOWN不得自动重放 | IN PROGRESS：实收通道通过，完整队列接线未启用 |
| 监督 ops/cloud/host_status.py、collect_paper_evidence.py、healthchecks_sender.py | 本地状态、Paper快照、独立外部心跳 | DONE基础部署与DOWN/UP实收；192小时及认证边界TODO |
| 备份/对账 | IBKR事实、本地意图及历史隔离证据分别保留；正式库单一写入路径 | TODO正式DB备份恢复；当前仅调度通过 |
| 性能/回放/审计优化 | 后台报告拥有采样，不改生产参数 | TODO阶段耗时/队列/慢失败样本，代码模型提示规则数据版本；回放仅使用当时available_at之前信息，保留退市样本、费用滑点 |

Fast Path依赖：行情新鲜度 → 策略 → 精确账户/敞口/幂等风控 → 持久意图 → adapter → ACK/成交事实持久化。Background研究输出必须经过Python硬审核；邮件异常不阻塞订单主路径，但必要风险证据不可省略。

## 第一批：框架与持久通知原语

- [x] 新建 reporting/incidents.py，使用同一recovery.sqlite3中的独立表，不改变coordinator已有表。
- [x] ingest(event_id, incident_key, payload, resolved=False)：event_id是发生身份，incident_key是归并身份，JSON指纹不能替代发生身份。一个事务提交事件、故障与通知；重复事件无新增通知；恢复需要显式证据。
- [x] claim/finish：原子PENDING→STARTED；崩溃后STARTED保留人工核对；UNKNOWN不重放；SMTP_ACCEPTED只表示relay接受。
- [x] 离线测试重复、并发claim、重启、恢复/再发生及回滚；完整suite、secret scan、Git整合、生产只读smoke。

## 后续批次：真实事件与发送器

1. 后台采集拒单history.jsonl和coordinator事件，先建立当前末尾水位，禁止历史重放；水位与incident事务提交；处理轮转/截断，输入失败不推进水位。UNKNOWN/保护异常必须携带真实来源身份和作用域，不从自由文本推测恢复。
2. 新鲜cloud-status/完整Paper证据提供服务及认证异常；inactive且disabled的交易服务为预期暂停，不误报崩溃。过期或缺失不是恢复。单笔拒单YELLOW/ORDER；保护或UNKNOWN为RED并交由既有风险门禁判定范围。
3. SMTP发送器消费outbox，Berlin时间、严重度、标的/订单类型/错误码、范围、已采取行动、交易权限、用户操作、恢复条件；用现有operation_attempts防止不确定重放，确认无收件人拒绝才标relay接受。恢复邮件不得越过未决ALERT。启用前隔离故障测试，不重复通道测试。

## Review Focus

- 同一证券多池不能重复消耗组合额度。
- 相同内容的不同发生事件不可吞掉；迟到事件不可重新打开已恢复故障。
- 收集器首次启动/日志轮转不发送历史告警。
- SMTP接受后进程崩溃必须保留不确定状态，不能自动重发。
- 数据缺失、stale、网络恢复均不能推导交易已安全或自动恢复权限。


## 2026-10-23 第二批实施记录（生产发送关闭）

- [x] 修复隔离环境，基础525项完整测试通过；96773d8已Git整合。
- [x] 接入保护报告、Paper认证/身份/连接及服务状态；以明确证据区分故障、停用、缺失、过期和恢复。
- [x] outbox接入现有SMTP worker和coordinator delivery操作身份；Berlin正文、升级通知、恢复顺序、STARTED/UNKNOWN不重发；默认不armed。
- [x] 最终完整离线套件544项通过；秘密扫描及Git整合以本批提交记录为准。本批不部署云端、不启用生产邮件；轮转接续及缺账户/复杂保护的人工对账仍独立待验收。

## 第三批：日志安全接续与影子故障验收

**Files:** reporting/journal_rotation.py持有文件锁/归档/轮转凭证；incident_sources._journal保持原有SQLite事务和事件身份；三个现有业务报告writer改用append_jsonl；shadow_incident_acceptance.py只写monitoring-tests并使用进程内模拟SMTP。

- [x] append_jsonl(path,payload,max_bytes=100MiB)与rotate_journal(path)使用同一kernel文件锁；rename保留旧inode，凭证记录旧/新inode、原文件size和SHA256，归档不按年龄删除。
- [x] collector先读完旧段，再从新段零偏移接续；限额可跨重启保存，事件身份仍由源/段inode/字节偏移组成，不能用内容hash吞掉独立发生。
- [x] 首次已有日志仅baseline；首次缺失之后的新段全部接续；无凭证copytruncate、损坏/缺失归档、部分行及未完成轮转intent一律保留证据并停止该源，不猜测历史。
- [x] 离线覆盖多次轮转、并发producer、半行、哈希篡改、缺段、重启和事务回滚；隔离故障脚本覆盖轮转接续、保护恢复、身份症状及模拟SMTP不确定结果。
- [ ] 完整suite及秘密扫描通过后Git整合/部署；云端只跑smoke、隔离故障影子及额外10分钟只读观察，不启用正式采集、邮件或交易。

## 第四批（2026-10-25）：显式中断恢复、日志证据备份、隔离恢复验收

**Spec:** 本聊天2026-10-25用户指令；保持Paper、PAUSED/MAINTENANCE、交易/SMTP关闭。
**Architecture:** 复用journal锁及现有轮转凭证。恢复只处理已持久pending的可证明阶段，先inspect生成内容/身份绑定token，再显式apply；不改SQLite水位。备份增加日志证据项，恢复只落隔离候选并保留原元数据和inode映射，不发布生产库。

- [x] reporting/journal_recovery.py：inspect_rotation(path)->plan，recover_rotation(path,token)->result；验证pending、归档hash/inode、空新文件及receipt连续性；拒绝数据不符、过期token；保留恢复前证据，提交后重试不重复轮转。
- [x] reporting/journal_backup.py：backup_journal(path,target)、inspect_backup(target)、restore_journal(backup,target,token)；有界复制、逐文件SHA256、拒绝路径逃逸/符号链接、目标必须全新；原元数据保留，候选中显式映射inode；不自动改生产cursor。ops/cloud/backup_state.py对三个既有日志源接线，无源时明确MISSING。
- [x] ops/cloud/journal_admin.py：inspect/recover/restore入口，生产recover需PAUSED/MAINTENANCE和token；restore限monitoring-tests。隔离验收覆盖各中断阶段、恢复中再次崩溃、篡改/缺段拒绝、备份还原、未读尾部及重复事件不重放；shadow_journal_acceptance只操作合成数据并硬禁网络。

Review focus：pending前后inode身份不猜测；新文件已有内容不能吞掉；备份不能伪造完整性；还原不能复用旧inode当当前事实；复制失败不留下可误认为完成的备份manifest。

2026-10-27续接：保留上次中断的改动，完成journal_admin显式入口及shadow_journal_acceptance隔离诊断；源档恢复不修改SQLite cursor，备份restore只生成候选，生产水位/灾备切换仍单独验收。使用既有专用.venv和完整离线runner，通过后才Git整合部署；不启用生产交易/采集/邮件。

验证：最终完整离线suite 573项/61.574秒/OK，FD回归5、连接恢复压力循环FD4且线程1。gitleaks staged扫描通过；Git整合、云端部署及隔离验收结果持续记录于finance/IBKR-Paper-实施进度.md，不以离线测试替代生产验收。

## 2026-11-05 11:25 Europe/Berlin — actual news and Paper checkpoint

Integrated pinned ib_async2.1.0 read-only news adapter with explicit Paper identity and lifecycle ownership. Removed legacy connection=>news entitlement inference; disabled default fixtures and tagged explicit fixture payloads. Added independent NEWS health dependency and persisted evidence. Full isolated suite762 PASS; secret scan PASS. Actual corrected cloud run10:24:15Z: eight providers, five Dow Jones sources with in-window titles + body hashes, Briefing old results excluded, DJNL empty not denied. Generic upstream datetime formatting differed from news spec; dashed start-only request + defensive return-window validation added. No new paid subscription or recurring collector installed. Details: docs/production-audit/NEWS_ACCEPTANCE.md.

10:25:00Z Paper preparation readback complete: six positions, existing PFE protective order retained, zero executions/order_requests. NVDA/AMZN/TSLA now all return10197 with absent bid/ask: current competing Live market-data session, unlike the earlier conflict-free sample. No orders/cancels sent; news access does not remove quote/risk/execution gates. Test sequence and remaining executor/reservation blockers: docs/production-audit/PAPER_TEST_PREPARATION_20261105.md. Existing unrelated heartbeat work remains outside these commits.

11:27 Berlin: user confirmed Live logout; immediate new Paper read still10197/noquotes. Recovery is not certified. Native4002 wildcard socket is protected by active default-deny UFW (onlySSHallowed); no portchange/restart. Code published to codex/cloud-paper-automation-20261105; source/tests762PASS and originalPFEorder untouched.

## 2026-11-05 23:30 Europe/Berlin — connection recovery distinguished from market recovery

Completed linked-worktree766 offline tests and secret scan, Git-integrateda410b19 and deployed bounded session recovery fixes. Explicit162 different-IP HMDS conflicts now use10197 policy; secondary historical errors cannot silence active quote recovery; atomic legacy adoption preserves budgets/evidence. Gateway generation follows ownedJava rather than persistentcontroller. SQLite/manifests backed up under runtime/session-recovery/20261105T222526Z; unrelated heartbeat work untouched.

User selectedQuantConnect path. Officialibapi and realib_async both returned10197. A single separately journaled authorized IBAutomater reauthentication at23:27Berlin auto-logged in~21s, monitor reconnected~42s and passed60s stability validation at23:28:42. No manual2FA was needed in this run; future IBKey requests still require user. New post-login quote requests still10197: API recovery VERIFIED, market recovery NOT VERIFIED. PFE8 protection retained, no orders/cancels, globalexecutionmanifest/PAUSED unchanged. Existing15min retries forBAC/KO were functioning; PFEclassificationstall fixed. Password-entry UI is not evidence of broker market-session logout. Full details and private evidence references: docs/production-audit/IBKR_SESSION_REPOS_20261105.md. Paper execution acceptance remains blocked by real quote denial and unfinished risk/test executor gates; no falseREADY or automaticorderreplay.

## 2026-11-06 00:19:44 Europe/Berlin — scoped real market recovery

Fresh independent PaperDUQ503649 readback at2026-11-05T23:19:44.702838Z was complete. NVDA179.10/179.18, AMZN253.88/254.66, TSLA335.50/335.60 all actualtype1 with callback receipt within~0.2s; no10197 in this request. Worker/reader stopped, three subscriptions cancelled, socket closed, threads1/fds5. Evidence private observations/current-session-20261105T231945Z.json. This proves scoped real quote availability at the observation time, not a fabricated recovery from API login alone.

Cause: broker competing-session restriction no longer applied to these new requests. Exact release mechanism/time is UNKNOWN: password-entry mobileUI did not prove logout; no server session inventory is exposed. Earlier one-time QuantConnect reauthentication23:27Berlin did NOT immediately restore quotes. No restart was performed in this successful observation. Do not attribute delayed broker release to a specific code patch or claim continuous absence of10197 between samples. Subscription record remains NetworkA/CTA L1, NetworkB L1 and NetworkC/UTP L1; RTH-only K-line query parameters are separate from these entitlements.

User now explicitly requests actual submit/fill/cancel Paper acceptance. Filled orders cannot be cancelled, so finite acceptance uses distinct single-share cancel/fill orders plus optional test-lot close. Independent scoped experiment only: NVDA, one share, limit<=USD200, max3 submissions, fresh real quotes, broker contract session/minTick, existing exposure/availableUSDcash, exact account, immutable intent before wire, no replay of STARTED/UNKNOWN, no originalPFE cancellation. GlobalstrategyPAUSED/production.json retained. Implementation and actual outcomes follow after offline suite and real preflight.

## 2026-11-06 — upstream registry and Telegram setup checkpoint

User clarified the requested integration concerns the whole project, not only currencies. Actual upstream integration/patch status is now maintained in REPOSITORIES.md (IBAutomater, LEAN brokerage, ib_async, Canary, ibflex, python-telegram-bot, IBC and official IBKR interfaces). Canary/LEAN full engines remain design references, not silently installed runtime components. User approved official Flex financial-report adaptation; parser/downloader/account-period verification remains separate from current live API evidence.

User approved creation/private local+cloud token storage for @deehub_paper_reports_bot. Native BotFather creation succeeded; token saved in ignored0600 config, getMe verified correct Bot. User created actual group named der (superseding proposed deehub); readonlyAPI verified exact chat, bot membership, single owner and total2members. No test message sent. Report-only transport uses pinned python-telegram-bot22.8 and existing outbox/schedule/PNG; operational alerts remain Brevo. Native server receipts and UNKNOWN non-replay are required before delivery is certified.

Paper acceptance preflight has sent zero orders. Real USD ledger returned$LEDGER-prefixed tags and a negativeUSD balance; base account values areEUR. New currency adapter preserves liabilities and broker USD-to-base rate, does not assume zero/missing balances or1:1FX. Any limited Paper financing remains explicitly scoped; no global trading permission changes.

## 2026-11-06 接续核对：Telegram统一主通道（部署前）
- 用户再次要求故障/恢复和日报全部迁至Telegram并尽快自动运行。现云端是自动只读监测+Brevo通知，不是自动交易。未解除PAUSED/MAINTENANCE，未发送验收订单。
- 逐项迁移计划见docs/superpowers/plans/2026-11-06-telegram-reports.md。已核对历史精确时刻：每天/周一/每月1日09:00 Asia/Shanghai，正常网络确认目标60秒；缺报同日一次补报、过日不补；故障首次/30分钟/2小时/24小时/每天，离线只汇总最新阶段。
- 实现Telegram所有通知类型、无图片缺报文本、原PNG附件及原生message_id/server_date回执；保留统一outbox身份。新增TELEGRAM_ALERTS_ARMED主通道，Brevo配置/旧arm可保留为休眠备用，无自动fallback/双发，UNKNOWN不重试。
- 云只读检查：e28b33f，ibkr-notifications active；发送账本18 FEISHU_ACCEPTED+769 SMTP_ACCEPTED，PENDING/STARTED/UNKNOWN均0。尚未部署Telegram、尚无Telegram真实发送，不以本地785项通过替代云验收。
- 官方Flex说明确认固定ndcdyn SendRequest/GetStatement并忽略响应URL；来源https://www.interactivebrokers.com/docs/web-api/flex-web-service/using-flex-web-service/generate-the-report 。正式Flex适配仍待完成。
- Telegram真实报告验收：云端629cd36，outbox788→TELEGRAM_ACCEPTED，群-5461963901原生message_id2、server_date2026-11-06T00:05:45Z（Berlin01:05:45），发起到ACK约0.34s；不是已读证明。TELEGRAM_ALERTS_ARMED/REPORTS_ARMED启用，Brevo arm备份后撤下，单一既有worker运行。正式Flex仍缺失。
- Paper preflight没有提交订单。查明ib_async默认$LEDGER:ALL只返回基准summary；显式$LEDGER:USD真实返回美元-69786.59和EUR/USD汇率0.8901638。新增有界单请求、end marker后cancel的资金读取，不将缺失当0。scope仍同一ID/预算/到期时间，仅Git部署身份和已授权有限Paper融资政策同步，全球门禁哈希不变。

## 2026-11-06 夜间暂停新验收，等待用户早上接续
用户要求收口记录，暂不继续Paper试单。交接详见docs/production-audit/HANDOFF_20261106_TELEGRAM_PAPER.md。最后云功能代码b3e4eac、通知服务active/NRestarts0、TELEGRAM_ACCEPTED报告788/message2、UNKNOWN通知0、Paper尝试0、全局门禁哈希不变。786项完整离线通过和stage后secret scan均通过。显式USD读取修复已部署，部署后preflight未做；正式Flex、真实09:00/故障恢复发送验收、公共DELIVERY通道依赖、有限Paper闭环和正式自动策略仍待接续，不能标成全部完成。现有自动只读监测/Telegram通知保持运行；没有安排定时唤醒。
- 本轮核对到真实调度/连接故障Telegram证据：09:00Asia/Shanghai日报outbox789/message3/server01:00:05Z，计划至本地ACK约5.78秒；API_CONNECTION_CLOSED outbox795/message9/server07:01:05Z，恢复outbox797/message11/server07:01:50Z。只验证调度/发送与回读恢复，不把API快照报表称作Flex正式报表；10197真实发送闭环仍不宣称已验收。
- 本轮修复：一次性验收连接的10197进入既有SymbolRecovery持久冲突身份；恢复仍要求多次独立新鲜报价与完整对账。旧NOTIFICATION_CHANNEL_TEST不再生成新周期提醒，原账本不改。完整离线787项通过；部署后不重开已用尽的Paper测试scope。

## 2026-11-06 可见时间线与自动运行门禁收口
- 用户要求看清今天何时暂停、何时恢复、Telegram是否确认；新增只读inspect_runtime_timeline导出，将全局门禁、通知原生回执与暂停条件聚合分开。文件mtime不冒充暂停起点，重复条件变化不冒充真实停机次数，UNKNOWN不当成功。
- 确认08:01:03 API断开事件→08:01:05Telegram message9；08:01:44完整账户回读恢复→08:01:50Telegram message11。00:45Gateway软重启与全局策略PAUSED分别展示，08:01stop/start触发者仍未知；截图tail是重复打印，不是重复重启。
- 公共health registry/resolver及恢复协调器按持久主通道选择依赖；Telegram不再被休眠Feishu故障连带阻塞，SMTP备用保持独立。配置路由不提升健康、不授予交易权限；Telegram/SMTP账本读取共享outbox而非旧delivery.json，未确认操作继续保持。
- 791项完整离线通过；本轮不下单、不发测试消息、不解除PAUSED/MAINTENANCE。真实Paper三笔已于前轮验收完成且scope关闭，不重复。
- 自动策略尚被明确事实阻塞：production.json ready=false/SAFE_MONITOR_ONLY，canonical_current_state_verified=false，控制/风控/权威状态/隔离风险与策略依赖尚未获批准。门禁输出中的Duplicate/uncertain默认拒绝项不等于发现了新UNKNOWN订单；上轮已独立查明UNKNOWN订单0。
- 用户偏好此项目后续以VS Code Codex扩展为开发入口，已记AGENTS.md。当前桌面聊天没有因展示终端而迁入IDE；生产systemd单owner仍在云端，开发/全套测试仍限既有linked worktree。官方IDE依据https://learn.chatgpt.com/docs/codex/ide 。
- 新发现并修复平仓后保护故障未闭环：NVDA真实回读为0、无挂单，但paper-safety:protection:NVDA仍OPEN。仅在_complete新鲜账户+全部end markers+非dirty且零持仓/无任何非终态挂单时生成NO_EXPOSURE恢复；不靠scope到期/文件名清理。新持仓仍产生新故障实例；保留全部历史账本。
- 平仓恢复回归还验证了同一时刻再次出现相同故障：使用持久transition sequence区分新事件，不能用相同内容指纹吞掉新故障。793项完整离线通过；计划仅重载现有只读监测/通知owner应用修复，不重启Gateway、不重开已耗尽Paper scope。
- 云实际验收补记：2e85fd3已部署，Gateway PID827485不变；仅只读监测/通知owner受控重载。18:00:31柏林API客户端断开→Telegram21/22；18:00:40完整回读/PFE保护恢复→23/24；同一新鲜完整回读关闭NVDA零敞口旧故障，18:00:54Telegram message25/outbox811接受。测试仓17:33已平，旧故障记录持续到18:00不代表持仓未平27分钟。UNKNOWN通知0，全球门禁hash和已关闭scope不变。最后793项离线通过、gitleaks通过。
- 今日可读对照和原始回执保存在本机.codex/visualizations/2026/11/05/01a1ae27-a046-7772-a9c8-5554aa4dfc85/gateway-review/2026-11-06-通知与暂停核验.md、today-runtime-final.json。00:45故障当时仍SMTP接受，不冒充Telegram；17:29–17:30独立probe的10197未匹配到Telegram原生回执，仍明确发送验收缺口。

## 2026-11-06 日志证据与Telegram文案改版
- 用户截图中的4455是当时pause_transition条件记录数，不是断线/订单/Telegram次数。后续4557条中3900条来自同一GLOBAL_NEW_ORDERS_PAUSED原因里reconciliation_verified周期切换。停止把同scope仅reason变化记成新PAUSE；最新原因仍存state与新分钟采样，真实进入/解除/恢复及错误仍保留，旧记录不删。
- 昨天柏林日Nov5核对285份约5分钟账户快照：166完整、119不完整，最大采样间隔332.017秒；这些快照没有报价。昨天10197错误回调136条，不能等同136独立事件。audit当前market_session_events/quote_readiness_events/quote_state_events均0条，因此不能声称非断线时段全部Paper行情正常；账户回读成功也不等于行情/策略可用。
- 在既有recovery.sqlite3增加paper_health_samples：每个进程epoch每分钟最多一条API/上游/身份/回读/逐标的行情/门禁快照，保留原始精确时间，缺失历史不补造。每个采样点不是整分钟连续可用率；重启同一分钟可有不同epoch记录。
- Telegram改展示，不改历史身份：字段间空行；人类可读中文类型与保护状态；事件/排队/发起按柏林时间到秒；分数秒仅隐藏、原账本保留；用户操作改建议你操作；实例改故障批次；事件编号最后一行（图片caption预算也保留）；删除固定末句。PROTECTION_PROTECTION_UNKNOWN是保护状态变化通知的历史机器名，不是Python类，不改旧key/去重身份。
- 昨天进一步分组：00:45:16–10:25:59共117次TimeoutError，10:41/10:46另2次TimeoutError；10:47:53后155次账户回读完整。这些是采样点而非精确停机区间，不能推定同期间行情正常。本地已打开昨天证据及805通知新版预览；未向Telegram重发805。完整离线799项通过。
- 部署后独立只读PFE/BAC/KO均取得type1新鲜bid/ask，无10197；常驻监测却UNKNOWN。定位@retry三标的保留旧1100/WAIT_CONNECTION且next_retry=null，冷连接的完整回读恢复没有1101回调，故订阅恢复未继续。新增稳定60秒+正确账户+新鲜完整回读后的connection proof桥接，仅解除旧1100等待；保留耗尽的4次预算、pending不确定订阅与人工审查，低频诊断沿原15分钟策略，不改交易权限。
- 云实际结果：文案/降噪/分钟采样代码671cae4已重载生效，新维护通知812–817获Telegram消息26–31回执；旧805未改写/重发。新增分钟表已真实写入16条（当时），API/上游/身份/回读与逐标的行情分开。
- 3dd3a1a恢复桥接代码已部署；为保留现有行情连接，未再重启worker。以现有连接UUID、稳定>=60s、正确Paper身份、全量fresh回读执行一次有界bridge，PFE/BAC/KO均从旧1100等待转入原低频恢复，fast budgets仍4，常驻owner重新收到三标的type1报价、market_errors空。当前进程881453仍是671启动版本，新冷启动hook在下次正常worker重载加载；不声称热加载或已完成未来冷启动验收。
- 最新样本仍可能REALTIME_STALE，且SESSION_UNKNOWN/交易时段未核验，不能把type1收到报价说成连续新鲜或策略可交易。最终smoke NOT_READY，全球门禁hash及关闭的三笔scope不变，UNKNOWN通知/订单均0。801项离线与gitleaks通过；没有新增试单、换汇、强抢Live或重启Gateway。

## 2026-11-06 四项运行证据与外部心跳核对

- 用户确认四项为会话、行情、API连接、云端监控；quotes/bars/history是行情内部三路，不能代替用户分类。固定滚动窗口柏林Nov5 20:32:37至Nov6 20:32:37，保存云recovery只读导出、systemd及通知账本；4557条暂停条件噪音不当作订单或断线。
- API事件/完整回读成对保存；会话初始化、API回复、行情新鲜分别判定；分钟采样始于Nov6 18:20:53，历史无证据区间UNKNOWN。24h报告、CSV、原始证据和源码研究在本机.codex/visualizations/2026/11/06/01a1b258-c8a7-7703-9689-7d0fb0459f18/market-review，已在VS Code打开。
- 增加runtime_health_samples/events/current：既有安全owner逐回调记录API/会话证据及逐标的行情三流变化，既有host-status timer记录云服务、load/内存/磁盘观测；进程epoch变化不冒充连续健康。inspect_health_window只读滚动报告标出采样缺口，不回填旧历史。
- 增加heartbeat_delivery：发起前STARTED，HTTP200后记录ACK时间/响应码/是否报告健康，超时UNKNOWN且不自动重放该次尝试；不保存秘密ping URL。已云端回读host/API真实HTTP200和多轮约60秒间隔。API心跳读取既有owner的新鲜identity/upstream/server reply/reconciliation，不再用最长10分钟旧快照证明API正常。
- Healthchecks后台原有两条检查均5分钟period+5分钟grace，仅邮件。现云timer已60秒/AccuracySec1秒，平台两条period/grace各60秒已保存核验；目标是最后成功ping约120秒后Down再加调度/传输，不是手机120秒必达。
- 用户指定云外告警只发der群，不绑定私聊。当前新增Telegram user None（私聊）已取消全部检查分配0/2，保留原邮件2/2；der只读核对仍2成员时未发测试。官方机器人普通成员加群、群内/start绑定及真实Down/Up通知尚待完成，不宣称外部Telegram已验收。
- Healthchecks官方源码5b9a198bca9dc959326f6492e460166373530499已在OpenWorkspace只读审阅；默认HTTP传输最多3次尝试且不对本工程暴露Telegram message_id，因此不能声称等价于本工程UNKNOWN不重放账本；社区讨论只作参考。
- 806项完整隔离离线通过及gitleaks通过。功能云部署3734bca；安全owner加载d03d355含connection-proof hook；仅原owner重载，Gateway PID827485未变。部署备份目录权限失败后重载曾被旧manifest拒绝，失败记录保留；批准身份已修正，单owner恢复API/Paper完整回读。PAUSED/MAINTENANCE和已关闭Paper scope不变；当前bars/history仍缺证，不称行情或自动交易已完成。

## 2026-11-06 旧总设计与当前工程文档对齐

- 按用户“直接实现”接续上一轮总设计对照建议，落地文档/总图/术语和README署名，不视为启用全自动交易或修改云通知配置的授权。
- 新增docs/SYSTEM_STATUS_20261106.md：六层业务架构、代码/部署/验收矩阵、canonical六层股票池与七池report-only视图区分、AI复盘边界和分阶段验收标准。ARCHITECTURE.md将旧Mode9/7497图明确保留为历史设计，顶部链接当前状态。
- README明确当前云4002、PAUSED/signal-only、已关闭Paper范围，补上实际使用/参考上游署名与REPOSITORIES固定版本登记链接；替换主目录直接unittest的旧指引。未变更运行逻辑、凭据、数据库、服务或交易许可。

## 2026-11-06 云外心跳与秘书档案

云外心跳失联演练：先安排190秒自动恢复，再停止共用心跳发送器；23:44 Down，23:46 Up，host Down窗口1分17秒。Healthchecks显示Delivered，用户确认der群故障与恢复均收到。未关机、未停止Gateway，不能等同真实主机断电或API断开验收。

新增独立秘书档案模块（尚未激活生产/Telegram聊天），区分用户指示、模型分析、工具结果和系统事件；持久运行预留阻止STARTED/UNKNOWN重放。用户确认der群，并明确不再查找旧OpenClaw；后续使用独立正式OAuth流程。佣金感知过滤仍是roadmap，不能宣称LEAN费用模型已融合。详见docs/AGENT_SECRETARY_AND_COSTS_20261106.md。

第二次Gateway验收：23:50:19下线，90秒自动启动原服务；23:50:23告警，23:54:13 API恢复，23:54:20/22 PFE/BAC行情竞争解除。用户确认API与行情恢复消息都看到。连接恢复包含已有退避，不能宣称下线后立即重连；确认恢复后通知随即排队发送。门禁/持仓不变，未知订单操作0。816离线测试与gitleaks通过；秘书档案模块未激活聊天。

## 2026-11-07 多人群隐私与通知中心

用户计划邀请朋友进入der。现有输入仅owner，但输出人数校验仅适用私人小群。改造为共享群固定运维摘要及用户追加授权的公开日报+已核验owner私聊；不把群成员/管理员当owner。保留唯一Telegram轮询、唯一投递owner与未知结果对账规则。新增类别/来源/本地未读/偏好、预览、展开详情、同事件原消息更新；逻辑职责用标签区分，无额外机器人凭据。

线上只读核查：der机器人隐私模式开启，owner私聊原生getChat可用，群3成员。Healthchecks每分钟上报两个检查，主机正常、Paper API异常信号均获HTTP_ACCEPTED；其覆盖并非全部业务门禁。未故障演练、未broker变更。设计及分类案例见docs/NOTIFICATION_CENTER.md；FYI原生API未接通。第三方仓库仅参考，不自动集成或复制源码。

验证：最终代码树完整隔离离线套件914项通过（/tmp/notification-center-final-tested-tree.log），gitleaks通过。额外覆盖公开日报例外、私人路由、非owner拒绝、未知分类、群人数变化、HTML转义、URL中token脱敏、敏感列别名/截取拒绝、同事件编辑回执及UNKNOWN不重放。上线仅重载Telegram inbox/notifications；Gateway与paper-safety保持，交易/测试额度/资金/风险文件哈希须相同。原生部署回执与回滚备份另存runtime/notification-center-deployment，不包含在Git中。

## 2026-11-08 恢复Nov7 Goal

重新核对SSH、服务、broker状态：云在线不等于IBKR恢复；02:09/02:15 Berlin上游/回读失败，API预算4次用尽，Gateway未重启。修复上游断开时跳过API心跳超时；仍保留新鲜socket与原预算/退避，不清空测试配额。

用户最终要求“能在群里搜索”，不新增整群档案。增加/work、/searchlog查询既有数据；/search与模型telegram_search通过原local bridge调用精确der/机器人白名单的按需用户会话搜索。缺会话明确NEEDS_OWNER_USER_SESSION，登录工具仅本人手动执行，会话不交模型或云。TDLib消息数据库限制与Telethon迁移源已核查并存清单。

Nov8日报实际发出的是缺报告警（group message156，02:00:06 Berlin）；新增内容状态避免误称今日附件已发。全量任务状态、工程门禁与一次参数清单在docs/GOAL_20261107_STATUS.md。没有订单、撤单、保护单修改、故障演练、自动换汇、预算重置或解除暂停。

02:18–02:20 Berlin实际故障修复：GUI卡Shutdown API且旧Java不退出，保存1247FD/963线程资源证据后通过现有systemd owner受控重启一次；新代际1378654、常驻四end与独立READBACK_COMPLETE均恢复。恢复983群message157有原生回执；现有日报补报986已发送。交易/资金/暂停/旧3次试验文件哈希不变。此为实际修复，不是演练；无人值守处理卡死shutdown仍是独立缺口，不能用本次人工修复冒充自动恢复已完善。
