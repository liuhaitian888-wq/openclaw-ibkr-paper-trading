# 行情订阅登记与会话通知 Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 维护零基础大纲，提供私人秘书行情订阅与股票名单入口，将既有Gateway会话证据接入现有通知队列。

**Architecture:** 订阅登记与关注名单保存在既有秘书库，canonical股票池仅只读查询；行情状态读取现有安全owner的持久证据。会话收集器复用incident timer、journal游标和outbox，不创建第二个登录、行情或发送owner。

**Tech Stack:** Python / SQLite / systemd journal / 既有Telegram。

**Spec:** 用户2026-11-08本聊天第1–5项；手机云文档明确仅研究。

## Global Constraints

- “当行情额度有限时，怎样从大量股票中找到机会，同时把实时行情留给最需要盯住的股票。”进入大纲。
- 缺少实时行情仍可关注；登记声明、实际行情、交易资格独立。
- 不购买订阅、不请求新增行情、不控制Live、不解除PAUSED/MAINTENANCE。
- linked worktree完整离线套件与secret scan通过后以Git整合；云仅观察/秘书组件部署，Gateway不重启。

## Review Focus

- 未登记或延迟行情不能宣称有实时权限；市场关闭不能仅凭报价老旧认定没订阅。
- Live套餐未声明Paper共享时不能应用于Paper。
- 六层中已晋级标的仍应出现在合格视图；关注名单不授予canonical资格。
- journal首次基线不重放历史，游标与outbox事务一致，超限/失效明确失败。
- 初始化/软重启不等于账户或行情恢复；未知投递不重发。

### Task 1: 大纲与来源（docs/PROJECT_INTRO_CN.md、docs/PROJECT_HANDOFF_MANUAL_CN.md、docs/MARKET_SUBSCRIPTIONS_AND_SESSION.md）

- [x] 写入核心问题、六层资源分配动机与LEAN相似机制/无完全同名证据的来源边界。
- [x] 记录订阅表、菜单、抽查以及手机云文档下一步研究。

### Task 2: 秘书登记与只读查询

**Files:** reporting/market_subscriptions.py、reporting/secretary_controls.py、reporting/secretary_queue.py；tests/test_market_subscriptions.py。

**Interfaces:** register(archive, instruction, data)保存owner声明；view(root, archive, eligible=False, after='')返回最多20条；check(archive,root,periodic=False)只读抽查与保存证据。

- [x] 测试未登记、Paper共享、延迟、显式权限错误、休市陈旧、分页与高层合格名单。
- [x] 增加/marketdata、/market_register、/market_check、/universe、/eligible、/watch，菜单入口；模型复用既有只读schema/query。
- [x] 在既有incident timer每6小时读取已有行情证据抽查，登记提示去重，不增加broker连接。

### Task 3: 既有会话证据通知

**Files:** reporting/gateway_session_events.py、ops/cloud/collect_incidents.py、reporting/notification_text.py；tests/test_gateway_session_events.py。

**Interfaces:** collect(store,root,reader=read_journal)保存journal游标并排队；reader(cursor)返回有界原生journal行。

- [x] 测试首次基线、重复游标、不同原生事件、未知发送不重放、初始化与新鲜账户回读分离、坏游标/超限不跳过。
- [x] 固定Gateway unit，读取脱敏阶段；复用现有outbox，私人认证类别。
- [x] 完整隔离离线测试、secret scan、commit、主工作区Git整合与smoke。
- [ ] 云端核对干净Git/manifest、备份并Git更新，只重载既有秘书inbox；incident timer自然加载。回读菜单/游标，保持Gateway代际与交易门禁哈希不变；真实会话事件不制造，未发生保持待验收。
