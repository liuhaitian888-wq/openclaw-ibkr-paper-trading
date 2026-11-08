# ABC Security Master Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [x]`) syntax for tracking.

**Goal:** 修复总名单只展示三条运行候选的问题，维护ABC范围证券目录并供秘书分页筛选，权限保持待核验。
**Architecture:** Nasdaq Trader两个官方目录进入秘书库的独立参考表；保留原始文件、hash、来源时间、刷新批次与退役记录，事务更新并保留上次成功版本。运行候选状态只读叠加，不把上市证券自动晋级或订阅行情。每日有界oneshot由systemd单owner维护目录，现有秘书负责查询。
**Tech Stack:** Python标准库、SQLite、现有Telegram秘书、systemd。
**Spec:** 本聊天用户三项要求，2026-11-08；现有market_subscriptions.py与security_master.py。

## Global Constraints
- 不操作订单、Live、Gateway或交易门禁；不全量订阅行情。
- ABC网络理论覆盖与当前实际实时权限分开，默认PENDING；未知交易所保留UNKNOWN。
- 目录覆盖美国上市证券，不声称全部美国公司；ETF/普通股/其他证券分开，OTC不属于这两个目录。
- 完整离线测试仅linked worktree；测试/secret scan后Git整合，主目录只smoke。

## Review Focus
- 空数据、HTML、缺字段、重复身份、缺尾部时间不得替换成功目录。
- 两份目录缺一或异常缩小不得部分发布；消失条目标未出现在新目录，不直接断言退市。
- 源代码符号与IBKR合约符号不混同，保留ACT/CQS/Nasdaq别名，conId未知。
- 筛选与翻页不能跳过/重复，且不能把master参考资格误标策略合格。
- 新刷新失败须保留旧名单与错误状态，连接/文件/子进程必须关闭。

### Task 1: 根因证据与官方范围
- [x] 保存云候选三条的source/time/history、13024条旧主档与71条种子名单对照。
- [x] 核对Nasdaq目录字段及ABC映射；说明LEAN大范围筛选数据与入选后实时报价分离、与券商线路限制关系。

### Task 2: 目录刷新（reporting/security_directory.py、scripts/refresh_security_directory.py）
- [x] 合成fixture测试ABC/未知交易所、ETF/普通股/其他、测试证券排除、别名与记录身份。
- [x] 实现全量解析验证、原始来源保全、事务发布、保留缺失条目与上次成功版本、异常缩小保护。
- [x] 测试失败不破坏原目录、重复快照及多次刷新、权限默认待核验。

### Task 3: 秘书查看筛选（reporting/market_subscriptions.py、reporting/secretary_controls.py）
- [x] 总名单读完整目录并叠加现有canonical/私人关注；合格名单仍只展示真实canonical资格。
- [x] 支持network=A/B/C、type=STOCK/ETF/OTHER、permission=PENDING、q=名称或代码及after分页；保留全部筛选条件。
- [x] 测试真实owner入口、分页、筛选交集、缺目录提示与合格名单不被批量晋级。

### Task 4: 验证与部署
- [x] 完整隔离离线、secret scan、Git整合、主目录smoke，日志保存state/engineering。
- [x] 云端备份/Git部署/仅重载秘书，安装每日有界目录维护timer并执行首次刷新；查询数量、来源与权限标签。
- [x] 核验Gateway代际、canonical原始载荷与交易门禁hash保持；记录当前目录时间和未验证权限。
