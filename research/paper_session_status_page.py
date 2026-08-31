import argparse
import html
import json
import sys
from pathlib import Path
from typing import Any, Mapping

PROJECT_ROOT = Path(__file__).resolve().parent.parent
if str(PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(PROJECT_ROOT))


def render_status_page(runbook: Mapping[str, Any]) -> str:
    status = str(runbook.get("status", "unknown"))
    status_class = _status_class(status)
    commands = runbook.get("commands", [])
    blockers = runbook.get("blockers", [])
    steps = runbook.get("operator_steps", [])
    artifacts = runbook.get("artifacts", {})
    return "\n".join(
        [
            "<!doctype html>",
            '<html lang="en">',
            "<head>",
            '  <meta charset="utf-8">',
            '  <meta name="viewport" content="width=device-width, initial-scale=1">',
            "  <title>Paper Trial Status</title>",
            "  <style>",
            _css(),
            "  </style>",
            "</head>",
            "<body>",
            "  <main>",
            "    <section class=\"topline\">",
            "      <div>",
            "        <h1>Paper Trial Status</h1>",
            f"        <p>{html.escape(str(runbook.get('summary', 'No summary available.')))}</p>",
            "      </div>",
            f"      <span class=\"status {status_class}\">{html.escape(status)}</span>",
            "    </section>",
            "    <section class=\"grid two\">",
            _state_panel(runbook),
            _list_panel("Blockers", blockers, empty="None detected by the latest reports."),
            "    </section>",
            "    <section>",
            _ordered_panel("Operator Steps", steps),
            "    </section>",
            "    <section>",
            _commands_panel(commands),
            "    </section>",
            "    <section>",
            _artifacts_panel(artifacts),
            "    </section>",
            "  </main>",
            "</body>",
            "</html>",
        ]
    )


def write_status_page(runbook: Mapping[str, Any], output: Path) -> Path:
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(render_status_page(runbook), encoding="utf-8")
    return output


def main() -> int:
    parser = argparse.ArgumentParser(description="Build a static HTML status page from the paper session runbook JSON.")
    parser.add_argument("--runbook-json", type=Path, default=PROJECT_ROOT / "reports" / "paper_session_runbook.json")
    parser.add_argument("--output", type=Path, default=PROJECT_ROOT / "reports" / "paper_session_status.html")
    args = parser.parse_args()

    runbook = _load_json_object(args.runbook_json)
    write_status_page(runbook, args.output)
    print(str(args.output))
    return 0


def _state_panel(runbook: Mapping[str, Any]) -> str:
    rows = [
        ("Generated", str(runbook.get("created_at", "unknown"))),
        ("Environment", str(runbook.get("environment_status", "unknown"))),
        ("Guarded Session", str(runbook.get("guarded_session_status", "unknown"))),
    ]
    body = "\n".join(
        f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
        for label, value in rows
    )
    return f"<article><h2>Current State</h2><table>{body}</table></article>"


def _list_panel(title: str, values: object, *, empty: str) -> str:
    items = values if isinstance(values, list) else []
    if not items:
        content = f"<p>{html.escape(empty)}</p>"
    else:
        content = "<ul>" + "".join(f"<li>{html.escape(str(item))}</li>" for item in items) + "</ul>"
    return f"<article><h2>{html.escape(title)}</h2>{content}</article>"


def _ordered_panel(title: str, values: object) -> str:
    items = values if isinstance(values, list) else []
    content = "<ol>" + "".join(f"<li>{html.escape(str(item))}</li>" for item in items) + "</ol>"
    return f"<article><h2>{html.escape(title)}</h2>{content}</article>"


