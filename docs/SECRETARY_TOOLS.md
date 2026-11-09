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
