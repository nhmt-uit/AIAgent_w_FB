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

from human_bot import data_sync, schedule_store  # noqa: E402
from human_bot.admin import router as admin_router  # noqa: E402
from human_bot.agent import TaskRequest, run_task  # noqa: E402
from human_bot.browser_pool import close_all, warm_up  # noqa: E402
from human_bot.config import AccountStatus, get_all_accounts  # noqa: E402
from human_bot.runtime_config import get_data_sync_config  # noqa: E402

SCHEDULE_CLEANUP_INTERVAL_SECONDS = 24 * 60 * 60

logger = logging.getLogger("human_bot.service")


async def _data_sync_poll_loop() -> None:
    """Background loop: periodically pull new jobs/candidates from side B,
    dedupe, and schedule them (human_bot/data_sync.py). Runs inside this
    already-24/7 process rather than as a separate cron job — see
    docs/architecture.md section 3c. Never lets one bad cycle kill the
    loop: side B being briefly unreachable, or one malformed record,
    should not take down posting for the rest of the process."""
    while True:
        cfg = get_data_sync_config()
        if cfg.enabled:
            active_accounts = [a for a in get_all_accounts().values() if a.status == AccountStatus.ACTIVE]
            for account in active_accounts:
                try:
                    await data_sync.sync_once(account.account_id, cfg)
                except Exception:  # noqa: BLE001 - one account's failure must not stop the others
                    logger.exception("data_sync.sync_once failed for account_id=%s", account.account_id)
        await asyncio.sleep(max(cfg.poll_interval_minutes, 1.0) * 60)


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
    ngay' button for the safe-by-default alternative."""
    while True:
        cfg = get_data_sync_config()
        try:
            await data_sync.fire_due_tasks()
        except Exception:  # noqa: BLE001 - keep the loop alive across failures
            logger.exception("data_sync.fire_due_tasks failed")
        await asyncio.sleep(max(cfg.due_check_interval_seconds, 5.0))


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


@asynccontextmanager
async def lifespan(app: FastAPI):
    active_accounts = [a for a in get_all_accounts().values() if a.status == AccountStatus.ACTIVE]
    await warm_up(active_accounts)
    poll_task = asyncio.create_task(_data_sync_poll_loop())
    fire_task = asyncio.create_task(_data_sync_fire_loop())
    cleanup_task = asyncio.create_task(_schedule_cleanup_loop())
    yield
    poll_task.cancel()
    fire_task.cancel()
    cleanup_task.cancel()
    for t in (poll_task, fire_task, cleanup_task):
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
