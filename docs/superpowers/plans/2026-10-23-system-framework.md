# Paper 系统框架与业务通知实施计划

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
