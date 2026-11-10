# Grouped Recovery Disposition Implementation Plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Existing owner-authorized engineering chats supply the implementation and independent review; this does not request a new worker or repeat human approval.

**Goal:** Restore ongoing grouped automatic recovery without replaying three historical unknown deliveries or losing new severe changes.

**Architecture:** Keep original notification rows and causal references. A separate explicit owner scope binds exactly three legacy dispositions and the installed grouped-policy cutover. Only trusted registered new broker RECOVERED summaries may exclude those exact dependencies; every other unknown outcome and earlier uncertain aggregate still blocks. Shared Paper persistence fault checks and continuous native freshness precede claims and transport.

**Tech Stack:** Python, existing SQLite recovery store, one Telegram sender, existing Paper SDK owner.

**Spec:** `openspec/specs/protection-recovery-notifications/spec.md`; `openspec/changes/secretary-market-operations`.

## Global Constraints

- Preserve PAUSED/MAINTENANCE, Gateway, financial scopes and every STARTED/UNKNOWN original.
- Exact legacy IDs are1270/NIO/gen7,1271/PFE/gen171,1272/T/gen7; bind raw payloads and unchanged positive-attempt evidence.
- Full grouping authority is actual owner message01a1c326-572e-7e33-b5b3-2be24ab9056b, separate from the earlier one-current-report capability.
- Old historical pending projections may be retained as suppressed only with positive zero-wire evidence; no fabricated sent state or missing causal references.
- Complete account PNG reports remain group-visible under explicit shared_group policy; interactive replies/control stay native owner-private.
- Develop/test only linked worktrees; complete suite through scripts/run_worktree_tests.py, all-files gitleaks, actual native acceptance separately.

## Review Focus

- A source with an operation reservation, receipt, delivery or wire evidence remains isolated; aggregation cannot replay it.
- Claimed payloads with changed counts, phase, nonce, identity or provenance fail before transport.
- Freshness/epoch/persistence loss or any new fault during the60-second window restarts recovery stability.
- Old exact-three exceptions never unblock another unknown or an uncertain earlier aggregate.
- New generic YELLOW→RED severity updates the same card promptly and does not receive protection-specific wording.

### Task 1: Complete immutable grouped source and registry guards

**Files:** `reporting/automatic_notifications.py`, `reporting/notification_access.py`, `reporting/incident_telegram.py`, `reporting/notification_center.py`, source/provenance producer and grouped tests.

**Interfaces:** Existing sender remains owner. Reuse `reporting.local_persistence.has_local_persistence_fault(root, connection=None, *, marker_only=False) -> bool`; unavailable checks fail closed. `automatic_notifications.valid` accepts a borrowed connection without closing it or recursive validity checks.

- [ ] Add negative regressions for each Review Focus class.
- [ ] Complete safe-unsent operation guard, immutable registry fingerprint/typed fields, continuous native stability and generic serious escalation.
- [ ] Freeze one follow-up after independent review, run the full isolated suite and secret/spec checks.

### Task 2: Exact grouped-current administrative continuation

**Files:** `reporting/notification_disposition.py`, `reporting/incidents.py`, automatic module and corresponding disposition/integration tests.

**Interfaces:** `authorize_grouped_current(store, scope_id, legacy_scope_id, authorization)` records USER provenance plus exact installed cutover. `register_grouped_current(store, c, item, scope_id)` binds only post-cutover broker RECOVERED current summaries. `eligible_grouped_current_ids(store, c, now)` returns bounded valid IDs. `grouped_current_valid(store, c, item, now)` rechecks registration, authorization, all three originals/attempt evidence, source cutover, native epoch, shared negative gate and continuous stability.

- [ ] Test no authorization, old source, changed original/receipt, changed epoch/fault latch, other unknown and earlier uncertain aggregate all deny.
- [ ] Insert the narrow causal SQL exception only for eligible report IDs plus exact legacy unresolved IDs; retain recovery_members and all other original guards.
- [ ] Verify existing CURRENT fallback remains separately bounded and shares the persistence negative gate.
- [ ] Run real helper positive/negative integration cases, complete linked suite, secret/spec checks and independent review before Git handoff.

### Task 3: One-owner Wave B release and actual acceptance

**Files:** deployment audit, existing OpenSpec/task-closeout; only operator-owned state/config/scope changes after tested source publication.

- [ ] Combine only immutable Paper7d1ccac+7ae2b2f and reviewed grouped patches onto actual accepted WaveA source; keep unrelated financial branches out.
- [ ] Publish through Git with exact dual manifests and unchanged permissions; activate grouped policy before one-shot Paper recovery.
- [ ] Record original-three retirement and separate grouped authorization with exact owner provenance; no historical resend.
- [ ] Execute one source/Gateway-bound read-only resume; preserve old four attempts and one new operation identity, no Gateway restart or automatic replay.
- [ ] Require real non-dirty four-end heartbeat/state plus both persistence gates clear and stable observation; independently verify group fault→recovery same-card update and no unwanted private automatic notices.
- [ ] Prefer actual grouped recovery card acceptance; do not add a duplicate CURRENT fallback card. Archive truthful secretary SYSTEM handoff, logs, remaining items and refresh five projects.
