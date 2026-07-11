# OpenClaw / IBKR Paper 自动交易项目交接手册

版权声明：Copyright (c) 2026 der. All rights reserved. 本项目为专有和保密项目，仅供授权阅读和协作。未经 der 事先书面许可，任何人不得复制、转发、公开发布、修改、商用、再授权或分享给第三方。完整条款见根目录 `LICENSE`。

这份手册是给新朋友快速上手用的。它不假设读者已经熟悉项目，只讲这个项目是什么、为什么这样设计、每个模块负责什么、以后继续写代码或文档应该从哪里开始。

## 一句话总结

这是一个本地运行的美股 IBKR paper trading 自动化系统。它把 AI 研究、股票池筛选、实时行情、策略判断、风控审核、下单执行、审计记录和报告展示分成不同模块，让系统可以自动观察市场和生成交易动作，但所有 paper order 都必须经过本地 Python Trading API 的安全门。

核心流程是：

```text
行情 / 新闻 / 财报
-> AI 或规则生成候选
-> 股票池筛选
-> 策略模块判断 BUY / SELL / HOLD
-> Trading API 风控
-> IBKR TWS paper
-> SQLite 审计和 reports 报告
```

## 项目特点和优势

1. 安全边界清楚  
   Discord、OpenClaw、研究模块、Python API 和 IBKR TWS 被分开。AI 可以分析和提建议，但不能直接连接 IBKR，也不能绕过本地风控。

2. 默认只做 paper trading  
   当前项目没有安全启用 live trading 的路径。所有自动化目标都是 IBKR paper account。

3. 风控优先  
   下单前要经过 `STOP / DEV_LOCK / TRADE_LOCK` 状态、daily trade token、TWS readiness、symbol allowlist、最大数量、最大订单金额、最大风险、行情新鲜度、spread、持仓和亏损限制。

4. 模块化，容易继续扩展  
   行情源、股票池、策略、风控、执行、审计、报告都相对独立。以后新增策略时，不需要重写整个系统。

5. 可审计  
   每次请求、失败、拒绝、提交、TWS 返回和关键耗时都会写入本地审计或报告文件，方便复盘。

6. 有模拟路径  
   可以用 simulated quote、delayed quote、validate mode 先测试策略，不需要一上来连接真实 TWS paper 下单。

7. 适合长期迭代  
   项目已经有大量测试、报告脚本和 runbook。后续可以一点点加 SEC 财报、新闻、事件风险、更多策略和绩效对比。

## 当前整体结构

### 1. 项目入口

主要文件：

- `README.md`
- `docs/PROJECT_MAP.md`
- `scripts/control_trading_mode.command`
- `api_service.py`

最重要的人工入口是：

```text
scripts/control_trading_mode.command
```

这个菜单控制交易模式：

```text
0 STOP                  停止 API、策略和 agent，清空 token
1 DEV_LOCK              开发检查模式，不能 transmit paper order
2 TRADE_LOCK            生成 daily token，允许 paper trading 前置条件
3 HEALTH                查看 API / TWS / token / account 状态
4 AUTO_VALIDATE_SEQ     自动验证订单，不进 TWS
5 AUTO_STAGE_SEQ        进 TWS，但 transmit=False
6 AUTO_PAPER_SEQ        一次性发送 paper order
7 POOL_STRATEGY_PAPER   前台跑 pool strategy
8 POOL_STRATEGY_BG      后台跑 pool strategy
9 AUTONOMOUS_AGENT_BG   当前最完整的后台自动化 agent
```

日常建议：

```text
先选 2 TRADE_LOCK，并选择后台启动 API
再选 9 AUTONOMOUS_AGENT_BG
```

开发或检查时：

```text
选 1 DEV_LOCK
```

安全退出时：

```text
选 0 STOP
```

### 2. Trading API 层

主要文件：

- `api_service.py`
- `trading/service.py`
- `trading/risk.py`
- `trading/config.py`
- `trading/workflow.py`
- `trading/models.py`

这一层是所有下单请求的门卫。OpenClaw、策略模块或脚本不能直接下单，必须调用 API。

常见 endpoint：

