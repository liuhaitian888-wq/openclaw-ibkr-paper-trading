# deehub delivery repair implementation plan

Goal: coordinate native rename with exact identity validation, move only fixed calendar templates to the group, and replace misleading ACKs.
Architecture: retain existing inbox, outbox, delivery owner and immutable uncertain attempts. No broker operations or new sender.
Spec: owner request 2026-11-09; AGENTS.md and PRODUCTION.md.

- [ ] Verify Mac/GitHub/cloud identities, retain all concurrent work; audit Nov8/9 delivery receipts and secretary results.
- [ ] Allow reviewed group titles der/deehub while retaining exact native chat/bot/owner checks. Re-render public calendar notices from the checked-in calendar; ignore arbitrary producer prose. Add privacy and rename regression tests.
- [ ] Change inbox ACK to received/queued with explicit unverified execution and Mac bridge dependency. Audit cloud API credential availability without exposing or copying credentials.
- [ ] Run complete worktree suite and gitleaks; integrate through Git; back up cloud configuration/state and exact deployment manifests. Recheck parallel HEAD, expired scopes, reload only affected existing owners.
- [ ] Native get/set/get name and descriptions, coordinate expected title update; no test messages. Read-only smoke, receipts audit, document unresolved UNKNOWN and API migration blockers.
- [ ] Record OpenSpec/context impact and refresh five-project collection. Do not call untested behavior verified.
