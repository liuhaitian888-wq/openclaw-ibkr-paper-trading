"""Discord bot that turns selected channel discussions into handbook notes."""

import asyncio
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import DefaultDict, Dict, List

import discord

from discord_handbook.config import DiscordHandbookSettings
from discord_handbook.handbook import (
    AttachmentEntry,
    MessageEntry,
    append_image_gallery,
    append_summary,
    list_recent_summaries,
    safe_channel_name,
)


IMAGE_EXTENSIONS = {".png", ".jpg", ".jpeg", ".webp", ".gif"}
MAX_BACKFILL_MESSAGES = 500


class HandbookBot(discord.Client):
    def __init__(self, settings: DiscordHandbookSettings) -> None:
        intents = discord.Intents.default()
        intents.guild_messages = True
        intents.message_content = True
        super().__init__(intents=intents)
        self._settings = settings
        self._buffers: DefaultDict[int, List[MessageEntry]] = defaultdict(list)
        self._last_summary_at: Dict[int, datetime] = {}
        self._flush_task: asyncio.Task[None] | None = None

    async def setup_hook(self) -> None:
        self._flush_task = asyncio.create_task(self._periodic_flush())

    async def close(self) -> None:
        if self._flush_task:
            self._flush_task.cancel()
        await super().close()

    async def on_ready(self) -> None:
        print(f"Discord handbook bot connected as {self.user}")
        print(
            "Watching channel IDs: "
            + ", ".join(str(channel_id) for channel_id in sorted(self._settings.channel_ids))
        )
        if self._settings.admin_user_ids:
            print(
                "Handbook command admins: "
                + ", ".join(str(user_id) for user_id in sorted(self._settings.admin_user_ids))
            )
        else:
            print("Warning: HANDBOOK_ADMIN_USER_IDS is empty; any channel member can summarize.")
        if not self.guilds:
            print("Warning: bot is not in any Discord server yet.")
        for guild in self.guilds:
            print(f"Connected server: {guild.name} ({guild.id})")
        for channel_id in sorted(self._settings.channel_ids):
            channel = self.get_channel(channel_id)
            if channel is None:
                print(f"Warning: configured channel {channel_id} is not visible to the bot.")
            else:
                print(f"Watching channel: #{channel.name} ({channel.id})")
        await self.change_presence(
            activity=discord.Activity(
                type=discord.ActivityType.watching,
                name="handbook notes",
            )
        )

    async def on_message(self, message: discord.Message) -> None:
        if message.author.bot:
            return

        command = message.content.strip().lower()
        if command == "!handbook help":
            await message.channel.send(
                "`!handbook status` checks whether I can see this channel.\n"
                "`!handbook summarize` writes the current message buffer to the handbook.\n"
                "`!handbook backfill 100` reads recent history, including image attachments.\n"
                "`!handbook images 100` writes saved images into today's handbook.\n"
                "`!handbook recent` lists recently updated handbook files."
            )
            return

        if command == "!handbook status":
            watched = message.channel.id in self._settings.channel_ids
            buffer_size = len(self._buffers[message.channel.id])
            admin_configured = bool(self._settings.admin_user_ids)
            can_summarize = self._can_summarize(message.author.id)
            await message.channel.send(
                "Handbook bot is online.\n"
                f"Channel ID: `{message.channel.id}`\n"
                f"Your user ID: `{message.author.id}`\n"
                f"Configured for this channel: `{watched}`\n"
                f"Admin allowlist enabled: `{admin_configured}`\n"
                f"You can summarize: `{can_summarize}`\n"
                f"Buffered messages: `{buffer_size}`"
            )
            return

        if message.channel.id not in self._settings.channel_ids:
            return

        if command == "!handbook recent":
            files = list_recent_summaries(self._settings.handbook_dir)
            if not files:
                await message.channel.send("No handbook files have been written yet.")
                return
            lines = [
                f"- `{path.relative_to(self._settings.handbook_dir)}`"
                for path in files
            ]
            await message.channel.send("Recent handbook files:\n" + "\n".join(lines))
            return

        if command.startswith("!handbook images"):
            if not self._can_summarize(message.author.id):
                await message.channel.send(
                    "You are not allowed to write handbook image galleries."
                )
                return
            limit = self._parse_image_limit(command)
            path = append_image_gallery(
                self._settings.handbook_dir,
                message.channel.name,
                datetime.now(),
                limit=limit,
            )
            await message.channel.send(
                f"Image gallery updated: `{path}` with up to `{limit}` saved images."
            )
            return

        if command.startswith("!handbook backfill"):
            if not self._can_summarize(message.author.id):
                await message.channel.send(
                    "You are not allowed to run handbook backfills."
                )
                return
            limit = self._parse_backfill_limit(command)
            await message.channel.send(f"Backfilling up to `{limit}` recent messages...")
            entries = await self._history_entries(message.channel, limit)
            if not entries:
                await message.channel.send("No readable history messages found.")
                return
            path = append_summary(
                self._settings.handbook_dir,
                message.channel.name,
                entries,
                datetime.now(),
            )
            await message.channel.send(
                f"Backfill complete: `{len(entries)}` messages written to `{path}`"
            )
            return

        if command == "!handbook summarize":
            if not self._can_summarize(message.author.id):
                await message.channel.send(
                    "You are not allowed to run handbook summaries. "
                    "Ask the bot owner to add your Discord user ID to "
                    "`HANDBOOK_ADMIN_USER_IDS`."
                )
                return
            cooldown = self._cooldown_remaining(message.channel.id)
            if cooldown > 0:
                await message.channel.send(
                    f"Summary cooldown is active. Try again in `{cooldown}` seconds."
                )
                return
            path = self._flush_channel(message.channel)
            if path is None:
                await message.channel.send("No new messages to summarize yet.")
            else:
                self._last_summary_at[message.channel.id] = datetime.now(timezone.utc)
                await message.channel.send(f"Handbook updated: `{path}`")
            return

        entry = await self._message_entry(message)
        if entry is None:
            return

        self._buffers[message.channel.id].append(entry)
        if len(self._buffers[message.channel.id]) >= self._settings.summary_every_messages:
            self._flush_channel(message.channel)

    async def _periodic_flush(self) -> None:
        while True:
            await asyncio.sleep(self._settings.summary_interval_seconds)
            for channel_id in list(self._buffers):
                channel = self.get_channel(channel_id)
                if channel is not None:
                    self._flush_channel(channel)

    def _flush_channel(self, channel: discord.abc.GuildChannel) -> str | None:
        entries = self._buffers.pop(channel.id, [])
        if not entries:
            return None
        path = append_summary(
            self._settings.handbook_dir,
            channel.name,
            entries,
            datetime.now(),
        )
        return str(path)

    def _can_summarize(self, user_id: int) -> bool:
        if not self._settings.admin_user_ids:
            return True
        return user_id in self._settings.admin_user_ids

    def _cooldown_remaining(self, channel_id: int) -> int:
        if self._settings.summary_cooldown_seconds <= 0:
            return 0
        last_summary_at = self._last_summary_at.get(channel_id)
        if last_summary_at is None:
            return 0
        elapsed = (datetime.now(timezone.utc) - last_summary_at).total_seconds()
        return max(0, int(self._settings.summary_cooldown_seconds - elapsed))

    async def _history_entries(
        self,
        channel: discord.abc.Messageable,
        limit: int,
    ) -> List[MessageEntry]:
        entries = []
        async for history_message in channel.history(limit=limit, oldest_first=True):
            if history_message.author.bot:
                continue
            entry = await self._message_entry(history_message)
            if entry is not None:
                entries.append(entry)
        return entries

    async def _message_entry(self, message: discord.Message) -> MessageEntry | None:
        attachments = await self._save_image_attachments(message)
        content = message.content.strip()
        if not content and not attachments:
            return None
        return MessageEntry(
            created_at=message.created_at.replace(tzinfo=None),
            author=message.author.display_name,
            content=content,
            attachments=tuple(attachments),
        )

    async def _save_image_attachments(
        self,
        message: discord.Message,
    ) -> List[AttachmentEntry]:
        entries = []
        for attachment in message.attachments:
            if not self._is_image_attachment(attachment):
                continue
            target = self._attachment_path(message, attachment.filename)
            target.parent.mkdir(parents=True, exist_ok=True)
            try:
                await attachment.save(target)
            except Exception as exc:
                print(f"Could not save Discord attachment {attachment.url}: {exc}")
                continue
            entries.append(
                AttachmentEntry(
                    filename=attachment.filename,
                    path=str(target),
                    url=attachment.url,
                )
            )
        return entries

    def _attachment_path(self, message: discord.Message, filename: str) -> Path:
        channel_name = getattr(message.channel, "name", str(message.channel.id))
        channel_dir = safe_channel_name(channel_name)
        suffix = Path(filename).suffix.lower()
        if suffix not in IMAGE_EXTENSIONS:
            suffix = ".img"
        safe_name = safe_channel_name(Path(filename).stem)
        unique_name = f"{message.id}-{safe_name}{suffix}"
        return (
            self._settings.handbook_dir
            / channel_dir
            / "assets"
            / f"{message.created_at:%Y-%m-%d}"
            / unique_name
        )

    @staticmethod
    def _is_image_attachment(attachment: discord.Attachment) -> bool:
        content_type = attachment.content_type or ""
        suffix = Path(attachment.filename).suffix.lower()
        return content_type.startswith("image/") or suffix in IMAGE_EXTENSIONS

    @staticmethod
    def _parse_backfill_limit(command: str) -> int:
        parts = command.split()
        if len(parts) < 3:
            return 100
        try:
            requested = int(parts[2])
        except ValueError:
            return 100
        return max(1, min(requested, MAX_BACKFILL_MESSAGES))

    @staticmethod
    def _parse_image_limit(command: str) -> int:
        parts = command.split()
        if len(parts) < 3:
            return 100
        try:
            requested = int(parts[2])
        except ValueError:
            return 100
        return max(1, min(requested, 500))


def main() -> None:
    settings = DiscordHandbookSettings.load()
    try:
        HandbookBot(settings).run(settings.bot_token)
    except discord.PrivilegedIntentsRequired as exc:
        raise SystemExit(
            "Discord refused the bot because a privileged intent is not enabled. "
            "Open Discord Developer Portal -> your app -> Bot, enable "
            "'Message Content Intent', save changes, then start the bot again."
        ) from exc


if __name__ == "__main__":
    main()
