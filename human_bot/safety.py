"""
Rate limiting and anomaly detection for human_bot.

See docs/skills/rate-limiting-pacing.md and docs/skills/anomaly-detection.md.
This module intentionally has no dependency on browser-use so it can be
unit-tested on its own.
"""
from __future__ import annotations

import json
import random
from datetime import datetime, timedelta
from pathlib import Path

from human_bot.config import AccountConfig, RateLimits

# Text signals indicating Facebook has restricted/challenged the account.
# Keep this list in sync with docs/skills/anomaly-detection.md.
ANOMALY_TEXT_SIGNALS = [
    "we restricted your account",
    "confirm your identity",
    "unusual activity",
    "you're temporarily blocked",
    "please verify",
    "certain actions have been restricted",
    "checkpoint",
]

# Text signals meaning the TARGET post/content is gone (deleted, made
# private, or the group isn't one this account can see) — confirmed
# 2026-09-08 against a real dead link from side B's candidate feed
# (screenshot: "This content isn't available right now" / "Go to Feed" /
# "Go back" / "Visit Help Center", no post body, no comment box). This is
# NOT an ANOMALY_TEXT_SIGNALS case: nothing here indicates Facebook has
# flagged THIS BOT ACCOUNT — pausing the account over a dead link the bot
# had no control over would be wrong. Checked separately by
# human_bot/actions.py's _check_content_unavailable() so a dead
# comment_on_group_post/comment_on_friend_post target fails fast with a
# clear reason instead of timing out ~30s waiting for a comment box that
# will never appear, then surfacing as a generic "Timeout ... exceeded".
CONTENT_UNAVAILABLE_TEXT_SIGNALS = [
    "this content isn't available right now",
    "this content isn't available",
]


class AnomalyDetected(RuntimeError):
    """Raised by human_bot/actions.py's _check_anomaly_or_raise() when a
    page shows one of ANOMALY_TEXT_SIGNALS mid-action. A distinct
    exception type (not a bare RuntimeError) so human_bot/agent.py's
    run_task() can catch this specifically and persist
    AccountStatus.PAUSED for the account (via
    human_bot/runtime_config.py's set_account_paused) — this is what
    actually makes docs/skills/anomaly-detection.md's "never retry past
    this point" true: before this, detection only aborted the one
    in-flight action and the account would be tried again normally next
    time, with nothing stopping it from hitting the same wall repeatedly.
    A paused account stays paused until a human resumes it at
    /admin/accounts."""

    def __init__(self, signal: str):
        self.signal = signal
        super().__init__(f"anomaly_detected:{signal}")


def detect_anomaly(page_text: str, current_url: str = "") -> str | None:
    """Return the matched signal string, or None if nothing suspicious found."""
    haystack = page_text.lower()
    for signal in ANOMALY_TEXT_SIGNALS:
        if signal in haystack:
            return signal
    if "checkpoint" in current_url:
        return "checkpoint_url"
    return None


def is_content_unavailable(page_text: str) -> bool:
    """True if the page is Facebook's "this content isn't available"
    dead-link page (post deleted, made private, or in a group this
    account can't see) — see CONTENT_UNAVAILABLE_TEXT_SIGNALS above.
    Deliberately separate from detect_anomaly(): this says nothing about
    the bot account's own standing, so it must never trigger
    AnomalyDetected/account-pause."""
    haystack = page_text.lower()
    return any(signal in haystack for signal in CONTENT_UNAVAILABLE_TEXT_SIGNALS)


def _gap_bounds(limits: RateLimits, action_type: str) -> tuple[int, int]:
    """Which (min, max) delay-seconds pair applies to `action_type` —
    "post" gets its own, everything else ("comment", "like") gets the
    comment pair (added 2026-09-10; this project has no separate
    schedule/numbers for likes, and comments/likes are both much
    lower-effort than a full post)."""
    if action_type == "post":
        return limits.post_min_delay_seconds, limits.post_max_delay_seconds
    return limits.comment_min_delay_seconds, limits.comment_max_delay_seconds


