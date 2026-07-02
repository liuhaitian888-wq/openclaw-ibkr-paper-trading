import re
import shutil
from os.path import relpath
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from typing import Iterable, List, Optional, Tuple


SECRET_PATTERNS = [
    re.compile(r"\bsk-[A-Za-z0-9_-]{16,}\b"),
    re.compile(r"\b(?:api[_ -]?key|token|secret)\s*[:=]\s*\S+", re.IGNORECASE),
]
MAX_SUMMARY_IMAGES = 80
IMAGE_GALLERY_EXTENSIONS = {".gif", ".jpeg", ".jpg", ".png", ".webp"}
IMAGE_GALLERY_START = "<!-- BEGIN HANDBOOK IMAGE GALLERY -->"
IMAGE_GALLERY_END = "<!-- END HANDBOOK IMAGE GALLERY -->"


@dataclass(frozen=True)
class AttachmentEntry:
    filename: str
    path: str
    url: str


@dataclass(frozen=True)
class MessageEntry:
    created_at: datetime
    author: str
    content: str
    attachments: Tuple[AttachmentEntry, ...] = ()


def safe_channel_name(name: str) -> str:
    cleaned = re.sub(r"[^A-Za-z0-9._-]+", "-", name.strip()).strip("-")
    return cleaned.lower() or "channel"


def redact_secrets(text: str) -> str:
    redacted = text
    for pattern in SECRET_PATTERNS:
        redacted = pattern.sub("[redacted]", redacted)
    return redacted


def build_summary(
    entries: Iterable[MessageEntry],
    link_base_dir: Optional[Path] = None,
) -> str:
    messages = list(entries)
    if not messages:
        return "No new messages to summarize.\n"

    participants = sorted({message.author for message in messages})
    decisions = _select_lines(
        messages,
        ("decided", "agree", "agreed", "approved", "confirmed", "final"),
    )
    actions = _select_lines(
        messages,
        ("todo", "to do", "action", "need to", "will", "please", "next"),
    )
    questions = [
        _format_message(message)
        for message in messages
        if "?" in message.content
    ][:8]

    notes = [_format_message(message) for message in messages[-8:]]
    attachments = [
        _format_attachment(message, attachment, link_base_dir)
        for message in messages
        for attachment in message.attachments
    ][-MAX_SUMMARY_IMAGES:]
    lines = [
        f"### Summary {messages[0].created_at:%Y-%m-%d %H:%M} - {messages[-1].created_at:%H:%M}",
        "",
        f"- Messages reviewed: {len(messages)}",
        f"- Participants: {', '.join(participants)}",
        "",
        "#### Decisions",
        *(_bullet_or_empty(decisions)),
        "",
        "#### Action Items",
        *(_bullet_or_empty(actions)),
        "",
        "#### Open Questions",
        *(_bullet_or_empty(questions)),
        "",
        "#### Images",
        *(_bullet_or_empty(attachments)),
        "",
        "#### Conversation Notes",
        *(_bullet_or_empty(notes)),
        "",
    ]
    return "\n".join(lines)


def append_summary(
    handbook_dir: Path,
    channel_name: str,
    entries: Iterable[MessageEntry],
    now: datetime,
) -> Path:
    channel_dir = handbook_dir / safe_channel_name(channel_name)
    channel_dir.mkdir(parents=True, exist_ok=True)
    target = channel_dir / f"{now:%Y-%m-%d}.md"
    if not target.exists():
        target.write_text(
            f"# {channel_name} Handbook Notes - {now:%Y-%m-%d}\n\n",
            encoding="utf-8",
        )
    with target.open("a", encoding="utf-8") as handle:
        handle.write(build_summary(entries, target.parent))
        handle.write("\n")
    return target


