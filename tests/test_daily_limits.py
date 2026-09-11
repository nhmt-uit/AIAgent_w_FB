from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

from human_bot.config import RateLimits
from human_bot.daily_limits import (
    business_day_key,
    business_day_start,
    can_proceed,
    count_since_business_day_start,
    hard_cap_message,
)


# --- business_day_start / business_day_key ----------------------------------

def test_business_day_start_exactly_at_boundary():
    # 17:00 UTC == 02:00 JST — the boundary itself, so it IS the start.
    t = datetime(2026, 9, 11, 17, 0, tzinfo=timezone.utc)
    assert business_day_start(t) == t


def test_business_day_start_just_before_boundary_falls_back_a_day():
    # 16:59 UTC == 01:59 JST — one minute before 2 AM JST, so the
    # business day is still YESTERDAY's (started 02:00 JST the day before).
    t = datetime(2026, 9, 11, 16, 59, tzinfo=timezone.utc)
    assert business_day_start(t) == datetime(2026, 9, 10, 17, 0, tzinfo=timezone.utc)


def test_business_day_start_midday():
    # 03:00 UTC == 12:00 JST (noon) — well inside the business day that
    # started at 02:00 JST the same calendar day.
    t = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
    assert business_day_start(t) == datetime(2026, 9, 10, 17, 0, tzinfo=timezone.utc)


def test_business_day_key_matches_jst_date_of_its_start():
    t = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)  # noon JST 9/11
    assert business_day_key(t) == date(2026, 9, 11)


def test_business_day_key_before_2am_jst_belongs_to_previous_day():
    t = datetime(2026, 9, 11, 16, 59, tzinfo=timezone.utc)  # 01:59 JST 9/12
    assert business_day_key(t) == date(2026, 9, 11)


# --- count_since_business_day_start / can_proceed / hard_cap_message --------

@dataclass
class _FakeAccount:
    """Same duck-typed stand-in as tests/test_safety.py's _FakeAccount —
    daily_limits.py's functions only ever touch .rate_limits and
    .action_log_path (via RateLimiter), so the real accounts/ directory
    is never involved."""
    rate_limits: RateLimits
    action_log_path: Path


def _make_account(tmp_path, **rate_limit_overrides) -> _FakeAccount:
    return _FakeAccount(
        rate_limits=RateLimits(**rate_limit_overrides),
        action_log_path=tmp_path / "action_log.jsonl",
    )


