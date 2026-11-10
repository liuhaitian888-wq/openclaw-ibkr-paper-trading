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

The secretary SHALL implement /api, /cloud and /market as bounded click-scoped live checks through existing owners, reporting passed, failed or timeout instead of snapshot-only uncertainty. Checks SHALL preserve gates, the daily model budget and uncertain attempts without replay, new broker sessions or service restarts.

#### Scenario: Actual routes and matching responses
- **WHEN** the owner clicks /api, /cloud or /market
- **THEN** /api runs one25s nonce-checked model call and an existing-owner broker query, /cloud runs current systemd/SQLite checks, and /market requires realtime bid/ask timestamps after the click; OAuth never requires an API key. Old snapshots are historical, not current proof.

#### Scenario: Requested live check does not complete
- **WHEN** an owner selects a live status entry and the existing owner does not return a valid fresh response within the deadline
- **THEN** the secretary reports timeout or the specific failure for this click, without replaying an uncertain attempt.

### Requirement: Cloud-native deterministic authentication assistance
The verified cloud inbox SHALL own approved fresh Gateway-start controls independently of model inference and a Mac bridge. It SHALL recheck native owner provenance, cutover time and stopped-unit state, record the attempt before transport, and use only a bounded fixed-unit start. Normal Gateway processes SHALL NOT be restarted. Native startup acceptance SHALL NOT imply authentication or trading permission.

#### Scenario: Explicit owner assistance for a stopped Gateway
- **WHEN** a fresh native owner /login_assist request has the approved cloud control owner and the exact service is inactive or failed
- **THEN** the inbox submits at most one bounded start to that existing systemd unit and awaits separate complete fresh Paper readback for authentication success.

#### Scenario: Existing process or unknown startup outcome
- **WHEN** the service is already running or a native start result is uncertain
- **THEN** a running service receives no start/restart, and an uncertain original operation remains UNKNOWN with a separate private outcome notice and no automatic replay.

#### Scenario: Control ownership cutover
- **WHEN** the cloud inbox becomes the Gateway-start owner
- **THEN** it does not adopt old controls before the cutover, cloud models do not consume unsupported transport controls, and Mac-only searches retain their distinct owner.

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

Official hosted executor decision and uncertain submission (observed boundary):
Owner selected the OpenAI official hosted Codex Cloud environment and approved one read-only acceptance chat on2026-11-10. This resolves the earlier executor-choice question. One create_thread submission returned no native task identity; outcome remains UNKNOWN, and absence from recent thread lists does not authorize replay. Current legacy CLI adapter is unarmed and is not verified compatible with the selected saved configuration. End-to-end dispatch and result delivery remain unaccepted.

### Requirement: Ledger domain is distinct from execution provenance
The cloud Python dispatcher SHALL accept work and notifications only as registered search_records ledger domains, while retaining cloud-only execution provenance for all other tools. Local snapshot and Telegram live-source impersonation SHALL remain rejected.

#### Scenario: Model searches existing notification receipts
- **WHEN** a cloud owner run selects search_records with source=notifications or source=work
- **THEN** the registered bounded read-only query executes, archives its result once, and does not claim complete Telegram history.

#### Scenario: Ledger values do not widen other tools
- **WHEN** any other tool supplies source=notifications, or search_records supplies source=local_snapshot
- **THEN** the dispatcher rejects the request without executing it.


### Requirement: Recorded automatic notification target and provenance
The project SHALL record the latest owner target separately from historical routing and deployed acceptance: all noninteractive automatic safe status belongs in deehub, with shared-cause ALERT/escalation/RECOVERY grouping, bounded reminders, stable recovery and no automatic private detail mirror. Private source evidence SHALL remain queryable through verified owner interaction rather than being copied automatically. A planning record SHALL NOT imply runtime changes or new business permissions.

#### Scenario: Fault flood despite recovery grouping
- **WHEN** repeated protection-unknown alerts still use individual private delivery while recoveries are grouped
- **THEN** record both routing and lifecycle gaps as unfinished implementation, retain raw occurrence/attempt evidence and do not claim that clearing old delivery blockers resolves the flood.

#### Scenario: Automatic safe summary contains sensitive source evidence
- **WHEN** automatic status is based on account, authentication or diagnostic evidence
- **THEN** the target group summary uses validated safe fields, retains sensitive originals privately for on-demand interaction and creates no automatic private detail mirror.

#### Scenario: Evidence received from another Codex engineering chat
- **WHEN** another Codex chat reports observations through a cross-thread message following human collaboration authorization
- **THEN** attribute the evidence to that engineering chat, distinguish it from independent verification and do not claim Telegram secretary-originated delivery or an accepted autonomous engineering consumer.

Planning boundary2026-11-10: this target supersedes earlier automatic-private defaults as desired behavior only. Existing sensitivity-first routing, private supervisor notices and RECOVERY-only aggregation remain historical/current implementation until a separately evidenced change. No grouping interval or recurrence root cause is established by this specification update.

Current deployment observation2026-11-10: cloud57452de7f8cf1fee0c27d737b9f38cb9d39dafc7 includes ledger-domain dispatch fix and bounded redacted broker diagnostics. Native engineering work/notifications searches returned2rows each in0.015/0.018s, archived separate run, zero modelcalls/messages. Actual owner504 Telegram→model→Python→DBinventory→nativeprivate391 took50s by native timestamps; broker data failed (unclaimed READY). Existing monitor has persistentattempts4 under same API process generation and CONNECTION_BUDGET_OR_BACKOFF; no budget reset or Gateway restart. Local scanner/secretary constructors pass on private consistent SQLite copy with network disabled; preceding OperationalError root cause remainsUNKNOWN. Inactive-Gateway/login drill, successful fresh Telegram broker data, official hosted Cloud task acceptance, general dev/ops/database writes remain incomplete.
