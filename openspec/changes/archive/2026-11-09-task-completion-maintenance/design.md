# Design

## Context
现有采集器能隔离五项目证据，旧小时heartbeat不能表达用户的“任务结束再维护”。Codex原生UserPromptSubmit和Stop hook提供明确的任务边界。已有notify和secret scan hook继续保留。

## Goals / Non-Goals
**Goals:** 按内容变化接续一次；五项目独立规格；保护脏源码、无提交源码和项目权限；所有输出仅写独立工程状态。
**Non-Goals:** 文件保存监听、无人活动定时检查、后台无限开发、生产启停或自动删除。

## Decisions
1. 用原生生命周期hook而不是轮询：UserPromptSubmit采集起点，Stop比较与起点/上次结束的指纹；不读取对话原文。关联Git common-dir识别linked worktree。
2. 单次接续而不循环：同一turn请求后及stop_hook_active路径均停止再次请求；事件记录不冒充语义核验。文件锁与原子替换保护有界状态。
3. 每项目独立OpenSpec根，官方技能全局共享；CLI固定1.16.1而不自动追最新版。正常安装、审阅及原生hook信任流程，不写伪造trust hash，不更换notify。
4. 继续使用dee和archify。收尾必须核对当前用户授权，不能把新文档当新的执行命令；变更限定在当前任务，待办留给后续任务。

## Risks / Trade-offs
- [外部手工编辑后未开启任务] → 下一次项目任务收尾时与上次结束指纹比较；没有用户任务时不自行唤醒。
- [首个事件没有起点] → 只建立基线，安装时为五项目建立初始基线。
- [hook错误或维护仍未完成] → 明确记录未验证/阻塞，下一次活动任务可读证据；不无限继续。
- [应用版本和hook信任] → 使用已安装CLI的原生hooks/list核查定义与信任；不以手工执行夹具代替真实模型行为证明。

## Migration Plan
在各linked worktree准备配置并运行OpenSpec验证；主实现通过完整离线套件和秘密扫描后Git整合。安装有界用户hook并核验原生注册；旧小时任务暂停。回滚只恢复本次hook配置备份和移除本次新增的OpenSpec设置，不删除项目源码、凭据或历史状态。
