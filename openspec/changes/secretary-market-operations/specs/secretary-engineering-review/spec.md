## Purpose
Give the owner a recurring private evidence-based engineering review and editable Codex handoff, with honest delivery and integration status and bounded authority for autonomous research.

## ADDED Requirements

### Requirement: Weekly engineering prompt
The system SHALL generate at most one scheduled owner-private engineering review per local ISO week, with explicit evidence freshness, unresolved blockers, bounded proposals, and an editable Codex prompt. It SHALL NOT claim missing evidence or research as completed work.

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

### Requirement: Bounded public filing explanations
The system SHALL publish only validated public SEC filing metadata through a fixed explanation template to deehub. Arbitrary model research, account details and payload prose SHALL remain private. The explanation SHALL identify unparsed financial information and SHALL NOT claim that the filing body was analyzed.

#### Scenario: Valid public filing with private prose
- **WHEN** a validated SEC filing notification also contains arbitrary private prose
- **THEN** the group receives only fixed metadata explanations, source and publication time without that prose.

#### Scenario: Unapproved source or model research
- **WHEN** a notification has an unapproved SEC URL or is a private model research result
- **THEN** it remains owner-private and is not eligible for public group delivery.

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
