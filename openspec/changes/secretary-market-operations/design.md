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

## 2026-11-09 deehub route correction

Reviewed group title transition der → deehub retains exact native group, bot and owner identity. MARKET_SESSION only becomes public when checked-in calendar reconstruction matches occurrence/phase/version/expiry; group rendering ignores producer prose. Calendar-review and unrecognized events remain private. Inbox acknowledgements explicitly mean durable receipt/queue, with current Mac model dependency disclosed. Cloud API migration and source-linked public research explanations remain future work; do not infer authorization or implementation from these goals.

New SEC_EDGAR filing notifications may publish bounded validated accession/SEC URL/form/symbol/time with three fixed Chinese points: occurrence, document meaning, and unparsed financial/causality gaps. Arbitrary headline/model prose and broker/provider-only records remain private. No prior notices are replayed. This is metadata explanation, not filing-body financial analysis.

## Cloud model API migration — 2026-11-09

Reuse the bounded existing executor with injected cloud Responses inference/RPC. Fixed gpt-6.1-sol/low; native tools disabled, JSON host tools retain the same permission boundary. Root0600 credential entered through an interactive SSH getpass installer and supplied with systemd LoadCredential. Existing Telegram receiver/sender remain sole owners. Persist model_owner and cutover timestamp; deny Mac claims after switch and never resume pre-cutover READY/STARTED via a new provider. Per-turn public response receipts precede archive finalization, UNKNOWN never auto-replays. Credentials/account access and actual Mac-independent private reply are acceptance blockers until directly verified. Shared health registry gains provider-conditional credential dependency; file readability alone is not API authentication.
