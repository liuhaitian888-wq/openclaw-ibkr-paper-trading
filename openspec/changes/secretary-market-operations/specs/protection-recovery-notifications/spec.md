## MODIFIED Requirements

### Requirement: Explicit current-state administrative continuation
The system SHALL preserve the unknown delivery outcome of an explicitly scoped historical occurrence when the owner authorizes retiring its dependency. Such a disposition SHALL NOT create a receipt, retry, or historical success/non-delivery conclusion. A separately registered current report SHALL require fresh complete broker evidence and exact scope/content binding; other uncertain protection occurrences SHALL still block it.

#### Scenario: Three archived dependencies and one current summary
- **WHEN** an owner-authorized scope binds1270–1272 by original ID/key/generation/status/raw content and unchanged attempt evidence
- **THEN** retain all three originals intact, retain never-attempted obsolete aggregate history as superseded, and permit only the registered fresh current group summary; do not release old per-symbol queues or automatically mirror private detail.

#### Scenario: Evidence changed or broker readback stale
- **WHEN** authorization/original/attempt evidence changes, another protection outcome is uncertain, or the current epoch/content/freshness no longer matches
- **THEN** the current report is denied before transport and no historical uncertainty is cleared.

#### Scenario: Proven preflight failure permits explicit current-only refresh
- **WHEN** every prior version has terminal PREFLIGHT_FAILED evidence and no operation, delivery, receipt or transport evidence, and an operator explicitly requests refresh with fresh complete broker proof
- **THEN** retain all version registrations, payloads and attempts; supersede only the old unsent current projection and audit the new version in the same scope. The scope permits at most one transport attempt; STARTED, UNKNOWN and accepted outcomes are never refreshed or replayed. No automatic refresh loop is authorized.
