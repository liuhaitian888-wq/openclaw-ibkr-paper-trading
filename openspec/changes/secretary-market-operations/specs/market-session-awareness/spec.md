## Purpose
Provide venue-specific market phase and closure awareness with explicit calendar provenance and expiry, without granting business permission or disguising operational outages as scheduled closure.

## ADDED Requirements

### Requirement: Verified venue calendar
The system SHALL bind reminders to explicit venue profiles and verified date coverage, convert time zones with daylight-saving rules, and disclose unknown calendar dates rather than invent sessions.

#### Scenario: EQQQ venue binding
- **WHEN** EQQQ contract 18706552 is observed
- **THEN** reminders use Milan ETFplus in Europe/Rome and SHALL NOT infer a US or London venue from the ticker alone.

#### Scenario: Expired calendar
- **WHEN** the current venue date exceeds verified coverage
- **THEN** one calendar-unavailable notice is produced and no unverified opening time is announced.

### Requirement: Durable phase notifications
The system SHALL announce current phase transitions once per venue occurrence through the owner notification outbox, include closure reasons and next opening when relevant, and avoid replay of historical transitions after downtime.

#### Scenario: Restart after missed phases
- **WHEN** the producer resumes after multiple session boundaries
- **THEN** it emits at most the current state for each venue and does not replay missed openings.

#### Scenario: Upcoming closure
- **WHEN** a trading day closes before consecutive non-trading dates
- **THEN** the close notice lists those dates with reasons and the next verified opening.

### Requirement: Operational independence
Calendar observations SHALL NOT start or stop APIs, clear maintenance or paused state, submit broker orders, or imply market data entitlement or trading permission.

#### Scenario: Closed market and failed API
- **WHEN** a scheduled closure coincides with an API fault
- **THEN** the calendar message describes only the schedule and the independent API fault remains visible.

### Requirement: Public fixed-template calendar routing
The system SHALL route only calendar events whose occurrence, phase, source version and expiry match the checked-in calendar to the verified deehub group through the existing notification owner. Public rendering SHALL reconstruct fixed schedule text and SHALL NOT publish arbitrary payload prose. Unknown/unrecognized event types, private research, risk, account and authentication information SHALL remain owner-private.

#### Scenario: Producer prose contains private information
- **WHEN** a valid calendar occurrence includes arbitrary private prose in its payload
- **THEN** the group receives only the reconstructed fixed calendar text and no private prose.

#### Scenario: Calendar identity mismatch
- **WHEN** the calendar version or occurrence does not match reconstruction
- **THEN** the event is not eligible for public group routing.
