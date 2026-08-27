# Audit Model

The audit system has two jobs:

1. Prove what happened in the trading workflow.
2. Measure whether the strategy is better than simple benchmarks such as QQQ or
   Nasdaq.

These jobs should be related but not mixed into one table too early.

## Execution Audit

Execution audit answers:

- What request arrived?
- Who or what submitted it?
- Which workflow step accepted or rejected it?
- Did risk pass?
- Was the manual lock open?
- Was TWS ready?
- Was an idempotency key reserved?
- Did the order reach TWS?
- What did TWS acknowledge?
- Where did the workflow stop if it failed?

Request ledger fields:

- `idempotency_key`
- `created_at`
- `mode`
- `status`
- `proposal_json`
- `details`

The reconciliation schema now also stores:

- append-only `order_events` for request and broker observations
- `broker_orders` with raw and canonical lifecycle states
- idempotent `executions` keyed by IBKR execution ID
- `reconciliation_runs` with unknown-active-order counts and diagnostics

Unknown active TWS orders that cannot be joined through
`orderRef=idempotency_key` create a fail-closed submission block. TWS/IBKR is
the broker-truth source; SQLite is the durable local history and recovery
ledger.

Recommended next fields:

- `source`
- `workflow_step`
- `workflow_step_message`
- `symbol`
- `side`
- `quantity`
- `limit_price`
- `stop_price`
- `submitted_at`
- `acknowledged_at`
- `failed_at`
- `error_type`
- `error_message`
- `timings_json`

The execution audit should remain append-friendly and failure-friendly. A failed
order attempt is still valuable data.

## Performance Audit

Performance audit answers:

- Current account value.
- Cash.
- Positions.
- Realized P&L.
- Unrealized P&L.
- Fees and commissions.
- Daily return.
- Drawdown.
- Strategy return versus QQQ/Nasdaq.
- Strategy return versus a pure-AI baseline.

Recommended snapshots:

- `account_snapshot`
- `position_snapshot`
- `order_fill`
- `daily_performance`
- `benchmark_snapshot`
- `model_signal_snapshot`

## Benchmark Comparison

The first benchmark should be QQQ because it is tradable and closely represents
large Nasdaq technology exposure. Nasdaq Composite or Nasdaq-100 index levels can
also be stored for reference, but QQQ is easier for practical comparison.

Daily comparison fields:

- `date`
- `strategy_equity`
- `strategy_daily_return`
- `strategy_cumulative_return`
- `qqq_close`
- `qqq_daily_return`
- `qqq_cumulative_return`
- `nasdaq_level`
- `nasdaq_daily_return`
- `alpha_vs_qqq`
- `max_drawdown`
- `realized_pnl`
- `unrealized_pnl`
- `fees`

The question is not only "did the account make money?" The better question is:

```text
Did the strategy beat QQQ after risk, drawdown, and costs?
```

## Pure-AI Baseline

The system should eventually compare the controlled strategy with a pure-AI
baseline. This baseline is for research only and must not get execution rights.

Pure-AI baseline rules:

- It receives the same market and filing data.
- It does not receive preset factor rules or handcrafted strategy filters.
- It produces hypothetical decisions and position sizes.
- It is recorded as paper research, not as executable orders.
- It is compared beside QQQ/Nasdaq and the controlled strategy.

Useful fields:

- `model_name`
- `prompt_version`
- `input_window`
- `decision_timestamp`
- `symbol`
- `hypothetical_side`
- `hypothetical_weight`
- `hypothetical_entry_price`
- `hypothetical_exit_price`
- `hypothetical_return`
- `reasoning_summary`
- `risk_flags`

This creates a fair scoreboard:

```text
controlled strategy vs pure-AI baseline vs QQQ/Nasdaq
```

## Timing Audit

Speed matters. Every stage from first signal to order acknowledgement should be
measured.

Required timing groups:

- data ingestion latency
- research normalization latency
- OpenClaw decision latency
- Python API latency
- risk gate latency
- lock/token check latency
- TWS preflight latency
- audit reserve latency
- broker submit latency
- TWS acknowledgement latency
- final audit update latency

The first optimization target is not guessing which stage is slow. The first
target is making every stage measurable.

Fast trade check mode should separate pre-window research latency from
post-window execution latency. A slow research cycle is acceptable before the
window is locked. After the window is locked, the measured path should be limited
to:

- OpenClaw client startup and request build
- Python API request latency
- risk gate
- lock and token check
- TWS preflight
- audit reserve
- broker submit
- TWS acknowledgement
- audit update

Report generation, attachment sending, long explanations, and deep account
queries should be measured as post-trade reporting, not as execution latency.

## Mathematical Model Extension

Future models should be added as independent signal producers. They should write
scores and explanations, not place orders.

Candidate model families:

- momentum: relative strength, moving-average trend, breakout strength
- mean reversion: z-score, Bollinger bands, short-term reversal
- volatility: ATR, realized volatility, volatility targeting
- factor: value, quality, growth, profitability, leverage, revision momentum
- event-driven: earnings surprise, guidance change, 8-K event classification
- risk: beta to QQQ, drawdown, correlation, concentration
- portfolio: mean-variance, risk parity, Kelly-inspired sizing caps

Each model output should include:

- `model_id`
- `model_version`
- `symbol`
- `timestamp`
- `score`
- `confidence`
- `horizon`
- `inputs_used`
- `explanation`
- `risk_flags`

The decision layer can combine model outputs later. The execution layer should
only see a final proposal after all controls pass.

## SQLite And PostgreSQL

SQLite is a real database. It is embedded in one local file and is excellent for
local audit, idempotency, and a single-machine gateway.

PostgreSQL has a moderate setup cost:

- install or run a PostgreSQL service
- create database and user
- add a Python driver
- add migrations
- manage backups
- manage credentials
- think about network access and firewall rules

The code migration is not hard if the storage layer is kept clean. The operating
discipline is the real threshold. For this project, the low-risk path is:

1. Keep execution audit in SQLite now.
2. Add PostgreSQL later for research data and performance history.
3. Mirror SQLite execution events into PostgreSQL for reporting.
4. Move execution idempotency only after PostgreSQL has proven stable.
