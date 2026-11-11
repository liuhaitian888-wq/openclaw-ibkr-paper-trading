## Why
Root disk is82percent with roughly6.72GiB available, dominated by protected historical copies. Owner requires real future-growth controls and bounded local archiving while retaining historical/critical data. Capacity monitoring first release remains independent.

## What Changes
Add opt-in optional-write budgets for public research/directory producers, fixed diagnostic ring and existing capacity-owner/shared-health exposure. Add a manual public-artifact archive client with target quota/headroom, chunk checksums, resume/dedup and quarantine byte-restore validation. Cleanup is dry-run-only; no deletionAPI.

## Capabilities
### New Capabilities
- `storage-growth-governance`: Semantic retention, bounded optional writes and finite verified local copies.

### Modified Capabilities

## Impact
Standard library only, no daemon/DB schema/sender/broker changes. Existing optional producers defer before DB/network work when armed. Core financial/task/UNKNOWN/receipt state remains exempt and protected. Source/metadata audit and small actual archive receipts are separate from publisher deployment/native secretary acceptance.
