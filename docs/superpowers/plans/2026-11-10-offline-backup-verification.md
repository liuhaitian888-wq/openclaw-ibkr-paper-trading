# Offline backup verification Implementation Plan

> Execution: native in this already-authorized session, isolated linked worktree. No production publication or new service is part of this tool.

**Goal:** Repeatably validate the existing minimal four-database backup tar without restoring live state or granting recovery authority.

**Architecture:** A standard-library verifier reads a bounded, flat uncompressed tar (backup.json plus four fixed gzip names), validates the manifest, writes exclusive checker-owned copies into a new0700 directory, and checks hashes/SQLite read-only. It records a private receipt, preserves failed outputs and never extracts archive paths or deletes source data.

**Tech Stack:** Python3.13 standard library, prescribed isolated unittest runner.

**Spec:** openspec/specs/project-maintenance/spec.md, Offline backup copy verification.

## Global Constraints

No network/subprocess/credentials; no daemon, scheduler, production DB path, live restore, deletion, UNKNOWN replay or publication permission. Root output is caller-selected; existing files never overwritten. SHA agreement does not authenticate the manifest; per-file checks do not prove cross-database consistency. Limits:200MiB tar,4MiB manifest,50MiB per gzip,512MiB per decoded DB,2GiB total,60s overall/20s per SQLite check. Four expected DB identities only; required restore reconciliation flag. Failure retains a safe receipt/new partial copies when available.

## Review Focus

Reject traversal/link/duplicate/extra entries before any member is copied; reject partial/malformed/ambiguous manifest; cap gzip expansion and deadline; reject matching-hash corrupt SQLite; preserve original/unknown rows and never label copy-check as restored or origin-authenticated.

### Task 1: Verifier and CLI

Files: reporting/backup_verification.py; scripts/verify_state_backup.py; tests/test_backup_verification.py; docs/OFFLINE_BACKUP_VERIFICATION.md.
Interface: verify_archive(archive_path, output_root, *, expected_archive_sha256=None) returns a sanitized receipt or raises BackupVerificationError(code, workdir). All artifacts are in one new private workdir. Source tar opens nofollow/read-only and is hashed before/after. Existing input/output data is not changed.

- [x] Write regression cases and observe missing-module failure.
- [x] Implement safe member streaming without extract/extractall, fixed manifest mapping, bounded decode and read-only/query_only SQLite copies; no recovery entry point.
- [x] Run complete python scripts/run_worktree_tests.py with supported venv; scan all-files gitleaks; validate current+delta OpenSpec.
- [x] Use the already-private copied backup tar for a local operational readback acceptance, with source/hash unchanged and no production/network activity.
- [ ] Commit/push standalone task branch and hand off exact source; do not compete with main/cloud WaveB owner. Record source/offline/operational/remaining boundaries and refresh five-project collection.
