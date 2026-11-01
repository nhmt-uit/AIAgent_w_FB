"""
Purpose of this file / Muc dich cua file nay:
EN: Telegram FAILURE TICKETS (2026-11-01, owner request: "when I receive a
failure message I want to deal with it right in Telegram, not in the admin").

Every failed post/comment the bot reports becomes ONE "card" message that can
be acted on without leaving Telegram:
  - [🔄 Lên lịch lại] — ONE tap, no confirmation: the failed task is re-queued
    at the earliest slot that respects the account's gaps/caps/quiet hours
    (admin._suggest_reschedule_at, the same engine as the admin), and the card
    turns into "✅ Đã lên lịch lại lúc …" with an [↩ Hoàn tác] button. Undo
    puts the task back exactly as it was.
  - [🗑 Bỏ qua] — dismiss.
  - REPLY to the card with new text — the task is re-queued (or, if already
    re-queued and not yet fired, updated) with THAT text instead.
  - When the failure left it UNCERTAIN whether the post is already live
    (Facebook never confirmed after the click) the buttons are [✅ Đã lên rồi —
    bỏ qua] and [🔄 Vẫn lên lịch lại] (the latter asks to confirm) — a blind
    retry could double-post.
  - Failures a retry cannot fix (checkpoint, wrong identity, target post
    gone, code bug) only offer [🗑 Bỏ qua] (and [▶ Bật lại] when the account
    was switched off).

The card is ALWAYS re-rendered from the ticket's state (never "original text +
appended line") so a photo caption stays under Telegram's 1024-char cap and
every recipient's copy can be refreshed to the same truth.

Safety nets before re-queueing: not for a no-retry cause; at most MAX_RETRIES
re-queues per task; the account must be ACTIVE; refuse if the same text was
meanwhile posted successfully to the same target (would double-post); and a
failure older than 48h (24h for comments) needs a confirm tap.
VI: The loi Telegram: nhan nut duoi tin loi de len lich lai (1 cham + hoan tac),
bo qua, hoac tra loi tin bang noi dung moi — khong can vao admin.
"""
from __future__ import annotations

import logging
import threading
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from human_bot import db, failure_info, failure_tickets, schedule_store
from human_bot.config import AccountStatus, get_all_accounts
from human_bot.telegram_alerts import jst_hhmm
from human_bot.telegram_actions import CallbackResult, Item, _btn

logger = logging.getLogger("human_bot.telegram_failures")

# One press / reply at a time: button handlers run in worker threads, and two
# recipients tapping the same card at once must not BOTH re-queue it (a
# failure with no task file would be queued twice). Re-queueing is rare and
# fast, so a single process-wide lock costs nothing.
_action_lock = threading.RLock()

MAX_RETRIES = 2  # re-queues allowed per task from Telegram (3 attempts in all)
STALE_HOURS_POST = 48
STALE_HOURS_COMMENT = 24
LIST_WINDOW_HOURS = 48  # /error shows failures from this far back
UNDO_CUTOFF_SECONDS = 60  # no undo once the re-queued task is due within this long
MAX_LIST_ITEMS = 5
MAX_REPLY_CHARS = 4000
_COMMENT_ACTIONS = {"comment_on_group_post", "comment_on_friend_post"}


# --- building the card ---------------------------------------------------------------

def _parse(iso: str | None) -> datetime | None:
    try:
        dt = datetime.fromisoformat((iso or "").replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)


def parse_iso(iso: str | None) -> datetime | None:
    return _parse(iso)


def _action_label(action: str) -> str:
    if action in _COMMENT_ACTIONS:
        return "Bình luận"
    if action == "post_to_own_profile":
        return "Đăng lên tường cá nhân"
    return "Đăng bài"


def _group_label(account_id: str, target_url: str | None) -> str:
    if not target_url:
        return "(tường cá nhân)"
    try:
        from human_bot.agent import resolve_group_name  # local import — avoid import cycle at module load
        name = resolve_group_name(account_id, target_url)
    except Exception:  # noqa: BLE001 — purely cosmetic
        name = None
    return name or target_url.rstrip("/").rsplit("/", 1)[-1]


group_label = _group_label  # public name for the alerts (human_bot/telegram_streaks.py)


def _subject(source_kind: str | None, job_data: dict | None) -> str:
    title = (job_data or {}).get("title") if isinstance(job_data, dict) else None
    return f'Tin: "{title}"' if source_kind == "job" and title else ""


