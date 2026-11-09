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
The system SHALL deliver classified public automatic updates and research/task progress to deehub. Private account, security, immediate-control and interactive content SHALL use verified owner private delivery. The owner-approved full account-report group policy SHALL be explicit and separate. Unclassified model prose SHALL remain private with a fixed public status card. Existing uncertain sends SHALL NOT be replayed or copied.

#### Scenario: Research and task updates
- **WHEN** a new automatic research result or task progress notification is ready
- **THEN** the classified public result or fixed public progress card is delivered to deehub, while private or unclassified details use verified owner private delivery; a status card is not represented as a full research report.

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

Implementation boundary: the Nov10 continuation implements classification, immutable enqueue artifacts, append-only attempts/reviews and a bounded single-owner supervisor. The owner explicitly selected full account reports in deehub for all members. Native labels/ephemeral UI and full source-body public research acceptance remain pending. Source, offline and deployment/native receipts are separately recorded; this specification is not deployment acceptance.

### Requirement: Immutable notification artifact identity
The system SHALL preserve the exact report PNG and manifest bytes selected at enqueue, record every delivery attempt separately, and retain historical provenance when mutable previews change. Changed or missing historical bytes SHALL NOT be relabeled as the original artifact.

#### Scenario: Builder updates a queued report preview
- **WHEN** the report builder replaces a date-based PNG after enqueue
- **THEN** the queued send reads its frozen content-addressed artifact and historical hashes remain unchanged.

#### Scenario: Definitive rejection without proven root recovery
- **WHEN** Telegram rejects a send but the root cause remains unverified
- **THEN** the original evidence remains retained and no automatic retry occurs solely because connectivity returned.


## Evidence boundary

This specification records expected behavior, not production acceptance. Source 5df418d passed 1133 isolated offline tests and was deployed; native deehub identity/profile readback succeeded. Cloud API migration is blocked on credentials, Nov9 report1094 remains UNKNOWN, and new natural public-event delivery, phone display and full filing-body analysis remain unaccepted. The change stays active.

### Cloud API implementation stage

Source98cd05a adds the bounded provider, credential input and dormant systemd units. Official model/low support is documented; account credentials and a native model response are still required. The deployed owner remains mac_bridge and the new model service is disabled until acceptance. This stage does not upgrade the evidence boundary above into a claim of cloud dialogue readiness.
