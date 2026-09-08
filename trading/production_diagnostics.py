"""Low-overhead local observation. No broker requests, sends, kills, or fd cleanup."""
import collections
import json
import logging
from logging.handlers import RotatingFileHandler
import os
from pathlib import Path
import resource
import subprocess
import threading
import time
from datetime import datetime, timezone

from trading.production_paths import CODE_ROOT, STATE_ROOT, LOG_ROOT, REPORT_ROOT


def command(args):
    try:
        p = subprocess.run(args, capture_output=True, text=True, timeout=5)
        return p.stdout if p.returncode == 0 else ''
    except (OSError, subprocess.TimeoutExpired):
        return ''


def process_snapshot(pid=None):
    pid = pid or os.getpid()
    details = command(['ps', '-p', str(pid), '-o', 'ppid=,etime=,rss=,%cpu=,stat='])
    fields = details.split()
    fds = []; current = None
    for line in command(['lsof', '-nP', '-a', '-p', str(pid), '-Fftn']).splitlines():
        if line.startswith('f'):
            current = {'fd': line[1:]}; fds.append(current)
        elif current is not None and line[:1] in ('t', 'n'):
            current[line[0]] = line[1:]
    counts = collections.Counter()
    cwd = None
    for fd in fds:
        if fd['fd'] == 'cwd': cwd = fd.get('n')
        if not fd['fd'].isdigit(): continue
        path = fd.get('n', ''); kind = fd.get('t', 'UNKNOWN')
        category = ('sqlite' if '.sqlite' in path else 'socket' if kind in ('IPv4','IPv6','unix')
                    else 'pipe' if kind in ('PIPE','FIFO') else 'watcher' if kind=='KQUEUE'
                    else 'logfile' if '.log' in path else 'file' if kind=='REG' else kind.lower())
        counts[category] += 1
    limit = resource.getrlimit(resource.RLIMIT_NOFILE)[0] if pid == os.getpid() else None
    count = sum(counts.values()) if fds else None
    warning = int(limit*.70) if limit and limit > 0 else None
    critical = int(limit*.85) if limit and limit > 0 else None
    level = ('UNKNOWN' if count is None else 'CRITICAL' if critical and count >= critical
             else 'WARNING' if warning and count >= warning else 'OK')
    children = command(['pgrep', '-P', str(pid)]).splitlines()
    threads = command(['ps','-M','-p',str(pid)]).splitlines()[1:]
    return {'timestamp': datetime.now(timezone.utc).isoformat(), 'pid':pid,
            'ppid':int(fields[0]) if fields else None, 'uptime':fields[1] if len(fields)>1 else None,
            'rss_kb':int(fields[2]) if len(fields)>2 else None,'cpu_percent':fields[3] if len(fields)>3 else None,
            'process_state':fields[4] if len(fields)>4 else None, 'cwd':cwd,
            'open_fd_count':count,'fd_types':dict(counts),'fd_soft_limit':limit,
            'fd_warning':warning,'fd_critical':critical,'fd_status':level,
            'thread_count':len(threads) or None,'child_process_count':len(children),
            'sqlite_handle_count':counts.get('sqlite',0),'sqlite_pool_connections':'UNKNOWN: no pool instrumentation'}


def process_inventory():
    rows=[]
    for line in command(['ps','-axo','pid=,ppid=,lstart=,command=']).splitlines():
        parts=line.split(None,7)
        if len(parts)<8: continue
        cmd=parts[7]
        if not any(x in cmd for x in ('run_autonomous_', 'api_service.py','report_production_scheduler.py',
                                      'send_daily_', 'send_feishu_report.py','run_pool_strategy_module.py')):continue
        # Exclude the inspection shell's embedded command text.
        if ' -c ' in cmd or 'rg ' in cmd:continue
        pid=int(parts[0]); cwd=None
        for l in command(['lsof','-a','-p',str(pid),'-d','cwd','-Fn']).splitlines():
            if l.startswith('n'):cwd=l[1:]
        rows.append({'pid':pid,'ppid':int(parts[1]),'started':' '.join(parts[2:7]),'cwd':cwd,'command':cmd,
                     'legacy_worktree':bool(cwd and '/worktrees/' in cwd),'deleted_cwd':bool(cwd and '(deleted)' in cwd)})
    return rows


def directory_size(root):
    # Explicit maintenance inspection only; never recurse over archive each sampling tick.
    total=0
    for directory, dirs, files in os.walk(root, followlinks=False):
        for name in files:
            try:total += (Path(directory)/name).lstat().st_size
            except OSError:pass
    return total


def read_json(path):
    try:return json.loads(Path(path).read_text())
    except (OSError,ValueError):return {}


def context():
    return {'commit':command(['git','-C',str(CODE_ROOT),'rev-parse','HEAD']).strip(),
            'branch':command(['git','-C',str(CODE_ROOT),'branch','--show-current']).strip(),
            'code_root':str(CODE_ROOT),'state_root':str(STATE_ROOT)}


class ResourceMonitor:
    """One owned worker per service. Samples once/minute; logs bounded to 20 MiB."""
    def __init__(self, service, interval=60):
        self.service=service;self.interval=max(10,interval);self.stop_event=threading.Event();self.thread=None
        self.logger=logging.getLogger('production.resources.'+service);self.logger.propagate=False
        self.history=[];self.handler=None
    def __enter__(self):
        LOG_ROOT.mkdir(parents=True,exist_ok=True)
        self.handler=RotatingFileHandler(LOG_ROOT/(self.service+'-resources.log'),maxBytes=5*1024*1024,backupCount=3)
        self.logger.addHandler(self.handler);self.logger.setLevel(logging.INFO)
        self.logger.info(json.dumps({'startup':context(),'cwd':os.getcwd()}))
        self.thread=threading.Thread(target=self.run,name='resource-monitor-'+self.service,daemon=True);self.thread.start()
        return self
    def run(self):
        while not self.stop_event.is_set():
            sample=process_snapshot();count=sample['open_fd_count']
            if count is not None:
                self.history=(self.history+[count])[-5:]
                sample['fd_monotonic_growth']=len(self.history)==5 and all(a<b for a,b in zip(self.history,self.history[1:]))
                if sample['fd_monotonic_growth'] and sample['fd_status']=='OK':sample['fd_status']='WARNING'
            self.logger.info(json.dumps(sample))
            if self.stop_event.wait(self.interval):break
    def __exit__(self,*exc):
        self.stop_event.set()
        if self.thread:self.thread.join(timeout=20)
        # Never close a handler while a live sampling worker still owns it.
        if self.thread and self.thread.is_alive():raise RuntimeError('Resource monitor has not stopped')
        if self.handler:self.logger.removeHandler(self.handler);self.handler.close()
