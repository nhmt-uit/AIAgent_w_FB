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

from fastapi import Depends, FastAPI, Header, HTTPException, status  # noqa: E402
from pydantic import BaseModel  # noqa: E402

import asyncio  # noqa: E402
import logging  # noqa: E402
import os  # noqa: E402
import secrets  # noqa: E402
import sys  # noqa: E402
from datetime import datetime, timezone  # noqa: E402

from human_bot import data_sync, schedule_store, screenshots  # noqa: E402
from human_bot.admin import router as admin_router  # noqa: E402
from human_bot.agent import TaskRequest, run_task  # noqa: E402
from human_bot.browser_pool import close_all, warm_up  # noqa: E402
from human_bot.config import AccountStatus, get_all_accounts  # noqa: E402
from human_bot.logging_setup import configure_logging  # noqa: E402
from human_bot.runtime_config import (  # noqa: E402
    get_active_cooldown_rate_limits,
    get_all_active_cooldown_account_ids,
    get_config_changed_event,
    get_data_sync_config,
    get_sync_disabled_account_ids,
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
    human_bot.db regardless (human_bot/db.py), so this never loses
    anything /admin/reports can show."""
    while True:
        try:
            schedule_store.cleanup_old()
        except Exception:  # noqa: BLE001 - a cleanup failure must not take down posting
            logger.exception("schedule_store.cleanup_old failed")
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
    active_accounts = [a for a in get_all_accounts().values() if a.status == AccountStatus.ACTIVE]
    await warm_up(active_accounts)
    poll_task = asyncio.create_task(_data_sync_poll_loop())
    fire_task = asyncio.create_task(_data_sync_fire_loop())
    cleanup_task = asyncio.create_task(_schedule_cleanup_loop())
    screenshot_cleanup_task = asyncio.create_task(_screenshot_cleanup_loop())
    resume_cooldown_task = asyncio.create_task(_resume_cooldown_maintenance_loop())
    yield
    poll_task.cancel()
    fire_task.cancel()
    cleanup_task.cancel()
    screenshot_cleanup_task.cancel()
    resume_cooldown_task.cancel()
    for t in (poll_task, fire_task, cleanup_task, screenshot_cleanup_task, resume_cooldown_task):
        try:
            await t
        except asyncio.CancelledError:
            pass
    await close_all()


app = FastAPI(title="human_bot", lifespan=lifespan)
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