```text
GET  /health
GET  /v1/orders/audit
POST /v1/orders/validate/limit
POST /v1/orders/stage/limit
POST /v1/orders/paper/limit
```

简单理解：

- `validate`：只检查，不进 TWS。
- `stage`：发到 TWS，但不 transmit。
- `paper`：发到 TWS paper，并 transmit。

### 3. IBKR / TWS 连接层

主要文件：

- `trading/tws_paper.py`
- `trading/ibkr_readonly.py`
- `trading/ibkr_streaming.py`
- `scripts/check_ibkr_quotes.py`
- `scripts/diagnose_market_data_channels.py`

分两种连接：

1. Read-only 行情和账户读取  
   用于报价、position、account、PnL、order 状态，不负责下单。

2. Paper execution adapter  
   只在 Trading API 风控全部通过后，才向 TWS paper 发送订单。

TWS 默认配置：

```text
host: 127.0.0.1
paper port: 7497
```

### 4. 股票池 universe

主要文件：

- `data/us_equity_universe.csv`
- `data/security_master.csv`
- `trading/universe.py`
- `trading/security_master.py`
- `VALUE_POOL.md`

股票池负责回答：

```text
哪些股票值得被策略观察？
```

它不是买入信号。它只是先过滤掉质量差、流动性差、估值或基本面不合适的标的。

当前会考虑：

- symbol 是否 enabled
- sector / tags
- average volume
- PE / forward PE / PEG
- margin / ROIC
- debt
- growth
- free cash flow
- analyst revision
- gateway allowlist

### 5. 行情和 bar 构建

主要文件：

- `trading/market_data.py`
- `DATA_FEEDS.md`

统一行情对象是：

```text
Quote(symbol, last, bid, ask, close, volume, timestamp, source)
```

这样 Stooq、Yahoo、IBKR 或未来数据源都可以接入同一套策略逻辑。

当前行情路径：

```text
QuoteSource
-> InMemoryQuoteCache
-> BarBuilder
-> SymbolRingBuffers
-> strategy module
```

重点：

- 不为每只股票开一个长期通道。
- 使用 rotating symbol pool 分批扫描。
- cache 保存每个 symbol 最新报价。
- ring buffer 保存有限 bar 历史，避免内存无限增长。

### 6. 策略模块

主要文件：

- `trading/strategy_modules.py`
- `trading/strategy.py`
- `scripts/run_pool_strategy_module.py`
- `docs/STRATEGY_MODULES.md`
- `docs/STRATEGY_FLOW.md`

当前主策略是：

```text
classic_conservative_trend
```

它是一个保守的 long-only 双均线趋势策略。

BUY 大致要求：

```text
symbol 在 approved pool
quote 新鲜
spread 不太宽
不在 cooldown
bar 历史足够
fast SMA > slow SMA
last price > slow SMA
```

SELL 大致要求：

```text
达到小止盈
或触发小止损
或 fast SMA 跌破 slow SMA
```

策略本身不直接连接 broker。它只生成结构化订单意图，再交给 Trading API。

### 7. Autonomous Agent

主要文件：

- `scripts/run_autonomous_trading_agent.py`
- `trading/autonomous_runtime.py`
- `reports/autonomous_agent/latest.json`
- `reports/autonomous_agent/cycles.jsonl`
- `logs/autonomous_agent.log`

这是当前最完整的自动化入口，对应菜单：

```text
9) AUTONOMOUS_AGENT_BG
```

agent 每轮会做：

1. 读取 Trading API `/health`。
2. 检查 `TRADE_LOCK`、TWS、token、account。
3. 刷新 universe。
4. 读取一批或全池 IBKR 行情。
5. 计算 movers、spread、quote age。
6. 生成 research tasks。
7. 处理候选 inbox。
8. 按周期调用 pool strategy。
9. 写入 latest 和 cycles 报告。

当前项目里最值得持续观察的文件：

```text
reports/autonomous_agent/latest.json
reports/autonomous_agent/cycles.jsonl
logs/autonomous_agent.log
```

### 8. OpenClaw / AI 研究管线

主要文件：

- `openclaw/openclaw_trading_client.py`
- `openclaw/SKILL.md`
- `docs/RESEARCH_CANDIDATE_PIPELINE.md`
- `trading/candidate_research.py`
- `scripts/review_candidate_report.py`
- `scripts/approve_candidate_to_universe.py`

