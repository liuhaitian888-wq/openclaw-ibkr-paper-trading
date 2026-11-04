# Cloud Monitoring Delivery Implementation Plan

**Goal:** 落实 ENGINEERING.md 的持久提醒、时间证据、准点报告与可追溯验收。
**Architecture:** 复用 IncidentStore、RecoveryCoordinator 和唯一飞书 worker；不新增交易权限或重复发送者。报告以只读数据构建，监测与生产数据发布分别验收。
**Tech Stack:** Python、SQLite、systemd、官方飞书 webhook。
**Spec:** ENGINEERING.md

## Constraints
- linked worktree 离线测试；维护标记保留；UNKNOWN 不重放。
- 每项真实测试前说明主机、方法、影响、证据路径。

## Tasks
- [ ] 统一工程主文件，历史入口保留链接。
- [ ] 持久提醒：30分钟、2小时、24小时与此后每天；跨越多阶段只生成最新摘要，事务/重启/恢复/不确定状态去重。
- [ ] 通知时间：发送前/回执时间持久化；服务端时间不合成，成功不重发。
- [ ] 报告：09:00北京时间准点，周一/每月1日合并、缺失准点告警、当天一次补报，禁止过日重放。
- [ ] 完整离线 suite 和 gitleaks；Git 整合后主目录 smoke。
- [ ] 云端受控部署与真实飞书验收；Gateway 设置与外部监控独立核查，保留备份。

## Review Focus
- UNKNOWN 或成功回执后落库失败不允许再次发送。
- 调度跨过多个阈值、时区/DST和重启不能补发多条旧消息。
- 过期/缺失/跨账户数据不得伪装新报表。
- 维护门禁不因通知恢复而改变。
- Gateway 进程在线不等于 API、行情、认证正常。
