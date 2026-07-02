import os
from dataclasses import dataclass
from pathlib import Path
from typing import FrozenSet


def _read_channel_ids(value: str) -> FrozenSet[int]:
    ids = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError as exc:
            raise RuntimeError("DISCORD_CHANNEL_IDS must contain numeric IDs") from exc
    return frozenset(ids)


def _read_user_ids(value: str) -> FrozenSet[int]:
    ids = set()
    for item in value.split(","):
        item = item.strip()
        if not item:
            continue
        try:
            ids.add(int(item))
        except ValueError as exc:
            raise RuntimeError("HANDBOOK_ADMIN_USER_IDS must contain numeric IDs") from exc
    return frozenset(ids)


@dataclass(frozen=True)
class DiscordHandbookSettings:
    bot_token: str
    channel_ids: FrozenSet[int]
    admin_user_ids: FrozenSet[int]
    handbook_dir: Path
    summary_every_messages: int
    summary_interval_seconds: int
    summary_cooldown_seconds: int

    @classmethod
    def load(cls) -> "DiscordHandbookSettings":
        token = os.getenv("DISCORD_BOT_TOKEN", "").strip()
        if not token:
            raise RuntimeError("DISCORD_BOT_TOKEN is required")

        channel_ids = _read_channel_ids(os.getenv("DISCORD_CHANNEL_IDS", ""))
        if not channel_ids:
            raise RuntimeError("DISCORD_CHANNEL_IDS must contain at least one channel ID")

        return cls(
            bot_token=token,
            channel_ids=channel_ids,
            admin_user_ids=_read_user_ids(os.getenv("HANDBOOK_ADMIN_USER_IDS", "")),
            handbook_dir=Path(os.getenv("HANDBOOK_DIR", "handbook")),
            summary_every_messages=max(
                1,
                int(os.getenv("SUMMARY_EVERY_MESSAGES", "25")),
            ),
            summary_interval_seconds=max(
                60,
                int(os.getenv("SUMMARY_INTERVAL_SECONDS", "900")),
            ),
            summary_cooldown_seconds=max(
                0,
                int(os.getenv("SUMMARY_COOLDOWN_SECONDS", "60")),
            ),
        )
