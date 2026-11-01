"""
Purpose of this file / Muc dich cua file nay:
EN: The loud "keeps failing" alerts and what can be pressed on them (2026-11-01,
failure tickets phases 2-3).

Two alerts, one card type (a "streak" ticket; `scope` says which):
  - account — "N failures IN A ROW" for one account and action. The next thing the
    operator does is nearly always the same — stop the account from failing again
    and again (a bot that keeps retrying a broken session looks worse to Facebook):
      [⏻ Tắt]      one tap — nothing is wrong with the account, it just rests; the
                   card then offers [▶ Bật lại] (immediate, full limits).
      [⚠ Tạm dừng] asks to confirm — for a suspected Facebook restriction; the card
                   then offers [▶ Kích hoạt lại (hạ nhiệt)] (asks to confirm too:
                   resuming starts the reduced-limit cooldown).
  - group — one GROUP keeps failing for the same account. Facebook-side causes (the
    account was blocked or restricted in the group, posts wait for an admin's
    approval, posting rights changed) look exactly like this. Only reported — owner's
    decision: the bot keeps trying the group's later posts; the card says where to
    edit or remove the group (/admin/groups). Failures that say nothing about the
    group (no network, slow Facebook, the browser died) are not counted.
Both have [👌 Đã biết] and [🔕 Im 1 giờ] / [🔕 Im đến 6h sáng]: a snooze mutes THAT
alert (that account+action, or that account+group) for the time; failures are still
logged and handled as usual. Nothing runs on a timer — when the time is up, the next
failure that finds the streak still at or above the threshold alerts again (a used-up
snooze that never meets such a failure is simply cleared the next time one does).

Same rules as the admin's buttons (runtime_config.set_account_disabled /
set_account_paused / resume_account); the account card is re-rendered from the
account's LIVE status, so it stays true when the admin changes it, and every
recipient's copy is refreshed once one of them has acted.
VI: Tin do "N lan that bai LIEN TIEP" (tai khoan) va "nhom loi lien tuc": Tat / Tam dung
(can xac nhan) / Da biet / Im 1 gio / Im den 6h sang.
"""
from __future__ import annotations

import logging
import threading
from datetime import datetime, timedelta, timezone
from typing import Any

from human_bot import failure_info, failure_tickets
from human_bot.config import AccountStatus, get_all_accounts
from human_bot.telegram_actions import CallbackResult, _btn
from human_bot.telegram_alerts import jst_hhmm

logger = logging.getLogger("human_bot.telegram_streaks")

SNOOZE = "snooze"  # failure_tickets kind of a "muted until" record
_snooze_lock = threading.RLock()  # button handlers and the agent's alert check run on different threads
SNOOZE_SHORT = timedelta(hours=1)
_JST = timedelta(hours=9)
_QUIET_UNTIL_HOUR_JST = 6  # "Im đến 6h sáng"

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


# --- snoozing -------------------------------------------------------------------------------------

def account_key(account_id: str, action: str) -> str:
    return f"account:{account_id}:{action}"


def group_key(account_id: str, target_url: str) -> str:
    return f"group:{account_id}:{target_url}"


def _snoozes(key: str) -> list[dict[str, Any]]:
    return [t for t in failure_tickets.list_open(kind=SNOOZE) if t.get("key") == key]


def snooze_until(kind: str, now: datetime | None = None) -> datetime:
    """"1h" → an hour from now; "morning" → the next 06:00 JST (at least an hour away)."""
    now = now or datetime.now(timezone.utc)
    if kind == "1h":
        return now + SNOOZE_SHORT
    jst = now + _JST
    target = jst.replace(hour=_QUIET_UNTIL_HOUR_JST, minute=0, second=0, microsecond=0)
    if target - jst < SNOOZE_SHORT:
        target += timedelta(days=1)
    return target - _JST


def _drop(records: list[dict[str, Any]]) -> None:
    for r in records:
        failure_tickets.delete(r["id"])


def snooze(key: str, until: datetime, by_ticket: str | None = None) -> None:
    """Mutes `key` until `until` (replacing an earlier snooze of the same key). `by_ticket` = the card
    whose button asked for it, so that card's "Báo lại bình thường" only undoes ITS OWN mute."""
    with _snooze_lock:
        _drop(_snoozes(key))
        failure_tickets.create(kind=SNOOZE, key=key, until=until.isoformat(), by_ticket=by_ticket)


def unsnooze(key: str, by_ticket: str | None = None) -> bool:
    """Lifts the mute of `key` (only the one `by_ticket` set, when given). True if one was lifted."""
    with _snooze_lock:
        records = [r for r in _snoozes(key) if by_ticket is None or r.get("by_ticket") == by_ticket]
        _drop(records)
        return bool(records)


