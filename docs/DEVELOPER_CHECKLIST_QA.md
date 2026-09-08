# 开发者勾选问答：Paper 自动交易平台

本文件只描述已提交代码；每项可作为开发、审查或组会勾选记录。

- [ ] **Q：唯一的日常入口是什么？** A：`scripts/paper_platform.command` 只负责安装、拉起和检查 TWS Paper 应用；它不会启动 API、Agent 或订单。
  - 下一步建议：在真实 Paper 登录后，以 `safe-api` 仅启动 DEV_LOCK API，再单独验证只读数据链路；讨论结果：________。
- [ ] **Q：六层池的执行真相在哪里？** A：`trading/pool_state.py` 是唯一六层状态机，状态和迁移落在 SQLite；`trading/pool_manager.py` 的七池报告只做可视化，不能授权交易。
  - 下一步建议：将七池报告显式映射到六层状态机，删除任何可能被误用为执行来源的描述；讨论结果：________。
- [ ] **Q：是否已经同时监听全部目标股票？** A：否；`trading/ibkr_streaming.py` 仅订阅配置上限内的符号，`trading/monitoring_plan.py` 会把其余符号标为轮转批次。
  - 下一步建议：根据 IBKR 行情额度和稳定性实测决定全量并发订阅容量，未验证前不得宣称全量同时监听；讨论结果：________。
- [ ] **Q：数据异常会怎样？** A：`trading/data_quality_gate.py` 对空数据、接口错误、缺失/陈旧报价进入 SAFE_MODE，并要求连续新鲜数据后恢复。
  - 下一步建议：把该门接到所有真实策略入口与报警通知；讨论结果：________。
- [ ] **Q：哪些风控不能绕过？** A：`trading/risk.py` 强制正数量、最大数量、单笔金额、单笔风险、保护性止损、单标的与总敞口；`trading/session_policy.py` 另加会话、报价、重复订单和仓位限制。
  - 下一步建议：在真实账户状态同步后，把当前持仓敞口传入 `RiskEngine.validate`；讨论结果：________。
- [ ] **Q：不同余额如何缩放？** A：`trading/risk_scaling.py` 按经确认的新鲜账户权益缩放单笔、单标的、总敞口和最大风险，不接受非正权益值。
  - 下一步建议：将参数版本和账户快照哈希写入每个订单意图；讨论结果：________。
- [ ] **Q：短周期演练如何运行？** A：`scripts/run_short_cycle_endurance_simulation.py` 使用正式池、风控、SQLite 和恢复链路，但绝不连接 TWS 或提交订单。
  - 下一步建议：把短周期的故障矩阵扩大为 7 天前的持续性演练；讨论结果：________。
- [ ] **Q：如何回放和查证？** A：演练将统一时间线、状态迁移、SQLite 审计库和 SQL 查询模板写入指定输出目录。
  - 下一步建议：为真实 Paper 数据建立不可变原始行情归档与版本化回测数据集；讨论结果：________。
- [ ] **Q：日报和飞书是否已有入口？** A：`scripts/generate_daily_feishu_update.py` 生成日报，`send_daily_feishu_update.command` 负责发送；它们读取运行报告而非下单。
  - 下一步建议：补充发送幂等 ID、回执审计和数据异常/风控拒绝的统一聚合；讨论结果：________。
- [ ] **Q：LaunchAgent 的职责是什么？** A：`scripts/ibkr_paper_app_entry.py` 每五分钟检查并仅拉起 TWS 应用，7497 是唯一允许的 Paper 端口；不会保存或输入凭据、2FA，也不会启动 API/策略。
  - 下一步建议：在 TWS GUI 手动完成 Paper 登录、Socket API 和 Auto Restart 配置后，观察一周拉起和重启日志；讨论结果：________。

## 提交前勾选

- [ ] 离线单元测试通过。
- [ ] 短周期演练通过且 `paper_orders_submitted=0`、`live_orders_submitted=0`。
- [ ] `pre-commit run gitleaks --all-files` 通过。
- [ ] 未把凭据、运行产物或绝对本地路径提交到 Git。

## Production maintenance workflow (supersedes older run/verification advice)

- 开发与完整测试只在 worktree：`python scripts/run_worktree_tests.py`。默认独立临时 state，禁用真实 TCP；不得用生产源做测试。成功后 secret scan、commit，再 Git merge/cherry-pick。
- 主工作区合入后只运行 `scripts/check_gateway_health.command`；不重复完整测试。import/path/权限/singleton/DB migration gate/FD/依赖均检查；未知或 PAUSED/MAINTENANCE → NOT_READY，不自动修复或恢复。
- 生产 workspace/commit/branch/state 由已批准 manifest 约束；linked worktree 拒绝启动。生产目录当前状态以 PRODUCTION.md 为准，旧部署说明不构成启动授权。
- 每个长期资源必须有 owner；短连接在 finally/context manager 关闭，长期 IBKR worker 退出后才可替换。禁止提高 ulimit 掩盖泄漏，禁止扫描 fd 强关，禁止启动时杀掉另一实例。
- Runtime/ledger/快照/报告在 persistent state；tmp 可清理、cache 可重建、logs 有容量上限；数据库和 UNKNOWN delivery history 不是缓存。
- retry 前重验依赖，UNKNOWN/non-idempotent outcome 不自动重发。旧库恢复与冲突裁决未通过，不切换、不删源、不恢复发送/交易。
