# OpenClaw / IBKR Paper 自动投资系统说明

## 当前目标

项目正在建设一个模块化、美股大池子、IBKR paper 自动交易系统。核心目标不是一次性生成固定股票池，而是在 `TRADE_LOCK` 运行后，让 AI supervisor 持续工作：

```text
实时行情监控 -> AI/agent 研究任务 -> 候选报告 -> Python 硬审核 -> 动态 universe -> 策略模块交易 -> 风控审计
```

## 当前运行状态

截至本次检查：

- Mac Python Trading API 正在运行。
- `TRADE_LOCK` 已启用。
- TWS paper 已连接，`ready_for_orders=true`。
- Paper account: `DUQ503649`。
- Autonomous agent 已启动。
- agent 已进入第 8 个 cycle。
- 当前每轮监控 60 只美股/ETF。
- IBKR real-time quote 返回正常，最近一轮 `quote_count=60`。
- 策略模块已被 autonomous agent 触发过。
- 最近策略运行 `submitted_count=0`，表示当前没有满足全部策略/风控条件的下单。

运行状态文件：

```text
reports/autonomous_agent/latest.json
reports/autonomous_agent/cycles.jsonl
logs/autonomous_agent.log
```

## 已实现模块

### 1. 大池子 universe

基础 universe 文件：

```text
data/us_equity_universe.csv
```

它包含美股大盘/高流动性股票与 ETF，字段包括：

- symbol
- name
- exchange
- sector
- tags
- average volume
- PE / forward PE / PEG
- debt / growth / margin / ROIC
- free cash flow / earnings / analyst revision flags

当前 universe 不是固定不变的。后续可以通过 candidate report 动态审批入池。

### 2. IBKR real-time 行情

已订阅并验证：

- NYSE Network A / CTA / L1
- Network B / ARCA / BATS / Regional / L1
- NASDAQ Network C / UTP / L1

系统使用 IBKR TWS paper API `7497` 读取行情。只读行情模块不会下单。

并行行情读取方式：

- 每只股票使用唯一 `reqId`。
- TWS `clientId` 是 API 连接身份，不是每只股票一个。
- 当前实现使用有限 worker/clientId 分片请求全池，避免 TWS clientId 过多导致不稳定。

### 3. Autonomous Agent

入口：

```text
scripts/run_autonomous_trading_agent.py
```

菜单入口：

```text
scripts/control_trading_mode.command
9) AUTONOMOUS_AGENT_BG
```

agent 每个 cycle 会：

1. 读取 Trading API `/health`。
2. 确认 `TRADE_LOCK`、TWS readiness、allowed symbols。
3. 刷新 universe。
4. 全池读取 IBKR 实时行情。
5. 计算 intracycle movers、spread、volume、quote age。
6. 生成 research tasks。
7. 处理 OpenClaw/Gemini 候选草案 inbox。
8. 按周期触发策略模块。
9. 写入 `latest.json` 和 `cycles.jsonl`。

### 4. OpenClaw / Gemini 候选研究管线

设计目标：

```text
OpenClaw/Gemini 找方案
-> agent 抓财报、新闻、行情信息
-> LLM 预审，给出 bull/bear/catalyst/risk
-> Python 验证基本面、IBKR quote、TWS contract
-> 写 candidate report
-> 规则或人工批准进入 universe
-> 策略模块交易
```

新增文档：

```text
docs/RESEARCH_CANDIDATE_PIPELINE.md
```

核心模块：

```text
trading/candidate_research.py
scripts/review_candidate_report.py
scripts/approve_candidate_to_universe.py
```

安全边界：

- LLM 可以提出候选、解释理由、生成结构化报告。
- LLM 不能直接写入 universe。
- LLM 不能直接下单。
- Python hard audit 是入池前的硬门。
- Trading API risk gate 是下单前的硬门。

### 5. 策略模块

当前第一策略模块：

```text
classic_conservative_trend
```

位置：

```text
trading/strategy_modules.py
```

特点：

- long-only
- 小仓位 paper
- 快慢均线趋势确认
- 小盈利目标
- 小止损
- cooldown
- spread / quote freshness 检查
- portfolio risk gate

### 6. 风控层

当前风控包括：

- TRADE_LOCK / DEV_LOCK / STOP 状态机
- paper transmit token
- TWS readiness
- symbol allowlist
- max quantity
- max order value
- max risk per order
- max open positions
- max symbol market value
- max gross market value
- max daily loss
- max consecutive losses
- quote age
- spread
- audit ledger

STOP / DEV_LOCK 会停止后台 agent 和策略进程。

## 推荐运行方式

1. 打开并登录 TWS paper。
2. 确认 TWS API socket port `7497`。
3. 运行：

```text
scripts/control_trading_mode.command
```

4. 选择：

```text
2) TRADE_LOCK
```

并选择 background。

5. 再次运行菜单，选择：

```text
9) AUTONOMOUS_AGENT_BG
```

## 当前 v1 限制

- OpenClaw/Gemini research worker 还没有完全接入自动网页抓取和 Gemini API。
- 目前 agent 会生成 research tasks，并处理 candidate inbox。
- 后续需要增加真正的 research worker，把财报、新闻、SEC、Gemini 分析写成候选 JSON。
- 当前策略还是第一版保守趋势模块，需要通过 paper 长测继续调参。

## 下一步建议

1. 接入 OpenClaw/Gemini research worker。
2. 增加 SEC company facts / filings 拉取。
3. 增加新闻源和 earnings calendar。
4. 将 candidate inbox 自动产出候选报告。
5. 做 1-2 个完整交易日 paper 长测。
6. 根据 `cycles.jsonl`、strategy report、P&L 曲线调参。
