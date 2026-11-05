# Paper session recovery Implementation Plan

**Goal:** Diagnose persistent10197, repair bounded subscription recovery, then advance isolated Paper execution acceptance.
**Architecture:** Keep the existing owner, budgets, exact account and durable uncertainty journal. Preserve broker orders and paused global strategy. A new Gateway child identity is independent from its persistent controller identity.
**Spec:** User confirmed Live logout and requested recovery repair and Paper test progression, 2026-11-05.

## Constraints and review focus
- Worktree-only full offline suite; secret scan then Git integration/deployment.
- Distinguish broker-denied fresh requests from a stuck client; do not invent server logout state.
- 162 session-conflict text must not permanently disable10197 recovery; unrelated162 stays diagnostic.
- 1101 recovery must consume existing bounded subscription admission;1102 preserves subscriptions.
- Java child restarts must be visible without replenishing unchanged incident budgets.
- Quote evidence requires actual fresh distinct callbacks; no connection-only recovery.
- No UNKNOWN order replay or existingPFE cancellation; maintain global PAUSED.

## Tasks
- [ ] Capture fresh broker/session/owner evidence and resource baseline.
- [ ] Add regression tests, fix session-error classification and Gateway child identity.
- [ ] Run isolated full suite and scan, Git integrate; bounded monitor-only rollout after state backup.
- [ ] Verify real quote recovery; if fresh broker requests remain denied after confirmed logout, investigate native session and perform at most one separately journaled authorized Paper reauthentication, not a recovery-loop restart.
- [ ] Reconcile account/orders/quotes after recovery; implement/validate the explicit Paper test journal and risk scope before any test order.
- [ ] Record evidence and push code through Git.
