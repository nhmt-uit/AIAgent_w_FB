"""
FastAPI service exposing human_bot to n8n over plain HTTP.

n8n's HTTP Request node calls POST /tasks with a Task JSON (see
docs/agents/content-strategist.md for the schema produced by the Content
Strategist Agent) and receives a TaskResult back (see
docs/agents/human-bot-executor.md).

On startup, this pre-launches a persistent, already-logged-in browser for
every ACTIVE account in human_bot/config.py (see human_bot/browser_pool.py)
and keeps it open for the life of the process — this is what makes "the
browser is always ready" true: run this service continuously (e.g. under
systemd, pm2, or a Docker container that stays up), and n8n just calls
POST /tasks whenever it needs an action performed. It does not need to
know anything about the browser's lifecycle.

Run with: uvicorn human_bot.service:app --host 0.0.0.0 --port 8000

This also serves a local admin UI at /admin (config editor + manual/queued
posting — see human_bot/admin.py) with real posting power. If this host is
reachable from anywhere other than your own machine, set ADMIN_USERNAME and
ADMIN_PASSWORD in .env, or put it behind a firewall/reverse proxy — do not
expose /admin to the public internet unauthenticated.

POST /tasks itself has the same real posting power and the same rule:
if this host is reachable from anywhere but your own machine, set
TASKS_API_KEY in .env (added 2026-09-04) — every caller (n8n, a
data-fetching service, ...) then needs to send that same value back in an
"X-API-Key" header. Left unset, the endpoint has no auth at all, same
permissive default as ADMIN_USERNAME/ADMIN_PASSWORD when those are blank.
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import Depends, FastAPI, Header, HTTPException, Request, status  # noqa: E402
from fastapi.responses import RedirectResponse, Response  # noqa: E402
from pydantic import BaseModel  # noqa: E402
from starlette.middleware.sessions import SessionMiddleware  # noqa: E402

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import secrets  # noqa: E402
import sys  # noqa: E402
import time  # noqa: E402
from urllib.parse import quote  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from human_bot import data_sync, db, schedule_store, screenshots, telegram_notify  # noqa: E402
from human_bot.admin import (  # noqa: E402
    NotLoggedIn,
    _SESSION_EXPIRY_WARNING_DAYS,
    _SILENCE_WARNING_HOURS,
    _account_health_telegram_text,
    _account_warning_status,
    router as admin_router,
)
from human_bot.agent import TaskRequest, run_task  # noqa: E402
from human_bot.browser_pool import close_all, warm_up  # noqa: E402
from human_bot.config import AccountStatus, get_all_accounts  # noqa: E402
from human_bot.logging_setup import configure_logging  # noqa: E402
from human_bot import runtime_config  # noqa: E402
from human_bot.runtime_config import (  # noqa: E402
    get_active_cooldown_rate_limits,
    get_all_active_cooldown_account_ids,
    get_config_changed_event,
    get_data_sync_config,
    get_sync_disabled_account_ids,
    get_telegram_recipients,
)

configure_logging()

logger = logging.getLogger(__name__)

SCHEDULE_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60


async def _wait_until_due(remaining_seconds: float) -> None:
    """Sleep for up to `remaining_seconds`, but wake up EARLY the moment
    human_bot/runtime_config.py's notify_config_changed() fires (any
    /admin/config save, or a per-account sync toggle) — see that
    function's docstring for the incident this fixes (2026-09-08): a
    human changing a setting in the admin UI must apply immediately, not
    whenever a background loop's current sleep happens to end on its own.
    The timeout is still there as a plain safety net for the ordinary
    "nothing changed, just waiting for the interval to elapse" case, so
    this never depends solely on every writer remembering to notify."""
    event = get_config_changed_event()
    try:
        await asyncio.wait_for(event.wait(), timeout=max(remaining_seconds, 0))
    except asyncio.TimeoutError:
        pass
    else:
        event.clear()


async def _data_sync_poll_loop() -> None:
    """Background loop: periodically pull new jobs/candidates from side B,
    dedupe, and schedule them (human_bot/data_sync.py). Runs inside this
    already-24/7 process rather than as a separate cron job — see
    docs/architecture.md section 3c. Never lets one bad cycle kill the
    loop: side B being briefly unreachable, or one malformed record,
    should not take down posting for the rest of the process.

    Re-reads config every time it wakes — either because the interval
    elapsed, or because _wait_until_due() woke it early on a config
    change — and only runs once `poll_interval_minutes` has actually
    elapsed since the last real sync. `last_run_at` only advances when a
    sync actually runs, so flipping `enabled` back on fires on the very
    next wake instead of waiting out whatever interval was current before
    it was turned off.

    An ACTIVE account can still be excluded from just this loop via
    get_sync_disabled_account_ids() (human_bot/runtime_config.py) — set
    from /admin/accounts, independent of pausing the account outright
    (which would also block manual posting)."""
    last_run_at: datetime | None = None
    while True:
        cfg = get_data_sync_config()
        now = datetime.now(timezone.utc)
        interval_seconds = max(cfg.poll_interval_minutes, 1.0) * 60
        elapsed = None if last_run_at is None else (now - last_run_at).total_seconds()
        due = elapsed is None or elapsed >= interval_seconds
        if cfg.enabled and due:
            last_run_at = now
            sync_disabled = get_sync_disabled_account_ids()
            active_accounts = [
                a for a in get_all_accounts().values()
                if a.status == AccountStatus.ACTIVE and a.account_id not in sync_disabled
            ]
            # ONE call for every active account, not one call per account
            # in a loop — data_sync.sync_all() fetches side B's jobs/
            # candidates once and fair-distributes them across whichever
            # accounts are passed in here. Looping sync_once() per account
            # (removed 2026-09-10) used to make every account after the
            # first silently get nothing, since they'd all share one
            # global "seen" cache and the first account to run each cycle
            # claimed every new item for itself.
            try:
                await data_sync.sync_all([a.account_id for a in active_accounts], cfg)
            except Exception:  # noqa: BLE001 - a bad sync cycle must not kill this loop
                logger.exception("data_sync.sync_all failed")
            await _wait_until_due(interval_seconds)
        else:
            remaining = interval_seconds if elapsed is None else interval_seconds - elapsed
            await _wait_until_due(remaining)


async def _data_sync_fire_loop() -> None:
    """Background loop: check for scheduled tasks that are now due and,
    only if SchedulingConfig.auto_fire_enabled is True, actually post them
    (via run_task()). Runs regardless of DataSyncConfig.enabled — that
    flag only gates the side-B poll loop above, while due tasks can also
    come from composing by hand at /admin/post, so this check must not
    depend on whether the side-B integration is turned on (fixed
    2026-09-07 alongside moving auto_fire_enabled to its own config — see
    human_bot/scheduling_config.py — since both were the same "buried
    under data-sync" issue). Left False by default — see
    human_bot/scheduling_config.py and /admin/schedule's manual 'Đăng
    ngay' button for the safe-by-default alternative.

    Same wake-on-change-or-interval pattern as _data_sync_poll_loop()
    above, same reason — see _wait_until_due()'s docstring."""
    last_run_at: datetime | None = None
    while True:
        cfg = get_data_sync_config()
        now = datetime.now(timezone.utc)
        interval_seconds = max(cfg.due_check_interval_seconds, 5.0)
        elapsed = None if last_run_at is None else (now - last_run_at).total_seconds()
        due = elapsed is None or elapsed >= interval_seconds
        if due:
            last_run_at = now
            try:
                await data_sync.fire_due_tasks()
            except Exception:  # noqa: BLE001 - keep the loop alive across failures
                logger.exception("data_sync.fire_due_tasks failed")
            await _wait_until_due(interval_seconds)
        else:
            await _wait_until_due(interval_seconds - elapsed)


async def _schedule_cleanup_loop() -> None:
    """Background loop: prune old posted/failed/cancelled scheduled-task
    files (human_bot/schedule_store.py's cleanup_old()) so `scheduled/`
    doesn't grow without bound as the schedule gets busier over time.
    Runs once at startup, then once a day — this is disk housekeeping,
    not something that needs a tight interval. Reporting history lives in
    human_bot.db (human_bot/db.py), untouched by the file cleanups above —
    but since 2026-09-28 the same loop also prunes action_log rows older
    than its own 180-day window (db.cleanup_old(), owner's explicit
    choice), which DOES drop those rows from /admin/reports.

    Also runs schedule_store.cancel_stale_missed() (2026-09-24, owner
    request) — MISSED_DIR previously had no cleanup of its own at all
    (see that function's docstring), so a task nobody reviewed in
    /admin/schedule's "⚠️ Task quá hạn" tab would sit there forever.
    Same daily cadence is plenty for a 30-day-default threshold; bundled
    into this existing loop rather than a new one since it's the same
    kind of housekeeping, not something latency-sensitive."""
    while True:
        try:
            schedule_store.cleanup_old()
        except Exception:  # noqa: BLE001 - a cleanup failure must not take down posting
            logger.exception("schedule_store.cleanup_old failed")
        try:
            schedule_store.cancel_stale_missed()
        except Exception:  # noqa: BLE001 - a cleanup failure must not take down posting
            logger.exception("schedule_store.cancel_stale_missed failed")
        try:
            # 2026-09-28: also prunes human_bot.db's action_log beyond its
            # (180-day default) retention window — see db.cleanup_old().
            db.cleanup_old()
        except Exception:  # noqa: BLE001 - a cleanup failure must not take down posting
            logger.exception("db.cleanup_old failed")
        await asyncio.sleep(SCHEDULE_CLEANUP_INTERVAL_SECONDS)


async def _screenshot_cleanup_loop() -> None:
    """Background loop: prune old evidence screenshots
    (human_bot/screenshots.py's cleanup_old()) so `screenshots/` doesn't
    grow without bound — every posting attempt, success or failure, saves
    one (added 2026-09-07). Same daily-interval, startup-plus-once-a-day
    pattern as _schedule_cleanup_loop right above; a pruned screenshot
    just means that row in /admin/reports loses its image link, the text
    history in human_bot.db is unaffected."""
    while True:
        try:
            screenshots.cleanup_old()
        except Exception:  # noqa: BLE001 - a cleanup failure must not take down posting
            logger.exception("screenshots.cleanup_old failed")
        await asyncio.sleep(SCHEDULE_CLEANUP_INTERVAL_SECONDS)


# How often this loop re-checks for cooldown work when it currently has
# NONE — short enough that a resume happening right after a check still
# gets picked up same-day, but far cheaper than the 1x/day cadence used
# once there's real work (owner request 2026-09-15).
_RESUME_COOLDOWN_IDLE_CHECK_SECONDS = 60 * 60


async def _resume_cooldown_maintenance_loop() -> None:
    """Background loop for human_bot/runtime_config.py's post-resume
    cooldown (see get_active_cooldown_rate_limits()'s docstring for the
    full 2-week floor/step-up design and the bug it replaced).

    Every rate-limit check this project actually enforces already reads
    the cooldown-adjusted numbers fresh, on demand, via human_bot/
    config.py's get_all_accounts() — so correctness never depended on
    this loop running at all; a cooldown transitioning from week 1 to
    week 2, or finishing entirely, takes effect the very next time
    anything asks for that account's rate limits, with or without this
    loop. What this loop adds is PROMPTNESS for anyone just watching
    (e.g. /admin/accounts' "🧊 Đang hạ nhiệt" banner, or
    runtime_config.json itself) — without it, a finished cooldown's
    record would keep sitting there, stale, until the next time some
    other code path happened to touch that account.

    Owner-specified shape (2026-09-15): checks once an hour for whether
    ANY account has a cooldown record at all
    (get_all_active_cooldown_account_ids(), cheap — just reads the raw
    key list); if none, there's nothing to do, so it just waits and
    checks again next hour. Once at least one exists, it switches to a
    1x/day cadence, nudging every such account via
    get_active_cooldown_rate_limits() (which does the real, lazy
    "has cooldown_days actually passed?" check and drops the record
    itself if so) so records don't go stale for a full 14 days between
    checks. Restarting the service re-enters this same loop from
    scratch, which immediately re-reads runtime_config.json — cooldown
    state is plain JSON on disk (started_at + base_tier), not in-memory,
    so a restart mid-cooldown loses no progress and this loop simply
    picks the same accounts back up on its very first check."""
    while True:
        active_ids = get_all_active_cooldown_account_ids()
        if not active_ids:
            await asyncio.sleep(_RESUME_COOLDOWN_IDLE_CHECK_SECONDS)
            continue
        for account_id in active_ids:
            try:
                get_active_cooldown_rate_limits(account_id)  # lazily expires if due
            except Exception:  # noqa: BLE001 - one bad record must not kill the loop
                logger.exception("resume-cooldown maintenance failed for %s", account_id)
        await asyncio.sleep(SCHEDULE_CLEANUP_INTERVAL_SECONDS)


# How often _telegram_health_check_loop() re-scans "im lặng quá lâu" /
# "phiên đăng nhập sắp hết hạn" — these are slow-moving conditions (hours/
# days), unlike every other Telegram alert type (paused, N-fail-streak,
# sync errors), which all fire inline at the exact moment they happen —
# see human_bot/agent.py's run_task()/human_bot/data_sync.py's
# sync_all(). 6h is frequent enough that a condition crossing its
# threshold overnight is still caught the same business day.
_TELEGRAM_HEALTH_CHECK_INTERVAL_SECONDS = 6 * 60 * 60
# How long _telegram_listen_loop() sleeps between checks while Telegram
# isn't configured/enabled (or get_updates() comes back suspiciously
# fast — see _TELEGRAM_LISTEN_MIN_POLL_SECONDS below) — short enough
# that enabling it at runtime (no restart needed) picks up within half a
# minute, long enough to never busy-spin the event loop in the meantime.
_TELEGRAM_LISTEN_IDLE_SLEEP_SECONDS = 30
# A genuine Telegram long-poll (telegram_notify.get_updates()'s own
# _POLL_TIMEOUT=30s) either blocks close to that long, or returns near-
# instantly because real messages were already waiting. Anything else
# returning this fast — a revoked/typo'd token, DNS failure, any other
# network error — hits get_updates()'s own try/except and returns []
# without raising, so it looks identical to "not configured" from here
# and needs the same idle sleep to avoid busy-spinning/hammering
# Telegram (2026-10-05 self-review, round 3 — round 2's fix only covered
# the literal "not configured" case).
_TELEGRAM_LISTEN_MIN_POLL_SECONDS = 2


async def _telegram_health_check_loop() -> None:
    """Background loop: the "sức khoẻ tài khoản" signals that are a
    slowly-true CONDITION rather than a one-off EVENT (2026-10-05, alert
    types 4/5 and 5/5) — im lặng > admin._SILENCE_WARNING_HOURS, phiên
    đăng nhập còn < admin._SESSION_EXPIRY_WARNING_DAYS ngày (hoặc đã hết
    hạn hẳn, hoặc không đọc được). Calls human_bot/admin.py's
    _account_warning_status() directly for the actual combination logic
    (2026-10-05 self-review, round 5 — a prior version hand-copied that
    logic here instead of calling it, and the copy had silently drifted
    from admin.py's _account_health_signals(): it was missing the
    "already expired" vs "expiring soon" distinction, so an already-dead
    session got the milder "sắp hết hạn" wording here while /admin
    correctly showed red "đã hết hạn" for the same account) — this is
    what actually makes the Telegram alert and the /admin dashboard card
    never disagree about when a condition starts/stops being a warning,
    not just a shared pair of threshold constants.

    Dedup: only alerts on the TRANSITION into a warning (compared against
    `_last_warned`, in-memory — a service restart re-alerts once for any
    condition still active, which is the right default: better one
    redundant message after a restart than silently losing track of a
    real, still-unresolved warning). Clears an account's entry the moment
    it's no longer warning-worthy, so a LATER recurrence alerts again."""
    last_warned: dict[str, set[str]] = {}
    # (kind, message) in priority order — _account_warning_status()'s
    # `kinds` set is the single source of truth for WHETHER each of
    # these applies (2026-10-05 self-review, round 5); this loop only
    # decides the Telegram WORDING for each kind.
    alert_texts = (
        ("silence", "🟡 {aid} im lặng quá {hours} giờ — chưa có lượt đăng/bình luận thành công nào gần đây."),
        ("session_expiring_soon", "🟡 {aid}: phiên đăng nhập Facebook sắp hết hạn (dưới {days} ngày) — cần đăng nhập lại sớm."),
        ("session_expired", "🔴 {aid}: phiên đăng nhập Facebook ĐÃ HẾT HẠN — cần đăng nhập lại ngay."),
        ("session_unreadable", "🔴 {aid}: không đọc được phiên đăng nhập Facebook (chưa đăng nhập/file hỏng) — cần đăng nhập lại."),
    )
    while True:
        try:
            # Self-heal (self-review follow-up) for the one-shot
            # fire-and-forget telegram_notify.refresh_bot_username() call
            # at service startup — if THAT attempt failed (a transient
            # network blip exactly at boot), retry here every 6h rather
            # than leaving the admin tab's bot link stuck on its
            # plain-text fallback for the service's entire uptime. The
            # `get_cached_bot_username()` guard means this never re-calls
            # Telegram once it has already succeeded once.
            if not telegram_notify.get_cached_bot_username():
                await telegram_notify.refresh_bot_username()
            last_success_map = db.last_successful_action_per_account()
            for aid, account in get_all_accounts().items():
                # Isolated per-account (2026-10-05 self-review, round 4) —
                # same pattern _resume_cooldown_maintenance_loop already
                # uses: one account's bad data must not skip every OTHER
                # account's check for this entire 6-hour cycle too.
                # _account_warning_status() itself already isolates its
                # own 2 independent sub-checks (round 5), so this outer
                # try is now mostly a safety net for anything unexpected
                # in the alert-sending loop below.
                try:
                    warnings_now = _account_warning_status(aid, account, last_success_map).kinds
                    previously = last_warned.get(aid, set())
                    new_warnings = warnings_now - previously
                    for kind, template in alert_texts:
                        if kind in new_warnings:
                            await telegram_notify.send_message(
                                template.format(aid=aid, hours=_SILENCE_WARNING_HOURS, days=_SESSION_EXPIRY_WARNING_DAYS),
                                silent=False,
                            )
                    last_warned[aid] = warnings_now
                except Exception:  # noqa: BLE001 - one bad account must not skip the rest
                    logger.exception("_telegram_health_check_loop failed for account %s", aid)
        except Exception:  # noqa: BLE001 - one bad scan must not kill the loop
            logger.exception("_telegram_health_check_loop failed")
        await asyncio.sleep(_TELEGRAM_HEALTH_CHECK_INTERVAL_SECONDS)


async def _telegram_listen_loop() -> None:
    """Background loop: long-polls Telegram for messages sent to the bot
    (human_bot/telegram_notify.py's get_updates()) and replies to ANY of
    them — ANY message type, not just text (round 5 fix: a prior version
    required `message.get("text")`, so a sticker/photo/voice note got
    silently ignored, contradicting this v1's own "no slash-command
    parsing... nhắn gì cũng được" design) — with the same health
    snapshot /admin's home page shows, one account per line-block
    (human_bot.admin._account_health_telegram_text()), sent back ONLY to
    the chat that asked (telegram_notify.send_message_to(), not a
    broadcast) — someone else registered doesn't need to see every
    query another recipient makes. Ignores messages from any chat not
    currently in human_bot/runtime_config.py's get_telegram_recipients()
    (2026-10-05, admin-managed list at /admin/telegram — replaces the
    original single hardcoded TELEGRAM_CHAT_ID env var) — otherwise
    anyone who discovers the bot's username could query it too. Reread
    EVERY poll cycle (not once outside the loop) so a recipient added
    via /admin while the service is already running can query
    immediately, no restart needed.

    get_updates() itself no-ops instantly (empty list, no network call)
    when Telegram isn't configured/enabled, so this loop doesn't bother
    pre-checking is_configured() itself (round 5 — a prior version did,
    which just meant reading runtime_config.json from disk twice every
    iteration for the same answer get_updates() already re-derives
    internally). It ALSO returns near-instantly (still [], but via a
    real failed network call this time) on a broken token/network error
    — either way, and ALSO when real messages arrive but none of them
    match a registered chat id (round 5 — a stranger who discovered the
    bot's username spamming it would otherwise keep this loop spinning
    with zero delay, since `updates` being non-empty used to be enough
    to skip the idle sleep even though nothing was actually replied to),
    this loop must sleep itself rather than relying on get_updates()'s
    own long-poll timeout for pacing, or it busy-spins the event loop
    (pegging a CPU core, hammering Telegram) whenever a genuine ~30s
    long-poll never actually happens (see _TELEGRAM_LISTEN_MIN_POLL_SECONDS)."""
    offset: int | None = None
    while True:
        try:
            poll_started_at = time.monotonic()
            updates = await telegram_notify.get_updates(offset)
            # Only looked up when there's actually something to match
            # against — get_updates() already no-ops instantly (no disk
            # read, no network call) when not configured, and computing
            # this unconditionally every idle ~30s cycle would reopen and
            # re-parse runtime_config.json for nothing, the same
            # redundant-read problem this function's own docstring says
            # was fixed for is_configured() (self-review follow-up).
            # Reread fresh on every batch that needs it (not cached
            # across iterations) — see this function's own docstring for
            # why (a recipient added via /admin must work next cycle).
            registered_chat_ids = {r["chat_id"] for r in get_telegram_recipients()} if updates else set()
            # Computed at most once per poll cycle (round 4), not once
            # per matching message — a user sending several messages
            # before the previous long-poll returns would otherwise
            # re-run these same DB/file reads and rebuild the identical
            # reply once per message. None until the first valid message
            # in this batch needs it (most polls return 0 updates, or
            # updates from an unregistered chat, so skip the work
            # entirely then).
            reply = None
            replied_to_anything = False
            for update in updates:
                offset = update["update_id"] + 1
                # A Telegram CHANNEL delivers its posts as "channel_post",
                # never "message" (self-review follow-up) — without this,
                # a channel the bot was added to as admin could never be
                # discovered as a pending sender at all, defeating the
                # whole point of this feature for that one chat type.
                message = update.get("message") or update.get("channel_post") or {}
                chat = message.get("chat") or {}
                chat_id = str(chat.get("id", ""))
                if chat_id not in registered_chat_ids:
                    # Not a reply target, but still worth remembering —
                    # the admin UI offers a one-click "➕ Thêm" for anyone
                    # here (see telegram_notify.record_pending_sender()'s
                    # own docstring for why this exists: nobody but the
                    # owner should ever need to know TELEGRAM_BOT_TOKEN
                    # to find a chat_id). A group/channel's `title` is
                    # the more useful name to show than the individual
                    # member who happened to send this one message.
                    sender = message.get("from") or {}
                    name = (
                        chat.get("title")
                        or " ".join(p for p in (sender.get("first_name"), sender.get("last_name")) if p)
                        or (f"@{sender['username']}" if sender.get("username") else "")
                        or chat_id
                    )
                    if chat_id:
                        telegram_notify.record_pending_sender(chat_id, name)
                    continue
                # Isolated per-message (round 4) — a failure building/
                # sending the reply to ONE message (e.g. a DB hiccup)
                # must not also abort every OTHER valid message already
                # advanced past in this same batch.
                try:
                    if reply is None:
                        sync_statuses = data_sync.get_all_sync_statuses()
                        last_success_map = db.last_successful_action_per_account()
                        accounts = get_all_accounts()
                        reply = "\n\n".join(
                            _account_health_telegram_text(aid, a, sync_statuses, last_success_map)
                            for aid, a in accounts.items()
                        ) or "Chưa có tài khoản nào."
                    await telegram_notify.send_message_to(chat_id, reply, silent=True)
                    replied_to_anything = True
                except Exception:  # noqa: BLE001 - one bad reply must not skip the rest of this batch
                    logger.exception("_telegram_listen_loop failed to reply to update %s", update.get("update_id"))
            # A genuine long-poll either blocks close to _POLL_TIMEOUT, or
            # returns near-instantly because a message this loop actually
            # replied to was already waiting — any OTHER fast return
            # (not configured, a broken token/network error, or real
            # traffic that never matched a registered chat id) is the
            # ambiguous case the idle sleep guards against; gating on
            # `replied_to_anything` rather than bare `updates` (round 5)
            # keeps back-to-back REAL queries from being throttled by
            # this same guard, while still catching the "non-empty but
            # nothing relevant" case round 4 missed.
            if not replied_to_anything and time.monotonic() - poll_started_at < _TELEGRAM_LISTEN_MIN_POLL_SECONDS:
                await asyncio.sleep(_TELEGRAM_LISTEN_IDLE_SLEEP_SECONDS)
        except Exception:  # noqa: BLE001 - one bad poll cycle must not kill the loop
            logger.exception("_telegram_listen_loop failed")
            await asyncio.sleep(5)  # avoid a tight error loop hammering Telegram


def _missing_auth_env_vars() -> list[str]:
    """.env is gitignored, so cloning/redeploying this project to a new
    machine starts with NONE of these set — and _require_auth()/
    _require_tasks_auth() both silently skip their check entirely when
    that happens (convenient for local dev, dangerous anywhere else)."""
    return [
        name for name in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "TASKS_API_KEY")
        if not os.environ.get(name, "").strip()
    ]


