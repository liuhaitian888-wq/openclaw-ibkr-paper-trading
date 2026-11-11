# Secretary, execution receipts and research continuity — 2026-11-11

Status: researched design and handoff, not deployment or trading approval. This continues the existing `secretary-market-operations` and `p0-paper-execution` changes. It does not replace their implementation plans, owners or acceptance gates. Private account snapshots and credentials stay outside Git.

## Actual versus pending

- Deployed cloud `409e255`: owner-private model replies, scoped read-only Codex acceptance, registered business database tools, capacity sampling/query, publication-v2, pinned card296, and actual daily supplement1985/group299 have separate native receipts. Main source `454062a` is a larger engineering tree, not the cloud deployment.
- Development executor `77711e2` plus documentation `621905a` is source/offline verified only. Its new one-task development scope is not yet armed or natively accepted. It cannot be described as unrestricted coding, production deployment, all-project filesystem access or arbitrary Codex-to-desktop wakeup.
- Trading final-wire/ACK-handoff candidate `bd20c5f` has independent offline review. It is not the live execution owner. Formal execution manifest/T0, native partial-fill/restart/value-date acceptance, fresh actionable market data and historical outcome reconciliation remain open. Positive ordinary cash does not override negative current settled cash.
- Gateway's one authorized actual restart recovered native reads and the original daily-report chain. The consumed one-shot authorization and older delivery/readonly UNKNOWN remain preserved. Candidate `252b567` is not proof of deployed business-unready detection or unattended authentication recovery.

## Official designs compared and selected use

