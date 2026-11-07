# 2026-11-07 IBKR upstream investigation

Read-only investigation; no fault injection, Gateway restart, order, cancel or credential retry.

At 14:08 UTC (15:08 Europe/Berlin), the independent broker observer reported 2110, no account end markers and INCOMPLETE. Local API heartbeat and Paper identity remain available; those do not establish upstream connectivity. Durable 1100 events occurred 06:09:54–06:15:37 UTC; no 1101/1102 appeared in that window through inspection. Last complete report snapshot: 06:08:28 UTC.

Official status: https://www.interactivebrokers.com/en/software/systemStatus.php lists Saturday reset 00:00–02:00 ET, equivalent to 06:00–08:00 Berlin on this date. It reports no general issue; this does not prove recovery for this account.

Saved IBAutomater.log (mtime 06:15:37 UTC) records a reconnect/login sequence, two Unrecognized Username or Password dialogs and an unhandled Log In window. It has no per-line timestamps. This indicates a failed saved login sequence, not proof credentials changed or a verified view of the current UI. Do not copy raw launcher logs: they contain authentication material.

Pinned vendor IBAutomater IsWithinWeekendServerResetTimes treats all Saturday as reset time and can suppress LoginFailed handling. The controller retries only after process exit; an alive login window does not trigger systemd Restart. Native recovery has not completed. Do not weaken this guard or retry login blindly.

Telegram reconciliation alerts accepted at 07:10:11, 07:40:11 and 09:10:12 Berlin; outbox 940/943/946, message 138/142/145. Earlier 04:41:49 API recovery belongs to a monitor deployment, not this upstream outage. Upstream incident remained open since Oct29 because the prior end-handler never resolved it; its age is not actual outage duration.

Fix: persist 2110 as upstream loss, retain early loss across managedAccounts initialization, close upstream/reconciliation/connection incidents only after fresh complete broker readback with upstream connected, and distinguish upstream Telegram headers. Do not emit a recovery for this still-open incident. Trading, PAUSED and MAINTENANCE remain independent.

Verification: full isolated offline suite and secret scan required before Git deployment. Reload only existing safety/notification owners after deployment; preserve Gateway and private state. Actual recovery must subsequently be verified from 1101/1102 plus full readback and a real Telegram receipt.
