"""One approved Paper Gateway owner; delegates login/restarts to pinned IBAutomater."""
from pathlib import Path
from contextlib import contextmanager
import hashlib
import json
import os
import signal
import subprocess
import sys
import time
sys.path.insert(0,str(Path(__file__).resolve().parents[2]))
from ops.cloud.monitoring_guard import monitoring_service
from trading.production_diagnostics import context


def validate_deployment(root, actual, *, home=None):
    home=Path(home) if home else Path.home()
    manifest=json.loads((root/'runtime/gateway-automater-deployment.json').read_text())
    if (manifest.get('approved') is not True or manifest.get('environment')!='PAPER'
            or manifest.get('grants_trading_permission') is not False
            or any(not actual.get(k) or manifest.get(k)!=actual.get(k) for k in ('commit','branch','code_root','state_root'))):
        raise PermissionError('Approved Gateway automater deployment required')
    credentials=home/'.config/openclaw/ibautomater-credentials.json'
    if credentials.is_symlink() or credentials.stat().st_mode & 0o077:
        raise PermissionError('Private mode0600 credentials required')
    cfg=json.loads(credentials.read_text())
    if (cfg.get('trading_mode')!='paper' or not all(isinstance(cfg.get(k),str) and cfg[k] and
            not any(ch in cfg[k] for ch in '\r\n\x00') for k in ('username','password'))):
        raise PermissionError('Valid private Paper configuration required')
    release=Path(manifest['release']).resolve()
    if not release.is_relative_to(Path('/opt/openclaw/ibautomater/releases')):
        raise PermissionError('Approved release root required')
    if set(manifest.get('hashes',{})) != {p.name for p in release.iterdir() if p.is_file()}:
        raise PermissionError('Release inventory differs')
    for name,digest in manifest['hashes'].items():
        if (release/name).is_symlink() or Path(name).name!=name or hashlib.sha256((release/name).read_bytes()).hexdigest()!=digest:
            raise PermissionError('Release content differs')
    return manifest,credentials


def run_owned(command,env,*,stop_event=None):
    import threading
    stopped=stop_event or threading.Event()
    previous={}
    if stop_event is None:
        for sig in (signal.SIGTERM,signal.SIGINT):previous[sig]=signal.signal(sig,lambda *_:stopped.set())
    process=None
    try:
        process=subprocess.Popen(command,env=env)
        while process.poll() is None and not stopped.wait(.5):pass
        return process.returncode or 0
    finally:
        if process is not None and process.poll() is None:
            process.terminate()
            try:process.wait(timeout=30)
            except subprocess.TimeoutExpired:
                process.kill();process.wait(timeout=5)
        for sig,handler in previous.items():signal.signal(sig,handler)


def main():
    os.umask(0o077)
    root=Path.home()/'.local/state/openclaw'
    manifest,credentials=validate_deployment(root,context())
    private=root/'runtime/ibautomater'
    private.mkdir(mode=0o700,exist_ok=True)
    if private.is_symlink() or private.stat().st_mode & 0o077:raise PermissionError('Private agent directory required')
    env=os.environ.copy();env.update(OPENCLAW_AUTOMATER_CREDENTIALS=str(credentials),
        OPENCLAW_AUTOMATER_PRIVATE=str(private),OPENCLAW_GATEWAY_INSTALL=str(Path.home()/'Jts'),
        DISPLAY=':99',XAUTHORITY='/run/ibkr-gui/Xauthority')
    with monitoring_service('gateway-automater',root):
        print('GATEWAY_AUTOMATER_PAPER_START_NO_ORDER_AUTHORITY',flush=True)
        return run_owned(['/usr/bin/dotnet',str(Path(manifest['release'])/'OpenClaw.IBAutomater.dll')],env)

if __name__=='__main__':raise SystemExit(main())
