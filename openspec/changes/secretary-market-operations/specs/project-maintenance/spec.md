## ADDED Requirements

### Requirement: Stable secret snapshot identities
Secret scanning SHALL preserve repository-relative finding identities when scanning a temporary snapshot, honor only existing explicit false-positive decisions, retain redaction, and block remaining findings.

#### Scenario: Exact dependency hash false positive
- **WHEN** a source hash has been recomputed and documented with an exact relative file/rule/line fingerprint
- **THEN** temporary snapshot scanning uses that same relative identity without adding a broad rule or file exclusion

#### Scenario: Other scanner finding
- **WHEN** the scanner returns a remaining finding in a tracked or untracked nonignored file
- **THEN** the stop hook blocks completion with redacted diagnostic output