def ticket_fields_for_failure(
    *, account_id: str, action: str, target_url: str | None, content: str | None, message: str,
    task_id: str | None, log_id: int | None, screenshot: str | None, retries: int,
    source_kind: str | None, job_data: dict | None, source_id: str | None = None,
    media_path: str | None = None, audience: str | None = None,
) -> dict[str, Any]:
    accounts = get_all_accounts()
    account = accounts.get(account_id)
    info = failure_info.classify(message)
    return {
        "kind": "failure", "account_id": account_id, "action": action, "target_url": target_url,
        "content": content or "", "message": message, "task_id": task_id, "log_id": log_id,
        "screenshot": screenshot, "retries": retries, "category": info.code, "safety": info.safety,
        "account_label": (("📄 " if getattr(account, "page_name", "") else "") + account.display_name) if account else account_id,
        "group_label": _group_label(account_id, target_url),
        "subject": _subject(source_kind, job_data), "source_kind": source_kind, "source_id": source_id or "",
        "media_path": media_path, "audience": audience or "public",
        "failed_at": datetime.now(timezone.utc).isoformat(),
    }


_SAFETY_LINE = {
    failure_info.SAFE: "✅ Chưa đăng gì — an toàn để thử lại.",
    failure_info.UNCERTAIN: "⚠️ Chưa rõ bài đã lên chưa — xem ảnh/nhóm trước khi đăng lại để khỏi bị trùng.",
    failure_info.NO_RETRY: "⛔ Thử lại sẽ không giải quyết được — cần xử lý nguyên nhân trước.",
}


def _status_line(ticket: dict[str, Any]) -> str:
    status = ticket.get("status")
    who = f" — bởi {ticket['resolved_by']}" if ticket.get("resolved_by") else ""
    if status == failure_tickets.RESCHEDULED:
        r = ticket.get("resched") or {}
        edited = " với nội dung mới" if r.get("edited") else ""
        return f"✅ Đã lên lịch lại{edited} lúc {jst_hhmm(r.get('at'))} (JST){who}"
    if status == failure_tickets.DISMISSED:
        return f"🗑 Đã bỏ qua{who}"
    if status == failure_tickets.POSTED:
        return f"✅ Đã ghi nhận bài đã lên{who}"
    return ""


def render(ticket: dict[str, Any]) -> str:
    """The card's text, always built from the ticket's current state (≤ ~1000
    chars so it also fits a photo caption)."""
    info = failure_info.classify(ticket.get("message"))
    retries = int(ticket.get("retries") or 0)
    where = f"Nhóm: {ticket.get('group_label')}"
    if ticket.get("subject"):
        where += f" · {ticket['subject']}"
    head = [
        f"❌ {_action_label(ticket.get('action', ''))} thất bại — {ticket.get('account_label')}",
        where,
        f"Nguyên nhân: {info.cause}" + (f" · lần thử {retries + 1}" if retries else ""),
        _SAFETY_LINE[info.safety],
    ]
    if info.repeats_likely and retries:
        head.append("↻ Lỗi kiểu này hay lặp lại — nếu vẫn hỏng, có thể Facebook đã đổi giao diện.")
    tail: list[str] = []
    if ticket.get("status") == failure_tickets.OPEN and info.retryable:
        tail.append("💬 Trả lời tin này bằng nội dung mới để đăng lại với nội dung đó.")
    status_line = _status_line(ticket)
    if status_line:
        tail.append(status_line)
    technical = failure_info.technical_line(ticket.get("message") or "", 90)
    if technical:
        tail.append(f"({technical})")
    room = 960 - len("\n".join(head + tail)) - len("Nội dung: ")
    limit = max(40, min(220, room))
    content = (ticket.get("content") or "").strip().replace("\n", " ")
    preview = content if len(content) <= limit else content[: limit - 1] + "…"
    return "\n".join(head + [f"Nội dung: {preview or '(không có)'}"] + tail)[:1020]


def keyboard_for(ticket: dict[str, Any]) -> list[list[dict[str, str]]]:
    tid = ticket["id"]
    status = ticket.get("status")
    if status == failure_tickets.RESCHEDULED:
        if _rescheduled_task_pending(ticket):
            return [[_btn("↩ Hoàn tác", f"fx|ud|{tid}")]]
        return []
    if status != failure_tickets.OPEN:
        return []
    info = failure_info.classify(ticket.get("message"))
    if info.safety == failure_info.SAFE:
        return [[_btn("🔄 Lên lịch lại", f"fx|rs|{tid}"), _btn("🗑 Bỏ qua", f"fx|sk|{tid}")]]
    if info.safety == failure_info.UNCERTAIN:
        return [
            [_btn("✅ Đã lên rồi — bỏ qua", f"fx|ok|{tid}")],
            [_btn("🔄 Vẫn lên lịch lại", f"fx|fr|{tid}")],
        ]
    return [[_btn("🗑 Bỏ qua", f"fx|sk|{tid}")]]


