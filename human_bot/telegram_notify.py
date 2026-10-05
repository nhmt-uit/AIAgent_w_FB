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

Credentials (TELEGRAM_BOT_TOKEN/TELEGRAM_CHAT_ID) live in .env, same
pattern as DATA_INGESTION_API_TOKEN — a one-time setup credential, not
something edited often enough to need an admin-UI field. The one
admin-editable piece is the on/off switch (human_bot/telegram_config.py,
/admin/config) so the owner can mute without touching .env or
restarting.

Every public function here is best-effort: no token configured, the
switch is off, a network error, Telegram returning non-200 — all
swallowed, never raised. A notification failing must never break the
real task it's reporting on, same stance human_bot/db.py's log_action()
and human_bot/screenshots.py's capture() already take for their own
"record what happened" side-channels.
VI: Lop boc API Telegram cho tinh nang bao dong 3 phan (yeu cau owner,
2026-10-05) — bao am tham moi luot dang/binh luan, bao dong 5 loai su co
that, va hoi-dap 2 chieu lay lai dung bang suc khoe da co o trang chu.
"""
from __future__ import annotations

import logging
import os

import httpx

from human_bot.runtime_config import get_telegram_config

logger = logging.getLogger("human_bot.telegram_notify")

_API_BASE = "https://api.telegram.org/bot{token}"
_TIMEOUT = 15  # send calls — must never hang a real task waiting on Telegram
_POLL_TIMEOUT = 30  # getUpdates' own long-poll window, passed to Telegram itself


def _token() -> str:
    return os.environ.get("TELEGRAM_BOT_TOKEN", "").strip()


def _chat_id() -> str:
    return os.environ.get("TELEGRAM_CHAT_ID", "").strip()


def is_configured() -> bool:
    """True only when there's actually somewhere to send to AND the admin
    hasn't muted it — every public function below checks this first so a
    missing/disabled setup is a silent no-op, not a wall of log noise on
    every single task."""
    return bool(_token()) and bool(_chat_id()) and get_telegram_config().enabled


async def send_message(text: str, *, silent: bool = False) -> None:
    if not is_configured():
        return
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _API_BASE.format(token=_token()) + "/sendMessage",
                data={
                    "chat_id": _chat_id(),
                    "text": text[:4096],  # Telegram's own hard per-message cap
                    "disable_notification": silent,
                },
            )
            if resp.status_code != 200:
                logger.warning("telegram_notify: sendMessage HTTP %s: %s", resp.status_code, resp.text[:300])
    except Exception:  # noqa: BLE001 — must never break the caller's real task
        logger.exception("telegram_notify: sendMessage failed")


async def send_photo(path: str, caption: str = "", *, silent: bool = False) -> None:
    """Uploads a local file (e.g. human_bot/screenshots.py's capture()
    output) directly — never a URL, since screenshots live only on this
    machine's disk. Falls back to a plain send_message() with the same
    caption if the file can't be read (never silently drops the report
    text just because the image failed)."""
    if not is_configured():
        return
    try:
        with open(path, "rb") as f:
            photo_bytes = f.read()
    except OSError:
        await send_message(caption, silent=silent)
        return
    try:
        async with httpx.AsyncClient(timeout=_TIMEOUT) as client:
            resp = await client.post(
                _API_BASE.format(token=_token()) + "/sendPhoto",
                data={"chat_id": _chat_id(), "caption": caption[:1024], "disable_notification": silent},
                files={"photo": (os.path.basename(path), photo_bytes)},
            )
            if resp.status_code != 200:
                logger.warning("telegram_notify: sendPhoto HTTP %s: %s", resp.status_code, resp.text[:300])
    except Exception:  # noqa: BLE001 — see send_message()
        logger.exception("telegram_notify: sendPhoto failed")


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
    except Exception:  # noqa: BLE001 — see send_message()
        logger.exception("telegram_notify: getUpdates failed")
        return []
