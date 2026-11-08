# Proposal

## Why
用户希望开发任务完成后同步架构与证据；无活动时按小时或每日唤醒会空跑。五项目需要OpenSpec规格闭环，同时保留dee、archify及既有只读采集器。

## What Changes
- 新增有变化才接续的任务收尾hook，最多继续一次，不创建定时任务。
- 五项目各自配置OpenSpec；官方技能全局安装，CLI固定1.16.1，保留项目权限和独立状态。
- 用内容指纹和有界事件记录去重，不保存聊天、凭据、运行数据库或模型原文。

## Capabilities
### New Capabilities
- `task-completion-gate`: 登记项目与worktree定位、源码变化检测、单次收尾接续和隐私边界。
### Modified Capabilities
无既有产品需求变更。project-maintenance作为各项目维护基线，不把初始化当作全部架构融合完成。

## Impact
仅工程工具、配置、OpenSpec资料与收尾规则。旧小时automation暂停；现有notify和秘密扫描hook保留。生产服务及业务权限不因本次安装改变。