class RateLimiter:
    """Tracks an account's recent actions against docs/skills/rate-limiting-pacing.md limits."""

    def __init__(self, account: AccountConfig):
        self.account = account
        self.log_path: Path = account.action_log_path
        self.log_path.parent.mkdir(parents=True, exist_ok=True)

    def _read_recent(self, since: timedelta) -> list[dict]:
        if not self.log_path.exists():
            return []
        cutoff = datetime.utcnow() - since
        rows = []
        with self.log_path.open() as f:
            for line in f:
                try:
                    row = json.loads(line)
                    if datetime.fromisoformat(row["timestamp"]) >= cutoff:
                        rows.append(row)
                except (ValueError, KeyError):
                    continue
        return rows

    def next_allowed_at(self, action_type: str) -> datetime | None:
        """Read-only lookup of next_allowed_at from this account's last
        logged action OF THIS SAME action_type bucket ("post" / "comment"
        / "like" — see agent.py's _ACTION_DISPATCH) — never appends
        anything, so it's safe to call just to check/display state
        without that call itself counting as an attempt. Returns None if
        there's no logged action of this type yet, or the last matching
        row predates this field.

        Scoped per action_type (changed 2026-09-08, see the conversation
        that requested this): min_delay_seconds/max_delay_seconds is the
        minimum gap between two consecutive actions of the SAME kind
        (post-to-post, comment-to-comment), not a single account-wide
        clock shared across every action type — a comment can fire
        shortly after a post, they just each need their own spacing from
        the last action of their own kind, same as posts_per_day/
        comments_per_hour below already only count same-type rows.

        Used by _last_action_gap_ok() below, and by callers that want a
        suggested reschedule time without going through can_proceed()
        (e.g. /admin/schedule showing a rate-limit warning on a due task
        instead of just failing it — see human_bot/data_sync.py's
        fire_due_tasks() and admin.py's schedule_fire_now())."""
        if not self.log_path.exists():
            return None
        last_row: dict | None = None
        with self.log_path.open() as f:
            for line in f:
                try:
                    row = json.loads(line)
                except ValueError:
                    continue
                if row.get("action") == action_type:
                    last_row = row
        if not last_row:
            return None
        next_allowed_at = last_row.get("next_allowed_at")
        if not next_allowed_at:
            return None  # a row logged before this field existed
        try:
            return datetime.fromisoformat(next_allowed_at)
        except ValueError:
            return None

    def _last_action_gap_ok(self, action_type: str) -> tuple[bool, str]:
        """Enforces RateLimits.min_delay_seconds/max_delay_seconds as an
        actual minimum gap between two consecutive actions of the SAME
        action_type bucket on this account (see next_allowed_at()'s
        docstring for why it's scoped this way) — refuses the task
        outright if not enough time has passed, rather than sleeping/
        blocking (see docs/skills/rate-limiting-pacing.md's "Enforcement
        point": "refuse the task rather than queue and wait"). Previously
        these two fields were defined but never actually enforced
        anywhere — see the conversation that requested wiring this up,
        2026-09-07."""
        allowed_at = self.next_allowed_at(action_type)
        if allowed_at is None:
            return True, "ok"
        now = datetime.utcnow()
        if now < allowed_at:
            wait_s = int((allowed_at - now).total_seconds())
            return False, f"min_delay_seconds gap not elapsed yet, wait ~{wait_s}s"
        return True, "ok"

    def can_proceed(self, action_type: str, ignore_gap: bool = False) -> tuple[bool, str]:
        """`ignore_gap=True` skips ONLY the min/max_delay_seconds pacing
        check (see _last_action_gap_ok's docstring) — the count-based hard
        caps below (posts_per_day/comments_per_hour/comments_per_day/
        likes_per_hour) are never skippable. Used by admin.py's manual
        "Đăng ngay" override: an admin who explicitly confirms past the
        pacing warning is a judgment call the system can trust; silently
        letting them blow through a per-day/per-hour COUNT cap would not
        be — that count is the strongest signal Facebook itself uses to
        flag automation, so it stays a hard refusal regardless of this
        flag. See is_gap_reason() for how callers tell the two apart
        before deciding whether to offer this override at all."""
        if not ignore_gap:
            gap_ok, gap_reason = self._last_action_gap_ok(action_type)
            if not gap_ok:
                return False, gap_reason
        limits = self.account.rate_limits
        if action_type == "post":
            count = len([r for r in self._read_recent(timedelta(days=1)) if r["action"] == "post"])
            if count >= limits.posts_per_day:
                return False, "posts_per_day limit reached"
        elif action_type == "comment":
            hourly = len([r for r in self._read_recent(timedelta(hours=1)) if r["action"] == "comment"])
            daily = len([r for r in self._read_recent(timedelta(days=1)) if r["action"] == "comment"])
            if hourly >= limits.comments_per_hour:
                return False, "comments_per_hour limit reached"
            if daily >= limits.comments_per_day:
                return False, "comments_per_day limit reached"
        elif action_type == "like":
            hourly = len([r for r in self._read_recent(timedelta(hours=1)) if r["action"] == "like"])
            if hourly >= limits.likes_per_hour:
                return False, "likes_per_hour limit reached"
        return True, "ok"

    def record(self, action_type: str, success: bool) -> None:
        # Draws the randomized gap ONCE, right here, and persists it as
        # next_allowed_at — rather than re-rolling it on every
        # can_proceed() check, which would let the required wait shrink
        # or grow each time it's checked. _last_action_gap_ok() above
        # just compares "now" against this stored value, scoped to the
        # last row of this SAME action_type (see next_allowed_at()'s
        # docstring) — so this next_allowed_at only ever gets compared
        # against a future action of the same type.
        gap_min, gap_max = _gap_bounds(self.account.rate_limits, action_type)
        next_allowed_at = (
            datetime.utcnow()
            + timedelta(seconds=random.uniform(gap_min, gap_max))
        ).isoformat()
        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action_type,
            "success": success,
            "next_allowed_at": next_allowed_at,
        }
        with self.log_path.open("a") as f:
            f.write(json.dumps(row) + "\n")


