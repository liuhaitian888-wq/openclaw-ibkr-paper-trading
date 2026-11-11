# Publication routing implementation plan

**Goal:** Apply human instruction 01a1c869-090b-7b62-8bb4-7c8850b54d4c: archive ordinary events, publish actual reports and finished research, retain quick owner interaction/action requests, maintain one current link-status card.
**Architecture:** publication-v2 supersedes historical grouped-v1. Existing transactional outbox and sender own all wire operations; fixed host registry binds one status card and separate pin outcome. No new worker, Gateway action, replay or permission expansion.
**Tech Stack:** Python, SQLite, existing Telegram Bot API sender; existing owner session only for operator-authorized native verification/pinning when bot lacks rights.
**Spec:** Existing secretary-market-operations change, protection-recovery-notifications current spec.

## Global constraints
- Preserve every STARTED/UNKNOWN/reserved/wired occurrence and source SHA. Only proven zero-wire pending rows may become SUPPRESSED with append-only policy receipt.
- LINK_STATUS_CARD requires host registry and exact payload SHA at claim and both prewire boundaries. Model metadata never grants pin or publication permission.
- Reports require actual original PNG/manifests; research must be an archived completed result, never a generic status placeholder.
- Pin has a separate single attempt from known SEND/EDIT; permission failure does not expand rights; timeout is UNKNOWN and never automatically replayed.
- Complete offline suite only in linked worktree with scripts/run_worktree_tests.py; secret scan before immutable commit; unique publisher integrates and verifies native Telegram.

## Review focus
- More than500 archived events must not leak through a claim backlog.
- Race after destination proof must not send an event newly classified archive or tampered card.
- Model CHAT/CONTROL/public labels and arbitrary pin IDs must fail host provenance validation.
- Stale TCP/model evidence must not imply current business readiness or trading permission.
- Accepted SEND survives independent pin failure without a duplicate replacement card.

## Tasks
- [ ] Implement publication_policy.py decision/prepare/archive_claimed and queue finished-result provenance; test archive boundaries, complete artifacts and direct replies.
- [ ] Implement link_status_card.py host scope/registry, readonly snapshot, one-card queue and independent pin state; test tamper/UNKNOWN/stale and fixed identity.
- [ ] Integrate policy preclaim/prewire gates and pin handling in existing sender/worker; test no activity mirror, no generic auto wire, one-card EDIT.
- [ ] Update existing OpenSpec/current specs/closeout with historical vs current policy, run applicable suite/scan, commit and hand to sole publisher for native acceptance.
