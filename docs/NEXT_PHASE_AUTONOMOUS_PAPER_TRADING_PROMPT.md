# Next Phase Prompt: Autonomous IBKR Paper Trading Runtime

你现在继续担任我的量化交易项目总工程师、投研助手、IBKR/TWS 自动化架构师。请基于当前项目 `/Users/nbhsbgnb/Documents/New project` 的真实状态继续推进，不要重做已经完成的部分。

## 当前已完成事实

- 已完成真实 IBKR paper 端到端链路。
- Trading API / TWS 已在 paper account `DUQ503649` 上通过。
- 已提交一笔 paper order：`AAPL BUY 1 @ 311.84`。
- TWS 回读到 order id `46`，状态 `Submitted`，remaining `1`。
- reconciliation 已完成：gate、audit DB、TWS readback、P&L snapshot 全部 pass。
- `reports/project_completion_audit.md` 当前为 `complete`。
- 全量测试通过：`155 tests OK`。
- live trading 仍默认禁用，下一阶段仍只允许 paper trading。

## 目标

把当前项目升级为可以长期运行的 IBKR paper trading 自动化系统，最大化利用美股盘前、盘中、盘后、overnight 可交易窗口，但每个时段必须有不同的策略允许范围、订单类型、风控阈值、流动性限制、监控与停止条件。

不要直接进入 live trading。所有真实资金交易必须继续保持禁用。

用户明确允许 paper 账户长期自动下单。不要把系统停留在“一单 smoke test”阶段；目标是让 paper runtime 持续流动起来，通过真实 paper 运行暴露行情、订单、成交、撤单、P&L、TWS 断线等问题。安全重点应放在 paper-only、止损、限价、仓位上限、日亏上限、重复下单防护、异常停机和可回放审计，而不是默认只允许每个 session 一单。

## 必须先完整评估

1. 当前项目哪些模块已经适合长期自动 paper 运行：
   - market data / IBKR quote
   - strategy modules
   - risk
   - execution
   - audit DB
   - runbook / evidence bundle
   - reconciliation
   - status page

2. 哪些模块还只是 smoke test，不适合长期无人值守：
   - 策略质量
   - 持仓管理
   - 成交后管理
   - 撤单/改单
   - 盘前盘后流动性过滤
   - TWS 断线恢复
   - alerting
   - 日志轮转
   - 自动开关与 kill switch

3. 请明确回答：当前“所有策略模块”是否已经全部生产化运行？如果没有，列出每个策略模块的成熟度：
   - dual moving average
   - grid / 做T
   - z-score mean reversion
   - conservative trend
   - LightGBM-style baseline
   - VWAP/TWAP execution
   - ML / regime / portfolio research modules

## 请上网核对并引用主流方案

请检索并优先参考：

- IBKR 官方文档：
  - US stocks regular trading hours
  - outside RTH / Fill Outside RTH / `outsideRth`
  - overnight trading support
  - TWS API order fields
- QuantConnect / LEAN：
  - paper trading
  - live trading architecture
  - scheduled events / market hours
- 自动化交易风控最佳实践：
  - pre-trade risk controls
  - kill switch
  - post-trade reconciliation
  - monitoring and alerting
- 社区主流实践：
  - IBKR TWS / Gateway 长期运行的问题
  - TWS 重连、session、2FA、断线处理
  - paper vs live fill 差异

只使用公开资料，不要臆测。

## 设计一个交易时段细节目录

请在项目中创建或整理一个目录，例如：

```text
docs/trading_sessions/
```

至少包含：

```text
docs/trading_sessions/README.md
docs/trading_sessions/01_calendar_and_timezones.md
docs/trading_sessions/02_overnight_session.md
docs/trading_sessions/03_premarket_session.md
docs/trading_sessions/04_regular_session.md
docs/trading_sessions/05_afterhours_session.md
docs/trading_sessions/06_risk_by_session.md
docs/trading_sessions/07_order_types_by_session.md
docs/trading_sessions/08_monitoring_and_recovery.md
docs/trading_sessions/09_autonomous_runtime_runbook.md
```

