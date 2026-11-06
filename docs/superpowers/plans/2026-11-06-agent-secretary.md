# Agent secretary and monitoring acceptance Implementation Plan

**Goal:** Verify external heartbeat loss/recovery and add an auditable, read-only Telegram research secretary.

**Architecture:** Preserve the existing single monitoring and notification owners. Store secretary records separately from trading and recovery state; reuse approved Telegram audience validation and persistent outbox. Model tools cannot submit/cancel/modify orders.

**Tech Stack:** Python, SQLite, Telegram Bot API, OpenAI Responses API.

**Spec:** User requirements in this session dated 2026-11-06: conversational research, queries/backtests, user/model provenance, fee assumptions/results, existing trading gates preserved.

## Global Constraints
- Develop/test in linked worktree, full suite via scripts/run_worktree_tests.py; main quick smoke only.
- Preserve PAUSED/MAINTENANCE and broker orders; no automatic order replay.
- Store persistent state under ~/.local/state/openclaw.
- Record concise rationale and evidence, not private internal model reasoning.

## Review Focus
- Duplicate Telegram updates must not duplicate paid model runs.
- STARTED/UNKNOWN paid operations survive restart without automatic replay.
- Human instruction and model proposal have separate provenance.
- Unverified fee schedules must not masquerade as actual commissions.
- Notifications must distinguish simulated checks from real availability incidents.

### Task 1: External heartbeat acceptance
- [x] Read source and actual systemd timer/check configuration.
- [x] Arm bounded automatic restore before stopping heartbeat delivery.
- [ ] Observe external Down and Up plus provider notification result; preserve evidence.
- [ ] Compare production gates and service owners before/after.

### Task 2: Recovery semantics
- [ ] Separate session-conflict clearance from strategy quote freshness.
- [ ] Test post-fault quote provenance, stale/closed/unknown market sessions and independent API recovery.
- [ ] Run full offline suite and secret scan; deploy through Git only.
- [ ] Perform bounded API failure/recovery and verify real notification receipts.

### Task 3: Secretary archive and chat
- [ ] Add dedicated agent_secretary.sqlite3 with append-only events, source references, model/tool run states, strategy revisions and backtest/fee artifacts.
- [ ] Reuse exact user/group authentication; one update receiver owner, durable update cursor and idempotency.
- [ ] Add bounded read-only tools for monitor/account/strategy/history queries and isolated backtests.
- [ ] Verify configured API credentials/model access without printing secrets; do not borrow desktop session credentials.
- [ ] Test authorization, duplicate updates, UNKNOWN operations, provenance, bounded shutdown; full suite and secret scan.
- [ ] Activate only after reviewed manifest and conversation delivery test.

### Task 4: Costs and documentation
- [ ] Audit existing cost implementation and upstream provenance against official IBKR schedule and LEAN source.
- [ ] Require versioned asset/venue/account-plan/date inputs, decimal arithmetic and explicit missing assumptions.
- [ ] Reconcile estimates with execution commissions/Flex; never silently use zero fees.
- [ ] Record actual databases, remaining gaps and acceptance evidence in README/ENGINEERING.

Execution is authorized in the current session. This plan does not authorize trading or new paid market-data subscriptions.
