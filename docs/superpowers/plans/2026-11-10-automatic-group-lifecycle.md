# Automatic Group Notification Lifecycle Implementation Plan

> **For agentic workers:** Execute natively with the existing notification engineer owning integration/deployment; do not create another production worker.

**Goal:** Route noninteractive automatic safe status to deehub and replace fault/recovery floods with durable grouped cards, preserving private interactions and uncertain delivery evidence.

**Architecture:** An explicit grouped-v1 policy projects only proven-unattempted outbox events into bounded groups before the existing sender claims. Persistent group cursors and member records survive restart; immutable summary versions update a single native group card. The existing producer/worker/broker owners remain unchanged.

**Tech Stack:** Python, SQLite, existing Telegram transport.

**Spec:** openspec/changes/secretary-market-operations/design.md; openspec/specs/secretary-engineering-review/spec.md.

## Global Constraints
- PAUSED/MAINTENANCE, broker permissions and all original STARTED/UNKNOWN bytes/outcomes stay unchanged.
- Historical pending cutover rows with positive zero-wire evidence are retained as policy-suppressed, never represented as sent or replayed.
- New recovery member references retain existing causal uncertainty guards; the exact-three CURRENT_RISK_STATUS scope is not widened.
- No raw account/source/model prose or credentials enters generic group templates; actual owner dialogue/control remains private.
- Sole sender and linked-worktree full offline suite; notification engineer owns config activation/cloud deployment.

## Review Focus
- A preflight attempt is not wire proof; any WIRE_START/delivery/receipt prevents regrouping.
- Reopened protection incidents share one broker group; unknown coverage is not cancelled protection.
- Recovery must remain stable for60s and require fresh complete Paper evidence; stale/dependency-changing snapshots cannot claim recovery.
- Pending older versions are invalidated before wire; UNKNOWN aggregate prevents a second wire occurrence across restart.
- Real query responses remain private, automatic review/authorization-status notices do not mirror to private.

### Task 1: Routing and zero-wire aggregation
**Files:** reporting/automatic_notifications.py (new), reporting/notification_access.py, reporting/notification_center.py, reporting/incident_telegram.py, ops/cloud/feishu_alert_watch.py; tests/test_automatic_notifications.py (new).
**Interfaces:** enabled(config), interactive(item), prepare(store,config), valid(store,item,now), rendered(item,at). Policy configuration automatic_notification_policy='grouped-v1'.
- [x] Add tests for7→1 fault grouping, stable60s recovery,15min repeat cap, escalation, restart, old queue cutover and UNKNOWN/attempt preservation.
- [x] Implement persistent group cursor/member provenance and sender-before-claim hook;2s coalescing, deterministic fixed templates and same-card EDIT.
- [x] Add tests for private interactive controls, automatic supervisor/auth states, safe generic task/research status, and no public credential/source prose.
- [x] Run focused offline tests then the complete prescribed isolated suite; retain immutable patch/config contract for integration owner.

### Task 2: Integration and native acceptance
**Files:** existing OpenSpec current/delta/design/tasks, docs/NOTIFICATION_RESPONSIBILITIES.md, .der/context/task-closeout.md.
- [x] Update current/delta specs and implementation boundary; inspect existing diagram semantics/dependency receipts without declaring planned topology deployed.
- [ ] Complete full suite, secret scan, Git integration via coordinated owner and five-project refresh.
- [ ] Notification engineer deploys reviewed runtime and policy before the separately owned Paper recovery; retain source/manifest and cutover evidence.
- [ ] Inspect real Telegram group/private histories and native receipts over a measured observation window; report exact sends/edits/private alert count, not service liveness. No fabricated fault or UNKNOWN replay.
