# Telegram group migration and Gateway acceptance plan

**Goal:** Restore exact der audience validation and demonstrate a bounded Gateway disconnect/recovery through existing incident delivery.

**Architecture:** Keep existing outbox, original notification owner and Gateway service. Explicitly reconcile the old-to-new chat migration; permit only the verified Healthchecks bot as one extra ordinary member. No automatic migration, unknown replay, second Gateway or trade authorization.

**Scope:** User authorized a controlled Gateway disconnect/reconnect and Telegram acceptance. Existing positions/orders and global gates remain unchanged. Market 10197 competition is a separate untested scenario.

- [ ] Implement read-only verify_audience and explicit bounded additional-bot identity configuration.
- [ ] Verify exact ID/username/is_bot/member status and unchanged owner/count; reject impostors, humans, admins and fourth members before send.
- [ ] Full linked-worktree offline suite, gitleaks, Git integration and production smoke.
- [ ] Back up deployment/config, deploy through Git, update identity before controlled owner reload; read-only target proof.
- [ ] Freeze original positions/orders, gate hashes, closed acceptance scope and unknown-operation counts. Stop existing Gateway once with a separately armed bounded systemd recovery timer; observe fault ACK, restore original service, verify new broker readback/recovery ACK and unchanged exposure/gates.
- [ ] Finish external Healthchecks group binding/Down-Up as a separate acceptance only after exact group target proof. Preserve email until replaced path verified; never replay historic messages.
