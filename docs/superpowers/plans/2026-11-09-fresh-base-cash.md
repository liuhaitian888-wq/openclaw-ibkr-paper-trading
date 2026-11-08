# Fresh base cash Implementation Plan

**Goal:** Every reused client cashbook obtains a fresh base-currency ledger end, even if cached EUR cash exists.
**Route:** dee bugfix-lifecycle; current gates scope_confirmed/root_cause_documented; implementation and deterministic verification roles kept distinct in evidence. User authorized P0 funding repair, no additional account permission needed.
**Files:** trading/currency_book.py; tests/test_currency_book.py; P0 evidence/spec/context closeout.
**Cause:** Conditional base request checked presence, so a cached pre-FX EUR row could be relabelled alongside fresh USD.
- [x] Always request base ledger when base!=USD; retain cancellation on success/error.
- [x] Regression cached EUR changes and failed EUR read cannot fall back to cached cash.
- [x] Full linked-worktree offline suite; gitleaks; Git integration; main smoke.
- [x] Cloud read-only source identity and scope metadata reconciliation only if deployed; never submit FX from a calculator/what-if result.
- [x] OpenSpec/context and five-project collection, preserving prior closeouts.

Extension: one finite cash-funded conversion scope prepared/tested using existing native reference/what-if. Scope publication and native outcome stay separately evidenced; no stock release.
