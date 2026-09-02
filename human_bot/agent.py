"""
human_bot Executor entry point: turns one TaskRequest into one TaskResult.

Dispatches DIRECTLY to the matching Python function in human_bot/actions.py
by action name — no LLM involved in deciding what to do (see that module's
docstring for why: the steps are already fully known from a Codegen
recording, so there is nothing for an AI to figure out). Uses the
persistent per-account browser from human_bot/browser_pool.py (launched
once, kept open 24/7) rather than opening/closing a browser per task.

See docs/agents/human-bot-executor.md for the full behavior contract and
docs/skills/facebook-custom-actions.md for what each action name maps to.
"""
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Awaitable, Callable

from human_bot import actions
from human_bot.actions import ActionResult
from human_bot.browser_pool import get_session
from human_bot.config import AccountStatus, get_account
from human_bot.safety import RateLimiter
from playwright.async_api import Page


@dataclass
class TaskRequest:
    action: str  # see _ACTION_DISPATCH keys below
    account_id: str
    target_url: str | None = None  # group/post URL; not needed for post_to_own_profile
    content: str | None = None
    media_path: str | None = None
    reasoning: str = ""


@dataclass
class TaskResult:
    success: bool
    message: str
    screenshot_path: str | None
    timestamp: str


# Maps a Task JSON `action` value to: (rate-limit bucket, the actions.py
# function to call). Keep this in sync with
# docs/skills/facebook-custom-actions.md and docs/agents/content-strategist.md.
_ACTION_DISPATCH: dict[str, tuple[str, Callable[[Page, TaskRequest], Awaitable[ActionResult]]]] = {
    "post_to_own_profile": (
        "post",
        lambda page, req: actions.post_to_own_profile(page, req.content, req.media_path),
    ),
    "post_to_group": (
        "post",
        lambda page, req: actions.post_to_group(page, req.target_url, req.content, req.media_path),
    ),
    "comment_on_friend_post": (
        "comment",
        lambda page, req: actions.comment_on_friend_post(page, req.target_url, req.content),
    ),
    "comment_on_group_post": (
        "comment",
        lambda page, req: actions.comment_on_group_post(page, req.target_url, req.content),
    ),
    "like_post": (
        "like",
        lambda page, req: actions.like_post(page, req.target_url),
    ),
}


async def run_task(request: TaskRequest) -> TaskResult:
    account = get_account(request.account_id)

    if account.status != AccountStatus.ACTIVE:
        return TaskResult(
            success=False,
            message=f"account_paused:{request.account_id}",
            screenshot_path=None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    if request.action not in _ACTION_DISPATCH:
        return TaskResult(
            success=False,
            message=f"unsupported_action:{request.action}",
            screenshot_path=None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    rate_limit_bucket, action_fn = _ACTION_DISPATCH[request.action]

    limiter = RateLimiter(account)
    allowed, reason = limiter.can_proceed(rate_limit_bucket)
    if not allowed:
        return TaskResult(
            success=False,
            message=f"rate_limited:{reason}",
            screenshot_path=None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    success = False
    message = ""
    session = None
    try:
        session = get_session(account)
        await session.ensure_started()
        result = await action_fn(session.page, request)
        success = result.success
        message = result.message
    except Exception as e:  # noqa: BLE001 — surfaced to caller as a failed TaskResult
        message = f"error:{e}"
    finally:
        # Save the login session (cookies/localStorage) right after every
        # task, not only when the service shuts down cleanly. This is what
        # protects against losing a session on Ctrl+C / crash / kill -9 —
        # see human_bot/browser_pool.py's save_state() for why a
        # shutdown-only save is not reliable enough on its own.
        if session is not None:
            await session.save_state()
        limiter.record(rate_limit_bucket, success)
        # Deliberate paced delay before this account's NEXT action — see
        # docs/skills/rate-limiting-pacing.md. In production this should be
        # a scheduling delay on the n8n side, not a blocking sleep here.
        # limiter.jittered_delay()

    return TaskResult(
        success=success,
        message=message,
        screenshot_path=None,  # TODO: capture a screenshot on failure for debugging
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
