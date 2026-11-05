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

## Actual bounded rollout and QuantConnect reauthentication

Cloud sourcea410b19 deployed after consistent SQLite/source-manifest backups to private `runtime/session-recovery/20261105T222526Z`. Only paper-safety monitor restarted to load verified code; Gateway Java716364 was unchanged. Native-generation inspection correctly returned716364:112616175. LegacyPFE162 policy adopted as10197 with original_code162 and preserved attempts/history. Production execution manifest hash stayed6012349bf80386432c9a2d24f3fa640813b9e88fcb2e7936b5f77b7c20aa69eb.

Current-session fresh readback22:26:26Z: exact Paper account, complete snapshots, originalPFE8 PreSubmitted permId911411084 intact, but all three NVDA/AMZN/TSLA quote requests returned10197. This is a real broker rejection, not an inference from stale cached quotes.

One explicitly authorized Paper reauthentication via the existing QuantConnect IBAutomater was durably reserved in `runtime/quantconnect-session-reauth-20261105.json`; no repeat/replay. Timeline UTC (Berlin+1hour):
-22:27:00 systemd stopped the existing owner and started the same approved service.
-22:27:21.372 START_RESULT None after automatic credential login; no human2FA requested in this attempt.
-22:27:41.580 monitor recorded a new connection attempt against nativeJava782068:117157745.
-22:28:42.280 sustained60-second account/end-marker validation completed. API connection recovery succeeded, independently of market readiness.

Post-reauth independent readback22:28:24Z remained complete, but new requests for all three stocks still returned10197 and no bid/ask. Original protective order retained and execution manifest unchanged. Evidence `runtime/quantconnect-reauth-readback-20261105.json`. Diagnostic subscriptions cancelled, socket/reader/worker closed, threads1, fds5. No orders/cancels submitted. Do not label this MARKET_RECOVERED, and do not repeat Gateway reauthentication to chase a green state.

Continuous owner logs also prove BAC/KO automatic15-minute data subscription attempts persisted through21:05,21:20,21:35,21:50,22:06,22:21UTC; they did not stop altogether. PFE resumed bounded low-frequency recovery at22:25:37UTC after classification repair. A15-minute recovery cadence intentionally does not promise immediate restoration after a user closes a Live UI.

User now reports the Live app asks for a password and guesses it is logged out. This is not proof of server-side brokerage/market-session release. The exact still-competing session remains unverified; the available SocketAPI/connector exposes no active-session inventory. Both officialibapi and ib_async reproduced the error, including after a real reauthentication. Need explicit broker logout/session release or IBKR-side investigation before real quote recovery can be certified. No additional Live brokerage session is opened by diagnostics.
