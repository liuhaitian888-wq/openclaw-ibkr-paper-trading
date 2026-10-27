# Paper 会话追踪与已有模型运行 Implementation Plan

> **For agentic workers:** 按用户已确认的 native/每批三项方式顺序实施；策略发送和生产业务邮件继续关闭。

**Goal:** 让已有模型在云端真实数据上持续产生只读结果，并提供可审计的会话干扰及恢复记录。

**Architecture:** 复用已经持续保存的私有 observations 原始证据，在现有五分钟报告中生成会话状态时间线。报告复用 ConservativeTrendModule 的纯评估方法，禁止调用订单发送、record_order_decision 或将券商外部持仓猜为策略持仓；已有 CSV 基本面只作有来源版本的参考筛选，不升级为新鲜审批。

**Tech Stack:** 现有 Python 模型、私有 JSON/Markdown、readback timer、离线 unittest。

**Spec:** 用户本轮会话追踪、稳定恢复、优先继续已有模型部署的要求；用户随后再次明确授权Paper订单，无须另询问批准，仍禁止Live。

## Global Constraints
- 本批报告接线保留 PAUSED/MAINTENANCE，不启动发送器；后续真实验收通过后直接按已获Paper授权发布/执行，不伪造安全事实，不重复请求交易批准。
- 只用精确白名单 Paper 回读；不连接 Live，不代操作手机交易。
- 原始观察文件是审计源；派生时间线可重建，采样间发生/结束时间未知须明确，不能猜手机接管或认证到期。
- 断线或10197等故障不得把旧成功/信号当当前状态；恢复后重新采样，不重放历史订单。
- CSV价格/基本面不是新鲜来源；此批只读模型输出不代表完整原系统或策略实盘验收。

## Review Focus
- 10197与1100/1101/1102分开，旧版及带时间戳callback格式均正确解析。
- 断线之后回读恢复只能标记数据恢复，不能授予交易权限或把未知结果改已确认。
- 跨重启、重复输入、缺观测区间、窗口截断不得制造登录次数或精确故障时长。
- 外部持仓不变成策略own position；评估不调用发送/记录虚拟成交，过期数据不产新建议。
- 坏文件不得留下看似当前的模型建议；报告故障不影响已有采集与心跳事实。

### Task 1: 状态时间线与已有模型输出
**Files:** reporting/paper_signal_report.py、tests/test_paper_signal_report.py。
**Interfaces:** session_state(item, account, symbols) -> dict；session_timeline(dated, account, symbols) -> dict；existing_model(samples, quote, symbol) -> dict。
- [ ] 测试10197、1100、失效身份、延迟报价、恢复、采样缺口、重复采集；模型复用、参数来源、过期/损坏禁用、无ownership/提交副作用。
- [ ] 复用原始观察生成可重建时间线；参数显式标为现有CLI参考值、未正式批准；复用value filter评估版本化CSV并标为非新鲜参考。
- [ ] 完整离线runner、gitleaks、Git整合、生产只读smoke与部署；现有定时器自动生成结果。

### Task 2: 运行方案与后续验收（不冒充此批已实现）
- [ ] 保存官方日志现有位置、开启/导出方式；确认API详细日志开启状态，保留加密原件，不自动上传。
- [ ] 记录手机Live、误登Paper、网络/服务/认证四类干扰恢复规则；用隔离样本验收，不实际踢出手机。
- [ ] 完整生产路径依次接数据/筛选池/已有策略/风控/订单回读，发布单一正式DB；最小安全验收后按已获授权直接执行Paper订单。

## 具体会话恢复方案

| 干扰 | 检测证据 | 自动动作 | 人工边界/恢复条件 |
|---|---|---|---|
| 手机Live共享行情冲突 | 10197或新鲜身份成立但报价缺失 | 停止新信号，记录缺口，保持主机/日志；只读有界重查 | 不抢回会话；用户退出冲突行情会话或独立用户名/行情配置后重新验证 |
| 手机误登同Paper用户/接管 | 券商明确竞争提示才确认；只有超时则UNKNOWN | 保留订单意图/状态，不自动登录抢回 | 用户明确结束接管并Paper重认证；精确账户、活动订单/成交/持仓对账后才能恢复 |
| 网络/API断线或日常重启 | 1100/连接错误；1101数据丢失/1102保留需区分 | 正式持久连接计划30/60/120/300秒退避；当前五分钟readback已可自动恢复只读采集 | 重订阅数据、按permId/execId/orderRef及账户对账；STARTED/UNKNOWN不重发 |
| Gateway崩溃/主机重启 | systemd/主机心跳 | 已有服务恢复进程；不能承诺恢复认证 | 若登录页或周认证失效，由用户完成2FA，不保存/绕过密码验证 |

未来Live部署仅作为设计：专用云端用户名/最小权限/独立必要行情；手机独立用户名，不与机器人互抢。人工操作视为真实组合敞口，不能自动取消或猜归属。新增用户名、权限、订阅、Live账户连接均需独立批准与验收。官方周认证限制意味着不能承诺数月完全无人干预。

官方依据：https://www.interactivebrokers.com/docs/tws-api/doc/error-handling/error-codes ；https://www.interactivebrokers.com/docs/web-api/authentication/multiple-sessions ；https://www.interactivebrokers.com/campus/trading-lessons/request-paper-trading-account/ ；https://www.interactivebrokers.com/docs/tws-api/doc/troubleshooting-support/log-files/exporting-logs 。
