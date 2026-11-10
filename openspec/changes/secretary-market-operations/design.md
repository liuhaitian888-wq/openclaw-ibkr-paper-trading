# Design

## Context
Existing cloud inbox is the sole Telegram input owner and notification outbox is the sole delivery path. Trading remains independently gated. See proposal.md for motivation.

## Goals / Non-Goals
**Goals:** Lightweight, durable market awareness and private engineering review without new broker subscriptions or a second Telegram sender.
**Non-Goals:** Enabling full trading, changing stops, or treating scheduled closures as outages. Large-scale extreme-event execution remains deferred.

## Decisions
- Store reviewed official annual holiday exceptions and phase profiles in a versioned JSON manifest. Runtime uses Python zoneinfo and stdlib only; no heavy pandas import in the fast inbox. Calendar coverage ends explicitly at the last reviewed date. Compare exchange_calendars as a research source, not an unverified substitute for ETFplus phases or new Italian 2027 rules.
- Model scheduled phases separately from runtime API health, halts and entitlement. ETFplus random auction ends are disclosed and use a conservative 30-second guard before declaring the next phase.
- Persist per-venue cursor and outbox enqueue atomically in recovery.sqlite3; emit only current state after restart and disclose gaps. Ordinary polling is bounded; no historical alert replay.
- Generate owner-private weekly engineering packet Sunday 18:00 Europe/Berlin using immutable archive evidence and explicit coverage limits. Existing financial weekly reports remain separate. Scheduled Codex review is a separate app automation and cannot silently deploy.
- Reuse engineering proposal archive; copyable prompt is valid fallback until an official Codex consumer is independently verified. Keep model proposals lower authority than native owner instructions.

## Risks / Trade-offs
- Official calendar revisions → provenance URL, verification date, bounded validity, stale notice, review task.
- Instrument ticker ambiguity → explicit EQQQ contract and venue binding only; no connected-account positions copied into Paper.
- Host downtime → one current-state message, not stale phase replay.
- Large weekly payload → bounded evidence and private prompt artifact; delivery receipt is separate from report generation.
- Concurrent deployments invalidate finite scopes → merge only through Git, test combined source, reconcile scope dependencies without increasing authorization.

## Migration Plan
Offline verification in linked worktree, secret scan, Git merge into designated workspace, quick smoke, approved cloud code deployment with identity manifests and finite-scope reconciliation. Rollback disables only the new producer, retains outbox and cursor evidence, and never restarts trading.

## 2026-11-09 deehub route correction

Reviewed group title transition der → deehub retains exact native group, bot and owner identity. MARKET_SESSION only becomes public when checked-in calendar reconstruction matches occurrence/phase/version/expiry; group rendering ignores producer prose. Calendar-review and unrecognized events remain private. Inbox acknowledgements explicitly mean durable receipt/queue, with current Mac model dependency disclosed. Cloud API migration and source-linked public research explanations remain future work; do not infer authorization or implementation from these goals.

New SEC_EDGAR filing notifications may publish bounded validated accession/SEC URL/form/symbol/time with three fixed Chinese points: occurrence, document meaning, and unparsed financial/causality gaps. Arbitrary headline/model prose and broker/provider-only records remain private. No prior notices are replayed. This is metadata explanation, not filing-body financial analysis.

## Cloud model API migration — 2026-11-09

Reuse the bounded existing executor with injected cloud Responses inference/RPC. Fixed gpt-6.1-sol/low; native tools disabled, JSON host tools retain the same permission boundary. Root0600 credential entered through an interactive SSH getpass installer and supplied with systemd LoadCredential. Existing Telegram receiver/sender remain sole owners. Persist model_owner and cutover timestamp; deny Mac claims after switch and never resume pre-cutover READY/STARTED via a new provider. Per-turn public response receipts precede archive finalization, UNKNOWN never auto-replays. Credentials/account access and actual Mac-independent private reply are acceptance blockers until directly verified. Shared health registry gains provider-conditional credential dependency; file readability alone is not API authentication.

## Notification recovery implementation — Nov10

