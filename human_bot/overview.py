"""
Purpose of this file / Muc dich cua file nay:
EN: ONE definition of "today's situation" (2026-11-02), shared by the admin home page ("Hôm nay") and
Telegram's /report footer, so the two can never show different numbers: how many posts wait for the rest
of the BUSINESS day (02:00 → 02:00 JST, the same day the daily caps use), how many of those are already
past due, how many are overdue / waiting for review, and how many attempts succeeded / failed today.
Read-only: nothing here writes anything.
VI: Mot dinh nghia duy nhat cho "tinh hinh hom nay" — trang chu admin va tin /report cua Telegram dung chung.
"""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone

from human_bot import daily_limits, db, schedule_store


@dataclass(frozen=True)
class QueueCounts:
    left_today: int  # pending posts through the end of the current business day (due ones included)
    due: int  # of those, the time has already passed but they are still pending (stuck)
    later: int  # pending after today


@dataclass(frozen=True)
class Today:
    queue: QueueCounts
    missed: int
    reviews: int
    ok: int
    failed: int
    day_start: datetime  # UTC instant the current business day began


def parse_iso(iso: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)  # like schedule_store: a naive time is UTC


def day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = daily_limits.business_day_start(now)
    return start, start + timedelta(days=1)


def split_pending(now: datetime | None = None, pending=None) -> tuple[list, int, int]:
    """(the pending tasks that fall in the current business day, soonest first; how many of those are already
    past due; how many wait for a later day). The ONE place that decides "today" for /schedule, /report and
    the admin home page. `pending` = schedule_store.list_pending() if the caller already has it."""
    now = now or datetime.now(timezone.utc)
    _start, end = day_bounds(now)
    today_tasks, due, later = [], 0, 0
    for task in (schedule_store.list_pending() if pending is None else pending):
        when = parse_iso(task.scheduled_at)
        if when is not None and when >= end:
            later += 1
            continue
        today_tasks.append(task)
        if when is None or when <= now:
            due += 1
    return today_tasks, due, later


def queue_counts(now: datetime | None = None, pending=None) -> QueueCounts:
    today_tasks, due, later = split_pending(now, pending)
    return QueueCounts(left_today=len(today_tasks), due=due, later=later)


def today(now: datetime | None = None, account_ids=None, pending=None) -> Today:
    """`account_ids` = the accounts whose attempts count (default: every registered account); `pending` = the
    pending list if the caller already read it."""
    now = now or datetime.now(timezone.utc)
    start, _end = day_bounds(now)
    if account_ids is None:
        from human_bot.config import get_all_accounts
        account_ids = list(get_all_accounts())
    ok = failed = 0
    for aid in account_ids:
        stats = db.summary_stats(aid, start.isoformat(), None)
        ok += stats["succeeded"]
        failed += stats["failed"]
    return Today(
        queue=queue_counts(now, pending), missed=len(schedule_store.list_missed()), reviews=len(schedule_store.list_needs_review()),
        ok=ok, failed=failed, day_start=start,
    )
