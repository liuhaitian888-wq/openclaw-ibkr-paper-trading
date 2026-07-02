# Trading Lock Policy

This project uses a two-state token lock. The lock is an operating rule; the
actual safety boundary is the trade session token, which must never be stored in
the repository.

## DEV_LOCK

Use this state for coding, tests, refactors, and maintenance.

- Codex may edit code and run non-trading tests.
- `TRADE_SESSION_TOKEN` must be unset.
- `TRADING_KILL_SWITCH` should be `true`.
- Do not call `/v1/orders/stage` or `/v1/orders/paper`.
- Do not run scripts that place TWS orders.

Suggested shell state:

```bash
unset TRADE_SESSION_TOKEN
export TRADING_KILL_SWITCH=true
```

Shortcut:

```bash
scripts/start_dev_lock_api.command
```

## TRADE_LOCK

Use this state only for paper-trading execution windows.

- Codex is read-only: no code edits, no config edits, no dependency changes.
- The user manually sets `TRADE_SESSION_TOKEN` in the trading terminal.
- `TRADING_KILL_SWITCH` may be `false`.
- Trading requests must still pass Python risk checks and audit logging.

Suggested shell state:

```bash
export TRADE_SESSION_TOKEN='temporary-user-chosen-token'
export TRADING_KILL_SWITCH=false
```

Shortcut:

```bash
scripts/start_trade_lock_api.command
```

The trade shortcut prompts for the daily token, writes the same token to the
VM shared folder as `trade_session_token`, then starts the Mac Python API.

## Core Rule

Do not mix the states:

- When Codex can edit code, no trading token exists.
- When a trading token exists, Codex does not edit code.

## Mode Control

The preferred shortcut is:

```bash
scripts/control_trading_mode.command
```

It generates a fresh daily token, asks whether to enter `DEV_LOCK` or
`TRADE_LOCK`, distributes or clears the shared token file accordingly, and then
starts the Mac Python API in the selected mode.

It also supports `STOP`, which clears the shared token file and stops the Mac
Python API process.
