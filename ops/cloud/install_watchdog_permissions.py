"""One-time reviewed admin deployment, never a timer/helper execution target.

Run the reviewed bytes via system /usr/bin/python3 -I -S with expected hashes
provided by the operator. Does not enable the timer or restart the Gateway.
"""
import argparse
import configparser
from datetime import datetime,timezone
import hashlib
import os
from pathlib import Path
import re
import subprocess

BASE=Path('/opt/openclaw/app/ops/cloud')
UNIT=Path('/etc/systemd/system/ibkr-gateway-watchdog.service')
RULE=Path('/etc/polkit-1/rules.d/00-openclaw-paper-gateway.rules')


def protected(path):
    for part in [*reversed(path.parents),path]:
        st=part.lstat()
        if part.is_symlink() or st.st_uid!=0 or st.st_mode & 0o022:
            raise PermissionError('Root-owned non-writable path required: '+str(part))


def verified_bytes(path,digest):
    if not re.fullmatch('[a-f0-9]{64}',digest):raise ValueError('Reviewed SHA256 required')
    data=path.read_bytes()
    if hashlib.sha256(data).hexdigest()!=digest:raise PermissionError('Source differs from reviewed bytes')
    return data


def install(data,path):
    protected(path.parent)
    if path.exists() or path.is_symlink():protected(path)
    temp=path.with_name('.'+path.name+'.new')
    # Exclusive creation refuses any pre-existing file/symlink; never follow it as root.
    with temp.open('xb') as f:
        f.write(data);f.flush();os.fsync(f.fileno())
    temp.chmod(0o644);temp.replace(path)
    protected(path)


def gateway_boundary():
    p=subprocess.run(['/usr/bin/systemctl','show','ibkr-gateway.service','-p','User','-p','Group','-p','FragmentPath','-p','DropInPaths','-p','NoNewPrivileges'],capture_output=True,text=True,timeout=5,check=True)
    props=dict(x.split('=',1) for x in p.stdout.splitlines() if '=' in x)
    if props.get('User')!='ibkr' or props.get('Group')!='ibkr' or props.get('NoNewPrivileges')!='yes':
        raise PermissionError('Target service must remain an unprivileged ibkr owner')
    for name in [props['FragmentPath'],*props.get('DropInPaths','').split()]:
        p=Path(name);protected(p)
        for line in p.read_text().splitlines():
            key,sep,value=line.strip().partition('=')
            if sep and key.startswith('Exec') and value.strip():
                # No ancillary hooks or privileged prefixes, even in root-owned drop-ins.
                if key!='ExecStart' or re.match(r'[-:@!+|]*[!+]',value.strip()):
                    raise PermissionError('Privileged/ancillary target hooks require separate review')
    return props


def main():
    if os.getuid()!=0 or os.geteuid()!=0:raise PermissionError('Administrative deployment only')
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--unit-sha256',required=True);parser.add_argument('--rule-sha256',required=True)
    args=parser.parse_args()
    unit=verified_bytes(BASE/'systemd/ibkr-gateway-watchdog.service',args.unit_sha256)
    rule=verified_bytes(BASE/'polkit/00-openclaw-paper-gateway.rules',args.rule_sha256)
    cfg=configparser.ConfigParser(interpolation=None,strict=False);cfg.read_string(unit.decode());s=cfg['Service']
    if s.get('User')!='ibkr' or s.get('Group')!='ibkr' or s.get('NoNewPrivileges')!='yes' or s.get('CapabilityBoundingSet')!='':
        raise PermissionError('Watchdog must be an unprivileged service')
    gateway_boundary();protected(UNIT);protected(RULE.parent)
    # Backups live only below protected root-owned directories, never ibkr-writable paths.
    backup=Path('/root/.local/state/openclaw/watchdog-security')
    backup.mkdir(parents=True,exist_ok=True,mode=0o700);protected(backup)
    backup=backup/datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ');backup.mkdir(mode=0o700)
    for path in (UNIT,RULE):
        if path.exists():protected(path);(backup/path.name).write_bytes(path.read_bytes())
    install(unit,UNIT);install(rule,RULE)
    subprocess.run(['/usr/bin/systemctl','daemon-reload'],check=True,timeout=10)
    subprocess.run(['/usr/bin/systemd-analyze','verify',str(UNIT)],capture_output=True,check=True,timeout=10)
    gateway_boundary()
    print('Unprivileged unit and protected exact-unit policy installed; timer remains disabled pending authorization probes.')

if __name__=='__main__':main()
