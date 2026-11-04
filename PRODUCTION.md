# 买 der — PRODUCTION（维护停写 / STOP）

任何生产任务：先读本文件 → 执行只读 preflight → 只在已授权阶段内操作。本轮维护停写已完成；**禁止正式切换、启动、发送、下单**，直到损坏数据/历史 state/业务冲突对账通过。工程修复通过 worktree 测试后以 Git 提交收回；数据发布单独验收。

| 项目 | 当前事实 / 唯一目标 |
|---|---|
| Production Root | 代码目标 `/Users/nbhsbgnb/Documents/New project`。7c43 代码保留并通过 Git 整合；生产启动须匹配已审核 commit/branch manifest。旧 worktree 保留 |
| IBKR Chain | 目标 TWS 127.0.0.1:7497 → 本地 API 127.0.0.1:8789；API 与 app watchdog jobs 已 disable + bootout；本轮未关闭 TWS 本体、未调用订单接口 |
| Mode 9 | `scripts/run_autonomous_trading_agent.py`；已停止。ibkr-paper-mode9、legacy mode9-agent/autonomous-paper 均 disabled、未加载；不得重启 |
| Databases | 固定 state 目标 `/Users/nbhsbgnb/.local/state/openclaw`，最终 audit=`trading_audit.sqlite3`、financial=`financial_ledger.sqlite3`；**尚未激活**。当前新库仅在维护目录 staging；源库/WAL/SHM 与所有备份保留 |
| Reports | 最终目标 `${STATE_ROOT}/reports`、运行状态 `${STATE_ROOT}/runtime`；当前 M/P 的旧 reports/runtime 未迁移或归档，已备份。代码默认路径已集中；安装中的旧 launchd 配置仍待数据验收，不可运行生产入口 |
| Delivery | 最终目标 `${STATE_ROOT}/delivery.json`；当前旧 S=`~/.local/state/paper-report-delivery` 的 ledger 原封保留且 PAUSED，daily-feishu disabled/未加载；新 root 也有 PAUSED、MAINTENANCE。staging 保留旧历史及 50 个 legacy marker，不允许重放 |
| Control | 六个 openclaw jobs 已持久 disable 并 bootout；既有 STOP 菜单未经正式收口，不使用它恢复。已授权维护操作不要求损坏源预先 integrity PASS，但正式切换仍需完整验收 |
| Health Check | 停写 PASS、备份 PASS、当前 worktree 160744 行 staging 逐行保全 PASS、目标 SQLite integrity PASS；整体 **STOP**：旧快照 72 行 state 未证明、恢复独有 1 行已获健康 state 全字段佐证并保存独立 supplement；损坏总遗失量仍 UNKNOWN、1811 个候选 key 组与目标 schema/业务 invariant 未验收。SQLite 生命周期已修复、离线 fd 回归通过；生产持续运行验收未进行 |
| Last Verified | 2026-09-09；维护观察六 job 未加载、禁用，未见本项目 DB/ledger 打开句柄。维护证据 `/Users/nbhsbgnb/.local/state/openclaw/maintenance/20260908T192959`；摘要 `docs/production-audit/MAINTENANCE.md` |

最终固定路径是目标，不是已发布配置。launchd 目前仍保存旧路径但不能自动拉起；不允许将 staging 或 Git merge 工作区当作已验收生产版本。旧 worktree 待单独审计，不删除。

快速只读检查：`scripts/check_gateway_health.command --json`（扩展诊断加 `--maintenance`）。当前预期 NOT_READY：PAUSED/MAINTENANCE、未批准生产 manifest、目标 DB 未发布。完整测试仅在 worktree 使用 `scripts/run_worktree_tests.py`；主工作区仅 smoke。

数据收口最新证据：维护目录 `final-review/`。Schema 候选已事务化重建并保留原表；当前门禁仍 STOP：state 初始化链/两条不连续历史、跨账户 occurrence 分组及 PFE 活跃订单与池状态归属未验收。72 条缺失旧载荷仅保留历史歧义标签，不作为永久独立阻塞。未发布正式 manifest、未发送。

架构审查：统一模块视图在既有 smoke 的 `modules` 字段；持久恢复状态为 runtime/recovery.sqlite3。PFE 已找到旧 position_protection 精确执行来源，不能归为手工单；来源裁决保存在维护证据，不授权修改订单。模块 observations 缺失与未发布 manifest 仍保持 NOT_READY；本轮只读查询及离线故障测试，不启动生产。

真实 adapter 接线与验收：见 `docs/production-audit/ADAPTER_ACCEPTANCE.md`。24 个模块接入既有 coordinator；真实 IBKR 只读连接与 Feishu 新认证已验证，但批准 universe、正式数据/manifest、业务对账、webhook 接收与完整生产长跑仍未验收。PAUSED/MAINTENANCE 不变，不以组件通过代替 READY。

Production Acceptance：正式 manifest/audit/financial/delivery 仍未发布；候选库 48 条待确认、11 条已提交未闭环、50 条历史 FAILED 不自动重试。维护标记正式位置为 `${STATE_ROOT}/runtime/MAINTENANCE`，与 `maintenance/` 证据目录分离，PAUSED 保留。验收明细见 `docs/production-audit/PRODUCTION_ACCEPTANCE.md`。


## 2026-11-05 云端期初基线（不解除本机停写）

用户批准从今天开始跟踪当前券商事实。云端/opt/openclaw/app已建立PAPER DUQ503649期初持仓/订单基线，2026-11-05 00:19:33 Europe/Berlin，6持仓与1张既有PFE保护单持久化回读一致。旧109条请求保留在legacy_epoch；当前broker_orders不再为空，PFE活动标记已同步；历史收益与原始交易来源不因此变完整。详细表/备份/证据与未完成事项见ENGINEERING.md最新纪要。

Broker baseline批准标记只授权现有只读采集器持久化券商事实，不授权订单、撤单或策略。PAUSED/MAINTENANCE保持；production.json仍为SAFE_MONITOR_ONLY且未批准执行。Brevo通知/PNG报表在单独监测身份下运行，不能把邮件通道批准当交易批准。
