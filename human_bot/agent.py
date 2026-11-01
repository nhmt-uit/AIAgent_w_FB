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

from human_bot import actions, daily_limits, db, media, screenshots, telegram_notify
from human_bot.actions import ActionResult, _group_id_from_url
from human_bot.browser_pool import get_session
from human_bot.config import get_all_accounts, AccountStatus, get_account
from human_bot.runtime_config import get_joined_groups, get_media_config, set_account_paused
from human_bot.safety import AnomalyDetected, RateLimiter
from playwright.async_api import Page

# Actions whose actions.py function even accepts a media_path — comment/
# like actions don't, so the random-meme auto-fill below (and side B's own
# image, once that's wired in data_sync.py) only ever apply to these two.
_MEDIA_CAPABLE_ACTIONS = {"post_to_own_profile", "post_to_group"}

# "N lần fail liên tiếp" Telegram alert threshold (2026-10-05, owner's
# request) — same (account_id, action) failing this many times in a row
# is treated as "something is actually broken", not 1 random blip.
_CONSECUTIVE_FAILURE_ALERT_THRESHOLD = 3


@dataclass
class TaskRequest:
    action: str  # see _ACTION_DISPATCH keys below
    account_id: str
    target_url: str | None = None  # group/post URL; not needed for post_to_own_profile
    content: str | None = None
    media_path: str | None = None
    # post_to_own_profile only — "public" (default) | "friends" | "only_me".
    # See actions.post_to_own_profile's docstring. Ignored by every other
    # action.
    audience: str = "public"
    reasoning: str = ""
    # Filled in by run_task() itself from the account (never by callers): the
    # Page this task must act as, "" for a personal account. Lets the
    # per-action identity guards in actions.py read it without re-resolving
    # the account.
    expected_page_name: str = ""
    # Where this task originated — recorded alongside every action in
    # human_bot/db.py's action_log so /admin/reports can tell manual clicks
    # apart from automated ones. "api" is the default because the most
    # common untagged caller is POST /tasks (n8n or anything else hitting
    # the HTTP API directly) — human_bot/admin.py and human_bot/data_sync.py
    # set a more specific value at each of their own call sites.
    source: str = "api"  # manual | queue | schedule_manual | schedule_auto | api
    source_kind: str | None = None  # "job" | "candidate" — only set for data-sync-originated tasks
    source_id: str | None = None  # side B's own record id, for traceability
    # Raw side-B job data (title/attributes — human_bot/schedule_store.py's
    # ScheduledTask.job_data) for job posts only (2026-09-12) — logged
    # alongside every per-group action_log row so /admin/reports' "theo
    # từng lần đăng" view can show the original data a job was drafted
    # from, not just what got posted. See db.log_action()'s docstring.
    job_data: dict | None = None
    # The action_log row id this task is a retry OF (2026-09-12) — see
    # human_bot/schedule_store.py's ScheduledTask.retry_of_log_id
    # docstring. Set by admin.py's reports_repost() ("Đăng ngay") directly,
    # or carried through from a ScheduledTask.retry_of_log_id for a task
    # fired via data_sync.py's fire_due_tasks()/admin.py's
    # schedule_fire_now() ("Đặt lịch"/"Lên lịch lại"). Logged onto the
    # resulting action_log row so /admin/reports can show "Đã đăng lại"/
    # "Đã lên lịch lại" instead of offering the same failed row again.
    retry_of_log_id: int | None = None
    # Admin-confirmed override of the min-gap pacing check ONLY (see
    # human_bot/safety.py's RateLimiter.can_proceed(ignore_gap=...)) — set
    # by admin.py's schedule_fire_now() after the admin clicks "Vẫn đăng
    # ngay" on the rate-limit warning modal. Never set by data_sync.py's
    # auto-fire path. Hard per-day/per-hour count caps still apply
    # regardless of this flag.
    force_ignore_gap: bool = False


@dataclass
class TaskResult:
    success: bool
    message: str
    screenshot_path: str | None
    timestamp: str


# Page accounts whose "wrong identity" alert was already sent (in-memory) —
# one loud Telegram message per episode, not one per refused task.
_wrong_identity_alerted: set[str] = set()


