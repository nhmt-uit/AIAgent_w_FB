"""
Purpose of this file / Muc dich cua file nay:
EN: Telegram Vòng 2 (2026-10-16) — action BUTTONS under bot messages:
  - /overdue  → each overdue task with [🔄 Lên lịch lại] [🗑 Huỷ]
  - /review → each job waiting for review with [✅ Duyệt] [🗑 Bỏ qua]
  - /pause, /resume → [⏸ Tạm dừng tự đăng] / [▶️ Bật lại tự đăng]
Owner decision: everyone in the admin-managed recipient list may act (no
separate roles). Pure logic only — building the messages and executing a
button press; no Telegram I/O (human_bot/service.py does the sending), so it
is easy to test. Every action reuses the SAME core the /admin UI uses
(admin._suggest_reschedule_at, admin.approve_needs_review_core, schedule_store).

Every state-changing button is TWO-STEP: the first tap only swaps the
keyboard for [✅ Xác nhận …] [↩ Quay lại] (a mis-tap on a phone is cheap to
make); the second tap executes. Execution is idempotent against stale or
doubled taps (another recipient got there first → "đã được xử lý"), because
each underlying operation claims its file atomically.

callback_data format (Telegram caps it at 64 bytes): "<verb>|<id>", the
execute step adds "!" to the verb, "bk|<kind>|<id>" goes back.
  rs=reschedule missed, cm=cancel missed, ap=approve review, rj=reject
  review, af=auto-fire on/off (id is "on"/"off").
VI: Nut bam duoi tin nhan Telegram (Vong 2): len lich lai/huy task qua han,
duyet/bo qua job cho duyet, tam dung/bat lai tu dang. Moi nguoi trong danh
sach nguoi nhan deu thao tac duoc; moi hanh dong deu co buoc xac nhan.
"""
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from human_bot import admin, schedule_store, telegram_commands
from human_bot.config import get_all_accounts
from human_bot.runtime_config import get_scheduling_config, get_scheduling_overrides, save_scheduling_overrides
from human_bot.telegram_alerts import jst_hhmm

logger = logging.getLogger("human_bot.telegram_actions")

MAX_ITEMS = 5  # messages per command — each is its own message with its own buttons

Keyboard = list[list[dict[str, str]]]
_JST = timedelta(hours=9)


@dataclass
class Item:
    """One message to send. keyboard None = plain text."""
    text: str
    keyboard: Keyboard | None = None


@dataclass
class CallbackResult:
    toast: str = ""  # small popup shown to the person who tapped
    text: str | None = None  # new message text; None = leave the text as it was
    # New buttons; [] removes them. None = leave them as they are ONLY when
    # `text` is also None — Telegram drops the buttons on any text edit that
    # doesn't resend them, so a result that changes `text` should always set
    # `keyboard` too.
    keyboard: Keyboard | None = None
    broadcast: str | None = None  # also tell every recipient (high-impact toggles)
    ticket_id: str | None = None  # a failure ticket this press changed → refresh every recipient's copy
    also_sync: tuple[str, ...] = ()  # more tickets this press changed (a group card's members) → refresh their copies too
    close_session_of: str | None = None  # an account just switched off/paused → close its idle browser
    alert: bool = False  # show `toast` as a popup that stays until dismissed (for refusals worth reading)


def _btn(label: str, data: str) -> dict[str, str]:
    if len(data.encode("utf-8")) > 64:  # Telegram's hard cap; explicit (not `assert`, which -O strips)
        raise ValueError(f"callback_data too long: {data}")
    return {"text": label, "callback_data": data}


# --- keyboards ---------------------------------------------------------------

_KIND_OF_VERB = {"rs": "mt", "cm": "mt", "ap": "rv", "rj": "rv", "af": "af"}


def _main_keyboard(kind: str, ident: str) -> Keyboard:
    if kind == "mt":
        return [[_btn("🔄 Lên lịch lại", f"rs|{ident}"), _btn("🗑 Huỷ", f"cm|{ident}")]]
    if kind == "rv":
        return [[_btn("✅ Duyệt", f"ap|{ident}"), _btn("🗑 Bỏ qua", f"rj|{ident}")]]
    if kind == "af":
        label = "⏸ Tạm dừng tự đăng" if ident == "off" else "▶️ Bật lại tự đăng"
        return [[_btn(label, f"af|{ident}")]]
    return []


