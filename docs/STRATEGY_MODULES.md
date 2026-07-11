# OpenClaw Strategy Modules

本文档整理当前已经实现的策略相关模块，目标是让策略逻辑、函数职责和安全边界可以被独立审阅。本文只描述 paper-only 策略层，不授予任何绕过 Trading API 的下单能力。

## 实施背景

OpenClaw / IBKR paper 自动投资项目采用分层架构：

```text
universe 股票池
-> 行情读取与 bar 构建
-> 策略信号
-> 策略内风控
-> Trading API 硬风控
-> IBKR paper
```

策略层的职责是从 approved universe 和实时/模拟行情中生成小仓位、结构化、可审计的交易意图。策略层不直接连接 broker，不直接写入账户，不保存或读取 daily trade token。所有真实 paper order 仍必须经过 Trading API 的 lock、token、TWS readiness、allowlist、风控和 audit gate。

## 当前策略清单

| 策略/模块 | 位置 | 当前用途 | 下单权限 |
| --- | --- | --- | --- |
| `classic_conservative_trend` | `trading/strategy_modules.py` | 当前 autonomous agent 调用的主策略模块 | 只能通过 Trading API 提交 validate/stage/paper 请求 |
| `MovingAverageSignalEngine` + `TacticalLongStrategy` | `trading/strategy.py` | 早期模块化扫描框架和本地仿真路径 | 生成 proposal，由调用方决定是否提交到 Trading API |
| `ValuePoolFilter` | `trading/strategy.py` | universe/value pool 预筛选 | 不生成订单 |

## 主策略：classic_conservative_trend

`classic_conservative_trend` 是当前主策略。它是一个保守的双均线 SMA 趋势策略，不是纯 AI 自由决策策略。

### 策略目标

- 只做 long-only。
- 每次 1 股级别小仓位。
- 只交易 approved pool / allowlist 里的 symbol。
- 使用 fast SMA 和 slow SMA 做趋势确认。
- 用小止盈、小止损和趋势破坏退出。
- 用 cooldown、quote freshness、spread 和 portfolio risk gate 降低误触发。

### 入场逻辑

BUY 条件全部满足才会生成订单意图：

```text
symbol 在 approved pool 中
quote 未过期
spread 未超过阈值
不在 cooldown 中
bar 数量足够计算 slow SMA
fast SMA > slow SMA
last price > slow SMA
(fast SMA - slow SMA) / slow SMA >= min_gap_pct
```

满足条件后，策略用 `ask` 作为优先 limit price；如果没有 `ask`，退到 `midpoint`，再退到 `last`。

### 出场逻辑

已持有该 symbol 的 in-memory paper position 时，任一条件满足即 SELL：

```text
last price >= entry_price * (1 + profit_target_pct)
last price <= entry_price * (1 - stop_loss_pct)
fast SMA < slow SMA
```

SELL 使用 `bid` 作为优先 limit price；如果没有 `bid`，退到 `midpoint`，再退到 `last`。

### 默认/运行参数

代码默认值在 `ConservativeTrendConfig` 中；`scripts/run_pool_strategy_module.py` 会用命令行默认值覆盖为更快触发的 paper 参数。

| 参数 | 代码默认值 | runner 默认值 | 含义 |
| --- | ---: | ---: | --- |
| `fast_window` | 3 | 2 | 快速 SMA 窗口 |
| `slow_window` | 5 | 3 | 慢速 SMA 窗口 |
| `profit_target_pct` | 0.004 | 0.0015 | 小止盈阈值 |
| `stop_loss_pct` | 0.003 | 0.0015 | 小止损阈值 |
| `min_gap_pct` | 0.0005 | 0.0001 | 快慢均线最小距离 |
| `max_spread_pct` | 0.002 | 0.002 | 最大 bid/ask spread 比例 |
| `max_quote_age_ms` | 5000 | 5000 | 最大行情年龄 |
| `quantity` | 1 | 1 | 每次订单股数 |
| `cooldown_steps` | 1 | 0 | 同一 symbol 订单后的冷却步数 |

## `trading/strategy_modules.py` 函数和类职责

### 数据结构