def _warn_if_auth_unconfigured() -> list[str]:
    """Logs (does not print/prompt) a warning listing which of the 3 auth
    env vars are missing, if any. Returns that same list so callers (the
    interactive confirmation below) don't need to recompute it. Always
    safe to call on its own — never blocks, never raises."""
    missing = _missing_auth_env_vars()
    if missing:
        logger.warning(
            "SECURITY: %s not set in .env — /admin and/or POST /tasks are running with NO "
            "authentication. Fine for local-only use; set these in .env before this service "
            "is reachable from anywhere else.",
            ", ".join(missing),
        )
    return missing


def _get_or_create_session_secret() -> str:
    """Key used to sign the /admin login-session cookie (Starlette's
    SessionMiddleware, added 2026-09-24 alongside the real login page that
    replaced Basic Auth — see human_bot/admin.py's _require_login()).

    Unlike ADMIN_USERNAME/ADMIN_PASSWORD/TASKS_API_KEY above, a missing
    SESSION_SECRET_KEY is NOT treated as an open security hole worth an
    interactive abort prompt — it only means sessions can't survive a
    restart (a UX papercut: everyone gets logged out), not that anyone
    unauthenticated gets in. So this generates a fresh random key at
    every process startup instead (secrets.token_hex(32) — same entropy
    class as a real secret should have) and just logs a lighter warning
    recommending a persistent value be set in .env."""
    configured = os.environ.get("SESSION_SECRET_KEY", "").strip()
    if configured:
        return configured
    logger.warning(
        "SECURITY: SESSION_SECRET_KEY not set in .env — using a random ephemeral key for "
        "this run only. Every /admin login session will be invalidated the next time this "
        "service restarts. Set SESSION_SECRET_KEY in .env for sessions that survive a restart."
    )
    return secrets.token_hex(32)


