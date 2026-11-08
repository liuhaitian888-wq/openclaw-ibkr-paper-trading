# 大范围筛选的数据与每日维护

当行情额度有限时，怎样从大量股票中找到机会，同时把实时行情留给最需要盯住的股票。

借鉴 LEAN 的 Universe Selection：总目录和初筛使用低频资料，只有较小的候选集才值得占用实时行情。本项目沿用六层业务定义，另建 L1–L3 研究投影，保存缺口；研究候选不能覆盖已有持仓、订单和 canonical 执行状态，不能自动进入 L4–L6。

## 免费数据方案核查（2026-11-09）

| 来源/开源参考 | 提供什么 | 边界 |
|---|---|---|
| Nasdaq 官方股票目录 | A/B/C 证券身份、类别与挂牌范围 | 不是账户行情订阅证明 |
| [OpenBB Nasdaq adapter](https://github.com/openbq-org/OpenBB)使用的公开 Screener | 大范围价格、当日成交股数、市值、行业 | 无免费 SLA；日期需独立交叉核验，失败保留旧缓存并标记 |
| [yfinance](https://github.com/ranaroussi/yfinance)对应的 Yahoo 公开接口 | Most Active 预设名单、带时间价格、当日量及三个月平均量 | 仅部分名单；非全市场、个人使用条件，无稳定性保证 |
| [SEC 官方 API](https://www.sec.gov/search-filings/edgar-application-programming-interfaces) | CIK、季度资产、权益、净利润、部分收入 | 免费无 key；US GAAP 标签/币种/期间可能不齐；不是历史时点可见数据 |
| [FinanceToolkit](https://github.com/JerBouma/FinanceToolkit) | 财务整理与计算方法 | 完整数据往往仍依赖 FMP 等 key/付费套餐，未当作免费全覆盖来源 |
| [LEAN](https://github.com/QuantConnect/Lean) | 宽选股池逐步缩小、动态订阅的架构 | 引擎开源不代表数据免费，不绕过 IBKR 行情额度 |
| IBKR 原生 Scanner | MOST_ACTIVE、TOP_PERC_GAIN、TOP_PERC_LOSE，单次最多50个排名候选 | 复用既有 Paper 连接；扫描结果没有价格，不等于实时权限已确认 |

因此采用 Nasdaq 广筛 + Yahoo 部分补充 + SEC 基础财务 + IBKR 小范围交叉候选，不安装整个大型选股框架。Nasdaq 原始代码保留，尾部空格明确归一化；归一化后重复仍拒绝发布。每条记录区分采集时间、源数据日期、单位、缺值和来源状态，缺值不填零。Nasdaq 未提供平均量时明确缺失，不用当天量代替。SEC 季度事实不据此臆算 PE。

## 手机入口

既有 Telegram 私聊秘书原生命令：

- `/screen`：研究候选；例如 `/screen network=C min_price=10 min_volume=2000000`，支持 q、min_cap、layer、after。
- `/screen_refresh`：登记一次当前数据维护，完成后由既有通知 owner 回复。
- `/scan MOST_ACTIVE`：排队一次真实 Paper 扫描；也支持 TOP_PERC_GAIN、TOP_PERC_LOSE。
- `/compare AAPL`：外部价量/财务与既有券商回读逐字段对照。
- `/data_status`：来源覆盖、日期、失败、任务状态和研究层分布。
- `/universe`、`/eligible`、`/marketdata`、`/market_check`：继续查看目录、执行合格名单、订阅登记及六小时抽查。

对照只读既有 broker 事实；合约对应、币种、时间戳、报价类型、连接健康任一未确认，就展示“不能直接比较”和原因，不制造差价结论。当前没有 Live 独立会话比对，也不自动登录 Live。A/B/C 登记仍不能代替账户当前订阅与 Paper 共享权限验证。

## 每日维护

| 时间（自动跟随所在时区夏令时） | 动作 |
|---|---|
| 08:10 Europe/Berlin | 既有证券目录维护：新增/退出证券、A/B/C 与类型 |
| 08:25 Europe/Berlin | 公共价量刷新；SEC 财务距离上次至少20小时才请求 |
| 工作日 09:40、15:45 America/New_York | 三种 IBKR Scanner 各一次；市场休市或依赖未就绪会明确失败/过期，不补跑旧请求 |
| 工作日 18:20 America/New_York | 收盘后公共价量维护；页面仍可能只提供上一交易日，保留实际日期 |
| 每6小时 | 既有行情权限抽查，不自动增加订阅 |
| 每分钟 | 只检查当前任务/到时窗口；无任务不采集公网行情 |

公开接口403退避1小时、429退避15分钟，其余错误至少120秒；旧值保留并标记来源失败/陈旧。Scanner 每小时最多12次、一次活动请求、最多50项、20秒超时、排队180秒过期。中断的 STARTED 标记 UNKNOWN，不自动重放。维护产生的 L2/L3 均为研究状态；无实时权限的关注股票仍保留并标待核验。

交互数据流图：[打开](diagrams/broad-screening.html)。精确部署、真实来源/Scanner验收与未确认项见 OpenSpec verification 与工程纪要；离线通过不代表云端已部署。

## 首次云端实际验收（2026-11-09）

已部署并启用维护timer。Nasdaq7062条、Yahoo活跃股450条；SEC季度事实9227项（资产2717、权益2512、净利润2544、收入1454），不是9227家公司或完整财报。ABC目录13217项，匹配到价量6645项，剩余6572项标缺失；当前研究L2为1503项、L3为22项，后者来自50项真实MOST_ACTIVE扫描的交集。其余目录记录仍在L1，可能是缺资料、类别不适用或未过初筛。Nasdaq数据日期2026-11-05，Yahoo保留各自时间戳；均不冒充此刻实时报价。

真实扫描通过既有Paper owner收到scannerDataEnd；完成通知获Telegram接受，19项私人菜单set/get一致。AAPL两路来源与broker对照均因时间/行情类型/跨源合约证据不齐而明确“不能直接比较”。定时服务已实际成功运行；未来每个交易日仍以/data_status实际状态为准。完整离线1042项通过，秘密扫描通过；PAUSED/MAINTENANCE和交易权限未因本功能放开。

手机列表逐股直接展示缺平均量、基本面不全、日期失效等标记；单股对照列出具体缺少的财务字段。/data_status层级数量是最近研究投影的汇总，逐股有效期与实时权限需继续看查询标记。
