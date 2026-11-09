# secretary-engineering-review Specification

## Purpose

Give the owner a recurring evidence-based engineering review in the authorized automatic-update group and editable Codex handoff, with honest delivery and integration status and bounded authority for autonomous research.

## Requirements


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

### Requirement: Owner-selected independent ChatGPT OAuth
The system SHALL support the owner-selected Hetzner ChatGPT OAuth provider through the official Codex CLI using a fresh cloud login. It SHALL NOT require an API key, copy the Mac auth cache, automatically fall back to another authentication method, or grant native model tools. API-key preparation remains inactive historical work.

#### Scenario: Fresh cloud device authorization
- **WHEN** the owner completes the official device-code flow for the cloud login
- **THEN** credentials persist only in the private cloud OAuth home and the official CLI owns token refresh; model availability still requires a completed inference.

#### Scenario: API-key cache or missing OAuth
- **WHEN** the cloud credential is absent, insecure or not ChatGPT OAuth
- **THEN** the provider refuses before claiming work and does not switch to API-key authentication.

#### Scenario: Uncertain OAuth model turn
- **WHEN** the cloud Codex inference fails without a completed acknowledged turn
- **THEN** the attempt is retained for reconciliation and is not automatically replayed, while trading gates remain unchanged.

## Evidence boundary

This specification records expected behavior, not production acceptance. Source 5df418d passed 1133 isolated offline tests and was deployed; native deehub identity/profile readback succeeded. Cloud API migration is blocked on credentials, Nov9 report1094 remains UNKNOWN, and new natural public-event delivery, phone display and full filing-body analysis remain unaccepted. The change stays active.

### Cloud API implementation stage

Source98cd05a adds the bounded provider, credential input and dormant systemd units. Official model/low support is documented; account credentials and a native model response are still required. The deployed owner remains mac_bridge and the new model service is disabled until acceptance. This stage does not upgrade the evidence boundary above into a claim of cloud dialogue readiness.

### Owner OAuth correction

OAuth is the selected route; API-key instructions above describe superseded preparation. Cloud login, actualgpt-6.1-sol/low access and Mac-disabled native private reply remain required before acceptance.
