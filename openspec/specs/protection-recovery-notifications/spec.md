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

## Acceptance examples

- Seven symbols recover in one observation: seven retained suppressed evidence rows and one pending digest.
- One other protection incident remains open: digest says one unresolved and retains that alert.
- Transaction fails midway: no partial recovery or digest commits; next observation can retry unsent evidence ingestion.
- Earlier alert UNKNOWN: digest waits for reconciliation and never resubmits that alert.

## Evidence boundary

2026-11-10 local implementation and offline checks are separate from deployment and future real broker-recovery acceptance. Native deehub UI and read-only outbox confirmed consecutive #RISK recovery cards (1296–1302, seven symbols at one observation). No deliberate broker fault or test group message is required.


### Current deployment evidence — 2026-11-10
Clouda46921b and loaded Paper producer657d64d were independently observed. Real batches1340/1370 each aggregate seven newly recovered symbols; original per-symbol recoveries remain SUPPRESSED evidence. Actual risk group delivery is NOT_VERIFIED: old STARTED1270–1272 lack trustworthy outcome evidence and block claiming the digest. Engineering event1371/group225 is not a risk receipt. Secretary persistent engineering status was independently read. See docs/production-audit/RISK_RECOVERY_20261110.md; future reconciliation and native acceptance remain separate.
