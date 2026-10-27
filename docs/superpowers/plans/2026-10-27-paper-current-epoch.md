# Paper current epoch Implementation Plan

> **For agentic workers:** 用户已指定本会话 native、每批约三项执行；无需重新索取 Paper 授权。

**Goal:** 保留全部历史行，为 DUQ503649 建立独立当前执行命名空间，旧请求永不重放。

**Architecture:** 使用 SQLite backup 复制已隔离源库；在候选副本内将全部原表改名为 legacy_epoch_*，原始行和元数据保留。复用 AuditLog 和 ensure_paper_automation_tables 初始化当前表。只生成候选与验证证据，不直接发布 manifest 或移除维护门禁。

**Tech Stack:** 现有 Python、SQLite、unittest。

**Spec:** 本轮用户授权与 IBKR-Paper-实施进度.md。

## Global Constraints
- 只允许 DUQ503649 / PAPER；无券商提交或外部通知。
- 来源只读、SHA256 前后相同；所有历史表逐表计数保全。
- 候选不能冒充正式已验收数据库；发布须另经真实回读/风险/备份恢复验证。

## Review Focus
- 旧 pending/UNKNOWN 行只进入历史表，当前执行表为空。
- 重复构建、目标已存在、符号链接和源目标相同拒绝覆盖。
- 非空 WAL、视图/触发器或意外表名拒绝猜测迁移。
- 索引名不占用新当前表的索引命名空间。
- 失败不留下可被误认成功的 proof；源库不变。

### Task 1: 保留历史的当前 epoch 候选
**Files:** scripts/build_reconciled_schema.py；tests/test_current_epoch.py。
**Interfaces:** stage_current_epoch(source, destination, *, account) -> dict。
- [ ] 添加测试：所有历史数据保全、旧请求不能执行、目标不可覆盖、错误账户拒绝、非空WAL拒绝。
- [ ] 实现副本内事务重命名、原索引重建、既有当前 schema 初始化和完整性/来源hash证明。
- [ ] 完整离线 runner、gitleaks，提交并Git整合主工作区，仅 smoke；部署候选构建代码。

### Task 2: 云端构建与发布门禁
- [ ] 保持 PAUSED/MAINTENANCE、发送器关闭，使用隔离源构建新候选；保存来源和逐表计数。
- [ ] 真实 DUQ503649 回读、持仓/订单/成交和PFE不可修改归属核验，备份及还原检查。
- [ ] 只有以上及新鲜行情/风险/策略事实全通过才发布正式库/manifest，进入最小Paper订单闭环。10197时禁止提交，不自动抢登录。
