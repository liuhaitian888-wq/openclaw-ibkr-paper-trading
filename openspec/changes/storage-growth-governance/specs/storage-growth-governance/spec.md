## ADDED Requirements

### Requirement: Protect core state and control optional new bytes
An approved nontrading policy SHALL gate public research/directory writes before DB creation, task claim or network intake. It MUST preserve queued/UNKNOWN and core order/risk/task/receipt data. Floor8GiB/28percent, class quotas256/64MiB and per-blob5/2MiB SHALL be explicit; partial inventory or invalid policy MUST defer optional writes. Differing prior source content MUST NOT be overwritten. Additional optional engineering preparation SHALL follow its separate noncore budget below.

#### Scenario: Research timer fires under current disk pressure
- **WHEN** policy is armed and available space is about6.72GiB
- **THEN** optional intake returnsDEFERRED before DB/network work; existing core workers, data and trading permissions remain unchanged.

### Requirement: Single-owner bounded evidence
The existing capacity owner SHALL observe the optional budget through the shared health registry with900second freshness. New diagnostic evidence SHALL stay within128events/64KiB; secretary reads SHALL use stored data without triggering scans/writes. OAuth internal capacity metadata SHALL be stat-only, without SQLite connection or model content grants.

#### Scenario: Policy disappears or becomes unreadable
- **WHEN** policy is unarmed or budget evidence is unknown
- **THEN** record disabled/unknown optional budget separately from valid core capacity evidence and do not create a second observer or permission recovery callback.

### Requirement: Finite verified local archive
Local copies SHALL use explicit public-artifact allowlists,5GiB total quota and100GiB free floor by default. Plans MUST bound paths32/files512MiB, chunks1MiB and batches128MiB/60seconds. Source identity and chunk checksums SHALL precede durable checkpoints. Read-only transport interruption MAY resume explicitly; changed source or corrupt content MUST require reconciliation. Core runtime MUST NOT depend on Mac availability.

#### Scenario: A two-part copy is interrupted
- **WHEN** the first finite batch endsPARTIAL and source identity is stable
- **THEN** the next explicit batch reuses verified chunks, advances exact offsets, and local quarantine byte reconstruction can be independently checksum-verified without activating any DB.

### Requirement: Cleanup is review-only
The archive interface MUST NOT delete sources. Dry-run output SHALL state candidates, blockers and approvedreclaimbytes0. Order/risk/task/UNKNOWN/receipts, internal credentials and historical backup/migration sources SHALL remain protected and outside this version's public-artifact whitelist.

#### Scenario: Source and local bytes match
- **WHEN** a public artifact passes copy and byte-restore checks
- **THEN** retain its source and require provenance/reference reconciliation plus explicit itemized owner approval before any separate cleanup task.

### Requirement: Admission precedes optional engineering copies
New optional engineering preparation SHALL apply the existing approved8GiB/28percent policy with128MiB reserve and512MiB development quota before reservation, child/canary/model execution or source/repository/worktree creation. The prepare entry SHALL recheck the decision. Partial bounded inventory SHALL defer. Existing STARTED/UNKNOWN reconciliation and ordinary replies/core persistence SHALL remain independent.

#### Scenario: Insufficient space for a new source task
- **WHEN** a new authorized scope is queued but its optional snapshot budget is insufficient
- **THEN** the task stays queued, its one-shot opportunity is not consumed, and no source archive or child starts.

### Requirement: Sole publisher binds retained artifact preflight
The sole publisher SHALL apply explicit projected artifact bytes before upload and before backup creation, retain the original peak guard and mandatory liveDB backups, and refuse nonessential waves exceeding256MiB or leaving less than2GiB available. External scripts SHALL not be described as controlled until the actual owner binds and verifies this entry. Content reuse SHALL not be claimed by B1.

#### Scenario: A projected oversized release
- **WHEN** backup, input/fetch, source bundle, additional artifact estimates and overhead exceed the wave budget
- **THEN** the optional release defers without deleting history or skipping required recovery copies.
