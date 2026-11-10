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

#### Scenario: Configuration rejected before a Telegram claim
- **WHEN** the current private Telegram configuration is invalid or differs from the existing client identity
- **THEN** the regular Telegram owner rejects it before claim and leaves the notification PENDING without creating a new unaudited STARTED.

#### Scenario: Configuration rejected in an already claimed legacy route
- **WHEN** the mixed legacy route has claimed an item but configuration fails before transport entry
- **THEN** append PREFLIGHT_FAILED with transport_entered=false before deferring that unsent attempt, preserve errors after transport as UNKNOWN, and never infer non-delivery of older legacy STARTED records from the new guard.

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

### Requirement: Cloud OAuth startup notice reconciliation
The bounded OAuth adapter SHALL accept only the exact pre-turn CLI notice that Code Mode is unavailable because its host is disabled, only when a public structured result and native turn-completion usage are present. It SHALL retain the notice in usage metadata, reject all other error/native tool events, and preserve earlier UNKNOWN receipts without replay.

#### Scenario: Disabled Code Mode does not mask successful inference
- **WHEN** the exact disabled-host notice precedes turn start and the cloud OAuth turn completes with valid public JSON and usage
- **THEN** the adapter records CODE_MODE_DISABLED and accepts that completed inference without enabling native tools

#### Scenario: Actual errors remain blocking
- **WHEN** another error, a post-start error, native tool execution, or missing turn completion occurs
- **THEN** the attempt remains unacknowledged and is not automatically replayed

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

#### Scenario: Combined broker facts in one readback
- **WHEN** an owner question needs multiple broker datasets together
- **THEN** the registered snapshot tool accepts an explicit bounded section list, returns only the requested datasets from one owned reconciliation window, and avoids account-summary subscriptions when neither account nor cash is requested; source times and non-atomic consistency limits remain explicit.

#### Scenario: Cross-database analysis
- **WHEN** the owner requests analysis across business databases
- **THEN** registered read-only tools expose each registered business database with bounded results and distinguish unavailable databases and stale snapshots from complete current coverage.

#### Scenario: End-to-end latency acceptance
- **WHEN** a fresh Telegram request exercises a model-selected Python broker tool
- **THEN** acceptance records receive, model, tool, archive and native delivery timing and verifies the broker result without claiming an unmeasured speed guarantee.

Historical planning boundary (2026-11-10, before implementation): the owner-confirmed Python broker target was initially unimplemented. This paragraph is not the current runtime state.

Implementation update (2026-11-10 observation): source91f7f64709c76aef1e55f65afa5c918cc5813397 registered and deployed model-selected broker query/result tools on the existing Python broker connection owner, registered read-only service observations, absolute paths for all four business databases, and an unarmed official CLI Cloud-task adapter. Four native database queries and a native engineering broker snapshot succeeded; the latter returned6 positions/6 orders/3 API-window executions/6 account-summary fields in1.226s. Returned summary fields do not establish complete per-currency or settled-cash coverage. The first aggregate-account rejection remains retained as a separate failed query. Full source integration passed1218 isolated offline tests; those tests do not prove native Telegram delivery. The OAuth dialogue loop has its separate verified stage below. Telegram model-selected live broker/private result timing, all development/operations write paths and the intended Codex executor remain incomplete. Owner clarification is pending between the server-hosted OAuth Codex executor, official hosted Codex Cloud, or both; no substitute executor is declared accepted.


## Evidence boundary

This specification records expected behavior, not production acceptance. Source 5df418d passed 1133 isolated offline tests and was deployed; native deehub identity/profile readback succeeded. Cloud API migration is blocked on credentials, Nov9 report1094 remains UNKNOWN, and new natural public-event delivery, phone display and full filing-body analysis remain unaccepted. The change stays active.

### Cloud API implementation stage

Source98cd05a adds the bounded provider, credential input and dormant systemd units. Official model/low support is documented; account credentials and a native model response are still required. The deployed owner remains mac_bridge and the new model service is disabled until acceptance. This stage does not upgrade the evidence boundary above into a claim of cloud dialogue readiness.

### Owner OAuth correction

OAuth is the selected route; API-key instructions above describe superseded preparation. Cloud login, actualgpt-6.1-sol/low access and Mac-disabled native private reply remain required before acceptance.




### Independent OAuth verified stage — 2026-11-09T23:40:14Z
The preceding API and OAuth preparation paragraphs are historical snapshots. Current cloud source71fa3e6 uses independent Gmail ChatGPT OAuth, gpt-6.1-sol/low, with Mac bridge stopped. Fresh owner private update600875499 completed a native model turn in7.833s, archived SUCCEEDED and delivered through existing notification1304 with private message247/serverdate23:40:14Z. Human confirmed seeing actual text. Evidence: cloud engineering/secretary-oauth-20261109/cloud-private-acceptance.json. This verifies the current cloud dialogue loop for that request, not future uptime, live broker model tools, Codex Cloud task execution or all pending tasks in this active change. Earlier UNKNOWN states remain preserved.

Notification continuation: candidate61619c0/8c63c5a retains explicit full group account-report approval, immutable artifacts and append-only reviews. New combined deployment/native report acceptance is recorded separately.