def _confirm_keyboard(tid: str) -> list[list[dict[str, str]]]:
    return [[_btn("✅ Xác nhận lên lịch lại", f"fx|fc|{tid}"), _btn("↩ Quay lại", f"fx|bk|{tid}")]]


# --- state helpers --------------------------------------------------------------------------

def _rescheduled_task_pending(ticket: dict[str, Any]) -> bool:
    r = ticket.get("resched") or {}
    return bool(r.get("task_id")) and schedule_store.get(r["task_id"]) is not None


rescheduled_task_pending = _rescheduled_task_pending  # public name for the group cards


def _result(ticket: dict[str, Any], toast: str = "", *, keyboard=None) -> CallbackResult:
    return CallbackResult(
        toast=toast, text=render(ticket), keyboard=keyboard if keyboard is not None else keyboard_for(ticket),
        ticket_id=ticket["id"],
    )


def _stale_hours(ticket: dict[str, Any]) -> float:
    failed = _parse(ticket.get("failed_at") or ticket.get("created_at")) or datetime.now(timezone.utc)
    return (datetime.now(timezone.utc) - failed).total_seconds() / 3600


def _stale_limit(ticket: dict[str, Any]) -> int:
    return STALE_HOURS_COMMENT if ticket.get("action") in _COMMENT_ACTIONS else STALE_HOURS_POST


# --- re-queueing ---------------------------------------------------------------------------------

@dataclass
class _Refusal:
    toast: str
    keyboard: list | None = None
    code: str = "other"  # a stable reason, for the bulk flow's "skipped because…" summary


def _blocking_account(ticket: dict[str, Any]):
    """The account that currently keeps this task from running: the task's own if
    it is not ACTIVE, else — for a Page that needs its owner's session — the
    owner. None when nothing blocks it."""
    accounts = get_all_accounts()
    account = accounts.get(ticket.get("account_id", ""))
    if account is None:
        return None
    if account.status != AccountStatus.ACTIVE:
        return account
    if getattr(account, "page_name", "") and getattr(account, "page_session_mode", "") == "owner_session":
        owner = accounts.get(account.owner_account_id)
        if owner is not None and owner.status != AccountStatus.ACTIVE:
            return owner
    return None


def _check_can_requeue(ticket: dict[str, Any], *, check_duplicate: bool) -> _Refusal | None:
    info = failure_info.classify(ticket.get("message"))
    if not info.retryable:
        return _Refusal(f"Không thử lại được: {info.cause}.", code="no_retry")
    if int(ticket.get("retries") or 0) >= MAX_RETRIES:
        return _Refusal(f"Đã thử lại {MAX_RETRIES} lần mà vẫn lỗi — nên kiểm tra tay thay vì thử tiếp.", code="limit")
    if get_all_accounts().get(ticket.get("account_id", "")) is None:
        return _Refusal("Tài khoản này không còn trong hệ thống.", code="missing_account")
    blocker = _blocking_account(ticket)
    if blocker is not None:
        whose = "Tài khoản" if blocker.account_id == ticket.get("account_id") else "Tài khoản cá nhân sở hữu Page"
        if blocker.status == AccountStatus.PAUSED:
            return _Refusal(
                f"{whose} {blocker.account_id} đang TẠM DỪNG. Kích hoạt lại sẽ phải chạy giới hạn thấp vài ngày (hạ nhiệt).",
                [[_btn("▶ Kích hoạt lại (hạ nhiệt)", f"fx|rv|{ticket['id']}")], [_btn("🗑 Bỏ qua", f"fx|sk|{ticket['id']}")]],
                code="blocked",
            )
        return _Refusal(
            f"{whose} {blocker.account_id} đang TẮT. Bật lại rồi bấm Lên lịch lại.",
            [[_btn("▶ Bật lại", f"fx|en|{ticket['id']}")], [_btn("🗑 Bỏ qua", f"fx|sk|{ticket['id']}")]],
            code="blocked",
        )
    if check_duplicate:
        since = ticket.get("failed_at") or ticket.get("created_at") or ""
        done = db.success_logged_after(
            ticket["account_id"], ticket.get("target_url"), ticket.get("content"), since,
            source_id=ticket.get("source_id"), source_kind=ticket.get("source_kind"),
        )
        if done is not None:
            return _Refusal(f"Bài này đã được đăng thành công vào lúc {jst_hhmm(done['created_at'])} — không lên lịch lại để khỏi đăng trùng.", code="duplicate")
    return None