# Maps a Task JSON `action` value to: (rate-limit bucket, the actions.py
# function to call). Keep this in sync with
# docs/skills/facebook-custom-actions.md and docs/agents/content-strategist.md.
_ACTION_DISPATCH: dict[str, tuple[str, Callable[[Page, TaskRequest], Awaitable[ActionResult]]]] = {
    "post_to_own_profile": (
        "post",
        lambda page, req: actions.post_to_own_profile(page, req.content, req.media_path, req.audience),
    ),
    "post_to_group": (
        "post",
        lambda page, req: actions.post_to_group(
            page, req.target_url, req.content, req.media_path,
            group_name=resolve_group_name(req.account_id, req.target_url),
        ),
    ),
    "comment_on_friend_post": (
        "comment",
        lambda page, req: actions.comment_on_friend_post(page, req.target_url, req.content),
    ),
    "comment_on_group_post": (
        "comment",
        lambda page, req: actions.comment_on_group_post(
            page, req.target_url, req.content,
            expected_page_name=req.expected_page_name,
        ),
    ),
    "like_post": (
        "like",
        lambda page, req: actions.like_post(page, req.target_url),
    ),
}


def rate_limit_bucket_for(action: str) -> str | None:
    """The RateLimiter bucket ("post" / "comment" / "like") a given
    TaskRequest.action falls into, per _ACTION_DISPATCH above — or None
    for an unknown action. Public wrapper so callers outside this module
    (data_sync.py's fire_due_tasks(), admin.py's schedule_fire_now())
    can look up the same bucket run_task() itself will use, e.g. to call
    human_bot.safety.rate_limit_wait_message(account, bucket) BEFORE
    attempting the task, without needing to know _ACTION_DISPATCH's
    (private) internal shape."""
    entry = _ACTION_DISPATCH.get(action)
    return entry[0] if entry else None


def resolve_group_name(account_id: str, url: str | None) -> str | None:
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
            target_group_name=resolve_group_name(request.account_id, request.target_url),
            content=request.content,
            source=request.source,
            source_kind=request.source_kind,
            source_id=request.source_id,
            job_data=request.job_data,
            retry_of_log_id=request.retry_of_log_id,
            screenshot_path=screenshot_path,
        )
    except Exception:  # noqa: BLE001 — see docstring
        pass


async def _notify_telegram_for_attempt(
    request: TaskRequest, success: bool, message: str, screenshot_path: str | None,
) -> None:
    """Called ONLY for a genuine attempt (run_task()'s 3 early-exit paths
    — paused/unsupported/rate_limited — never reached Facebook at all, so
    they're not "a post" to report) — must run AFTER _log_result() so the
    consecutive-failure count below includes this very attempt.
    telegram_notify's own functions are already best-effort/never-raise,
    so no extra try/except needed here."""
    target = request.target_url or "(tường cá nhân)"
    content_preview = (request.content or "").strip()
    if len(content_preview) > 300:
        content_preview = content_preview[:300] + "…"
    icon = "✅" if success else "❌"
    report = (
        f"{icon} {request.account_id} · {request.action}\n"
        f"Nhóm/Bài: {target}\n"
        f"Nội dung: {content_preview or '(không có)'}"
    )
    if not success:
        report += f"\nLý do: {message}"
    # Alert type 2/5 ("mọi lượt đăng") — ALWAYS silent, per owner's request.
    if screenshot_path:
        await telegram_notify.send_photo(screenshot_path, caption=report, silent=True)
    else:
        await telegram_notify.send_message(report, silent=True)

    # Alert type 3/5 ("N lần fail liên tiếp") — loud, fires exactly once
    # right when the streak reaches the threshold (see
    # db.consecutive_failure_streak()'s own docstring for why this can't
    # just check ">=").
    if not success:
        streak = db.consecutive_failure_streak(
            request.account_id, request.action, max_rows=_CONSECUTIVE_FAILURE_ALERT_THRESHOLD + 1,
        )
        if streak == _CONSECUTIVE_FAILURE_ALERT_THRESHOLD:
            await telegram_notify.send_message(
                f"🔴 {request.account_id} · {request.action} thất bại {streak} lần LIÊN TIẾP\n"
                f"Lần gần nhất: {message}",
                silent=False,
            )


def _owner_session_usable(account) -> bool:
    """A Page's owner exists and is a personal account — a fallback to the
    owner's session can only succeed if so (a retry would fail identically)."""
    owner = get_all_accounts().get(account.owner_account_id)
    return owner is not None and not owner.page_name and owner.status == AccountStatus.ACTIVE


@dataclass
class _Attempt:
    success: bool
    message: str
    screenshot_path: str | None
    anomaly_paused: bool
    action_started: bool


