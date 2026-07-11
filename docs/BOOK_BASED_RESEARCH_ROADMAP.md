# Book-Based Quant Research Roadmap

This document turns the current local book set into an implementation roadmap.
It is a research and paper-trading plan only. Live trading remains disabled
unless explicitly enabled by the operator.

## Current Book Set

- Ernest P. Chan, `Quantitative Trading`.
- Ernest P. Chan, `Algorithmic Trading`.
- Robert Carver, `Systematic Trading`.
- Marcos Lopez de Prado, `Advances in Financial Machine Learning`.

Local source paths:

- `/Users/nbhsbgnb/Library/Mobile Documents/iCloud~com~apple~iBooks/Documents/Quantitative Trading - 2012 - Chan.pdf`
- `/Users/nbhsbgnb/Library/Mobile Documents/iCloud~com~apple~iBooks/Documents/Algorithmic Trading - 2013 - Chan.pdf`
- `/Users/nbhsbgnb/Library/Mobile Documents/iCloud~com~apple~iBooks/Documents/Systematic Trading.pdf`
- `/Users/nbhsbgnb/Library/Mobile Documents/iCloud~com~apple~iBooks/Documents/Advances in Financial Machine Learning.pdf`

Do not copy long passages from these books into the project. Extract concepts,
formulas, tests, pseudo-code, and engineering tasks.

## Data And Execution Reality

`simulated-scenario` is a deterministic synthetic price path. It exists to force
BUY and SELL events so that the project can test signal generation, risk checks,
API calls, audit logs, dashboards, and reports without depending on live market
conditions.

`simulated-scenario` is not IBKR market data and is not a realistic fill model.

The current real-data path is:

```text
IBKR TWS paper session
-> read-only market data API
-> Quote / Bar cache
-> strategy module
-> portfolio risk gate
-> Trading API
-> TWS paper order adapter
-> SQLite audit
```

The live-account path must remain separate and disabled:

```text
IBKR live account
-> live order adapter
-> explicit live-trading enable flag
-> explicit kill switch off
-> explicit operator approval
```

Changing a paper account to a live account should not be treated as a harmless
environment swap. Live trading needs different account checks, buying-power
checks, permission checks, kill-switch policy, order-size limits, and operator
confirmation.

## P0 Implementation Sequence

### 1. Ernest Chan: Quantitative Trading

Immediate extraction:

- Backtest hygiene: survivorship bias, transaction costs, benchmark comparison,
  drawdown, consistency, paper trading drift.
- Strategy families: mean reversion, momentum, regime switching, stationarity,
  cointegration, factor models, seasonal effects.
- Risk: Kelly-style sizing as a research reference, not an execution default.

Engineering tasks:

- Add a research report that compares backtest and paper behavior.
- Add transaction cost and slippage assumptions to all strategy reports.
- Add benchmark comparison against SPY/QQQ.
- Add a first stationarity and cointegration research notebook/script before
  allowing pairs trading into paper mode.

### 2. Ernest Chan: Algorithmic Trading

Immediate extraction:

- Mean reversion diagnostics: ADF, Hurst exponent, variance ratio, half-life.
- Cointegration diagnostics: CADF and Johansen.
- Strategy structures: Bollinger-style mean reversion, Kalman-filter hedge
  ratio, ETF pairs/triplets, interday momentum, intraday momentum.
- Execution warnings: quote source, primary vs. consolidated quotes, short-sale
  constraints, regime shifts, live drift from backtests.

Engineering tasks:

- Implement a `research/mean_reversion_diagnostics.py` script. Done: the
  project now has a zero-heavy-dependency diagnostics runner that reports
  lag-1 ADF-style t-stat, half-life, Hurst exponent, variance ratio, latest
  z-score, a research score, and a verdict.
- Implement a pairs-trading candidate report before any pair order generation.
- Add paper-only Bollinger/z-score mean reversion module.
- Keep intraday momentum limited to liquid US ETFs/stocks and minute bars.

Run the diagnostics on any CSV with `symbol` and `close` columns:

```bash
.venv313/bin/python scripts/run_mean_reversion_diagnostics.py path/to/prices.csv --output reports/mean_reversion_diagnostics.json
```

This is a research filter, not a final statistical proof. A `research_candidate`
verdict means the symbol deserves a backtest and paper observation, not that it
has a tradable edge.

