"""
Purpose of this file / Muc dich cua file nay:
EN: The "/" commands of the Telegram bot (2026-10-13, Telegram Vòng 1) and
the daily summary text. Pure "build the reply text" functions — no network,
no sending — so they are easy to test; human_bot/service.py's
_telegram_listen_loop()/_telegram_daily_summary_loop() do the sending.

"Hôm nay" everywhere means the BUSINESS day (02:00 → 02:00 JST,
human_bot/daily_limits.py's business_day_start()), the same definition the
daily posting caps use, so these numbers line up with "how many slots are
left today". /health is built by service.py (it needs human_bot/admin.py's
health text, which this module deliberately doesn't import).

Read-only: no command here changes any data.
VI: Cac lenh "/" cua bot Telegram + noi dung tom tat hang ngay. Chi dung
chuoi tra loi, khong gui gi; "hom nay" = ngay nghiep vu 02:00 -> 02:00 JST.
"""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

from human_bot import daily_limits, db, overview, schedule_store
from human_bot.config import get_all_accounts
from human_bot.telegram_alerts import jst_hhmm

# (command, description) — Telegram only allows lowercase ASCII letters,
# digits and "_" in the command itself, so no Vietnamese diacritics there.
# One line per command: (name, short description for the bot's "/" menu, longer description for /help, /help group).
# The menu list (COMMANDS) and the /help text are both built from this, so they cannot drift apart.
_SPEC: list[tuple[str, str, str, str]] = [
    ("schedule", "Bài sắp đăng hôm nay", "các bài sắp đăng hôm nay", "view"),
    ("report", "Báo cáo hôm nay", "hôm nay đăng được bao nhiêu bài, lỗi bao nhiêu", "view"),
    ("health", "Tình trạng các tài khoản", "tình trạng từng tài khoản", "view"),
    ("error", "Bài bị lỗi — thử lại hoặc bỏ qua", "bài đăng/bình luận bị lỗi: thử lại hoặc bỏ qua", "act"),
    ("overdue", "Bài lỡ giờ — xếp lại hoặc huỷ", "bài lỡ giờ đăng: xếp lại giờ hoặc huỷ", "act"),
    ("review", "Tin chờ duyệt — duyệt hoặc bỏ qua", "tin tuyển dụng chờ bạn duyệt", "act"),
    ("pause", "Tạm dừng tự động đăng", "tạm dừng (các bài đến giờ sẽ nằm lại hàng chờ)", "auto"),
    ("resume", "Bật lại tự động đăng", "bật lại", "auto"),
    ("help", "Danh sách lệnh", "hiện lại danh sách này", "other"),
]
_HELP_GROUPS = [
    ("view", "📋 XEM NHANH"),
    ("act", "🛠 XỬ LÝ (có nút bấm ngay trong Telegram)"),
    ("auto", "⏯ TỰ ĐỘNG ĐĂNG"),
    ("other", ""),
]
# The menu lists the commands in the order people reach for them: look first, then act.
COMMANDS: list[tuple[str, str]] = [(name, short) for name, short, _long, _group in _SPEC]
_COMMAND_NAMES = {c for c, _ in COMMANDS} | {"start"}
# The commands used to have Vietnamese names (before 2026-11-01). They still work —
# parse_command() maps them to the English name — but are no longer listed in the
# bot menu or /help.
_LEGACY_ALIASES = {
    "lich": "schedule", "quahan": "overdue", "loi": "error", "choduyet": "review",
    "baocao": "report", "suckhoe": "health", "tamdung": "pause", "tieptuc": "resume",
}
_MAX_LINES = 10  # list lines per reply (Telegram caps a message at 4096 chars)
_JST = timedelta(hours=9)
_CMD_RE = re.compile(r"^/([A-Za-z0-9_]+)(?:@(\S+))?(?:\s|$)")


def parse_command(text: str | None) -> str | None:
    """"/schedule", "/schedule@my_bot", "/schedule arg" → "schedule"; anything else
    (plain text, or "/" followed by garbage) → None. An old Vietnamese name
    ("/lich") gives its English name."""
    m = _CMD_RE.match((text or "").strip())
    if not m:
        return None
    name = m.group(1).lower()
    return _LEGACY_ALIASES.get(name, name)


