"""
Purpose of this file / Muc dich cua file nay:
EN: Telegram alerts about tasks landing in "Task quá hạn" and jobs landing
in "Chờ duyệt" (2026-10-13, Telegram Vòng 1), plus the small on-disk
state that lets an alert survive the very outage it reports.

Why state on disk: when the internet is down, Telegram is down too — a
"mất mạng" alert sent at that moment is simply lost (telegram_notify
swallows send failures). So the network gate in data_sync.fire_due_tasks()
only RECORDS the outage here (record_outage()); the human_bot/service.py
fire loop calls flush_pending() on every tick, which sends ONE combined
message the first time the internet is back, then clears the record. A
service restart in the middle of an outage keeps the record (JSON file).

Everything here is best-effort: a Telegram problem must never break the
scheduler that calls us.
VI: Bao qua Telegram khi task vao "Task qua han" / job vao "Cho duyet".
Mat mang thi Telegram cung khong gui duoc, nen chi GHI LAI luc mat mang
va gui 1 tin gom sau khi co mang lai.
"""
from __future__ import annotations

import asyncio
import json
import logging
import os
import tempfile
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from human_bot import network_check, telegram_notify

logger = logging.getLogger("human_bot.telegram_alerts")

STATE_PATH = Path(__file__).resolve().parent.parent / "data_sync_cache" / "_telegram_state.json"

_JST = timedelta(hours=9)
_MAX_LISTED = 5  # lines shown in a message; the rest is "và X task khác"
_MAX_STORED_ITEMS = 20  # per outage record — enough to list 5, bounded on disk
_MAX_NOTICES = 10


# Strong references to fire-and-forget tasks — the event loop only keeps
# WEAK references, so an un-referenced task can be garbage-collected before
# it finishes (code review 2026-10-13).
_background: set[asyncio.Task] = set()


def spawn(coro) -> asyncio.Task:
    """Runs `coro` in the background without delaying the caller; failures
    are logged, never raised into the caller."""
    async def _guarded():
        try:
            await coro
        except Exception:  # noqa: BLE001 — a notification must never break the caller's job
            logger.exception("telegram_alerts: background task failed")

    task = asyncio.ensure_future(_guarded())
    _background.add(task)
    task.add_done_callback(_background.discard)
    return task


def _load() -> dict[str, Any]:
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, ValueError):
        return {}


def _save(state: dict[str, Any]) -> None:
    """Best-effort and never raises — callers include data_sync's
    fire_due_tasks(), which must not fail because a state file could not
    be written (full disk, bad permissions)."""
    tmp = None
    try:
        STATE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=STATE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(state, f, ensure_ascii=False)
        os.replace(tmp, STATE_PATH)
    except OSError:
        logger.exception("telegram_alerts: could not save state")
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass


def get_state() -> dict[str, Any]:
    """Whole state file, for the other Telegram pieces that share it
    (e.g. the daily-summary "already sent" marker)."""
    return _load()


def update_state(**fields: Any) -> None:
    state = _load()
    state.update(fields)
    _save(state)


def jst_hhmm(iso: str | None) -> str:
    if not iso:
        return "?"
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return "?"
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return (dt + _JST).strftime("%H:%M %d/%m")


def _task_item(task) -> dict[str, str]:
    return {"account_id": task.account_id, "action": task.action, "scheduled_at": task.scheduled_at}


def _lines(items: list[dict[str, str]], total: int) -> str:
    lines = [
        f"• {jst_hhmm(i.get('scheduled_at'))} · {i.get('account_id')} · {i.get('action')}"
        for i in items[:_MAX_LISTED]
    ]
    if total > len(lines):
        lines.append(f"…và {total - len(lines)} bài khác")
    return "\n".join(lines)


def record_outage(tasks: list, now: datetime | None = None) -> None:
    """Called by data_sync.fire_due_tasks() right after it moved `tasks`
    to "Task quá hạn" because there was no internet. Merges into an outage
    already being recorded (one outage = one message)."""
    if not tasks:
        return
    now = now or datetime.now(timezone.utc)
    state = _load()
    outage = state.get("outage") or {"since": now.isoformat(), "count": 0, "items": []}
    outage["count"] = int(outage.get("count", 0)) + len(tasks)
    outage["items"] = (list(outage.get("items", [])) + [_task_item(t) for t in tasks])[:_MAX_STORED_ITEMS]
    state["outage"] = outage
    _save(state)