To use real IBKR read-only quote snapshots as the source data, first record a
small CSV from TWS or IB Gateway:

```bash
.venv313/bin/python scripts/record_ibkr_quotes.py \
  --symbols AAPL,MSFT,SPY \
  --samples 30 \
  --interval-seconds 60 \
  --market-data-type 3 \
  --output-csv data/ibkr_quotes.csv \
  --output-report reports/ibkr_quote_recorder.json
```

Then run the diagnostics on the recorded CSV:

```bash
.venv313/bin/python scripts/run_mean_reversion_diagnostics.py \
  data/ibkr_quotes.csv \
  --output reports/mean_reversion_diagnostics.json
```

Use `--market-data-type 1` only after IBKR real-time market data permissions are
confirmed. The recorder is read-only and does not expose order placement.

Before any paper-trading trial, audit the local environment:

```bash
.venv313/bin/python scripts/audit_paper_trading_readiness.py \
  --output reports/paper_environment_audit.json
```

The audit never places orders. It reports `ready_for_one_share_paper_trial` only
when the Trading API `/health` response and local settings agree that the system
is in `TRADE_LOCK`, paper transmit is enabled, the kill switch is off, a trade
session token is present, TWS is ready, and the connected account is a `DU`
paper account. Use `--no-api-health` only for configuration-only checks.

The guarded session runner is the daily paper-trial entrypoint. It runs the
environment audit first and stops with `environment_blocked` before recording
market data if the local machine is not ready:

```bash
.venv313/bin/python scripts/run_guarded_paper_trial_session.py \
  --symbols AAPL,MSFT,SPY \
  --samples 30 \
  --interval-seconds 60 \
  --market-data-type 3 \
  --guarded-session-report reports/guarded_paper_trial_session.json
```

After the audit is ready, add `--submit-validate` for validate-only API checks.
For an intentional one-share paper order, add `--execute-paper`, `--confirm
PAPER_ONLY_1_SHARE`, and `--trade-session-token-file`. The guarded runner still
never calls live endpoints.

Build a current operator runbook after any audit or guarded session run:

```bash
.venv313/bin/python scripts/build_paper_session_runbook.py \
  --output-md reports/paper_session_runbook.md \
  --output-json reports/paper_session_runbook.json
```

The runbook condenses the latest JSON reports into blockers, operator steps,
and safe next commands for the current machine state.

Generate the local status page from that runbook:

```bash
.venv313/bin/python scripts/build_paper_session_status_page.py \
  --output reports/paper_session_status.html
```

After any actual paper order, take read-only post-trade snapshots and reconcile:

```bash
.venv313/bin/python scripts/list_tws_orders.py > reports/tws_orders_snapshot.json
.venv313/bin/python scripts/record_account_pnl.py --samples 1 --interval-seconds 1
.venv313/bin/python scripts/build_paper_trial_reconciliation.py \
  --output reports/paper_trial_reconciliation.json
```

Then build the evidence bundle so the current paper-trial stage is explicit:

```bash
.venv313/bin/python scripts/build_paper_trial_evidence_bundle.py \
  --output-json reports/paper_trial_evidence_bundle.json \
  --output-md reports/paper_trial_evidence_bundle.md
```

For routine status refreshes, use the single safe entrypoint:

```bash
.venv313/bin/python scripts/refresh_paper_trial_reports.py
```

It regenerates audit, guarded session, reconciliation, runbook, status page, and
evidence bundle. A blocked environment remains a successful refresh and does not
touch IBKR quote capture. If a paper execution gate contains an idempotency key,
the refresh also reads the SQLite audit DB automatically for reconciliation.

To test the post-ready code path without IBKR or orders, run a simulated
rehearsal:

```bash
.venv313/bin/python scripts/rehearse_paper_trial_workflow.py \
  --output-dir reports/paper_trial_rehearsal
```

This creates rehearsal artifacts only. It does not prove real IBKR market data,
Trading API validation, or paper order execution.

The one-command version records read-only IBKR quotes, runs diagnostics, and
writes a validate-only paper plan plus a pipeline summary:

