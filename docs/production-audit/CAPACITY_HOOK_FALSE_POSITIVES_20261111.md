# Capacity closeout hook: five exact source-fingerprint false positives

Event `dc7ab596d7d2b42f4fe1d993`, canonical main base877b4f4. The stop hook scans a temporary copy of Git-tracked plus nonignored-untracked files. Its report contains exactly five generic-api-key findings in `.der/maintenance/diagram-dependencies.json`. Pre-commit uses a staged scan and therefore its earlier PASS does not disprove the hook result.

All five JSON values were independently recomputed using SHA256 of the named source file bytes, with five exact matches. They are file fingerprints with explicit source provenance, not credentials. Existing receipt line shifts left the prior exact ignore entries insufficient.

| Receipt line | Referenced source | Recomputed SHA-256 |
| --- | --- | --- |
| 84 | ops/cloud/secretary_rpc.py | d5cfdb85e54d5d82ecac7f7c55ced87ef9419f387fbf601c03da1dd4b582809e |
| 118 | ops/cloud/secretary_cloud_oauth.py | 064d1a67098cd9b73c7f9a44dd295fe16b5057c90bd655920880cd9445499dcd |
| 119 | ops/cloud/secretary_rpc.py | d5cfdb85e54d5d82ecac7f7c55ced87ef9419f387fbf601c03da1dd4b582809e |
| 133 | reporting/secretary_read.py | 46c09392c866ba1c99d545ceffdc13fc785c6ae8e5581b95f225e21dd1df5f12 |
| 134 | scripts/run_secretary_bridge.py | 56e51e6fdfdec56b49684c6a4ed8e7258b47f370023d60f481d10ad01acf00cd |

Only the five exact `file:rule:line` fingerprints are added to `.gitleaksignore`; no whole file, rule, directory or entropy class is excluded. Future source/line changes require re-verification. The original redacted hook-scope report and source-byte verification are retained privately as engineering/capacity-engineering-loop-20261111/hook-exact-scan.json and hook-fp-verification.json. A separate exploratory no-git scan also traversed Git-ignored local credentials/reports; its redacted report is outside Git and is not the hook's five-finding scope. No local credentials or historical reports were copied into a commit, changed or deleted.

This is a documentation/scan-exclusion correction, not a runtime fix or cloud deployment. A/B1 real event handoff/admission acceptance remains as independently recorded; C archive reuse remains a source/offline candidate, excluded from this release's current specification. The diagram specification/HTML and source hashes are unchanged; semantic source mapping was verified above, so no redraw is needed.
