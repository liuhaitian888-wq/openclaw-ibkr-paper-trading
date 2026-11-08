# Broad Screening and Broker Comparison Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** 免费宽范围价量/基础财务筛选接入六层研究投影，Telegram随查/刷新/真实IBKR扫描/券商对照，缺失和权限边界可见，定时维护实际运行。
**Architecture:** 既有秘书库保存带版本的外部数据、来源/时间/覆盖/失败与六层研究投影；不覆盖canonical执行状态。独立有界数据维护oneshot处理定时与按需HTTP任务；真实scanner复用已有PaperSafetyClient连接，单次最多50项并取消，未知不重放。Telegram只读查缓存、排队请求，不阻塞模型或新建broker会话。
**Tech Stack:** Python标准库、SQLite、现有ibapi/Telegram/systemd，无新增大型框架依赖。
**Spec:** 用户2026-11-09本聊天要求；参考LEAN、OpenBB、yfinance、FinanceToolkit与SEC官方接口。用户要求完成实施，不在计划末尾另设审批停点。

## Global Constraints
- 只用既有Paper身份/owner，既有交易门禁不变；不登录Live、不下单/撤单、不全量订阅、不付费snapshot。
- 免费库不等于免费完整数据；来源访问失败、日期不明、缺字段、数据冲突、权限待核验分别存储，不能填零或称可靠全覆盖。
- 日成交量不冒充平均成交量；市值不冒充基本面；SEC每项保留期间/单位/原始标签/来源，不能据季度快照算未经核对的PE。
- 真实scanner与旧模拟fixture严格区分；scanner仅候选排名，不提供报价或完整市场覆盖。
- 完整测试仅linked worktree，secret scan通过后Git整合；主工作区只smoke，云只有经批准监测服务单owner。

## Review Focus
- Nasdaq下载价量与日期元数据不同步时不借用时间；Yahoo预设Top列表保留total/partial。
- SEC映射歧义、IFRS/标签/单位/期间缺口保持UNKNOWN，不填0，不当历史point-in-time。
- 外部日频与broker盘中数据不直接判错，缺合约/币种/时间/数据类型即不可严格比较。
- scanner有界超时/取消/重连/错误/关机生命周期；STARTED在重启后变UNKNOWN，不自动重放。
- canonical活跃持仓/订单/层级不能被研究刷新覆盖或降级。

### Task 1: 来源与适配（reporting/screening_sources.py）
- [ ] 审阅官方/上游接口，实测Nasdaq/yahoo/SEC并保留脱敏能力矩阵。
- [ ] Nasdaq一次下载价量+独立日期交叉核验，Yahoo预设Most Active有界分页，SEC官方ticker映射+季度frames基础财务。
- [ ] 合成测试缺值/NaN/日期错位/重复符号/错误响应/CIK映射/季度与单位，HTTP关闭和持久退避。

### Task 2: 缓存、六层投影、维护（reporting/broad_screening.py、scripts/refresh_broad_screening.py、systemd）
- [ ] 新增只读研究数据表及任务账本，原始数据/hash/版本保全；失败保留旧快照并标陈旧。
- [ ] L1总目录→L2研究筛选→L3真实scanner交叉候选；L4–L6明确依赖实时/合约/信号/风控/执行证据，不自动晋级canonical。
- [ ] 每分钟队列检查，08:25 Berlin和交易日18:20 New York维护价量，SEC至少20小时间隔；不补跑历史，不阻塞inbox。

### Task 3: 真实IBKR Scanner（trading/broker_screening.py、paper_safety_client.py、paper_safety_watch.py）
- [ ] 复用现有连接，固定三种scan code，单一活动请求、有界50项、请求结束/超时/退出都取消owned订阅。
- [ ] 持久预留与TTL/重复抑制、错误/未知状态；回调只写有界内存，由原owner轮询落库。
- [ ] 测试不建连接、不调用订单/快照、并发/重连/晚回调/取消与UNKNOWN。

### Task 4: Telegram与对照（secretary_controls.py、secretary_queue.py、screening_comparison.py）
- [ ] /screen [筛选]、/screen_refresh、/scan [代码]、/compare 股票、/data_status原生owner菜单。
- [ ] 比较字段/日期/币种/合约与broker权限，只有可比时计算偏差；缺数据返回可解释原因。
- [ ] 完整离线/secret scan/Git整合/主smoke；云备份、Git部署、维护timer、有限真实scanner及只读回读验收，不制造订单或Live冲突。