def should_alert(key: str, streak: int, threshold: int, now: datetime | None = None) -> bool:
    """Whether the loud alert for `key` goes out now. Normally exactly when the streak REACHES the
    threshold (the caller passes max_rows = threshold + 1 so it cannot re-equal it later). Muted
    while a snooze is running — for ANY streak that reaches the threshold in that time, as the
    person asked for quiet, not for one particular outage. After a snooze has run out, the next
    failure alerts again if the streak is at or above the threshold (and the used-up snooze is
    cleared). A streak below the threshold never alerts — and costs no disk read."""
    if streak < threshold:
        return False
    now = now or datetime.now(timezone.utc)
    with _snooze_lock:
        records = _snoozes(key)
        if not records:
            return streak == threshold
        untils = []
        for r in records:
            try:
                untils.append(datetime.fromisoformat(r["until"]))
            except (KeyError, TypeError, ValueError):
                continue  # a damaged record counts as run out
        if untils and max(untils) > now:
            return False
        _drop(records)
        return True


# --- the card -----------------------------------------------------------------------------------------

def _label(account_id: str, account) -> str:
    return (("📄 " if getattr(account, "page_name", "") else "") + account.display_name) if account else account_id


def create_ticket(account_id: str, action: str, streak: int, message: str, *, target_url: str | None = None) -> dict[str, Any]:
    """The account alert ("N in a row"); `target_url` names the group of the latest failure, if any."""
    from human_bot import telegram_failures
    account = get_all_accounts().get(account_id)
    return failure_tickets.create(
        kind=failure_tickets.STREAK, scope="account", account_id=account_id, action=action, streak=streak, message=message,
        account_label=_label(account_id, account), handled=None, snooze_key=account_key(account_id, action),
        group_label=telegram_failures.group_label(account_id, target_url) if target_url else "",
    )


def create_group_ticket(account_id: str, target_url: str, streak: int, message: str) -> dict[str, Any]:
    """The group alert: this group keeps failing for this account."""
    from human_bot import telegram_failures
    account = get_all_accounts().get(account_id)
    return failure_tickets.create(
        kind=failure_tickets.STREAK, scope="group", account_id=account_id, action="post_to_group", streak=streak,
        message=message, account_label=_label(account_id, account), handled=None, target_url=target_url,
        group_label=telegram_failures.group_label(account_id, target_url), snooze_key=group_key(account_id, target_url),
    )


def _handled_lines(ticket: dict[str, Any]) -> list[str]:
    handled = ticket.get("handled")
    who = ticket.get("resolved_by") or "Ai đó"
    if handled == "snoozed":
        until = ticket.get("snooze_until")
        return [f"🔕 {who} đã tắt tiếng loại cảnh báo này đến {jst_hhmm(until)} JST — hết giờ mà còn lỗi bot sẽ báo lại."]
    if handled in _HANDLED_LINE:
        return [_HANDLED_LINE[handled].format(who=who)]
    return []


def render(ticket: dict[str, Any]) -> str:
    info = failure_info.classify(ticket.get("message"))
    technical = failure_info.technical_line(ticket.get("message") or "", 90)
    if ticket.get("scope") == "group":
        lines = [
            f"🟠 Nhóm \"{ticket.get('group_label')}\" lỗi {ticket.get('streak')} lần liên tiếp — {ticket.get('account_label')}",
            f"Lần gần nhất: {info.cause}",
        ]
        if technical:
            lines.append(f"({technical})")
        lines.append(
            "Có thể tài khoản bị nhóm chặn/hạn chế, bài đang chờ quản trị viên duyệt, hoặc nhóm đổi quyền đăng. "
            "Bot vẫn thử các bài sau theo lịch; muốn ngưng đăng vào nhóm này, sửa hoặc xoá nhóm ở /admin/groups."
        )
        return "\n".join(lines + _handled_lines(ticket))[:1000]
    account = get_all_accounts().get(ticket.get("account_id", ""))
    what = _ACTION_LABEL.get(ticket.get("action", ""), "đăng bài")
    lines = [
        f"🔴 {ticket.get('account_label') or ticket.get('account_id')} · {what} thất bại {ticket.get('streak')} lần LIÊN TIẾP",
        f"Lần gần nhất: {info.cause}",
    ]
    if ticket.get("group_label"):
        lines.append(f"Nhóm gần nhất: {ticket['group_label']}")
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
    return "\n".join(l for l in lines + _handled_lines(ticket) if l)[:1000]


def _snooze_row(tid: str) -> list[dict[str, str]]:
    return [_btn("🔕 Im 1 giờ", f"fa|sn1|{tid}"), _btn("🔕 Im đến 6h sáng", f"fa|snm|{tid}")]


def _unmute_row(tid: str) -> list[dict[str, str]]:
    return [_btn("🔔 Báo lại bình thường", f"fa|un|{tid}")]


