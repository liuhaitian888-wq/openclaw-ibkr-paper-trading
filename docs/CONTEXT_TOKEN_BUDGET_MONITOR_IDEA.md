# Context Token Budget Monitor — Research Backlog

Status: research only; not part of the trading-core implementation priority.

## Goal

Warn when a task may be approaching its usable context budget and recommend a
compact project digest or handoff. A later iteration might become a standalone
Codex skill.

## Verified capability boundary

- The OpenAI Responses API returns response-level `usage`, including input,
  output, and total token counts:
  https://developers.openai.com/api/reference/cli/resources/responses/methods/create
- The Responses API also provides `POST /responses/input_tokens` to count the
  input for a request before generation:
  https://developers.openai.com/api/reference/cli/resources/responses/subresources/input_tokens
- These API measurements do not establish the current Codex App task's exact
  live context occupancy. As of 2026-08-24, the official OpenAI documentation
  reviewed for this note did not document a Codex App interface exposing that
  exact real-time value or percentage.

## Future research

1. Check whether Codex later exposes supported task/session usage metadata.
2. If not, evaluate a clearly labelled estimate based on known handoff inputs,
   response usage, compaction events, and model context limits.
3. Never present an estimate as an exact Codex App measurement.
4. Keep all alerts advisory; they must not pause or alter trading runtime.
