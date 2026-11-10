## ADDED Requirements

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
