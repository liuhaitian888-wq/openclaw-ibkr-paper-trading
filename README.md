# IBKR Paper Trading Gateway

Copyright (c) 2026 der. All rights reserved.

This project is for internal testing and authorized collaboration. No part of this repository may be
copied, redistributed, modified, published, sublicensed, used commercially, or
shared with third parties without prior written permission from der. See
[LICENSE](LICENSE).

This project is the controlled execution layer between OpenClaw and an IBKR
paper-trading TWS session.

## Design documents

- [Security Model](SECURITY_MODEL.md) defines Discord, OpenClaw, Python, and
  IBKR trust boundaries.
- [Architecture](ARCHITECTURE.md) maps the layered system, tool ownership,
  trigger flow, timing optimization path, and future model space.
- [Audit Model](AUDIT_MODEL.md) separates execution audit, P&L, benchmark
  comparison, pure-AI baseline comparison, and PostgreSQL migration planning.
- [Data Feeds](DATA_FEEDS.md) explains quote-source boundaries, Stooq, IBKR
  free data, spread control, and slippage.
- [Value Pool](VALUE_POOL.md) defines the first value-investing filter and how
  new finance concepts become testable modules.
- [Strategy Modules](docs/STRATEGY_MODULES.md) documents the current paper-only
  strategy modules, including the conservative dual-SMA trend strategy.

## Current safety state

- TWS host: `127.0.0.1`
- Paper port: `7497`
- API mode: `DRY_RUN`
- TWS staging: disabled by default
- Paper transmission: disabled by default
- Paper transmission also requires `TRADE_SESSION_TOKEN`
- `TRADING_KILL_SWITCH=true` rejects all order submissions
- Live-account orders: rejected; only one `DU` paper account is accepted
- Maximum quantity: 1 share
- Maximum order value: USD 200
- Maximum estimated stop risk: USD 10
- Allowed symbols: `AAPL`, `MSFT`, `SPY`

The paper order adapter creates a limit entry and a protective stop as a bracket.
Every submission requires a unique idempotency key and is recorded in SQLite.

SQLite is only the local audit ledger. It is not part of the realtime order
route, and no manual database operation is needed during normal trading. The
default file is `trading_audit.sqlite3`; SQLite may also create `-wal` and `-shm`
sidecar files while the API is running. Keep those files local, do not edit them
by hand during a trading session, and use `/v1/orders/audit` or `audit-key` to
inspect order history.

## PyCharm interpreter

Use:

```text
/Users/nbhsbgnb/Documents/New project/.venv313/bin/python
```

## Run tests

```bash
.venv313/bin/python -m unittest discover -v
```

## Run local strategy simulation

This simulation does not connect to IBKR and does not place orders. It exercises
the first modular strategy framework: simulated quote stream, quote cache, bar
builder, value-pool filter, moving-average signal, and tactical entry planner.

```bash
.venv313/bin/python scripts/run_strategy_simulation.py --symbols AAPL,MSFT
.venv313/bin/python scripts/run_strategy_simulation.py --symbols AAPL,MSFT,QQQ,SPY,NVDA,AMD --steps 12 --batch-size 2
```

The second command exercises the large-universe path: one quote source, a
rotating symbol pool, a latest-quote cache, and bounded per-symbol bar history.
It does not place orders.

Run the first modular pool strategy in automatic validate mode:

```bash
.venv313/bin/python scripts/run_pool_strategy_module.py --mode validate --source simulated-scenario --symbols AAPL,MSFT,AMD,INTC,KO,PFE,T,F --steps 18 --batch-size 4
```

The first module is `classic_conservative_trend`: a long-only conservative trend
module that buys a value/allowlist pool symbol after a short moving average
confirms above a longer moving average, then sells on a small paper target,
small stop, or trend loss. The `simulated-scenario` source intentionally moves
fast enough to show BUY and SELL decisions in one run.

Build the strategy catalog and book-principle mapping:

