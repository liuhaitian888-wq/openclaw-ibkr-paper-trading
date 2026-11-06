# Scoped Paper order acceptance plan

**Goal:** User-authorized real Paper acceptance: one nonmarketable limit submitted/cancelled, one single-share limit filled, and test-only exposure reconciled/closed if fill succeeds.
**Architecture:** Finite one-shot executor using existing ib_async transport, exact DUQ503649/loopback4002 and approved Git identity. Separate explicit test manifest/journal; global strategy PAUSED and production safety files remain unchanged. No retries of sent/UNKNOWN side effects.
**Tech stack:** Python, ib_async2.1.0, SQLite, shared monitoring deployment guard.
**Spec:** User request2026-11-06 and previously approved independent Paper experiment range.

## Constraints / review focus
- Linked-worktree full offline suite and secret scan; Git-only production integration.
- SymbolNVDA only, no existing NVDA position/order, one share, limit<=USD200, max3 submissions, no concurrent test order, no shorting; any simulated currency financing requires the explicit bounded Paper policy.
- Current exact Paper account, fresh type1 bid/ask, contract resolution/minTick, available USD funds and existing manual/system exposure checked before every submission.
- Account snapshot + reserve + durable STARTED precede send. Sent/UNKNOWN cannot be replayed. Broker rejection is not a successful fill/cancel.
- Cancellation only exact test clientId/orderRef/contract/account/order identity; originalPFE untouched.
- Persist native timestamps, callbacks, permId/execId, pre/post positions and raw messages. Return uncertainty rather than fabricate completion.
- Test manifest explicitly permits this finite maintenance-time Paper experiment; it does not unpause strategy or approve full production.

## Tasks
- [ ] Record real quote recovery observation and unknown exact session-release cause.
- [ ] Implement test scope/journal and finite one-shot ib_async runner, add offline failure/risk/ownership tests.
- [ ] Full offline suite and scan; commit, integrate and deploy through Git.
- [ ] Review fresh real preflight, then execute each finite stage visibly; journal all outcomes and reconcile.
- [ ] Record actual results, preserve uncertain attempts and upload code/evidence summary.
