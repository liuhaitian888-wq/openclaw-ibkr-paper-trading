# Competing session repository review — 2026-11-05

- QuantConnect/Lean.Brokerages.InteractiveBrokers, reviewed17702a6ae438a17495b9dea75b6db2857292d892, Apache2.0: `Client/CompetingLiveSessionMarketDataErrorHandler.cs` explicitly handles10197 by throttling warnings to15minutes. It does not terminate competing sessions, clear broker entitlement state or declare price recovery. This mature reference confirms notification management is different from session repair.
- ib-api-reloaded/ib_async2.1.0 (BSD): Watchdog probes actual historical bars on inactivity and restarts its IBC-owned app on hard timeout. Its explicit error-triggered restart set is100/1100, not10197. It is not a standalone cure for entitlement competition. Adding it beside the deployed IBAutomater would create competing service owners, so it is not activated. The installed ib_async library is used for one bounded independent Paper price comparison, without any Watchdog or orders.
- IbcAlpha/IBC: README says retired2026-09-01 and repository archived. `ExistingSessionDetectedAction` can prioritize a brokerage login, including primaryoverride behavior. This can eject a session rather than solve the Live/Paper shared-market-data restriction. No replacement of our current manager is performed.
- Existing QuantConnect/IBAutomater: on `Existing session detected`, its Java handler selects Exit Application/Cancel and C# reports ExistingSessionDetected. It deliberately does not silently kick off the other session. Existing bounded automatic cold/native softrestart management remains the only Gateway owner.

Primary sources:
https://github.com/QuantConnect/Lean.Brokerages.InteractiveBrokers/blob/master/QuantConnect.InteractiveBrokersBrokerage/Client/CompetingLiveSessionMarketDataErrorHandler.cs
https://github.com/ib-api-reloaded/ib_async/blob/main/ib_async/ibcontroller.py
https://github.com/IbcAlpha/IBC
https://github.com/QuantConnect/IBAutomater
https://www.interactivebrokers.com/docs/tws-api/doc/error/codes

No repository can be assumed to override broker-enforced sharing restrictions. A supported recovery must independently prove Paper identity/readback and fresh actual type1 bid/ask, then satisfy separate risk/order gates. A one-time explicitly authorized reauthentication, if required, must have its own durable attempt evidence and cannot become an unbounded10197 restart loop.

## Actual comparison and repair

At10:37:56–10:38:07Z, installed ib_async2.1.0 connected read-only to exact Paper identity, resolved NVDA/AMZN/TSLA and explicitly requested market type1. All three requests returned10197 with no bid/ask, matching earlier officialibapi probes. Connection was closed and subscriptions cancelled. Evidence: private `runtime/ib-async-session-comparison-20261105.json`. This is a negative real test, not a library-based recovery success.

Confirmed local defects corrected:
- Explicit162 `Trading TWS session is connected from a different IP address` is a session conflict variant; classify it into bounded10197 recovery, retaining original broker details.
- A secondary HMDS162/321 error cannot erase an active10197 quote retry policy. Other162/321 messages remain diagnostic when no active quote collision exists.
- On startup, adopt the legacy misclassified162 records atomically with lifecycle state, without resetting attempts/incident identity or deleting history; existing slow-probe budget remains in force.
- Passive Gateway generation inspection follows only the systemd-owned descendant tree to the unique Gateway Java process. The persistent Python/.NET automater controller no longer hides Java/native soft restarts. Missing/ambiguous children remain UNKNOWN.

766 isolated offline tests passed; no real TCP permitted by the runner. Existing notifications are not test-sent. Deployment must back up source SQLite and identities before bounded monitor restart. Any explicitly authorized Gateway reauthentication is a separately recorded one-time operation, not a read-only recovery callback or automatic restart loop.
