# Nov9 inherited Paper protection scope

Owner explicitly instructed to add missing protection without asking again. This is a finite reduce-only authorization for PAPER DUQ503649, separate from paused strategy entries. It does not adopt legacy holdings into a new strategy, cancel/replace orders, enable entry, reset NVDA3/3, or release PAUSED/MAINTENANCE.

## Exact action

Only AAPL<=17, META<=100, MSFT<=13, NIO<=200, T<=3 existing positive integer USD/STK positions. PFE and every existing symbol order are preserved. At most5 immutable order occurrences, at most1 new protective order/run, one dated Nov9 timer window. Each order is SELL STP/GTC with outsideRth=false; trigger is floor(fresh live bid*0.95/broker minTick)*minTick. The5% fallback already exists in trading/position_protection.py (STOP-001); it is a temporary Paper policy, not calibrated optimal loss control. A gap can execute below trigger; plain STP does not provide round-the-clock protection.

The general100-share/2000USD entry limit is not a reason to leave a200-share inherited NIO position partly uncovered. This scope cannot increase position or submit BUY; its quantity is bounded by broker position and immutable inherited maximum. Other active orders on a symbol block adding a stop to avoid overcoverage/short exposure; no ownership inference or cancellation.

## Evidence before transport

- Exact approved code/branch/workspace/state/account scope; expiry at2026-11-09T21:00:00Z; operator pause/maintenance and production.json hashes preserved.
- Regular US session plus broker liquidHours/timeZoneId; exact contract details/minTick; native type1 bid/ask with both receipt timestamps<=3s and uncrossed bounded spread.
- Fresh positions, active orders, completed-order end and executions end. The oldest end timestamp must be<=5s, not merely the final snapshot serialization time. Mixed account/ambiguous duplicate symbol contracts block.
- No global STARTED/UNKNOWN order operation or pending audit intent. Fresh readback repeated after quotes and before the exact immutable intent is durably reserved.

A dedicated ibkr oneshot owns one kernel lock, at most one temporary non-overlapping quote stream per run (legacy5 symbols exclude current PFE/BAC/KO quote owner), all end-marker requests and the client disconnect. Client18992 never places entries or invokes order cancellation. Timeout110s, systemd start bound140s, stop15s; no service in a worktree. Uses the already pinned news-venv/ib_async; no new package or unverified upstream adapter installed.

## Durable outcome

Canonical audit protection_repair_attempts/events and order_requests STARTED commit before transport. RecoveryCoordinator order operation is independently persisted before placement. Any lost ACK, partial/changed quantity, interruption, timeout, unmatched contract/position/price or extra same-symbol order is UNKNOWN; no timer replay or new key bypass. Explicit native201 rejection consumes that occurrence and is not silently retried.

CONFIRMED requires submitted/pre-submitted native state, positive permId, exact scoped orderRef/account/conId/side/type/tif/transmit/quantity/stop price and a new complete four-end readback proving exact remaining protection and position. Broker rejection/UNKNOWN/CONFIRMED results enqueue one owner-only notification through the existing notification owner. Waiting for session/quotes is local status, not an invented success or repeated alert.

## Remaining boundaries

Offline/fake broker tests do not prove native acceptance. The maintenance smoke must report WAIT_SESSION with zero orders; actual Nov9 regular-session first submission is separately recorded and notified. Until native readbacks show coverage, all5 remain unconfirmed. Full continuous strategy execution, fresh USD funding/FX, canonical ownership, atomic entry-budget reservation and native partial-entry-fill/restart acceptance remain independent P0 requirements. This repair does not set any global business gate healthy.

Validation: final isolated worktree suite1009 tests/41.471s/OK, including pure scope/coverage/age/identity cases, ACK loss/interruption/restart non-replay, native adapter exact-price/quantity/contract/extra-sell rejection and own-client cleanup. FD regression5 for300 cycles, endurance FD4/threads1->1. Source interfaces checked against the existing pinned ib_async review and cloud news-venv imports without connection. systemd-analyze calendar confirmed dated UTC timer. Scope additionally requires an explicit USER/PROTECTIVE_REPAIR_AUTHORIZATION event in the existing secretary archive with CODEX_OWNER_CHAT source; numerical delegation alone does not masquerade as native Telegram instruction. Deployment/native results live in state/engineering/p0-execution-20261109 and local engineering/p0-execution-20261108.

## Native acceptance — 2026-11-09 regular session

After one owner-authorized, durably reserved Gateway login recovery at20:40:05Z, exact Paper native and independent readback recovered. A temporary10197 competing-live-session fault subsequently cleared; this was not an exchange closure and no other account session was forcibly disconnected. The already approved timer submitted its original five immutable protective occurrences, without resetting IDs or expanding quantities/budget.

|Stock|Covered shares|STP trigger USD|Native permId|Confirmed UTC|
|---|---:|---:|---:|---|
|META|100|613.67|2068984074|20:46:02|
|NIO|200|3.25|2068984075|20:48:02|
|T|3|20.58|2068984076|20:49:01|
|AAPL|17|334.09|2068984077|20:50:01|
|MSFT|13|519.64|2068984078|20:51:01|

Independent current broker projection at~21:06Z showed all six held securities PROTECTED, all new stops PreSubmitted/GTC/transmit=true and exact remaining quantities; PFE8/23.01USD/perm911411084 was preserved. Readback age3.009s. The five operation journal outcomes areCONFIRMED, with0 STARTED/UNKNOWN broker order operations. Existing notification uncertainty is separate: two deliveryUNKNOWN operations (old notification953 and today's financial report1094) remain unreplayed.

Each five-stop notice and actual Nasdaq/NYSE core close plus ETFplus phases reachedTELEGRAM_ACCEPTED, which proves server acceptance, not phone display. Completed, expired finite timer was disabled/stopped after native verification; broker GTC stops remain, original expiry/budget/spent FX scope and global entry gates unchanged. No new BUY or extra currency exchange occurred. Ordinary STP remains regular-session-only; current coverage is a point-in-time broker fact, not perpetual protection or calibrated maximum loss.

Evidence: private engineering/continuous-entry-20261109/protection-final-native.log and native-recovery-and-settlement.json; canonical auditprotection_repair_events. Source cloud9f66cd8. This acceptsP0 task2.2 only, not continuous stock entry, ownership adoption, settlement, T0 or formal strategy release.
