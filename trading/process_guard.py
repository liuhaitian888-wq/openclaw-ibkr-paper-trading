import json
import os
import signal
import subprocess
import time
from contextlib import AbstractContextManager
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable, Sequence

from trading.config import PROJECT_ROOT


EXECUTION_LOCK_PATH = PROJECT_ROOT / ".runtime" / "execution_writer.lock"
REPORT_DIR = PROJECT_ROOT / "reports" / "process_guard"

EXECUTION_CAPABLE_MARKERS = (
    "scripts/run_autonomous_trading_agent.py",
    "scripts/run_autonomous_paper_runtime.py",
    "scripts/run_pool_strategy_module.py",
)
MODE9_MARKER = "scripts/run_autonomous_trading_agent.py"
AUTONOMOUS_RUNTIME_MARKER = "scripts/run_autonomous_paper_runtime.py"
POOL_STRATEGY_MARKER = "scripts/run_pool_strategy_module.py"


@dataclass(frozen=True)
class ProcessInfo:
    pid: int
    command: str
    cwd: str | None = None

    @property
    def process_name(self) -> str:
        if MODE9_MARKER in self.command:
            return "mode9_autonomous_agent"
        if AUTONOMOUS_RUNTIME_MARKER in self.command:
            return "autonomous_paper_runtime"
        if POOL_STRATEGY_MARKER in self.command:
            return "pool_strategy_module"
        return "unknown"


class ExecutionLock(AbstractContextManager["ExecutionLock"]):
    def __init__(
        self,
        *,
        process_name: str,
        mode: str,
        can_submit_orders: bool,
        prefer_mode9: bool = True,
        lock_path: Path = EXECUTION_LOCK_PATH,
    ) -> None:
        self.process_name = process_name
        self.mode = mode
        self.can_submit_orders = can_submit_orders
        self.prefer_mode9 = prefer_mode9
        self.lock_path = lock_path
        self.acquired = False

    def __enter__(self) -> "ExecutionLock":
        if not self.can_submit_orders:
            return self

        inherited = _inherited_owner()
        if inherited is None:
            inherited = _parent_mode9_owner(self.lock_path)
        if inherited is not None:
            owner = read_lock(self.lock_path)
            if owner and int(owner.get("pid", -1)) == inherited and _pid_alive(inherited):
                self.acquired = False
                write_process_guard_report(
                    action_taken="accepted inherited execution-writer lock",
                    reason=f"{self.process_name} is running under lock owner pid {inherited}",
                    execution_writer_pid=inherited,
                    lock_owner=owner,
                )
                return self
            raise SystemExit(
                f"Execution lock owner pid {inherited} is not alive or does not match lock file"
            )

        self.lock_path.parent.mkdir(parents=True, exist_ok=True)
        owner = read_lock(self.lock_path)
        if owner and _pid_alive(int(owner.get("pid", -1))):
            owner_name = str(owner.get("process_name", "unknown"))
            if self.prefer_mode9 and owner_name == "mode9_autonomous_agent":
                write_process_guard_report(
                    action_taken="blocked duplicate execution-capable process",
                    reason=f"{self.process_name} cannot start while Mode 9 owns execution lock",
                    execution_writer_pid=int(owner["pid"]),
                    lock_owner=owner,
                )
                raise SystemExit(
                    f"Execution lock is held by Mode 9 pid {owner['pid']}; {self.process_name} exits"
                )
            write_process_guard_report(
                action_taken="blocked duplicate execution-capable process",
                reason=f"execution lock is held by {owner_name} pid {owner.get('pid')}",
                execution_writer_pid=int(owner["pid"]),
                lock_owner=owner,
            )
            raise SystemExit(
                f"Execution lock is held by {owner_name} pid {owner.get('pid')}"
            )

        if owner:
            append_history(
                {
                    "timestamp": _utc_now(),
                    "action_taken": "recovered stale execution lock",
                    "reason": f"previous owner pid {owner.get('pid')} is not alive",
                    "lock_owner": owner,
                    "lock_path": str(self.lock_path),
                }
            )

        payload = {
            "process_name": self.process_name,
            "pid": os.getpid(),
            "started_at": _utc_now(),
            "command": " ".join(_current_command()),
            "mode": self.mode,
            "can_submit_orders": self.can_submit_orders,
            "heartbeat_timestamp": _utc_now(),
        }
        self.lock_path.write_text(json.dumps(payload, indent=2, sort_keys=True), encoding="utf-8")
        self.acquired = True
        write_process_guard_report(
            action_taken="acquired execution-writer lock",
            reason=f"{self.process_name} is the execution-capable process",
            execution_writer_pid=os.getpid(),
            lock_owner=payload,
        )
        return self

    def heartbeat(self) -> None:
        if not self.acquired:
            return
        owner = read_lock(self.lock_path) or {}
        owner["heartbeat_timestamp"] = _utc_now()
        self.lock_path.write_text(json.dumps(owner, indent=2, sort_keys=True), encoding="utf-8")

    def __exit__(self, exc_type: object, exc: object, traceback: object) -> bool:
        if self.acquired:
            owner = read_lock(self.lock_path)
            if owner and int(owner.get("pid", -1)) == os.getpid():
                self.lock_path.unlink(missing_ok=True)
                write_process_guard_report(
                    action_taken="released execution-writer lock",
                    reason=f"{self.process_name} exiting",
                    execution_writer_pid=None,
                    lock_owner=owner,
                )
        return False


