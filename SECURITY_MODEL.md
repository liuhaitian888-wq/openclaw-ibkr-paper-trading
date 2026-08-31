# Security Model

This project keeps Discord, OpenClaw, local Python control, and IBKR/TWS in
separate trust zones. The default rule is simple: discussion and analysis tools
may prepare information, but only the local Python trading gateway may touch
IBKR.

## Trust Zones

### Discord Handbook Zone

The Discord handbook bot has been split out to
`/Users/nbhsbgnb/Documents/discord_handbook_project`. It remains an external
context tool, not part of the trading gateway.

Allowed:

- Read selected Discord channels.
- Summarize discussion into its own handbook files.
- Save images and attachments for project memory.
- Report handbook status.

Forbidden:

- Calling the trading API.
- Reading API keys, trade session tokens, or broker credentials.
- Opening, closing, or changing trade locks.
- Connecting to IBKR/TWS.
- Placing, staging, cancelling, or modifying orders.

The Discord bot is a handbook assistant only. It must stay useful for project
context without becoming a remote-control surface for the trading system.

### OpenClaw / AI Analyst Zone

Allowed:

- Read research summaries, market data, filings, and audit summaries.
- Generate watchlists and structured trade proposals.
- Query read-only status endpoints that are explicitly exposed.
- Submit proposals to the local Python API when the user intentionally enables
  that path.

Forbidden:

- Direct connection to the IBKR/TWS port.
- Direct use of IBKR credentials.
- Bypassing the Python API, risk gate, lock state, or daily trade token.
- Creating or storing long-lived trade session tokens.

OpenClaw is an analyst and orchestrator. It may propose, compare, and explain,
but it does not get a direct broker connection.

### Local Python Control Zone

Allowed:

- Validate proposal shape.
- Enforce risk limits.
- Enforce `STOP`, `DEV_LOCK`, and `TRADE_LOCK`.
- Verify the daily trade session token.
- Run TWS preflight.
- Submit paper orders through the IBKR adapter.
- Record execution audit and timing fields.

This is the only zone that may call the IBKR execution adapter.

### IBKR / TWS Zone

Allowed:

- Accept local Python adapter connections.
- Provide read-only account, position, order, market, and P&L data.
- Accept paper orders only after every Python gate passes.

Forbidden:

- Direct Discord access.
- Direct OpenClaw access.
- Remote partner access.

TWS should remain bound to localhost where possible. If any network bridge is
needed, it must terminate at the Python API, not at TWS.

## Lock States

`STOP`:

- API is stopped or kill switch is enabled.
- No proposal can reach TWS.
- This is the safest deployment and maintenance state.

`DEV_LOCK`:

- Research, validation, audit reads, and dry-run checks are allowed.
- Paper transmission is disabled.
- TWS staging may be disabled unless explicitly needed for a controlled test.

`TRADE_LOCK`:

- Only the owner can enable it locally.
- Requires a fresh daily trade session token.
- Enables paper execution only after proposal validation, risk approval, TWS
  preflight, and audit reservation.

The kill switch always wins over every other state.

## Role Boundaries

`viewer`:

- Can read summaries, status, and reports.
- Cannot approve, trigger, or modify trading behavior.

`reviewer`:

- Can add comments or review notes.
- Cannot trigger execution.

`operator`:

- Can operate local scripts on the owner's machine.
- Cannot bypass risk controls or session token checks.

`owner`:

- Can create the daily trade token.
- Can enter `TRADE_LOCK`.
- Can approve future expansion of automation rights.

Partners using Discord should remain `viewer` or `reviewer` unless the owner
explicitly changes the operating model later.

## Secret Handling

- API keys and trade session tokens must not be committed.
- Discord summaries must redact token-like values.
- Daily trade tokens should expire by habit: generate one for the session and
  clear it when leaving `TRADE_LOCK`.
- OpenClaw may read its long-term API key file for the Python API, but it must
  never store the daily trade session token as durable memory.

## Failure Reporting

Every failed workflow should include:

- `workflow_step`
- `workflow_step_message`
- human-readable `error`

Important steps include:

- `client_secret`
- `client_http`
- `client_preflight`
- `api_auth`
- `api_request_body`
- `service_parse`
- `service_risk`
- `service_gate`
- `service_tws_preflight`
- `service_audit_reserve`
- `service_broker_submit`
- `service_audit_update`
- `complete`

This lets an operator or AI assistant know exactly where the workflow stopped
without guessing from logs.
