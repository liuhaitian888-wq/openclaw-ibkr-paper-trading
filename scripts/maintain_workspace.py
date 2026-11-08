"""Explicit engineering refresh; never owns trading, product services or source cleanup."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from engineering.workspace_maintenance import collect_project,refresh


def main():
    parser=argparse.ArgumentParser()
    parser.add_argument('--workspace-root',type=Path,default=Path.home()/'Documents/der')
    parser.add_argument('--registry',type=Path,default=Path(__file__).resolve().parents[1]/'.der/maintenance/workspace.json')
    parser.add_argument('--output',type=Path,default=Path.home()/'.local/state/openclaw/engineering/workspace-maintenance/current')
    mode=parser.add_mutually_exclusive_group();mode.add_argument('--check',action='store_true');mode.add_argument('--refresh',action='store_true')
    args=parser.parse_args();registry=json.loads(args.registry.read_text())
    if args.refresh:result=refresh(registry,args.workspace_root,args.output)
    else:result={'projects':{p['id']:collect_project(args.workspace_root,p) for p in registry['projects']}}
    print(json.dumps({'output':str(args.output) if args.refresh else None,'changed_projects':result.get('changed_projects'),
        'projects':[{k:item[k] for k in ('id','name','git','source_fingerprint','context','verification','next_task')} for item in result['projects'].values()]},ensure_ascii=False,indent=2))


if __name__=='__main__':main()