```bash
.venv313/bin/python scripts/run_ibkr_mean_reversion_pipeline.py \
  --symbols AAPL,MSFT,SPY \
  --samples 30 \
  --interval-seconds 60 \
  --market-data-type 3 \
  --quotes-csv data/ibkr_quotes.csv \
  --diagnostics-report reports/mean_reversion_diagnostics.json \
  --paper-plan-report reports/paper_validation_plan.json \
  --pipeline-report reports/ibkr_mean_reversion_pipeline.json
```

This command is the first real-market-data research bridge. It still does not
place orders; paper trading should only come after a recorded dataset, a
diagnostics report, and a strategy-specific paper plan exist.

If you want the same one-command pipeline to call `/v1/orders/validate/limit`,
add `--submit-validate`. This remains validate-only and does not stage, transmit,
or place paper orders.

The full trial version continues from there: it records read-only IBKR quotes,
runs diagnostics, builds the validate-only plan, writes the manual readiness
report, and writes the paper execution gate report. Dry-run is still the
default:

```bash
.venv313/bin/python scripts/run_full_paper_trial_pipeline.py \
  --symbols AAPL,MSFT,SPY \
  --samples 30 \
  --interval-seconds 60 \
  --market-data-type 3 \
  --quotes-csv data/ibkr_quotes.csv \
  --diagnostics-report reports/mean_reversion_diagnostics.json \
  --paper-plan-report reports/paper_validation_plan.json \
  --readiness-report reports/paper_readiness_report.json \
  --execution-gate-report reports/paper_execution_gate.json \
  --full-pipeline-report reports/full_paper_trial_pipeline.json
```

For validate-only API checks in the same run, add `--submit-validate`. For an
actual paper order in the same run, all final gate conditions still apply:
`--execute-paper`, `--confirm PAPER_ONLY_1_SHARE`, a trade session token file,
Trading API `/health` readiness, and a validation payload with `approved=true`.
The full pipeline never calls live endpoints.

Generate the validate-only paper plan from the diagnostics report:

```bash
.venv313/bin/python scripts/build_paper_validation_plan.py \
  reports/mean_reversion_diagnostics.json \
  --entry-z 1.0 \
  --output reports/paper_validation_plan.json
```

If you explicitly want to call the local Trading API validation endpoint, add
`--submit-validate`. That still only calls `/v1/orders/validate/limit`; it does
not stage, transmit, or place paper orders:

```bash
.venv313/bin/python scripts/build_paper_validation_plan.py \
  reports/mean_reversion_diagnostics.json \
  --entry-z 1.0 \
  --submit-validate \
  --api-url http://127.0.0.1:8787 \
  --output reports/paper_validation_plan.json
```

The plan is intentionally long-only for the first module. Negative z-score
candidates may create BUY validation payloads; positive z-score candidates are
watch-only until a pullback or an explicit short-capable strategy exists.

Build the manual paper-readiness report from a validation plan:

```bash
.venv313/bin/python scripts/build_paper_readiness_report.py \
  reports/paper_validation_plan.json \
  --output reports/paper_readiness_report.json
```

This report is the final pre-paper checklist. It classifies the session as
`not_ready_for_paper`, `validate_required`, or `ready_for_manual_paper_review`.
Even the final status is not an automatic order instruction: it means an
operator can review the plan, confirm TWS paper readiness, and then choose
whether to submit at most one small paper order through the existing Trading API
gates.

The last gate can prepare or explicitly submit at most one 1-share paper limit
order from the readiness artifacts. Dry-run is the default:

```bash
.venv313/bin/python scripts/submit_single_paper_from_readiness.py \
  reports/paper_readiness_report.json \
  reports/paper_validation_plan.json \
  --output reports/paper_execution_gate.json
```

Submitting to `/v1/orders/paper/limit` requires all of the following:

- readiness status is `ready_for_manual_paper_review`;
- the selected validation payload has `approved=true`;
- order side is `BUY` and quantity is `1`;
- the operator passes `--execute-paper`;
- the operator passes `--confirm PAPER_ONLY_1_SHARE`;
- the trade session token file is supplied;
- Trading API `/health` reports `TRADE_LOCK`, paper transmit enabled, kill
  switch off, and TWS ready.

Example explicit paper submission command:

