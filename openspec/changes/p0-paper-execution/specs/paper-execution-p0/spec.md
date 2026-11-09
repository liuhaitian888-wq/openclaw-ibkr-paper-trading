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
