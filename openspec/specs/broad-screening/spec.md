# Broad Research Screening

## Purpose

Provide evidence-based broad US equity research from bounded public data and existing-owner broker scans, preserving explicit missing fields, source dates, entitlement uncertainty and execution independence.
证据明确的宽范围研究、六层投影、私人查询和Paper只读对照。

## Requirements

### Requirement: Explicit source and missing-data provenance
The system SHALL persist source, collection time, provider time quality, coverage, raw snapshot hash and missing fields for research data; missing values MUST NOT become zero.

#### Scenario: A financial metric is unavailable
- **WHEN** one SEC frame fails while other frames are valid
- **THEN** valid fields remain available and the missing metric and source error are recorded independently.

### Requirement: Research projection cannot authorize execution
The system SHALL use the canonical six layer names for an explicitly read-only research projection; it MUST NOT rewrite canonical execution/position state or grant realtime permission.

#### Scenario: Coarse liquidity criteria match
- **WHEN** current-enough research price and session volume match the documented rule
- **THEN** L2 research is published with contract/realtime/signal/risk blocks still visible; a fresh completed native scanner intersection may add L3 research only.

### Requirement: Existing-owner bounded broker scanner
The system SHALL use the existing Paper connection for one active scanner request, at most 50 rows, a 20-second timeout and owned cancellation; STARTED/UNKNOWN MUST NOT replay automatically.

#### Scenario: The monitor restarts mid-request
- **WHEN** a persisted request was STARTED without a durable end result
- **THEN** it becomes UNKNOWN and is not sent again; a new owner instruction is a distinct occurrence.

### Requirement: Private deterministic query and comparison
The system SHALL expose screen, screen_refresh, scan, compare and data_status through native verified owner controls; non-comparable quote fields MUST have explicit reasons and no strict difference verdict.

#### Scenario: Public daily data is compared to broker realtime
- **WHEN** times, currency, contract mapping or quote type are missing or incompatible
- **THEN** both available observations are displayed as NOT_DIRECTLY_COMPARABLE without claiming one source is wrong.

### Requirement: Owned maintenance schedule
The system SHALL maintain public data through a bounded single-owner oneshot, preserve old evidence on failure, persist backoff and expose actual status independently of schedule configuration.

#### Scenario: Nothing is due
- **WHEN** no owner task or current scheduled window is due
- **THEN** the worker records NOT_DUE and does not fetch a source or replay old jobs.