```bash
.venv313/bin/python scripts/submit_single_paper_from_readiness.py \
  reports/paper_readiness_report.json \
  reports/paper_validation_plan.json \
  --execute-paper \
  --confirm PAPER_ONLY_1_SHARE \
  --trade-session-token-file /Volumes/openclaw_shared/trade_session_token \
  --api-url http://127.0.0.1:8787 \
  --output reports/paper_execution_gate.json
```

This is still paper-only. It never calls live endpoints.

### 3. Robert Carver: Systematic Trading

Immediate extraction:

- Modular framework: instruments, forecasts, combined forecasts, volatility
  targeting, position sizing, portfolios, trading cost constraints.
- Forecast normalization: convert heterogeneous rules into comparable forecast
  values.
- Risk targeting: position size should be derived from volatility and capital,
  then capped by hard risk gates.
- Diversification: combine weak but independent forecasts rather than trusting
  one strong-looking rule.

Engineering tasks:

- Add a normalized forecast object beside `Signal`.
- Add volatility estimation and volatility-target sizing in research mode.
- Add cost-aware rule selection so fast strategies are rejected when spreads or
  fees dominate expected edge.
- Add a combined-forecast module that blends trend, carry/quality, and mean
  reversion forecasts.

### 4. Marcos Lopez de Prado: Advances in Financial Machine Learning

Immediate extraction:

- Data structures: bars, event sampling, feature sampling.
- Labeling: fixed horizon first, then triple-barrier method.
- Meta-labeling: use a primary strategy for side and an ML model for whether to
  act and how large.
- Sample weights: uniqueness, overlap, time decay.
- Validation: purged K-fold and walk-forward; standard random K-fold is unsafe
  for overlapping financial labels.
- Models: random forest, boosting, feature importance, probability-driven bet
  sizing.

Engineering tasks:

- Build a LightGBM-style MVP with technical indicators and walk-forward splits.
- Add triple-barrier labels only after event sampling and clean minute/daily bars
  exist.
- Add purged cross-validation before using ML performance numbers in reports.
- Add feature-importance reports before paper enabling any ML signal.

## P0 Strategy Modules From The Books

1. Dual moving average trend module.
   - Already exists in the current project.
   - Next: add volatility-target position sizing.

2. Z-score mean reversion.
   - Implemented as a unified interface skeleton.
   - Next: add diagnostics and backtest report.

3. Grid / do-T rebalance.
   - Implemented as a unified interface skeleton.
   - Next: require position sync from IBKR before live-like paper use.

4. Bollinger mean reversion.
   - Derive from Chan mean-reversion framework.
   - Next: add half-life estimation and cost filter.

5. LightGBM-style ML baseline.
   - Implemented as dependency-free signal skeleton using precomputed
     probability.
   - Next: train a real model from local bars and save predictions as features.

6. Volatility-target trend following.
   - Derive from Carver.
   - Next: add volatility estimator and forecast scaling.

## P1 Research Queue

- Pairs trading: CADF/Johansen diagnostics, hedge ratio, spread z-score,
  stop-loss by spread breakdown.
- Turtle breakout: channel breakout, ATR sizing, pyramiding disabled initially.
- Intraday momentum: only with IBKR minute bars or a reliable historical vendor.
- Triple-barrier labeling: only after clean event generation.
- Meta-labeling: primary rule side plus model probability.
- Feature importance: permutation and SHAP-style reports where dependency
  budget allows.

## P2 Research Queue

- Transformer time-series models.
- Reinforcement learning trading or execution.
- Hierarchical risk parity and ML portfolio allocation.
- Microstructure features from tick/order-book data.
- Execution quality analyzer and slippage predictor.

## External Book Gaps

Recommended additions:

- Perry J. Kaufman, `Trading Systems and Methods`.
- Perry J. Kaufman, `A Guide to Creating a Successful Algorithmic Trading
  Strategy`.
- Thomas Stridsman, `Trading Systems That Work`.
- Thomas Stridsman, `Trading Systems and Money Management`.
- Larry Harris, `Trading and Exchanges`.
- Joel Hasbrouck, `Empirical Market Microstructure`.
- Maureen O'Hara, `Market Microstructure Theory`.
- Robert Almgren and Neil Chriss papers on optimal execution.
- Barry Johnson, `Algorithmic Trading and DMA`.

For the current project, Harris and Johnson are the most practical execution
references. Hasbrouck and O'Hara are deeper research references.