def is_gap_reason(reason: str) -> bool:
    """True if a can_proceed() failure reason is the soft min-gap pacing
    check (overridable via can_proceed(ignore_gap=True)) rather than one
    of the hard per-day/per-hour count caps (never overridable). See
    can_proceed()'s docstring for why the two are treated differently."""
    return reason.startswith("min_delay_seconds")


def rate_limit_wait_message(account: AccountConfig, action_type: str) -> str | None:
    """Human-readable (Vietnamese) warning + suggested reschedule time in
    JST for an account currently blocked by RateLimiter's min_delay_seconds
    gap for THIS action_type bucket ("post" / "comment" / "like" — see
    agent.py's _ACTION_DISPATCH), or None if it isn't blocked right now.
    Built from RateLimiter.next_allowed_at() — a read-only lookup, doesn't
    count as an attempt. Shared by data_sync.py's fire_due_tasks() and
    admin.py's schedule_fire_now(): a due task that's simply too soon
    after the account's last action OF THE SAME TYPE stays in
    /admin/schedule with this as a visible banner instead of landing in
    failed/ indistinguishable from a real error. Fixed +9h JST offset,
    not zoneinfo — same reasoning as admin.py's _fmt_jst() (Japan has had
    no DST since 1951)."""
    allowed_at = RateLimiter(account).next_allowed_at(action_type)
    if allowed_at is None or allowed_at <= datetime.utcnow():
        return None
    jst = allowed_at + timedelta(hours=9)
    label = {"post": "bài đăng", "comment": "comment", "like": "lượt thích"}.get(action_type, action_type)
    return (
        f"⚠️ {label.capitalize()} này đang bị chặn bởi rate-limit (chưa đủ khoảng nghỉ tối thiểu "
        f"giữa 2 {label} liên tiếp trên tài khoản này). Gợi ý: dời lịch sau "
        f"{jst.strftime('%H:%M %d-%m-%Y')} (giờ Nhật Bản)."
    )


def rate_limit_hard_cap_message(account: AccountConfig, action_type: str) -> str | None:
    """Human-readable (Vietnamese) notice when an account is blocked by one
    of the HARD count caps (posts_per_day / comments_per_hour /
    comments_per_day / likes_per_hour — see can_proceed()'s docstring for
    why these are never overridable), as opposed to rate_limit_wait_message()
    above which only covers the soft min_delay_seconds pacing gap. Returns
    None if the account isn't currently blocked, or is blocked only by the
    soft gap (that case stays rate_limit_wait_message()'s job — check
    is_gap_reason() on can_proceed()'s own `reason` to tell them apart).

    Deliberately does NOT compute an exact "unblocks at" time the way
    rate_limit_wait_message() does for the soft gap: these caps are
    enforced over a ROLLING window (the last 24h / 1h from whenever this
    is checked, human_bot/safety.py's RateLimiter._read_recent()), not a
    single next_allowed_at timestamp, and — critically — that rolling
    window is a different "day" than the one human_bot/data_sync.py's
    scheduler reasons about when spreading new tasks across calendar
    dates (UTC midnight-to-midnight). A backlog of tasks scheduled across
    several calendar days (e.g. while auto_fire_enabled was off) can
    still all land inside the same rolling 24h window once they finally
    fire, exceeding the daily cap even though each calendar day's own
    schedule stayed under it — see the conversation this was added from,
    2026-09-11, for the full investigation. So instead of promising a
    specific clock time, this just tells the admin the cap is hit and to
    reschedule by hand."""
    allowed, reason = RateLimiter(account).can_proceed(action_type)
    if allowed or is_gap_reason(reason):
        return None
    label = {"post": "bài đăng", "comment": "comment", "like": "lượt thích"}.get(action_type, action_type)
    return (
        f"⛔ Tài khoản này đã đạt giới hạn số lượng {label} tối đa (theo giờ hoặc theo ngày) — "
        f"KHÔNG phải lỗi tạm thời, sẽ còn bị chặn cho tới khi hoạt động cũ đủ 24h/1h trôi qua. "
        f"Gợi ý: dời lịch bài này sang một thời điểm khác (VD ngày mai) ở trang Lịch đăng, "
        f"hoặc huỷ nếu không còn cần thiết."
    )