- `ConservativeTrendConfig`: 主策略参数，包括均线窗口、止盈止损、价差、新鲜度、数量和 cooldown。
- `ModulePosition`: 策略内存中的 paper position，仅用于让 SELL 必须跟随本模块记录过的 BUY。
- `ModuleDecision`: 单次策略判断结果。`action` 为 `BUY`、`SELL` 或 `HOLD`；`is_order` 表示是否具备提交订单所需字段。
- `PortfolioRiskConfig`: portfolio-level 风控参数，包括最大持仓数、单标的市值、总市值、日亏损和连续亏损限制。
- `PortfolioRiskDecision`: portfolio risk gate 的批准/拒绝结果。

### `ConservativeTrendModule`

- `__init__`: 校验 fast/slow window，并初始化 approved symbols、in-memory positions 和 cooldown 记录。
- `positions`: 返回当前策略内存持仓副本。
- `evaluate`: 核心策略入口。读取 bars 计算 fast/slow SMA，先做通用阻断检查，再决定 BUY、SELL 或 HOLD。
- `record_order_decision`: 在订单提交成功后记录 BUY/SELL 对策略内存持仓的影响，并更新 cooldown step。
- `_exit_decision`: 对已有 position 判断止盈、止损或均线趋势破坏，返回 SELL 或继续 HOLD。
- `_common_block_reason`: 做 symbol allowlist、quote freshness、spread、cooldown 四类通用阻断。
- `_averages`: 从 close 序列计算 fast SMA 和 slow SMA；历史不足时返回 `None`。

### `PortfolioRiskGate`

- `evaluate`: 对 `ModuleDecision` 做组合级风控。SELL 必须对应已有内存持仓；BUY 会检查日亏损、连续亏损、是否 RTH、最大持仓数、单标的市值和组合总市值。
- `_position_market_value`: 用 latest quote 或 entry price 估算单个持仓市值。
- `_is_regular_session`: 根据本地 `datetime` 的时分判断是否处于配置的常规交易时段。

## `scripts/run_pool_strategy_module.py` 职责

这是当前主策略的 runner。它可以跑 `validate`、`stage` 或 `paper`，但 `stage`/`paper` 必须先通过 Trading API health gate。

- `parse_args`: 定义策略、行情源、universe、Trading API、TWS read-only、风控和报告参数。
- `main`: 端到端运行策略。读取 API key、检查 health、筛选 universe、构建行情源、扫描行情、调用策略、调用 portfolio risk gate、提交订单、写 JSON report 和 dashboard。
- `build_source`: 根据 `--source` 构建 simulated、simulated-scenario 或 IBKR read-only quote source。
- `build_universe_selection`: 把 universe CSV、value filter、手动 symbols 和 gateway allowlist 合并成可扫描集合。
- `monitor_symbols_from_records`: 从 universe selection 中过滤结构性拒绝原因，形成 monitor symbols。
- `scenario_price_series`: 生成能快速触发 BUY/SELL 的测试行情序列。
- `default_price_series`: 给模拟行情提供基础价格。
- `endpoint_for_mode`: 把 `validate`、`stage`、`paper` 映射到 Trading API endpoint。
- `submit_order`: 调 Trading API；失败时返回结构化错误，不直接抛出到策略循环外。
- `order_payload`: 从 `ModuleDecision` 生成 Trading API limit order payload，并创建 idempotency key。
- `decision_payload`: 把策略判断序列化到 report。
- `compact_scan_report`: 压缩 scanner 输出，减少 report 噪声。
- `pnl_snapshot`: 基于策略内存持仓和 latest quotes 估算策略内 PnL 曲线。它不是账户级实时 PnL。
- `realized_pnl_for_decision`: SELL 时按策略内存 entry 和 limit price 估算 realized PnL。
- `require_gateway_mode`: 对 stage/paper 模式检查 TRADE_LOCK、paper transmit 和 TWS readiness。
- `request_json`: 调 Trading API 并解析 JSON。
- `parse_symbols` / `parse_list`: 命令行字符串解析。
- `read_required`: 读取必需文件，例如 API key 文件；调用方不得打印内容。
- `read_trade_session_token`: paper 模式读取 daily token；调用方不得打印内容。
- `payload_without_token`: 写 report 前移除 trade session token。
- `quote_payload`: 序列化 quote。
- `write_report`: 写策略 JSON report。
- `write_dashboard`: 写本地 HTML dashboard。
- `elapsed_ms`: 毫秒计时工具。