def format_outage_text(outage: dict[str, Any], ended_at: datetime) -> str:
    # "since" is when the FIRST affected task was parked, not when the
    # internet actually dropped (nobody probes in between) — worded so it
    # doesn't claim to be the exact outage window.
    count = int(outage.get("count", 0))
    return (
        f"🌐 Đã có mạng lại (lúc {jst_hhmm(ended_at.isoformat())}). Mất mạng được phát hiện từ "
        f"{jst_hhmm(outage.get('since'))} (có thể đã mất từ trước đó).\n"
        f"{count} bài đến giờ trong lúc đó đã chuyển sang mục \"Quá hạn\" của Lịch đăng (cần lên lịch lại):\n"
        f"{_lines(outage.get('items', []), count)}"
    )


def queue_notice(text: str) -> None:
    """Keeps a message that could not be delivered, to retry from
    flush_pending()."""
    state = _load()
    notices = list(state.get("notices", []))
    notices.append(text)
    state["notices"] = notices[-_MAX_NOTICES:]
    _save(state)


async def flush_pending() -> bool:
    """Sends whatever alert could not go out earlier. Cheap no-op (one
    small file read) when nothing is pending. Returns True if it sent
    something.

    The state file is RE-READ after every await (network/Telegram calls
    can take many seconds, and the daily-summary marker or a freshly
    queued notice may have been written meanwhile) and only the keys this
    function owns are changed — never write back a stale snapshot."""
    state = _load()
    outage = state.get("outage")
    notices = list(state.get("notices", []))
    if not outage and not notices:
        return False
    if not telegram_notify.is_configured():
        # Muted/unconfigured: nothing can be delivered, don't keep retrying forever.
        fresh = _load()
        fresh.pop("outage", None)
        fresh["notices"] = []
        _save(fresh)
        return False
    if not await network_check.is_online():
        return False
    sent = False
    if outage:
        text = format_outage_text(outage, datetime.now(timezone.utc))
        if not await telegram_notify.send_message_checked(text, silent=False):
            return sent
        fresh = _load()
        # record_outage() may have merged MORE tasks into the record while
        # the send was in flight — only drop what this message covered,
        # keep the rest (as a new outage) for the next flush.
        current = fresh.get("outage") or {}
        extra = int(current.get("count", 0)) - int(outage.get("count", 0))
        if extra > 0:
            fresh["outage"] = {
                "since": datetime.now(timezone.utc).isoformat(),
                "count": extra,
                "items": list(current.get("items", []))[len(outage.get("items", [])):],
            }
        else:
            fresh.pop("outage", None)
        _save(fresh)
        sent = True
    for notice in notices:
        if not await telegram_notify.send_message_checked(notice, silent=False):
            break
        fresh = _load()
        remaining = list(fresh.get("notices", []))
        if notice in remaining:
            remaining.remove(notice)
        fresh["notices"] = remaining
        _save(fresh)
        sent = True
    return sent


async def notify_startup_sweep(items: list[dict[str, str]]) -> None:
    """One combined message after the startup sweep moved overdue tasks to
    "Task quá hạn". Kept for retry if Telegram can't be reached yet."""
    if not items:
        return
    text = (
        f"⚠️ Service vừa khởi động lại — {len(items)} bài đã quá giờ đăng trong lúc tắt, "
        f"đã chuyển sang mục \"Quá hạn\" của Lịch đăng (cần lên lịch lại):\n"
        f"{_lines(items, len(items))}"
    )
    if not await telegram_notify.send_message_checked(text, silent=False):
        queue_notice(text)


async def notify_needs_review(count: int) -> None:
    """One combined message per sync cycle for jobs that went to "Chờ
    duyệt" (confidence below the threshold)."""
    if count <= 0:
        return
    await telegram_notify.send_message(
        f"🔍 {count} job mới đang chờ duyệt (độ tin cậy thấp) — vào /admin/schedule, tab \"Chờ duyệt\".",
        silent=False,
    )
