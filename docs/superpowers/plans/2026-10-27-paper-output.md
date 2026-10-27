# Paper 只读输出 Implementation Plan

> **For agentic workers:** Use the existing worktree workflow to implement sequentially. Keep all trading and production email gates closed.

**Goal:** 让现有云端五分钟采集持续产生可读的真实行情质量与均线影子报告。

**Architecture:** 复用 collect_paper_evidence 的独立、精确 Paper 账户只读采集及 MovingAverageSignalEngine。只消费已存观察文件，不新增连接、数据库、交易服务或通知；采集结束后生成私有 JSON/中文 Markdown，报告错误不改变原采集结论。

**Tech Stack:** Python 标准库、现有 strategy 引擎、现有 systemd readback timer。

**Spec:** 本轮用户“make it run, make it produce”及禁止未批准自动下单的持续约束。

## Global Constraints
- PAUSED/MAINTENANCE 和交易/生产业务邮件关闭状态保持。
- 仅验证完整、精确白名单 Paper、已断开且 data_type=1 的新鲜双边报价；不使用示例基本面。
- 均线仅用于五分钟报价中间价采样的影子分析，不冒充完整 L1、成交价 K 线或盈利验证。
- 不做付费快照、不修改交易数据库，不绕过 production guard。

## Review Focus
- 旧成功后登录失败：当前必须显示阻塞，不输出当前信号。
- 跨断线、重复观察、异常时间：清空连续样本或去重，禁止虚构连续趋势。
- 账户错误、延迟行情、NaN、倒挂报价：拒绝样本，不输出信号。
- 报告错误：不能改变已保存采集证据或外部心跳结论。
- 文件读取有界，输出 0600；不发布私钥、Ping URL 或凭据。

### Task 1: 报告出口和安全回归
**Files:** reporting/paper_signal_report.py；tests/test_paper_signal_report.py；ops/cloud/collect_paper_evidence.py。
**Interfaces:** build_report(observations, expected_account, symbols, now) -> dict；write_report(root, config) -> dict。
- [x] 写失败测试：新鲜完整样本、断线清空、重复不计数、账户/数据质量拒绝、无网络/DB写入、报告故障隔离。
- [x] 实现有界读取、现有 MA3/5 两次确认、原子私有报告、采集后调用。
- [x] 完整离线 suite：581 tests / 57.633s / OK；gitleaks --all-files 通过。
- [ ] 通过 Git 整合；只读部署，不改变 unit/gates。

### Task 2: 实际输出与恢复
- [ ] 云端现有定时器自动产生报告；若未登录，真实输出 AUTH_OR_CONNECTION_REQUIRED。
- [ ] 用户完成 Paper 登录后只读验证精确账户、真实行情，积累连续采样；展示具体报告。
- [ ] 更新总进度，区分运行、数据可用、信号和未授权交易。
