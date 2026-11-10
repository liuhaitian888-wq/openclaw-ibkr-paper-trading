"""Manually check an existing backup export; no network, restore, or cleanup."""
import argparse
import json
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reporting.backup_verification import verify_archive, BackupVerificationError


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument('archive')
    parser.add_argument('--output-root',required=True,help='Existing private directory; each check creates a new child')
    parser.add_argument('--expected-archive-sha256')
    args=parser.parse_args(argv)
    try:
        result=verify_archive(args.archive,args.output_root,expected_archive_sha256=args.expected_archive_sha256)
    except BackupVerificationError as exc:
        print(json.dumps(dict(state='FAILED',error_code=exc.code,workdir=exc.workdir,grants_restore_permission=False)))
        return 2
    print(json.dumps(result,ensure_ascii=False,indent=2))
    return 0


if __name__=='__main__':raise SystemExit(main())