def _write_rows(account, rows: list[dict]) -> None:
    with account.action_log_path.open("a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_count_since_business_day_start_excludes_rows_before_boundary():
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        account = _make_account(Path(d))
        now = datetime.utcnow()
        before_boundary = business_day_start(now) - timedelta(minutes=1)
        after_boundary = business_day_start(now) + timedelta(minutes=1)
        _write_rows(account, [
            {"timestamp": before_boundary.isoformat(), "action": "comment", "success": True},
            {"timestamp": after_boundary.isoformat(), "action": "comment", "success": True},
            {"timestamp": after_boundary.isoformat(), "action": "comment", "success": True},
            {"timestamp": after_boundary.isoformat(), "action": "post", "success": True},
        ])
        assert count_since_business_day_start(account, "comment") == 2
        assert count_since_business_day_start(account, "post") == 1


def test_count_since_business_day_start_no_log_file_returns_zero(tmp_path):
    account = _make_account(tmp_path)
    assert count_since_business_day_start(account, "post") == 0


def test_can_proceed_true_with_no_history(tmp_path):
    account = _make_account(tmp_path)
    allowed, reason = can_proceed(account, "post")
    assert (allowed, reason) == (True, "ok")


def test_can_proceed_daily_cap_uses_business_day_not_rolling_window(tmp_path):
    """The whole point of this module: a row from just over 24h ago but
    still within the SAME business day counts; a row from just under 24h
    ago but in the PREVIOUS business day does not — the opposite of what
    safety.py's rolling-24h RateLimiter.can_proceed() would do."""
    account = _make_account(
        tmp_path, comments_per_day=1, comment_min_delay_seconds=0, comment_max_delay_seconds=0,
    )
    # Naive UTC (no tzinfo), matching exactly what safety.py's
    # RateLimiter.record() actually writes (datetime.utcnow(), never
    # timezone-aware) — using an aware datetime here would silently test
    # an unrealistic log format and could mask a real mismatch.
    now = datetime.utcnow()
    just_after_todays_boundary = business_day_start(now) + timedelta(minutes=1)
    _write_rows(account, [
        {"timestamp": just_after_todays_boundary.isoformat(), "action": "comment", "success": True},
    ])
    allowed, reason = can_proceed(account, "comment", ignore_gap=True)
    assert allowed is False
    assert reason == "comments_per_day limit reached"


def test_can_proceed_row_in_previous_business_day_does_not_count(tmp_path):
    account = _make_account(
        tmp_path, comments_per_day=1, comment_min_delay_seconds=0, comment_max_delay_seconds=0,
    )
    now = datetime.utcnow()
    just_before_todays_boundary = business_day_start(now) - timedelta(minutes=1)
    _write_rows(account, [
        {"timestamp": just_before_todays_boundary.isoformat(), "action": "comment", "success": True},
    ])
    allowed, reason = can_proceed(account, "comment", ignore_gap=True)
    assert (allowed, reason) == (True, "ok")


def test_can_proceed_post_daily_cap(tmp_path):
    account = _make_account(
        tmp_path, posts_per_day=2, post_min_delay_seconds=0, post_max_delay_seconds=0,
    )
    now = datetime.utcnow()
    boundary = business_day_start(now) + timedelta(hours=1)
    _write_rows(account, [
        {"timestamp": boundary.isoformat(), "action": "post", "success": True},
        {"timestamp": boundary.isoformat(), "action": "post", "success": True},
    ])
    allowed, reason = can_proceed(account, "post", ignore_gap=True)
    assert allowed is False
    assert reason == "posts_per_day limit reached"


def test_can_proceed_comment_hourly_cap_still_uses_rolling_window():
    """comments_per_hour/likes_per_hour are UNCHANGED by this module —
    still RateLimiter.recent_count()'s rolling window, not business-day."""
    import tempfile
    with tempfile.TemporaryDirectory() as d:
        account = _make_account(
            Path(d), comments_per_hour=1, comments_per_day=100,
            comment_min_delay_seconds=0, comment_max_delay_seconds=0,
        )
        now = datetime.utcnow()
        _write_rows(account, [
            {"timestamp": now.isoformat(), "action": "comment", "success": True},
        ])
        allowed, reason = can_proceed(account, "comment", ignore_gap=True)
        assert allowed is False
        assert reason == "comments_per_hour limit reached"


def test_can_proceed_gap_check_still_applies(tmp_path):
    account = _make_account(
        tmp_path, comment_min_delay_seconds=999999, comment_max_delay_seconds=999999,
    )
    now = datetime.utcnow()
    _write_rows(account, [
        {
            "timestamp": now.isoformat(),
            "action": "comment",
            "success": True,
            "next_allowed_at": (now + timedelta(hours=5)).isoformat(),
        },
    ])
    allowed, reason = can_proceed(account, "comment")
    assert allowed is False
    assert reason.startswith("min_delay_seconds")


def test_can_proceed_ignore_gap_skips_gap_but_not_daily_cap(tmp_path):
    account = _make_account(
        tmp_path, comments_per_day=1,
        comment_min_delay_seconds=999999, comment_max_delay_seconds=999999,
    )
    now = datetime.utcnow()
    boundary = business_day_start(now) + timedelta(minutes=1)
    _write_rows(account, [
        {
            "timestamp": boundary.isoformat(),
            "action": "comment",
            "success": True,
            "next_allowed_at": (now + timedelta(hours=5)).isoformat(),
        },
    ])
    # Gap alone would block this too, but with ignore_gap=True the daily
    # cap (not skippable, see can_proceed()'s docstring) is what trips.
    allowed, reason = can_proceed(account, "comment", ignore_gap=True)
    assert allowed is False
    assert reason == "comments_per_day limit reached"


def test_hard_cap_message_none_when_allowed(tmp_path):
    account = _make_account(tmp_path)
    assert hard_cap_message(account, "post") is None


def test_hard_cap_message_none_for_gap_only_block(tmp_path):
    account = _make_account(
        tmp_path, post_min_delay_seconds=999999, post_max_delay_seconds=999999,
    )
    now = datetime.utcnow()
    _write_rows(account, [
        {
            "timestamp": now.isoformat(),
            "action": "post",
            "success": True,
            "next_allowed_at": (now + timedelta(hours=5)).isoformat(),
        },
    ])
    assert hard_cap_message(account, "post") is None


def test_hard_cap_message_present_for_daily_cap(tmp_path):
    account = _make_account(
        tmp_path, posts_per_day=1, post_min_delay_seconds=0, post_max_delay_seconds=0,
    )
    now = datetime.utcnow()
    boundary = business_day_start(now) + timedelta(minutes=1)
    _write_rows(account, [
        {"timestamp": boundary.isoformat(), "action": "post", "success": True},
    ])
    msg = hard_cap_message(account, "post")
    assert msg is not None
    assert "giới hạn" in msg.lower()