def current_execution_processes() -> list[ProcessInfo]:
    output = subprocess.run(["ps", "axo", "pid=,command="], capture_output=True, text=True, check=False).stdout
    processes: list[ProcessInfo] = []
    for line in output.splitlines():
        stripped = line.strip()
        if not stripped:
            continue
        pid_text, _, command = stripped.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == os.getpid():
            continue
        if command.startswith(("/bin/zsh -c", "zsh -c", "/bin/bash -c", "bash -c")):
            continue
        if any(marker in command for marker in EXECUTION_CAPABLE_MARKERS):
            cwd = process_cwd(pid)
            if cwd and Path(cwd).resolve() != PROJECT_ROOT.resolve():
                continue
            processes.append(ProcessInfo(pid=pid, command=command, cwd=cwd))
    return processes


def stop_duplicate_autonomous_processes(
    *,
    keep_pid: int | None,
    timeout: float = 5.0,
) -> dict[str, Any]:
    active = current_execution_processes()
    duplicates = [
        item for item in active
        if item.pid != keep_pid and item.process_name in {"autonomous_paper_runtime", "mode9_autonomous_agent"}
    ]
    killed: list[int] = []
    for proc in duplicates:
        if not process_belongs_to_project(proc):
            continue
        try:
            os.kill(proc.pid, signal.SIGTERM)
        except ProcessLookupError:
            killed.append(proc.pid)
            continue
        deadline = time.monotonic() + timeout
        while time.monotonic() < deadline and _pid_alive(proc.pid):
            time.sleep(0.1)
        if _pid_alive(proc.pid):
            os.kill(proc.pid, signal.SIGKILL)
        killed.append(proc.pid)
    report = write_process_guard_report(
        action_taken="stopped duplicate execution-capable processes" if killed else "no duplicate execution process found",
        reason="Mode 9 has priority",
        killed_pids=killed,
    )
    return report


def write_process_guard_report(
    *,
    action_taken: str,
    reason: str,
    killed_pids: Sequence[int] = (),
    execution_writer_pid: int | None = None,
    lock_owner: dict[str, Any] | None = None,
) -> dict[str, Any]:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    active = current_execution_processes()
    mode9 = [item for item in active if item.process_name == "mode9_autonomous_agent"]
    duplicate = [item for item in active if item.process_name == "autonomous_paper_runtime"]
    owner = lock_owner if lock_owner is not None else read_lock(EXECUTION_LOCK_PATH)
    report = {
        "timestamp": _utc_now(),
        "active_processes": [item.__dict__ | {"process_name": item.process_name} for item in active],
        "mode9_pid": mode9[0].pid if mode9 else None,
        "duplicate_pids": [item.pid for item in duplicate],
        "killed_pids": list(killed_pids),
        "execution_writer_pid": execution_writer_pid if execution_writer_pid is not None else (owner or {}).get("pid"),
        "lock_path": str(EXECUTION_LOCK_PATH),
        "lock_owner": owner,
        "action_taken": action_taken,
        "reason": reason,
    }
    (REPORT_DIR / "latest.json").write_text(json.dumps(report, indent=2, sort_keys=True), encoding="utf-8")
    append_history(report)
    return report


def append_history(payload: dict[str, Any]) -> None:
    REPORT_DIR.mkdir(parents=True, exist_ok=True)
    with (REPORT_DIR / "history.jsonl").open("a", encoding="utf-8") as handle:
        handle.write(json.dumps(payload, sort_keys=True) + "\n")


def read_lock(lock_path: Path = EXECUTION_LOCK_PATH) -> dict[str, Any] | None:
    try:
        payload = json.loads(lock_path.read_text(encoding="utf-8"))
    except (FileNotFoundError, json.JSONDecodeError):
        return None
    return payload if isinstance(payload, dict) else None


def process_cwd(pid: int) -> str | None:
    try:
        output = subprocess.run(["lsof", "-p", str(pid), "-a", "-d", "cwd", "-Fn"], capture_output=True, text=True, check=False).stdout
    except FileNotFoundError:
        return None
    for line in output.splitlines():
        if line.startswith("n"):
            return line[1:]
    return None


def process_belongs_to_project(process: ProcessInfo) -> bool:
    if not any(marker in process.command for marker in EXECUTION_CAPABLE_MARKERS):
        return False
    if process.cwd is None:
        return False
    return Path(process.cwd).resolve() == PROJECT_ROOT.resolve()


def _inherited_owner() -> int | None:
    value = os.getenv("OPENCLAW_EXECUTION_LOCK_OWNER_PID")
    if not value:
        return None
    try:
        return int(value)
    except ValueError:
        return None


def _parent_mode9_owner(lock_path: Path) -> int | None:
    owner = read_lock(lock_path)
    if not owner or owner.get("process_name") != "mode9_autonomous_agent":
        return None
    try:
        owner_pid = int(owner.get("pid", -1))
    except (TypeError, ValueError):
        return None
    return owner_pid if owner_pid == os.getppid() and _pid_alive(owner_pid) else None


def _pid_alive(pid: int) -> bool:
    if pid <= 0:
        return False
    try:
        os.kill(pid, 0)
    except ProcessLookupError:
        return False
    except PermissionError:
        return True
    return True


def _current_command() -> Iterable[str]:
    try:
        with open(f"/proc/{os.getpid()}/cmdline", "rb") as handle:
            return [part.decode() for part in handle.read().split(b"\0") if part]
    except FileNotFoundError:
        return [Path(os.getenv("_", "python")).name]


def _utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()
