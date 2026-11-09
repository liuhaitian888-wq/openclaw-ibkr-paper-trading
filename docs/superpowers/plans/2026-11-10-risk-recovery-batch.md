# Risk recovery aggregation implementation plan

Goal: one protection recovery digest per complete broker readback, retaining symbol evidence.
Approved scope: user requested recovery aggregation, investigation of live risk messages, and coordination with Telegram/secretary owners. Existing linked-worktree execution instructions apply.

- [x] Observe native deehub cards and read-only cloud outbox; compare Alertmanager grouping.
- [x] Add reporting/risk_recovery.py transaction owner; preserve individual RECOVERY rows as SUPPRESSED, create one digest only for newly resolved incidents.
- [x] Wire trading/paper_safety_monitor.py complete protection observations; signatures advance after successful commit.
- [x] Guard IncidentStore.claim against unresolved earlier member deliveries, including STARTED/UNKNOWN.
- [x] Validate atomic rollback, seven-symbol grouping, no-open/no-repeat and uncertainty; complete isolated suite and gitleaks.
- [ ] Hand tested Git commit to existing deployment owner; main smoke, manifests, secretary access and real acceptance recorded separately.

Sources: https://prometheus.io/docs/alerting/latest/alertmanager/ and https://prometheus.io/docs/alerting/latest/configuration/ (grouping/timing/inhibition; no new runtime dependency).
