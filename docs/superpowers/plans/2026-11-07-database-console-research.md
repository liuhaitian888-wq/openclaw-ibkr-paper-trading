# Database console and secretary research Implementation Plan

**Goal:** Deliver a bounded read-only database status page, isolate secretary OAuth, and establish evidence for historical data and reproducible research.

**Architecture:** An on-demand collector reads fixed state paths and backup manifests; a static HTML page renders its sanitized JSON. No production worker or broker connection is created. Secretary credentials and research artifacts have separate owners/state; existing execution gates remain authoritative.

**Tech Stack:** Python standard library, SQLite read-only URI, static HTML, official Codex CLI OAuth.

**Spec:** User request 2026-11-07 in this chat: database page in VS Code without affecting trading/monitoring; OAuth secretary; evidence-based research, paper replication, source attribution.

## Global Constraints
- Preserve all gates/orders/owners and unrelated work; develop/test in linked worktree.
- Do not store the supplied email password; OAuth stores tokens only in private isolated state.
- Expose no database editing, restore, checkpoint, vacuum or unrestricted SQL buttons.
- Bounded read-only SQL; no live full-database integrity scan. Distinguish observed file mutation, known business timestamp, backup readability, checksum verification and restored integrity.
- UNKNOWN model/tool outcomes must never auto-replay side effects.

## Review Focus
- Missing/symlinked/corrupt databases remain visible without creating a file.
- Expensive last-write queries are interrupted on a per-query budget.
- Malformed/traversing backup manifests never read outside state.
- Old backup success is never displayed as current live integrity PASS.
- Untrusted text is escaped in HTML; private account/credentials are not exported.

### Task 1: Database status page
- [ ] Add reporting/database_console.py with fixed inventory, stat evidence, read-only timestamp probes and manifest status.
- [ ] Add bounded tests for missing/WAL/corrupt state, provenance, untrusted manifests and escaped HTML.
- [ ] Run full offline suite + gitleaks; commit and integrate via Git.
- [ ] Run on-demand cloud read-only collector; display saved HTML/JSON in VS Code and visually inspect.

### Task 2: Isolated secretary authorization
- [ ] Start official device authorization with separate CODEX_HOME, without touching desktop credentials.
- [ ] Human completes intended account authorization; verify identity/account access without printing tokens.
- [ ] Validate a bounded read-only analysis turn and persist public output and usage in secretary archive.
- [ ] Connect authenticated Telegram owner messages via a single approved receiver; preserve durable delivery and execution gates.

### Task 3: Research evidence and reusable projects
- [ ] Inspect actual saved quote/bar/execution schemas and time ranges; distinguish on-disk coverage from vendor capability.
- [ ] Define paper retrieval → hypothesis → point-in-time dataset → costs → isolated backtest → out-of-sample validation → report lineage.
- [ ] Reuse selected upstream patterns with pinned commits/license attribution; avoid parallel frameworks and unreviewed auto-trading.
- [ ] Document offsite backup requirements, multi-agent roles, SDK meaning and unfinished acceptance.

Execution is already authorized; work continues natively in this session. No deployment of trading, archive migration or purchase of data is authorized by this plan.
