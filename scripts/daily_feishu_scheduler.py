"""Asia/Shanghai daily scheduler gate for the Paper Trading Feishu report."""

from __future__ import annotations

import argparse
import json
from dataclasses import dataclass
from datetime import date, datetime, time, timedelta, timezone
from pathlib import Path
from zoneinfo import ZoneInfo


PROJECT_ROOT = Path(__file__).resolve().parent.parent
SCHEDULER_TIMEZONE = ZoneInfo("Asia/Shanghai")
SEND_TIME = time(9, 0)
LAST_SENT_FILE = Path(".runtime") / "daily_feishu_last_sent_date"


@dataclass(frozen=True)
class SchedulerDecision:
    timezone: str
    send_time: str
    now: str
    beijing_date: str
    last_sent_date: str | None
    due: bool
    reason: str
    next_scheduled_send: str


def parse_now(value: str | None) -> datetime:
    if not value:
        return datetime.now(tz=SCHEDULER_TIMEZONE)
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=SCHEDULER_TIMEZONE)
    return parsed.astimezone(SCHEDULER_TIMEZONE)


def legacy_marker_path(root: Path, beijing_day: date) -> Path:
    return root / ".runtime" / f"daily_feishu_sent_{beijing_day:%Y%m%d}"


def read_last_sent_date(root: Path, beijing_day: date) -> str | None:
    last_sent = root / LAST_SENT_FILE
    if last_sent.exists():
        value = last_sent.read_text(encoding="utf-8").strip()
        if value:
            return value
    if legacy_marker_path(root, beijing_day).exists():
        return beijing_day.isoformat()
    return None


def next_send_time(now_bj: datetime, last_sent_date: str | None) -> datetime:
    today_send = datetime.combine(now_bj.date(), SEND_TIME, tzinfo=SCHEDULER_TIMEZONE)
    if now_bj < today_send:
        return today_send
    if last_sent_date == now_bj.date().isoformat():
        return today_send + timedelta(days=1)
    return today_send


def evaluate(now_bj: datetime, last_sent_date: str | None) -> SchedulerDecision:
    today = now_bj.date().isoformat()
    send_at = datetime.combine(now_bj.date(), SEND_TIME, tzinfo=SCHEDULER_TIMEZONE)
    if last_sent_date == today:
        due = False
        reason = f"already sent for Asia/Shanghai date {today}"
    elif now_bj < send_at:
        due = False
        reason = f"before scheduled Asia/Shanghai send time {SEND_TIME:%H:%M}"
    else:
        due = True
        reason = f"due for Asia/Shanghai date {today}"
    return SchedulerDecision(
        timezone="Asia/Shanghai",
        send_time=SEND_TIME.strftime("%H:%M"),
        now=now_bj.isoformat(),
        beijing_date=today,
        last_sent_date=last_sent_date,
        due=due,
        reason=reason,
        next_scheduled_send=next_send_time(now_bj, last_sent_date).isoformat(),
    )


def mark_sent(root: Path, beijing_day: date) -> None:
    runtime = root / ".runtime"
    runtime.mkdir(parents=True, exist_ok=True)
    (root / LAST_SENT_FILE).write_text(beijing_day.isoformat() + "\n", encoding="utf-8")
    legacy_marker_path(root, beijing_day).touch()


def decision_payload(decision: SchedulerDecision) -> dict[str, object]:
    return {
        "timezone": decision.timezone,
        "send_time": decision.send_time,
        "now": decision.now,
        "beijing_date": decision.beijing_date,
        "last_sent_date": decision.last_sent_date,
        "due": decision.due,
        "reason": decision.reason,
        "next_scheduled_send": decision.next_scheduled_send,
    }


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command", choices=("status", "due", "mark-sent"))
    parser.add_argument("--project-root", type=Path, default=PROJECT_ROOT)
    parser.add_argument("--now", default="")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    now_bj = parse_now(args.now)
    last_sent = read_last_sent_date(args.project_root, now_bj.date())
    decision = evaluate(now_bj, last_sent)
    if args.command == "mark-sent":
        mark_sent(args.project_root, now_bj.date())
        print(json.dumps({"marked_sent_date": now_bj.date().isoformat()}, ensure_ascii=False))
        return 0
    print(json.dumps(decision_payload(decision), ensure_ascii=False))
    if args.command == "due":
        return 0 if decision.due else 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
