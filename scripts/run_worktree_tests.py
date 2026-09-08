"""Full offline suite in a development worktree; production workspace uses smoke only."""
import os
from pathlib import Path
import subprocess
import sys
import tempfile


def main():
    root=Path(__file__).resolve().parents[1]
    if not (root/'.git').is_file():
        raise SystemExit('Full suite belongs in a linked development worktree; use check_gateway_health.command in production')
    with tempfile.TemporaryDirectory(prefix='openclaw-tests-') as temporary:
        state=Path(temporary);sandbox=state/'sandbox';sandbox.mkdir()
        (sandbox/'sitecustomize.py').write_text('''import socket
_original_connect=socket.socket.connect
_original_connect_ex=socket.socket.connect_ex
def _deny(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6):
        raise PermissionError("Offline suite: real network connections are disabled")
    return _original_connect(self,address)
def _deny_ex(self,address):
    if self.family in (socket.AF_INET,socket.AF_INET6):
        raise PermissionError("Offline suite: real network connections are disabled")
    return _original_connect_ex(self,address)
socket.socket.connect=_deny
socket.socket.connect_ex=_deny_ex
''')
        env=os.environ.copy();env.update(OPENCLAW_STATE_DIR=str(state),AUDIT_DB=str(state/'trading_audit.sqlite3'),
            OPENCLAW_API_KEY='offline-test-placeholder',PYTHONPATH=str(sandbox)+os.pathsep+str(root),
            LIVE_TRADING_ENABLED='false',ALLOW_PAPER_TRANSMIT='false')
        return subprocess.run([sys.executable,'-m','unittest','discover','-s','tests'],cwd=root,env=env).returncode

if __name__=='__main__':raise SystemExit(main())
