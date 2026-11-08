# Repository Instructions

## Secret Scanning

- Before committing, opening a PR, or reporting work as complete, run `pre-commit run gitleaks --all-files` when `pre-commit` is available.
- If `pre-commit` is unavailable but `gitleaks` is installed, run `gitleaks detect --source . --no-git --redact --verbose`.
- Never commit real secrets. Keep local credentials in ignored files such as `.env` or `.secrets/`, and use `.env.example` for placeholders.
- Treat any gitleaks finding as blocking until it is removed or explicitly documented as a false positive.

## Production engineering

- First read PRODUCTION.md and run the read-only health/smoke entry. Respect maintenance and PAUSED; do not start/send/trade to make a check green.
- Develop and run the complete offline suite only in a linked worktree, with `python scripts/run_worktree_tests.py`. It isolates state and disables real TCP connections. Never point tests at production DB/ledger.
- After worktree tests and secret scan pass, commit there and merge/cherry-pick through Git into the designated production workspace/branch. Preserve other uncommitted work. The production workspace runs only the quick smoke check; repeat full tests there only if the user explicitly overrides this workflow.
- Worktrees may not host long-running production services. Production code comes from the approved main workspace; persistent state uses `~/.local/state/openclaw`, never cwd or a worktree. Do not silently activate an unverified migration candidate.
- Every file/SQLite/HTTP/subprocess resource needs a lifecycle owner. SQLite transaction context managers do not close connections; use closing + a transaction scope. Long-lived clients have one owner, bounded shutdown, and no duplicate worker creation.
- Never hide a leak by raising fd limits or scanning and forcibly closing unrelated fds. Observe FD/RSS/CPU/thread/child trends; warn at 70% and critical at 85% of the process soft FD limit, or sustained growth. Diagnostics must not kill peers or send alerts externally.
- Startup must validate workspace, approved commit/branch/state manifest, maintenance gate, and a held kernel service lock; log deployment identity and paths. Reject duplicates instead of killing them.
- Recheck the dependency chain before retries. UNKNOWN or non-idempotent outcomes require reconciliation and must never be automatically replayed. Distinguish entity identity, event occurrence, and exact-content fingerprints; never add BUY/SELL blindly to a key.
- Keep source backups and provenance until reconciliation is complete. Do not delete uncommitted/unmerged worktrees or legacy state based on filename or age alone.

- Module dependency changes belong in the shared reporting.health registry/resolver. Persist stale/recovery/operation state locally; network restoration never implies business permission.
- Recovery callbacks must be bounded read-only/idempotent operations. UNKNOWN/STARTED side effects survive restart and never auto-replay. Do not install an unverified adapter merely to turn health green.
- Treat manual/external broker orders as normal exposure. Absence of a local strategy intent is not sufficient to claim ownership or cancel an order. Verify account/environment and retain broker exposure for risk checks.

## 可见研发工作流

- 用户偏好此项目以 VS Code 的 Codex 扩展和可见终端作为研发入口；展示重要命令、测试和部署的脱敏输出，并保存可复查的日志/纪要。
- 打开日志或终端不等于把当前聊天迁入 IDE；不要声称所有桌面端工具调用都会自动显示在 VS Code。
- 继续遵守 linked worktree 开发/完整离线测试、主工作区 quick smoke 和云端 systemd 单 owner。编辑器负责查看与研发，不重复启动云端生产 worker。


## 开发任务收尾维护

- 完成有源码或设计变化的授权任务时，按dee路由核对OpenSpec变更、当前规格、.der/context和受影响图表；图表需要重绘时使用archify。保留来源及历史/当前/未来分界。
- 使用项目现行验证入口和秘密扫描；源码、离线、部署、真实验收分别记录，不能把hook执行或模型审阅当成VERIFIED。
- 收尾结果写.der/context/task-closeout.md，记录本次提交/指纹、文档与图表影响、真实验证及剩余项，再刷新五项目采集状态。无变化不制造空提案或空提交。
- 任务收尾hook最多请求一次接续；不因维护启动新产品任务、定时空跑、删除旧文件、扩大业务权限或重放UNKNOWN。
