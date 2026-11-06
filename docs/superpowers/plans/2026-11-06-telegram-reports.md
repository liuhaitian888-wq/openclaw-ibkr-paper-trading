# Telegram daily report integration plan

**Goal:** Deliver existing actual-account PNG reports to the user-created der group through the new approved Bot, preserving durable side-effect identity.
**Architecture:** Keep the existing report source/template/scheduler and one outbox owner. Telegram is the primary owner for all new reports, incidents, recovery, reminders and authentication notices. Brevo remains a dormant manually selected backup, never an automatic fallback. Successful or UNKNOWN historical deliveries never replay on channel change.
**Tech stack:** python-telegram-bot22.8, existing SQLite/report schedule/systemd; token in private0600 config.
**Spec:** User created der group with only self and Bot, approved creation/private local+cloud credential storage and financial report delivery.

## Constraints and review focus
- Verify exact Bot identity and group ID/title, owner and member count2 before financial send.
- Original PNG content hash and bounded path/size before transfer.
- One native send per notification; record native messageID/server date. Timeout after send is UNKNOWN and never falls back automatically.
- All notification kinds route through the same Telegram owner. Preserve accepted/UNKNOWN history and occurrence identities; do not bulk replay historical messages.
- Full worktree offline suite, secret scan, Git deployment and one current real report acceptance.

## Tasks
- [x] Create/verify approved Bot, private token intake and real user-created target group.
- [ ] Implement mature library transport, shared receipts/queue routing and scheduling integration.
- [ ] Validate offline tests, scan, Git integrate/deploy without changing trading gates.
- [ ] Verify one actual report in the exact group and enable daily schedule.
- [ ] Record repository registry and actual integration/maintenance status.

## 2026-11-06 verified migration and acceptance checklist
Source: ENGINEERING.md lines 68–82 and existing report/authentication/incident schedulers.
- [x] Read-only main smoke: NOT_READY with PAUSED/MAINTENANCE retained.
- [x] Daily 09:00 Asia/Shanghai, Monday weekly, first-of-month monthly; merge overlaps.
- [x] Missing report text at schedule; once-only same-day supplement; no old-day catch-up.
- [x] Shared Telegram path: ALERT, RECOVERY, protection/escalation, staged reminders, current summary, authentication, report bundle/supplement.
- [x] Native message receipt, server time, local start/ack, planned/queued time and actual start delay; negative delay is retained.
- [x] Restart retains STARTED/UNKNOWN; no replay or SMTP fallback. One worker and one durable outbox.
- [ ] Verify cloud Telegram config/package/owner and bounded real report receipt; no synthetic test flood.
- [ ] Official Flex: bounded official endpoint collector, exact account/period/sections/hash, parser provenance; unavailable is missing.
- [ ] Reconcile existing Paper journal and scope before order acceptance; never reset consumed budget or touch PFE protection.
- [ ] Final full offline suite, staged+all-files secret scan, Git integration, remote push, cloud ff-only deployment/manifests and smoke.

Operational timing carried forward: <=60s normal-network event/schedule-to-ack target, reminders first/30min/2h/24h/daily, offline catch-up one current summary, estimated authentication 24h/1h. External heartbeat <=120s remains a separate unresolved acceptance item; existing 5min provider settings do not satisfy it.

## 可见运维收口（用户2026-11-06追加）
- [ ] 新增只读运行时间线导出：全球门禁、分故障通知及原生回执、暂停条件聚合；时间统一Europe/Berlin，原UTC保留。无发送/重连/订单接口。
- [ ] 用fixture验证账户/故障身份不混合、UNKNOWN保留、聚合不冒充停机次数、SQLite句柄关闭；缺来源明确warnings。
- [ ] 只读云取证后生成今日Markdown对照表，在VS Code打开；研发优先使用已授权worktree与可见终端，生产服务保留云systemd单owner。
- [ ] 公共健康依赖按实际主通道选择，默认保留兼容，Telegram不能因为旧Feishu故障被误判；不以健康图修改授予自动交易权限。

## 2026-11-06 用户追加：日志证据与通知字段
- [ ] 核对Nov5柏林日账户快照、10197回调、当前状态/历史表；缺少正常行情证据的区间明确UNKNOWN，不用没有报错推导正常。
- [ ] 同一pause scope保持暂停时，reason变化不再插入新的PAUSE；当前原因保留latest state及分钟采样，真实进入/解除/恢复与错误事件仍记录，旧历史不删。
- [ ] 在同一持久recovery数据库追加每分钟一条会话/行情采样，分API/上游/账户身份/回读/各标的行情/策略门禁，不冒充逐秒连续可用率；不回填历史。
- [ ] Telegram仅改展示：字段空行、柏林时间到秒、中文类型、建议操作、故障批次、事件编号最后、删固定尾句；底层高精度时间/身份/回执保留，图片caption也保留末行编号。
- [ ] fixture验证格式、caption边界、负时差、历史身份兼容、采样频率与reason去噪；全套离线+secret scan后Git部署，不重放旧消息。
