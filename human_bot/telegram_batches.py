"""
Purpose of this file / Muc dich cua file nay:
EN: ONE Telegram card for SEVERAL failures (2026-11-01, failure tickets phase 2).
The data showed why: 56% of the real failures were "no network / browser died",
and those arrive in bursts — an outage turns ten scheduled posts into ten cards,
each needing its own tap. Two kinds of group card ("batch" tickets):

  - burst — when BURST_MIN open SAFE failures of the SAME cause land within
    BURST_WINDOW, the third and later ones do not get a card of their own: one
    group card is sent (later failures of that cause are folded into it and the
    card is edited in place, so the chat is not flooded). Cards already sent
    for the first two stay where they are and stay in sync. Only SAFE failures
    are grouped (nothing was posted, so a card per failure adds nothing but
    noise): an "uncertain" one needs its own screenshot to check whether the
    post is live, and a failure that retrying cannot fix needs its own look.
  - list — /error opens with one when LIST_MIN or more safe failures are waiting.

Buttons: [🔄 Lên lịch lại tất cả (N)] re-queues every SAFE member in one tap
(each at its own free slot — the same engine as a single tap, one after the
other so they do not pile onto one slot), with [↩ Hoàn tác] for the whole batch;
[🗑 Bỏ qua tất cả] asks to confirm first. Bulk is STRICTER than a single tap: a
stale failure or one that hit the retry cap is skipped and counted — those stay
open for /error — and nothing "uncertain" is ever re-queued blindly.

The card is always rendered from its members' live state (like the single card),
so it stays true when members are handled one by one elsewhere (the service
refreshes the group cards of a member whenever the member changes).
VI: The gop nhieu loi: loi AN TOAN cung nguyen nhan dan dap -> 1 the, nut "Len lich lai
tat ca" + hoan tac; "Bo qua tat ca" can xac nhan.
"""
from __future__ import annotations

import asyncio
import logging
import threading
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any

from human_bot import failure_info, failure_tickets, telegram_failures
from human_bot.telegram_actions import CallbackResult, _btn
from human_bot.telegram_alerts import jst_hhmm

logger = logging.getLogger("human_bot.telegram_batches")

BURST_WINDOW = timedelta(minutes=15)  # failures this close together, with one cause, are one burst
BURST_MIN = 3  # open failures of one cause within the window that make a burst
LIST_MIN = 3  # safe failures waiting that make /error open with a "reschedule all" card
MAX_SHOWN = 4  # accounts / causes named on the card before "…"

# Held while a burst is started/joined AND while a group card's status is recomputed: two failures
# landing together must not both start a burst, and a status must not be derived from a member
# list that a joining failure is changing at that moment.
_burst_lock = threading.RLock()

_SKIP_REASON = {
    "uncertain": "chưa rõ bài đã lên chưa",
    "no_retry": "thử lại không giải quyết được",
    "limit": f"đã thử lại {telegram_failures.MAX_RETRIES} lần",
    "stale": "lỗi đã quá cũ",
    "repeats": "lỗi hay lặp lại (Facebook có thể đã đổi giao diện)",
    "blocked": "tài khoản đang tắt/tạm dừng",
    "duplicate": "bài đã đăng thành công",
    "missing_account": "tài khoản không còn",
    "error": "không lên lịch lại được",
    "other": "không lên lịch lại được",
}


def _parse(iso: str | None) -> datetime | None:
    return telegram_failures.parse_iso(iso)


def _failed_at(ticket: dict[str, Any]) -> datetime | None:
    return _parse(ticket.get("failed_at") or ticket.get("created_at"))


def _safety(ticket: dict[str, Any]) -> str:
    return failure_info.classify(ticket.get("message")).safety


def _bulk_ok(ticket: dict[str, Any]) -> bool:
    """Eligible for "Lên lịch lại tất cả": nothing was posted AND a retry is not expected to fail the same way."""
    info = failure_info.classify(ticket.get("message"))
    return info.safety == failure_info.SAFE and not info.repeats_likely


def members_of(batch: dict[str, Any]) -> list[dict[str, Any]]:
    """The members that still exist, in the order they joined — ONE read of the store."""
    return failure_tickets.get_many(list(batch.get("members") or []))