def _requeue(ticket: dict[str, Any], actor: str, *, new_content: str | None = None) -> tuple[dict[str, Any] | None, str | None]:
    """Does the re-queue. Returns (updated ticket, None) or (None, toast)."""
    from human_bot import admin  # local import — admin is heavy and imports a lot
    account = get_all_accounts()[ticket["account_id"]]
    slot = admin._suggest_reschedule_at(account, ticket["action"])
    retries = int(ticket.get("retries") or 0)
    task_id = ticket.get("task_id")
    fields: dict[str, Any] = {
        "scheduled_at": slot.isoformat(), "retries": retries + 1, "last_warning": None,
    }
    if ticket.get("log_id"):
        fields["retry_of_log_id"] = ticket["log_id"]
    prev_content = None
    prev_ai = None
    prev_task_fields: dict[str, Any] = {}
    if new_content is not None:
        fields.update(content=new_content, ai_redraft=False)  # the operator's own words must not be re-drafted by AI
    restored = None
    path = "task"
    if task_id and schedule_store.get_failed(task_id) is not None:
        old = schedule_store.get_failed(task_id)
        prev_content, prev_ai = old.content, old.ai_redraft
        prev_task_fields = {
            "scheduled_at": old.scheduled_at, "retry_of_log_id": old.retry_of_log_id, "last_warning": old.last_warning,
        }
        restored = schedule_store.restore_failed_to_pending(task_id, **fields)
    if restored is None:
        if task_id and schedule_store.get(task_id) is not None:
            return None, "Task này đang nằm trong lịch rồi."
        # No failed task file (a manual run, or it was cleaned up): rebuild from the ticket.
        path = "log"
        row = db.get_action_log(ticket["log_id"]) if ticket.get("log_id") else None
        raw = None
        if row is not None and row["job_data"]:
            import json
            try:
                raw = json.loads(row["job_data"])
            except (TypeError, ValueError):
                raw = None
        kind = ticket.get("source_kind") or (row["source_kind"] if row is not None else None) or ""
        restored = schedule_store.ScheduledTask(
            task_id=schedule_store.new_task_id(slot.isoformat()),
            action=ticket["action"], account_id=ticket["account_id"], scheduled_at=slot.isoformat(),
            content=new_content if new_content is not None else ticket.get("content") or "",
            target_url=ticket.get("target_url"),
            reasoning=f"telegram retry of log #{ticket.get('log_id')}",
            source_kind=kind, source_id=(row["source_id"] if row is not None and row["source_id"] else "") or "",
            job_data=raw if kind == "job" else None, candidate_data=raw if kind == "candidate" else None,
            media_path=ticket.get("media_path"), audience=ticket.get("audience") or "public",
            retry_of_log_id=ticket.get("log_id"), retries=retries + 1,
            # fire-time AI re-drafting only ever applied to side-B job tasks; a hand-typed
            # job ("manual-…") or an edited text keeps its words exactly
            ai_redraft=new_content is None and not str(ticket.get("source_id") or (row["source_id"] if row is not None else "") or "").startswith("manual-"),
        )
        schedule_store.add(restored)
        prev_content = ticket.get("content")
    updated = failure_tickets.update(
        ticket["id"], status=failure_tickets.RESCHEDULED, resolved_by=actor,
        resched={
            "task_id": restored.task_id, "path": path, "at": slot.isoformat(), "prev_retries": retries,
            "prev_content": prev_content, "prev_ai_redraft": prev_ai, "edited": new_content is not None,
            "prev_task_fields": prev_task_fields,
        },
    )
    if updated is None:  # the task IS queued now; only the ticket could not be saved (disk full?)
        return None, "Đã lên lịch lại nhưng không ghi được phiếu lỗi (ổ đĩa đầy?) — kiểm tra /admin/schedule và đừng bấm lại."
    return updated, None


def _reschedule(ticket: dict[str, Any], actor: str, *, confirmed: bool) -> CallbackResult:
    refusal = _check_can_requeue(ticket, check_duplicate=True)
    if refusal is not None:
        return CallbackResult(toast=refusal.toast, text=render(ticket), keyboard=refusal.keyboard or keyboard_for(ticket), ticket_id=ticket["id"], alert=True)
    hours = _stale_hours(ticket)
    if not confirmed and hours > _stale_limit(ticket):
        return CallbackResult(
            alert=True,
            toast=f"Lỗi đã {int(hours)} giờ trước — nội dung có thể đã cũ/hết hạn. Xác nhận nếu vẫn muốn lên lịch lại.",
            keyboard=_confirm_keyboard(ticket["id"]),
        )
    updated, toast = _requeue(ticket, actor)
    if updated is None:
        return CallbackResult(toast=toast or "Không lên lịch lại được.", text=render(ticket), keyboard=keyboard_for(ticket), ticket_id=ticket["id"], alert=True)
    return _result(updated, "Đã lên lịch lại")


