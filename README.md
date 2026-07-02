# IBKR Paper Trading Gateway

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

## Discord handbook bot

The optional Discord handbook bot listens to selected Discord channels and
writes rolling markdown summaries into `handbook/`. It is separate from the
trading execution gateway and does not place orders.

Install the Discord dependency:

```bash
.venv313/bin/python -m pip install -r requirements-discord.txt
```

Required environment:

```bash
export DISCORD_BOT_TOKEN="..."
export DISCORD_CHANNEL_IDS="1514270735638593616"
export HANDBOOK_ADMIN_USER_IDS="your_discord_user_id"
```

For the current Discord channel URL:

```text
https://discord.com/channels/1297628173898481735/1514270735638593616
```

the server ID is `1297628173898481735` and the channel ID to configure is
`1514270735638593616`.

Run:

```bash
scripts/start_discord_handbook_bot.command
```

In the selected Discord channel, send `!handbook summarize` to flush the current
buffer immediately. The bot needs Discord's bot scope, channel read/send
permissions, and the message content intent enabled in the Discord Developer
Portal.

Use `!handbook status` to check the bot and copy your Discord user ID. Add that
ID to `HANDBOOK_ADMIN_USER_IDS` to restrict summary-writing commands. If
`HANDBOOK_ADMIN_USER_IDS` is empty, any member in the configured channel can run
`!handbook summarize`.