def _confirm_keyboard(verb: str, ident: str, label: str) -> Keyboard:
    kind = _KIND_OF_VERB[verb]
    return [[_btn(f"✅ {label}", f"{verb}!|{ident}"), _btn("↩ Quay lại", f"bk|{kind}|{ident}")]]


# --- message builders ---------------------------------------------------------

def _preview(text: str | None, limit: int = 220) -> str:
    text = (text or "").strip()
    return text if len(text) <= limit else text[:limit] + "…"


def _lateness(scheduled_at: str, now: datetime) -> str:
    """"hôm nay" / "hôm qua" / "3 ngày trước" by JST calendar date, so it always agrees with the date printed beside it."""
    when = telegram_commands._parse(scheduled_at)
    if when is None:
        return "?"
    days = ((now + _JST).date() - (when + _JST).date()).days
    return "hôm nay" if days <= 0 else "hôm qua" if days == 1 else f"{days} ngày trước"


def _missed_item(task, now: datetime | None = None, accounts: dict | None = None) -> Item:
    now = now or datetime.now(timezone.utc)
    text = (
        "⚠️ Bài lỡ giờ đăng\n"
        f"🕐 Hẹn lúc {jst_hhmm(task.scheduled_at)} JST ({_lateness(task.scheduled_at, now)})\n"
        f"❓ Lý do: {telegram_commands.missed_reason_tag(task.task_id)}\n"
        f"👤 Tài khoản: {telegram_commands.account_name(task.account_id, accounts)}\n"
        f"🔖 Việc: {telegram_commands.action_label(task.action)}\n"
        f"📍 Nhóm: {telegram_commands.target_label(task)}\n"
        f"📝 Nội dung: {_preview(task.content) or '(không có)'}"
    )
    return Item(text, _main_keyboard("mt", task.task_id))


def _review_item(review, accounts: dict | None = None) -> Item:
    title = ((review.job_data or {}).get("title") or "(không có tiêu đề)")
    try:
        confidence = f"{float(review.confidence):.2f}"
    except (TypeError, ValueError):
        confidence = "không rõ"
    first = review.contents[0] if review.contents else ""
    text = (
        f"🔍 Tin tuyển dụng chờ duyệt\n"
        f"📌 Tiêu đề: {_preview(str(title), 100)}\n"
        f"👤 Sẽ đăng bằng: {telegram_commands.account_name(review.account_id, accounts)} · {len(review.groups)} nhóm\n"
        f"📊 Độ tin cậy của AI: {confidence} (thang 0–1, càng cao càng chắc)\n"
        f"📝 Bài mẫu: {_preview(first, 300) or '(trống)'}"
    )
    return Item(text, _main_keyboard("rv", review.review_id))


def _autofire_item(command: str) -> Item:
    on = get_scheduling_config().auto_fire_enabled
    if command == "pause":
        if not on:
            return Item("⏸ Tự động đăng đang TẮT sẵn rồi.\nGõ /resume để bật lại.")
        return Item(
            "⏯ Tự động đăng đang BẬT.\n\n"
            "Nếu tạm dừng: các bài đến giờ sẽ nằm lại hàng chờ, KHÔNG tự đăng, cho tới khi bạn bật lại "
            "(nút \"Đăng ngay\" thủ công ở /admin vẫn dùng được).\n\n"
            "Bạn muốn tạm dừng?",
            _main_keyboard("af", "off"),
        )
    if on:
        return Item("▶️ Tự động đăng đang BẬT sẵn rồi.\nGõ /pause nếu muốn tạm dừng.")
    return Item(
        "⏸ Tự động đăng đang TẮT.\n\n"
        "Nếu bật lại: các bài đã đến giờ trong hàng chờ sẽ được đăng ngay (theo giới hạn tốc độ của từng tài khoản).\n\n"
        "Bạn muốn bật lại?",
        _main_keyboard("af", "on"),
    )


