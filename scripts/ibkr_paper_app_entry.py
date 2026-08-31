#!/usr/bin/env python3
"""Open and supervise the local IBKR Paper application without credentials.

This entrypoint deliberately does not type usernames, passwords, or 2FA codes,
and it never starts the trading API or an order-producing agent.
"""

from __future__ import annotations

import argparse
import json
import os
import plistlib
import socket
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Sequence


LABEL = "com.openclaw.ibkr-paper-app"
DEFAULT_TWS_APP = Path.home() / "Applications/Trader Workstation/Trader Workstation.app"
DEFAULT_TWS_PORT = 7497
DEFAULT_CHECK_INTERVAL_SECONDS = 300


@dataclass(frozen=True)
class PaperAppStatus:
    app_path: str
    app_installed: bool
    process_running: bool
    paper_port: int
    paper_port_reachable: bool
    launch_agent_installed: bool
    state: str


def process_is_running(process_lines: Sequence[str]) -> bool:
    markers = (
        "Trader Workstation.app/Contents/",
        "Jts/",
        "jts.jar",
    )
    return any(any(marker in line for marker in markers) for line in process_lines)


def current_process_lines() -> list[str]:
    result = subprocess.run(
        ["/bin/ps", "-axo", "command="],
        check=False,
        capture_output=True,
        text=True,
    )
    return result.stdout.splitlines() if result.returncode == 0 else []


def port_is_reachable(host: str, port: int, timeout: float = 0.25) -> bool:
    try:
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def launch_agent_path(home: Path | None = None) -> Path:
    root = home or Path.home()
    return root / "Library/LaunchAgents" / f"{LABEL}.plist"


def inspect_status(
    app_path: Path,
    port: int,
    *,
    process_lines: Sequence[str] | None = None,
    port_reachable: bool | None = None,
    agent_path: Path | None = None,
) -> PaperAppStatus:
    running = process_is_running(
        current_process_lines() if process_lines is None else process_lines
    )
    reachable = (
        port_is_reachable("127.0.0.1", port)
        if port_reachable is None
        else port_reachable
    )
    installed = app_path.is_dir()
    if reachable:
        state = "PAPER_API_PORT_REACHABLE"
    elif running:
        state = "TWS_OPEN_LOGIN_OR_API_NOT_READY"
    elif installed:
        state = "TWS_CLOSED"
    else:
        state = "TWS_NOT_INSTALLED"
    return PaperAppStatus(
        app_path=str(app_path),
        app_installed=installed,
        process_running=running,
        paper_port=port,
        paper_port_reachable=reachable,
        launch_agent_installed=(agent_path or launch_agent_path()).exists(),
        state=state,
    )


def open_tws(app_path: Path) -> None:
    if not app_path.is_dir():
        raise FileNotFoundError(f"Trader Workstation app not found: {app_path}")
    subprocess.run(["/usr/bin/open", str(app_path)], check=True)


def ensure_tws_open(app_path: Path, port: int) -> PaperAppStatus:
    status = inspect_status(app_path, port)
    if not status.process_running and not status.paper_port_reachable:
        open_tws(app_path)
        return inspect_status(
            app_path,
            port,
            process_lines=[f"{app_path}/Contents/MacOS/Trader Workstation"],
            port_reachable=False,
        )
    return status


def build_launch_agent(
    script_path: Path,
    app_path: Path,
    port: int,
    log_dir: Path,
    interval_seconds: int = DEFAULT_CHECK_INTERVAL_SECONDS,
) -> dict[str, object]:
    return {
        "Label": LABEL,
        "ProgramArguments": [
            "/usr/bin/python3",
            str(script_path),
            "ensure",
            "--app-path",
            str(app_path),
            "--port",
            str(port),
            "--json",
        ],
        "RunAtLoad": True,
        "StartInterval": interval_seconds,
        "ProcessType": "Background",
        "StandardOutPath": str(log_dir / "ibkr_paper_app_entry.log"),
        "StandardErrorPath": str(log_dir / "ibkr_paper_app_entry.err.log"),
    }


def install_launch_agent(app_path: Path, port: int) -> Path:
    project_root = Path(__file__).resolve().parent.parent
    log_dir = project_root / ".runtime" / "logs"
    log_dir.mkdir(parents=True, exist_ok=True)
    destination = launch_agent_path()
    destination.parent.mkdir(parents=True, exist_ok=True)
    payload = build_launch_agent(Path(__file__).resolve(), app_path, port, log_dir)
    destination.write_bytes(plistlib.dumps(payload, fmt=plistlib.FMT_XML, sort_keys=True))
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["/bin/launchctl", "bootout", domain, str(destination)],
        check=False,
        capture_output=True,
    )
    subprocess.run(
        ["/bin/launchctl", "bootstrap", domain, str(destination)],
        check=True,
    )
    subprocess.run(
        ["/bin/launchctl", "enable", f"{domain}/{LABEL}"],
        check=True,
    )
    return destination


def uninstall_launch_agent() -> bool:
    destination = launch_agent_path()
    if not destination.exists():
        return False
    domain = f"gui/{os.getuid()}"
    subprocess.run(
        ["/bin/launchctl", "bootout", domain, str(destination)],
        check=False,
        capture_output=True,
    )
    destination.unlink()
    return True


def parser() -> argparse.ArgumentParser:
    result = argparse.ArgumentParser(description=__doc__)
    result.add_argument(
        "action",
        choices=("status", "open", "ensure", "install", "uninstall"),
    )
    result.add_argument(
        "--app-path",
        type=Path,
        default=Path(os.getenv("IBKR_TWS_APP_PATH", str(DEFAULT_TWS_APP))).expanduser(),
    )
    result.add_argument("--port", type=int, default=DEFAULT_TWS_PORT)
    result.add_argument("--json", action="store_true")
    return result


def emit(payload: dict[str, object], as_json: bool) -> None:
    if as_json:
        print(json.dumps(payload, indent=2, sort_keys=True))
        return
    for key, value in payload.items():
        print(f"{key}: {value}")


def main(argv: Sequence[str] | None = None) -> int:
    args = parser().parse_args(argv)
    if args.port != DEFAULT_TWS_PORT:
        raise SystemExit("Only the default TWS Paper port 7497 is accepted by this entrypoint")

    if args.action == "install":
        destination = install_launch_agent(args.app_path, args.port)
        emit({"status": "INSTALLED", "launch_agent": str(destination)}, args.json)
        return 0
    if args.action == "uninstall":
        removed = uninstall_launch_agent()
        emit({"status": "UNINSTALLED" if removed else "NOT_INSTALLED"}, args.json)
        return 0

    status = (
        ensure_tws_open(args.app_path, args.port)
        if args.action in {"open", "ensure"}
        else inspect_status(args.app_path, args.port)
    )
    emit(asdict(status), args.json)
    return 0 if status.app_installed else 1


if __name__ == "__main__":
    raise SystemExit(main())
