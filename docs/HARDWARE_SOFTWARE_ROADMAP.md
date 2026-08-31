# Hardware And Software Roadmap

This roadmap assumes Germany-based operation, IBKR TWS or IB Gateway, US equity
and ETF strategies, and paper trading before any live deployment.

## Current Machine

- MacBook Air 13-inch, M4, 16GB RAM.
- Suitable for Python strategy development, unit tests, dashboards, light ML,
  daily/minute backtests, and IBKR paper trading.
- Not suitable for heavy deep learning training, large tick databases, or
  latency-sensitive trading.

## Phase 0: Stabilize Current Laptop

Priority: immediate.

- Use IB Gateway for automation windows and TWS for manual inspection.
- Disable macOS sleep during trading windows.
- Keep one active market-data session where possible to avoid IBKR competing
  live-session errors.
- Use `127.0.0.1:7497` for paper TWS and keep live ports disabled.
- Keep `TRADING_KILL_SWITCH=true` outside planned paper windows.
- Use delayed market data for plumbing tests and real-time IBKR data only when
  permissions are confirmed.
- Keep all order sizes at 1 share until the audit trail has multiple clean
  sessions.

## Phase 1: Data And Research Upgrade

Priority: after paper pipeline is stable.

- Add a local time-series store:
  - DuckDB or SQLite for early OHLCV research.
  - Parquet files for portable minute/daily datasets.
  - PostgreSQL only when multi-process writes or richer reporting are needed.
- Add a reproducible data pipeline:
  - IBKR snapshot/minute bars where available.
  - Start with `scripts/record_ibkr_quotes.py` to capture read-only quote
    snapshots into CSV for research diagnostics.
  - A paid historical data vendor if serious minute-bar research becomes the
    bottleneck.
  - Separate raw, cleaned, feature, label, and prediction datasets.
- Add experiment tracking:
  - JSON reports first.
  - MLflow or a lightweight local registry later.

## Phase 2: Market Data Upgrade

Priority: before scaling strategy count or order size.

- Confirm IBKR real-time US equity data permissions.
- Understand that free IEX/Cboe-style feeds are not full consolidated NBBO.
- For tight intraday strategies, consider paid consolidated Level 1 data.
- For microstructure research, consider a vendor with historical tick and quote
  data. Do not build microstructure strategies from delayed or venue-only data.

## Phase 3: Execution Reliability Upgrade

Priority: before any live trading.

- Use IB Gateway on a dedicated always-on machine or VPS-like environment.
- Add a watchdog that restarts the read-only dashboard, not the order path.
- Add heartbeat checks:
  - TWS/IB Gateway connected.
  - account is paper or live as expected.
  - next order ID is available.
  - market data is fresh.
  - no unknown open orders.
- Add position reconciliation before every paper/live order:
  - strategy memory must match IBKR position state.
  - if not, block trading and require operator review.
- Add order state reconciliation:
  - open orders.
  - fills.
  - partial fills.
  - cancellations.
  - rejects.

## Phase 4: Hardware Options

Conservative option:

- Keep the MacBook Air for research and manual oversight.
- Add a Mac mini with 24GB or 32GB RAM for always-on IB Gateway, data capture,
  dashboard, and paper trading.

Balanced option:

- Mac mini M4 Pro, 48GB or 64GB RAM.
- External SSD for local Parquet/duckdb datasets.
- UPS if running at home.

Cloud option:

- Use cloud only for research/backtests and dashboards.
- Keep IBKR login and order path local unless the broker setup and security
  model are deliberately redesigned.

Not recommended yet:

- GPU workstation for deep learning.
- Low-latency colocated infrastructure.
- Tick-level paid feeds before the current strategy stack proves value in
  paper trading.

## Phase 5: Software Stack Targets

Core:

- Python 3.13 project environment.
- pandas, numpy, scipy, scikit-learn.
- statsmodels for stationarity and cointegration diagnostics.
- lightgbm or xgboost for first ML MVP.
- duckdb and pyarrow for local data.
- ibapi or ib_insync for broker integration, with strict execution boundaries.

Research:

- vectorbt for fast vectorized experiments.
- backtrader only if event-driven backtests need richer broker semantics.
- Qlib as a later research framework, not tonight's execution engine.
- PyPortfolioOpt for portfolio research.

Operations:

- launchd for Mac services.
- SQLite audit now, PostgreSQL later.
- Static HTML dashboard now, richer local web app later.
- Daily markdown/JSON reports with explicit data freshness and order status.

## Live Trading Readiness Gate

Do not enable live trading until all are true:

- At least 20 clean paper sessions.
- At least 100 audited paper orders or intentionally skipped signals.
- No unexplained TWS disconnects during an active session.
- Position reconciliation is implemented.
- Order reconciliation is implemented.
- Real-time data permissions are confirmed.
- Strategy has out-of-sample and paper evidence.
- Max order size, max daily loss, and kill-switch procedures are written down.
- Operator has explicitly enabled live trading for a specific session.
