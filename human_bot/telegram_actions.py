"""
Purpose of this file / Muc dich cua file nay:
EN: Telegram Vòng 2 (2026-10-16) — action BUTTONS under bot messages:
  - /quahan  → each overdue task with [🔄 Lên lịch lại] [🗑 Huỷ]
  - /choduyet → each job waiting for review with [✅ Duyệt] [🗑 Bỏ qua]
  - /tamdung, /tieptuc → [⏸ Tạm dừng tự đăng] / [▶️ Bật lại tự đăng]
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
from datetime import datetime, timezone
from typing import Any

from human_bot import admin, schedule_store, telegram_commands
from human_bot.config import get_all_accounts
from human_bot.runtime_config import get_scheduling_config, get_scheduling_overrides, save_scheduling_overrides
from human_bot.telegram_alerts import jst_hhmm

logger = logging.getLogger("human_bot.telegram_actions")

MAX_ITEMS = 5  # messages per command — each is its own message with its own buttons

Keyboard = list[list[dict[str, str]]]


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


def _missed_item(task) -> Item:
    text = (
        f"⚠️ Task quá hạn · {jst_hhmm(task.scheduled_at)} JST · {telegram_commands.missed_reason_tag(task.task_id)}\n"
        f"{task.account_id} · {task.action}\n"
        f"Nhóm: {telegram_commands.target_label(task)}\n"
        f"Nội dung: {_preview(task.content) or '(không có)'}"
    )
    return Item(text, _main_keyboard("mt", task.task_id))


def _review_item(review) -> Item:
    title = ((review.job_data or {}).get("title") or "(không có tiêu đề)")
    try:
        confidence = f"{float(review.confidence):.2f}"
    except (TypeError, ValueError):
        confidence = "không rõ"
    first = review.contents[0] if review.contents else ""
    text = (
        f"🔍 Job chờ duyệt — {_preview(str(title), 100)}\n"
        f"Dự kiến đăng: {review.account_id} · {len(review.groups)} nhóm · độ tin cậy {confidence}\n"
        f"Nội dung mẫu: {_preview(first, 300) or '(trống)'}"
    )
    return Item(text, _main_keyboard("rv", review.review_id))


def _autofire_item(command: str) -> Item:
    on = get_scheduling_config().auto_fire_enabled
    if command == "tamdung":
        if not on:
            return Item("⏸ Tự động đăng đang TẮT sẵn rồi. Dùng /tieptuc để bật lại.")
        return Item(
            "Tự động đăng đang BẬT. Tạm dừng sẽ giữ MỌI task đến giờ ở lại hàng chờ "
            "(không đăng) cho tới khi bật lại — nút \"Đăng ngay\" thủ công ở /admin vẫn dùng được.",
            _main_keyboard("af", "off"),
        )
    if on:
        return Item("▶️ Tự động đăng đang BẬT sẵn rồi. Dùng /tamdung để tạm dừng.")
    return Item(
        "Tự động đăng đang TẮT. Bật lại thì các task đã đến giờ trong hàng chờ sẽ được đăng ngay "
        "(theo giới hạn tốc độ của từng tài khoản).",
        _main_keyboard("af", "on"),
    )


def build_items(command: str) -> list[Item]:
    """Interactive messages for a command, in addition to (or instead of)
    the plain text reply. Empty list = nothing interactive for it."""
    if command == "quahan":
        missed = schedule_store.list_missed()
        if not missed:
            return [Item("✅ Không có task nào quá hạn.")]
        items = [_missed_item(t) for t in missed[:MAX_ITEMS]]
        if len(missed) > MAX_ITEMS:
            items.append(Item(f"…còn {len(missed) - MAX_ITEMS} task quá hạn nữa — xử lý xong các task trên rồi gõ lại /quahan, hoặc vào /admin/schedule."))
        return items
    if command == "choduyet":
        reviews = schedule_store.list_needs_review()
        if not reviews:
            return [Item("✅ Không có job nào đang chờ duyệt.")]
        items = [_review_item(r) for r in reviews[:MAX_ITEMS]]
        if len(reviews) > MAX_ITEMS:
            items.append(Item(f"…còn {len(reviews) - MAX_ITEMS} job chờ duyệt nữa (xem ở /admin/schedule, tab \"Chờ duyệt\")."))
        return items
    if command in ("tamdung", "tieptuc"):
        return [_autofire_item(command)]
    return []


# --- executing a button press --------------------------------------------------

def _gone(original: str, what: str) -> CallbackResult:
    return CallbackResult(
        toast="Đã được xử lý rồi",
        text=f"{original}\n\nℹ️ {what} đã được xử lý ở nơi khác.",
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
            return _gone(original, "Task này")
        account = get_all_accounts().get(task.account_id)
        if account is None:
            return CallbackResult(toast="Không tìm thấy tài khoản của task này")
        suggested = admin._suggest_reschedule_at(account, task.action)
        label = f"Lên lịch lại (khoảng {jst_hhmm(suggested.isoformat())})"
    elif verb == "cm":
        if schedule_store.get_missed(ident) is None:
            return _gone(original, "Task này")
        label = "Huỷ task"
    elif verb == "ap":
        review = schedule_store.get_needs_review(ident)
        if review is None:
            return _gone(original, "Job này")
        label = f"Duyệt (tạo {len(review.groups)} task)"
    elif verb == "rj":
        if schedule_store.get_needs_review(ident) is None:
            return _gone(original, "Job này")
        label = "Bỏ qua job"
    elif verb == "af":
        label = "Tạm dừng" if ident == "off" else "Bật lại"
    else:
        return CallbackResult(toast="Nút không hợp lệ")
    return CallbackResult(keyboard=_confirm_keyboard(verb, ident, label))


def _execute(verb: str, ident: str, original: str, actor: str) -> CallbackResult:
    if verb == "af" and ident not in ("on", "off"):
        return CallbackResult(toast="Nút không hợp lệ")  # a garbled id must never pause auto-posting
    if verb == "rs":
        task = schedule_store.get_missed(ident)
        if task is None:
            return _gone(original, "Task này")
        account = get_all_accounts().get(task.account_id)
        if account is None:
            return CallbackResult(toast="Không tìm thấy tài khoản của task này", keyboard=_main_keyboard("mt", ident))
        suggested = admin._suggest_reschedule_at(account, task.action)
        restored = schedule_store.restore_to_pending(ident, scheduled_at=suggested.isoformat())
        if restored is None:
            return _gone(original, "Task này")
        return _resolved(
            original, f"✅ Đã lên lịch lại lúc {jst_hhmm(suggested.isoformat())} JST — bởi {actor}", "Đã lên lịch lại",
        )
    if verb == "cm":
        if not schedule_store.cancel_missed(ident):
            return _gone(original, "Task này")
        return _resolved(original, f"🗑 Đã huỷ task — bởi {actor}", "Đã huỷ")
    if verb == "ap":
        err, created = admin.approve_needs_review_core(ident, "", None)
        if err in admin.REVIEW_ALREADY_HANDLED_ERRS:
            return _gone(original, "Job này")
        if err:
            # Not consumed (the core restores the review) — keep the buttons usable.
            return CallbackResult(toast=err[:190], keyboard=_main_keyboard("rv", ident))
        return _resolved(original, f"✅ Đã duyệt — tạo {created} task chờ đăng, bởi {actor}", "Đã duyệt")
    if verb == "rj":
        if not schedule_store.reject_needs_review(ident):
            return _gone(original, "Job này")
        return _resolved(original, f"🗑 Đã bỏ qua job — bởi {actor}", "Đã bỏ qua")
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
            else f"⏸ {actor} đã TẠM DỪNG tự động đăng — mọi task đến giờ sẽ nằm lại hàng chờ. Dùng /tieptuc để bật lại."
        )
        return CallbackResult(toast="Đã bật lại" if want_on else "Đã tạm dừng", text=f"{original}\n\n{line}", keyboard=[], broadcast=line)
    return CallbackResult(toast="Nút không hợp lệ")


def handle_callback(data: str, original_text: str, actor: str) -> CallbackResult:
    """Runs one button press. `original_text` is the message's current
    text (results are appended to it), `actor` is who pressed (a recipient
    label). Never raises for a malformed/stale `data`."""
    verb, _, rest = (data or "").partition("|")
    original_text = original_text or ""
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