Sensitivity-first access decisions precede transport/render. Full financial-report group delivery has explicit owner approval shared_group; other account/security/immediate-control/interactive content stays owner-private. Fixed calendar/SEC public subsets are reconstructed; unclassified model result details remain private with a separate public status card. Membership versions separate display tags from public-data capabilities, with owner-native private admission only and no account/control delegation. Native tags and ephemeral remain unenabled.

Enqueue snapshots PNG/JSON manifests with content addressing, exclusive publication and fsync; old mutable source bytes are retained as provenance, never substituted for historical fingerprints. Private recovery.sqlite3 retains per-attempt exact envelope, pre-wire target/content/policy, stage/error class/receipt events, deterministic evidence reviews and one retry authorization per original. Existing sender lock serializes one supervisor pass at startup/every10s; a rotating cursor bounds work, no extra worker. The model receives a read-only evidence tool. Reliable ACK repairs projections; recorded pre-wire failure or elapsed explicit RetryAfter may create one fresh, exact, valid linked send after native target verification. BadRequest/Forbidden root recovery is not inferred; UNKNOWN/STARTED/timeout/missing receipt never proves unsent. Supervisor notices have separate deduped private outbox records and do not recursively supervise themselves.

Rollback preserves new audit tables and immutable files; no destructive migration, marker reset or uncertain replay. Existing backup inventory covers recovery.sqlite3; this change also adds hash-verified frozen PNG/manifest copies to its existing backup owner. Legacy mutable reports are explicitly not included or reconstructed. Metadata rename/description actor identity does not establish its editing client; retained provenance stays UNKNOWN.

## Owner correction: ChatGPT OAuth, not API Key

The owner explicitly selects independent Hetzner ChatGPT OAuth. Retain the inactive API-key preparation as historical provenance; do not request a key or infer permission to copy Mac auth. Official Codex CLI0.167.0 is pinned from the verified official npm artifact; fresh device-code login persists only in the cloud OAuth home. Reuse the same bounded executor and claim-owner resolver withcloud_oauth/codex_oauth, preserve the cutoff for legacy checkpoints and private delivery routing. Cloud inference forces ChatGPT auth and disables native tools/dependency installation and provider retries; CLI alone owns token refresh. New OAuth model unit conflicts with API unit and stays unarmed until login, native model/low validation and controlled cutover. Account/model entitlement and native Mac-disabled reply remain independent acceptance gates.

## Python broker/data tools — owner target, 2026-11-10
Target: verified Telegram instruction → secretary model → bounded Python dispatcher → existing IB Gateway owner → IBKR → archived result → existing Telegram sender. Reuse the existing broker connection owner; do not create a competing worker or bypass reconciliation. All registered business databases remain accessible through bounded read-only tools, with source age and availability. Measure receive/model/tool/archive/delivery stages before selecting optimizations; no latency SLO has been agreed. This update adds no implementation. Current registered model tools read databases but do not issue live broker queries. OAuth authenticates model access separately from Gateway authentication; prior API-key preparation is not the selected requirement. Current service liveness and a Mac bridge process do not prove fresh OAuth/model/broker acceptance.

Owner active-goal clarification: Telegram shall orchestrate the complete authorized development/operations paths through Python, IB Gateway/IBKR, Codex Cloud and all business databases. Codex Cloud is an execution branch, not a broker transport hop. Current verified executor connectivity, allowed operations and write/deployment scope remain UNKNOWN until implementation and receipts; this maintenance deploys none of them.


## Risk deployment and closeout evidence — 2026-11-10

Independent source/runtime evidence is docs/production-audit/RISK_RECOVERY_20261110.md. Cloud a46921b runs the previously loaded657d64d Paper recovery producer and corrected sender. Actual1340/1370 batches each contain seven recoveries; their individual recovery evidence is SUPPRESSED. Legacy STARTED1270–1272 continue to block native digest delivery. A visible engineering card1371/group225 is not risk acceptance. Secretary SYSTEM ENGINEERING_STATUS is persisted, not inferred from an ACK. Future real risk delivery remains unchecked.

