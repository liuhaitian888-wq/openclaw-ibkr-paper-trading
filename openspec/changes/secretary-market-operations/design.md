# Design

## Context
Existing cloud inbox is the sole Telegram input owner and notification outbox is the sole delivery path. Trading remains independently gated. See proposal.md for motivation.

## Goals / Non-Goals
**Goals:** Lightweight, durable market awareness and private engineering review without new broker subscriptions or a second Telegram sender.
**Non-Goals:** Enabling full trading, changing stops, or treating scheduled closures as outages. Large-scale extreme-event execution remains deferred.

## Decisions
- Store reviewed official annual holiday exceptions and phase profiles in a versioned JSON manifest. Runtime uses Python zoneinfo and stdlib only; no heavy pandas import in the fast inbox. Calendar coverage ends explicitly at the last reviewed date. Compare exchange_calendars as a research source, not an unverified substitute for ETFplus phases or new Italian 2027 rules.
- Model scheduled phases separately from runtime API health, halts and entitlement. ETFplus random auction ends are disclosed and use a conservative 30-second guard before declaring the next phase.
- Persist per-venue cursor and outbox enqueue atomically in recovery.sqlite3; emit only current state after restart and disclose gaps. Ordinary polling is bounded; no historical alert replay.
- Generate owner-private weekly engineering packet Sunday 18:00 Europe/Berlin using immutable archive evidence and explicit coverage limits. Existing financial weekly reports remain separate. Scheduled Codex review is a separate app automation and cannot silently deploy.
- Reuse engineering proposal archive; copyable prompt is valid fallback until an official Codex consumer is independently verified. Keep model proposals lower authority than native owner instructions.

## Risks / Trade-offs
- Official calendar revisions → provenance URL, verification date, bounded validity, stale notice, review task.
- Instrument ticker ambiguity → explicit EQQQ contract and venue binding only; no connected-account positions copied into Paper.
- Host downtime → one current-state message, not stale phase replay.
- Large weekly payload → bounded evidence and private prompt artifact; delivery receipt is separate from report generation.
- Concurrent deployments invalidate finite scopes → merge only through Git, test combined source, reconcile scope dependencies without increasing authorization.

## Migration Plan
Offline verification in linked worktree, secret scan, Git merge into designated workspace, quick smoke, approved cloud code deployment with identity manifests and finite-scope reconciliation. Rollback disables only the new producer, retains outbox and cursor evidence, and never restarts trading.