async def _run_attempt(
    request: TaskRequest, account, action_fn, rate_limit_bucket: str, limiter: RateLimiter, use_owner: bool,
) -> _Attempt:
    """ONE attempt at a task on ONE browser session: the account's own
    (`use_owner=False`) or, for a Page, its owner's with a switch to the Page
    and back (`use_owner=True`). run_task() calls this once, or twice when a
    Page in "auto" mode falls back (see PAGE_MODE_AUTO)."""
    success = False
    message = ""
    session = None
    lock_held = False
    switched_identity = False  # owner-session mode: this task changed the SHARED session's identity
    screenshot_path = None
    anomaly_paused = False  # suppresses the redundant per-attempt report below — see its use site
    action_started = False  # True once the real action was invoked (no fallback to another session after that)
    try:
        # Which browser session runs this task: normally the account's own; a
        # Page configured as "owner_session" borrows its owning personal
        # account's session (switching to the Page for the task and back).
        session_account = account
        if use_owner:
            session_account = get_all_accounts().get(account.owner_account_id)
        if session_account is None or (use_owner and session_account.page_name):
            message = f"page_owner_missing:{account.owner_account_id}"
        elif use_owner and session_account.status != AccountStatus.ACTIVE:
            # The owner is switched off: its login/session is not to be used.
            message = f"page_owner_off:{account.owner_account_id}"
        else:
            session = get_session(session_account)
            # One task at a time per browser page: the owner's session is shared
            # by the personal account and its Pages.
            await session.lock.acquire()
            lock_held = True
            await session.ensure_started()
            identity_problem = None
            if account.page_name:
                # A Page account must only ever act AS the Page — verified before
                # EVERY action (not cached per browser session: Facebook can flip
                # the active identity mid-session) and refused otherwise (see
                # actions.ensure_page_identity()).
                request = replace(request, expected_page_name=account.page_name)
                if use_owner:
                    switched_identity = True  # set first: even a half-done switch must be undone below
                    session.identity_dirty = True  # nothing may persist this session until it is verified personal again
                    identity_problem = await actions.switch_to_identity(session.page, account.page_name)
                    if identity_problem is not None and identity_problem.startswith(actions.NO_SWITCH_BUTTON_PREFIX):
                        # "Switch to <Page>" is not offered: either we are ALREADY the
                        # Page (fine — verified positively just below) or the name is
                        # wrong (the verification refuses). Not a refusal by itself.
                        identity_problem = None
                if identity_problem is None:
                    identity_problem = await actions.ensure_page_identity(
                        session.page, account.page_name, account.personal_name,
                    )
            if identity_problem is not None:
                success, message = False, identity_problem
            else:
                action_started = True
                result = await action_fn(session.page, request)
                success = result.success
                message = result.message
            # Loud alert, once per episode — also covers the per-comment label
            # guard inside comment_on_group_post (same "wrong_identity" family).
            if account.page_name:
                alert_key = f"{account.account_id}:{'owner' if use_owner else 'own'}"
                if actions.needs_identity_alert(message):
                    if alert_key not in _wrong_identity_alerted:
                        what_next = (
                            "Bot sẽ thử lại bằng phiên của tài khoản cá nhân."
                            if account.can_fall_back_to_owner and not use_owner and _owner_session_usable(account)
                            else "Bot đã từ chối đăng. Cần chuyển lại sang Page và lưu phiên."
                        )
                        await telegram_notify.send_message(
                            f"🔴 {account.account_id}: phiên đăng nhập KHÔNG xác nhận được là danh tính Page "
                            f"'{account.page_name}' — {what_next}\n{message}",
                            silent=False,
                        )
                        _wrong_identity_alerted.add(alert_key)
                elif success:
                    _wrong_identity_alerted.discard(alert_key)
    except AnomalyDetected as e:
        # This is what makes docs/skills/anomaly-detection.md's "never
        # retry past this point" actually true, instead of just aborting
        # this one attempt and letting the account get tried again next
        # time as if nothing happened. Persisted via runtime_config.json
        # so it survives a service restart too — stays paused until a
        # human reviews and resumes it at /admin/accounts.
        message = str(e)
        anomaly_paused = True
        try:
            set_account_paused(request.account_id, True, reason=message)
            if account.page_name and account.owner_account_id:
                # A Page shares its owner's Facebook login: a checkpoint here
                # is a checkpoint on the personal account too.
                set_account_paused(account.owner_account_id, True, reason=f"{message} (via Page {request.account_id})")
        except Exception:  # noqa: BLE001 — the task must still return a result even if this write fails
            pass
        # Loud (not silent) Telegram alert — this is exactly the moment
        # the account transitions to paused, so it naturally fires once,
        # no dedup bookkeeping needed (2026-10-05, alert type 1/5).
        await telegram_notify.send_message(
            f"🔴 Tài khoản {request.account_id} đã bị TẠM DỪNG\nLý do: {message}",
            silent=False,
        )
    except Exception as e:  # noqa: BLE001 — surfaced to caller as a failed TaskResult
        message = f"error:{e}"
    finally:
        try:
            # Evidence screenshot — success or failure — taken here, not inside
            # each actions.py function, for the same "one choke point" reason as
            # db.log_action() above: session.page is whatever state the action
            # left it in (the browser page persists; nothing closes it), so this
            # is close enough to the actual moment of success/failure without
            # needing every action function to know about screenshots at all.
            # Taken BEFORE an owner-session Page task switches back, so it shows
            # the post/comment, not the facebook.com home it returns to. None
            # when there's no page to shoot from (an early-exit failure above —
            # paused account, unsupported action, rate limited — none of which
            # ever opened a browser).
            if session is not None and session.page is not None:
                screenshot_path = await screenshots.capture(session.page, request.account_id, request.action, success)

            # Whether the browser was still up when the attempt ended — decided
            # BEFORE any switch-back/close below can change it (see the
            # rate-limit comment further down).
            session_alive_after_attempt = session is not None and session.is_alive()

            # Owner-session mode: put the SHARED session back on the personal
            # profile, verified, before anything is saved. A session left on the
            # Page identity would make the next PERSONAL task act as the Page,
            # and saving it would write the Page identity into the personal
            # login file. If it can't be confirmed, the session is discarded
            # unsaved (the next task starts clean from the last good file).
            # After a checkpoint (AnomalyDetected) no further clicking is done on
            # the flagged login: the session is just closed unsaved.
            restored = True
            if switched_identity and session is not None:
                restored = False
                restore_problem = None
                if anomaly_paused:
                    restore_problem = "skipped_after_anomaly"
                elif session_alive_after_attempt:
                    try:
                        restore_problem = await actions.restore_personal_identity(
                            session.page, account.page_name, account.personal_name,
                        )
                    except Exception as e:  # noqa: BLE001 — treated as "not restored" below
                        restore_problem = f"error:{type(e).__name__}"
                else:
                    restore_problem = "browser_not_alive"
                if restore_problem is None:
                    restored = True
                    session.identity_dirty = False
                else:
                    await session.close(save=False)  # also clears identity_dirty
                    if not anomaly_paused and session_alive_after_attempt:
                        # Only worth a loud alert when the browser was fine yet the
                        # switch-back could not be proven; a crashed browser or a
                        # checkpoint already has its own signal.
                        await telegram_notify.send_message(
                            f"🔴 {account.owner_account_id}: sau tác vụ của Page {account.account_id} không xác nhận được "
                            f"đã chuyển về hồ sơ cá nhân ({restore_problem}) — đã đóng phiên mà KHÔNG lưu; "
                            f"tác vụ kế tiếp sẽ mở lại từ phiên đã lưu.",
                            silent=False,
                        )

            # Save the login session (cookies/localStorage) right after every
            # task, not only when the service shuts down cleanly. This is what
            # protects against losing a session on Ctrl+C / crash / kill -9 —
            # see human_bot/browser_pool.py's save_state() for why a
            # shutdown-only save is not reliable enough on its own.
            if session is not None and restored:
                await session.save_state()
            # Only charge this attempt against the account's rate-limit gap
            # (docs/skills/rate-limiting-pacing.md) when it plausibly sent real
            # traffic to Facebook. `success` covers the obvious case. Otherwise,
            # check whether the browser session SURVIVED the failure
            # (session.is_alive(), human_bot/browser_pool.py) — every action in
            # actions.py starts with page.goto(...) and never deliberately
            # closes the page/context/browser on error, so if the session is
            # still alive right after a failed attempt, that failure happened
            # DURING a real page load/interaction (selector not found, FB
            # rejected it, a timeout mid-navigation, ...) — genuine contact was
            # made, so it counts exactly like before.
            #
            # If the session is NOT alive, the failure was an infra problem —
            # ensure_started() never got a working browser at all, or (the
            # 2026-09-09 incident) the browser/page died out from under us
            # between the liveness check and the actual page.goto(), raising
            # "Target page, context or browser has been closed" before a
            # single byte reached Facebook's servers. Charging the account's
            # rate-limit gap for that would throttle it for something it never
            # actually did — so this case is deliberately NOT recorded here.
            # (Computed before the switch-back step above, so closing the
            # session there can't make a crashed browser look like it survived.)
            session_survived = session_alive_after_attempt
            # A refusal by the identity check made no attempt at the ACTION, so
            # it must not start the account's rate-limit gap (and throttle the
            # first real post after the owner fixes the session).
            identity_refused = actions.is_identity_refusal(message) or message.startswith(("page_owner_missing", "page_owner_off"))
            if success or (session_survived and not identity_refused):
                limiter.record(rate_limit_bucket, success)
        finally:
            if lock_held and session is not None:
                session.lock.release()

    return _Attempt(success, message, screenshot_path, anomaly_paused, action_started)