def _undo(ticket: dict[str, Any], actor: str) -> CallbackResult:
    r = ticket.get("resched") or {}
    task_id = r.get("task_id")
    if ticket.get("status") != failure_tickets.RESCHEDULED or not task_id:
        return _result(ticket, "Không có gì để hoàn tác")
    pending = schedule_store.get(task_id)
    if pending is None:
        return _result(ticket, "Task đã chạy rồi — không hoàn tác được", keyboard=[])
    due = _parse(pending.scheduled_at)
    if due is not None and due <= datetime.now(timezone.utc) + timedelta(seconds=UNDO_CUTOFF_SECONDS):
        # about to fire or already running: pulling it out now could race a post that is in progress
        return _result(ticket, "Task sắp chạy/đang chạy — không hoàn tác được nữa", keyboard=[])
    if r.get("path") == "task":
        schedule_store.update(
            task_id, retries=r.get("prev_retries", 0), **(r.get("prev_task_fields") or {}),
            **({"content": r["prev_content"]} if r.get("edited") and r.get("prev_content") is not None else {}),
            **({"ai_redraft": r["prev_ai_redraft"]} if r.get("edited") and r.get("prev_ai_redraft") is not None else {}),
        )
        schedule_store.mark_failed(task_id, ticket.get("message") or "failed")
        failed = _parse(ticket.get("failed_at"))
        if failed is not None:
            schedule_store.set_failed_at(task_id, failed)  # keeps its ORIGINAL failure time (the 48h window must not restart)
    else:
        schedule_store.cancel(task_id)
    updated = failure_tickets.update(ticket["id"], status=failure_tickets.OPEN, resched=None, resolved_by=None)
    if updated is None:  # the task is back where it was; only the ticket could not be saved
        return _result(ticket, "Đã hoàn tác nhưng không ghi được phiếu lỗi — kiểm tra ổ đĩa", keyboard=[])
    return _result(updated, f"Đã hoàn tác — bởi {actor}")


def _dismiss(ticket: dict[str, Any], actor: str, *, posted: bool) -> CallbackResult:
    if posted and ticket.get("task_id") and schedule_store.get_failed(ticket["task_id"]) is not None:
        schedule_store.mark_posted(
            ticket["task_id"], "Xác nhận thủ công qua Telegram: bài đã lên", source_dir=schedule_store.FAILED_DIR,
        )
    updated = failure_tickets.update(
        ticket["id"], status=failure_tickets.POSTED if posted else failure_tickets.DISMISSED, resolved_by=actor,
    )
    if updated is None:
        return _result(ticket, "Không ghi được phiếu lỗi — kiểm tra ổ đĩa", keyboard=[])
    return _result(updated, "Đã ghi nhận" if posted else "Đã bỏ qua")


def _enable_account(ticket: dict[str, Any], actor: str) -> CallbackResult:
    from human_bot.runtime_config import set_account_disabled
    blocker = _blocking_account(ticket)
    if blocker is None or blocker.status != AccountStatus.DISABLED:
        return _result(ticket, "Không có tài khoản nào đang tắt để bật")
    set_account_disabled(blocker.account_id, False)
    return _result(ticket, f"Đã bật lại {blocker.account_id} — bấm Lên lịch lại")


def _resume_account(ticket: dict[str, Any], actor: str) -> CallbackResult:
    from human_bot.runtime_config import resume_account
    blocker = _blocking_account(ticket)
    if blocker is None or blocker.status != AccountStatus.PAUSED:
        return _result(ticket, "Không có tài khoản nào đang tạm dừng")
    resume_account(blocker.account_id)  # with the reduced-limit cooldown, exactly like the admin's "Kích hoạt lại"
    return _result(ticket, f"Đã kích hoạt lại {blocker.account_id} (đang hạ nhiệt) — bấm Lên lịch lại")


# --- for the group cards (human_bot/telegram_batches.py) ----------------------------------------------
# These do ONE ticket of a bulk action. The caller holds action_lock() around the whole loop.

def action_lock() -> threading.RLock:
    return _action_lock


