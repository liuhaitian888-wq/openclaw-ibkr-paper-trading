# Calendar And Timezones

- Primary market clock: `America/New_York`.
- Operator clock: `Europe/Berlin`.
- Runtime clock: UTC internally.

Implemented session buckets:

- Overnight: 20:00-03:50 ET where supported.
- Premarket: 04:00-09:30 ET on US trading weekdays.
- Regular: 09:30-16:00 ET on US trading weekdays.
- Afterhours: 16:00-20:00 ET on US trading weekdays.
- Offline: weekends and unsupported gaps.

The first implementation does not yet ingest an exchange holiday calendar. Add NYSE/Nasdaq holiday handling before treating paper statistics as production-like.
