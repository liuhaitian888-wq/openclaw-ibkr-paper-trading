# 买der：本地、小米与 iPad 接续开发

## 边界

Codex Cloud 是开发环境。现有生产 systemd owner、生产分支、运行 manifest、数据库、PAUSED/MAINTENANCE 不随代码同步改变。禁止云任务启动生产 worker、发送业务通知、连接券商或操作订单。不得上传 .env、SSH 密钥、Telegram session、生产数据库、账本、原始报告和未审阅审计资料。

## 分支约定

- `develop`：已验证代码的跨设备汇合分支，不触发生产部署。
- `codex/<任务名>`：每项任务独立分支和 linked worktree；同一个任务在手机/iPad 上继续原云聊天。
- 现有生产工作区分支保留。合入生产代码必须另外遵守 PRODUCTION.md；GitHub push 不代表批准部署。
- 不启用定时双向覆盖、force push、自动 rebase 或自动合并。远端前进时先 fetch、查看差异，再合并并验证。

## Cloud 创建配置

仓库使用经过用户确认的 ibkr 仓库；环境名 `买der－云端开发`，使用权限 Only me。若界面提供默认分支，选择 develop；若没有，在准备会话中明确要求 fetch 并使用 origin/develop，核对提交后再发布。网络仅开放安装依赖所需包源；不设置生产 VPN、SSH、券商、消息通道凭据。

准备会话要求：

> 阅读 AGENTS.md、PRODUCTION.md 和本文件。环境只用于离线开发，不运行生产安装或启动脚本。使用 Python 3.13、Git、pre-commit、gitleaks。检查 origin/develop 并报告实际提交。创建 linked worktree 后执行 python scripts/run_worktree_tests.py，按实际缺失依赖补装开发依赖。禁止访问生产 state、数据库或券商。运行 pre-commit run gitleaks --all-files，并额外用 gitleaks detect --source . --no-git --redact 检查全工作区。报告全部测试结果和剩余问题，未通过不发布。

Cloud 主 checkout 可以先运行只读 smoke；无生产 manifest 时 NOT_READY 是预期门禁，不应通过启动服务修复。完整 suite 必须在 linked worktree。

示例（在云 checkout 内；任务名和路径每次唯一）：

```sh
git fetch origin
git worktree add -b codex/my-task ../my-task origin/develop
cd ../my-task
python scripts/run_worktree_tests.py
pre-commit run gitleaks --all-files
gitleaks detect --source . --no-git --redact
```

发布前核对 Environment published，并从新任务确认正确仓库、提交和离线测试；本机测试通过不能替代云端 Linux 验证。

## 每次从学校开始

手机/iPad 登录同一个 ChatGPT 账号，Codex 中选择已发布环境。继续已有任务时打开原聊天；新任务先 fetch origin，检查 origin/develop，再创建任务 worktree。已有云任务保留自己的状态，不假定自动拿到最新 develop。

## 每次交接

1. 记录当前分支、基准提交、修改范围、测试结果和待办。
2. 测试与密钥检查通过后，仅 add 本任务明确文件并 commit。
3. `git push -u origin codex/my-task`；PR 的 base 选择 develop。
4. 审阅、检查合并冲突、必要时重新运行离线测试，再合入 develop。
5. 另一设备 `git fetch origin`，在干净的开发 worktree 中 `git merge --ff-only origin/develop`。若失败，保留现场，检查分叉；不要 reset 或 force push。

生产工作区不执行普通开发 pull；只通过已审阅 Git 提交收回，并运行 quick smoke。没有任何自动部署或定时同步服务。

参考：https://learn.chatgpt.com/docs/environments/cloud-environments


## 已核验的有限冗余阶段（2026-11-10）

Hetzner现有20261109T234709.896409Z备份的四库已只读复制到Mac私有目录，逐库SHA256与SQLite quick_check通过；今日日报1778冻结PNG/JSON与原生回执也已复制并校验。数据不进入Git，云端原件保留。这是一次旧备份的第二主机副本和隔离读回验收，不是实时同步、跨库原子快照或生产恢复许可。完整证据与后续门禁见[冗余验收](production-audit/REDUNDANCY_ACCEPTANCE_20261110.md)。手机/iPad副本、断点续传、持续异地备份、Passkey发布审批及全部设备丢失恢复仍未实现/未验收，不因文档更新启动或放宽任何生产权限。