```bash
.venv313/bin/python scripts/build_strategy_catalog.py
```

This writes `reports/strategy_catalog.json` and `reports/strategy_catalog.md`.
It records the current modular strategy set, data requirements, risk controls,
book-derived principles, and the next validation steps before any strategy is
treated as paper-trading evidence.

The first free quote sources are Stooq and Yahoo delayed polling. They are
keyless and useful for wiring the framework, but they are not Level 1/NBBO and
not final low-latency execution feeds:

```bash
.venv313/bin/python scripts/run_strategy_simulation.py --source stooq --symbols AAPL,MSFT --steps 3
.venv313/bin/python scripts/run_strategy_simulation.py --source yahoo --symbols AAPL,MSFT --steps 3
.venv313/bin/python scripts/run_strategy_simulation.py --source yahoo-replay --symbols AAPL,MSFT --steps 20
```

Check read-only IBKR quotes without placing orders:

```bash
.venv313/bin/python scripts/diagnose_market_data_channels.py --symbols AAPL,MSFT,QQQ
.venv313/bin/python scripts/check_ibkr_quotes.py --symbols AAPL,MSFT,QQQ
.venv313/bin/python scripts/check_ibkr_quotes.py --symbols AAPL,MSFT,QQQ --market-data-type 3
.venv313/bin/python scripts/check_ibkr_quotes.py --symbols AAPL,MSFT,QQQ --market-data-type 1 --exchange IEX
```

Audit whether the local machine is ready for a one-share paper trial:

```bash
.venv313/bin/python scripts/audit_paper_trading_readiness.py
```

This writes `reports/paper_environment_audit.json`. It never places orders. A
ready report requires the local Trading API `/health` to respond, `TRADE_LOCK`,
paper transmit enabled, kill switch off, a trade session token, TWS ready for
orders, and exactly one `DU` paper account. Use `--no-api-health` for an offline
configuration-only check, or `--health-json path/to/health.json` to audit a
saved `/health` response.

The guarded paper-trial session is the preferred end-to-end entrypoint. It runs
the same environment audit first, and it stops before market-data recording or
validation unless the environment is ready:

```bash
.venv313/bin/python scripts/run_guarded_paper_trial_session.py \
  --symbols AAPL,MSFT,SPY \
  --samples 30 \
  --interval-seconds 60 \
  --market-data-type 3
```

Add `--submit-validate` only after the audit is ready and you want to call
`/v1/orders/validate/limit`. Add `--execute-paper --confirm PAPER_ONLY_1_SHARE`
only for a deliberate one-share paper trial with a trade session token file.

Build the operator runbook from the latest reports:

```bash
.venv313/bin/python scripts/build_paper_session_runbook.py
```

This writes `reports/paper_session_runbook.md` and
`reports/paper_session_runbook.json`. The runbook summarizes current blockers,
the next human steps, and the safe commands for the current state.

Build a static status page from the runbook:

```bash
.venv313/bin/python scripts/build_paper_session_status_page.py
```

Open `reports/paper_session_status.html` locally to see the current state,
blockers, operator steps, commands, and report artifacts in one place.

After any paper order, capture readbacks and reconcile them:

```bash
.venv313/bin/python scripts/list_tws_orders.py > reports/tws_orders_snapshot.json
.venv313/bin/python scripts/record_account_pnl.py --samples 1 --interval-seconds 1
.venv313/bin/python scripts/build_paper_trial_reconciliation.py
```

The reconciliation report cross-checks the execution gate, SQLite audit record,
TWS orders/executions, and the latest P&L snapshot.

Build a single evidence bundle for the whole paper-trial workflow:

```bash
.venv313/bin/python scripts/build_paper_trial_evidence_bundle.py
```

This writes `reports/paper_trial_evidence_bundle.json` and
`reports/paper_trial_evidence_bundle.md`, including the current stage, report
statuses, next actions, and artifact presence.

Refresh the complete report set in safe order:

