"""Manual finite public-artifact archive. Default action is a dry-run plan."""
import argparse
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reporting.storage_archive import Archive, SSHSource


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--destination', type=Path, required=True)
    parser.add_argument('--ssh-target')
    parser.add_argument('--key', type=Path)
    parser.add_argument('--known-hosts', type=Path)
    parser.add_argument('--path', action='append', default=[])
    parser.add_argument('--begin', action='store_true')
    parser.add_argument('--copy-batch', metavar='JOB_ID')
    parser.add_argument('--verify-restore', metavar='JOB_ID')
    parser.add_argument('--cleanup-dry-run', metavar='JOB_ID')
    parser.add_argument('--batch-bytes', type=int, default=16*1024**2)
    args = parser.parse_args()
    if sum(bool(value) for value in (args.copy_batch, args.verify_restore, args.cleanup_dry_run, args.path)) != 1:
        raise ValueError('One finite action required')
    archive = Archive(args.destination)
    if args.verify_restore:
        result = archive.verify_restore(args.verify_restore)
    elif args.cleanup_dry_run:
        result = archive.cleanup_dry_run(args.cleanup_dry_run)
    else:
        if not all((args.ssh_target, args.key, args.known_hosts)):
            raise ValueError('Existing SSH identity and known-host verification required')
        source = SSHSource(args.ssh_target, args.key, args.known_hosts)
        result = archive.batch(source, args.copy_batch, max_bytes=args.batch_bytes) if args.copy_batch else archive.plan(source, args.path, execute=args.begin)
    if args.cleanup_dry_run:
        print(json.dumps(result,ensure_ascii=False));return
    # Manifest is local/private; stdout remains bounded metadata only.
    print(json.dumps({k: result[k] for k in ('id','state','logical_bytes','source_deletion_allowed','restored','mode','approved_reclaim_bytes','deletion_api') if k in result}, ensure_ascii=False))


if __name__ == '__main__':
    main()