def command_target(text: str | None) -> str | None:
    """The "@bot_name" a command is addressed to ("/schedule@my_bot" →
    "my_bot"), None when it carries no suffix (the normal private-chat
    case). Lets the caller ignore commands meant for another bot."""
    m = _CMD_RE.match((text or "").strip())
    return m.group(2) if m and m.group(2) else None


def is_known_command(name: str | None) -> bool:
    return name in _COMMAND_NAMES


UNKNOWN_INTRO = "🤔 Mình chưa hiểu tin nhắn này."
WELCOME_INTRO = "👋 Xin chào! Mình là bot hỗ trợ đăng bài."


def help_text(intro: str | None = None) -> str:
    """The command list, built from _SPEC. `intro` is a first line for the cases where the person
    did not ask for /help (a message the bot did not understand, or /start)."""
    blocks = []
    for group, title in _HELP_GROUPS:
        lines = [f"/{name} — {long}" for name, _short, long, g in _SPEC if g == group]
        if lines:
            blocks.append("\n".join(([title] if title else []) + lines))
    boundary = _boundary_hhmm()
    blocks.append("💡 Mẹo: trả lời (reply) một tin báo lỗi bằng nội dung mới để đăng lại bằng nội dung đó.")
    blocks.append(f'🕐 Giờ hiển thị theo giờ Nhật (JST). "Hôm nay" tính từ {boundary} đến {boundary} hôm sau.')
    return (intro + "\n\n" if intro else "") + "Các lệnh bạn có thể dùng:\n\n" + "\n\n".join(blocks)


def static_reply(command: str | None) -> str | None:
    """The fixed-text answer for /help, /start and anything the bot does not know (None for the
    commands that are built from live data)."""
    if command == "start":
        return help_text(WELCOME_INTRO)
    if command == "help":
        return help_text()
    if not is_known_command(command):
        return help_text(UNKNOWN_INTRO)
    return None


def _boundary_hhmm() -> str:
    """When the business day starts, in JST ("02:00") — read from the same place the daily caps use."""
    return (daily_limits.business_day_start(datetime.now(timezone.utc)) + _JST).strftime("%H:%M")


# "today" and time parsing are defined once, in human_bot/overview.py (also used by the admin home page)
_day_bounds = overview.day_bounds


def _parse(iso: str) -> datetime | None:
    return overview.parse_iso(iso)


_ACTION_LABEL = {
    "post_to_group": "Đăng bài",
    "post_to_own_profile": "Đăng lên tường cá nhân",
    "comment_on_group_post": "Bình luận",
    "comment_on_friend_post": "Bình luận bài bạn bè",
    "like_post": "Thích bài",
    "read_recent_comments": "Đọc bình luận",
}


def action_label(action: str | None) -> str:
    """"post_to_group" → "Đăng bài" — the internal action names mean nothing to a reader."""
    return _ACTION_LABEL.get(action or "", action or "?")


def account_name(account_id: str, accounts: dict | None = None) -> str:
    """The account's display name (📄 for a Facebook Page), else the id it was registered under.
    Pass `accounts` (get_all_accounts()) when naming several: it is merged from disk on each call."""
    account = (get_all_accounts() if accounts is None else accounts).get(account_id)
    if account is None:
        return account_id
    return ("📄 " if getattr(account, "page_name", "") else "") + (getattr(account, "display_name", "") or account_id)


def short_when(iso: str | None, now: datetime | None = None) -> str:
    """"20:01" for a time on today's (JST) calendar date, "02/11 00:30" for another date."""
    when = _parse(iso or "")
    if when is None:
        return "?"
    now = now or datetime.now(timezone.utc)
    if (when + _JST).date() == (now + _JST).date():
        return (when + _JST).strftime("%H:%M")
    return (when + _JST).strftime("%d/%m %H:%M")


def target_label(task) -> str:
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
    today, stuck, later = overview.split_pending(now)
    later_line = f"📆 Các ngày sau: {later} bài."
    accounts = get_all_accounts()
    if not today:
        return f"📅 Hôm nay không còn bài nào chờ đăng.\n{later_line}"

    def entry(t) -> str:
        when = _parse(t.scheduled_at)
        mark = "⏰ " if (when is None or when <= now) else ""
        return f"• {mark}{short_when(t.scheduled_at, now)} · {action_label(t.action)} · {account_name(t.account_id, accounts)}\n   ↳ {target_label(t)}"

    lines = [entry(t) for t in today[:_MAX_LINES]]
    if len(today) > _MAX_LINES:
        lines.append(f"…và {len(today) - _MAX_LINES} bài khác")
    parts = [f"📅 Bài sắp đăng hôm nay: {len(today)} bài (giờ JST)"]
    if stuck:
        parts.append(
            f"⏰ {stuck} bài đã đến giờ nhưng chưa chạy. Có thể do: tự động đăng đang tạm dừng (kiểm tra bằng /resume), "
            "tài khoản chạm giới hạn tốc độ, hoặc service vừa khởi động lại."
        )
    return "\n\n".join([parts[0] + ("\n" + parts[1] if stuck else ""), "\n".join(lines), later_line])


