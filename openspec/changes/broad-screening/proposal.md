## Why
证券目录缺少宽范围价量和财务数据，旧scanner仍是模拟，用户需要Telegram随查及券商对比并明确缺口。

## What Changes
- 增加Nasdaq/Yahoo研究价量和SEC季度frames，带来源、时间、版本、覆盖和退避。
- 将数据接入L1–L3只读研究投影；真实scanner复用既有Paper owner；L4–L6和canonical执行资格独立。
- 增加筛选、刷新、扫描、对比、数据状态菜单，维护有界定时任务。

## Capabilities
### New Capabilities
- broad-screening: 证据明确的宽范围研究、只读券商扫描和比较。

## Impact
既有秘书库增加研究表；paper-safety仅新增只读scanner，不创建broker会话或改变订单。新增optional health模块、维护timer、文档与数据流图。
