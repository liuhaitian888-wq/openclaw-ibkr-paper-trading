# Installation Guide

## From Source

```bash
git clone <repo-url>
cd OpenWorkspace
swift build
swift test
swift run OpenWorkspace
```

## Optional Dependencies

Install Sunshine separately if Android display streaming is needed in future milestones.

BetterDisplay integration is planned as an external dependency. Do not copy BetterDisplay code into this repository.

## Local Configuration

Use the templates in `Config/` as references. Do not commit real workspace files, runtime state, logs, pairing material, or device identifiers.