设计目标：

```text
OpenClaw / Gemini 找候选
-> 抓财报、新闻、行情
-> 生成 bull / bear / catalyst / risk
-> Python 验证基本面和 IBKR contract
-> 写 candidate report
-> 人工或规则批准进入 universe
-> 策略模块才可以观察和交易
```

关键安全原则：

- AI 可以提候选。
- AI 可以写理由。
- AI 不能直接写入 universe。
- AI 不能直接下单。
- Python hard audit 是入池硬门。
- Trading API 是下单硬门。

### 9. 风控模块

主要文件：

- `trading/risk.py`
- `trading/session_policy.py`
- `trading/event_risk_control.py`
- `trading/position_guard.py`
- `trading/position_protection.py`
- `trading/gap_risk_manager.py`
- `SECURITY_MODEL.md`
- `TRADING_LOCK.md`

项目里的风控分多层：

```text
锁状态
-> daily token
-> API key
-> TWS readiness
-> symbol allowlist
-> order size
-> order value
-> stop risk
-> quote freshness
-> spread
-> session policy
-> portfolio limits
-> audit ledger
```

最重要的规则：

- kill switch 永远优先。
- `STOP` 下不能交易。
- `DEV_LOCK` 下不能 transmit paper order。
- `TRADE_LOCK` 才允许 paper，但仍要经过所有风控。
- live trading 当前没有安全启用路径。

### 10. 执行审计和报告

主要文件和目录：

- `trading/audit.py`
- `trading_audit.sqlite3`
- `AUDIT_MODEL.md`
- `reports/`
- `dashboard/`
- `scripts/build_paper_trial_evidence_bundle.py`
- `scripts/build_paper_session_runbook.py`
- `scripts/build_paper_session_status_page.py`

审计回答：

```text
请求是什么？
谁提交的？
在哪一步通过或失败？
风控是否通过？
TWS 是否 ready？
订单是否到达 TWS？
失败原因是什么？
耗时在哪里？
```

注意：

- 不要手动改 `trading_audit.sqlite3`。
- 不要随便删除 `reports/*.jsonl`。
- 报告可以归档，但最好保留最近运行证据。

### 11. Dashboard 和状态页

主要文件：

- `trading/dashboard.py`
- `scripts/serve_live_dashboard.py`
- `scripts/generate_strategy_dashboard.py`
- `scripts/refresh_strategy_dashboard.py`
- `dashboard/pool_strategy_dashboard.html`

Dashboard 用来快速看：

- 当前 pool strategy 状态
- 行情是否正常
- 最近是否有 BUY / SELL / HOLD
- 策略报告和运行结果

### 12. Research / 报告生成脚本

主要目录：

- `research/`
- `scripts/`
- `reports/`

`research/` 里很多文件是报告生成和验证逻辑。  
`scripts/` 里是命令行入口。  
`reports/` 是运行结果。

常见脚本：

```text
scripts/build_strategy_catalog.py
scripts/build_paper_readiness_report.py
scripts/build_quote_quality_report.py
scripts/build_paper_trial_preflight_checklist.py
scripts/refresh_paper_trial_reports.py
scripts/run_strategy_simulation.py
scripts/run_pool_strategy_module.py
```

### 13. 测试

主要目录：

- `tests/`

运行全部测试：

```bash
.venv313/bin/python -m unittest discover -v
```

新增模块时建议顺序：

```text
先写小模块
再写单元测试
再用 simulated quote 跑通
再 validate
最后才考虑 paper
```

## 给新朋友的上手路线

### 第一步：先读这几个文件

```text
README.md
docs/PROJECT_MAP.md
docs/STRATEGY_FLOW.md
docs/STRATEGY_MODULES.md
SECURITY_MODEL.md
VALUE_POOL.md
DATA_FEEDS.md
```

### 第二步：先不要下单，只跑模拟

```bash
.venv313/bin/python scripts/run_strategy_simulation.py --symbols AAPL,MSFT --steps 12
```

或：

```bash
.venv313/bin/python scripts/run_pool_strategy_module.py --mode validate --source simulated-scenario --symbols AAPL,MSFT,AMD,INTC,KO,PFE,T,F --steps 18 --batch-size 4
```

