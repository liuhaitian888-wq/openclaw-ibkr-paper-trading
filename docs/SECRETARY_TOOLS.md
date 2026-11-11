# 秘书 Python 执行工具（2026-11-10）

目标：owner 私聊 Telegram → 云端 OAuth 模型 → Python 注册工具 → 原生系统/券商/开发任务 → 归档 → 既有投递 owner 私聊回复。模型登录不是券商认证。源码、离线验证、部署与真实 Telegram 验收分别记录于 task-closeout，不能以此文档认定已经全路径接通。

## 已实现的工具接口

- `broker_query`：area 为 account / positions / cash / orders / executions / quotes / snapshot，可给最多5个 symbols。写入已备份的秘书档案库，由既有 `ibkr-paper-safety.service` 的唯一 SDK 连接执行，不创建第二 Gateway、连接或行情订阅。队列最多12项；30秒未领取则失效，领取后20秒超时。调用最多等待8秒，READY/STARTED 可用 `broker_result` 和原始 id 查询；不能重新生成身份重提。
- 本次回读须完成原生 reconciliation 和新鲜 server reply；账户现金额外等待 accountSummaryEnd 并取消该请求自己的订阅。账户必须精确匹配 Paper；连接 generation 变化、迟到、缺失和错误不会伪装成成功。成交是 API 可见窗口，quotes 仅复用已有订阅并区分过期与未覆盖；没有承诺全市场实时权限。
- `databases` 返回所有四个已登记业务库的绝对路径、库 ID、可用性和来源时间；`schema`、`query`、`hypothesis_test` 使用相同只读注册表、SQL authorizer 和行数/时间预算。范围：交易审计、财务账本、监控恢复/通知、秘书档案。历史备份和迁移候选不作为生产库。跨库不原子；源码登记不证明每库当前可查询，部署后逐库检验。
- `service_status` 在 Python 中执行固定 systemctl show argv，允许 gateway / paper-safety / notifications / secretary-inbox / secretary-oauth / readback / intelligence；返回实时 PID、状态、内存/线程等字段。没有模型 shell。
- `cloud_tasks`、`cloud_task_submit`、`cloud_task_status` 使用官方 Codex CLI。任务提交保存原始 owner 请求与独立 MODEL 建议，STARTED 先落库；原生任务 id 才标 SUBMITTED，超时或无明确 id 保持 UNKNOWN，不自动重提。只允许真实 owner 的新开发任务，自动研究只能提案。生成代码/测试不等于部署。

## 独立启用和验收

在 `secretary-policy.json` 中独立审批 `broker_queries_approved=true` 后，已审核的唯一 broker owner 才附加查询处理器；暂停和维护不解除。`engineering_cloud_approved`、`cloud_environment_id`、`cloud_branch` 必须经原生环境兼容性核验后配置；未配置时明确拒绝，不能拿桌面 environmentConfigId 冒充 CLI legacy ENV_ID。

2026-11-10 只读实测：桌面列出“买der－云端开发” ready/runnable 配置；云端 OAuth CLI cloud list 返回空任务，原生环境选择器仅 All Environments，没有可选具体环境。因此当前 Codex Cloud 消费者尚未验收；不为通过检查新建环境、不复制 OAuth 凭据、不调用非官方后端接口。后续须核验当前环境的正式可编程入口；现有 CLI adapter 不能代替这项验收。

工具调用保存开始/结束/耗时；broker 结果另有排队、领取、完成和原生时间戳。MODEL_STARTED/FINISHED 与 Telegram 原生回执独立保存，端到端速度以真实 owner 消息测量，不以离线测试估算。broker、主机和开发任务的模型结果强制 owner-private，保持既有 sender，不把账户/路径结果自动发布群。

## 尚未实现/验收

- 完整开发运维写操作（服务启停、配置修改、数据库迁移/写入、审核后发布）需要逐项注册、恢复策略和验收；当前只读检查与云端任务适配器不等于“所有运维任务”。
- 当前 Codex Cloud 环境的正式可编程消费者、任务进度与完成回传，以及对应原生任务验收。
- 新的 Telegram → 模型实际选择工具 → IBKR → 私聊结果及各阶段延迟验收。