def _confirm_startup_or_abort(missing: list[str]) -> None:
    """Interactive y/n gate for the auth-missing case — requested
    2026-09-10 after the project owner asked for a way to not silently
    miss the warning above (which only ever went to logs/human_bot.log,
    invisible unless someone goes and reads that file). Only prompts when
    stdin is an actual terminal (`sys.stdin.isatty()`): a detached/
    backgrounded deployment (systemd, Docker, `nohup ... &`, CI) has no
    one to answer a prompt, and blocking forever on `input()` there would
    turn a security reminder into a hung service — those keep the
    log-only warning above and continue unattended, exactly like before
    this feature existed. Defaults to abort (anything other than a typed
    "y", including Ctrl-D/EOF, refuses to start) — the safe default for a
    prompt about running with no authentication at all."""
    if not missing:
        return
    if not sys.stdin.isatty():
        return
    print(
        f"\n⚠️  SECURITY: {', '.join(missing)} chưa được đặt trong .env — "
        f"/admin và/hoặc POST /tasks sẽ chạy KHÔNG có xác thực nào.\n"
        f"Chỉ nên tiếp tục nếu service này KHÔNG ai khác chạm tới được ngoài bạn "
        f"(chỉ chạy trên máy cá nhân).\n",
        file=sys.stderr,
    )
    try:
        answer = input("Vẫn tiếp tục khởi động? [y/N]: ").strip().lower()
    except EOFError:
        answer = ""
    if answer != "y":
        print("Đã dừng khởi động — đặt các biến trên trong .env rồi chạy lại.", file=sys.stderr)
        raise RuntimeError(
            f"Startup aborted: {', '.join(missing)} not set in .env (answer 'y' at the "
            f"prompt, or set them, to proceed)"
        )


