# Secretary cloud API migration plan

Approved goal: gpt-6.1-sol / low via OpenAI Responses API on Hetzner; no Mac OAuth copy, no secrets in chat/Git/logs. Preserve inbox/outbox/notification owner, trading gates and uncertain runs.

1. Verify official model/API docs, live Git identities and read-only smoke. Keep account model access unverified until a real keyed call.
2. Reuse existing bounded prompt/tool/checkpoint executor with injectable inference/RPC. Gate model claiming by persisted model_owner to prevent Mac and cloud competing. Reject Mac-only tools on cloud with explicit unavailable evidence.
3. Add single-request HTTPS Responses adapter with fixed origin, bounded output/time, no redirects/retries, no native tools, store=false, sanitized errors, root/systemd credential delivery and durable public-result receipts. Retain STARTED/UNKNOWN; never replay automatically.
4. Add cloud systemd model owner using existing archive/RPC/queue and shared health observations. Keep dormant until credentials, owner policy and arm all approved. No new Telegram receiver/sender, no broker access.
5. Provide root-only getpass installer directly over SSH TTY; save root-owned0600 outside repo, use systemd LoadCredential. User enters secret only in private terminal. Prepare complete offline tests and secret scan before Git integration/deployment.
6. After user key entry: bounded real model availability/low response check, switch new claims to cloud, keep old runs unchanged, verify fresh native owner private instruction→cloud model receipt→archive→existing delivery owner native reply with Mac bridge disabled. No test group message or transaction.
7. Update existing OpenSpec change/current specs/context/engineering and five-project evidence. Real key access and end-to-end reply remain BLOCKED until actually observed.
