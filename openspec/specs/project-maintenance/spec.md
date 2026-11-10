# 买der 项目维护规范

## Purpose
保留本项目独立身份、证据适用范围及开发任务收尾规则。维护把历史设计、当前实现和未来提案分别记录，使规格、文档和受影响图表能随实际变更同步；本规范不表示历史产品架构已经全部融合或真实验收。

## Requirements
### Requirement: Independent project evidence
The project SHALL retain its own source, offline verification, deployment and acceptance evidence under project ID `buy-der`.

#### Scenario: Historical record has no current verification
- **WHEN** a historical digest claims completion without current source or runtime evidence
- **THEN** maintenance retains the record and marks current verification UNKNOWN

### Requirement: Task completion maintenance
The project SHALL synchronize relevant specs, context and affected diagram provenance when an authorized development task changes source or design, while preserving existing permissions and unrelated work.

#### Scenario: No project change
- **WHEN** a conversation ends without source or design content changes
- **THEN** no maintenance continuation is requested and no timer is created

#### Scenario: Changed project source
- **WHEN** an authorized task changes project source or design
- **THEN** task closeout checks OpenSpec deltas, context and affected diagrams once and records actual verification limits

### Requirement: Stable secret snapshot identities
Secret scanning SHALL preserve repository-relative finding identities when scanning a temporary snapshot, honor only existing explicit false-positive decisions, retain redaction, and block remaining findings.

#### Scenario: Exact dependency hash false positive
- **WHEN** a source hash has been recomputed and documented with an exact relative file/rule/line fingerprint
- **THEN** temporary snapshot scanning uses that same relative identity without adding a broad rule or file exclusion

#### Scenario: Other scanner finding
- **WHEN** the scanner returns a remaining finding in a tracked or untracked nonignored file
- **THEN** the stop hook blocks completion with redacted diagnostic output

### Requirement: Offline backup copy verification
The project SHALL provide bounded offline verification of a minimal four-database backup archive. It SHALL reject ambiguous or unsafe archive members, validate declared hashes and read-only SQLite copies in a new private directory, and preserve originals and failure evidence. A successful copy check SHALL NOT authenticate its source, establish cross-database business consistency or authorize live restoration.

#### Scenario: Existing snapshot copied to another host
- **WHEN** a complete declared backup archive passes byte limits, checksums and read-only SQLite checks
- **THEN** a private receipt records the individual checks while restoration and source authentication remain ungranted.

#### Scenario: Unsafe or corrupt archive
- **WHEN** an archive has unexpected paths or links, duplicate members, incomplete manifest, excessive expansion or corrupt SQLite
- **THEN** verification fails without overwriting existing data, restoring live state or deleting originals; checker-owned partial outputs remain distinct.