每个时段要明确：

- US/Eastern 时间
- Europe/Berlin 对应时间
- 是否允许自动交易
- 是否允许新开仓
- 是否允许平仓
- 是否允许撤单/改单
- 是否允许 market order
- 是否只允许 limit order
- 是否允许 `outsideRth=True`
- 最大 spread bps
- 最大 order value
- 最大 open orders
- 最大持仓数量
- 最小成交量/quote 更新要求
- 可运行策略
- 禁止运行策略
- 退出/暂停条件
- 需要记录的证据

## 建立 session-aware 自动交易状态机

请实现或设计以下模块，优先做可测试的最小闭环：

```text
trading/session_calendar.py
trading/session_policy.py
trading/autonomous_runtime.py
scripts/run_autonomous_paper_runtime.py
reports/autonomous_runtime_status.json
reports/autonomous_runtime_events.jsonl
```

状态机至少包含：

- `OFFLINE`
- `PRECHECK`
- `OVERNIGHT_PAPER`
- `PREMARKET_PAPER`
- `REGULAR_PAPER`
- `AFTERHOURS_PAPER`
- `RECONCILE`
- `PAUSED`
- `ERROR`
- `KILL_SWITCH`

## 每个时段的建议默认规则

请以保守 paper 默认值实现，并把配置放进 `config/`：

### Overnight

- 允许 paper 自动交易，但必须更严格。
- 默认只允许 allowlisted 高流动性股票/ETF。
- 只允许 limit order 或带保护腿的 bracket/attached stop 结构。
- 更严格 spread bps。
- 更小 order value。
- 不允许高频轮询。
- 必须有止损或最大不利偏离退出规则。
- 优先监控已有订单、撤单、风控；允许新开仓，但必须受 session policy 控制。

### Premarket

- 只允许高流动性 ETF / 大盘股。
- 只允许 limit order 或 bracket limit entry + protective stop。
- 不允许追价。
- 不允许 ML 激进信号直接下单。
- 允许持续 paper 自动交易，不限制为一笔 smoke-test order。
- 每个 symbol、每个 strategy、每个 session 都必须有 max position、max open orders、cooldown、stop-loss。

### Regular

- 允许 P0 策略 paper 运行。
- 允许双均线、grid、mean reversion、conservative trend、ML baseline，但必须逐个经过 risk gate。
- 允许更正常的 quote sampling。
- 必须有订单生命周期管理。
- 优先支持 bracket-style order plan：limit entry + stop loss + optional take profit。
- 没有止损或明确退出规则的策略不得自动开新仓。

### Afterhours

- 只允许 limit order 或带保护退出规则的 bracket/attached stop 结构。
- 更严格 spread / volume / quote freshness。
- 倾向平仓、减仓、撤单，但允许持续 paper 新开仓来暴露真实问题。
- 新开仓必须使用更小仓位、更宽容的成交等待、更严格 stale-order cancellation。

## 自动运行机制

请设计并实现长期运行模式：

- 单进程 loop 或 supervisor-friendly CLI。
- 每个 cycle：
  1. health check
  2. session detection
  3. quote capture
  4. strategy scan
  5. risk validation
  6. validate-only
  7. paper submit if enabled and policy allows
  8. TWS readback
  9. P&L snapshot
  10. reconciliation
  11. status write
  12. alert if abnormal

- 默认必须是 `paper_only=True`。
- live trading 必须继续 blocked。
- 自动 paper submit 必须有配置开关，但允许长期打开，例如：

