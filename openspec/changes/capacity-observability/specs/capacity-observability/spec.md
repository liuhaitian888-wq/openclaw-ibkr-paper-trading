## ADDED Requirements

### Requirement: Passive bounded capacity evidence
The existing secretary observation owner SHALL sample at most once every300seconds and retain at most288samples in a self-owned JSON file limited to1MiB. SQLite metadata reads MUST use mode=ro/query_only,80ms per-DB execution and10ms lock budgets with closing connections. OAuth metadata SHALL NOT expand SQL access. Hourly discovery SHALL stop at250ms/20000entries and32 unregistered candidates, preserving uncertainty.

#### Scenario: Count is unavailable or a new file appears
- **WHEN** a count exceeds its deadline, a DB is locked or discovery finds an unregisteredSQLite
- **THEN** count remains UNKNOWN and the file requires identity review; it is not silently promoted to a live SQL target or repaired.

### Requirement: Evidence-qualified capacity risk
The sampler SHALL report available/DB/WAL/SHM/page bytes, fixed-table row growth and notification anomaly-event growth. Forecasts MUST require positive consumption across >=1hour, same filesystem and gaps<=900seconds; DB rates additionally require inode continuity. Visible quantitative thresholds SHALL be markedprovisional. Lowering risk requires3continuous headroom samples; escalation is immediate.

#### Scenario: Only an initial79percent snapshot exists
- **WHEN** free space is7.78GiB and historical rate evidence is insufficient
- **THEN** the current space policy may warn, but growth and days-to-full remain UNKNOWN and no deletion or purchase is authorized.

### Requirement: Existing owners and safe public summaries
The CAPACITY module SHALL use the shared registry with900second expiry, and secretary reads SHALL only read stored evidence. Transition/event/cursor updates MUST be atomic. Ordinary warnings/recoveries SHALL remain local without OPEN incidents or delivery entries. Only critical actionable alerts SHALL enter the existing owner-private outbox; STARTED/UNKNOWN transport outcomes MUST NOT replay.

#### Scenario: Crash between snapshot and event publication
- **WHEN** the producer saves a pending snapshot but stops before writing its outbox event
- **THEN** the next owner tick reconciles the pending transition exactly once using its existing atomic cursor, without replaying any prior transport attempt.

### Requirement: Semantic storage governance without unapproved cleanup
Order, execution, risk, task-state, receipt and UNKNOWN evidence SHALL remain persistent. Retention proposals SHALL distinguish source identity, occurrence and content fingerprints, and SHALL specify recoverable copies, dependency/provenance and restoration evidence per candidate. File age, same filename/size, absent strategyintent or freeSQLite pages MUST NOT authorize deletion. Production cleanup requires an explicitly approved itemized list.

#### Scenario: Multiple historical1.86GB audit copies dominate disk
- **WHEN** metadata reveals historicalcopies with similar sizes but unverifiedhashes or restoration equivalence
- **THEN** list them as REVIEW_REQUIRED with approvedreclaimbytes0, preserve them, and report source/offline/deployment/native acceptance separately.