@asynccontextmanager
async def lifespan(app: FastAPI):
    _confirm_startup_or_abort(_warn_if_auth_unconfigured())
    # ONE-TIME sweep, before the recurring fire-due-tasks loop gets its
    # first turn (see data_sync.sweep_overdue_on_startup()'s docstring) —
    # so a task left over from before the service was down doesn't get
    # auto-fired the instant it comes back up; it waits in schedule_store's
    # missed/ for an admin to review at /admin/schedule instead.
    swept = data_sync.sweep_overdue_on_startup()
    if swept["swept"]:
        logger.warning(
            "sweep_overdue_on_startup: moved %d pending task(s) to missed/ for admin review "
            "(scheduled_at already past as of %s)", swept["swept"], swept["checked_at"],
        )
    # ONE-TIME migration (2026-10-05, same "do it once at startup" spot as
    # sweep_overdue_on_startup() above) — seeds the legacy single
    # TELEGRAM_CHAT_ID env var into the new admin-managed recipients list
    # (/admin/accounts's "Tài khoản Telegram" tab) the first time this
    # runs after the upgrade, so an owner who already set that up keeps
    # receiving alerts with no manual step. See
    # runtime_config.migrate_legacy_telegram_chat_id_once()'s own docstring.
    runtime_config.migrate_legacy_telegram_chat_id_once()
    # Fire-and-forget (self-review follow-up) — caches the bot's own
    # @username so the admin tab can link straight to its Telegram chat
    # instead of just describing it in words (telegram_notify.
    # refresh_bot_username()'s own docstring). NOT awaited here: this is
    # a purely cosmetic lookup with a working plain-text fallback
    # already in place, so it must never add Telegram's own network
    # latency (up to its 15s timeout) to the service's startup — every
    # other non-critical startup concern already runs as a background
    # task rather than blocking `yield`, this just matches that.
    # _telegram_health_check_loop() retries this on its own 6h cadence
    # (only while still uncached) if this first attempt fails.
    asyncio.create_task(telegram_notify.refresh_bot_username())
    active_accounts = [a for a in get_all_accounts().values() if a.status == AccountStatus.ACTIVE]
    await warm_up(active_accounts)
    poll_task = asyncio.create_task(_data_sync_poll_loop())
    fire_task = asyncio.create_task(_data_sync_fire_loop())
    cleanup_task = asyncio.create_task(_schedule_cleanup_loop())
    screenshot_cleanup_task = asyncio.create_task(_screenshot_cleanup_loop())
    resume_cooldown_task = asyncio.create_task(_resume_cooldown_maintenance_loop())
    telegram_health_task = asyncio.create_task(_telegram_health_check_loop())
    telegram_listen_task = asyncio.create_task(_telegram_listen_loop())
    yield
    poll_task.cancel()
    fire_task.cancel()
    cleanup_task.cancel()
    screenshot_cleanup_task.cancel()
    resume_cooldown_task.cancel()
    telegram_health_task.cancel()
    telegram_listen_task.cancel()
    for t in (
        poll_task,
        fire_task,
        cleanup_task,
        screenshot_cleanup_task,
        resume_cooldown_task,
        telegram_health_task,
        telegram_listen_task,
    ):
        try:
            await t
        except asyncio.CancelledError:
            pass
    await close_all()


