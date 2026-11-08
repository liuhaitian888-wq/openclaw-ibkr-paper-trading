# P0 execution closeout — Nov8/Nov9 Berlin

User authorized engineering work toward autonomous Paper readiness. Trading parameter decisions and final native acceptance/release remain distinct. No Live authority.

## Current cloud facts

Read-only collection on 2026-11-08 22:56 UTC (23:56 Berlin): exact PAPER DUQ503649, fresh complete four-end broker state, UNKNOWN/STARTED order operations=0 and pending order requests=0. Cloud source fdc84cb; branch codex/ibkr-cloud-paper. API and strategy services remain disabled, kill=true/transmit=false. Main Mac smoke NOT_READY is a separate local historical installation, not the cloud broker status.

Holdings: AAPL17, META100, MSFT13, NIO200, PFE8, T3. Only PFE has verified simple native protection: SELL STP8 at23.01 GTC, permId911411084. Ownership is not inferred from orderRef or missing local intent. Do not cancel/replace/adopt any legacy order without the approved boundary.

Bounded independent read-only cash query at22:59:44 UTC via the existing news-venv, explicit USD and EUR ledger end markers, no market subscriptions/orders: EUR1007456.40, USD-69788.66. Other-currency cash is not spendable USD. Result saved as evidence, not published as a permanently fresh runtime cashbook. Each actual executor/FX action needs new evidence and positive explicit fee reserve. First attempted main-venv query failed before connect because ib_async is not installed there; no dependency was installed to make a check green.

Actual additive controls revision3: QMAX1, OMAX2000USD, RMAX10USD, SMAX/GMAX null. Actual execution hard quantity/order cap remains1/200USD. The earlier revision0/OMAX200 template record is superseded. Five field confirmation and hard cap changes are distinct decisions.

## Independently repaired admission defects

- RiskEngine rejects invalid sides, non-integer/boolean quantity, nonfinite prices/exposures/limits and arithmetic overflow before monetary comparisons. NaN must not pass by making comparisons false.
- Strategy events retain original quote_timestamp. Candidate AutonomousPaperRuntime never fabricates current time for old quotes; missing/naive/future/crossed/missing/nonfinite bid/ask fail closed, stale original timestamp is checked by session policy.
- Runtime durably fsyncs/replaces STARTED status with exact proposal identity before opaque submit. Exceptions/PENDING/UNKNOWN/unrecognized results latch RECONCILIATION_REQUIRED; later cycles and process restart preserve the identity and do not replay. Transport exceptions no longer masquerade as ordinary REJECTED.
- A confirmed submission ends the current cycle, requiring another cycle/production guards instead of submitting a second event with the same pre-submit snapshot. This does not claim that a new loop iteration guarantees refreshed broker cash or replaces atomic budget reservation.

These repairs harden an existing candidate entry. They do not connect the active cloud MONITOR_ONLY observer to a fully accepted continuous executor. Existing systemd strategy unit points to the legacy Mode9 entry; do not enable it as a substitute for that integration.

## Remaining P0 work and dependencies

1. Owner decisions: frozen strategy/version and symbol scope; SMAX/GMAX plus all five caps; strategy funds/daily notional/day timezone/positive fees; exact cash-funded FX spend/fee boundary; handling of five unprotected inherited holdings; new independent native acceptance scope; Paper duration and owned-order cancel/exit authority. Previously approved no-new-borrowing/cash-funded FX policies remain approved.
2. Engineer: exact approved strategy signal -> unique executor admission; atomic durable funding/daily-risk reservation spanning intents, full portfolio/active external orders and recovery; prove ownership/canonical lifecycle from broker and source provenance, never manufacture flags.
3. Engineer + native window/scope: parent/child transmission, rejection/cancel/timeout, partial fills with exact covered quantity, reconnect/restart reconciliation and duplicate rejection. Single-share BAC candidate cannot prove partial fills. Preserve legacy NVDA3/3 closed scope.
4. Market facts at actual submission: fresh complete account/positions/orders/executions, explicit USD+base cash/FX, real bid/ask, contiguous bars, actual contract session. Weekend evidence must expire normally.
5. Formal release: reviewed exact commit/paths/account manifest, actual effective risk limits, protective coverage, canonical and funding gates, bound T0 with fresh NAV/cash/FX/fees; then final scoped approval and only one owner. Do not auto-clear PAUSED or MAINTENANCE.

