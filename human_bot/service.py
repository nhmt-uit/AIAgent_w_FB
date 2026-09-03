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
"""
from __future__ import annotations

from contextlib import asynccontextmanager
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from fastapi import FastAPI  # noqa: E402
from pydantic import BaseModel  # noqa: E402

from human_bot.admin import router as admin_router  # noqa: E402
from human_bot.agent import TaskRequest, run_task  # noqa: E402
from human_bot.browser_pool import close_all, warm_up  # noqa: E402
from human_bot.config import ACCOUNTS, AccountStatus  # noqa: E402


@asynccontextmanager
async def lifespan(app: FastAPI):
    active_accounts = [a for a in ACCOUNTS.values() if a.status == AccountStatus.ACTIVE]
    await warm_up(active_accounts)
    yield
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


# TODO (2026-09-03): this endpoint has NO authentication — any request that
# can reach this port can post to Facebook for real, for any registered
# account. Fine while everything calling in is on the same machine/trusted
# network; add an API key check (a required header, compared with
# secrets.compare_digest against an env var — same pattern as
# human_bot/admin.py's _require_auth) before any other system (e.g. a
# separate data-fetching service sending post content as JSON) is allowed
# to call this from outside that trust boundary.
@app.post("/tasks", response_model=TaskOut)
async def create_task(task: TaskIn) -> TaskOut:
    request = TaskRequest(**task.model_dump())
    result = await run_task(request)
    return TaskOut(**result.__dict__)


@app.get("/health")
async def health() -> dict:
    return {"status": "ok", "accounts": list(ACCOUNTS.keys())}