async def run_task(request: TaskRequest) -> TaskResult:
    account = get_account(request.account_id)

    if account.status != AccountStatus.ACTIVE:
        # "account_disabled" = switched off on purpose (nothing wrong);
        # "account_paused" = suspended for a suspected problem.
        message = (
            f"account_disabled:{request.account_id}" if account.status == AccountStatus.DISABLED
            else f"account_paused:{request.account_id}"
        )
        _log_result(request, False, message)
        return TaskResult(
            success=False,
            message=message,
            screenshot_path=None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    if account.page_name:
        # A Page shares its owner's Facebook login: if the owner is PAUSED
        # (e.g. a checkpoint), the Page must not keep driving that login. An
        # owner merely switched OFF only takes away the owner's SESSION (see
        # _run_attempt()); a Page with its own session can still run.
        owner = get_all_accounts().get(account.owner_account_id)
        if owner is not None and owner.status == AccountStatus.PAUSED:
            message = f"account_paused:{owner.account_id} (owner of Page {request.account_id})"
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

    # daily_limits.can_proceed() (2026-09-11), not RateLimiter.can_proceed()
    # directly — same gap check, but posts_per_day/comments_per_day now
    # count against a "business day" (2 AM JST boundary) instead of a
    # rolling 24h window; see human_bot/daily_limits.py's module docstring.
    limiter = RateLimiter(account)
    allowed, reason = daily_limits.can_proceed(account, rate_limit_bucket, ignore_gap=request.force_ignore_gap)
    if not allowed:
        message = f"rate_limited:{reason}"
        _log_result(request, False, message)
        return TaskResult(
            success=False,
            message=message,
            screenshot_path=None,
            timestamp=datetime.now(timezone.utc).isoformat(),
        )

    # Which session first: an owner-session Page goes straight to its owner's;
    # everything else (incl. an "auto" Page) starts with the account's own.
    attempt = await _run_attempt(request, account, action_fn, rate_limit_bucket, limiter, use_owner=account.uses_owner_session)
    if (
        account.can_fall_back_to_owner
        and not attempt.success
        and not attempt.action_started
        and not attempt.anomaly_paused
        and _owner_session_usable(account)
    ):
        # The Page's own session could not even START the action (logged out,
        # browser failure, identity not confirmed) — nothing was posted, so it
        # is safe to try the same task through the owner's session. Never done
        # after the action began: a second try could double-post.
        await telegram_notify.send_message(
            f"↪️ Page {account.account_id}: phiên riêng không dùng được ({attempt.message}) — "
            f"thử lại bằng phiên của tài khoản cá nhân {account.owner_account_id}.",
            silent=True,
        )
        attempt = await _run_attempt(request, account, action_fn, rate_limit_bucket, limiter, use_owner=True)
    success, message = attempt.success, attempt.message
    screenshot_path, anomaly_paused = attempt.screenshot_path, attempt.anomaly_paused

    _log_result(request, success, message, screenshot_path)
    # Skip the per-attempt report when AnomalyDetected already sent its own
    # loud "TẠM DỪNG" alert above for this exact incident — otherwise the
    # owner gets a redundant silent failure report (and possibly a 3rd,
    # unrelated "N lần liên tiếp" alert) on top of the one that actually
    # matters.
    if not anomaly_paused:
        await _notify_telegram_for_attempt(request, success, message, screenshot_path)
    return TaskResult(
        success=success,
        message=message,
        screenshot_path=screenshot_path,
        timestamp=datetime.now(timezone.utc).isoformat(),
    )