```text
AUTONOMOUS_MAX_ORDERS_PER_SESSION=20
AUTONOMOUS_MAX_ORDERS_PER_SYMBOL=3
AUTONOMOUS_MAX_OPEN_ORDERS=5
AUTONOMOUS_MAX_ORDER_VALUE=400
AUTONOMOUS_MAX_POSITION_PER_SYMBOL=5
AUTONOMOUS_DAILY_LOSS_LIMIT=100
AUTONOMOUS_REQUIRE_PROTECTIVE_STOP=true
AUTONOMOUS_REQUIRE_LIMIT_ENTRY=true
AUTONOMOUS_REQUIRE_PRE_SUBMIT_REVIEW=false
```

说明：`TRADE_LOCK` + `TRADING_MODE=PAPER` 就是自动 paper 下单模式。`AUTONOMOUS_REQUIRE_PRE_SUBMIT_REVIEW=false` 只适用于长期 paper runtime；真实资金 live 必须继续禁用，且未来开启 live 时必须重新要求人工确认、独立 live 风控、独立凭证、独立 kill switch。

## 订单生命周期管理

请补齐：

- open order tracking
- stale order cancellation policy
- submitted / presubmitted / filled / partially filled / cancelled / rejected 状态处理
- order_ref / idempotency_key 对齐
- audit DB 与 TWS readback 对齐
- 每轮只允许有限订单数
- 如果已有 open order，不是简单跳过整个阶段；应按 symbol/strategy/session 判断：
  - 同 symbol 同 strategy 同方向 open order 达到上限则不再追加。
  - 允许其他 symbol 或其他 strategy 在限额内继续 paper。
  - stale order 到期后自动撤单或重定价。
  - 部分成交后更新目标仓位和保护止损。
  - 成交后必须确认 protective stop / exit rule 已存在或可执行。

## 止损、限价与保护订单

必须实现或设计：

- 所有自动 paper 新开仓默认必须是 limit entry。
- 所有自动 paper 新开仓必须带止损、bracket stop、或可执行的 synthetic stop 监控。
- 每个策略必须声明：
  - entry limit price rule
  - stop loss price rule
  - take profit rule, optional
  - max holding time
  - max adverse excursion
  - stale quote timeout
  - stale order timeout
- 如果 IBKR/TWS 不支持某个时段的 attached stop 行为，则必须用 runtime synthetic stop 监控，并在文档里明确风险。
- 盘前/盘后/overnight 禁止 market entry；退出可以优先 limit/stop-limit，极端异常只允许 paper emergency flatten，并且必须记录。

## 监控与恢复

请设计：

- TWS disconnect detection
- API health failure handling
- stale quote detection
- duplicate order prevention
- kill switch file / env / API
- log rotation
- event JSONL
- daily report
- optional Feishu/Telegram/email alert

## 测试要求

必须新增测试覆盖：

- session classification by US/Eastern and Europe/Berlin
- session policy selection
- outsideRth only in allowed sessions
- no market orders outside RTH
- stale quote blocks order
- open order blocks duplicate submit
- max orders per session
- max orders per symbol
- protective stop required before new entry
- limit entry required before new entry
- stale order cancellation
- partial fill updates position and protection
- kill switch blocks runtime
- TWS health failure pauses runtime
- reconciliation required after submission
- live order remains disabled

跑全量测试，保持通过。

## 交付物

最终请交付：

- 当前状态实话总结：已跑通什么、没跑通什么。
- 主流方案调研结论和引用链接。
- `docs/trading_sessions/` 细节目录。
- session-aware runtime 设计与最小实现。
- 配置文件与默认参数。
- CLI 启动方式。
- 如何让它长期跑，例如 macOS `launchd` / `tmux` / `supervisor` 的方案比较。
- 风险与不能保证事项。
- 后续从 paper 走向 live 前必须补的清单。

## 安全限制

- 默认只允许 paper trading。
- 禁止 live trading。
- 不承诺收益。
- 不把 paper fill 当成 live fill。
- 不允许无限下单。
- 不允许无风控下单。
- 不允许盘前盘后 market order。
- 不允许 TWS/API 不健康时下单。
- 不允许 quote stale 时下单。
- 不允许已有未处理 open order 时重复下单。