# --- joining a burst (called when a failure ticket has just been created) ---------------------------

def _active_burst(category: str, now: datetime) -> dict[str, Any] | None:
    for batch in failure_tickets.list_open(kind=failure_tickets.BATCH):
        if batch.get("scope") != "burst" or batch.get("category") != category:
            continue
        last = _parse(batch.get("last_member_at"))
        if last is None or abs(now - last) > BURST_WINDOW:
            continue
        if any(m.get("status") == failure_tickets.OPEN for m in members_of(batch)):
            return batch
    return None


def attach(ticket: dict[str, Any]) -> tuple[dict[str, Any] | None, bool]:
    """Called right after a FAILURE ticket was created. Returns (group card, is it new) when
    this failure belongs to a burst — the caller then shows the group card INSTEAD of a card
    of its own — else (None, False). Only a SAFE failure is ever grouped."""
    category = ticket.get("category")
    if not category or ticket.get("kind", failure_tickets.FAILURE) != failure_tickets.FAILURE:
        return None, False
    if _safety(ticket) != failure_info.SAFE:
        return None, False
    now = _failed_at(ticket) or datetime.now(timezone.utc)
    with _burst_lock:
        burst = _active_burst(category, now)
        if burst is not None:
            members = list(burst.get("members") or []) + [ticket["id"]]
            return failure_tickets.update(burst["id"], members=members, last_member_at=now.isoformat()), False
        grouped = {  # already in an open burst (one whose window has lapsed) — never in two group cards
            member for batch in failure_tickets.list_open(kind=failure_tickets.BATCH)
            if batch.get("scope") == "burst" for member in batch.get("members") or []
        }
        recent = [
            t for t in failure_tickets.list_open(kind=failure_tickets.FAILURE)
            if t["id"] != ticket["id"] and t.get("category") == category and t["id"] not in grouped
            and abs((_failed_at(t) or now) - now) <= BURST_WINDOW
        ]
        if len(recent) + 1 < BURST_MIN:
            return None, False
        recent.sort(key=lambda t: t.get("failed_at") or t.get("created_at") or "")
        burst = failure_tickets.create(
            kind=failure_tickets.BATCH, scope="burst", category=category,
            members=[t["id"] for t in recent] + [ticket["id"]], last_member_at=now.isoformat(),
            last_resched=None, last_dismiss=None,
        )
        return burst, True


def build_list_batch(tickets: list[dict[str, Any]] | None = None) -> dict[str, Any] | None:
    """The "reschedule all" card /error opens with: every SAFE open failure of the last 48 h
    (`tickets` = the open failures if the caller already has them). None when fewer than
    LIST_MIN are waiting (then single cards are enough)."""
    if tickets is None:
        tickets = telegram_failures.open_failures()
    safe = [t for t in tickets if _bulk_ok(t)]
    if len(safe) < LIST_MIN:
        return None
    safe.sort(key=lambda t: t.get("failed_at") or t.get("created_at") or "")
    return failure_tickets.create(
        kind=failure_tickets.BATCH, scope="list", category=None, members=[t["id"] for t in safe],
        last_resched=None, last_dismiss=None,
    )


async def announce(batch: dict[str, Any], is_new: bool) -> bool:
    """Puts the group card in front of the recipients: a new one is sent, an existing one is
    edited in place (silently — per-attempt reports are always silent). True when somebody has it."""
    from human_bot import telegram_notify  # local import — as telegram_failures does
    if is_new or not batch.get("messages"):
        text, keyboard = card(batch)
        refs = await telegram_notify.send_ticket(text, keyboard, silent=True)
        for ref in refs:
            try:
                await asyncio.to_thread(failure_tickets.add_message, batch["id"], ref["chat_id"], ref["message_id"], ref["photo"])
            except Exception:  # noqa: BLE001 — it was DELIVERED; failing to remember where only loses later edits
                logger.exception("could not remember where group card %s was sent", batch["id"])
        return bool(refs)
    # True only if at least one copy was really updated — else nobody saw this failure, and the caller
    # gives it a card of its own
    return await telegram_failures.sync_copies(batch["id"]) > 0


# --- the card ----------------------------------------------------------------------------------------------

