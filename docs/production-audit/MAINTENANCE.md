# 2026-09-08 维护停写、备份与 staging：STOP

## 已执行与边界

本轮用户明确授权维护停写，覆盖此前“只读不可停机”的限制。顺序执行：保存 plist → disable → bootout → 两次无 DB handle/源 stat 稳定检查 → 原始文件及一致快照备份 → 副本恢复与 staging → 再次验证无 writer。没有恢复生产、发送、下单、移动原库、删除文件或 commit。

固定 state 目标：`/Users/nbhsbgnb/.local/state/openclaw`。

本次 run：`/Users/nbhsbgnb/.local/state/openclaw/maintenance/20260908T192959`，下文 R 表示该目录；它独立于任何 Codex worktree。

最终代码目标：`/Users/nbhsbgnb/Documents/New project`。最终文件目标：state root 下 `trading_audit.sqlite3`、`financial_ledger.sqlite3`、`delivery.json`，reports/runtime 使用同一 root 子目录。**尚未正式激活。**

## 维护停写 PASS

六 jobs：ibkr-paper-mode9、ibkr-paper-api、ibkr-paper-app、daily-feishu、mode9-agent、autonomous-paper，均执行 launchctl disable；已加载者 bootout 成功，原先未加载者返回 No such process。旧 S/PAUSED 未变，新 root 已建立 PAUSED/MAINTENANCE。没有停止 TWS 本体，不发 broker cancel/flatten/order 请求。

R/stop-actions.json 保存每一步返回值；R/no-writer.json 保存两次源 stat 与无句柄证据；R/final-no-writer.json 再次确认六 job 未加载、disabled，无本项目 DB/ledger 打开句柄。现有 API/Mode9 的 KeepAlive 已不能自动拉起。未将 PAUSED 误当 DB 停写门禁。

## 备份 PASS

R/backup-manifest.json：7 个 SQLite 源文件组（主目录 old/v2、P audit、financial 主库及两备份、simulation）。每组保留原 DB/WAL/SHM（若存在）及 SHA256、大小、mtime、SQLite metadata；健康库另用 SQLite backup API 生成一致 snapshot。损坏库仅保全原件，不声称其逻辑 backup API 成功。

R/backup/main、R/backup/worktree：M/P reports 与 .runtime；R/backup/delivery：旧 delivery 全目录。R/all-backup-files.json 对 2896 个备份文件保存 hash/size/mtime。备份非归档移动；所有源仍保留原路径。

## Git 回收完成到主目录工作区，尚未 commit

- 主目录原 tracked 修改用 Git stash 保全，stash 名 openclaw-maintenance-preserve-main-tracked，未 drop。
- `git merge --no-commit --no-ff 5d66e49...` 合入 P 已提交历史，保留主目录 cfae40c 的存储优化。
- 使用独立 Git index 捕获 P tracked/untracked 代码，经 `git diff --cached --binary` 与 `git apply --3way` 合入主目录，没有目录复制覆盖。
- 再 apply 主目录 stash。唯一冲突在 send_feishu_report.py；同时保留 P 的 guarded transport 和主目录 main() 提前 PAUSE 检查（在 image upload 前阻断）。无未解决冲突。
- R/worktree-uncommitted.patch、R/main-integrated.patch、R/git-status.txt、R/git-diff-stat.txt、R/git-stashes.txt 保留证据。7c43 文件未被清理，工作区原状态保留。
- 合并是待提交的 Git merge；没有批准生产 commit。13 个 report guard/scheduler/acknowledgement 单测通过；未把这些测试当整套生产验收。

## audit staging：逐行保全 PASS，正式验收 STOP

R/staging/trading_audit.sqlite3 是**候选库**，不得当 production DB。源为健康 M v2、停写 P snapshot、损坏 M old 中可直接读取的记录。恢复数据作为独立候选保存在 migration_rows，不静默灌入业务表。