def requeue_for_bulk(ticket: dict[str, Any], actor: str) -> tuple[dict[str, Any] | None, str]:
    """Re-queues one failure as part of "Lên lịch lại tất cả". Stricter than the single
    tap: ONLY a failure known to have happened before anything was submitted (safe)
    is re-queued in bulk — a blind bulk retry of an uncertain one could double-post —
    and a stale one is skipped instead of asking for a confirmation per item.
    Also skipped: a cause that tends to fail the same way again (the one-tap card still offers it).
    Returns (updated ticket, "") or (None, reason code)."""
    info = failure_info.classify(ticket.get("message"))
    if info.safety != failure_info.SAFE:
        return None, "uncertain" if info.retryable else "no_retry"
    if info.repeats_likely:
        return None, "repeats"  # e.g. Facebook changed its page: ten blind retries would just fail ten more times
    refusal = _check_can_requeue(ticket, check_duplicate=True)
    if refusal is not None:
        return None, refusal.code
    if _stale_hours(ticket) > _stale_limit(ticket):
        return None, "stale"
    updated, _toast = _requeue(ticket, actor)
    return (updated, "") if updated is not None else (None, "error")


def undo_requeue(ticket: dict[str, Any], actor: str) -> dict[str, Any]:
    """Puts a re-queued failure back (the card's [↩ Hoàn tác]); the ticket as it is afterwards."""
    _undo(ticket, actor)
    return failure_tickets.get(ticket["id"]) or ticket


def dismiss_ticket(ticket: dict[str, Any], actor: str) -> dict[str, Any]:
    _dismiss(ticket, actor, posted=False)
    return failure_tickets.get(ticket["id"]) or ticket


def handle_callback(rest: str, actor: str) -> CallbackResult:
    """`rest` = "<verb>|<ticket_id>" (the part after "fx|")."""
    with _action_lock:
        return _handle_callback_locked(rest, actor)


def _handle_callback_locked(rest: str, actor: str) -> CallbackResult:
    verb, _, ticket_id = rest.partition("|")
    ticket = failure_tickets.get(ticket_id)
    if ticket is None:
        return CallbackResult(toast="Phiếu lỗi này không còn (đã quá cũ hoặc bị xoá)", keyboard=[])
    status = ticket.get("status")
    if verb == "ud":
        return _undo(ticket, actor)
    if verb == "bk":
        return _result(ticket, "")
    if status != failure_tickets.OPEN:
        # someone else (another recipient) already handled it — show the truth, drop stale buttons
        return _result(ticket, "Đã được xử lý rồi")
    if verb == "rs" and failure_info.classify(ticket.get("message")).safety != failure_info.UNCERTAIN:
        return _reschedule(ticket, actor, confirmed=False)
    if verb in ("rs", "fr"):  # "rs" on an uncertain failure (a forged/stale button) must still ask first
        refusal = _check_can_requeue(ticket, check_duplicate=False)
        if refusal is not None:
            return CallbackResult(toast=refusal.toast, text=render(ticket), keyboard=refusal.keyboard or keyboard_for(ticket), ticket_id=ticket["id"], alert=True)
        return CallbackResult(
            alert=True,
            toast="Bài cũ có thể ĐÃ lên rồi — xác nhận để vẫn lên lịch lại (có thể bị trùng).",
            keyboard=_confirm_keyboard(ticket["id"]),
        )
    if verb == "fc":
        return _reschedule(ticket, actor, confirmed=True)
    if verb == "sk":
        return _dismiss(ticket, actor, posted=False)
    if verb == "ok":
        return _dismiss(ticket, actor, posted=True)
    if verb == "en":
        return _enable_account(ticket, actor)
    if verb == "rv":
        return CallbackResult(
            alert=True,
            toast="Kích hoạt lại tài khoản đã tạm dừng vì nghi vấn đề: nó sẽ chạy giới hạn thấp vài ngày. Xác nhận?",
            keyboard=[[_btn("✅ Xác nhận kích hoạt lại", f"fx|rc|{ticket['id']}"), _btn("↩ Quay lại", f"fx|bk|{ticket['id']}")]],
        )
    if verb == "rc":
        return _resume_account(ticket, actor)
    return CallbackResult(toast="Nút không hợp lệ")


# --- reply-to-edit ---------------------------------------------------------------------------------

@dataclass
class ReplyOutcome:
    ticket_id: str | None
    message: str  # what to say back to the person who replied
    keyboard: list | None = None  # [↩ Hoàn tác] when the reply changed something


def _preview(text: str, limit: int = 300) -> str:
    text = text.strip()
    return text if len(text) <= limit else text[:limit] + "…"


def apply_reply(ticket: dict[str, Any], new_text: str, actor: str) -> ReplyOutcome:
    """The operator replied to a card with replacement text. Open ticket → re-queue
    with that text; already re-queued and not yet fired → swap the text in the
    queued task. Anything else is explained."""
    kind = ticket.get("kind", failure_tickets.FAILURE)
    if kind == failure_tickets.BATCH:
        return ReplyOutcome(None, "Đây là thẻ tổng hợp nhiều lỗi — gõ /error rồi trả lời vào thẻ của TỪNG lỗi để đổi nội dung.")
    if kind != failure_tickets.FAILURE:
        return ReplyOutcome(None, "Đây là cảnh báo lỗi liên tiếp của một tài khoản, không có nội dung bài để đổi.")
    with _action_lock:
        ticket = failure_tickets.get(ticket["id"]) or ticket  # the state NOW, not when the reply arrived
        return _apply_reply_locked(ticket, new_text, actor)