IBKR 官方 account_summary 文档明确 `$LEDGER:ALL` 返回 account=All 的各币种汇总。工具只在 managedAccounts 精确为唯一 Paper 账户时接纳 CashBalance/TotalCashBalance/ExchangeRate，并保留原生 account=All 及汇总范围标签；其他账户仍拒绝，不把汇总伪装为精确账户字段。来源：https://interactivebrokers.github.io/tws-api/account_summary.html 。首次工程原生 snapshot 查询因该汇总标签被拒绝，保留 UNAVAILABLE；修正使用新查询身份验收，不重放原请求。

组合查询可用 `{"name":"broker_query","area":"snapshot","sections":["cash","positions","orders"]}`，sections为1–6个不同的已登记领域，省略保持旧全量snapshot行为。只请求持仓/订单时不额外开账户摘要订阅；仍保留原生观察时间和一致性限制。一次问题优先一次snapshot，减少重复完整回读与不需要的模型上下文。真实模型到工具工程基线为23.909s（3次broker_query+databases，2轮模型）；不是Telegram端到端耗时。

确定性认证协助不经过模型工具：云端inbox仅对新切换时间之后的原生owner /login_assist核验固定Gateway状态并提交一次start。是否已部署/授权看收尾证据；正常Gateway不重启，UNKNOWN不重放，登录成功仍需另行新鲜完整Paper回读。任意服务写操作、数据库写入和开发执行端仍未因此开放。


## Official hosted Cloud decision and first acceptance request — 2026-11-10
Owner explicitly selected OpenAI official hosted Codex Cloud and approved one new read-only acceptance chat in the existing ready/runnable 买der－云端开发 configuration. create_thread was submitted once at2026-11-10T00:48:18.478Z; no threadId/clientThreadId or completion receipt returned. Recent50-thread reconciliation found no matching title, which is not proof of rejection. Creation remains UNKNOWN and must not be resubmitted automatically. Chrome currently shows a Free ChatGPT session without projects/chats, not verified as the saved-environment account. Native Codex UI inspection was rejected by computer-use safety; no bypass attempted. Official hosted task ingress and result return remain unverified; local app-server/legacy CLI cannot be relabelled as this executor. This supersedes earlier executor-choice-pending wording only; all historical attempts remain.

Cloud deterministic-control deployment observation (2026-11-10): tested cloud lineagec11f36eed86c518670bca037bdcd423a87d551f0 is installed. Root-owned exact-unit rule start/restart positive and stop/other-unit negative native authorization queries passed for ibkr with NoNewPrivileges; no Gateway action. Fresh cloud_inbox cutover is set; inbox2741969/OAuth2741970 active, Gateway2406467 unchanged, protected gate/scope hashes unchanged. Native inactive-Gateway /login_assist and full authenticated Paper recovery remain unverified.

Current deployment observation2026-11-10: cloud57452de7f8cf1fee0c27d737b9f38cb9d39dafc7 includes ledger-domain dispatch fix and bounded redacted broker diagnostics. Native engineering work/notifications searches returned2rows each in0.015/0.018s, archived separate run, zero modelcalls/messages. Actual owner504 Telegram→model→Python→DBinventory→nativeprivate391 took50s by native timestamps; broker data failed (unclaimed READY). Existing monitor has persistentattempts4 under same API process generation and CONNECTION_BUDGET_OR_BACKOFF; no budget reset or Gateway restart. Local scanner/secretary constructors pass on private consistent SQLite copy with network disabled; preceding OperationalError root cause remainsUNKNOWN. Inactive-Gateway/login drill, successful fresh Telegram broker data, official hosted Cloud task acceptance, general dev/ops/database writes remain incomplete.


## 第二阶段：限定工程类生成补丁与隔离测试（2026-11-11，默认未武装）

保留已验收单次dbcheck与原HostedUNKNOWN，不扩大交易/生产发布权限。复用既有唯一OAuth模型owner、native thread/turn回执、24/day预算、任务账本、共享MODEL提案/SYSTEM进度和唯一私聊sender；不新增后台服务、账号或付费资源，不复制OAuth。能力来源是独立owner工程类授权，MODEL观察不会伪装成USER指令。