def keyboard_for(ticket: dict[str, Any]) -> list[list[dict[str, str]]]:
    tid = ticket["id"]
    muted = ticket.get("handled") == "snoozed"
    if ticket.get("scope") == "group":
        if muted:
            return [_unmute_row(tid)]
        return [] if ticket.get("handled") is not None else [[_btn("👌 Đã biết", f"fa|ok|{tid}")], _snooze_row(tid)]
    account = get_all_accounts().get(ticket.get("account_id", ""))
    if account is None:
        return []
    if account.status == AccountStatus.DISABLED:
        return [[_btn("▶ Bật lại", f"fa|on|{tid}")]]
    if account.status == AccountStatus.PAUSED:
        return [[_btn("▶ Kích hoạt lại (hạ nhiệt)", f"fa|rv|{tid}")]]
    if ticket.get("handled") is not None and not muted:
        return []  # acknowledged / already brought back — nothing left to decide
    rows = [[_btn("⏻ Tắt", f"fa|off|{tid}"), _btn("⚠ Tạm dừng", f"fa|ps|{tid}")]]
    # muting must not take the account choices away, and must be undoable
    return rows + [_unmute_row(tid)] if muted else rows + [[_btn("👌 Đã biết", f"fa|ok|{tid}")], _snooze_row(tid)]


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
    if verb == "bk":
        return _result(ticket)

    def done(handled: str, toast: str, **extra) -> CallbackResult:
        if ticket.get("handled") == "snoozed" and handled != "snoozed" and ticket.get("snooze_key"):
            unsnooze(ticket["snooze_key"], ticket["id"])  # acting on the account ends this card's mute — it must not stay muted unseen
        fields = {"handled": handled, "resolved_by": actor, **extra.pop("fields", {})}
        updated = failure_tickets.update(ticket["id"], **fields) or ticket
        return _result(updated, toast, **extra)

    if verb == "ok":
        return done("ack", "Đã ghi nhận")
    if verb in ("sn1", "snm"):
        key = ticket.get("snooze_key")
        if not key:
            return CallbackResult(toast="Không tắt tiếng được tin này", keyboard=[])
        until = snooze_until("1h" if verb == "sn1" else "morning")
        snooze(key, until, ticket["id"])
        return done("snoozed", f"Đã im đến {jst_hhmm(until.isoformat())} JST", fields={"snooze_until": until.isoformat()})
    if verb == "un":
        if ticket.get("handled") != "snoozed":
            return _result(ticket, "Cảnh báo này không đang bị tắt tiếng")
        if ticket.get("snooze_key"):
            unsnooze(ticket["snooze_key"], ticket["id"])  # only THIS card's mute: a newer card's stays
        updated = failure_tickets.update(ticket["id"], handled=None, resolved_by=None, snooze_until=None) or ticket
        return _result(updated, "Đã bật lại cảnh báo")
    if ticket.get("scope") == "group":
        return CallbackResult(toast="Nút không hợp lệ")  # a group alert has no account buttons
    aid = ticket.get("account_id", "")
    account = get_all_accounts().get(aid)
    if account is None:
        return CallbackResult(toast="Tài khoản này không còn trong hệ thống.", text=render(ticket), keyboard=[], alert=True)
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


# --- sending ---------------------------------------------------------------------------------------------------

async def _deliver(make_ticket, plain: str) -> None:
    """Creates the card and sends it LOUD to every recipient; falls back to the plain text when the
    card cannot be made or reaches nobody — this alert must never be lost, and never doubled."""
    import asyncio

    from human_bot import telegram_notify
    if not telegram_notify.is_configured():
        return
    ticket, refs = None, []
    try:
        ticket = await asyncio.to_thread(make_ticket)
        refs = await telegram_notify.send_ticket(render(ticket), keyboard_for(ticket), silent=False)
    except Exception:  # noqa: BLE001 — an alert must never fail the task it reports on
        logger.exception("could not send the alert card — falling back to the plain alert")
    for ref in refs:
        try:
            await asyncio.to_thread(failure_tickets.add_message, ticket["id"], ref["chat_id"], ref["message_id"], ref["photo"])
        except Exception:  # noqa: BLE001 — the card WAS delivered: a plain alert on top would be a duplicate
            logger.exception("could not remember where the alert %s was sent", ticket["id"])
    if not refs:
        if ticket is not None:
            await asyncio.to_thread(failure_tickets.delete, ticket["id"])  # nobody holds this card — do not leave it behind
        await telegram_notify.send_message(plain, silent=False)


async def send_alert(account_id: str, action: str, streak: int, message: str, *, target_url: str | None = None) -> None:
    """"N failures in a row" for an account."""
    await _deliver(
        lambda: create_ticket(account_id, action, streak, message, target_url=target_url),
        f"🔴 {account_id} · {action} thất bại {streak} lần LIÊN TIẾP\nLần gần nhất: {message}",
    )


async def send_group_alert(account_id: str, target_url: str, streak: int, message: str) -> None:
    """One group keeps failing for this account."""
    await _deliver(
        lambda: create_group_ticket(account_id, target_url, streak, message),
        f"🟠 {account_id} · nhóm {target_url} lỗi {streak} lần liên tiếp\nLần gần nhất: {message}",
    )