Engineering tests cannot replace steps3–5. Owner parameter approval cannot replace step2.

## Validation and evidence

Linked worktree /private/tmp/der-p0-execution, branch codex/p0-execution-preflight. Initial regression suite reproduced26 failures/1 error in983 tests. Fixed suite985 tests/39.065s/OK; FD regression stayed5 across300 cycles, endurance320 cycles FD4 and threads1->1. gitleaks passed; diff check passed. Evidence directory ~/.local/state/openclaw/engineering/p0-execution-20261108 contains cloud-before.json, cashbook-readonly.json and copied test/scan logs. Production runs quick smoke only.

A stale gateway-automater deployment identity was also found (f494ee3 while cloud code fdc84cb). Repair requires comparing launcher/import/release dependencies against its approved commit, retaining original manifest and hashes, and validating without launching/restarting Gateway. Do not silently bless changed launcher code.

## Nov9 owner delegation and implementation

Owner explicitly delegated numeric/strategy choices, authorized adding missing protective orders, requested100-share ceiling and2000USD amount gate, nullable fields and a Telegram update. Adopted Paper settings: QMAX100, OMAX2000USD, RMAX10USD retained, SMAX250000USD/GMAX1500000USD as finite large ceilings (not target allocations). Execution hard caps100/2000/10; daily cumulative notional ceiling20000USD with America/New_York day boundary; positive5USD per-order fee reserve is a conservative funding buffer, not a claim about actual commissions. Existing self-funded/no-new-borrowing policy remains.

Five additive fields now accept blank/null or 不限; an omitted additive restriction does not remove hard executable caps, cash/protection or scope checks. Explicit CODEX_OWNER_CHAT approval is recorded as EXTERNAL_OWNER_CONTROL, bound to exact revision/settings. It must not masquerade as a native Telegram message. Model-origin events cannot apply caps.

Monitor-only BUY proposals use the minimum of quantity ceiling, floor(amount/limit price) and floor(risk/stop distance). Example100-share ceiling with2000USD and51.01 entry yields39 shares, never forced100. The existing observer remains non-transmitting; its quantity/money defaults are not silently hardcoded1/200 when an explicit execution_limits manifest exists.

CashBook-style Decimal conversion via a common base currency checks exact account, timestamp and positive finite rates. The output is ACCOUNTING_REFERENCE_ONLY/executable_fx_quote=false; account-summary exchange rates are not executable live FX quotes. No third-party agent or runtime package was installed. Sources: https://www.quantconnect.com/docs/v2/writing-algorithms/portfolio/cashbook and https://www.quantconnect.com/docs/v2/writing-algorithms/algorithm-framework/risk-management/supported-models; IBKR order semantics https://www.interactivebrokers.com/campus/ibkr-api-page/order-types/ . LEAN risk models are design references, not proof of this strategy profitability or of submitted stop orders.

Secretary jobs include bounded prior same-conversation USER operating preferences, excluding MODEL/other conversations/future records. Preferences affect explanations/priorities, not allowed tool surface; secretary model remains read-only and cannot claim it installed protection.

Final linked-worktree isolated suite991/44.638s/OK; FD samples5 throughout300 cycles and endurance FD4/threads1->1. Exact deployment/settings/outbox receipts are persisted in local state engineering/p0-execution-20261108 and cloud engineering/p0-execution-20261109. The first engineering patch5fef4e1 was Git-deployed; Gateway PID1450345 unchanged and gate hashes preserved. Gateway launcher dependency comparison and real validate_deployment succeeded without launch; stale launcher identity repaired with original manifest backed up.

Protection authorization is now confirmed and must not be asked again. Actual five-position protection is still NOT INSTALLED: no fresh market evidence for those symbols and no verified scoped repair transport; a policy file/authorization is not a broker acknowledgement. Global execution stays paused while atomic budget admission, continuous executor integration, native partial-fill/restart acceptance and current protection/funding evidence remain unproved. No synthetic green flags.

Integration with concurrent five-project maintenance change preserved both ENGINEERING sections. Final merged source1001 tests/40.944s/OK; no full suite in production. Owner preferences also travel inside the cloud job payload, so an already-running local bridge can see them on the next new job without interrupting an active paid inference. Reconciliation of existing STARTED/UNKNOWN paid calls is not replayed.
