"""Tests for human_bot/admin.py's _suggest_reschedule_at() — the "🔄 Lên
lịch lại" slot suggestion used by both /admin/reports' retry flow and
/admin/schedule's "⚠️ Task quá hạn" review. Isolated from the real
schedule_store/ and any real account's action_log.jsonl via monkeypatch
and a fake account (per project rule: never touch real on-disk state in
tests)."""
import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import human_bot.schedule_store as schedule_store
from human_bot.admin import _suggest_reschedule_at
from human_bot.config import RateLimits
from human_bot.data_sync_config import DataSyncConfig
from human_bot import daily_limits


@dataclass
class _FakeAccount:
    account_id: str
    rate_limits: RateLimits
    action_log_path: Path


@pytest.fixture
def isolated_schedule_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(schedule_store, "POSTED_DIR", tmp_path / "posted")
    monkeypatch.setattr(schedule_store, "FAILED_DIR", tmp_path / "failed")
    monkeypatch.setattr(schedule_store, "CANCELLED_DIR", tmp_path / "cancelled")
    monkeypatch.setattr(schedule_store, "MISSED_DIR", tmp_path / "missed")
    return schedule_store


@pytest.fixture
def account(tmp_path):
    return _FakeAccount(
        account_id="acc-a",
        rate_limits=RateLimits(),
        action_log_path=tmp_path / "action_log.jsonl",
    )


def _add_pending(store, account_id, when, action="post_to_group"):
    task = store.ScheduledTask(
        task_id=store.new_task_id(when.isoformat()),
        action=action, account_id=account_id, scheduled_at=when.isoformat(),
        content="x", target_url="https://facebook.com/groups/1",
    )
    store.add(task)
    return task


def _log_real_action(account, next_allowed_at: datetime, action_type: str = "post") -> None:
    account.action_log_path.parent.mkdir(parents=True, exist_ok=True)
    with account.action_log_path.open("a") as f:
        f.write(json.dumps({
            "timestamp": datetime.utcnow().isoformat(),
            "action": action_type,
            "success": True,
            # RateLimiter always writes NAIVE UTC — see safety.py.
            "next_allowed_at": next_allowed_at.replace(tzinfo=None).isoformat(),
        }) + "\n")


def test_suggestion_avoids_quiet_hours_even_after_gap_floor_pushes_into_it(isolated_schedule_dirs, account):
    """Owner-reported bug 2026-09-14: quiet hours was applied BEFORE the
    gap floor, so a floor landing inside the quiet window was never
    re-clamped. Set up a real-history floor that lands at 3:00 JST
    (inside the default 2-6 AM quiet window) and confirm the final
    suggestion is NOT in that window."""
    cfg = DataSyncConfig()
    now = datetime.now(timezone.utc)
    # Pick a `next_allowed_at` landing at 3:00 JST tomorrow (inside quiet
    # hours), expressed in naive UTC as RateLimiter/safety.py always logs.
    target_jst = (now + timedelta(hours=9)).replace(hour=3, minute=0, second=0, microsecond=0) + timedelta(days=1)
    target_utc_naive = (target_jst - timedelta(hours=9)).replace(tzinfo=None)
    _log_real_action(account, target_utc_naive)

    suggested = _suggest_reschedule_at(account, "post_to_group")
    suggested_jst_hour = (suggested + timedelta(hours=9)).hour
    assert not (cfg.quiet_hour_start_local <= suggested_jst_hour < cfg.quiet_hour_end_local), (
        f"suggestion landed inside quiet hours: {suggested.isoformat()}"
    )


def test_suggestion_skips_a_day_already_full_from_pending_tasks_plus_gap_floor(isolated_schedule_dirs, account):
    """Owner-reported bug 2026-09-14: the daily-cap day-search only ran
    ONCE, before the gap floor was applied — so the gap floor (from the
    latest pending task) could push the suggestion onto a day that
    search never re-checked. Fill tomorrow to cap via pending tasks and
    confirm the suggestion lands on a LATER day, not on the full one."""
    cap = account.rate_limits.posts_per_day
    now = datetime.now(timezone.utc)
    tomorrow_start = daily_limits.business_day_start(now) + timedelta(days=1)

    for i in range(cap):
        _add_pending(isolated_schedule_dirs, account.account_id, tomorrow_start + timedelta(hours=10 + i))
    # One more pending task landing LATE on tomorrow — its own gap floor
    # (scheduled_at + post_min_delay_seconds) is what used to push the
    # suggestion onto this already-full day without re-checking it.
    _add_pending(isolated_schedule_dirs, account.account_id, tomorrow_start + timedelta(hours=20))

    suggested = _suggest_reschedule_at(account, "post_to_group")
    tomorrow_key = daily_limits.business_day_key(tomorrow_start)
    assert daily_limits.business_day_key(suggested) != tomorrow_key


def test_two_consecutive_suggestions_differ_once_first_is_pending(isolated_schedule_dirs, account):
    """Regression for the original 2026-09-12 bug this function was
    built to fix: suggesting twice in a row (nothing fired in between)
    must not return the identical slot the second time, once the first
    suggestion has been added as a pending task."""
    first = _suggest_reschedule_at(account, "post_to_group")
    _add_pending(isolated_schedule_dirs, account.account_id, first)

    second = _suggest_reschedule_at(account, "post_to_group")
    assert second != first
    gap = account.rate_limits.post_min_delay_seconds
    assert second >= first + timedelta(seconds=gap) - timedelta(seconds=1)


def test_suggestion_with_no_history_or_pending_tasks_is_close_to_now(isolated_schedule_dirs, account):
    """Sanity check: with a clean slate, the suggestion should be `now`
    (possibly nudged forward by quiet hours), not some far-future date."""
    before = datetime.now(timezone.utc)
    suggested = _suggest_reschedule_at(account, "post_to_group")
    after = datetime.now(timezone.utc)
    # Either right around "now", or pushed to the end of quiet hours —
    # either way, well within the same business day, not days away.
    assert suggested - before < timedelta(hours=12)
    assert suggested >= before - timedelta(seconds=1)