The closeout scanner snapshots tracked and untracked nonignored files. Its temporary absolute source prefix prevented seven existing exact false-positive fingerprints from matching. Run gitleaks from the snapshot root with source `.`; copy the existing precise .gitleaksignore, retain redaction and blocking on other findings. All seven flagged values were independently recomputed SHA-256 source dependencies. No rule/file-wide exclusion, credential allowance, hook disable or diagram receipt rewrite is introduced.

## Python execution implementation evidence — 2026-11-10
The earlier owner-target section describes the pre-implementation boundary. Runtime source91f7f64 now registers broker query/result and read-only systemctl tools, four DB absolute paths and a dormant official CLI Cloud-task adapter. The existing SDK owner processed native engineering snapshotv2 in1.226s with exact Paper identity and bounded source scope; v1 remains UNAVAILABLE, not replayed. Telegram end-to-end tool selection/private delivery, full operations writes/deployment/migrations and a verified developer executor remain open. The official CLI sees no concrete hosted environment; owner clarification between Hetzner-hosted Codex, official hosted Codex Cloud or both is pending. Do not turn the query-layer timing into a Telegram SLO or infer full cash coverage from six returned base-currency fields. The architecture source diagram shows these branches, with the Cloud branch explicitly unverified; no topology changes in this documentation reconciliation.

## Measured model-tool fast path — 2026-11-10
A clearly marked finite engineering acceptance reused the sole cloud model owner, production executor and Python tool dispatcher, with no Telegram instruction/delivery claim. The model selected cash/positions/orders broker tools plus databases and produced a grounded result in23.909s (two model turns; three separate reconciliations). To reduce repeated I/O and context, broker snapshot now accepts1–6 distinct registered sections. The model charter prefers one snapshot for combined broker questions; only selected sections return to context. Position/order-only snapshots do not create an unnecessary account-summary subscription. No response-time SLA follows from one engineering sample. Native Telegram latency, executor choice and development/operations writes remain open.

## Telegram configuration reservation guard — 2026-11-10
Source7aeea04 validates the regular, bounded, private Telegram configuration and cached-client identity before claim. Failure leaves the row PENDING. A mixed legacy route that already claimed records a positive PREFLIGHT_FAILED/transport_entered=false event before defer; transport-entered failures retain UNKNOWN. This applies only to new attempts and cannot reclassify STARTED1270–1272 or demonstrate risk digest delivery. The existing sender/receiver/producer topology and permissions are unchanged. Runtime release7a was reported by the deployment owner separately from the earlier independent a469 verification; no deployment or service action is performed by this documentation reconciliation.

## Cloud inbox authentication-control owner
Source inspection found a real cutover gap: cloud model polling reserved pending control dispatches but never executed them, while the original Mac bridge was stopped. Gateway-start assistance now belongs to the existing inbox under explicit gateway_start_control_owner/cloud_inbox and a fresh cutover timestamp, retaining the pre-existing gateway_start_assistance_approved grant. Native owner /login_assist and stopped/failed state are rechecked before one fixed systemctl start; no model or Mac is needed. Cloud models never claim transport controls they cannot execute; remaining local user-session searches retain Mac ownership. Polkit continues to allow only ibkr and the exact owned Gateway unit, with start for inbox and the existing restart for watchdog; stop, other units and broader privileges remain denied. Claim/native-start receipts precede effects; UNKNOWN originals survive and a separate successful notice run means notice construction, not operation success. Activation requires read-only native authorization probes; no healthy-Gateway restart or artificial login drill is performed for acceptance.

## Official hosted Cloud decision and first acceptance request — 2026-11-10
Owner explicitly selected OpenAI official hosted Codex Cloud and approved one new read-only acceptance chat in the existing ready/runnable 买der－云端开发 configuration. create_thread was submitted once at2026-11-10T00:48:18.478Z; no threadId/clientThreadId or completion receipt returned. Recent50-thread reconciliation found no matching title, which is not proof of rejection. Creation remains UNKNOWN and must not be resubmitted automatically. Chrome currently shows a Free ChatGPT session without projects/chats, not verified as the saved-environment account. Native Codex UI inspection was rejected by computer-use safety; no bypass attempted. Official hosted task ingress and result return remain unverified; local app-server/legacy CLI cannot be relabelled as this executor. This supersedes earlier executor-choice-pending wording only; all historical attempts remain.
