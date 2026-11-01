"""
Purpose of this file / Muc dich cua file nay:
EN: Buttons on the loud "N failures IN A ROW" alert (2026-11-01, failure tickets
phase 2). That alert used to be a text with nothing to press; the next thing the
operator does is nearly always the same — stop the account from failing again
and again (a bot that keeps retrying a broken session looks worse to Facebook)
— so the alert now carries the choices, applied to the account that failed:

  [⏻ Tắt]      one tap — nothing is wrong with the account, it just rests; the
               card then offers [▶ Bật lại] (immediate, full limits).
  [⚠ Tạm dừng] asks to confirm — for a suspected Facebook restriction; the card
               then offers [▶ Kích hoạt lại (hạ nhiệt)] (asks to confirm too:
               resuming starts the reduced-limit cooldown).
  [👌 Đã biết] just removes the buttons.

Same rules as the admin's two buttons (runtime_config.set_account_disabled /
set_account_paused / resume_account); the card is re-rendered from the account's
LIVE status, so it stays true when the admin changes it, and every recipient's
copy is refreshed once one of them has acted.
VI: Nut tren tin "N lan that bai LIEN TIEP": Tat / Tam dung (can xac nhan) / Da biet.
"""
from __future__ import annotations

import logging
from typing import Any

from human_bot import failure_info, failure_tickets
from human_bot.config import AccountStatus, get_all_accounts
from human_bot.telegram_actions import CallbackResult, _btn

logger = logging.getLogger("human_bot.telegram_streaks")

_ACTION_LABEL = {
    "comment_on_group_post": "bình luận", "comment_on_friend_post": "bình luận",
    "post_to_own_profile": "đăng lên tường cá nhân",
}
_HANDLED_LINE = {
    "off": "⏻ {who} đã TẮT tài khoản này (bật lại là chạy ngay).",
    "paused": "⚠ {who} đã TẠM DỪNG tài khoản này (nghi bị Facebook hạn chế).",
    "on": "▶ {who} đã bật lại tài khoản này.",
    "resumed": "▶ {who} đã kích hoạt lại tài khoản này (đang chạy giới hạn thấp một thời gian).",
    "ack": "👌 {who} đã xem.",
}


def create_ticket(account_id: str, action: str, streak: int, message: str) -> dict[str, Any]:
    account = get_all_accounts().get(account_id)
    return failure_tickets.create(
        kind=failure_tickets.STREAK, account_id=account_id, action=action, streak=streak, message=message,
        account_label=(("📄 " if getattr(account, "page_name", "") else "") + account.display_name) if account else account_id,
        handled=None,
    )


def render(ticket: dict[str, Any]) -> str:
    account = get_all_accounts().get(ticket.get("account_id", ""))
    info = failure_info.classify(ticket.get("message"))
    what = _ACTION_LABEL.get(ticket.get("action", ""), "đăng bài")
    lines = [
        f"🔴 {ticket.get('account_label') or ticket.get('account_id')} · {what} thất bại {ticket.get('streak')} lần LIÊN TIẾP",
        f"Lần gần nhất: {info.cause}",
    ]
    technical = failure_info.technical_line(ticket.get("message") or "", 90)
    if technical:
        lines.append(f"({technical})")
    if account is None:
        lines.append("Tài khoản này không còn trong hệ thống.")
    else:
        lines.append({
            AccountStatus.ACTIVE: "Tài khoản đang hoạt động.",
            AccountStatus.DISABLED: "Tài khoản đang TẮT.",
            AccountStatus.PAUSED: "Tài khoản đang TẠM DỪNG.",
        }.get(account.status, ""))
    handled = ticket.get("handled")
    if handled in _HANDLED_LINE:
        lines.append(_HANDLED_LINE[handled].format(who=ticket.get("resolved_by") or "Ai đó"))
    return "\n".join(l for l in lines if l)[:1000]


def keyboard_for(ticket: dict[str, Any]) -> list[list[dict[str, str]]]:
    tid = ticket["id"]
    account = get_all_accounts().get(ticket.get("account_id", ""))
    if account is None:
        return []
    if account.status == AccountStatus.DISABLED:
        return [[_btn("▶ Bật lại", f"fa|on|{tid}")]]
    if account.status == AccountStatus.PAUSED:
        return [[_btn("▶ Kích hoạt lại (hạ nhiệt)", f"fa|rv|{tid}")]]
    if ticket.get("handled") is not None:
        return []  # acknowledged / already brought back — nothing left to decide
    return [
        [_btn("⏻ Tắt", f"fa|off|{tid}"), _btn("⚠ Tạm dừng", f"fa|ps|{tid}")],
        [_btn("👌 Đã biết", f"fa|ok|{tid}")],
    ]


def _result(ticket: dict[str, Any], toast: str = "", *, close_session_of: str | None = None, alert: bool = False) -> CallbackResult:
    return CallbackResult(
        toast=toast, text=render(ticket), keyboard=keyboard_for(ticket), ticket_id=ticket["id"],
        close_session_of=close_session_of, alert=alert,
    )


def handle_callback(rest: str, actor: str) -> CallbackResult:
    """`rest` = "<verb>|<ticket id>" (the part after "fa|")."""
    from human_bot import telegram_failures
    with telegram_failures.action_lock():  # one press at a time, like the failure cards
        return _handle_locked(rest, actor)