### 第三步：看当前 agent 状态

```text
reports/autonomous_agent/latest.json
reports/autonomous_agent/cycles.jsonl
logs/autonomous_agent.log
```

### 第四步：如果要接 TWS，只先做 read-only 检查

```bash
.venv313/bin/python scripts/check_ibkr_quotes.py --symbols AAPL,MSFT,QQQ
```

如果实时行情不通，可以试 delayed：

```bash
.venv313/bin/python scripts/check_ibkr_quotes.py --symbols AAPL,MSFT,QQQ --market-data-type 3
```

### 第五步：真的要 paper 前，先看 health

使用：

```text
scripts/control_trading_mode.command
```

先选：

```text
2 TRADE_LOCK
```

再选：

```text
3 HEALTH
```

只有 health、TWS、token、paper account 都正常时，才考虑后续 paper。

## 常见修改位置

### 想改安全限制

看：

```text
trading/risk.py
trading/config.py
trading/service.py
SECURITY_MODEL.md
```

### 想改策略逻辑

看：

```text
trading/strategy_modules.py
trading/strategy.py
scripts/run_pool_strategy_module.py
docs/STRATEGY_MODULES.md
```

### 想改股票池筛选

看：

```text
data/us_equity_universe.csv
trading/universe.py
VALUE_POOL.md
```

### 想改行情源

看：

```text
trading/market_data.py
trading/ibkr_readonly.py
DATA_FEEDS.md
```

### 想改 agent 主循环

看：

```text
scripts/run_autonomous_trading_agent.py
trading/autonomous_runtime.py
```

### 想改报告或 dashboard

看：

```text
research/
scripts/build_*.py
trading/dashboard.py
dashboard/
reports/
```

### 想接入 AI 研究候选

看：

```text
docs/RESEARCH_CANDIDATE_PIPELINE.md
trading/candidate_research.py
scripts/review_candidate_report.py
scripts/approve_candidate_to_universe.py
openclaw/
```

## 当前状态提醒

根据 `reports/autonomous_agent/latest.json`，最近一次状态时间是 `2026-07-11T17:10:09+00:00`。当时 agent 正在运行，但因为周末市场关闭，状态里有：

```text
blocked_reason: market_weekend_no_live_bid_ask_expected
```

这不是策略本身坏了，而是没有正常 live bid/ask。朋友接手时不要在周末行情缺失时急着调大风险参数。

## 继续开发建议

1. 先保证 read-only 行情稳定。  
   没有 fresh quotes 时，策略不应该下单。

2. 给每个新策略加独立测试。  
   新策略先模拟，再 validate，再 paper。

3. 完善 research worker。  
   下一阶段重点是 SEC、新闻、earnings calendar 和 Gemini/OpenClaw 候选报告。

4. 增加策略报告汇总。  
   统计最近 24 小时 HOLD 原因、quote errors、BUY/SELL 信号数、API rejection 原因。

5. 做完整 paper 长测。  
   用 `cycles.jsonl`、strategy report、P&L、QQQ benchmark 来判断策略是否真的有价值。

6. 不要绕过 Trading API。  
   任何新功能都应该输出结构化 proposal 或 score，而不是直接连接 broker。

## 最重要的安全提醒

- 不要提交真实 secret。
- 不要手动改 daily trade token。
- 不要手动改 `trading_audit.sqlite3`。
- 不要让 AI 或外部服务直连 TWS。
- 不要在 `DEV_LOCK` 之外随便测试 stage / paper。
- 不要把 bracket parent 简单改成 `transmit=True`。
- 遇到行情缺失，先修数据通道，不要先放松风控。

## 项目的精神

这个项目不是“让 AI 随便炒股”。它更像一个可审计的自动交易实验室：

```text
AI 负责发现和解释
策略负责产生信号
Python 负责硬审核
TWS 只接受通过安全门的 paper order
报告负责复盘和改进
```

朋友接手时，最好的方式是小步推进：每次只新增一个数据字段、一个规则、一个策略模块或一个报告指标，并且配测试和模拟结果。这样项目会越写越清楚，而不是越写越危险。
