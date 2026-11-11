# Report period cutoff repair

Execution: native, linked worktree from exact productionc3443a2; no SOURCE22bac/backup-tool/new-owner code in this patch.

Goal: prevent a fresh pre-20:00NY preview for an older session from being sent at09:00Shanghai after the required complete session changes.

Preserve existing NY20:00 completeness, calendar, 600s source freshness, exact Paper account/environment/end evidence, schedule, once-only supplement and UNKNOWN handling. Cache identity must include report period. Dispatch recomputes the required period and source close coverage. Pre-close source cannot be relabelled as post-close; return an explicit wait and build the new period only after genuinely completed fresh source arrives. No attachment-name/transport edits here; notificationowner handles those.

Files: scripts/report_aggregation.py exposes existing session close; reporting/financial_reports.py gates source coverage/cache period; reporting/report_schedule.py revalidates period/source with meaningful missing reasons; report_rendering.py clarifies report date versus trading period and invalidates old label cache. Regression tests cover winter cutover, same-source wrong cached period, summer/DST, weekend/holiday, pre-close source and one safe supplement. Fixtures use actual period_for semantics, not arbitrary periods.

Steps: failing regression first; minimal patch; focused and complete isolated suite; all-files gitleaks/strict OpenSpec; hand exact immutable patch to existing publicationowner. Preserve historical1778/group256 and1895warning293; no old PNG substitution, no forced source recovery or parallel broker/API connection. No production writes by report engineer.
