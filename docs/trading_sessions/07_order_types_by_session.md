# Order Types By Session

- Market entries are disabled outside regular trading hours.
- The first autonomous runtime uses bracket-style paper order proposals because they include stop protection.
- Limit-only smoke orders remain supported elsewhere, but autonomous new entries should prefer protected proposals.
- If a broker-side attached stop is not available for a session, the runtime must track a synthetic stop and document the gap.
