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

The secretary SHALL expose /api, /cloud and /market as deterministic owner-private controls using existing shared health evidence with observation time and freshness. Missing evidence SHALL be UNKNOWN. Configuration and stale HEALTHY records SHALL NOT prove current connectivity. Menu reads SHALL NOT call models or brokers, restart services or alter gates.

#### Scenario: Existing status evidence is missing or old
- **WHEN** the owner selects an API, cloud or market status menu entry and relevant runtime evidence is missing or expired
- **THEN** the secretary shows UNKNOWN or stale status with observation time and does not create a model or broker connection.

### Requirement: Telegram development and operations orchestration
The secretary SHALL route verified owner development and operations requests to authorized Python operations and a verified Codex Cloud consumer, with task identity, scope, execution receipts and result delivery. Arbitrary database paths, deployment permission and unrestricted shell access SHALL NOT follow from model output alone.

#### Scenario: Development request from Telegram
- **WHEN** the owner requests a code change or an operational task
- **THEN** the secretary records the scope, dispatches only to an authorized verified executor and reports actual progress and verification evidence; an archived proposal alone does not mean Codex Cloud accepted the task.

### Requirement: Secretary Python broker and database access
The secretary SHALL invoke registered Python tools through the existing broker owner and expose all registered business databases with bounded read-only queries and source timestamps. Cached evidence SHALL NOT imply a fresh broker query. Model OAuth, broker authentication and write authorization SHALL remain separate.

#### Scenario: Owner asks for current broker facts
- **WHEN** a verified owner asks for current positions or cash
- **THEN** a registered Python tool queries through the existing broker connection owner, reports source time and incomplete or unavailable results honestly, and creates no competing Gateway or trading permission.

#### Scenario: Cross-database analysis
- **WHEN** the owner requests analysis across business databases
- **THEN** registered read-only tools expose each registered business database with bounded results and distinguish unavailable databases and stale snapshots from complete current coverage.

#### Scenario: End-to-end latency acceptance
- **WHEN** a fresh Telegram request exercises a model-selected Python broker tool
- **THEN** acceptance records receive, model, tool, archive and native delivery timing and verifies the broker result without claiming an unmeasured speed guarantee.

Implementation boundary (2026-11-10): owner-confirmed target, not implemented or deployed by this documentation update. The existing model tool dispatcher exposes registered database queries but no direct live broker tool. Exact latency target and fresh cloud OAuth/model response acceptance remain UNKNOWN.

## Evidence boundary

This specification records expected behavior, not production acceptance. Source 5df418d passed 1133 isolated offline tests and was deployed; native deehub identity/profile readback succeeded. Cloud API migration is blocked on credentials, Nov9 report1094 remains UNKNOWN, and new natural public-event delivery, phone display and full filing-body analysis remain unaccepted. The change stays active.

### Cloud API implementation stage

Source98cd05a adds the bounded provider, credential input and dormant systemd units. Official model/low support is documented; account credentials and a native model response are still required. The deployed owner remains mac_bridge and the new model service is disabled until acceptance. This stage does not upgrade the evidence boundary above into a claim of cloud dialogue readiness.

### Owner OAuth correction

OAuth is the selected route; API-key instructions above describe superseded preparation. Cloud login, actualgpt-6.1-sol/low access and Mac-disabled native private reply remain required before acceptance.