def _apply_reply_locked(ticket: dict[str, Any], new_text: str, actor: str) -> ReplyOutcome:
    text = (new_text or "").strip()
    if not text:
        return ReplyOutcome(None, "Nội dung trả lời đang trống.")
    if len(text) > MAX_REPLY_CHARS:
        return ReplyOutcome(None, f"Nội dung dài {len(text)} ký tự — tối đa {MAX_REPLY_CHARS}.")
    status = ticket.get("status")
    if status == failure_tickets.RESCHEDULED:
        r = ticket.get("resched") or {}
        task = schedule_store.get(r.get("task_id") or "")
        if task is None:
            return ReplyOutcome(ticket["id"], "Bài đã chạy rồi nên không đổi nội dung được nữa.")
        resched = dict(r)
        if not resched.get("edited"):
            resched.update(prev_content=task.content, prev_ai_redraft=task.ai_redraft, edited=True)
        schedule_store.update(task.task_id, content=text, ai_redraft=False)
        failure_tickets.update(ticket["id"], resched=resched, resolved_by=actor)
        return ReplyOutcome(
            ticket["id"],
            f"✏️ Đã đổi nội dung bài đang chờ (đăng lúc {jst_hhmm(r.get('at'))} JST). Nội dung mới:\n“{_preview(text)}”",
            [[_btn("↩ Hoàn tác", f"fx|ud|{ticket['id']}")]],
        )
    if status != failure_tickets.OPEN:
        return ReplyOutcome(ticket["id"], "Phiếu lỗi này đã được xử lý — không còn đổi nội dung được.")
    refusal = _check_can_requeue(ticket, check_duplicate=False)
    if refusal is not None:
        return ReplyOutcome(ticket["id"], refusal.toast)
    updated, toast = _requeue(ticket, actor, new_content=text)
    if updated is None:
        return ReplyOutcome(ticket["id"], toast or "Không lên lịch lại được.")
    extra = ""
    if failure_info.classify(ticket.get("message")).safety == failure_info.UNCERTAIN:
        extra = "\n⚠️ Bài cũ có thể đã lên — hãy kiểm tra nhóm để tránh trùng."
    return ReplyOutcome(
        ticket["id"],
        f"✏️ Đã lên lịch lại lúc {jst_hhmm((updated.get('resched') or {}).get('at'))} (JST) với nội dung mới:\n“{_preview(text)}”{extra}",
        [[_btn("↩ Hoàn tác", f"fx|ud|{ticket['id']}")]],
    )


# --- listing (/error) ----------------------------------------------------------------------------------

def _ticket_for_failed_task(task: schedule_store.ScheduledTask, index: dict[str, dict[str, Any]]) -> dict[str, Any]:
    existing = index.get(task.task_id)
    if existing is not None:
        failed = schedule_store.failed_at(task.task_id)
        # A ticket already handled (re-queued...) but the task is in failed/ AGAIN with a
        # later failure than the ticket's last update → this is a new failure needing its own card.
        newer = failed is not None and (_parse(existing.get("updated_at")) or failed) + timedelta(seconds=5) < failed
        if existing.get("status") == failure_tickets.OPEN or not newer:
            return existing
    reason = schedule_store.get_failed_reason(task.task_id) or ""
    failed = schedule_store.failed_at(task.task_id)
    fields = ticket_fields_for_failure(
        account_id=task.account_id, action=task.action, target_url=task.target_url, content=task.content,
        message=reason, task_id=task.task_id, log_id=None, screenshot=None, retries=task.retries,
        source_kind=task.source_kind, job_data=task.job_data, source_id=task.source_id,
    )
    if failed is not None:
        fields["failed_at"] = failed.isoformat()
    ticket = failure_tickets.create(**fields)
    index[task.task_id] = ticket
    return ticket


