# Monitoring And Recovery

Required monitoring:

- Trading API health.
- TWS readiness.
- Session classification.
- Quote freshness.
- Open orders.
- Submitted, partial fill, filled, cancelled, rejected states.
- Audit DB alignment.
- P&L snapshots.

Initial recovery behavior:

- Pause on unhealthy TWS/API.
- Pause on kill switch.
- Block stale quotes.
- Block duplicate same-symbol same-direction order refs.
- Write `reports/autonomous_runtime_status.json`.
- Append `reports/autonomous_runtime_events.jsonl`.