def _counts(items: list[str], limit: int = MAX_SHOWN) -> str:
    shown = Counter(items).most_common()
    text = " · ".join(f"{name} ×{n}" if n > 1 else name for name, n in shown[:limit])
    return text + (f" · +{len(shown) - limit} khác" if len(shown) > limit else "")


def _undoable(batch: dict[str, Any], members: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """The members the last bulk re-queue put back in the schedule and that can still be pulled out."""
    ids = set((batch.get("last_resched") or {}).get("ids") or [])
    return [
        m for m in members
        if m["id"] in ids and m.get("status") == failure_tickets.RESCHEDULED and telegram_failures.rescheduled_task_pending(m)
    ]


def _action_lines(batch: dict[str, Any]) -> list[str]:
    lines: list[str] = []
    resched = batch.get("last_resched") or {}
    if resched:
        who = f" — {resched['by']}" if resched.get("by") else ""
        span = ""
        if resched.get("first_at"):
            first, last = jst_hhmm(resched["first_at"]), jst_hhmm(resched.get("last_at") or resched["first_at"])
            span = f" ({first} → {last} JST)" if last != first else f" (lúc {first} JST)"
        lines.append(f"🔄 Đã lên lịch lại {len(resched.get('ids') or [])} lỗi{span}{who}")
        if resched.get("skipped"):
            why = ", ".join(f"{_SKIP_REASON.get(k, k)} ×{v}" for k, v in resched["skipped"].items())
            lines.append(f"⏭ Chưa lên lịch lại {sum(resched['skipped'].values())}: {why} — xem từng lỗi ở /error")
    dismiss = batch.get("last_dismiss") or {}
    if dismiss:
        who = f" — {dismiss['by']}" if dismiss.get("by") else ""
        lines.append(f"🗑 Đã bỏ qua {dismiss.get('count', 0)} lỗi{who}")
    return lines


def card(batch: dict[str, Any]) -> tuple[str, list[list[dict[str, str]]]]:
    """(text, buttons) from ONE read of the members."""
    members = members_of(batch)
    return _render(batch, members), _keyboard(batch, members)


def render(batch: dict[str, Any]) -> str:
    return card(batch)[0]


def keyboard_for(batch: dict[str, Any]) -> list[list[dict[str, str]]]:
    return card(batch)[1]


def _render(batch: dict[str, Any], members: list[dict[str, Any]]) -> str:
    if not members:
        return "Các lỗi trong thẻ này không còn nữa."
    open_ = [m for m in members if m.get("status") == failure_tickets.OPEN]
    rescheduled = [m for m in members if m.get("status") == failure_tickets.RESCHEDULED]
    closed = len(members) - len(open_) - len(rescheduled)
    causes = [failure_info.classify(m.get("message")).cause for m in members]
    if batch.get("scope") == "list":
        head = f"📋 {len(members)} lỗi an toàn đang chờ thử lại"
    else:
        head = f"⚠️ {len(members)} lỗi " + ("cùng nguyên nhân" if len(set(causes)) == 1 else "dồn dập")
    lines = [head, f"Nguyên nhân: {_counts(causes)}"]
    if open_:
        if not all(_safety(m) == failure_info.SAFE for m in open_):
            lines.append("⚠️ Có lỗi chưa rõ bài đã lên chưa — chỉ lỗi an toàn mới được thử lại hàng loạt.")
        else:
            lines.append("✅ Chưa đăng gì — an toàn để thử lại.")
        if any(failure_info.classify(m.get("message")).repeats_likely for m in open_):
            lines.append("↻ Lỗi kiểu này hay lặp lại (Facebook có thể đã đổi giao diện): không thử lại hàng loạt — thử từng lỗi ở /error.")
    lines.append(f"Tài khoản: {_counts([m.get('account_label') or m.get('account_id') or '?' for m in members])}")
    times = sorted(t for t in (_failed_at(m) for m in members) if t is not None)
    if times:
        first, last = jst_hhmm(times[0].isoformat()), jst_hhmm(times[-1].isoformat())
        lines.append(f"Lúc: {first} → {last} (JST)" if first != last else f"Lúc: {first} (JST)")
    lines.append(f"Còn chờ: {len(open_)} · đã lên lịch lại: {len(rescheduled)} · đã bỏ qua/ghi nhận: {closed}")
    lines.extend(_action_lines(batch))
    if open_:
        lines.append("💬 Gõ /error để xem và xử lý từng lỗi.")
    return "\n".join(lines)[:4000]


def _keyboard(batch: dict[str, Any], members: list[dict[str, Any]]) -> list[list[dict[str, str]]]:
    bid = batch["id"]
    open_ = [m for m in members if m.get("status") == failure_tickets.OPEN]
    rows: list[list[dict[str, str]]] = []
    if open_:
        row = []
        eligible = sum(1 for m in open_ if _bulk_ok(m))
        if eligible:
            row.append(_btn(f"🔄 Lên lịch lại tất cả ({eligible})", f"fb|ra|{bid}"))
        row.append(_btn(f"🗑 Bỏ qua tất cả ({len(open_)})", f"fb|sa|{bid}"))
        rows.append(row)
    undo = _undoable(batch, members)
    if undo:
        rows.append([_btn(f"↩ Hoàn tác ({len(undo)})", f"fb|ua|{bid}")])
    return rows


# --- button presses ----------------------------------------------------------------------------------------------

def _refresh_status(batch_id: str) -> dict[str, Any]:
    """OPEN while any member is still open, else DONE. Under _burst_lock: a failure joining the
    burst right now must not be missed (a DONE burst cannot be joined)."""
    with _burst_lock:
        batch = failure_tickets.get(batch_id) or {}
        has_open = any(m.get("status") == failure_tickets.OPEN for m in members_of(batch))
        return failure_tickets.update(batch_id, status=failure_tickets.OPEN if has_open else failure_tickets.DONE) or batch


def _result(batch: dict[str, Any], toast: str = "", *, changed: list[str] | tuple[str, ...] = (), alert: bool = False) -> CallbackResult:
    text, keyboard = card(batch)
    return CallbackResult(toast=toast, text=text, keyboard=keyboard, ticket_id=batch["id"], also_sync=tuple(changed), alert=alert)


def handle_callback(rest: str, actor: str) -> CallbackResult:
    """`rest` = "<verb>|<batch id>" (the part after "fb|")."""
    with telegram_failures.action_lock():
        return _handle_locked(rest, actor)


def _handle_locked(rest: str, actor: str) -> CallbackResult:
    verb, _, batch_id = rest.partition("|")
    batch_id, _, arg = batch_id.partition("|")  # "fb|sc|<id>|<how many the person was asked about>"
    batch = failure_tickets.get(batch_id)
    if batch is None or batch.get("kind") != failure_tickets.BATCH:
        return CallbackResult(toast="Thẻ này không còn (đã quá cũ hoặc bị xoá)", keyboard=[])
    if verb == "bk":
        return _result(batch)
    if verb == "ra":
        return _reschedule_all(batch, actor)
    if verb == "sa":
        n = sum(1 for m in members_of(batch) if m.get("status") == failure_tickets.OPEN)
        if not n:
            return _result(batch, "Không còn lỗi nào đang chờ")
        return CallbackResult(
            alert=True,
            toast=f"Bỏ qua {n} lỗi đang chờ? Bài không bị xoá, chỉ không nhắc nữa. Xác nhận?",
            keyboard=[[_btn(f"✅ Xác nhận bỏ qua {n} lỗi", f"fb|sc|{batch_id}|{n}"), _btn("↩ Quay lại", f"fb|bk|{batch_id}")]],
        )
    if verb == "sc":
        return _dismiss_all(batch, actor, expected=int(arg) if arg.isdigit() else None)
    if verb == "ua":
        return _undo_all(batch, actor)
    return CallbackResult(toast="Nút không hợp lệ")


def _reschedule_all(batch: dict[str, Any], actor: str) -> CallbackResult:
    members = members_of(batch)
    done: list[dict[str, Any]] = []
    skipped: Counter[str] = Counter()
    for member in members:  # oldest first, so the oldest gets the earliest slot
        if member.get("status") != failure_tickets.OPEN:
            continue
        try:
            updated, reason = telegram_failures.requeue_for_bulk(member, actor)
        except Exception:  # noqa: BLE001 — one bad member must not stop the others
            logger.exception("batch %s: could not re-queue %s", batch["id"], member.get("id"))
            updated, reason = None, "error"
        if updated is None:
            skipped[reason] += 1
        else:
            done.append(updated)
    if not done:
        # Nothing happened: leave the card (and any earlier undo record) exactly as it was and just explain.
        if not skipped:
            return _result(batch, "Không còn lỗi nào đang chờ")
        why = ", ".join(f"{_SKIP_REASON.get(k, k)} ×{v}" for k, v in skipped.items())
        return _result(batch, f"Chưa làm được {sum(skipped.values())} lỗi: {why}. Xem từng lỗi ở /error.", alert=True)
    previous = batch.get("last_resched") or {}
    still_queued = _undoable(batch, members)  # an earlier bulk's tasks that are still in the schedule stay undoable
    slots = sorted(filter(None, [(u.get("resched") or {}).get("at") for u in done] + (
        [previous.get("first_at"), previous.get("last_at")] if still_queued else [])))
    batch = failure_tickets.update(
        batch["id"],
        last_resched={
            "by": actor, "at": datetime.now(timezone.utc).isoformat(), "skipped": dict(skipped),
            "ids": [m["id"] for m in still_queued] + [u["id"] for u in done], "first_at": slots[0], "last_at": slots[-1],
        },
    ) or batch
    batch = _refresh_status(batch["id"])
    toast = f"Đã lên lịch lại {len(done)} lỗi" + (f", chưa làm được {sum(skipped.values())} (xem thẻ)" if skipped else "")
    return _result(batch, toast, changed=[u["id"] for u in done])


def _dismiss_all(batch: dict[str, Any], actor: str, expected: int | None = None) -> CallbackResult:
    open_ = [m for m in members_of(batch) if m.get("status") == failure_tickets.OPEN]
    if expected is not None and len(open_) != expected and open_:
        # the list changed between the question and the answer (a failure joined, or one was handled):
        # never dismiss what the person was not asked about — ask again with the real number
        return CallbackResult(
            alert=True,
            toast=f"Danh sách vừa thay đổi: nay có {len(open_)} lỗi đang chờ (lúc hỏi là {expected}). Xác nhận lại để bỏ qua {len(open_)} lỗi.",
            keyboard=[[_btn(f"✅ Xác nhận bỏ qua {len(open_)} lỗi", f"fb|sc|{batch['id']}|{len(open_)}"), _btn("↩ Quay lại", f"fb|bk|{batch['id']}")]],
        )
    changed = []
    for member in open_:
        telegram_failures.dismiss_ticket(member, actor)
        changed.append(member["id"])
    if not changed:
        return _result(batch, "Không còn lỗi nào đang chờ")
    # a separate field: an earlier bulk re-queue is still undoable
    batch = failure_tickets.update(batch["id"], last_dismiss={"by": actor, "count": len(changed), "at": datetime.now(timezone.utc).isoformat()}) or batch
    batch = _refresh_status(batch["id"])
    return _result(batch, f"Đã bỏ qua {len(changed)} lỗi", changed=changed)


def _undo_all(batch: dict[str, Any], actor: str) -> CallbackResult:
    resched = batch.get("last_resched") or {}
    if not resched:
        return _result(batch, "Không có gì để hoàn tác")
    ids = set(resched.get("ids") or [])
    undone, kept = [], []
    for member in members_of(batch):
        if member["id"] not in ids or member.get("status") != failure_tickets.RESCHEDULED:
            continue  # changed since (undone one by one, or handled elsewhere)
        after = telegram_failures.undo_requeue(member, actor)
        (undone if after.get("status") == failure_tickets.OPEN else kept).append(after["id"])
    batch = failure_tickets.update(batch["id"], last_resched=dict(resched, ids=kept) if kept else None) or batch
    batch = _refresh_status(batch["id"])
    toast = f"Đã hoàn tác {len(undone)} lỗi" + (f", {len(kept)} không hoàn tác được (sắp/đã chạy)" if kept else "")
    return _result(batch, toast, changed=undone + kept, alert=bool(kept and not undone))