def append_image_gallery(
    handbook_dir: Path,
    channel_name: str,
    now: datetime,
    limit: int = 100,
) -> Path:
    channel_slug = safe_channel_name(channel_name)
    channel_dir = handbook_dir / channel_slug
    assets_dir = channel_dir / "assets"
    channel_dir.mkdir(parents=True, exist_ok=True)
    target = channel_dir / f"{now:%Y-%m-%d}.md"
    if not target.exists():
        target.write_text(
            f"# {channel_name} Handbook Notes - {now:%Y-%m-%d}\n\n",
            encoding="utf-8",
        )

    safe_limit = max(1, min(int(limit), 500))
    attachments_dir = handbook_dir / "_attachments" / channel_slug
    image_paths = []
    if attachments_dir.exists():
        image_paths = [
            path
            for path in attachments_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_GALLERY_EXTENSIONS
        ]
    if assets_dir.exists():
        image_paths.extend(
            path
            for path in assets_dir.rglob("*")
            if path.is_file() and path.suffix.lower() in IMAGE_GALLERY_EXTENSIONS
        )
    image_paths.sort(key=lambda path: path.stat().st_mtime, reverse=True)

    gallery_lines = [
        IMAGE_GALLERY_START,
        f"### Image Gallery {now:%Y-%m-%d %H:%M}",
        "",
    ]
    if not image_paths:
        gallery_lines.extend(["- No saved images found.", ""])
    else:
        for image_path in image_paths[:safe_limit]:
            display_path = _asset_display_path(image_path, assets_dir, attachments_dir)
            link_path = relpath(display_path, target.parent)
            gallery_lines.append(f"- ![{image_path.name}]({link_path})")
        gallery_lines.append("")
    gallery_lines.append(IMAGE_GALLERY_END)
    gallery_lines.append("")
    _replace_or_append_block(target, IMAGE_GALLERY_START, IMAGE_GALLERY_END, gallery_lines)
    return target


def _asset_display_path(
    image_path: Path,
    assets_dir: Path,
    legacy_attachments_dir: Path,
) -> Path:
    try:
        relative = image_path.relative_to(legacy_attachments_dir)
    except ValueError:
        return image_path

    target = assets_dir / relative
    target.parent.mkdir(parents=True, exist_ok=True)
    if not target.exists():
        shutil.copy2(image_path, target)
    return target


def _replace_or_append_block(
    target: Path,
    start_marker: str,
    end_marker: str,
    replacement_lines: List[str],
) -> None:
    replacement = "\n".join(replacement_lines)
    text = target.read_text(encoding="utf-8")
    start = text.find(start_marker)
    end = text.find(end_marker)
    if start >= 0 and end >= start:
        end += len(end_marker)
        target.write_text(text[:start] + replacement.rstrip() + text[end:], encoding="utf-8")
        return
    separator = "" if text.endswith("\n\n") else "\n"
    target.write_text(text + separator + replacement, encoding="utf-8")


def list_recent_summaries(handbook_dir: Path, limit: int = 5) -> List[Path]:
    if not handbook_dir.exists():
        return []
    safe_limit = max(1, min(int(limit), 20))
    files = [
        path
        for path in handbook_dir.glob("*/*.md")
        if path.is_file() and path.parent.name != "_attachments"
    ]
    files.sort(key=lambda path: path.stat().st_mtime, reverse=True)
    return files[:safe_limit]


def _select_lines(
    messages: List[MessageEntry],
    keywords: tuple[str, ...],
    limit: int = 8,
) -> List[str]:
    selected = []
    for message in messages:
        content = message.content.lower()
        if any(keyword in content for keyword in keywords):
            selected.append(_format_message(message))
        if len(selected) >= limit:
            break
    return selected


def _format_message(message: MessageEntry) -> str:
    content = redact_secrets(" ".join(message.content.split()))
    if not content and message.attachments:
        content = "[image-only message]"
    if len(content) > 240:
        content = content[:237].rstrip() + "..."
    return f"{message.author}: {content}"


def _format_attachment(
    message: MessageEntry,
    attachment: AttachmentEntry,
    link_base_dir: Optional[Path],
) -> str:
    filename = redact_secrets(attachment.filename)
    link_path = attachment.path
    if link_base_dir is not None:
        try:
            link_path = relpath(Path(attachment.path), link_base_dir)
        except ValueError:
            link_path = attachment.path
    return f"{message.author}: ![{filename}]({link_path})"


def _bullet_or_empty(items: List[str]) -> List[str]:
    if not items:
        return ["- None captured."]
    return [f"- {item}" for item in items]