app = FastAPI(title="human_bot", lifespan=lifespan)

# /admin login session cookie (2026-09-24) — see _get_or_create_session_secret()'s
# docstring and human_bot/admin.py's _require_login()/_current_role(). Added
# unconditionally (regardless of whether ADMIN_USERNAME/PASSWORD are set, i.e.
# regardless of whether login is actually "on") — the middleware itself is
# cheap and harmless when unused; the on/off toggle lives entirely in
# admin.py's _is_login_configured(), not here.
app.add_middleware(
    SessionMiddleware,
    secret_key=_get_or_create_session_secret(),
    session_cookie="human_bot_admin_session",
    max_age=14 * 24 * 60 * 60,  # 14 days — owner's explicit choice, 2026-09-24
    same_site="lax",
    # This project's own long-standing threat model (see this file's module
    # docstring above): /admin is for local/trusted-network use only, never
    # exposed unauthenticated to the public internet. If that ever changes
    # and this sits behind real TLS, flip this to True.
    https_only=False,
)


@app.exception_handler(NotLoggedIn)
async def _handle_not_logged_in(request: Request, exc: NotLoggedIn) -> Response:
    """A route's _require_login()/_require_admin_role() dependency raises
    this instead of returning a redirect directly (a FastAPI Depends()
    can't itself short-circuit a route with an arbitrary response — an
    exception + handler is the standard way). Two different responses
    depending on how the request arrived:
    - A normal browser navigation (no session / session revoked) gets a
      real 303 redirect to the login page.
    - An htmx-driven request (clicking a button that does an hx-post/hx-get
      partway through the page) gets an HX-Redirect header instead — a
      plain 303 here would make htmx try to swap the login page's HTML
      into whatever small target div triggered the request, which reads
      as a broken UI rather than "please log in again". HX-Redirect tells
      htmx to do a full top-level navigation instead."""
    login_url = "/admin/login"
    if exc.next_path:
        login_url += "?next=" + quote(exc.next_path, safe="")
    if request.headers.get("hx-request") == "true":
        return Response(status_code=200, headers={"HX-Redirect": login_url})
    return RedirectResponse(login_url, status_code=303)