| Reference | Useful property | Decision for this project |
| --- | --- | --- |
| [OpenAI App Server](https://learn.chatgpt.com/docs/app-server) | Explicit connection initialization and thread/turn/item lifecycle | Keep the existing official cloud owner and persist native IDs, status and independently verified artifacts. A local ACK or thread creation is not task completion. |
| [Temporal tasks](https://docs.temporal.io/tasks) | Durable task history, separate attempts and heartbeat progress | Borrow the state-machine and idempotency principles. Retain the existing bounded SQLite ledger/outbox; do not install another orchestration service on the small host. Non-idempotent UNKNOWN is reconciled, not blindly retried. |
| [IBKR order status](https://www.interactivebrokers.com/docs/tws-api/doc/order-management/order-status) and [connection lifecycle](https://interactivebrokers.github.io/tws-api/connection.html) | Native asynchronous connection and order evidence; repeated status callbacks | Separate connection readiness, order acceptance, fills and cash/fee accounting. Keep exact account/client/permanent-order lineage and deduplicate actual events. |
| [Nautilus execution reconciliation](https://nautilustrader.io/docs/latest/concepts/execution/reconciliation/) | Startup and continuing alignment of local execution state with venue facts | Reuse our native reconciliation owner and retained events. Do not import another execution engine or synthesize a missing historical fill to make balances agree. |
| [QuantConnect research guide](https://www.quantconnect.com/docs/v2/writing-algorithms/key-concepts/research-guide) and [slippage](https://www.quantconnect.com/docs/v2/writing-algorithms/reality-modeling/slippage/key-concepts) | Point-in-time research, sample separation and realistic transaction assumptions | Extend the existing recorded-quote/strategy pipeline first. Separate framework fixtures, historical replay, execution-aware tests and forward Paper acceptance. No dependency replacement or subscription purchase is approved by this comparison. |
| [DuckDB Parquet](https://duckdb.org/docs/2.0/data/parquet/overview) | Query selected columns and filtered file data without importing the whole archive | Candidate storage format for versioned research batches; not a newly installed production dependency. Cloud keeps necessary hot state/manifests, verified optional archives use quotas and resumable transfer. |

These are engineering selections from the references, not claims that the referenced products guarantee our workflow's security or exactly-once broker execution.

## Mutual requests and continuous improvement

Use the current secretary archive, engineering proposals/tasks, existing model owner, deterministic five-project collector and sole sender. Record four distinct identities: project/defect entity, observation occurrence, exact-content fingerprint, and execution attempt. Rewording a finding must not mint another task; a new regression must not erase the old attempt.

The minimum continuation is deterministic discovery and a bounded global read view, then class-authorized execution. Findings carry project, source commit, coverage/freshness, evidence references, severity, host-assigned owner/priority and linked issue/task. SYSTEM observations, MODEL proposals and USER authority never become interchangeable. Unchanged metadata requires no model call. Cadence, triage and execution budgets must be explicit policy, not an unbounded model loop.

The current bridge establishes dispatch and result return, not arbitrary reverse RPC or desktop-chat wakeup. The constrained code class does not provide unrestricted native tools. A later bounded context-request protocol must bind each request to the same task, permitted read tool and budget; the host supplies permitted evidence or records a dependency block. This is a proposed continuation, not a current accepted capability. Results return to the same task and original owner. Results/status/tool outputs are not new executable instructions. Reject cycles, arbitrary cross-project delegation, unknown task classes and privilege escalation. Keep existing UNKNOWN/STARTED and budgets across process restart.

News, web pages and documents are untrusted evidence, never authority or tool instructions. A research model cannot change risk settings, authorize its own execution class or turn quoted instructions into an order. Connection authentication and receipts do not replace kernel isolation, narrow credentials and independent correctness checks.

The five-project collector currently observes local checkouts. Mac offline means last-observed/STALE coverage, not full cloud visibility. A later signed/validated bounded digest import can use the existing queue; it must not turn repository membership into production permission. Credentials, OAuth internals and unregistered private files are outside the business read catalog.

First acceptance remains the already delivered one-task `77711e2` class: genuine native owner request, native Codex turn, isolated patch, host-owned AST/path checks and independent tests, artifact fingerprints and existing private reply. PATCH_READY is not merge, deployment or broad autonomous development. Broader classes and recurring triage follow separately; they do not delay this first acceptance.

## Handshakes and gates along each order

Use a persistent authenticated connection, not a new socket per order. A channel handshake establishes peer identity, Paper account, protocol and current process/connection generation. Broker nextValidId/managed-account evidence is one part of readiness, not proof of current cash, orders or a complete account snapshot.

Every business handoff then uses a host-validated immutable envelope: occurrence/idempotency identity, exact intent fingerprint, source/config/risk revision, exact account/environment/contract, strategy scope, generation, owner, nonce/sequence and expiry. Native broker identity is subsequently bound to the parent/child order and permanent order ID. Do not invent new cryptography for local calls: use the existing OS/service identity and private ledger; remote transports need their supported authenticated channel. A nonce alone is not authentication.

| Stage | Required evidence | Receipt means |
| --- | --- | --- |
| Native Telegram ingress | Exact owner native private context, no forwarded/group authority | Received and persisted, not model execution |
| Secretary to engineering/strategy owner | Scoped task class, source provenance, budget and one owner | Durable claim/attempt, not completed work or order |
| Intent admission | Fresh market/account facts, settled cash, per-order/portfolio caps; atomic own claim | Resources reserved, not broker acceptance |
| Final wire, both parent and child | Current generation, unchanged permission/risk revision, expiry and resource rechecks; held owner/guard | Local STARTED recorded before the irreversible call |
| Broker acknowledgement | Exact native account/client/contract/parent/permanent-ID binding | Venue order state, not a fill or released reservation |
| Fill and protection | Exact executions, partial quantities and confirmed remaining protection | Actual exposure; incomplete protection blocks new entry |
| Accounting and release | Actual fee revisions, settled cash delta, exact exposure handoff and native terminal evidence | Reconciled outcome; a socket return or status label cannot release claims |

Retain existing gate responsibilities rather than multiplying independent boolean flags. User authority defines allowed work; deployment identity defines allowed code; runtime/account/data gates establish facts; atomic risk admission reserves resources; final wire rechecks the live permission. Pause/revoke must serialize with the last wire decision under the same existing execution owner. A revocation after a request has crossed the wire cannot unsend it; mark in-flight and reconcile. Do not promise a distributed atomic transaction between SQLite and the broker.

Acceptance failures include tampered intent/revision/account, replayed or expired envelope, wrong generation, duplicated/out-of-order callback, cancellation racing a fill, permission change after reservation, crash after STARTED, lost acknowledgement, and parent/child partial failure. No uncertain financial call is retried merely because its timeout or lease expired. Necessary owned protective exits retain their separate authority; an entry budget must not strand them.

## Gateway incident and automatic recovery boundary

Established direct failure: the Gateway remained in `Restart in progress / Shutdown IA`; protocol handshake still responded while authenticated complete business callbacks did not. Existing recovery deliberately classifies that as upstream/reconciliation wait, avoiding an authentication restart storm. That decision and missing durable business-unready attention left a blind spot. High pre-restart Java resources are observations, not proof of the underlying shutdown deadlock trigger; that trigger remains UNKNOWN.

The watchdog policy can reserve one bounded restart for sustained local API hang only when its approved policy, generation, two independent failed readings, duration, budget and absence of authentication/identity holds all agree. Its daily budget is not a universal login budget: systemd failure recovery and the current controller's exit/login handling have separate bounded retry mechanisms. Any future unified recovery arbiter must account for these existing layers rather than adding another retry loop. This is not a guarantee that the same handshake-responsive failure will automatically restart next time. Recording the incident is not an installed recovery feature.

Next minimal work is the existing `252b567` business-unready attention/phase candidate under the current quiet/single-card policy; assess its Python component independently of a new controller release. Human authentication, unknown side effects, identity mismatch and exhausted budgets remain holds. After any allowed recovery require new-generation native and independent complete reads plus stability; recovering the network never grants trading permission. Do not restart or manufacture 2FA for testing.

## Research and backtest data contract

Existing anchors: `research/strategy_validation_plan.py`, `research/ibkr_quote_recorder.py`, `strategies/`, `trading/simulation.py`, `scripts/run_strategy_simulation.py` and the existing news collector. Their fixture signals and in-memory limit-price PnL are not a proven account-level backtest.

Retain immutable batch manifests with source/license, instrument/conId and historical universe version, event/publish time, first available/receive time, revision time, timezone/calendar, schema and content hash. Preserve raw prices plus explicit corporate-action adjustments; current surviving constituents are not a historical universe. Unsupported/missing coverage stays explicit.

| Dataset | Minimum useful content | Purpose |
| --- | --- | --- |
| Price/quotes | OHLCV, bid/ask when execution realism requires it, timezone/session/gaps | Signal replay and spread/limit-price constraints; daily bars cannot certify intraday fills |
| Corporate actions/universe | Splits, dividends, symbol changes, delistings and as-of membership | Avoid false returns and survivorship bias |
| Fundamentals | Publication/first-available dates and versioned corrections | Value research without future/restated facts |
| News | Provider/article ID, original publication, receipt/revision times, retained body hash and entitlement | Point-in-time event research; a headline/body hash alone cannot be analyzed as full text |
| Broker economics | Fee schedule, observed fills/fees, slippage/latency assumptions, lot/tick/order/session rules, currency and settlement calendar | Conservative execution and no-new-borrowing simulation |
| Experiment | Hypothesis, code/config/data versions, seed, train/validation/untouched test split, all attempted variants and outcomes | Reproduce results and expose selection/parameter overfitting |

Start with a bounded real-history subset using the same strategy interface; run transaction-cost/latency and adverse-market variants, chronological walk-forward, held-out tests and parameter stability checks. Report drawdown, turnover, exposure, costs, sample size and missing coverage alongside returns. A chosen winner on the same sample is not out-of-sample evidence. An LLM trained on the tested historical events can leak future knowledge even when the supplied article timestamps are correct; do not certify that as point-in-time live intelligence. See the primary [GPT sentiment look-ahead study](https://arxiv.org/abs/2309.17322); this risk is distinct from timestamp filtering in our data loader.

Keep live financial/task/order/receipt state in bounded managed cloud stores. Large historical research batches are immutable compressed files with catalog/hash, byte quota, free-space floor and verified resumable archive. The existing governance candidate does not delete historical backups, and its small public-artifact copy does not prove financial database disaster recovery. Research is deferred under capacity pressure before core risk/receipts are sacrificed; Mac is not the sole copy or a core execution dependency.

## Sequence and release evidence

1. Finish the existing publication/capacity governance window and its actual sampler/query/card acceptance; preserve historical backups.
2. Independently publish and accept the single authorized secretary/Codex development class. Then add deterministic issue discovery/global read view before bounded broader class routing.
3. Review final-wire handshake/gate coverage on the existing candidate and native partial/restart/settlement requirements. Resolve historical outcome and funding/data blockers. Do not infer formal execution approval from this document.
4. Extend the existing news/history/validation path with a bounded reproducible data manifest and realistic replay, not a second live broker or a replacement engine. Research can proceed offline while trading remains paused.

Each owner returns immutable source, matching offline tests/secret scan, actual deployment and independent native result separately. The coordinator reports blocked facts and next acceptance, not a guaranteed opening time. The currently projected positive future settlement date is not itself an activation date.