- 停写 P 有 **160744 行**，全部可投影回原始列名、类型和值，校验差异 **0**。
- 全部非恢复源共 **549595 条来源记录**逐行投影验证通过；精确重复归并后 87 个业务表合计 **394235 行**。migration_rows 保留 source_id、table、source ordinal、原始 JSON、fingerprint、target rowid、outcome；每个精确重复仍有独立 provenance。
- 同 key 多载荷 **1811 组**，在 conflicts.json 单独输出；包含源内事件 ID 重复、跨源版本及可变 state，不能简单当 1811 笔重复交易。无静默 overwrite。
- integrity_check=ok、foreign_key_check=[]。后者只表明当前候选无被声明 FK 违规，**不是业务 invariant 完成**。
- 目标为暂存 schema union，保留各列值、类型冲突使用无损存储；原 PK/unique/index/业务 state 约束还未部署验收，production_schema_approved=false。不能直接 promote。
- 第二次运行只校验同源 hash/逐行映射，插入=0、更新=0、DB SHA256 不变。R/openclaw_stage.py 识别已有完成候选后转只读 verify；不完整候选拒绝覆盖。证据 repeat-verification.json。

逐表 row count / unique fingerprint / duplicate / 时间范围在 R/staging/reconciliation.json。源 SQL/恢复 stderr/候选数据/全部 provenance 都在 R/staging，源库未修改。

## 必须区分“停写快照全保留”与“此前160530行全保留”

此前只读观测后，Mode9 继续运行直至本轮授权停写。新快照多 214 行 transition，同时 72 行 canonical_pool_state 被运行中的程序更新。

- 85 张其他表 fingerprint set 与此前快照完全相等。
- canonical_pool_transition_events 按此前最大 timestamp 截断后，89757 条旧记录的 fingerprint set 与此前 SHA256 完全相等，新增 214 条也保留。
- 因此此前 **160458 条**可证明精确保留。
- **72 条旧 canonical_pool_state 的完整旧版本未证明保留**；本轮保全的是停写时的72条当前版本。旧观测只保存了集合 hash，没有原始载荷，不能靠总数 >=160530 代替证明。
- 在备份副本上解析 WAL：当前有效帧在校验中止前没有可用提交；又把旧/未提交页作为候选读取，只接受与旧已知 row-set SHA256 完全相等的结果，没有找到匹配。候选不是有效事务，未导入。

证据：historical-baseline-check.json、historical-preservation.json、wal-history-result.json、wal-stale-history-result.json。不得把未找到恢复版本写成“0 丢失”。原始 DB/WAL/SHM、旧报告与所有副本仍完整保留，待进一步取证。

## 损坏库恢复：62052行候选，1行未裁决

只对 R/staging/damaged-source 副本运行 SQLite .recover；默认和 --ignore-freelist 两种结果都得到 canonical_pool_transition_events **62052 行**，恢复库 integrity ok、无 lost_and_found 表。

其中 **62051 行**可从旧库直接迭代读取且匹配（旧 SELECT 在后续损坏处终止）；剩余 **1 行**只见于恢复结果：MU，2026-07-13T15:33:03.145120+00:00，trace mode9-cycle-1145。其列值与内嵌 payload 一致，但 M/P reports 备份中未找到独立同事件证据，保持 RECOVERY_QUARANTINE。恢复出的总数不是原库完整性的证明，unrecoverable_count=UNKNOWN。

不能猜测这一行是否足够代表全部损坏内容，不能在此状态删除/替换源库或宣称 reconciliation PASS。

## financial / delivery staging

R/staging/financial_ledger.sqlite3 来自80行主文件一致快照；两备份10/18行均为其子集，不 merge。运行 consumer 在 M/P 未证明，正式 ownership 验收仍未通过。

R/staging/delivery.json 保持原有字段逐项相等，追加 source hash/run provenance 和 **50 个**旧发送 marker 记录，全部 LEGACY_SENT_UNVERIFIED / automatic_replay_allowed=false。未把历史290个失败通知的 SENT_ACCEPTED 当完整报告 ACK。staging/PAUSED 存在，旧 S ledger/PAUSED 原封不动。

## 未执行的正式切换与回滚方案

由于以上三类证据缺口（历史72 state、损坏恢复1行及完整性、业务冲突/schema/financial ownership），正式切换门禁 STOP。未把主目录代码默认 DB、launchd、health、reports/state 改成尚未验收的目标；旧 plist 的旧路径仍在，但均禁用。未创建固定 root 的正式 active DB/ledger，只有 staging 候选。

未来路径切换方案明确为：代码根 M、state 根 ~/.local/state/openclaw、Python M/.venv313/bin/python；jobs/health/report/control 全部显式引用该配置，旧入口 fail closed。此时仍不得启动。只有完整 reconciliation、业务 invariant、schema compatibility、rollback rehearsal 后才能进行这个步骤。

