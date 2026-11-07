# Owner privacy and notification center implementation plan

Goal: Allow friends in der to see owner-authorized daily reports without granting account queries, credentials or secretary access; offer short, previewable, categorized notifications.
Architecture: Preserve IncidentStore/outbox/uncertain-send semantics. Deterministic policy classifies events, separates owner-private delivery from allowlisted generic group operations and explicitly authorized public daily reports, renders compact HTML and provides an owner-only inbox. Existing Telegram/SMTP/Feishu adapters remain the sole channel owners.
Constraints: Worktree-only offline tests; no broker mutation, failure drill, credential exposure or trading gate changes. No third-party source copying. Existing independent Healthchecks continues outside this pipeline.

- [x] Implement shared-group identity verification and exact native owner private target; reject forged/forwarded/anonymous/foreign commands.
- [x] Add category/source/read-watermark/preferences tables and owner commands /inbox /event /read /notify /preview /start. Unknown categories stay private. Critical alerts cannot be muted.
- [x] Compact HTML with first lines plus expandable details; safe group summaries use constants only. Update same-incident Telegram text card, preserving every outbox receipt; unknown outcomes never replay.
- [x] Test privacy routes, audience changes, HTML escaping, edit receipt and timeout, unread transitions, mute protections and deterministic commands.
- [x] Document bot responsibilities, Healthchecks coverage, FYI availability and category examples; record upstream reference URLs without claiming integrations.
- [ ] Full offline suite + gitleaks, Git deployment, private target verification and read-only production checks. No synthetic external alert.