def _handle_locked(rest: str, actor: str) -> CallbackResult:
    from human_bot.runtime_config import resume_account, set_account_disabled, set_account_paused
    verb, _, ticket_id = rest.partition("|")
    ticket = failure_tickets.get(ticket_id)
    if ticket is None or ticket.get("kind") != failure_tickets.STREAK:
        return CallbackResult(toast="Tin này không còn (đã quá cũ hoặc bị xoá)", keyboard=[])
    aid = ticket.get("account_id", "")
    account = get_all_accounts().get(aid)
    if account is None:
        return CallbackResult(toast="Tài khoản này không còn trong hệ thống.", text=render(ticket), keyboard=[], alert=True)
    if verb == "bk":
        return _result(ticket)

    def done(handled: str, toast: str, **extra) -> CallbackResult:
        updated = failure_tickets.update(ticket["id"], handled=handled, resolved_by=actor) or ticket
        return _result(updated, toast, **extra)

    if verb == "ok":
        return done("ack", "Đã ghi nhận")
    if verb == "off":
        if account.status != AccountStatus.ACTIVE:
            return _result(ticket, "Tài khoản không còn ở trạng thái hoạt động — bảng nút đã được làm mới")
        set_account_disabled(aid, True)
        logger.warning("telegram: %s switched account %s off from a failure-streak alert", actor, aid)
        return done("off", "Đã tắt tài khoản", close_session_of=aid)
    if verb == "on":
        if account.status != AccountStatus.DISABLED:
            return _result(ticket, "Tài khoản không còn đang tắt")
        set_account_disabled(aid, False)
        return done("on", "Đã bật lại")
    if verb == "ps":
        if account.status != AccountStatus.ACTIVE:
            return _result(ticket, "Tài khoản không còn ở trạng thái hoạt động — bảng nút đã được làm mới")
        return CallbackResult(
            alert=True,
            toast=f"Tạm dừng {aid[:30]} vì nghi Facebook hạn chế? Kích hoạt lại sẽ phải chạy giới hạn thấp vài ngày (hạ nhiệt). Chỉ nghỉ thì dùng Tắt. Xác nhận?",
            keyboard=[[_btn("✅ Xác nhận tạm dừng", f"fa|pc|{ticket['id']}"), _btn("↩ Quay lại", f"fa|bk|{ticket['id']}")]],
        )
    if verb == "pc":
        if account.status != AccountStatus.ACTIVE:
            return _result(ticket, "Tài khoản không còn ở trạng thái hoạt động — bảng nút đã được làm mới")
        set_account_paused(aid, True, reason=f"Tạm dừng qua Telegram sau {ticket.get('streak')} lần thất bại liên tiếp")
        logger.warning("telegram: %s paused account %s from a failure-streak alert", actor, aid)
        return done("paused", "Đã tạm dừng tài khoản", close_session_of=aid)
    if verb == "rv":
        if account.status != AccountStatus.PAUSED:
            return _result(ticket, "Tài khoản không còn đang tạm dừng")
        return CallbackResult(
            alert=True,
            toast="Kích hoạt lại tài khoản đã tạm dừng vì nghi vấn đề: nó sẽ chạy giới hạn thấp vài ngày. Xác nhận?",
            keyboard=[[_btn("✅ Xác nhận kích hoạt lại", f"fa|rc|{ticket['id']}"), _btn("↩ Quay lại", f"fa|bk|{ticket['id']}")]],
        )
    if verb == "rc":
        if account.status != AccountStatus.PAUSED:
            return _result(ticket, "Tài khoản không còn đang tạm dừng")
        resume_account(aid)  # with the reduced-limit cooldown, exactly like the admin's "Kích hoạt lại"
        return done("resumed", "Đã kích hoạt lại (đang hạ nhiệt)")
    return CallbackResult(toast="Nút không hợp lệ")


async def send_alert(account_id: str, action: str, streak: int, message: str) -> None:
    """The loud alert. Falls back to the old plain text when the card cannot be made or
    reaches nobody — this alert must never be lost, and never doubled."""
    import asyncio

    from human_bot import telegram_notify
    if not telegram_notify.is_configured():
        return
    ticket, refs = None, []
    try:
        ticket = await asyncio.to_thread(create_ticket, account_id, action, streak, message)
        refs = await telegram_notify.send_ticket(render(ticket), keyboard_for(ticket), silent=False)
    except Exception:  # noqa: BLE001 — an alert must never fail the task it reports on
        logger.exception("could not send the streak alert card — falling back to the plain alert")
    for ref in refs:
        try:
            await asyncio.to_thread(failure_tickets.add_message, ticket["id"], ref["chat_id"], ref["message_id"], ref["photo"])
        except Exception:  # noqa: BLE001 — the card WAS delivered: a plain alert on top would be a duplicate
            logger.exception("could not remember where the streak alert %s was sent", ticket["id"])
    if not refs:
        if ticket is not None:
            await asyncio.to_thread(failure_tickets.delete, ticket["id"])  # nobody holds this card — do not leave it behind
        await telegram_notify.send_message(
            f"🔴 {account_id} · {action} thất bại {streak} lần LIÊN TIẾP\nLần gần nhất: {message}", silent=False,
        )
