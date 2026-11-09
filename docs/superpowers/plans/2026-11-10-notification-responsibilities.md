# Notification responsibilities and reconciled recovery implementation plan

> **For agentic workers:** REQUIRED SUB-SKILL: Use superpowers:subagent-driven-development (recommended) or superpowers:executing-plans to implement this plan task-by-task. Steps use checkbox (`- [ ]`) syntax for tracking.

**Goal:** Classify recipients before sending and let the secretary investigate delivery evidence without blindly replaying uncertain notifications.

**Architecture:** Retain the existing receiver/sender owners, exact native owner checks, shared health registry and durable outbox. Separate deterministic authorization, model assessment and authorized sender actions; all attempt/reconciliation evidence is append-only. This plan is not runtime acceptance or authorization to enable group control.

**Tech Stack:** Existing Python/SQLite/python-telegram-bot; no new broker connection, framework, Vault/PostgreSQL or extra bot service.

**Spec:** docs/NOTIFICATION_RESPONSIBILITIES.md; docs/TELEGRAM_ACCESS_RESEARCH_20261110.md; existing openspec/changes/secretary-market-operations.

## Global Constraints

- UNKNOWN or non-idempotent outcomes require reconciliation and must never be automatically replayed.
- Labels never grant account/control authority; existing owner-native private identity remains required.
- Account-bearing report destination is pending the owner's visibility research decision; no silent destination change.
- Cloud model/provider acceptance belongs to its existing task; this plan must work with durable model-unavailable state.
- No runtime implementation in the current research/documentation pass.

## Review Focus

- Mixed research/task results containing personal balances must not leak through a public category.
- Missing callback identity, renamed user and self-edited tag never grant a capability.
- Lost ACK after a successful server send is not proof of non-delivery.
- Crash after approval/claim but before receipt cannot create a duplicate retry or duplicate supervisor.
- Stale/replaced PNG bytes cannot be called the original report; disconnected user cannot rely on ephemeral delivery.

### Task 1: Deterministic content classification and persistent membership decisions

**Files:** reporting/notification_center.py; reporting/secretary_queue.py; tests/test_notification_center.py; new reporting/notification_access.py and tests/test_notification_access.py.

**Interfaces:** notification_access.decision(item: dict, config: dict) -> dict with audience/reason/policy_version. Registered roles are keyed by chat_id/user_id, separate from display tags. No new control principal.

- [ ] Write regression cases for sensitive TASK/RESEARCH with account metadata, auth, safety, immediate gate, public market/engineering/calendar, unknown label, forwarded/anonymous callback and report decision pending.
- [ ] Add a versioned content classification schema and reject/hold ambiguous mixed private content; preserve old events and receipts. Until a report-sharing policy is selected, keep explicit current report authorization separately visible.
- [ ] Propagate producer classifications and enforce destination before render and transport, with no public fallback.
- [ ] Run the full isolated wrapper in a linked worktree and all-files gitleaks; commit only after success. Runtime validation uses read-only native destination proof first; future message receipts are separate.

### Task 2: Append-only reconciliation assessment and one recovery owner

**Files:** new reporting/notification_reconciliation.py and tests/test_notification_reconciliation.py; reporting/incidents.py; reporting/secretary_read.py; reporting/secretary_observations.py; reporting/health.py.

**Interfaces:** assess(root: Path, notification_id: int) -> dict with ACCEPTED/PROVEN_UNSENT/UNRESOLVED and evidence references; model explanation is not an authority token. Persist a versioned review occurrence and decision separately from the original send.

- [ ] Test accepted receipt, malformed receipt, UNKNOWN without receipt, STARTED crash, explicit rejection, changing evidence, model unavailable and repeated recovery callback.
- [ ] Add per-attempt append-only records and read-only evidence tool; no reset/delete of old delivery rows. Bind native IDs, content fingerprints, attempt timing, non-secret error class and policy version.
- [ ] Connect a bounded idempotent recovery observation through the shared health registry and existing secretary owner; atomically queue one review occurrence rather than a new background worker. Model spend follows existing budgets, unresolved work survives restart.
- [ ] Run full worktree tests/gitleaks, commit, integrate via Git; no production fault injection or automatic replay of1094.

### Task 3: Reconciled resend and dual notices

**Files:** reporting/incident_telegram.py; reporting/notification_reconciliation.py; reporting/notification_text.py; tests/test_incident_telegram.py; tests/test_notification_reconciliation.py.

**Interfaces:** authorize_retry(review_id: str, evidence_fingerprint: str) -> one bounded attempt, only after PROVEN_UNSENT plus dependency recovery or explicit per-occurrence acceptance of duplicate risk. Already-accepted outcomes repair bookkeeping instead.

- [ ] Test explicit rejection vs network timeout, source freshness/expiry, artifact hash change, duplicate approval, crash between attempt/receipt, group/private target, exhausted retry budget and missing model.
- [ ] Reuse existing sender lock and recipient verification; append a linked attempt with immutable original event. Never turn UNKNOWN into PENDING merely because the network recovered.
- [ ] Prefix the same approved public resend with short reason/original schedule/event ID; enqueue a bounded private result notice with its own outbox/receipt identity. Failed supervisor notices cannot recursively create infinite notices.
- [ ] Full worktree suite/gitleaks, reviewed Git deployment, native result acceptance on a new genuinely due event; do not manufacture a test send or replay uncertain historical report.

### Task 4: Optional native labels and ephemeral UI

**Files:** future reporting/notification_access.py and isolated connector tests; current Telegram adapter only after interface compatibility review.

- [ ] Select per-member labels and real data capabilities with owner; label changes alone do not authorize new readers.
- [ ] Compare SDK compatibility, 15-second ephemeral callback boundary, receiver_user identity, ID reuse, expiry and offline loss; test using fake transport first.
- [ ] Keep bot a regular member during research; any future required administrator rights need a concrete minimal proposal. No native tag/permission changes in this pass.
- [ ] Keep persistent account reports, controls and safety notices in verified private delivery; optional ephemeral views remain auxiliary until independently accepted.
