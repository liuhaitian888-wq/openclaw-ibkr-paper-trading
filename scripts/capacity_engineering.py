"""Host operator handoff; list is passive, claim/finish never execute a model."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None,''): sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reporting.capacity_engineering import read, claim, finish


def main():
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--state-root',type=Path,required=True)
    sub=parser.add_subparsers(dest='action',required=True)
    sub.add_parser('list')
    p=sub.add_parser('claim');p.add_argument('--task',required=True);p.add_argument('--sha256',required=True);p.add_argument('--owner',required=True)
    p=sub.add_parser('finish');p.add_argument('--task',required=True);p.add_argument('--owner',required=True)
    p.add_argument('--outcome',choices=('DIAGNOSED','UNKNOWN'),required=True);p.add_argument('--summary',required=True)
    args=parser.parse_args();root=args.state_root.absolute()
    if args.action=='list': result=read(root)
    elif args.action=='claim': result=claim(root,args.task,args.sha256,args.owner)
    else: result=finish(root,args.task,args.owner,args.outcome,args.summary)
    print(json.dumps(result,ensure_ascii=False));return 0


if __name__=='__main__': raise SystemExit(main())
