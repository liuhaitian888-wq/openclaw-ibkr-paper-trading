## ADDED Requirements

### Requirement: Deterministic severe event engineering task
The existing capacity owner SHALL reconcile exact persisted severe event/outbox evidence into the existing engineering queue, without new notifications, automatic model execution or fabricated USER authority. Processing SHALL be bounded to eight occurrences per tick, 128 retained tasks and a four KiB cursor. Warning/severe oscillation within an unresolved risk episode SHALL retain the first severe task identity; only an explicit OK transition ends that episode.

#### Scenario: Delivered historical severe event followed by warning
- **WHEN** a real severe event exists but the latest capacity state is warning
- **THEN** one SYSTEM read-only diagnostic task exists with original event identity and content fingerprint, and current risk is shown separately.

#### Scenario: Crash or source mutation
- **WHEN** destination commit succeeds before cursor save fails, or an occurrence changes content
- **THEN** restart deduplicates the former and blocks the latter for reconciliation without replacing evidence or replaying notification.

### Requirement: Explicit protected engineering claim
Claims SHALL bind task identity, payload fingerprint and operator; source evidence SHALL be revalidated. Only queued tasks may start; STARTED and UNKNOWN SHALL never be automatically replayed. Secretary visibility SHALL distinguish queued, claimed, diagnosed and unknown from native model acceptance and desktop wakeup.

#### Scenario: Uncertain task and capacity recovery
- **WHEN** a task is UNKNOWN and disk recovers
- **THEN** it remains UNKNOWN and no new execution or deletion is authorized.

#### Scenario: Severity oscillation
- **WHEN** warning and severe levels alternate before an explicit OK transition
- **THEN** the original engineering task identity and any UNKNOWN state remain unchanged.
