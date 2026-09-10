from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path

from human_bot.config import RateLimits
from human_bot.safety import (
    RateLimiter,
    detect_anomaly,
    is_content_unavailable,
    is_gap_reason,
)


# --- detect_anomaly / is_content_unavailable --------------------------------

def test_detect_anomaly_matches_known_signal_case_insensitive():
    assert detect_anomaly("Please Confirm Your Identity to continue") == "confirm your identity"


def test_detect_anomaly_no_match_returns_none():
    assert detect_anomaly("Welcome back! Here's your feed.") is None


def test_detect_anomaly_checkpoint_url_without_text_signal():
    assert detect_anomaly("Nothing suspicious here", current_url="https://facebook.com/checkpoint/123") == "checkpoint_url"


def test_is_content_unavailable_true_and_false():
    assert is_content_unavailable("This content isn't available right now") is True
    assert is_content_unavailable("A perfectly normal post body") is False


def test_is_gap_reason_distinguishes_gap_from_count_cap():
    assert is_gap_reason("min_delay_seconds gap not elapsed yet, wait ~120s") is True
    assert is_gap_reason("posts_per_day limit reached") is False


# --- RateLimiter -------------------------------------------------------------

@dataclass
class _FakeAccount:
    """Duck-typed stand-in for AccountConfig — RateLimiter only ever reads
    .rate_limits and .action_log_path, confirmed in human_bot/safety.py.
    Using this instead of a real AccountConfig means the log file lives
    under tmp_path, never under the real accounts/ directory."""
    rate_limits: RateLimits
    action_log_path: Path


def _make_limiter(tmp_path, **rate_limit_overrides) -> RateLimiter:
    account = _FakeAccount(
        rate_limits=RateLimits(**rate_limit_overrides),
        action_log_path=tmp_path / "action_log.jsonl",
    )
    return RateLimiter(account)


def _write_rows(limiter: RateLimiter, rows: list[dict]) -> None:
    import json

    with limiter.log_path.open("a") as f:
        for row in rows:
            f.write(json.dumps(row) + "\n")


def test_can_proceed_true_with_no_history(tmp_path):
    limiter = _make_limiter(tmp_path)
    ok, reason = limiter.can_proceed("post")
    assert ok is True
    assert reason == "ok"


def test_can_proceed_post_count_cap_trips(tmp_path):
    limiter = _make_limiter(tmp_path, posts_per_day=2, min_delay_seconds=0, max_delay_seconds=0)
    now = datetime.utcnow()
    _write_rows(limiter, [
        {"timestamp": now.isoformat(), "action": "post", "success": True, "next_allowed_at": now.isoformat()},
        {"timestamp": now.isoformat(), "action": "post", "success": True, "next_allowed_at": now.isoformat()},
    ])
    ok, reason = limiter.can_proceed("post", ignore_gap=True)
    assert ok is False
    assert reason == "posts_per_day limit reached"


def test_can_proceed_ignores_rows_outside_counting_window(tmp_path):
    limiter = _make_limiter(tmp_path, posts_per_day=1, min_delay_seconds=0, max_delay_seconds=0)
    two_days_ago = (datetime.utcnow() - timedelta(days=2)).isoformat()
    _write_rows(limiter, [
        {"timestamp": two_days_ago, "action": "post", "success": True, "next_allowed_at": two_days_ago},
    ])
    ok, reason = limiter.can_proceed("post", ignore_gap=True)
    assert (ok, reason) == (True, "ok")


def test_can_proceed_comment_hourly_and_daily_caps_are_independent(tmp_path):
    limiter = _make_limiter(
        tmp_path, comments_per_hour=100, comments_per_day=1, min_delay_seconds=0, max_delay_seconds=0,
    )
    now = datetime.utcnow()
    _write_rows(limiter, [
        {"timestamp": now.isoformat(), "action": "comment", "success": True, "next_allowed_at": now.isoformat()},
    ])
    ok, reason = limiter.can_proceed("comment", ignore_gap=True)
    assert ok is False
    assert reason == "comments_per_day limit reached"


def test_last_action_gap_blocks_before_next_allowed_at(tmp_path):
    limiter = _make_limiter(tmp_path, min_delay_seconds=3600, max_delay_seconds=3600)
    future = (datetime.utcnow() + timedelta(minutes=30)).isoformat()
    _write_rows(limiter, [
        {"timestamp": datetime.utcnow().isoformat(), "action": "post", "success": True, "next_allowed_at": future},
    ])
    ok, reason = limiter.can_proceed("post")
    assert ok is False
    assert is_gap_reason(reason) is True


def test_last_action_gap_allows_after_next_allowed_at(tmp_path):
    limiter = _make_limiter(tmp_path, posts_per_day=99)
    past = (datetime.utcnow() - timedelta(minutes=1)).isoformat()
    _write_rows(limiter, [
        {"timestamp": (datetime.utcnow() - timedelta(hours=2)).isoformat(), "action": "post",
         "success": True, "next_allowed_at": past},
    ])
    ok, reason = limiter.can_proceed("post")
    assert (ok, reason) == (True, "ok")


def test_ignore_gap_skips_gap_but_not_count_cap(tmp_path):
    limiter = _make_limiter(tmp_path, posts_per_day=1)
    future = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    now = datetime.utcnow().isoformat()
    _write_rows(limiter, [
        {"timestamp": now, "action": "post", "success": True, "next_allowed_at": future},
    ])
    # Gap alone would block this — ignore_gap=True should skip past it...
    ok, reason = limiter.can_proceed("post", ignore_gap=True)
    # ...but the count cap (posts_per_day=1, already 1 logged) still refuses.
    assert ok is False
    assert reason == "posts_per_day limit reached"


def test_gap_scoped_per_action_type(tmp_path):
    """A comment logged just now must not block a post — see
    next_allowed_at()'s docstring: gap is tracked per action_type bucket."""
    limiter = _make_limiter(tmp_path, min_delay_seconds=3600, max_delay_seconds=3600)
    future = (datetime.utcnow() + timedelta(hours=1)).isoformat()
    _write_rows(limiter, [
        {"timestamp": datetime.utcnow().isoformat(), "action": "comment",
         "success": True, "next_allowed_at": future},
    ])
    ok, reason = limiter.can_proceed("post")
    assert (ok, reason) == (True, "ok")


def test_record_writes_next_allowed_at_within_configured_range(tmp_path):
    limiter = _make_limiter(tmp_path, min_delay_seconds=100, max_delay_seconds=200)
    before = datetime.utcnow()
    limiter.record("post", success=True)
    allowed_at = limiter.next_allowed_at("post")
    assert allowed_at is not None
    delta = (allowed_at - before).total_seconds()
    # Generous tolerance around [100, 200] for wall-clock jitter during the test.
    assert 95 <= delta <= 205
