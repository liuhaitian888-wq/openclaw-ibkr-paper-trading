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