app.include_router(admin_router)


class TaskIn(BaseModel):
    action: str
    account_id: str
    target_url: str | None = None
    content: str | None = None
    media_path: str | None = None
    audience: str = "public"
    reasoning: str = ""


class TaskOut(BaseModel):
    success: bool
    message: str
    screenshot_path: str | None
    timestamp: str


# Done 2026-09-04 (was a TODO here since 2026-09-03): API key check via a
# required header, same "skip auth entirely if not configured" convenience
# as human_bot/admin.py's _require_auth (ADMIN_USERNAME/ADMIN_PASSWORD) —
# handy for local/dev use before TASKS_API_KEY is set, but MUST be set
# before this port is reachable from anywhere other than your own trusted
# machine/network (n8n, a data-fetching service, etc. all need to send the
# same key back in X-API-Key once this is on).
def _require_tasks_auth(x_api_key: str | None = Header(default=None)) -> None:
    expected = os.environ.get("TASKS_API_KEY", "").strip()
    if not expected:
        # Not configured — same permissive default as /admin when
        # ADMIN_USERNAME/ADMIN_PASSWORD are unset. Fine for local/dev, not
        # for anything reachable beyond your own machine.
        return
    if not x_api_key or not secrets.compare_digest(x_api_key, expected):
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="missing or invalid X-API-Key",
        )


@app.post("/tasks", response_model=TaskOut, dependencies=[Depends(_require_tasks_auth)])
async def create_task(task: TaskIn) -> TaskOut:
    request = TaskRequest(**task.model_dump())
    result = await run_task(request)
    return TaskOut(**result.__dict__)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "accounts": list(get_all_accounts().keys())}
