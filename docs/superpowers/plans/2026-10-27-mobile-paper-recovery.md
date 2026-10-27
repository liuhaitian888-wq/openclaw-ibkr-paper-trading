# Mobile Live / Paper safety recovery Implementation Plan

> **For agentic workers:** 本轮按用户指定 native 安全实施与隔离测试，不调用真实订单或邮件 transport。

**Goal:** 手机Live影响Paper行情时停止新仓，持续记录券商订单和保护证据，完整重同步后才允许恢复。
**Architecture:** 复用TwsPaperClient回调与AuditLog、RecoveryCoordinator/IncidentStore和SMTP outbox。新增只读持久监控，独立记录完整性epoch、保护覆盖、行情/完整K线恢复证据；共享health图约束新仓。
**Tech Stack:** 现有Python/ibapi/SQLite/unittest/systemd。
**Spec:** 本轮用户六项恢复要求。

## Global Constraints
- 精确DUQ503649，loopback 4002；无下单/修改/撤单/抢登录/Gateway重启。
- 不改策略止损或200USD限额；测试仅临时DB及模拟callback/SMTP。
- 原生Submitted/PreSubmitted且transmit确认才可能计入覆盖；本地待发送不算。
- 断线/重启/部分回读/未知结果阻断；新鲜报价与断线后完成K线不足均不能恢复。

## Review Focus
- 乱序/重复execution、部分成交、断线中漏回调、重复execId冲突。
- 子单拒绝/取消/未transmit、挂接父单未完成、OCA重叠/过度覆盖。
- 10197保持订单连接、重试有上限退避，无自动抢登录或撤单。
- 旧epoch结束标记/陈旧行情/K线/恢复状态不能开门。
- incident跨重启去重，SMTP不确定不重发，恢复不等于新交易授权。

### Task 1: 持久保护/会话状态与只读callback adapter
- [ ] 新增trading/paper_safety_monitor.py，复用正式audit及incident/recovery。
- [ ] 回调持久执行、完整快照重同步、四态保护与bounded subscription backoff。
- [ ] SMTP高优先级字段/incident ID；health图PROTECTION/SESSION门禁。
### Task 2: 只读运行入口与验收
- [ ] ops/cloud/paper_safety_watch.py和默认不启用systemd unit，正式状态/配置缺失拒绝启动。
- [ ] 模拟callbacks、部分成交、断线重启、竞争行情、失败对账、mock SMTP完整离线测试。
- [ ] 完整runner、gitleaks、worktree提交、Git整合、主工作区仅smoke；更新真实交付/部署边界。
