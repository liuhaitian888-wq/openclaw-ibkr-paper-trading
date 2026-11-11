## Context
Use docs/CAPACITY_ENGINEERING.md for actual evidence and quantitative initial thresholds. Current source stage is separate from deployment. Historical1.86GB copies are not live DBs or verified duplicates.

## Goals / Non-Goals
Expose capacity to the secretary and existing sender within explicit I/O/row/storage budgets. Do not clean, recover, change business permissions or reassign the P0 SQLite owner.

## Decisions
Use one fixed JSON ring and kernel sampler lock; existing inbox invokes every5min. Nine fixed DB metadata probes share80ms/DB budgets; unknown counts staynull. File metadata discovery is hourly250ms/20kentries. Growth needs same-identity continuous evidence >=1h. Persist incident transition cursor/outbox atomically; queries are snapshot-only. Ordinary transitions remain in incident_events; only critical actionable transitions enter the existing owner-private sender, per the newer human policy. The old public group patch is not deployed.

## Risks / Trade-offs
Bounded reads may time out under normal locks; UNKNOWN is explicit. OS filesystem I/O is not hard-real-time. Linear forecasts can be distorted by backups. No offsite backup or historical deduplication claim. Existing raw callback and health tables remain untrimmed pending semantic owner work.

## Migration Plan
No businessschema migration. Publisher validates the current combined tree with the critical-private / routine-archive producer, preserves gates/rollback and reloads only authorized existingowner. Observe first snapshot/health and native group receipt; do not manufacture a disk fault or reuse consumedscope.
