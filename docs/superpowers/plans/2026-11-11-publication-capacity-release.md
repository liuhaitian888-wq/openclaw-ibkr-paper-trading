# Quiet publication and capacity release implementation plan

> **For agentic workers:** Use the preserved native/team execution method; existing source owners implement, notification owner integrates and publishes. No new agent or production worker.

**Goal:** Deploy bounded capacity monitoring and quiet group publication, then verify one current chain-status pinned card and an actual secretary capacity query.

**Architecture:** Reuse the existing inbox observer, notification sender/outbox, exact native receipts and trusted host state registry. Ordinary events remain auditable without group placeholders. Status send/edit and pin have independent operation records.

**Tech Stack:** Python, SQLite, Telegram Bot API and existing owner native session, systemd, Git linked worktrees.

**Spec:** Existing secretary-market-operations and capacity-observability changes. Original human source: coordinator chat01a1c257, message01a1c869-090b-7b62-8bb4-7c8850b54d4c,2026-11-11.

## Global constraints
- Actual deployment basec1f95fa; main336069f and parallel evidence remain independent until reviewed integration.
- Policypublication-v2: ordinary events/short states archive only; real full report attachments and completed research results publish to group; direct interactions/urgent action remain owner private.
- A single trusted-host latest API/chain card; pin is authorized for this card only, without changing bot privileges.
- Existing bot cannot pin; verify native card first, then one existing owner-session pin with exact identity and UNKNOWN reconciliation.
- No Gateway action, trading, scope renewal, old UNKNOWN replay, deletion or archive/cleanup feature in this release.
- Preserve historical backups; free-space admission uses actual retained small liveDB backups with bounded checks, never copy obsolete1.86GB candidates.

## Review focus
- Zero-wire classification excludes reservations/attempts/delivery/receipts; historical uncertain rows retain bytes and statuses.
- A model-created kind or flags cannot authorize public content/pin; bind complete trusted-host payload/source/target.
- Unknown pin does not replay and cannot relabel an already accepted status send.
- TCP handshake, native account completeness, data freshness, model, limited Codex acceptance and trading gates remain separate.
- Capacity warning/recovery are archive only; immediate-action critical remains private; forecasts stay UNKNOWN until continuous evidence.

### Task1: Current-base capacity candidate
**Files:** reporting/capacity.py, health.py, secretary_observations.py, secretary_read.py, scripts/run_secretary_bridge.py; tests/test_capacity.py.
**Interfaces:** capacity.tick(root,now=None) owns bounded local sample and fixedRO metadata; capacity.read(root,now=None) reads saved evidence only.
- [x] Review owner's immutable c1 successor and archive-only warning/critical-private compatibility.
- [x] Verify exact linked suite/secret scan and no new daemon/schema/cleanup permission.

### Task2: Quiet route and host status card
**Files:** publication_policy.py, link_status_card.py, automatic_notifications.py, notification_access/center, incident_telegram.py, existing worker and focused tests; exact owner diff determines final paths.
**Interfaces:** publication policy enabled/decision/prepare/archive_claimed; trusted status registry with complete fingerprints and two prewire checks; send/edit and pin independent records.
- [ ] Review fixed candidate and source authority, pending sweep, send-time fail-closed guards.
- [ ] Test archive-only backlog beyond500, report/research group content, interaction/private critical, forged host card, state change, UNKNOWN/card/pin idempotency.

### Task3: Sole-owner integration and acceptance
- [ ] Combine only necessary c1 successors in linked worktree, full run_worktree_tests.py, strict current/active specs, all-filesgitleaks.
- [ ] Check actual source/dualmanifests/gates/Gateway/Paper generation, model idle and disk admission, retain bounded source/liveDB backups.
- [ ] Git FF approved cloud workspace, identity-only manifest update, reload only changed existing owners.
- [ ] Activatepublication-v2 and trusted card scope after exact source load; verify natural card native receipt then owner-session one-time pin/readback.
- [ ] Execute one newly authorized native capacity question, prove tool snapshot/result/private receipt, no consumed dbcheck scope or UNKNOWN replay.
- [ ] Record source/offline/deployed/native outcomes, main linked integration/quicksmoke, secret scan, task-closeout and five-project refresh.
