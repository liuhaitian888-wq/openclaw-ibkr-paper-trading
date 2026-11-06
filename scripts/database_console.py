"""On-demand collector/render CLI; never starts a service or connects to IBKR."""
import argparse
import json
import os
from pathlib import Path
import sys
sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from reporting.database_console import collect, render


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--root', type=Path)
    parser.add_argument('--input', type=Path, help='Render a previously collected JSON snapshot')
    parser.add_argument('--json', action='store_true')
    parser.add_argument('--output', type=Path)
    args = parser.parse_args()
    if bool(args.root) == bool(args.input):
        parser.error('Specify exactly one of --root or --input')
    data = json.loads(args.input.read_text()) if args.input else collect(args.root)
    result = json.dumps(data, ensure_ascii=False, indent=2) if args.json else render(data)
    if args.output:
        os.umask(0o077)
        args.output.parent.mkdir(parents=True, exist_ok=True)
        args.output.write_text(result)
    else:
        print(result)


if __name__ == '__main__':
    main()
