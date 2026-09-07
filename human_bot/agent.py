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
from dataclasses import dataclass, replace
from datetime import datetime, timezone
from typing import Awaitable, Callable

from human_bot import actions, db, media, screenshots
from human_bot.actions import ActionResult, _group_id_from_url
from human_bot.browser_pool import get_session
from human_bot.config import AccountStatus, get_account
from human_bot.runtime_config import get_joined_groups, get_media_config, set_account_paused
from human_bot.safety import AnomalyDetected, RateLimiter
from playwright.async_api import Page

# Actions whose actions.py function even accepts a media_path — comment/
# like actions don't, so the random-meme auto-fill below (and side B's own
# image, once that's wired in data_sync.py) only ever apply to these two.
_MEDIA_CAPABLE_ACTIONS = {"post_to_own_profile", "post_to_group"}


@dataclass
class TaskRequest:
    action: str  # see _ACTION_DISPATCH keys below
    account_id: str
    target_url: str | None = None  # group/post URL; not needed for post_to_own_profile
    content: str | None = None
    media_path: str | None = None
    reasoning: str = ""
    # Where this task originated — recorded alongside every action in
    # human_bot/db.py's action_log so /admin/reports can tell manual clicks
    # apart from automated ones. "api" is the default because the most
    # common untagged caller is POST /tasks (n8n or anything else hitting
    # the HTTP API directly) — human_bot/admin.py and human_bot/data_sync.py
    # set a more specific value at each of their own call sites.
    source: str = "api"  # manual | queue | schedule_manual | schedule_auto | api
    source_kind: str | None = None  # "job" | "candidate" — only set for data-sync-originated tasks
    source_id: str | None = None  # side B's own record id, for traceability


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
        lambda page, req: actions.post_to_group(
            page, req.target_url, req.content, req.media_path,
            group_name=_resolve_group_name(req.account_id, req.target_url),
        ),
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


def _resolve_group_name(account_id: str, url: str | None) -> str | None:
    """Best-effort lookup of a group's display name from /admin/groups'
    saved list, purely for readability in action_log (e.g. so a report
    shows "Nhóm IT Nhật Bản" instead of a bare URL) and as the search
    query text for post_to_group's Tier 3. Never let this fail the actual
    task — any error here just means the log row has no name / Tier 3 gets
    skipped.

    Matches by the group id/slug (via actions._group_id_from_url), NOT by
    exact URL string equality — fixed 2026-09-04 after a real miss: a
    group saved in /admin/groups as ".../groups/1383875949915495" (no
    trailing slash) didn't match a task's target_url of
    ".../groups/1383875949915495/" (with one), even though it's obviously
    the same group. Comparing on id/slug is the same normalization
    already used for the actual navigation safety-check in
    actions.py's _click_group_by_id/_confirms_group, so this now agrees
    with what post_to_group itself considers "the same group"."""
    if not url:
        return None
    target_id = _group_id_from_url(url)
    try:
        for g in get_joined_groups(account_id):
            if g.url == url or (target_id and _group_id_from_url(g.url) == target_id):
                return g.name or None
    except Exception:  # noqa: BLE001 — logging metadata, never worth failing the task over
        pass
    return None


def _log_result(request: TaskRequest, success: bool, message: str, screenshot_path: str | None = None) -> None:
    """Best-effort write to human_bot/db.py's action_log — every return
    path in run_task() calls this, including the early-exit failures
    (paused account, unsupported action, rate limited), so /admin/reports
    sees the full picture, not just successful posts. A logging failure
    must never surface as a task failure."""
    try:
        db.log_action(
            account_id=request.account_id,
            action=request.action,
            success=success,
            message=message,
            target_url=request.target_url,
            target_group_name=_resolve_group_name(request.account_id, request.target_url),
            content=request.content,
            source=request.source,
            source_kind=request.source_kind,
            source_id=request.source_id,
            screenshot_path=screenshot_path,
        )
    except Exception:  # noqa: BLE001 — see docstring
        pass


async def run_task(request: TaskRequest) -> TaskResult:
    account = get_account(request.account_id)

    if account.status != AccountStatus.ACTIVE:
        message = f"account_paused:{request.account_id}"
        _log_result(request, False, message)
        return TaskResult(
            success=False,
            message=message,
            screenshot_path=None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    if request.action not in _ACTION_DISPATCH:
        message = f"unsupported_action:{request.action}"
        _log_result(request, False, message)
        return TaskResult(
            success=False,
            message=message,
            screenshot_path=None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )
    rate_limit_bucket, action_fn = _ACTION_DISPATCH[request.action]

    # Auto-attach a random meme when the caller didn't already supply a
    # media_path — added 2026-09-04. Explicit always wins: if this
    # TaskRequest came with its own media_path (a caller-attached image,
    # or — once data_sync.py maps it — an image side B sent along with a
    # job), that's left untouched and never overridden by a random pick.
    # Only applies to actions that actually take a media_path at all (see
    # _MEDIA_CAPABLE_ACTIONS above) and only when the global toggle at
    # /admin/config is on (default: on — see human_bot/runtime_config.py's
    # get_attach_random_meme_default() and media/memes/README.md).
    if (
        request.media_path is None
        and request.action in _MEDIA_CAPABLE_ACTIONS
        and get_media_config().attach_random_meme_default
    ):
        request = replace(request, media_path=media.pick_random_meme())

    limiter = RateLimiter(account)
    allowed, reason = limiter.can_proceed(rate_limit_bucket)
    if not allowed:
        message = f"rate_limited:{reason}"
        _log_result(request, False, message)
        return TaskResult(
            success=False,
            message=message,
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
    except AnomalyDetected as e:
        # This is what makes docs/skills/anomaly-detection.md's "never
        # retry past this point" actually true, instead of just aborting
        # this one attempt and letting the account get tried again next
        # time as if nothing happened. Persisted via runtime_config.json
        # so it survives a service restart too — stays paused until a
        # human reviews and resumes it at /admin/accounts.
        message = str(e)
        try:
            set_account_paused(request.account_id, True)
        except Exception:  # noqa: BLE001 — the task must still return a result even if this write fails
            pass
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

    # Evidence screenshot — success or failure — taken here, not inside
    # each actions.py function, for the same "one choke point" reason as
    # db.log_action() above: session.page is whatever state the action
    # left it in (the browser page persists; nothing closes it), so this
    # is close enough to the actual moment of success/failure without
    # needing every action function to know about screenshots at all.
    # None when there's no page to shoot from (an early-exit failure
    # above — paused account, unsupported action, rate limited — none of
    # which ever opened a browser).
    screenshot_path = None
    if session is not None and session.page is not None:
        screenshot_path = await screenshots.capture(session.page, request.account_id, request.action, success)

    _log_result(request, success, message, screenshot_path)
    return TaskResult(
        success=success,
        message=message,
        screenshot_path=screenshot_path,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
