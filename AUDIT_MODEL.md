# Audit Model

The audit system has two jobs:

1. Prove what happened in the trading workflow.
2. Measure whether the strategy is better than the formal Nasdaq-100 Total
   Return benchmark, XNDX, while keeping QQQ as an auxiliary historical
   benchmark.

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

The reporting currency is USD. Keep original-currency source data and
FX-normalized views so each report can split local asset return, FX effect, and
total USD return.

TWR should be the primary strategy score. MWR/XIRR remain auxiliary
cash-flow-sensitive views.

Performance audit answers:

- Current account value.
- Cash.
- Positions.
- Realized P&L.
- Unrealized P&L.
- Fees and commissions.
- Local asset return.
- FX effect.
- Total USD return.
- Daily return.
- Drawdown.
- Strategy return versus XNDX/Nasdaq-100 Total Return.
- Strategy return versus QQQ as an auxiliary historical benchmark.
- Strategy return versus a pure-AI baseline.

Recommended snapshots:

- `account_snapshot`
- `position_snapshot`
- `order_fill`
- `daily_performance`
- `benchmark_snapshot`
- `model_signal_snapshot`

## Benchmark Comparison

The first benchmark should be XNDX, the Nasdaq-100 Total Return index, because
it is the formal total-return reference. QQQ should be retained as an
auxiliary historical benchmark and tradable proxy.

Daily comparison fields:

- `date`
- `strategy_equity`
- `strategy_daily_return`
- `strategy_cumulative_return`
- `xndx_close`
- `xndx_daily_return`
- `xndx_cumulative_return`
- `qqq_close`
- `qqq_daily_return`
- `qqq_cumulative_return`
- `local_asset_return`
- `fx_effect`
- `total_usd_return`
- `alpha_vs_xndx`
- `alpha_vs_qqq`
- `max_drawdown`
- `realized_pnl`
- `unrealized_pnl`
- `fees`

The question is not only "did the account make money?" The better question is:

```text
Did the strategy beat XNDX after risk, drawdown, and costs?
```

## Pure-AI Baseline

The system should eventually compare the controlled strategy with a pure-AI
baseline. This baseline is for research only and must not get execution rights.

Pure-AI baseline rules:

- It receives the same market and filing data.
- It does not receive preset factor rules or handcrafted strategy filters.
- It produces hypothetical decisions and position sizes.
- It is recorded as paper research, not as executable orders.
- It is compared beside XNDX/Nasdaq-100 Total Return, QQQ as a historical
  proxy, and the controlled strategy.

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
controlled strategy vs pure-AI baseline vs XNDX/QQQ
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

## Production migration identity review (2026-09-09)

1811 means distinct `(table, inferred key)` groups with multiple full-row fingerprints in the staging migration, not 1811 trades or SQLite constraint violations. The migration used declared primary key, then event_id, transition_id, canonical_pool_state.symbol, otherwise full-row fingerprint. Raw values and source provenance remain intact. The exact reproducer result and twelve raw candidate groups are in the maintenance run `engineering/conflict-summary.json`; classification of every group is in `engineering/conflict-classification.json`.

Observed classifications are candidates: 1338 event-history groups (A), 407 distinct-observation groups (B), 66 mutable state versions (A). Exact duplicate fingerprints are C at row ingestion, not these differing-payload groups. D remains possible wherever business lineage cannot be established; automatic classification does not approve reconciliation. No group mixes BUY/BOT with SELL/SLD. Adding side to every key would conceal reset counters and timestamp collisions, and is not justified.

Producer evidence: realtime_account_state_bus uses `state-{state_key}-{source_event_seq}`; state_timestamp_reconciler uses `reconcile-{state_version}`; state_bootstrap_manager uses seconds; ibkr_callback_bridge uses local callback counts. These identifiers can repeat across process runs. Stored `source_module=test` and `callback-audit-test-bus` also demonstrate historical test contamination, without proving an Agent caused it.

Identity contract for future schema migration (not retroactively applied):
- Execution: broker + environment + account + execId, retaining corrections and original provenance; side is a consistency attribute.
- Order: broker/environment/account + valid permId, otherwise client/session/orderId. Parent/child remain separate orders with explicit relationship.
- Intent: persisted UUID created before request; retries reuse it and recheck dependencies. UNKNOWN/non-idempotent outcomes must be reconciled, never automatically resent.
- Event occurrence: persisted occurrence UUID or source-instance/run scope + sequence. Timestamp, strategy, conId, action and source are event attributes; do not synthesize unsupported historical run IDs.
- Mutable state entity: environment/account/instrument conId/source scope, retaining observed version history. Symbol alone is insufficient across accounts/contracts.
- Full canonical row fingerprint removes exact duplicates only. Ambiguous identity/value differences retain all originals in quarantine; no last-write-wins without validated timestamps and semantics.

Conflict counts: {"account_state_events": 160, "bootstrap_state_events": 132, "callback_wiring_events": 342, "canonical_pool_state": 66, "event_risk_events": 8, "event_store": 6, "execution_state_events": 4, "ibkr_error_events": 17, "news_candidate_events": 8, "open_order_state_events": 4, "order_conflict_events": 1, "order_intent_events": 182, "pnl_state_events": 1, "position_state_events": 18, "quote_state_events": 311, "raw_news_events": 8, "router_decisions": 7, "structured_news_events": 8, "timestamp_reconciliation_events": 528}


Full raw examples: [12 conflict groups and all original candidate records](/Users/nbhsbgnb/.local/state/openclaw/maintenance/20260908T192959/engineering/conflict-summary.json). Source IDs identify immutable snapshots in backup-manifest.json; raw fields are not altered.

| Table / original key | Candidate count | Reason to retain |
|---|---:|---|
| account_state_events / `['account_state_events', 'state-account-1']` | 500 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
| bootstrap_state_events / `['bootstrap_state_events', 'bootstrap-account-1783772756']` | 3 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
| callback_wiring_events / `['callback_wiring_events', 'real-ibkr-accountDownloadEnd-180']` | 2 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
| canonical_pool_state / `['canonical_pool_state', 'AAPL']` | 2 | Mutable entity versions; retain history |
| event_risk_events / `['event_risk_events', 'auto-open-20260711105737-news-0']` | 2 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
| event_store / `['event_store', 'callback-audit-test-bus']` | 110 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
| execution_state_events / `['execution_state_events', 'state-execution-190']` | 2 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
| ibkr_error_events / `['ibkr_error_events', 'real-ibkr-error-1']` | 6 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
| news_candidate_events / `['news_candidate_events', 'auto-open-20260711105737-news-0']` | 2 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
| open_order_state_events / `['open_order_state_events', 'state-open_order-189']` | 2 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
| order_conflict_events / `['order_conflict_events', 'conflict-conflict-entry_buy_lmt-pfe-0-conflict-gap_escape_sell_lmt-pfe-0']` | 29 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
| order_intent_events / `['order_intent_events', 'auto-open-20260711111945-entry_buy_lmt-aapl-9']` | 2 | Same locally scoped identifier, differing original content/time; establish occurrence lineage before reconciliation |
