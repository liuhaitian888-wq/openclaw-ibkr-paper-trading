import tempfile
import unittest
from datetime import datetime
from pathlib import Path

from discord_handbook.handbook import (
    AttachmentEntry,
    MAX_SUMMARY_IMAGES,
    MessageEntry,
    append_image_gallery,
    append_summary,
    build_summary,
    list_recent_summaries,
    redact_secrets,
    safe_channel_name,
)


class DiscordHandbookTests(unittest.TestCase):
    def test_redacts_secret_like_values(self) -> None:
        text = "api_key=abc123 token: super-secret sk-abcdefghijklmnopqrstuvwxyz"

        redacted = redact_secrets(text)

        self.assertNotIn("abc123", redacted)
        self.assertNotIn("super-secret", redacted)
        self.assertNotIn("sk-abcdefghijklmnopqrstuvwxyz", redacted)

    def test_build_summary_extracts_actions_and_questions(self) -> None:
        entries = [
            MessageEntry(datetime(2026, 6, 27, 9, 0), "Brother Wang", "I agree this is final."),
            MessageEntry(datetime(2026, 6, 27, 9, 1), "Nick", "I will upload the screenshots."),
            MessageEntry(datetime(2026, 6, 27, 9, 2), "Nick", "Should the bot update the handbook?"),
        ]

        summary = build_summary(entries)

        self.assertIn("Brother Wang: I agree this is final.", summary)
        self.assertIn("Nick: I will upload the screenshots.", summary)
        self.assertIn("Nick: Should the bot update the handbook?", summary)

    def test_append_summary_writes_channel_daily_file(self) -> None:
        entries = [
            MessageEntry(datetime(2026, 6, 27, 9, 0), "Nick", "Need to document setup."),
        ]
        with tempfile.TemporaryDirectory() as directory:
            path = append_summary(
                Path(directory),
                "Trading Admin Chat",
                entries,
                datetime(2026, 6, 27, 10, 0),
            )

            self.assertEqual(path.name, "2026-06-27.md")
            self.assertEqual(path.parent.name, "trading-admin-chat")
            self.assertIn("Need to document setup", path.read_text(encoding="utf-8"))

    def test_safe_channel_name_has_fallback(self) -> None:
        self.assertEqual(safe_channel_name(" $$ "), "channel")

    def test_build_summary_includes_image_attachments(self) -> None:
        entries = [
            MessageEntry(
                datetime(2026, 6, 27, 9, 0),
                "Nick",
                "",
                (
                    AttachmentEntry(
                        filename="setup.png",
                        path="handbook/_attachments/channel/2026-06-27/1-setup.png",
                        url="https://cdn.discordapp.com/example/setup.png",
                    ),
                ),
            )
        ]

        summary = build_summary(entries, Path("handbook/channel"))

        self.assertIn("#### Images", summary)
        self.assertIn("![setup.png](../_attachments/channel/2026-06-27/1-setup.png)", summary)
        self.assertIn("[image-only message]", summary)

    def test_build_summary_keeps_latest_images_when_many_are_backfilled(self) -> None:
        entries = [
            MessageEntry(
                datetime(2026, 6, 27, 9, minute % 60),
                "Nick",
                "",
                (
                    AttachmentEntry(
                        filename=f"chart-{minute:03d}.png",
                        path=f"handbook/_attachments/channel/2026-06-27/{minute}-chart.png",
                        url=f"https://cdn.discordapp.com/example/{minute}.png",
                    ),
                ),
            )
            for minute in range(MAX_SUMMARY_IMAGES + 5)
        ]

        summary = build_summary(entries, Path("handbook/channel"))

        self.assertNotIn("chart-000.png", summary)
        self.assertIn(f"chart-{MAX_SUMMARY_IMAGES + 4:03d}.png", summary)

    def test_list_recent_summaries_ignores_attachment_directory(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            older = root / "trading-chat" / "2026-06-26.md"
            newer = root / "trading-chat" / "2026-06-27.md"
            attachment_note = root / "_attachments" / "2026-06-27.md"
            older.parent.mkdir(parents=True)
            attachment_note.parent.mkdir(parents=True)
            older.write_text("old", encoding="utf-8")
            newer.write_text("new", encoding="utf-8")
            attachment_note.write_text("not a summary", encoding="utf-8")

            files = list_recent_summaries(root, limit=10)

            self.assertIn(newer, files)
            self.assertIn(older, files)
            self.assertNotIn(attachment_note, files)

    def test_append_image_gallery_writes_saved_images(self) -> None:
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            image_dir = root / "_attachments" / "trading-chat" / "2026-06-27"
            image_dir.mkdir(parents=True)
            first = image_dir / "1-chart.png"
            second = image_dir / "2-chart.png"
            first.write_bytes(b"fake image 1")
            second.write_bytes(b"fake image 2")

            path = append_image_gallery(
                root,
                "Trading Chat",
                datetime(2026, 6, 27, 10, 0),
                limit=10,
            )

            text = path.read_text(encoding="utf-8")
            self.assertIn("### Image Gallery 2026-06-27 10:00", text)
            self.assertIn("![1-chart.png](assets/2026-06-27/1-chart.png)", text)
            self.assertIn("![2-chart.png](assets/2026-06-27/2-chart.png)", text)
            self.assertTrue((root / "trading-chat" / "assets" / "2026-06-27" / "1-chart.png").exists())
            self.assertTrue((root / "trading-chat" / "assets" / "2026-06-27" / "2-chart.png").exists())

            append_image_gallery(
                root,
                "Trading Chat",
                datetime(2026, 6, 27, 11, 0),
                limit=1,
            )

            updated_text = path.read_text(encoding="utf-8")
            self.assertNotIn("### Image Gallery 2026-06-27 10:00", updated_text)
            self.assertIn("### Image Gallery 2026-06-27 11:00", updated_text)
            self.assertEqual(updated_text.count("### Image Gallery"), 1)


if __name__ == "__main__":
    unittest.main()
