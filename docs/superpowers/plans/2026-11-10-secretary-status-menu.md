# Secretary status menu

Approved scope: add deterministic /api, /cloud and /market entries to the existing owner-private Telegram secretary. Read existing production observations only, with timestamps and freshness. Do not send model probes, create broker sessions or alter trading permissions.

Implementation: reuse reporting.health.resolve_modules and read-only recovery SQLite; display model provider/owner separately from connection proof and host sample time separately from current reachability. Expire old evidence and fail UNKNOWN on missing/corrupt evidence. Keep existing行情订阅/行情抽查 entries.

Validation: linked-worktree complete offline suite, missing/stale evidence regression, secret scan, Git deployment preserving current cloud commit, monitoring identity and gates, native owner-private menu set/get readback. User click acceptance remains separate.
