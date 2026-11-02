# Native capability evidence — bounded Paper conflict monitoring

Checked 2026-11-02 for this patch only; not an inventory or permission grant.

Official: https://www.interactivebrokers.com/docs/tws-api/doc/error/codes documents 10197 as competing Paper/Live market-data use, with Live preferred. It does not identify a phone or provide a phone-logout event. https://www.interactivebrokers.com/docs/tws-api/doc/md/streaming-data documents reqMktData/cancelMktData and callback streams. Reuse these primitives and the existing PaperSafetyClient owner; no second feed, login takeover or order API.

Code: immediate persisted per-symbol conflict episode notifications, explicit recovery after three distinct fresh type1 bid/ask observations after the conflict and fresh complete Paper reconciliation in a verified active session. Four-fast subscription admission is retained; 15-minute atomic slow probes continue an exhausted10197 incident without resetting its fast budget. UNKNOWN requests, human-review errors and closed sessions stay held. Session UNKNOWN permits diagnostics only, never recovery. Legacy incident history does not generate new notifications until a real new10197 callback arrives.

Mail: reuse the existing armed SMTP owner/outbox; SMTP uncertainty never auto-replays. Existing generic stale-feed/protection incidents retain separate identities. Healthchecks Paper API remains account/API availability, not market-data readiness or trade permission. A slow probe has a15-minute scheduling bound, not a promise to recover within15minutes or while IBKR requires authentication.

Deployment: pending tested Git integration and monitoring-only rollout. Broker acceptance: pending genuine post-deployment events; offline fixtures are not real10197 or recovery. Existing PFE protection and all execution controls are preserved.
