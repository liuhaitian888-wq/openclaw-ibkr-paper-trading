# Secretary Fast Controls Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 降低私聊排队并提供门禁置顶与整组限额设置。

**Architecture:** 保留云端唯一接收者与通知owner、Mac受限模型owner。将接收、快速控制、模型调度、回执分别计时；复用既有版本化限额存储，增加私聊表单及预览确认。

**Tech Stack:** Python / SQLite / python-telegram-bot / Telegram Mini Apps / systemd / 现有本机Codex桥接。

**Spec:** docs/superpowers/plans/2026-11-08-secretary-fast-controls-spec.md

## Global Constraints
- 方案已获用户批准实施与部署；真实限额仅在owner明确提交确认后改变。
- 后续完整离线测试仅linked worktree使用python scripts/run_worktree_tests.py；生产只quick smoke。
- 不重放STARTED/UNKNOWN，不创建第二getUpdates owner/通知worker，不扩大模型工具、硬上限或交易权限，不清除PAUSED/MAINTENANCE。
- 目标是正常网络下快速控制p95≤3秒、聊天首次确认≤2秒；发布后实测验收，不以目标代替结果。

## Review Focus
- 运行中的研究不能让新私聊等完整多轮研究结束；只在调用边界让出，不取消或重放未知调用。
- 群中owner指令仍需拒绝交互，owner私聊正常处理；转发、匿名和其他用户均拒绝。
- 过期revision、重复确认和重复原生update不产生重复限额版本。
- 缺项、重字段、NaN/Infinity、错误单位、小数股数任一错误均整组拒绝。
- 通知拥堵、网络超时及UNKNOWN不能被提速逻辑变成第二次发送。

---

### Task 1: 可观测的快速私聊处理
**Files:** reporting/secretary_queue.py, reporting/secretary_controls.py, scripts/run_secretary_bridge.py, ops/cloud/secretary_rpc.py, reporting/incidents.py; tests/test_secretary_queue.py, tests/test_secretary_controls.py。
**Interfaces:** 新增latency_sample(received, saved, claimed, finished, send_started, ack)返回逐段耗时；保留既有claim/控制接口。新增分步模型调度接口run_step(job, checkpoint)，checkpoint只承接已确认输出，未知步骤停待对账。
- [ ] 用假时钟和假模型写测试：研究一个步骤完成后新用户任务先领取；未知调用不重放；控制指令不经过模型；接收确认每个update至多一次。
- [ ] 在worktree用指定离线入口执行，记录预期新断言失败。
- [ ] 将30秒固定等待改为有界自适应等待；将多轮研究在已确认调用边界持久化并让出。给普通消息入库后排队一条简短确认；不新增接收者或发送worker。
- [ ] 同一通知worker中优先未开始的直接控制响应，保留故障优先级及同incident先后约束；记录每阶段时间。
- [ ] 完整离线检查、gitleaks、Git提交；受控部署后使用owner实际消息测端到端，报告样本量及p50/p95。

### Task 2: 菜单和私聊边界
**Files:** reporting/secretary_controls.py, reporting/secretary_queue.py, tests/test_secretary_controls.py, tests/test_secretary_queue.py；新增scripts/configure_secretary_menu.py。
**Interfaces:** menu_commands()返回owner私聊命令列表；configure接口需支持--preview，只有--apply才调用set_my_commands，并精确限定owner私聊scope。
- [ ] 测试ready/gate前两项；群内指令拒绝且不写控制任务；owner私聊接受；第三方与转发拒绝。
- [ ] 离线入口运行并确认新增测试先失败。
- [ ] 实现菜单预览、说明文字及接收端群只通知策略，保留既有命令别名；模型不参与门禁判断。
- [ ] 完整离线检查、gitleaks、提交整合；预览核对后发布owner菜单并从Telegram实读顺序验收。

### Task 3: 五项限额表单与事务确认
**Files:** reporting/telegram_gate.py, reporting/secretary_controls.py, ops/cloud/secretary_rpc.py, tests/test_telegram_gate.py, tests/test_secretary_controls.py；新增reporting/gate_drafts.py, tests/test_gate_drafts.py, web/secretary-limits/index.html及表单入口适配。
**Interfaces:** parse_batch(text)->settings；create_draft(owner,revision,settings)->opaque_draft_id；confirm_draft(owner,id,occurrence)->既有apply结果。草案绑定owner、revision、完整五项设置与10分钟有效期；一次确认一个版本。
- [ ] 测试五项合法批量输入、缺项/重复/非法值/单位、过期/并发revision/非owner/重复确认/未知结果；断电恢复仍遵守已提交版本，不重复应用。
- [ ] 离线入口运行确认新增测试先失败。
- [ ] 实现/gate_batch兼容路径、草案存储与旧值→新值预览；确认通过既有apply写入，任何字段失败整组拒绝。
- [ ] 部署前核实既有HTTPS承载及生命周期owner；实现私聊Mini App五项预填表单，按官方initData签名和有效期验证owner，bot token只留服务端；服务器签名草案绑定当前版本，前端数据不被当作授权。缺少承载先保留表单草图，不擅自购买资源或暴露控制接口。
- [ ] 完整离线检查、gitleaks、Git整合与quick smoke；通过不改变实际限额的预览、拒绝用例及既有值确认完成线上验收。

## Audit outcome
方案审阅阶段已完成，用户随后批准实施。工程验收、部署及真实点击状态记录于 ENGINEERING.md 与脱敏部署证据。
