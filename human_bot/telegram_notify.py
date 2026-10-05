"""
Purpose of this file / Muc dich cua file nay:
EN: Thin wrapper around the Telegram Bot API for 2026-10-05's 3-part
alert feature (owner request): (1) a silent report for every real
post/comment attempt (human_bot/agent.py's run_task()), (2) loud alerts
for 5 kinds of real trouble (account paused, N consecutive failures,
side-B sync errors, 48h+ silence, session expiring soon), and (3) a
2-way health query — send the bot any message, get back the same "sức
khoẻ tài khoản" snapshot /admin's home page shows (human_bot/admin.py's
_account_health_signals(), shared so this file never re-implements that
logic).

Recipients (2026-10-05, same day — owner follow-up request: "ai cũng tự
dùng Telegram của họ... nhưng phải được cài đặt ở ADMIN") are an
admin-managed LIST (human_bot/runtime_config.py's get_telegram_recipients(),
editable at /admin/accounts's "Tài khoản Telegram" tab), not a single
hardcoded chat id — every broadcast (send_message/send_photo) goes to
every registered recipient, each isolated in its own try/except so one
bad/blocked recipient can never swallow the others' alerts.
send_message_to() is the one exception: a DIRECT reply to a single chat
id (used for the 2-way query's answer — only the person who asked gets
the reply, not every recipient).

Pending senders (2026-10-05, follow-up — owner noticed someone who only
has /admin access has no way to know TELEGRAM_BOT_TOKEN, so they can't
hand-build a getUpdates URL to find their own chat_id): record_pending_sender()/
get_pending_senders()/clear_pending_sender() track, in-memory only (no
disk persistence — this is a short-lived convenience list, not data worth
surviving a restart), anyone who messaged the bot but isn't registered
yet, so the admin UI can offer a one-click "➕ Thêm" instead of ever
asking anyone to read a raw API response. Populated by
human_bot/service.py's _telegram_listen_loop() for every unregistered
sender it sees.

Credentials (TELEGRAM_BOT_TOKEN) lives in .env, same pattern as
DATA_INGESTION_API_TOKEN — a one-time setup credential, not something
edited often enough to need an admin-UI field. The one admin-editable
piece is the on/off switch (human_bot/telegram_config.py, /admin/config)
so the owner can mute without touching .env or restarting.

Every public function here is best-effort: no token configured, the
switch is off, a network error, Telegram returning non-200 — all
swallowed, never raised. A notification failing must never break the
real task it's reporting on, same stance human_bot/db.py's log_action()
and human_bot/screenshots.py's capture() already take for their own
"record what happened" side-channels.
VI: Lop boc API Telegram cho tinh nang bao dong 3 phan (yeu cau owner,
2026-10-05) — bao am tham moi luot dang/binh luan, bao dong 5 loai su co
that, va hoi-dap 2 chieu lay lai dung bang suc khoe da co o trang chu.
Nguoi nhan la danh sach quan ly qua tab "Tai khoan Telegram" trong
/admin/accounts, khong con 1 chat id co dinh nua.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timezone

import httpx

from human_bot.runtime_config import get_telegram_config, get_telegram_recipients

logger = logging.getLogger("human_bot.telegram_notify")

_API_BASE = "https://api.telegram.org/bot{token}"
_TIMEOUT = 15  # send calls — must never hang a real task waiting on Telegram
_POLL_TIMEOUT = 30  # getUpdates' own long-poll window, passed to Telegram itself

# In-memory only (2026-10-05) — see this module's own docstring. Capped so
# a stranger repeatedly messaging an unregistered chat can't grow this
# unboundedly; oldest-by-last-seen is evicted first, same "never let one
# bad actor degrade the whole service" posture as everything else here.
_PENDING_SENDERS_CAP = 20
_pending_senders: dict[str, dict[str, str]] = {}


def record_pending_sender(chat_id: str, name: str) -> None:
    """Called by human_bot/service.py's _telegram_listen_loop() for every
    message from a chat_id that ISN'T (yet) a registered recipient —
    `name` is whatever human_bot/service.py could derive from the raw
    Telegram update (a group's title, or a private sender's first/last
    name or @username), falling back to the chat_id itself when Telegram
    gave nothing usable. Re-messaging updates `last_seen` (and evicts the
    actual oldest entry if already at the cap) rather than being a no-op,
    so a sender who tried a while ago and comes back shows up fresh."""
    if chat_id not in _pending_senders and len(_pending_senders) >= _PENDING_SENDERS_CAP:
        oldest_chat_id = min(_pending_senders, key=lambda cid: _pending_senders[cid]["last_seen"])
        del _pending_senders[oldest_chat_id]
    _pending_senders[chat_id] = {"name": name, "last_seen": datetime.now(timezone.utc).isoformat()}


def get_pending_senders() -> dict[str, dict[str, str]]:
    """A snapshot, not a live view — copies each inner {"name", ...}
    dict too (self-review follow-up), not just the outer dict, so a
    caller can never mutate the real _pending_senders state by reaching
    into a value it got back from here."""
    return {chat_id: dict(info) for chat_id, info in _pending_senders.items()}


def clear_pending_sender(chat_id: str) -> None:
    """Called right after a pending sender is actually added as a
    recipient (admin.py's telegram_recipients_add()) — idempotent, same
    "deleting something already gone is a no-op" stance
    runtime_config.py's delete_* functions take."""
    _pending_senders.pop(chat_id, None)


# Bot username (2026-10-05 follow-up — owner: the "Tài khoản Telegram"
# tab's instructions should link straight to the bot's own chat instead
# of just saying "message the bot"). Cached in-memory rather than looked
# up on every page render: human_bot/admin.py's content renderer is a
# plain SYNC function (no network calls), so the lookup happens once,
# async, at service startup (human_bot/service.py's lifespan(), right
# alongside its other one-time startup actions) via refresh_bot_username()
# — get_cached_bot_username() itself never makes a network call, safe to
# call from sync code. A bot's username essentially never changes while
# the service is running, so a startup-only fetch is enough; like the
# token itself, picking up a change needs a restart anyway.
_cached_bot_username: str | None = None


async def refresh_bot_username() -> None:
    if not _token():
        return
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.get(_API_BASE.format(token=_token()) + "/getMe")
            if resp.status_code != 200:
                logger.warning("telegram_notify: getMe HTTP %s: %s", resp.status_code, resp.text[:300])
                return
            data = resp.json()
            if data.get("ok"):
                global _cached_bot_username
                _cached_bot_username = data.get("result", {}).get("username")
    except Exception:  # noqa: BLE001 — must never block service startup over this
        logger.exception("telegram_notify: getMe failed")


def get_cached_bot_username() -> str | None:
    return _cached_bot_username


def _token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def is_configured() -> bool:
    """True only when there's a token to send with AND the admin hasn't
    muted it — every public function below checks this first so a
    missing/disabled setup is a silent no-op, not a wall of log noise on
    every single task. Deliberately does NOT also require the recipients
    list to be non-empty (2026-10-05) — broadcasting to an empty list is
    already a harmless no-op on its own, and get_updates()/the 2-way
    listen loop must keep polling even with zero recipients registered
    yet, so a brand new recipient added via /admin while the service is
    already running can query immediately, no restart needed."""
    return bool(_token()) and get_telegram_config().enabled


async def _send_message_to(chat_id: str, text: str, *, silent: bool) -> bool:
    """Low-level single-recipient send — shared by send_message()'s
    broadcast loop and the public send_message_to(). Never raises; logs
    and swallows every failure, same stance every function in this
    module takes. Returns whether it actually reached Telegram with a
    200 (not just "didn't raise") — send_message_to()'s caller
    (admin.py's "🧪 Gửi thử" button) needs a REAL success/failure signal,
    not just "no exception", or a bad chat_id/revoked token would report
    a false "✅ đã gửi" every time."""
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _API_BASE.format(token=_token()) + "/sendMessage",
                data={
                    "chat_id": chat_id,
                    "text": text[:4096],  # Telegram's own hard per-message cap
                    "disable_notification": silent,
                },
            )
            if resp.status_code != 200:
                logger.warning(
                    "telegram_notify: sendMessage to %s HTTP %s: %s", chat_id, resp.status_code, resp.text[:300],
                )
                return False
            return True
    except Exception:  # noqa: BLE001 — must never break the caller's real task
        logger.exception("telegram_notify: sendMessage to %s failed", chat_id)
        return False


