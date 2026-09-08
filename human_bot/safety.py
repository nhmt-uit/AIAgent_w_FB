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

from human_bot.config import AccountConfig

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

    def _last_action_gap_ok(self) -> tuple[bool, str]:
        """Enforces RateLimits.min_delay_seconds/max_delay_seconds as an
        actual minimum gap between ANY two consecutive actions on this
        account, regardless of action type — refuses the task outright if
        not enough time has passed, rather than sleeping/blocking (see
        docs/skills/rate-limiting-pacing.md's "Enforcement point": "refuse
        the task rather than queue and wait"). Previously these two
        fields were defined but never actually enforced anywhere — see
        the conversation that requested wiring this up, 2026-09-07."""
        if not self.log_path.exists():
            return True, "ok"
        last_row: dict | None = None
        with self.log_path.open() as f:
            for line in f:
                try:
                    last_row = json.loads(line)
                except ValueError:
                    continue
        if not last_row:
            return True, "ok"
        next_allowed_at = last_row.get("next_allowed_at")
        if not next_allowed_at:
            return True, "ok"  # a row logged before this field existed
        try:
            allowed_at = datetime.fromisoformat(next_allowed_at)
        except ValueError:
            return True, "ok"
        now = datetime.utcnow()
        if now < allowed_at:
            wait_s = int((allowed_at - now).total_seconds())
            return False, f"min_delay_seconds gap not elapsed yet, wait ~{wait_s}s"
        return True, "ok"

    def can_proceed(self, action_type: str) -> tuple[bool, str]:
        gap_ok, gap_reason = self._last_action_gap_ok()
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
        # just compares "now" against this stored value.
        limits = self.account.rate_limits
        next_allowed_at = (
            datetime.utcnow()
            + timedelta(seconds=random.uniform(limits.min_delay_seconds, limits.max_delay_seconds))
        ).isoformat()
        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action_type,
            "success": success,
            "next_allowed_at": next_allowed_at,
        }
        with self.log_path.open("a") as f:
            f.write(json.dumps(row) + "\n")