def _commands_panel(commands: object) -> str:
    items = commands if isinstance(commands, list) else []
    parts = ["<article><h2>Commands</h2>"]
    for command in items:
        if not isinstance(command, Mapping):
            continue
        parts.extend(
            [
                "<div class=\"command\">",
                f"<h3>{html.escape(str(command.get('name', 'Command')))}</h3>",
                f"<p>{html.escape(str(command.get('purpose', '')))}</p>",
                f"<pre>{html.escape(str(command.get('command', '')))}</pre>",
                "</div>",
            ]
        )
    parts.append("</article>")
    return "\n".join(parts)


def _artifacts_panel(artifacts: object) -> str:
    values = artifacts if isinstance(artifacts, Mapping) else {}
    rows = "\n".join(
        f"<tr><th>{html.escape(str(name))}</th><td>{html.escape(str(path))}</td></tr>"
        for name, path in sorted(values.items())
    )
    return f"<article><h2>Artifacts</h2><table>{rows}</table></article>"


def _status_class(status: str) -> str:
    if "blocked" in status:
        return "blocked"
    if "ready" in status:
        return "ready"
    if "submitted" in status:
        return "submitted"
    return "neutral"


def _css() -> str:
    return """
    :root { color-scheme: light; font-family: Inter, ui-sans-serif, system-ui, -apple-system, BlinkMacSystemFont, "Segoe UI", sans-serif; }
    body { margin: 0; background: #f5f7f9; color: #17202a; }
    main { width: min(1120px, calc(100% - 32px)); margin: 0 auto; padding: 32px 0 48px; }
    h1, h2, h3, p { margin-top: 0; }
    h1 { font-size: 32px; line-height: 1.15; margin-bottom: 10px; }
    h2 { font-size: 18px; margin-bottom: 14px; }
    h3 { font-size: 15px; margin-bottom: 6px; }
    p, li, td, th { font-size: 14px; line-height: 1.5; }
    section { margin-top: 16px; }
    article { background: #ffffff; border: 1px solid #dce3ea; border-radius: 8px; padding: 18px; box-shadow: 0 1px 2px rgba(16, 24, 40, 0.04); }
    .topline { display: flex; align-items: flex-start; justify-content: space-between; gap: 18px; background: #ffffff; border: 1px solid #dce3ea; border-radius: 8px; padding: 22px; }
    .topline p { max-width: 760px; margin-bottom: 0; color: #526070; }
    .grid.two { display: grid; grid-template-columns: minmax(0, 1fr) minmax(0, 1fr); gap: 16px; }
    .status { flex: 0 0 auto; border-radius: 999px; padding: 8px 12px; font-size: 13px; font-weight: 700; border: 1px solid transparent; }
    .status.blocked { background: #fff1f0; color: #9f1d1d; border-color: #f1b8b8; }
    .status.ready { background: #eefaf1; color: #1e6b35; border-color: #bfe5ca; }
    .status.submitted { background: #eef5ff; color: #244f92; border-color: #bfd3f5; }
    .status.neutral { background: #f2f4f7; color: #475467; border-color: #d0d5dd; }
    table { border-collapse: collapse; width: 100%; }
    th, td { text-align: left; vertical-align: top; padding: 9px 0; border-top: 1px solid #edf1f5; }
    th { width: 180px; color: #526070; font-weight: 700; }
    ul, ol { margin: 0; padding-left: 22px; }
    li + li { margin-top: 7px; }
    .command { border-top: 1px solid #edf1f5; padding-top: 14px; margin-top: 14px; }
    pre { margin: 8px 0 0; white-space: pre-wrap; overflow-wrap: anywhere; background: #101828; color: #f8fafc; border-radius: 6px; padding: 12px; font-size: 13px; line-height: 1.45; }
    @media (max-width: 720px) { .topline { display: block; } .status { display: inline-block; margin-top: 16px; } .grid.two { grid-template-columns: 1fr; } main { width: min(100% - 20px, 1120px); padding-top: 16px; } }
    """


def _load_json_object(path: Path) -> Mapping[str, Any]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(payload, Mapping):
        raise ValueError(f"{path} must contain a JSON object")
    return payload


if __name__ == "__main__":
    raise SystemExit(main())