## 早期扫描框架：`trading/strategy.py`

这个文件包含更通用的模块化策略组件，其中双均线信号和战术入场规划可用于仿真和后续策略扩展。

### Value pool

- `CandidateProfile`: 基本面画像输入。
- `ValueFilterConfig`: 估值、质量、成长、安全性阈值。
- `FilterResult`: value filter 输出。
- `ValuePoolFilter.evaluate`: 判断 profile 是否通过硬阈值和最低分。
- `ValuePoolFilter.score`: 计算 valuation、quality、demand、safety 四部分分数。
- `ValuePoolFilter.approved_symbols`: 从 profile 列表提取通过筛选的 symbols。

### 双均线信号

- `MovingAverageConfig`: short/long window、确认 bar 数、最小斜率和最小 gap。
- `SignalDecision`: `ENTER_LONG`、`EXIT_LONG` 或 `HOLD` 结果。
- `MovingAverageSignalEngine.__init__`: 校验窗口并初始化每个 symbol 的状态。
- `MovingAverageSignalEngine.update`: 收到 bar 后更新 close 历史，计算 short MA、long MA、slope 和 gap；满足确认条件后只发出一次 `ENTER_LONG`。

### 扫描和战术入场

- `TacticalRiskConfig`: quote age、spread、止盈止损和 quantity。
- `StrategyPlan`: 是否批准入场，以及可选 `TradeProposal`。
- `StrategyScannerConfig`: rotation batch、bar interval、历史容量、均线配置和 tactical risk。
- `StrategyScanEvent.as_dict`: 把一次扫描事件序列化。
- `RotatingStrategyScanner.__init__`: 组合 quote source、rotating pool、quote cache、bar builder、bar history、signal engine 和 tactical strategy。
- `RotatingStrategyScanner.scan_once`: 获取一批 symbols 的 quotes，更新 cache/bar，生成 signal 和 strategy plan。
- `RotatingStrategyScanner._record_bar`: 去重或追加 bar history。
- `TacticalLongStrategy.plan_entry`: 对 `ENTER_LONG` 做 approved pool、quote freshness 和 spread 检查，生成 BUY proposal、stop loss 和 profit target。
- `_average_available`: 计算可用指标均值。
- `_lower_is_better`: 把越低越好的指标映射到 0-100 分。
- `_higher_is_better`: 把越高越好的指标映射到 0-100 分。

## 当前健康观察

最近 `reports/autonomous_agent/latest.json` 显示：

- Trading API health gate 最近可达，状态为 TRADE_LOCK，TWS ready。
- autonomous agent 进程仍在运行。
- 最新 cycle 的 `quote_count` 为 0。
- IBKR read-only quote errors 集中为 `No market data during competing live session`。
- 最近策略运行 `submitted_count` 为 0，且 `returned_symbols` 为空。

这说明当前主要问题不是双均线策略是否存在，而是行情读取层存在会话竞争或行情通道占用。策略在没有 fresh quotes 时不会产生 BUY/SELL，符合当前安全设计。

## 下一步策略建议

1. 先修复 read-only 行情会话竞争：确保只保留一个 live market data session，或把 agent 切到 delayed/frozen market data 模式做休市/测试扫描。
2. 把 `latest.json`、pool strategy report 和 PnL CSV 的数据新鲜度写入日报，让日报明确区分“API ready”和“行情可用”。
3. 保持当前双均线策略 paper-only，不建议在行情 quote_count 为 0 时调大风险参数。
4. 增加策略 report 汇总脚本，统计最近 24 小时的 HOLD 原因、quote errors、BUY/SELL 信号数和 Trading API rejection 原因。
5. 后续新增策略时，沿用“独立模块 -> 单元测试 -> 模拟行情 -> validate -> paper”的顺序。
