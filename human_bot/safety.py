"""
Rate limiting and anomaly detection for human_bot.

See docs/skills/rate-limiting-pacing.md and docs/skills/anomaly-detection.md.
This module intentionally has no dependency on browser-use so it can be
unit-tested on its own.
"""
from __future__ import annotations

import json
import random
import time
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

    def can_proceed(self, action_type: str) -> tuple[bool, str]:
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
        row = {
            "timestamp": datetime.utcnow().isoformat(),
            "action": action_type,
            "success": success,
        }
        with self.log_path.open("a") as f:
            f.write(json.dumps(row) + "\n")

    def jittered_delay(self) -> float:
        """Sleep a randomized duration per docs/skills/rate-limiting-pacing.md and return it."""
        limits = self.account.rate_limits
        delay = random.uniform(limits.min_delay_seconds, limits.max_delay_seconds)
        time.sleep(delay)
        return delay
