# Monitor-only release, 29 October 2026

Authorization: latest user GO objective in execution chat permits safe monitor integration and takeover, keeps trading disabled, reuses existing29Oct13:30UTC passive acceptance timer, forbidsGateway restart/PFE mutations. This supersedes the earlier no-production-switch limitation only for verified monitoring.

This release is projected directly from productiona31c1c5. Market files are taken from readiness6cfe558, excluding all TradingService/Audit/Mode9/position_protection/strategy_modules changes. Those files remain byte-identical to production baseline. T4-v2 symbol policy, durable subscription lifecycle and signal-only observer are reused, not a second controller.

Changes: account-only independent readback (noL1); onepaper_safety owner; max4 durable subscription recovery batches per incident; cooldown plus later actual session/upstream transition required to rearm, never restart/time/repeated fault alone; UNKNOWN reservations remain held. Verified explicitNYSE28/29/30Oct sessions permit safe closed→regular transition; unknown dates retain normal calendar verification/fallback. Holiday/early-close regressions fixed without changing tests. Completed historical update supersedes pending partial; history-only gap repair uses original budget. Type/bid/ask/last/broker timestamps recorded separately.

Exact isolated release validation:669tests/58.743s PASS. First run found2calendar regressions, fixed;17focused calendar/rearm tests passed and final full run passed. Full suite disabled realTCP and used temporary state. No productionfault injection. Scan gitleaks and diff check required before release.

Takeover: assert clean productiona31c1c5 and closed execution gates; fetch exactGitbundle; temporarily pause readback timer, stop onlyoldpaper-safety; verifyoldPIDgone andFLOCKreleased. Back up manifests/fullrecoverySQLite and preservehistory. Fast-forward existing production branch to this release, atomically bind monitor manifest to actualcommit/path, keepready=false and trading controls unchanged. Startsinglepaper-safety then resume existingreadback timer. VerifynewPID/lock/account/fullendmarkers/PFEread-only, stableGatewayPID and same existingacceptancetimer.

Rollback safety: any failure keeps execution closed. Preserve newDBtables and logs, never overwrite historicalstate. If candidate cannot run, keep monitoring stopped rather than reactivating unlimited-retry baseline. A code rollback may usegit reset --keep only after a clean-tree check, restoring saved manifests; oldmonitor/readback remain stopped until bounded behavior restored. Do not restartGateway or cancel/replacePFE.

Expected bounded overnight state: exhaustedlegacy130+budget is inherited as4; no artificial fresh retry allowance. Safe heartbeat/accountreadback continue. Next verifiedregular-session transition aftercooldown may rearmonce, using the sameowner. Missingreal1100/1101/10197 and currentclosed-market bars remainPENDING, not proof of failure/recovery.

## 09UTC follow-up — real 1102/session-boundary interaction

Observed real upstream1100/1102 at05:30UTC and later PREMARKET boundary08:00UTC. Current complete Paper readback recovered, but RECONCILE_ONLY veto prevented rearm of the previously exhausted legacy episode. Fix: a later verified session condition may rearm after cooldown, including PREMARKET→REGULAR, while1102 by itself preserves streams. Permission-review and UNKNOWN holds remain blocked. Each rearmed episode keeps the existing max4 budget. No direct state/budget reset.

Only symbol_health and its regression tests changed relative toe08492a. Existing monitor-only worktree suite672/57.053s PASS; existing bounded fault/lifecycle cases reused. Tests cover1102-alone no rearm, later session rearm, max4 consumption through policy and transport, permission denial preserved. Final scan and diff checks PASS. Source readiness changes65a81f2/4ff2bcd/ce411cf projected by explicit file list; trading candidate54f647d excluded.

Rollback is monitor code back toe08492a with matching monitor-only manifests and a single held lock. Preserve current recovery DB and audit history; do not roll counters/state back after subscriptions were attempted. Keep PAUSED/MAINTENANCE, kill=true, transmit=false, API/strategyinactive. Gateway and PFE orders unchanged.
