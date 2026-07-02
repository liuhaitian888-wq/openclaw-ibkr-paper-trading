---
name: ibkr-paper-gateway
description: Validate or submit tightly constrained IBKR paper trades through the Mac Python risk service.
---

# IBKR Paper Gateway

Use this skill to check service health, validate a proposed paper trade, or submit
a paper trade only when the Python gateway reports that TRADE_LOCK is active.

## Safety rules

- Never claim that validation placed or transmitted an order.
- Never connect directly to TWS port 7497.
- Never call `/v1/orders/stage`.
- Call `/v1/orders/paper` only when TRADE_LOCK is active.
- TRADE_LOCK is active when gateway health reports all of the following:
  `mode=PAPER`, `kill_switch_enabled=false`, `paper_transmit_enabled=true`, and
  `trade_session_required=true`.
- The user does not need to type the literal word `TRADELOCK` when those
  conditions are true.
- Paper submission requires `TRADE_SESSION_TOKEN`; never ask the user to reveal it
  in chat. The user may provide it through the environment or through the shared
  token file `/mnt/openclaw_shared/trade_session_token`.
- Never invent missing symbol, side, quantity, or limit price. Stop price is
  required only for bracket/stop-loss orders, not for simple limit orders.
- For first-pass outside-regular-hours execution tests, prefer a simple limit
  order with `validate-limit` and `paper-limit`; do not add a stop leg unless the
  user explicitly asks for bracket/stop-loss protection.
- Use standard mode for research, rehearsal, and operator-visible checks.
- Use `--fast` only after the trading window and symbol have already been
  selected. Fast mode skips the OpenClaw-side health preflight, but it still goes
  through the Python gateway's risk gate, lock check, daily token check, TWS
  preflight, idempotency reserve, and audit update.
- In fast mode, do not run account, order, position, market snapshot, report
  generation, or attachment steps before submission. Those belong before the
  window is locked or after the order response is recorded.
- Report every rejection reason exactly to the user.
- Keep quantity at 1 unless the Python service reports a different limit.
- Use `source=openclaw` for audit logging.

## Commands

Health:

```bash
python3 openclaw_trading_client.py health
```

Validation:

```bash
python3 openclaw_trading_client.py validate \
  --symbol AAPL \
  --side BUY \
  --quantity 1 \
  --limit-price 190 \
  --stop-price 185 \
  --idempotency-key paper-20260623-0001
```

Simple limit validation:

```bash
python3 openclaw_trading_client.py validate-limit \
  --symbol AAPL \
  --side BUY \
  --quantity 1 \
  --limit-price 190 \
  --idempotency-key paper-limit-20260625-0001
```

Paper submission during TRADE_LOCK only:

```bash
python3 openclaw_trading_client.py paper \
  --symbol AAPL \
  --side BUY \
  --quantity 1 \
  --limit-price 190 \
  --stop-price 185 \
  --idempotency-key paper-20260624-0001
```

Simple limit paper submission during TRADE_LOCK only:

```bash
python3 openclaw_trading_client.py paper-limit \
  --symbol AAPL \
  --side BUY \
  --quantity 1 \
  --limit-price 190 \
  --idempotency-key paper-limit-20260625-0001
```

Fast simple limit submission after the window and symbol are already locked:

```bash
python3 openclaw_trading_client.py paper-limit \
  --fast \
  --symbol AAPL \
  --side BUY \
  --quantity 1 \
  --limit-price 190 \
  --idempotency-key paper-limit-20260625-0001
```

The environment may provide `OPENCLAW_API_KEY`; otherwise the client reads it
from `.secrets/openclaw_api_key` next to `openclaw_trading_client.py`. The
default API endpoint is `http://192.168.64.1:8787`; override it with
`TRADING_API_URL` when necessary.

Paper submission also requires `TRADE_SESSION_TOKEN`, set only by the user for
the active trading window. If the environment variable is absent, the client
reads `/mnt/openclaw_shared/trade_session_token`. Without a token, this client
refuses to call `/paper`. The Python gateway performs the final token match at
`/paper`.

## Timing

Every order response includes `timings` in milliseconds. The most useful fields
for speed checks are:

- `openclaw_execution_mode` is `fast_trade_check` when `--fast` was used.
- `openclaw_fast_mode` confirms whether the client skipped OpenClaw-side
  preflight.
- `openclaw_command_total_ms` for local OpenClaw client runtime.
- `openclaw_http_round_trip_ms` for VM-to-Mac API latency.
- `service_total_ms` for Mac Python gateway work.
- `service_broker_submit_ms` and `broker_total_ms` for the TWS adapter.
- `broker_connect_handshake_ms`, `broker_place_orders_ms`, and
  `broker_wait_ack_ms` for the main IBKR phases.

These values start when the OpenClaw client process is already running. Channel
message dispatch time must be measured by the channel/OpenClaw side and compared
with `openclaw_command_started_at`.

## Fast trade check mode

Fast mode exists for the moment after analysis has already identified a narrow
growth window and the user has enabled `TRADE_LOCK`. The intended path is:

```text
prepared proposal -> paper-limit --fast -> Python API -> risk gate
-> lock/token check -> TWS preflight -> audit reserve -> paper order
```

The fast path deliberately avoids:

- extra OpenClaw-side `/health` preflight
- account orders query
- positions query
- market snapshot query
- report file generation
- attachment sending
- long explanation before submission

The Python gateway remains the final authority. If `TRADE_LOCK`, token, TWS,
risk, or idempotency is wrong, the gateway rejects the order and returns the
`workflow_step`.
