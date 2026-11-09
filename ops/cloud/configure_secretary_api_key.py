"""Interactive root TTY credential install. Never accepts key in arguments/stdout."""
import getpass
import os
from pathlib import Path
import re
import sys

TARGET=Path('/etc/openclaw/credentials/secretary-openai.key')

def main():
    if os.geteuid()!=0 or not sys.stdin.isatty():raise SystemExit('Run as root in an interactive SSH terminal')
    if TARGET.exists() or TARGET.is_symlink():raise SystemExit('Credential already exists; retain it and request explicit rotation')
    for parent in (Path('/etc/openclaw'),TARGET.parent):
        if parent.is_symlink():raise SystemExit('Credential directory must not be a symlink')
        parent.mkdir(mode=0o700,exist_ok=True)
        meta=parent.stat()
        if meta.st_uid!=0 or meta.st_mode&0o022:raise SystemExit('Root-owned protected directory required')
    os.umask(0o077)
    value=getpass.getpass('Paste OpenAI API key (hidden; not logged): ')
    if not re.fullmatch(r'sk-[A-Za-z0-9_-]{20,500}',value):raise SystemExit('Invalid key format; nothing saved')
    fd=os.open(TARGET,os.O_WRONLY|os.O_CREAT|os.O_EXCL|os.O_NOFOLLOW,0o600)
    with os.fdopen(fd,'w') as f:f.write(value+'\n');f.flush();os.fsync(f.fileno())
    print('Credential saved root-only. No model call, service start or policy activation performed.')

if __name__=='__main__':main()