async def send_message(text: str, *, silent: bool = False) -> None:
    """Broadcasts to every registered recipient (/admin/telegram) — each
    one isolated via _send_message_to()'s own try/except, so a recipient
    who blocked the bot or typo'd their chat_id never swallows the alert
    for everyone else."""
    if not is_configured():
        return
    for recipient in get_telegram_recipients():
        await _send_message_to(recipient["chat_id"], text, silent=silent)


async def send_message_to(chat_id: str, text: str, *, silent: bool = False) -> bool:
    """Direct reply to ONE specific chat id — used by the 2-way health
    query (human_bot/service.py's _telegram_listen_loop()) so only the
    person who actually asked gets the answer, not every registered
    recipient; also used by admin.py's "🧪 Gửi thử" button, which is WHY
    this returns bool (actually reached Telegram?) rather than None —
    see _send_message_to()'s own docstring. Still gated on
    is_configured() (token + admin switch), but deliberately does NOT
    check `chat_id` is itself in the registered list — the caller
    already filtered to a registered chat_id before calling this."""
    if not is_configured():
        return False
    return await _send_message_to(chat_id, text, silent=silent)


async def send_photo(path: str, caption: str = "", *, silent: bool = False) -> None:
    """Uploads a local file (e.g. human_bot/screenshots.py's capture()
    output) directly — never a URL, since screenshots live only on this
    machine's disk. Falls back to a plain send_message() with the same
    caption if the file can't be read (never silently drops the report
    text just because the image failed). Broadcasts to every registered
    recipient, reading the file bytes ONCE and reusing them for each
    (not re-reading per recipient) — each send isolated, same as
    send_message()'s loop."""
    if not is_configured():
        return
    recipients = get_telegram_recipients()
    if not recipients:
        return
    try:
        with open(path, "rb") as f:
            photo_bytes = f.read()
    except OSError:
        await send_message(caption, silent=silent)
        return
    filename = os.path.basename(path)
    for recipient in recipients:
        chat_id = recipient["chat_id"]
        try:
            async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
                resp = await client.post(
                    _API_BASE.format(token=_token()) + "/sendPhoto",
                    data={"chat_id": chat_id, "caption": caption[:1024], "disable_notification": silent},
                    files={"photo": (filename, photo_bytes)},
                )
                if resp.status_code != 200:
                    logger.warning(
                        "telegram_notify: sendPhoto to %s HTTP %s: %s", chat_id, resp.status_code, resp.text[:300],
                    )
        except Exception:  # noqa: BLE001 — see send_message()'s docstring
            logger.exception("telegram_notify: sendPhoto to %s failed", chat_id)


async def get_updates(offset: int | None, *, timeout: int = _POLL_TIMEOUT) -> list[dict]:
    """Long-polls Telegram for new messages sent to the bot — works from
    behind NAT/no public IP (this is an OUTBOUND request Telegram
    responds to, not an inbound webhook), which is the whole reason this
    project uses Telegram over Slack for the 2-way health query. Returns
    [] on any error (not configured, network, bad response) — caller's
    poll loop just tries again next cycle, same "one bad cycle must never
    kill the loop" stance as human_bot/service.py's other loops."""
    if not is_configured():
        return []
    try:
        async with httpx.AsyncClient(timeout=timeout + 10) as client:
            params: dict = {"timeout": timeout}
            if offset is not None:
                params["offset"] = offset
            resp = await client.get(_API_BASE.format(token=_token()) + "/getUpdates", params=params)
            if resp.status_code != 200:
                logger.warning("telegram_notify: getUpdates HTTP %s: %s", resp.status_code, resp.text[:300])
                return []
            data = resp.json()
            return data.get("result", []) if data.get("ok") else []
    except Exception:  # noqa: BLE001 — see send_message()'s docstring
        logger.exception("telegram_notify: getUpdates failed")
        return []
