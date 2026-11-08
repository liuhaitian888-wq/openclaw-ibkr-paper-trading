"""Codex synchronous hook adapter. JSON in/out; unrelated workspaces are no-ops."""
import json
from pathlib import Path
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from engineering.task_completion import handle


def main():
    try:
        raw = sys.stdin.buffer.read(100_001)
        if len(raw) > 100_000:
            raise ValueError('Hook input exceeds metadata budget')
        event = json.loads(raw)
        root = Path(__file__).resolve().parents[1]
        registry = json.loads((root / '.der/maintenance/workspace.json').read_text())
        result = handle(event, registry, Path.home() / 'Documents/der',
                        Path.home() / '.local/state/openclaw/engineering/workspace-maintenance/task-completion')
    except Exception as exc:
        # A failed collector must not claim maintenance completion or loop the agent indefinitely.
        result = {'systemMessage': '任务收尾维护未执行：' + type(exc).__name__ + '。请在本次任务中核查，未标记为通过。'}
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
