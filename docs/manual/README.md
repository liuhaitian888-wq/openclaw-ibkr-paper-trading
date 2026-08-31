# IBKR Paper-Trading Engineering Manual

Manual version: `v0.1.0`  
Release name: `Foundation Baseline` / `初始架构基线版`  
Status: `Draft / Not yet fully system-validated`

This directory contains the reproducible source for the system-first engineering
manual. It intentionally separates documentation generation from trading
runtime behavior: the build reads source files, Git metadata, SQLite schema,
logs, and reports, but it does not connect to TWS, start Mode 9, submit orders,
cancel orders, or modify account configuration.

## Build

Use the bundled Codex Python runtime when available:

```bash
/Users/nbhsbgnb/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 docs/manual/scripts/build_manual.py
```

Fallback:

```bash
python3 docs/manual/scripts/build_manual.py
```

The build writes:

- `docs/manual/generated/manual_facts.json`
- `docs/manual/generated/manual_validation.json`
- `docs/manual/diagrams/*.svg`
- `output/pdf/ibkr_paper_trading_engineering_manual_v0.1.0_cn.pdf`

## Validate

```bash
/Users/nbhsbgnb/.cache/codex-runtimes/codex-primary-runtime/dependencies/python/bin/python3 docs/manual/scripts/validate_manual.py
```

The validation checks required chapters, diagram files, repository paths,
version metadata, placeholder/fabricated page markers, PDF readability, and the
latest build facts.
