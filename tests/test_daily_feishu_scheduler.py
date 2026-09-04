import tempfile
import unittest
from datetime import date
from pathlib import Path

from scripts.daily_feishu_scheduler import (
    evaluate,
    mark_sent,
    parse_now,
    read_last_sent_date,
)


class DailyFeishuSchedulerTests(unittest.TestCase):
    def test_beijing_0900_triggers(self) -> None:
        decision = evaluate(parse_now("2026-03-29T09:00:00+08:00"), None)

        self.assertTrue(decision.due)
        self.assertEqual(decision.timezone, "Asia/Shanghai")
        self.assertEqual(decision.send_time, "09:00")

    def test_beijing_0859_does_not_trigger(self) -> None:
        decision = evaluate(parse_now("2026-03-29T08:59:00+08:00"), None)

        self.assertFalse(decision.due)
        self.assertIn("before scheduled Asia/Shanghai send time 09:00", decision.reason)

    def test_beijing_0901_backfills_if_not_sent(self) -> None:
        decision = evaluate(parse_now("2026-03-29T09:01:00+08:00"), None)

        self.assertTrue(decision.due)

    def test_same_beijing_date_does_not_repeat(self) -> None:
        decision = evaluate(parse_now("2026-03-29T09:01:00+08:00"), "2026-03-29")

        self.assertFalse(decision.due)
        self.assertIn("already sent", decision.reason)

    def test_germany_dst_does_not_affect_beijing_0900(self) -> None:
        spring_forward = evaluate(parse_now("2026-03-29T03:00:00+02:00"), None)
        winter_time = evaluate(parse_now("2026-10-25T02:00:00+01:00"), None)

        self.assertTrue(spring_forward.due)
        self.assertTrue(spring_forward.now.startswith("2026-03-29T09:00:00+08:00"))
        self.assertTrue(winter_time.due)
        self.assertTrue(winter_time.now.startswith("2026-10-25T09:00:00+08:00"))

    def test_last_sent_date_file_uses_asia_shanghai_date(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            mark_sent(root, date(2026, 9, 4))

            self.assertEqual(read_last_sent_date(root, date(2026, 9, 4)), "2026-09-04")
            self.assertEqual((root / ".runtime" / "daily_feishu_last_sent_date").read_text(encoding="utf-8").strip(), "2026-09-04")


if __name__ == "__main__":
    unittest.main()