def missed_reason_tag(task_id: str) -> str:
    reason = schedule_store.get_missed_reason(task_id) or ""
    if reason.startswith("Mất mạng"):
        return "mất mạng"
    if "khởi động" in reason:
        return "service tắt"
    if "đang được tắt" in reason:
        return "tài khoản bị tắt"
    if "đang tạm dừng" in reason:
        return "tài khoản tạm dừng"
    return "khác"


def _activity_block(since: datetime, until: datetime | None) -> str:
    since_iso = since.isoformat()
    until_iso = until.isoformat() if until else None
    accounts = get_all_accounts()
    lines, idle = [], []
    total_ok = total_fail = 0
    for aid in sorted(accounts):
        stats = db.summary_stats(aid, since_iso, until_iso)
        if not stats["total"]:
            idle.append(account_name(aid, accounts))
            continue
        total_ok += stats["succeeded"]
        total_fail += stats["failed"]
        by_action: dict[str, list[int]] = {}
        for row in db.action_type_counts(aid, since_iso, until_iso):
            ok_fail = by_action.setdefault(row["action"], [0, 0])
            ok_fail[0 if row["success"] else 1] += row["total"]
        detail = " · ".join(
            f"{action_label(a)} " + " ".join(p for p in (f"✅{ok}" if ok else "", f"❌{bad}" if bad else "") if p)
            for a, (ok, bad) in by_action.items()
        )
        lines.append(f"• {account_name(aid, accounts)}: ✅ {stats['succeeded']} · ❌ {stats['failed']}" + (f"\n   ↳ {detail}" if detail else ""))
    if not lines:
        return "Chưa có lượt đăng/bình luận nào."
    if idle:
        lines.append(f"• Chưa có lượt nào: {', '.join(idle)}")
    return f"Kết quả: ✅ {total_ok} thành công · ❌ {total_fail} thất bại\n\n" + "\n".join(lines)


def _queue_footer(now: datetime) -> str:
    """The queue AS OF NOW (not as of the day being reported) — said so in the heading. Counts the
    same way /schedule does, so the two never disagree: tasks overdue but still pending are
    included and called out. Only what needs attention gets a line, each with the command that
    deals with it."""
    queue = overview.queue_counts(now)  # the same numbers the admin home page shows
    left, stuck = queue.left_today, queue.due
    from human_bot import telegram_failures  # local import — it imports modules that import this one
    missed, errors, reviews = len(schedule_store.list_missed()), telegram_failures.open_failure_count(), len(schedule_store.list_needs_review())
    lines = ["Tình hình hiện tại:", f"📅 Chờ đăng hôm nay: {left}" + (f" (⏰ {stuck} đã quá giờ chưa chạy)" if stuck else "")]
    if missed:
        lines.append(f"⚠️ Bài lỡ giờ: {missed} → /overdue")
    if errors:
        lines.append(f"❌ Lỗi chưa xử lý: {errors} → /error")
    if reviews:
        lines.append(f"🔍 Tin chờ duyệt: {reviews} → /review")
    if not (missed or errors or reviews):
        lines.append("✅ Không có bài lỡ giờ, lỗi hay tin nào đang chờ xử lý.")
    return "\n".join(lines)


def report_text(now: datetime | None = None) -> str:
    now = now or datetime.now(timezone.utc)
    start, _end = _day_bounds(now)
    return f"📊 Báo cáo hôm nay (từ {_boundary_hhmm()} JST đến giờ)\n\n{_activity_block(start, None)}\n\n{_queue_footer(now)}"


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
    return f"🌅 Tóm tắt ngày {label} ({_boundary_hhmm()} → {_boundary_hhmm()} JST)\n\n{_activity_block(day_start, today_start)}\n\n{_queue_footer(now)}"