```bash
.venv313/bin/python scripts/refresh_paper_trial_reports.py
```

This updates environment audit, guarded session, reconciliation, runbook,
status page, preflight checklist, evidence bundle, and completion audit. If the
environment is blocked, the refresh is still successful and stops before IBKR
quote capture. Reconciliation reads the SQLite audit DB automatically when an
execution gate contains an idempotency key.

Rehearse the ready-environment code path without real IBKR data or orders:

```bash
.venv313/bin/python scripts/rehearse_paper_trial_workflow.py
```

This is a simulated rehearsal only. It proves the guarded pipeline can pass the
ready gate and build validation/readiness artifacts, but it is not market-data
or order execution evidence.

Build the final preflight checklist before a real IBKR paper window:

```bash
.venv313/bin/python scripts/build_paper_trial_preflight_checklist.py
```

This writes `reports/paper_trial_preflight_checklist.json` and
`reports/paper_trial_preflight_checklist.md`. It reads the latest audit,
runbook, and simulated rehearsal reports, then states the next allowed action,
machine-check status, manual confirmations, and hard stop conditions. It does
not connect to IBKR and does not place orders.

Monitor readiness while opening TWS paper and TRADE_LOCK:

```bash
.venv313/bin/python scripts/monitor_paper_trial_readiness.py --max-attempts 60 --interval-seconds 5
```

This writes `reports/paper_trial_readiness_monitor.json` and refreshes the
audit, runbook, and preflight checklist. It only polls `/health`; it does not
capture IBKR quotes, call validate endpoints, or submit orders. When it reports
`ready_for_validate_only_window`, the next allowed action is guarded
validate-only.

Assess whether recorded IBKR quotes are useful for candidate generation:

```bash
.venv313/bin/python scripts/build_quote_quality_report.py
```

This writes `reports/quote_quality_report.json` and
`reports/quote_quality_report.md`. It explains whether the recorded sample has
enough rows, last-price movement, and reasonable spreads. Static quote samples
are valid market-data evidence, but they should not be forced into paper orders.

Hunt for a validate payload without submitting any paper order:

```bash
.venv313/bin/python scripts/hunt_paper_candidate.py \
  --symbols AAPL,MSFT,SPY \
  --max-attempts 3 \
  --samples 30 \
  --interval-seconds 5 \
  --api-url http://192.168.64.1:8787
```

This writes `reports/paper_candidate_hunt.json`, updates the latest guarded
session reports, and refreshes quote quality. It calls validate-only when a
payload exists, but it never passes `--execute-paper` and never submits orders.

Build a validate-only plan from the modular P0 strategy interface when the
mean-reversion plan has no payload:

```bash
.venv313/bin/python scripts/build_strategy_validation_plan.py \
  --quotes-csv data/ibkr_quotes.csv \
  --submit-validate \
  --api-url http://192.168.64.1:8787
.venv313/bin/python scripts/build_paper_readiness_report.py reports/paper_validation_plan.json
.venv313/bin/python scripts/build_paper_execution_gate.py \
  reports/paper_readiness_report.json \
  reports/paper_validation_plan.json
```

This uses the unified strategy modules to create validation candidates from
recorded IBKR quotes. It still only calls the validate endpoint; paper
submission remains behind the same execution gate, confirmation phrase, and
session token checks.

Before the final one-share paper submission, build a no-order pre-submit
review, then submit through the reviewed gate only after explicit confirmation:

```bash
.venv313/bin/python scripts/build_paper_pre_submit_review.py
.venv313/bin/python scripts/build_paper_execution_gate.py \
  reports/paper_readiness_report.json \
  reports/paper_validation_plan.json \
  --execute-paper \
  --confirm PAPER_ONLY_1_SHARE \
  --trade-session-token-file ~/Documents/openclaw_shared/trade_session_token \
  --pre-submit-review reports/paper_pre_submit_review.json \
  --api-url http://192.168.64.1:8787
```

