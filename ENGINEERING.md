# 工程主文件

本文件统一工程纲领、核心要点、运行约束与验收状态。PRODUCTION.md 是当前生产停写与启动门禁的操作事实来源；历史证据按原路径保留。

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