def open_failures(now: datetime | None = None) -> list[dict[str, Any]]:
    """Failures from the last LIST_WINDOW_HOURS still waiting for a decision:
    open tickets + failed task files that have no ticket yet (made on the fly).
    Newest first."""
    now = now or datetime.now(timezone.utc)
    since = now - timedelta(hours=LIST_WINDOW_HOURS)
    index = failure_tickets.task_index()  # ONE read of the ticket store for the whole listing
    out: dict[str, dict[str, Any]] = {}
    for task in schedule_store.list_failed(since=since):
        ticket = _ticket_for_failed_task(task, index)
        if ticket.get("status") == failure_tickets.OPEN:
            out[ticket["id"]] = ticket
    for ticket in failure_tickets.list_open(since=since):
        tid = ticket.get("task_id")
        if tid and schedule_store.get_failed(tid) is None:
            # The failed file is gone. It may be IN FLIGHT (the card goes out inside run_task(),
            # a moment before the scheduler moves the task into failed/) — only treat the ticket
            # as stale once it is not brand new.
            fresh = (_parse(ticket.get("created_at")) or now) > now - timedelta(minutes=2)
            if not fresh:  # re-queued/cancelled elsewhere (e.g. in the admin) — the ticket is stale
                failure_tickets.update(ticket["id"], status=failure_tickets.DISMISSED, resolved_by="hệ thống")
            continue  # fresh: in flight — neither listed nor dismissed yet
        out.setdefault(ticket["id"], ticket)
    return sorted(out.values(), key=lambda t: t.get("failed_at") or t.get("created_at") or "", reverse=True)


def open_failure_count() -> int:
    try:
        return len(open_failures())
    except Exception:  # noqa: BLE001 — a count in a footer must never break the message
        logger.exception("open_failure_count failed")
        return 0


def build_list(
    now: datetime | None = None, tickets: list[dict[str, Any]] | None = None,
) -> tuple[list[tuple[dict[str, Any], str, list, str | None]], int]:
    """For /error: ((ticket, card text, keyboard, screenshot path) for up to
    MAX_LIST_ITEMS open failures, how many more there are). `tickets` = the open
    failures when the caller already computed them (open_failures())."""
    if tickets is None:
        tickets = open_failures(now)
    items = [(t, render(t), keyboard_for(t), t.get("screenshot")) for t in tickets[:MAX_LIST_ITEMS]]
    return items, max(0, len(tickets) - MAX_LIST_ITEMS)


async def sync_copies(ticket_id: str, *, skip: tuple[str, Any] | None = None) -> int:
    """Re-renders the card in EVERY chat that holds a copy of it (except `skip`,
    the message that was just edited by the caller), so once one recipient has
    acted nobody else is left with stale buttons. Best-effort; returns how many
    copies were actually updated."""
    from human_bot import telegram_notify
    ticket = failure_tickets.get(ticket_id)
    if ticket is None:
        return 0
    kind = ticket.get("kind", failure_tickets.FAILURE)
    if kind == failure_tickets.BATCH:
        from human_bot import telegram_batches  # local import — it imports this module
        text, keyboard = telegram_batches.card(ticket)
    elif kind == failure_tickets.STREAK:
        from human_bot import telegram_streaks
        text, keyboard = telegram_streaks.render(ticket), telegram_streaks.keyboard_for(ticket)
    else:
        text, keyboard = render(ticket), keyboard_for(ticket)
    updated = 0
    for m in ticket.get("messages", []):
        if skip is not None and (m.get("chat_id"), m.get("message_id")) == (str(skip[0]), skip[1]):
            continue
        try:
            if await telegram_notify.edit_message(m["chat_id"], m["message_id"], text=text, keyboard=keyboard, photo=bool(m.get("photo"))):
                updated += 1
        except Exception:  # noqa: BLE001 — a stale copy must not break the others
            logger.exception("sync_copies: could not refresh %s/%s", m.get("chat_id"), m.get("message_id"))
    return updated


async def sync_with_groups(ticket_id: str, *, skip: tuple[str, Any] | None = None) -> None:
    """sync_copies() for a failure AND for every group card it is a member of (their counts and
    buttons change when one member does)."""
    await sync_copies(ticket_id, skip=skip)
    for batch in failure_tickets.batches_containing(ticket_id):
        if batch.get("messages"):
            await sync_copies(batch["id"])


async def sync_changed(ticket_ids: list[str], *, exclude: tuple[str, ...] = ()) -> None:
    """After a group card acted on several failures: refresh the cards of the members that have
    one, and every OTHER group card holding any of them — each exactly once (`exclude` = the group
    card the caller has just edited itself)."""
    members = failure_tickets.get_many(list(ticket_ids))
    for member in members:
        if member.get("messages"):
            await sync_copies(member["id"])
    for batch in failure_tickets.batches_containing(ticket_ids):
        if batch["id"] not in exclude and batch.get("messages"):
            await sync_copies(batch["id"])


def empty_list_item() -> Item:
    return Item(f"✅ Không có lỗi nào đang chờ xử lý trong {LIST_WINDOW_HOURS} giờ qua.")
