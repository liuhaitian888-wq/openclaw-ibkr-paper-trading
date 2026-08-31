# Repository Instructions

## Secret Scanning

- Before committing, opening a PR, or reporting work as complete, run `pre-commit run gitleaks --all-files` when `pre-commit` is available.
- If `pre-commit` is unavailable but `gitleaks` is installed, run `gitleaks detect --source . --no-git --redact --verbose`.
- Never commit real secrets. Keep local credentials in ignored files such as `.env` or `.secrets/`, and use `.env.example` for placeholders.
- Treat any gitleaks finding as blocking until it is removed or explicitly documented as a false positive.
