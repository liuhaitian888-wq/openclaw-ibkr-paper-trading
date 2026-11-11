"""Sole publisher must bind this before optional release artifact creation."""
import argparse
import json
from pathlib import Path
import sys
if __package__ in (None,''):sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from reporting.storage_policy import engineering_decision,publication_decision


def main():
    p=argparse.ArgumentParser(description=__doc__);p.add_argument('--state-root',type=Path,required=True)
    p.add_argument('--kind',choices=('engineering','publication'),required=True)
    p.add_argument('--input-bytes',type=int,default=0);p.add_argument('--source-bundle-bytes',type=int,default=0);p.add_argument('--extra-bytes',type=int,default=0)
    a=p.parse_args();root=a.state_root.absolute()
    try:
        value=engineering_decision(root) if a.kind=='engineering' else publication_decision(root,
            input_bytes=a.input_bytes,source_bundle_bytes=a.source_bundle_bytes,extra_bytes=a.extra_bytes)
    except (OSError,ValueError,TimeoutError):value={'allowed':False,'state':'DEFERRED_CAPACITY_UNKNOWN'}
    print(json.dumps(value,ensure_ascii=False));return 0 if value['allowed'] else 2


if __name__=='__main__':raise SystemExit(main())
