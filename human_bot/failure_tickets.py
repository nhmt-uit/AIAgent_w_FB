"""
Purpose of this file / Muc dich cua file nay:
EN: A small on-disk store of Telegram FAILURE TICKETS (2026-11-01). Each failed
attempt the bot reports gets a ticket that remembers (a) what failed — the
failed task file or the action_log row — and (b) which Telegram message(s)
carry its buttons, in every recipient's chat. That is what lets a button press
or a plain REPLY to the message find the right task again, and lets the bot
update every recipient's copy once someone has dealt with it.

Callback data only carries the ticket id (Telegram caps callback_data at 64
bytes); everything else is looked up here. File-backed (data_sync_cache/),
atomic writes, one lock — it is touched both from the event loop (creating a
ticket when an attempt fails) and from worker threads (button handlers run in
asyncio.to_thread()).
VI: Kho "phieu loi" Telegram: moi lan dang/binh luan that bai co 1 phieu nho
task/ban ghi nao va tin nhan nao dang mang nut, de bam nut hoac tra loi tin
nhan tim lai dung viec.
"""
from __future__ import annotations

import json
import logging
import os
import tempfile
import threading
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("human_bot.failure_tickets")

STORE_PATH = Path(__file__).resolve().parent.parent / "data_sync_cache" / "_telegram_tickets.json"
MAX_TICKETS = 300
KEEP_RESOLVED_DAYS = 14
MAX_COPIES_PER_CHAT = 8

OPEN = "open"
RESCHEDULED = "rescheduled"
DISMISSED = "dismissed"
POSTED = "posted"  # the operator confirmed the post was already live

_lock = threading.RLock()


def _load() -> dict[str, dict[str, Any]]:
    try:
        text = STORE_PATH.read_text(encoding="utf-8")
    except OSError:
        return {}
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
        raise ValueError("not an object")
    except ValueError:
        # Never let the next create() silently overwrite (and so destroy) a damaged
        # store: keep the bad file aside for inspection first.
        try:
            os.replace(STORE_PATH, STORE_PATH.with_name(f"{STORE_PATH.name}.corrupt-{datetime.now(timezone.utc):%Y%m%dT%H%M%S}"))
            logger.error("failure_tickets: store was unreadable — moved aside, starting empty")
        except OSError:
            logger.exception("failure_tickets: store unreadable and could not be moved aside")
        return {}


def _save(tickets: dict[str, dict[str, Any]]) -> bool:
    tmp = None
    try:
        STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
        fd, tmp = tempfile.mkstemp(dir=STORE_PATH.parent, suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(tickets, f, ensure_ascii=False)
        os.replace(tmp, STORE_PATH)
        return True
    except OSError:
        logger.exception("failure_tickets: could not save")
        if tmp:
            try:
                os.unlink(tmp)
            except OSError:
                pass
        return False


def _prune(tickets: dict[str, dict[str, Any]]) -> None:
    cutoff = (datetime.now(timezone.utc) - timedelta(days=KEEP_RESOLVED_DAYS)).isoformat()
    for tid in [t for t, v in tickets.items() if v.get("status") != OPEN and v.get("updated_at", v.get("created_at", "")) < cutoff]:
        tickets.pop(tid, None)
    if len(tickets) > MAX_TICKETS:  # drop the oldest resolved first, then the oldest overall
        order = sorted(tickets, key=lambda t: (tickets[t].get("status") == OPEN, tickets[t].get("created_at", "")))
        for tid in order[: len(tickets) - MAX_TICKETS]:
            tickets.pop(tid, None)


def create(**fields: Any) -> dict[str, Any]:
    """Raises RuntimeError if the ticket could not be stored."""
    now = datetime.now(timezone.utc).isoformat()
    ticket = {
        "id": uuid.uuid4().hex[:8], "status": OPEN, "created_at": now, "updated_at": now,
        "messages": [], "resched": None, **fields,
    }
    with _lock:
        tickets = _load()
        _prune(tickets)
        tickets[ticket["id"]] = ticket
        if not _save(tickets):
            # a card whose buttons point at a ticket that was never stored would all fail —
            # let the caller fall back to the plain report instead
            raise RuntimeError("failure_tickets: could not persist the new ticket")
    return ticket


def get(ticket_id: str) -> dict[str, Any] | None:
    with _lock:
        return _load().get(ticket_id)


def update(ticket_id: str, **fields: Any) -> dict[str, Any] | None:
    with _lock:
        tickets = _load()
        ticket = tickets.get(ticket_id)
        if ticket is None:
            return None
        ticket.update(fields)
        ticket["updated_at"] = datetime.now(timezone.utc).isoformat()
        _save(tickets)
        return ticket


def add_message(ticket_id: str, chat_id: str, message_id: int, photo: bool = False) -> None:
    with _lock:
        tickets = _load()
        ticket = tickets.get(ticket_id)
        if ticket is None:
            return
        messages = ticket.setdefault("messages", [])
        messages.append({"chat_id": str(chat_id), "message_id": int(message_id), "photo": bool(photo)})
        # /loi adds a fresh copy each time it is used: keep the newest few PER CHAT
        # (older copies' buttons still work — callbacks carry only the ticket id;
        # only replying to / refreshing a very old copy stops being tracked).
        keep: list[dict] = []
        per_chat: dict[str, int] = {}
        for m in reversed(messages):
            per_chat[m["chat_id"]] = per_chat.get(m["chat_id"], 0) + 1
            if per_chat[m["chat_id"]] <= MAX_COPIES_PER_CHAT:
                keep.append(m)
        ticket["messages"] = list(reversed(keep))
        _save(tickets)


def find_by_message(chat_id: str, message_id: int) -> dict[str, Any] | None:
    with _lock:
        for ticket in _load().values():
            for m in ticket.get("messages", []):
                if m.get("chat_id") == str(chat_id) and m.get("message_id") == int(message_id):
                    return ticket
    return None


def task_index() -> dict[str, dict[str, Any]]:
    """task_id → its newest ticket, from ONE read of the store (for listings that
    look up many tasks)."""
    with _lock:
        tickets = list(_load().values())
    index: dict[str, dict[str, Any]] = {}
    for t in tickets:
        tid = t.get("task_id")
        if tid and (tid not in index or t.get("created_at", "") > index[tid].get("created_at", "")):
            index[tid] = t
    return index


def find_by_task(task_id: str) -> dict[str, Any] | None:
    """The most recent ticket for a failed task, if any."""
    with _lock:
        matches = [t for t in _load().values() if t.get("task_id") == task_id]
    return max(matches, key=lambda t: t.get("created_at", "")) if matches else None


def list_open(since: datetime | None = None) -> list[dict[str, Any]]:
    """Open tickets, newest first."""
    with _lock:
        items = [t for t in _load().values() if t.get("status") == OPEN]
    if since is not None:
        items = [t for t in items if t.get("created_at", "") >= since.isoformat()]
    return sorted(items, key=lambda t: t.get("created_at", ""), reverse=True)
