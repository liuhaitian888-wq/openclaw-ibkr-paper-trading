# Protection recovery notifications

## Purpose

Preserve per-symbol protection evidence while grouping newly resolved incidents into one bounded recovery digest through the existing sender, without replaying uncertain outcomes.

## Requirements

A complete broker observation MUST create at most one protection recovery digest for newly resolved symbol incidents. Initial healthy observations without an open incident and repeated identical observations MUST NOT generate a recovery message.

Original events, incident generations and symbol RECOVERY records MUST remain queryable. Individual recoveries MUST become SUPPRESSED atomically with digest creation, before any sender can claim them. SUPPRESSED MUST NOT imply Telegram acceptance. The digest MUST reference member event and notification identities, distinguish protected symbols from closed no-exposure faults, and state remaining unresolved protection count/symbols. It MUST NOT grant trading permission.

New/ongoing risk alerts MUST retain existing escalation and reminder handling. Existing STARTED/UNKNOWN attempts and receipts MUST remain intact; a digest MUST NOT be claimed while an earlier member occurrence notification is unresolved. No historical queued recovery rewrite or replay is authorized.

The existing notification worker remains the sole delivery owner. Account detail uses the current privacy decision; a public fixed summary must be rebuilt from validated bounded fields rather than arbitrary account payload prose.

## Acceptance examples

- Seven symbols recover in one observation: seven retained suppressed evidence rows and one pending digest.
- One other protection incident remains open: digest says one unresolved and retains that alert.
- Transaction fails midway: no partial recovery or digest commits; next observation can retry unsent evidence ingestion.
- Earlier alert UNKNOWN: digest waits for reconciliation and never resubmits that alert.

## Evidence boundary

2026-11-10 local implementation and offline checks are separate from deployment and future real broker-recovery acceptance. Native deehub UI and read-only outbox confirmed consecutive #RISK recovery cards (1296–1302, seven symbols at one observation). No deliberate broker fault or test group message is required.
