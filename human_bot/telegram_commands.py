"""
Purpose of this file / Muc dich cua file nay:
EN: The "/" commands of the Telegram bot (2026-10-13, Telegram Vòng 1) and
the daily summary text. Pure "build the reply text" functions — no network,
no sending — so they are easy to test; human_bot/service.py's
_telegram_listen_loop()/_telegram_daily_summary_loop() do the sending.

"Hôm nay" everywhere means the BUSINESS day (02:00 → 02:00 JST,
human_bot/daily_limits.py's business_day_start()), the same definition the
daily posting caps use, so these numbers line up with "how many slots are
left today". /suckhoe is built by service.py (it needs human_bot/admin.py's
health text, which this module deliberately doesn't import).

Read-only: no command here changes any data.
VI: Cac lenh "/" cua bot Telegram + noi dung tom tat hang ngay. Chi dung
chuoi tra loi, khong gui gi; "hom nay" = ngay nghiep vu 02:00 -> 02:00 JST.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from human_bot import daily_limits, db, schedule_store
from human_bot.config import get_all_accounts
from human_bot.telegram_alerts import jst_hhmm

# (command, description) — Telegram only allows lowercase ASCII letters,
# digits and "_" in the command itself, so no Vietnamese diacritics there.
COMMANDS: list[tuple[str, str]] = [
    ("lich", "Task sắp đăng hôm nay"),
    ("quahan", "Task quá hạn đang chờ xử lý"),
    ("baocao", "Báo cáo hôm nay"),
    ("suckhoe", "Sức khoẻ tài khoản"),
    ("help", "Danh sách lệnh"),
]
_COMMAND_NAMES = {c for c, _ in COMMANDS} | {"start"}
_MAX_LINES = 10  # list lines per reply (Telegram caps a message at 4096 chars)
_JST = timedelta(hours=9)
_CMD_RE = re.compile(r"^/([A-Za-z0-9_]+)(?:@(\S+))?(?:\s|$)")


def parse_command(text: str | None) -> str | None:
    """"/lich", "/lich@my_bot", "/lich arg" → "lich"; anything else
    (plain text, or "/" followed by garbage) → None."""
    m = _CMD_RE.match((text or "").strip())
    return m.group(1).lower() if m else None


def command_target(text: str | None) -> str | None:
    """The "@bot_name" a command is addressed to ("/lich@my_bot" →
    "my_bot"), None when it carries no suffix (the normal private-chat
    case). Lets the caller ignore commands meant for another bot."""
    m = _CMD_RE.match((text or "").strip())
    return m.group(2) if m and m.group(2) else None


def is_known_command(name: str | None) -> bool:
    return name in _COMMAND_NAMES


def help_text() -> str:
    lines = ["Các lệnh bot hiểu:"] + [f"/{c} — {d}" for c, d in COMMANDS]
    return "\n".join(lines)


def _day_bounds(now: datetime) -> tuple[datetime, datetime]:
    start = daily_limits.business_day_start(now)
    return start, start + timedelta(days=1)


def _parse(iso: str) -> datetime | None:
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def _target_label(task) -> str:
    """Group name when /admin/groups knows it, else the tail of the URL."""
    target = getattr(task, "target_url", None)
    if not target:
        return "(tường cá nhân)"
    try:
        from human_bot.agent import resolve_group_name  # local import — avoid import cycle at module load
        name = resolve_group_name(task.account_id, target)
    except Exception:  # noqa: BLE001 — purely cosmetic
        name = None
    return name or target.rstrip("/").rsplit("/", 1)[-1]


def schedule_text(now: datetime | None = None) -> str:
    """Pending tasks through the end of the current business day. A task
    whose time already passed but is still pending (auto-fire off, rate
    limited, or the service was down) is flagged ⏰ and counted apart from
    the ones still upcoming — otherwise "sắp đăng" would hide that
    something is stuck."""
    now = now or datetime.now(timezone.utc)
    _start, end = _day_bounds(now)
    today, later, stuck = [], 0, 0
    for t in schedule_store.list_pending():
        when = _parse(t.scheduled_at)
        if when is not None and when >= end:
            later += 1
            continue
        today.append(t)
        if when is None or when <= now:
            stuck += 1
    if not today:
        return f"📅 Hôm nay không còn task nào chờ đăng.\nCác ngày sau: {later} task."

    def line(t) -> str:
        when = _parse(t.scheduled_at)
        mark = "⏰ " if (when is None or when <= now) else ""
        return f"• {mark}{jst_hhmm(t.scheduled_at)} · {t.account_id} · {t.action} · {_target_label(t)}"

    lines = [line(t) for t in today[:_MAX_LINES]]
    if len(today) > _MAX_LINES:
        lines.append(f"…và {len(today) - _MAX_LINES} task khác")
    head = f"📅 Task chờ đăng hôm nay ({len(today)})"
    if stuck:
        head += f" — ⏰ {stuck} task đã đến giờ nhưng chưa chạy"
    return head + ":\n" + "\n".join(lines) + f"\nCác ngày sau: {later} task."


def _missed_reason_tag(task_id: str) -> str:
    reason = schedule_store.get_missed_reason(task_id) or ""
    if reason.startswith("Mất mạng"):
        return "mất mạng"
    if "khởi động" in reason:
        return "service tắt"
    return "khác"


def missed_text(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    missed = schedule_store.list_missed()
    if not missed:
        return "✅ Không có task nào quá hạn."
    lines = [
        f"• {jst_hhmm(t.scheduled_at)} · {t.account_id} · {t.action} · "
        f"{_missed_reason_tag(t.task_id)} · quá {schedule_store.missed_overdue_days(t, now)} ngày"
        for t in missed[:_MAX_LINES]
    ]
    if len(missed) > _MAX_LINES:
        lines.append(f"…và {len(missed) - _MAX_LINES} task khác")
    return (
        f"⚠️ {len(missed)} task quá hạn đang chờ xử lý (vào /admin/schedule → tab \"Task quá hạn\"):\n"
        + "\n".join(lines)
    )


def _activity_block(since: datetime, until: datetime | None) -> str:
    since_iso = since.isoformat()
    until_iso = until.isoformat() if until else None
    lines = []
    total_ok = total_fail = 0
    for aid in sorted(get_all_accounts()):
        stats = db.summary_stats(aid, since_iso, until_iso)
        if not stats["total"]:
            lines.append(f"{aid}: chưa có lượt nào")
            continue
        total_ok += stats["succeeded"]
        total_fail += stats["failed"]
        by_action: dict[str, list[int]] = {}
        for row in db.action_type_counts(aid, since_iso, until_iso):
            ok_fail = by_action.setdefault(row["action"], [0, 0])
            ok_fail[0 if row["success"] else 1] += row["total"]
        detail = ", ".join(f"{a} {ok}✅/{bad}❌" for a, (ok, bad) in by_action.items())
        lines.append(f"{aid}: ✅ {stats['succeeded']} · ❌ {stats['failed']}" + (f" ({detail})" if detail else ""))
    head = f"Tổng: ✅ {total_ok} · ❌ {total_fail}"
    return head + ("\n" + "\n".join(lines) if lines else "")


def _queue_footer(now: datetime) -> str:
    """The queue AS OF NOW (not as of the day being reported) — labeled
    "Hiện" for that reason. Counts the same way /lich does, so the two
    never disagree: tasks overdue but still pending are included and
    called out."""
    _start, end = _day_bounds(now)
    left, stuck = 0, 0
    for t in schedule_store.list_pending():
        when = _parse(t.scheduled_at)
        if when is not None and when >= end:
            continue
        left += 1
        if when is None or when <= now:
            stuck += 1
    pending = f"{left}" + (f" (⏰ {stuck} đã quá giờ chưa chạy)" if stuck else "")
    return (
        f"Hiện — chờ đăng hôm nay: {pending} · Quá hạn: {len(schedule_store.list_missed())} · "
        f"Chờ duyệt: {len(schedule_store.list_needs_review())}"
    )


def report_text(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    start, _end = _day_bounds(now)
    return f"📊 Báo cáo hôm nay (từ 02:00 JST):\n{_activity_block(start, None)}\n{_queue_footer(now)}"


def daily_summary_text(now: datetime | None = None, anchor: datetime | None = None) -> str:
    """Summary of the business day that just ended (the one before the
    current one), meant to be sent at ~06:00 JST. `anchor` (the scheduled
    send time) decides WHICH day that is — a catch-up send after midnight
    must still summarize the day it was scheduled for, not a later one;
    `now` only feeds the queue footer."""
    now = now or datetime.now(timezone.utc)
    today_start, _end = _day_bounds(anchor or now)
    day_start = today_start - timedelta(days=1)
    label = (day_start + _JST).strftime("%d/%m")
    return f"🌅 Tóm tắt ngày {label} (02:00 → 02:00 JST):\n{_activity_block(day_start, today_start)}\n{_queue_footer(now)}"
