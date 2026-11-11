# Secretary development work view implementation plan

Goal: Show the actual engineering child state through the owner's existing /work command and either short reference.
Architecture: Bounded read-only archive aggregation joins existing engineering tasks by requested_by_run or direct native instruction. Keep child completion, deployment and reply delivery separate. Missing legacy table leaves ordinary views usable; malformed child data is not promoted to success.
Tech stack: Python, SQLite, existing secretary presentation and isolated unittest suite.

- [x] Add regression cases for parent reply succeeded while child UNKNOWN, PATCH_READY without deployment, child-reference lookup, direct diagnostic and legacy missing table.
- [x] Implement bounded read-only engineering projection without creating tables, workers or notifications.
- [x] Update existing OpenSpec work-view scenario and closeout evidence; topology unchanged.
- [x] Run focused tests, complete linked-worktree offline suite, strict specs and all-files secret scan. Commit only scoped files; unique publisher owns integration/deployment.
