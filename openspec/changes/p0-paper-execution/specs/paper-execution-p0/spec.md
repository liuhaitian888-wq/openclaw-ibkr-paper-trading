## ADDED Requirements
### Requirement: Scoped P0 actions
The system SHALL keep global stock entry paused until independent engineering and runtime gates pass; scoped protective and cash-funded actions SHALL bind exact account, deployment identity, source authority and finite budget.

#### Scenario: Protective order acknowledgement is uncertain
- **WHEN** the single scoped stop attempt loses acknowledgement or exact readback fails
- **THEN** STARTED or UNKNOWN survives restart and no new identity replays the action

#### Scenario: Operator leaves an additive field blank
- **WHEN** an owner confirms a null additive cap
- **THEN** no additional cap is applied for that field and executable hard ceilings remain in force

### Requirement: Fresh currency funding evidence
The system SHALL obtain explicit new USD and base currency ledger ends on every funding read, including when a cached base row exists, and SHALL distinguish accounting conversion, hypothetical estimate and actual exchange.

#### Scenario: Cached EUR predates a conversion
- **WHEN** the same client already has a cached EUR balance
- **THEN** a fresh EUR ledger end is required and failure cannot fall back to cached positive cash

#### Scenario: Own-cash exchange is reconciled
- **WHEN** the finite EUR to USD scope fills
- **THEN** exact executions, actual fee, EUR debit, USD credit, no active scoped order and unchanged inherited non-cash positions must reconcile before FILLED is recorded

### Requirement: Typed portfolio and currency facts
The system SHALL retain raw broker exposure while separating verified stock holdings, identified currency-pair position facts and unsupported instruments. Currency-pair position quantities SHALL NOT be represented as actual currency balances, stock shorts or missing stock-stop coverage; funding and currency liabilities SHALL remain independently verified. Unsupported instrument identity and active external currency orders SHALL NOT be silently omitted from risk checks.

#### Scenario: Negative virtual currency position after own-cash conversion
- **WHEN** native readback contains a CASH EUR/USD pair position and actual EUR/USD cash balances are separately available
- **THEN** the pair remains visible as an FX position fact, stock protection excludes it, and no cash or borrowing permission is inferred from its quantity

#### Scenario: Ambiguous currency contract
- **WHEN** CASH metadata is incomplete, unsupported or conflicting
- **THEN** the exposure remains visible and applicable admission remains blocked

#### Scenario: Legacy execution gains instrument evidence
- **WHEN** an exact existing execId is read back with previously missing contract metadata
- **THEN** only missing contract fields may be enriched; changed economics or known identity conflicts remain blocked

### Requirement: Transactional entry resource claims
The system SHALL atomically reserve entry intent and applicable monetary budgets before an opaque broker transport, revalidate current gates, and persist a transport-start occurrence that cannot be replayed by relabeling statuses. Unknown outcomes SHALL retain claims until exact reconciliation; only a proven unsent intent may release its own unspent claim without broker proof.

#### Scenario: Two callers race for the same funding
- **WHEN** simultaneous callers attempt to spend funds or daily capacity already reserved by the other intent
- **THEN** at most the funded admitted intents commit and rejected transactions leave no phantom reservation

#### Scenario: Operator revokes a gate during preflight
- **WHEN** the gate or risk limit changes before reservation commit
- **THEN** the current admission is rejected and no broker transport is entered

#### Scenario: Status label changes after transport start
- **WHEN** a previously started occurrence is relabeled RESERVED or FAILED
- **THEN** its durable occurrence history still prevents replay and unresolved monetary claims remain held

### Requirement: Exact native accounting before claim release
The system SHALL bind cash claims only to direct native account, contract, client, permId and parent-child evidence. Native fee absence SHALL remain unknown; explicit zero and fee corrections SHALL be distinguishable. Cash claim reconciliation SHALL require ordered fresh native execution, fee and currency cash evidence, and SHALL NOT grant order mutation authority.

#### Scenario: Fee callback precedes an execution
- **WHEN** an unbound fee is received before its execId's canonical account is known
- **THEN** its fact is retained without cash-release permission and may bind only after exact execution evidence

#### Scenario: Cash read predates a new fee correction
- **WHEN** a fee revision is persisted after the cash refresh began
- **THEN** fresh entry funding remains blocked until a later complete currency cash refresh

### Requirement: Distinct actual turnover and live commitments
The system SHALL count canonical native stock buys and sells by actual occurrence day and explicit timezone, separately retain live entry commitments, and combine them for entry budget without double counting filled quantity. Missing evidence SHALL NOT be treated as zero and the entry budget SHALL NOT block protective exits.

#### Scenario: Partial entry remains active into the next day
- **WHEN** some quantity has filled and the exact native parent still has unfilled quantity
- **THEN** actual turnover belongs to its occurrence day and remaining commitment continues across days until verified terminal reconciliation

#### Scenario: Failed label follows transport start
- **WHEN** an already started intent is later labeled FAILED without no-send or native terminal proof
- **THEN** its unresolved commitment remains reserved

### Requirement: Explicit settlement capacity and cash accounting
The system SHALL distinguish native trade-date cash from per-currency cumulative settlement schedules and SHALL NOT infer current usable USD from future credits or a BASE projection. Until stock value-date matching is verified, new entry capacity SHALL be conservatively bounded by current and known scheduled USD balances. Claim release SHALL require the observed USD cash delta to agree with all newly known native stock flows and actual fee revisions, not merely a later RPC end marker.

#### Scenario: Ordinary USD cash is positive while settlement is negative
- **WHEN** native CashBalance is positive but current SettledCashByDate remains negative
- **THEN** that ordinary balance does not independently authorize a no-new-borrowing entry

#### Scenario: Two filled intents share one lagging ledger observation
- **WHEN** a later account RPC reflects only one of two known filled intents
- **THEN** neither may reuse that one debit as proof that the whole newly known cash-flow cohort was accounted for

### Requirement: One read-only native currency evidence owner
The system SHALL collect native cash and settlement through at most one owned accountUpdateMulti request on the existing read-only SDK owner. Only exact account/request/generation callbacks and an explicit end may publish the bounded book. Missing or negative facts SHALL NOT be replaced with zero or promoted to spending permission.

#### Scenario: Late callback follows reconnect
- **WHEN** a callback from an earlier request or connection arrives after its owner is closed
- **THEN** it cannot publish a cashbook for the current account/generation

#### Scenario: Completion lacks a coherent exact currency schedule
- **WHEN** the end marker arrives with missing USD, accountReady=false, conflicting values or an overlarge snapshot
- **THEN** the last published file remains unchanged and no entry permission is granted

### Requirement: Bounded cash subscription lifecycle
The system SHALL use timeout8s and refresh no faster than5s, cancel only owned subscriptions on completion, timeout and shutdown, and publish through one atomic private-file owner. Its opt-in CURRENCY_BOOK dependency SHALL belong to the shared health registry and expire after10s.

#### Scenario: Request times out or cancellation fails
- **WHEN** a request exceeds8s or cancellation cannot be completed
- **THEN** the owned client must close before another request is admitted and no partial book is published

### Requirement: Preserve finite FX evidence without a competing writer
Approved continuous cash collection SHALL prevent the finite FX adapter from overwriting the continuous owner's latest-book file while retaining the original finite FX receipt and immutable operation outcome.

#### Scenario: Finite FX completes while continuous publication is approved
- **WHEN** a finite exchange produces its independently reconciled cash receipt
- **THEN** that receipt remains archived and the continuous cashbook file is left to its approved owner
