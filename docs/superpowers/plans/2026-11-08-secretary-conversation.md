# Secretary conversation implementation plan

**Goal:** Owner messages support ordinary conversation, bounded tasks and research without automatically treating every message as a research topic.
**Architecture:** Keep the authenticated inbox and durable paid-run ledger; add response modes and recent same-chat conversation context. Autonomous instructions remain research. Python controls and all privacy/trading gates remain independent.
**Tech Stack:** Python, SQLite, existing constrained model bridge and Telegram outbox.
**Spec:** Owner request 2026-11-08: simple conversation must not become a topic/task.

## Constraints and review focus
- Linked worktree only; full isolated offline suite and gitleaks before Git deployment.
- Only exact owner messages; context from completed same-chat user runs, never autonomous output or other members.
- CHAT is default; optional /chat, /task, /research explicitly select a mode. No extra classification model call.
- Preserve UNKNOWN/no-replay, daily spend bound, private destinations and trading gates.
- Context truncated and bounded; research-specific fields only for research, task progress only after actual tool use, chat has no research footer.

### Task 1: Modes and conversation context
- [ ] Add pure mode helpers and bounded previous completed exchange context; test isolation and overrides.
- [ ] Wire bridge prompt, RPC result kind, progress and durable reply role; test chat versus research delivery.
- [ ] Run full offline suite and secret scan; commit/cherry-pick, deploy manifests preserving gate hashes and verify identity.
