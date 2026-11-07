# Evidence-first intelligence Implementation Plan

**Goal:** Operate a bounded, source-audited Telegram intelligence intake for the user's five selected categories, retaining explicit unavailable capabilities.

**Architecture:** Official RSS/SEC oneshot and existing approved IBKR news adapter, each with one lock and bounded lifetime. Both archive in the secretary database and enqueue to the existing notifications owner; fresh records can create a capped research task. No model-native broker tools or automatic trading enablement.

**Tech Stack:** Python stdlib HTTP/XML/SQLite, existing ib_async, systemd timers, existing secretary/outbox.

**Spec:** User request 2026-11-07: reference repository URLs in one place, news/SEC/earnings/macro/market/portfolio intelligence, source/plugin/automation distinction, Telegram notifications and activity updates. SEC technical contact explicitly supplied privately. User requested direct execution and no extra agents.

## Constraints and review focus
- Worktree-only full offline suite; main quick smoke; gitleaks; commit and Git ff-only cloud deployment.
- Real owner identity, correct Paper account, existing PAUSED/MAINTENANCE/3-of-3 exhausted test scope unchanged.
- First startup archives history without backfill spam; revised source content retains provenance.
- Unknown HTTP outcomes never replay; deduplicated enqueue repairs cross-database crash windows.
- SEC contact appears only in private configuration/SEC User-Agent, cross-host redirects blocked before transmission.
- Neither news proximity nor price correlation proves causality; missing prices/volume/consensus/rights remain missing.

### Task 1: Sources and integration
- [x] Centralize 16 traceable repository URLs and verify GitHub metadata; retain pins/licenses/status.
- [x] Implement reporting/intelligence.py and finite cloud public/broker entrypoints; reuse trading/news_feed.py.
- [x] Add two systemd oneshot/timer pairs; dependencies belong in reporting.health.
- [x] Add public secretary progress milestones without private reasoning.

### Task 2: Checks and activation
- [ ] Run final complete offline suite and secret scan; commit, integrate into main, smoke and ff-only cloud bundle.
- [ ] Activate approved read-only policies/timers; test real HTTP and scoped broker results, native Telegram receipts and no duplicate owners.
- [ ] Save source coverage/results, refresh DB console, make report/logs reviewable.

Execution is already authorized. Similarweb onboarding/API rights and unlicensed paid news feeds must not be called connected without verification. No new paid subscriptions have been purchased.