首类`engineering-policy-types-v1`只处理工程policy坏类型：先比较scope.since才验证类型会产生TypeError/AttributeError。模型获得当前批准提交中的两个文件作为上下文，仅能修改reporting/engineering_tasks.py：在scope赋值后插入宿主规定的两条类型守卫。AST必须保留其他所有函数、导入与原门禁；测试文件只读，拒绝替代编码、路径越界、symlink、不同base hash和额外源码。不是任意代码执行授权。

`engineering_development_context`提供最小源码/来源/当前授权；`engineering_development_submit`可给MODEL提案正文（由宿主原样按MODEL存档再排队）或既有proposal_id，不接受命令或路径。两个工具轮即可完成提案/交办，适配既有第三轮只总结的预算。新任务为SYSTEM ENGINEERING_INSTRUCTION，parent指向明确标记CODEX_HUMAN_AUTHORIZATION的USER standing授权；不进入普通自动研究队列。每个独立scope最多一项，包括失败和UNKNOWN，不能更换version自动重做。

宿主从批准Git commit制作无旧history/凭据/DB的独立repository，再建linked worktree；模型补丁只应用其中。测试子进程在加载补丁前，以Landlock ABI>=3限制只读系统/venv和唯一RW worktree/tmp；libseccomp拒绝网络、宿主proc/凭据/生产DB路径访问之外的进程信号/ptrace/命名空间/新exec。所有新命令均拒绝，已启动的固定Python解释器直接执行指定测试；清空环境、关闭额外FD、继承上限只下调不抬高、整个任务130秒。用户命名空间在实际Hetzner uid_map EPERM，不作为依赖或弱化为workspace-write。

每项先运行真实kernel canary再执行不可信代码；缺失Landlock/libseccomp或canary失败即不启动模型/测试。宿主固定7-case regression先复现，然后原生Codex返回JSON补丁，再跑独立regression与原13项工程task suite。结果/patchSHA/日志由隔离外的宿主持久化，测试后校验整树diff/.git/额外文件与测试前patch完全一致；不能以模型‘PASS’或被修改的测试自行声称通过。PATCH_READY仅指该类固定检查完成，发布负责人仍须独立完整离线suite/审阅；不自动merge或deploy。

配置增量为独立`engineering_development_scope`（不得覆盖已消费engineering_scope）：
```json
{"approved":false,"class":"engineering-policy-types-v1","version":"engineering-types-20261111-v1","base_commit":"<发布后真实40位commit>","since":0,"expires":0,"max_tasks":1,"grants_trading_permission":false,"grants_deployment_permission":false,"authority":{"kind":"CODEX_HUMAN_AUTHORIZATION","thread_id":"01a1c855-b112-7351-a5b1-0f9173f49ea5","message_id":"01a1c85c-9911-7cf0-a5f2-8c8840382068"}}
```
以上未武装占位值被拒绝。sole publisher在其窗口独立验证后，base_commit必须与干净运行源码一致，since为新cutoff且>=model_owner_since，expires>now且<=since+86400，之后才可approved=true。保留实际权限来源，不将模型提案自行视为批准。

验收方案：在新scope生效后仅交办一次自然私人任务，要求秘书检查当前预授权policy类型问题；秘书先context，再submit附MODEL proposal，观察QUEUED→原生accepted/completed→受限patch→隔离测试→结果工件/private原生回执。不要再发/codex dbcheck，不创建Hosted任务，不因模型响应UNKNOWN重提。实际native验收尚未发生，不能把实现/测试称整个全局Agent已打通。

源码候选的真实kernel探测9项拒绝/许可通过；c1f源码独立repo/worktree隔离baseline复现5个异常，918字节可信参考补丁让固定7-case和原13tests通过，显式reference fixture、未调用模型/未更改生产。曾遇到tempfile缓存/tmp被Landlock拒绝，改为job/tmp后实测通过，未放宽外写。源码/完整suite/秘密扫描/实际部署与新native任务证据分别记录task-closeout。图见[受限开发实现与隔离边界](diagrams/secretary-development.html)。

发布兼容修正：开发接单/结果/UNKNOWN通知只由宿主反查原生交办来源，绑定当前已验证private owner、原任务run与received回执及原scope时间。外部standing授权只授权执行类，不作为原生私聊来源。现有publication-v2保持普通事件静默；无来源或owner变更则归档。旧SUPPRESSED/STARTED/UNKNOWN不补写或重发。