The reviewed gate blocks if the pre-submit review is stale, missing, failed, or
does not match the selected one-share payload.

Audit whether the whole current objective is actually complete:

```bash
.venv313/bin/python scripts/build_project_completion_audit.py
```

This writes `reports/project_completion_audit.json` and
`reports/project_completion_audit.md`. It is deliberately strict: strategy
catalog and simulated rehearsal are not enough. The audit remains incomplete
until real IBKR readiness, quote capture, validate-only results, and a reconciled
one-share paper order are all evidenced by current reports.

Record account-level P&L over time without placing orders:

```bash
.venv313/bin/python scripts/record_account_pnl.py --samples 60 --interval-seconds 60
```

This appends read-only snapshots to `reports/pnl_timeseries.csv` and
`reports/pnl_timeseries.jsonl`. The main unrealized P&L field is calculated from
TWS portfolio updates, which matches the Portfolio panel more closely than the
raw account P&L stream.

Generate a local static dashboard:

```bash
.venv313/bin/python scripts/generate_strategy_dashboard.py --source simulated --symbols AAPL,MSFT,QQQ
.venv313/bin/python scripts/generate_strategy_dashboard.py --source yahoo --symbols AAPL,MSFT,QQQ --output dashboard/yahoo_strategy_dashboard.html
.venv313/bin/python scripts/generate_strategy_dashboard.py --source yahoo-replay --symbols AAPL,MSFT,QQQ --steps 20 --output dashboard/yahoo_replay_strategy_dashboard.html
.venv313/bin/python scripts/generate_strategy_dashboard.py --source ibkr-readonly --symbols AAPL,MSFT,QQQ --steps 1 --ibkr-market-data-type 3 --output dashboard/ibkr_readonly_strategy_dashboard.html
.venv313/bin/python scripts/generate_strategy_dashboard.py --source ibkr-readonly --symbols AAPL,MSFT,QQQ --steps 1 --ibkr-market-data-type 1 --ibkr-exchange IEX --output dashboard/ibkr_iex_strategy_dashboard.html
```

Start the IBKR-only live dashboard:

```bash
scripts/start_live_dashboard.command
```

Then open:

```text
http://127.0.0.1:8790/
```

The live dashboard currently watches:

```text
AAPL, MSFT, NVDA, TSLA, AMD, INTC, NFLX
```

## Run the API locally

```bash
.venv313/bin/python api_service.py
```

Shortcut scripts:

- `scripts/control_trading_mode.command` generates a fresh daily trade token,
  asks whether to enter `STOP`, `DEV_LOCK`, or `TRADE_LOCK`, then starts or
  stops the API with the matching environment.
- `scripts/stop_trading_api.command` clears the shared trade token and stops the
  Mac Python API.
- `scripts/start_dev_lock_api.command` starts the API with the kill switch on
  and no trade session token.
- `scripts/start_trade_lock_api.command` asks for the daily trade token, writes
  it to the VM shared folder, and starts the API with paper transmission enabled.
- `scripts/check_gateway_health.command` prints the current `/health` response.
- `scripts/deploy_openclaw_gateway.command` packages the OpenClaw gateway client
  and copies it to `/Volumes/openclaw_shared` when the shared folder is mounted.
  If SSH to the Linux VM is configured, it also installs the update remotely.

The deployment script excludes OpenClaw `.secrets`, so updating the VM gateway
code should not require re-pasting the long-term API key.

Optional SSH deployment variables:

```bash
export OPENCLAW_VM_HOST=192.168.64.2
export OPENCLAW_VM_USER=nbhsbgnb
export OPENCLAW_VM_KEY="$HOME/.ssh/openclaw_vm_ed25519"
```

The API key is generated on first startup in `.secrets/openclaw_api_key` and
must be sent in the `X-API-Key` header. Do not commit or send this key in chat.

## Endpoints

