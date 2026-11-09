## Purpose
Give the owner a recurring evidence-based engineering review in the authorized automatic-update group and editable Codex handoff, with honest delivery and integration status and bounded authority for autonomous research.

## ADDED Requirements

### Requirement: Weekly engineering prompt
The system SHALL generate at most one scheduled engineering review in the authorized automatic-update group per local ISO week, with explicit evidence freshness, unresolved blockers, bounded proposals, and an editable Codex prompt. It SHALL NOT claim missing evidence or research as completed work.

#### Scenario: Repeated weekly check
- **WHEN** the due check runs again within the same scheduled ISO week
- **THEN** the same report occurrence is retained without duplicate notification.

### Requirement: Proactive value investing research
The secretary SHALL prioritize valuation, quality, margin of safety, portfolio and protection calibration, and valid historical testing while recording data limitations, fees, lookahead and survivorship risks. Research proposals SHALL NOT grant broker or deployment permissions.

#### Scenario: Inadequate historical data
- **WHEN** a proposed centuries-long or multi-asset test lacks point-in-time data
- **THEN** the secretary identifies the missing dataset and proposes bounded validation instead of inventing returns.

### Requirement: Honest Codex handoff
The system SHALL distinguish archived engineering prompts from an accepted Codex turn and completed implementation; native owner instructions and model-generated suggestions SHALL retain separate provenance.

#### Scenario: No connected consumer
- **WHEN** an engineering packet is generated without a verified Codex consumer
- **THEN** the owner receives a copyable prompt and the state SHALL NOT claim that Codex was woken or work completed.

### Requirement: Honest message receipt
The secretary SHALL distinguish durable receipt from confirmed model execution and SHALL disclose the current Mac bridge dependency while cloud API access is unavailable. An acknowledgement SHALL NOT claim analysis has started solely because a message was stored.

#### Scenario: Model dependency unavailable
- **WHEN** an owner instruction is stored without confirmed model execution
- **THEN** the acknowledgement describes receipt and pending processing without promising an executing analysis or guaranteed response time.

### Requirement: Owner-authorized automatic update routing
The system SHALL deliver noninteractive automatic notifications, delegated task progress and completion, research reports, market intelligence and weekly engineering reviews to deehub when automatic_updates_to_group is approved. Interactive CHAT/ACK/CONTROL/AUTH replies and explicit requires_response requests SHALL use the verified secretary interaction destination. Credentials SHALL remain redacted. Existing uncertain sends SHALL NOT be replayed or copied.

#### Scenario: Research and task updates
- **WHEN** a new automatic research result or task progress notification is ready
- **THEN** it is delivered to deehub with its substantive result, without requiring fixed SEC metadata.

#### Scenario: Immediate response required
- **WHEN** a message is an interactive reply, authentication request or explicitly requires a response
- **THEN** it uses the verified secretary interaction destination and never falls back to the group.

### Requirement: Cloud model ownership and credential boundary
The system SHALL use a dedicated private credential for gpt-6.1-sol with low reasoning on Hetzner when cloud ownership is activated. It SHALL retain the existing inbox, delivery and tool permission boundaries, deny Mac claims after cutover, and never automatically replay uncertain model attempts or pre-cutover checkpoints.

#### Scenario: Missing cloud credential
- **WHEN** the dedicated credential is absent, public-readable or invalid
- **THEN** the cloud model owner refuses before claiming a task and does not report a successful API connection.

#### Scenario: Unacknowledged inference
- **WHEN** a model request times out or lacks a valid native completed response
- **THEN** its attempt remains UNKNOWN with sanitized diagnostics and cannot be automatically replayed.

#### Scenario: Mac-independent acceptance
- **WHEN** a fresh owner-private instruction is processed with the Mac bridge disabled
- **THEN** acceptance requires a cloud model response receipt, archived result and native private Telegram delivery receipt, rather than service liveness or an ACK.

### Requirement: Evidence-based notification recovery and private-data boundaries
The system SHALL classify private account/security/immediate-gate content before public delivery and retain append-only occurrence/attempt evidence. Secretary assessment SHALL NOT authorize replay from missing receipts or network recovery alone. Display tags SHALL NOT grant data/control access; account report sharing requires an explicit recipient policy.

#### Scenario: Lost receipt after a possible send
- **WHEN** a notification is UNKNOWN and no native acceptance or definitive rejection is proven
- **THEN** its evidence and uncertainty survive restart, a bounded private review may explain the gap, and the original send is not automatically replayed.

#### Scenario: Confirmed unsent public report after recovery
- **WHEN** trusted evidence proves an occurrence was not sent, dependencies recover and the report remains valid
- **THEN** the existing sender may create one authorized linked retry with a short public explanation and separately recorded owner-private result notice.

#### Scenario: Display label versus authorized reader
- **WHEN** a group member changes a tag or a private report is requested through an ordinary group message
- **THEN** the label does not confer access and existing owner-private control requirements remain enforced.

Implementation boundary: this requirement is planned in the active change. Current source3694676 does not implement complete sensitivity classification, per-attempt reconciliation supervision or ephemeral UI. Existing account report recipients are unchanged pending owner decision; this specification is not deployment acceptance.

### Requirement: Owner-private status menu

The existing secretary SHALL expose /api, /cloud and /market as deterministic owner-private controls. They SHALL read existing real runtime observations through the shared health resolver, show observation time and freshness, and fail UNKNOWN for unavailable evidence. Old HEALTHY records SHALL NOT imply current availability. Provider configuration and cloud host snapshots SHALL be distinguished from successful model calls and live Telegram reachability. Menu reads SHALL NOT create broker sessions, call models, restart services or alter trading gates.

#### Scenario: Existing status evidence is missing or old
- **WHEN** the owner selects an API, cloud or market status menu entry and relevant runtime evidence is missing or expired
- **THEN** the secretary shows UNKNOWN or stale status with observation time and does not create a model or broker connection.
