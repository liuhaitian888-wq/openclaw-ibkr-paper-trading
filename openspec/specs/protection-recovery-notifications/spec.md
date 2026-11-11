# Protection recovery notifications

## Purpose

Preserve per-symbol protection evidence while grouping newly resolved incidents into one bounded recovery digest through the existing sender, without replaying uncertain outcomes.

## Requirements

### Requirement: Atomic protection recovery digest

A complete broker observation MUST create at most one protection recovery digest for newly resolved symbol incidents. Initial healthy observations without an open incident and repeated identical observations MUST NOT generate a recovery message.

#### Scenario: Evidence survives digest creation

- **WHEN** a recovery digest is created
- **THEN** retain its member identities and uncertainty with these constraints

Original events, incident generations and symbol RECOVERY records MUST remain queryable. Individual recoveries MUST become SUPPRESSED atomically with digest creation, before any sender can claim them. SUPPRESSED MUST NOT imply Telegram acceptance. The digest MUST reference member event and notification identities, distinguish protected symbols from closed no-exposure faults, and state remaining unresolved protection count/symbols. It MUST NOT grant trading permission.

New/ongoing risk alerts MUST retain existing escalation and reminder handling. Existing STARTED/UNKNOWN attempts and receipts MUST remain intact; a digest MUST NOT be claimed while an earlier member occurrence notification is unresolved. No historical queued recovery rewrite or replay is authorized.

The existing notification worker remains the sole delivery owner. Account detail uses the current privacy decision; a public fixed summary must be rebuilt from validated bounded fields rather than arbitrary account payload prose.

#### Scenario: Newly resolved symbols share one digest

- **WHEN** a complete observation resolves several symbol incidents
- **THEN** their retained evidence is suppressed atomically and one bounded digest is queued without replaying earlier uncertain sends

### Requirement: Explicit current-state administrative continuation
The system SHALL preserve the unknown delivery outcome of an explicitly scoped historical occurrence when the owner authorizes retiring its dependency. Such a disposition SHALL NOT create a receipt, retry, or historical success/non-delivery conclusion. A separately registered current report SHALL require fresh complete broker evidence and exact scope/content binding; other uncertain protection occurrences SHALL still block it.

#### Scenario: Three archived dependencies and one current summary
- **WHEN** an owner-authorized scope binds1270–1272 by original ID/key/generation/status/raw content and unchanged attempt evidence
- **THEN** retain all three originals intact, retain never-attempted obsolete aggregate history as superseded, and permit only the registered fresh current group summary; do not release old per-symbol queues or automatically mirror private detail.

#### Scenario: Evidence changed or broker readback stale
- **WHEN** authorization/original/attempt evidence changes, another protection outcome is uncertain, or the current epoch/content/freshness no longer matches
- **THEN** the current report is denied before transport and no historical uncertainty is cleared.


### Requirement: Current deliverables-only publication policy
The system SHALL apply publication-v2: ordinary events remain archived without push; actual account-report artifacts and registered completed research publish to the approved group. Native interaction and fresh human-action requirements MUST remain owner-private. Uncertain/reserved/wired attempts MUST NOT be suppressed as unsent or replayed. This overrides the earlier all-automatic group dispatch rule.

#### Scenario: Large ordinary backlog after policy change
- **WHEN** more than500 pending ordinary events exist
- **THEN** bounded archival passes retain payload fingerprints and the whole-queue claim filter prevents any ordinary event escaping to either chat.

#### Scenario: Quiet missing notice is followed by a real report
- **WHEN** an initial Telegram report row was locally SUPPRESSED only as a missing-only notice with exactly empty included reports and PNGs, and its publication-v2 archive policy/reason/parsed-payload hash and positive zero-wire proof remain intact
- **THEN** retain that initial row unchanged, permit at most one same-day genuine report supplement through all existing period/source/artifact/expiry checks, and bind the exact initial identity/hash for revalidation at claim and before wire.

#### Scenario: Missing-notice evidence changes before the supplement is sent
- **WHEN** the initial has any operation, delivery, receipt, wire or uncertain outcome, its archive proof/content changes, or it contained an actual report
- **THEN** do not use the local archive exception, do not retry the initial, and refuse the supplement's exception again before wire; unrelated historical UNKNOWN and STARTED outcomes remain unchanged.

#### Scenario: Private input identity is independent of publication
- **WHEN** publication-v2 archives ordinary outbound events and the cloud inbox verifies its native private input destination
- **THEN** validate the exact configured owner/private target, bot native identity and private chat type directly without routing a fabricated outbound notification; preserve webhook/sole-receiver and native-owner update gates.

#### Scenario: Telegram polling is unavailable while local capacity monitoring is due
- **WHEN** the existing inbox owner cannot poll Telegram
- **THEN** its bounded local observation schedule still runs independently under the same owner, without creating a second daemon, changing business gates or invoking a model.

### Requirement: One authorized current-link card and independent pin result
The system SHALL maintain one registered current-link card through the existing sender, checking source, target, exact payload and current facts before wire. Heartbeat MUST NOT imply business readiness or trading authority. Accepted receipts MUST prevent replacement SEND. Pin uncertainty MUST remain independent of accepted delivery and MUST NOT permit replay or expanded rights.

#### Scenario: Pin permission missing after accepted card
- **WHEN** the accepted status-card bot lacks existing pin rights
- **THEN** retain accepted delivery, record BLOCKED_PERMISSION without changing rights, and permit only the separately human-authorized exact owner pin reservation followed by native readback.

#### Scenario: Business state changes during destination proof
- **WHEN** current independent facts differ from a queued status version
- **THEN** suppress that proven zero-wire version and retain evidence instead of publishing stale readiness; create no second card for uncertain outcomes.


## Acceptance examples

- Seven symbols recover in one observation: seven retained suppressed evidence rows and one pending digest.
- One other protection incident remains open: digest says one unresolved and retains that alert.
- Transaction fails midway: no partial recovery or digest commits; next observation can retry unsent evidence ingestion.
- Earlier alert UNKNOWN: digest waits for reconciliation and never resubmits that alert.

## Evidence boundary

2026-11-10 local implementation and offline checks are separate from deployment and future real broker-recovery acceptance. Native deehub UI and read-only outbox confirmed consecutive #RISK recovery cards (1296–1302, seven symbols at one observation). No deliberate broker fault or test group message is required.


### Current deployment evidence — 2026-11-10
Clouda46921b and loaded Paper producer657d64d were independently observed. Real batches1340/1370 each aggregate seven newly recovered symbols; original per-symbol recoveries remain SUPPRESSED evidence. Actual risk group delivery is NOT_VERIFIED: old STARTED1270–1272 lack trustworthy outcome evidence and block claiming the digest. Engineering event1371/group225 is not a risk receipt. Secretary persistent engineering status was independently read. See docs/production-audit/RISK_RECOVERY_20261110.md; future reconciliation and native acceptance remain separate.

#### Scenario: Proven preflight failure permits explicit current-only refresh
- **WHEN** every prior version has terminal PREFLIGHT_FAILED evidence and no operation, delivery, receipt or transport evidence, and an operator explicitly requests refresh with fresh complete broker proof
- **THEN** retain all version registrations, payloads and attempts; supersede only the old unsent current projection and audit the new version in the same scope. The scope permits at most one transport attempt; STARTED, UNKNOWN and accepted outcomes are never refreshed or replayed. No automatic refresh loop is authorized.