- `GET /health`
- `POST /v1/orders/validate` - validation only
- `POST /v1/orders/validate/limit` - validation only for a single limit order
- `POST /v1/orders/stage` - sends an untransmitted bracket to paper TWS; disabled
- `POST /v1/orders/stage/limit` - sends an untransmitted limit order to paper TWS; disabled
- `POST /v1/orders/paper` - transmits a bracket to paper TWS; disabled
- `POST /v1/orders/paper/limit` - transmits a single limit order to paper TWS; disabled

Example request body:

```json
{
  "symbol": "AAPL",
  "side": "BUY",
  "quantity": 1,
  "limit_price": 190.0,
  "stop_price": 185.0,
  "idempotency_key": "paper-20260623-0001",
  "source": "openclaw"
}
```

For `/v1/orders/paper`, include the user-provided session token in the request
body:

```json
{
  "trade_session_token": "temporary-user-token"
}
```

`GET /health` reports both the operating lock and IBKR/TWS readiness:

- `lock_state`: `DEV_LOCK`, `TRADE_LOCK`, or `MIXED`.
- `tws.connected`: whether the Mac API can complete the TWS API handshake.
- `tws.ready_for_orders`: true only when TWS is reachable, logged in, returns a
  next order id, and exposes exactly one `DU` paper account.
- `tws.error`: human-readable reason when TWS is not ready.

The OpenClaw client checks `/health` before calling `/paper` or `/paper/limit`.
The Mac API also performs a TWS preflight before reserving the idempotency key or
calling `placeOrder`, so an IBKR login/API failure is rejected before any order
is sent.

## OpenClaw network path

The intended private path is:

```text
OpenClaw VM (192.168.64.2)
  -> Mac Python API (192.168.64.1:8787)
  -> TWS (127.0.0.1:7497)
```

Keep TWS restricted to localhost. Only the Python API should become reachable
from the VM, and the macOS firewall should allow only `192.168.64.2`.

## Order timing fields

Order responses include a `timings` object. Durations use Python
`time.perf_counter()` and are reported in milliseconds, so they measure elapsed
runtime rather than wall-clock time.

- `openclaw_command_total_ms`: OpenClaw client process time from argument
  parsing through JSON output.
- `openclaw_http_round_trip_ms`: HTTP request/response time between the OpenClaw
  VM client and the Mac Python API.
- `service_parse_ms`: Mac API JSON-to-proposal parsing time.
- `service_risk_ms`: Python risk-engine validation time.
- `service_gate_ms`: mode, kill switch, paper transmit, staging, and session
  token checks.
- `service_audit_reserve_ms`: SQLite idempotency reserve write.
- `service_broker_submit_ms`: time spent inside the IBKR broker adapter.
- `broker_connect_handshake_ms`: TWS API connect, `nextValidId`, and managed
  accounts handshake.
- `broker_place_orders_ms`: `placeOrder` calls into TWS.
- `broker_wait_ack_ms`: wait for TWS `orderStatus` or accepted `openOrder`
  acknowledgement.
- `broker_open_orders_fallback_ms`: optional `reqOpenOrders` fallback wait when
  no direct acknowledgement arrives before the timeout.
- `broker_total_ms`: total broker adapter time.
- `service_audit_update_ms`: SQLite final status update.
- `service_total_ms`: total Mac API service time after request dispatch.

The current code cannot directly measure the external phase from a Discord or
OpenClaw channel message to the moment the OpenClaw client process starts. To
measure true channel-to-order latency, pass the original message timestamp into
the client and compare it with `openclaw_command_started_at`.

## Related projects

Non-trading projects were split out of this gateway so this folder stays focused
on IBKR paper-trading automation:

- Discord handbook bot: `/Users/nbhsbgnb/Documents/discord_handbook_project`
- Croatian A1 Anki deck: `/Users/nbhsbgnb/Documents/Hrvatski/anki_a1_project`
- Wind/storage MPC model: `/Users/nbhsbgnb/Documents/wind_storage_mpc_project`