def build_items(command: str) -> list[Item]:
    """Interactive messages for a command, in addition to (or instead of)
    the plain text reply. Empty list = nothing interactive for it."""
    if command == "overdue":
        missed = schedule_store.list_missed()
        if not missed:
            return [Item("✅ Không có bài nào lỡ giờ đăng.")]
        shown = missed[:MAX_ITEMS]
        items = []
        if len(missed) > 1:
            items.append(Item(
                f"⚠️ Có {len(missed)} bài lỡ giờ đăng (hiện {len(shown)} bài, mỗi bài một tin bên dưới).\n"
                "🔄 Lên lịch lại: hệ thống tự chọn giờ trống gần nhất · 🗑 Huỷ: bỏ hẳn bài đó."
            ))
        accounts = get_all_accounts()
        items.extend(_missed_item(t, accounts=accounts) for t in shown)
        if len(missed) > MAX_ITEMS:
            items.append(Item(
                f"…còn {len(missed) - MAX_ITEMS} bài lỡ giờ nữa.\n"
                "Xử lý các bài trên rồi gõ lại /overdue để xem tiếp, hoặc vào /admin/schedule → tab \"Task quá hạn\"."
            ))
        return items
    if command == "review":
        reviews = schedule_store.list_needs_review()
        if not reviews:
            return [Item("✅ Không có tin tuyển dụng nào đang chờ duyệt.")]
        shown = reviews[:MAX_ITEMS]
        items = []
        if len(reviews) > 1:
            items.append(Item(
                f"🔍 Có {len(reviews)} tin tuyển dụng chờ duyệt (hiện {len(shown)} tin, mỗi tin một tin nhắn bên dưới).\n"
                "✅ Duyệt: tạo bài đăng vào các nhóm · 🗑 Bỏ qua: không đăng tin này."
            ))
        accounts = get_all_accounts()
        items.extend(_review_item(r, accounts) for r in shown)
        if len(reviews) > MAX_ITEMS:
            items.append(Item(f"…còn {len(reviews) - MAX_ITEMS} tin chờ duyệt nữa (xem ở /admin/schedule, tab \"Chờ duyệt\")."))
        return items
    if command in ("pause", "resume"):
        return [_autofire_item(command)]
    return []


# --- executing a button press --------------------------------------------------

def _gone(original: str, what: str) -> CallbackResult:
    return CallbackResult(
        toast="Đã được xử lý rồi",
        text=f"{original}\n\nℹ️ {what} đã được xử lý ở nơi khác (trang admin hoặc người khác).",
        keyboard=[],
    )


def _resolved(original: str, line: str, toast: str) -> CallbackResult:
    return CallbackResult(toast=toast, text=f"{original}\n\n{line}", keyboard=[])


def _confirm_step(verb: str, ident: str, original: str) -> CallbackResult:
    if verb == "af" and ident not in ("on", "off"):
        return CallbackResult(toast="Nút không hợp lệ")
    if verb == "rs":
        task = schedule_store.get_missed(ident)
        if task is None:
            return _gone(original, "Bài này")
        account = get_all_accounts().get(task.account_id)
        if account is None:
            return CallbackResult(toast="Không tìm thấy tài khoản của bài này")
        suggested = admin._suggest_reschedule_at(account, task.action)
        label = f"Lên lịch lại (khoảng {jst_hhmm(suggested.isoformat())})"
    elif verb == "cm":
        if schedule_store.get_missed(ident) is None:
            return _gone(original, "Bài này")
        label = "Huỷ bài"
    elif verb == "ap":
        review = schedule_store.get_needs_review(ident)
        if review is None:
            return _gone(original, "Tin này")
        label = f"Duyệt (tạo {len(review.groups)} bài đăng)"
    elif verb == "rj":
        if schedule_store.get_needs_review(ident) is None:
            return _gone(original, "Tin này")
        label = "Bỏ qua tin"
    elif verb == "af":
        label = "Tạm dừng" if ident == "off" else "Bật lại"
    else:
        return CallbackResult(toast="Nút không hợp lệ")
    return CallbackResult(toast="Bấm Xác nhận để hoàn tất (hoặc Quay lại)", keyboard=_confirm_keyboard(verb, ident, label))


