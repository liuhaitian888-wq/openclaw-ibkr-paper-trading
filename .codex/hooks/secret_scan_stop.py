#!/usr/bin/env python3
import json
import os
import shutil
import subprocess
import sys
import tempfile
from pathlib import Path


def respond(payload):
    print(json.dumps(payload))


def run(cmd, cwd):
    return subprocess.run(
        cmd,
        cwd=cwd,
        text=True,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )


def main():
    try:
        event = json.load(sys.stdin)
    except Exception:
        event = {}

    if os.environ.get("CODEX_SECRET_SCAN_DISABLE") == "1":
        respond({"continue": True, "suppressOutput": True})
        return

    cwd = Path(event.get("cwd") or os.getcwd())
    root_result = run(["git", "rev-parse", "--show-toplevel"], cwd)
    if root_result.returncode != 0:
        respond({"continue": True, "suppressOutput": True})
        return

    repo = Path(root_result.stdout.strip())
    status = run(["git", "status", "--porcelain"], repo)
    if status.returncode != 0 or not status.stdout.strip():
        respond({"continue": True, "suppressOutput": True})
        return

    gitleaks = shutil.which("gitleaks")
    if not gitleaks:
        respond(
            {
                "decision": "block",
                "reason": "gitleaks is not installed. Install it, then run `pre-commit run gitleaks --all-files` before finishing.",
            }
        )
        return

    tracked = run(["git", "ls-files"], repo)
    untracked = run(["git", "ls-files", "--others", "--exclude-standard"], repo)
    paths = []
    for output in (tracked.stdout, untracked.stdout):
        paths.extend(line for line in output.splitlines() if line)

    if not paths:
        respond({"continue": True, "suppressOutput": True})
        return

    with tempfile.TemporaryDirectory(prefix="codex-gitleaks-") as tmp:
        scan_root = Path(tmp) / "scan"
        scan_root.mkdir()
        for rel in paths:
            src = repo / rel
            dst = scan_root / rel
            if not src.is_file() or src.is_symlink():
                continue
            dst.parent.mkdir(parents=True, exist_ok=True)
            try:
                shutil.copy2(src, dst)
            except OSError:
                continue

        result = run(
            [gitleaks, "detect", "--source", str(scan_root), "--no-git", "--redact", "--verbose"],
            repo,
        )

    if result.returncode == 0:
        respond({"continue": True, "suppressOutput": True})
        return

    details = (result.stderr or result.stdout).strip()
    if len(details) > 1600:
        details = details[:1600] + "\n..."
    respond(
        {
            "decision": "block",
            "reason": "Gitleaks found a possible secret before Codex finished. Remove it or document a false positive, then rerun `pre-commit run gitleaks --all-files`.\n\n" + details,
        }
    )


if __name__ == "__main__":
    main()