回滚材料已保全，回滚动作未执行：
1. 保持全部 jobs disabled、两个 PAUSED 与 MAINTENANCE，不以回滚为理由启动或发送。
2. 本轮尚未切换生产源，数据回滚无需覆盖任何源；只需保持候选隔离。
3. 若需要撤回主目录 Git 整合，先保存当前 patch 和未跟踪文档，再通过 Git merge abort/恢复保留 stash 处理；不得对用户工作区直接 reset --hard。stash 与 P 原工作区都保留。
4. 原 plist 备份可供配置回退，但不能自动 enable/bootstrap。
5. 真正发布前必须演练目标快照恢复、hash/keys/checksum、无writer与禁发送检查；当前 rollback readiness 只到“材料完整”，不是正式恢复验收 PASS。

下一步是继续独立历史取证及业务对账，不能生产恢复。若缺少原始历史72行载荷或损坏记录独立依据，不得把目标改成“猜测恢复”来通过门禁。

## Engineering follow-up — 2026-09-09 (supersedes code status above)

Development and full offline tests run only in the linked `production-maintenance` worktree. Code defaults now use `trading/production_paths.py`; Git promotion is separate from production data activation. Installed launchd plists remain disabled with legacy paths pending a reviewed data cutover. No source DB, report tree, credential, worktree or ledger was removed.

EMFILE means a process exhausted its descriptor limit. The confirmed code defect is using SQLite connection context managers as though they close connections: they commit/rollback but leave close to GC. Repeated audit/state/report opens are now explicitly closed while preserving transactions. Offline regression disables GC, lowers the child limit to 256, runs 300 audit/pool cycles: all 11 samples were 5 FDs. The stopped historical PID cannot be profiled retrospectively; this proves the defect and fix, not the exact historical allocation breakdown or live endurance acceptance. IBKR streaming has one owner, rejects duplicate threads, and disconnects/joins on timeout and shutdown; HTTP server closes in finally; failed audit flush preserves queued events. No arbitrary fd close or limit increase.

Inventory evidence: `engineering/worktree-process-inventory.json`. Fourteen worktrees exist, none proved stale enough to delete. No orphan/zombie production runner was observed; cwd-matching node/shell inspection helpers are not production. Unmerged branches and dirty 7c43 remain. Multi-agent causation is unsupported.

Dot directories mean hidden names, not a lifecycle guarantee. Observed repository/worktree names: .codex (tool config), .secrets (legacy credentials, retained), .pytest_cache/.pycache/.pip-cache (rebuildable test/interpreter/package caches), .venv/.venv313 (environments), .git (Git metadata), .idea (editor metadata), .der (project local metadata), .runtime (legacy state, migration source). No project .local was found. Home ~/.local contains bin, share, state; state contains gh, pnpm, openclaw and paper-report-delivery. Home .cache includes gh, yt-dlp, fontconfig, codex-runtimes, pre-commit. Do not bulk-delete these unrelated directories.

Canonical write destinations: ~/.local/state/openclaw/{trading_audit.sqlite3,financial_ledger.sqlite3,delivery.json}; reports/ for generated reports and snapshots; runtime/ for lock/PID, IBKR/watchdog/report/retry state; runtime/tmp/ for disposable scratch; cache/ only rebuildable data; logs/ for diagnostics (5 MiB × 4 retained files per service). Existing legacy logs retain their prior policy and are not silently cleaned. maintenance/ holds immutable backup/provenance/reconciliation evidence. Credential files remain in their existing ignored locations until a separate validated move; no secret values were read into reports. Explicit fixture paths are retained for tests; production entry guards reject linked worktrees, incompatible paths, missing approval manifest, maintenance and duplicate instance.

Diagnostics use stdlib ps/lsof and rotating logs: PID/PPID/uptime/RSS/CPU/threads/children, FD categories and 70% warning/85% critical thresholds, trend, commit/branch/cwd/state root. Directory size is opt-in. Missing live IBKR/Feishu proof reports DEGRADED, not success. Reused health command performs read-only smoke; it never sends or orders. A production restart is not authorized by passing unit tests. Existing 72 historical state values, recovery-only row and semantic/schema reconciliation remain STOP.