def _execute(verb: str, ident: str, original: str, actor: str) -> CallbackResult:
    if verb == "af" and ident not in ("on", "off"):
        return CallbackResult(toast="Nút không hợp lệ")  # a garbled id must never pause auto-posting
    if verb == "rs":
        task = schedule_store.get_missed(ident)
        if task is None:
            return _gone(original, "Bài này")
        account = get_all_accounts().get(task.account_id)
        if account is None:
            return CallbackResult(toast="Không tìm thấy tài khoản của bài này", keyboard=_main_keyboard("mt", ident))
        suggested = admin._suggest_reschedule_at(account, task.action)
        restored = schedule_store.restore_to_pending(ident, scheduled_at=suggested.isoformat())
        if restored is None:
            return _gone(original, "Bài này")
        return _resolved(
            original, f"✅ Đã lên lịch lại lúc {jst_hhmm(suggested.isoformat())} JST — bởi {actor}", "Đã lên lịch lại",
        )
    if verb == "cm":
        if not schedule_store.cancel_missed(ident):
            return _gone(original, "Bài này")
        return _resolved(original, f"🗑 Đã huỷ bài — bởi {actor}", "Đã huỷ")
    if verb == "ap":
        err, created = admin.approve_needs_review_core(ident, "", None)
        if err in admin.REVIEW_ALREADY_HANDLED_ERRS:
            return _gone(original, "Tin này")
        if err:
            # Not consumed (the core restores the review) — keep the buttons usable.
            return CallbackResult(toast=err[:190], keyboard=_main_keyboard("rv", ident))
        return _resolved(original, f"✅ Đã duyệt — tạo {created} bài chờ đăng, bởi {actor}", "Đã duyệt")
    if verb == "rj":
        if not schedule_store.reject_needs_review(ident):
            return _gone(original, "Tin này")
        return _resolved(original, f"🗑 Đã bỏ qua tin — bởi {actor}", "Đã bỏ qua")
    if verb == "af":
        want_on = ident == "on"
        if get_scheduling_config().auto_fire_enabled == want_on:
            return _resolved(original, "ℹ️ Đã ở trạng thái này rồi.", "Không đổi")
        # save_*_overrides REPLACES the whole section — read, merge, write.
        overrides = dict(get_scheduling_overrides())
        overrides["auto_fire_enabled"] = want_on
        save_scheduling_overrides(overrides)
        logger.warning("telegram: %s set auto_fire_enabled=%s", actor, want_on)
        line = (
            f"▶️ {actor} đã BẬT LẠI tự động đăng." if want_on
            else f"⏸ {actor} đã TẠM DỪNG tự động đăng — mọi task đến giờ sẽ nằm lại hàng chờ. Dùng /resume để bật lại."
        )
        return CallbackResult(toast="Đã bật lại" if want_on else "Đã tạm dừng", text=f"{original}\n\n{line}", keyboard=[], broadcast=line)
    return CallbackResult(toast="Nút không hợp lệ")


def handle_callback(data: str, original_text: str, actor: str) -> CallbackResult:
    """Runs one button press. `original_text` is the message's current
    text (results are appended to it), `actor` is who pressed (a recipient
    label). Never raises for a malformed/stale `data`."""
    verb, _, rest = (data or "").partition("|")
    original_text = original_text or ""
    if verb in ("fx", "fb", "fa"):
        # Failure cards re-render their own text and buttons: fx = one failure
        # (telegram_failures), fb = a group of failures (telegram_batches),
        # fa = the "N failures in a row" alert (telegram_streaks). Local imports:
        # each of those modules imports this one.
        try:
            if verb == "fx":
                from human_bot import telegram_failures as handler
            elif verb == "fb":
                from human_bot import telegram_batches as handler
            else:
                from human_bot import telegram_streaks as handler
            return handler.handle_callback(rest, actor)
        except Exception:  # noqa: BLE001 — a bad ticket must still answer the tap
            logger.exception("telegram_actions: failure-card callback %r failed", data)
            return CallbackResult(toast="Có lỗi khi xử lý phiếu lỗi — thử lại hoặc dùng /admin.", alert=True)
    try:
        if verb == "bk":
            kind, _, ident = rest.partition("|")
            if kind in ("mt", "rv", "af") and ident:
                return CallbackResult(keyboard=_main_keyboard(kind, ident))
            return CallbackResult(toast="Nút không hợp lệ")
        if verb.endswith("!") and verb[:-1] in _KIND_OF_VERB:
            return _execute(verb[:-1], rest, original_text, actor)
        if verb in _KIND_OF_VERB:
            return _confirm_step(verb, rest, original_text)
    except ValueError:
        # e.g. schedule_store's path-traversal guard rejecting a forged id
        logger.warning("telegram_actions: rejected callback %r", data)
    return CallbackResult(toast="Nút không hợp lệ")
