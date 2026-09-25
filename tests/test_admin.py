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
from human_bot.admin import (
    _clamp_missed_min_days,
    _clamp_schedule_page_size,
    _fmt_jst,
    _local_dt_html,
    _localize_iso_timestamps_html,
    _safe_next_path,
    _schedule_form_filter,
    _sponsor_badge_html,
    _suggest_reschedule_at,
    _task_local_date,
)
from human_bot.config import RateLimits
from human_bot.data_sync_config import DataSyncConfig
from human_bot import daily_limits


@dataclass
class _FakeAccount:
    account_id: str
    rate_limits: RateLimits
    action_log_path: Path


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


def _fake_task(job_data=None, candidate_data=None) -> schedule_store.ScheduledTask:
    return schedule_store.ScheduledTask(
        task_id="t1", action="post_to_group", account_id="acc-a",
        scheduled_at=datetime.now(timezone.utc).isoformat(),
        job_data=job_data, candidate_data=candidate_data,
    )


def test_sponsor_badge_shown_when_job_has_sponsored_by():
    """2026-09-25 owner request: a job-sourced task whose job carried a
    sponsored_by value should show a "Sponsor" tag next to the action
    badge in both /admin/schedule's "Chờ đăng" and "Task quá hạn" tabs."""
    task = _fake_task(job_data={"title": "x", "sponsored_by": "AcmeCorp"})
    assert "Sponsor" in _sponsor_badge_html(task)


def test_sponsor_badge_empty_when_job_data_missing_sponsored_by():
    task = _fake_task(job_data={"title": "x", "sponsored_by": None})
    assert _sponsor_badge_html(task) == ""


def test_sponsor_badge_empty_for_candidate_sourced_task():
    task = _fake_task(candidate_data={"attributes": {}})
    assert _sponsor_badge_html(task) == ""


def test_sponsor_badge_empty_when_no_job_or_candidate_data():
    task = _fake_task()
    assert _sponsor_badge_html(task) == ""


# --- Phase 1 (2026-09-25 test-coverage plan): more admin.py pure functions ---

def test_safe_next_path_accepts_bare_admin_and_admin_subpaths():
    assert _safe_next_path("/admin") == "/admin"
    assert _safe_next_path("/admin/schedule") == "/admin/schedule"
    assert _safe_next_path("/admin/schedule?tab=missed") == "/admin/schedule?tab=missed"


def test_safe_next_path_rejects_protocol_relative_and_absolute_urls():
    assert _safe_next_path("//evil.example") == "/admin"
    assert _safe_next_path("https://evil.example/admin") == "/admin"
    assert _safe_next_path("/admin/../https://evil.example") == "/admin"


def test_safe_next_path_rejects_blank_or_unrelated_path():
    assert _safe_next_path(None) == "/admin"
    assert _safe_next_path("") == "/admin"
    assert _safe_next_path("/other-page") == "/admin"


def test_fmt_jst_adds_nine_hours():
    assert _fmt_jst("2026-01-01T00:00:00+00:00") == "09:00 01-01-2026"


def test_fmt_jst_blank_or_malformed_input():
    assert _fmt_jst(None) == "—"
    assert _fmt_jst("") == "—"
    assert _fmt_jst("not-a-date") == "not-a-date"


def test_local_dt_html_embeds_utc_and_jst_fallback():
    out = _local_dt_html("2026-01-01T00:00:00+00:00")
    assert 'data-utc="2026-01-01T00:00:00+00:00"' in out
    assert "09:00 01-01-2026" in out


def test_local_dt_html_blank_input():
    assert _local_dt_html(None) == "—"


def test_localize_iso_timestamps_html_replaces_only_the_timestamp():
    text = "Đã quá giờ đăng dự kiến (2026-09-24T10:17:38.337289+00:00) lúc service khởi động lại."
    out = _localize_iso_timestamps_html(text)
    assert "Đã quá giờ đăng dự kiến (" in out
    assert 'data-utc="2026-09-24T10:17:38.337289+00:00"' in out
    assert ") lúc service khởi động lại." in out


def test_localize_iso_timestamps_html_escapes_surrounding_text():
    """The surrounding free text is NOT a trusted timestamp — must still
    be html.escape()'d so it can't inject markup."""
    out = _localize_iso_timestamps_html("<script>alert(1)</script>")
    assert "<script>" not in out
    assert "&lt;script&gt;" in out


def test_localize_iso_timestamps_html_no_timestamp_present():
    assert _localize_iso_timestamps_html("plain text, no dates here") == "plain text, no dates here"


def test_clamp_schedule_page_size_allowlist():
    assert _clamp_schedule_page_size(50) == 50
    assert _clamp_schedule_page_size(7) == 20  # not in the allowlist -> default
    assert _clamp_schedule_page_size(-1) == 20
    assert _clamp_schedule_page_size(0) == 20


def test_clamp_missed_min_days_allowlist():
    assert _clamp_missed_min_days(7) == 7
    assert _clamp_missed_min_days(None) is None
    assert _clamp_missed_min_days(4) is None  # not one of (3, 5, 7, 30)
    assert _clamp_missed_min_days(-5) is None


def test_task_local_date_applies_tz_offset():
    # 2026-01-01T23:30:00Z + 9h (JST) = 2026-01-02
    assert _task_local_date("2026-01-01T23:30:00+00:00", 540) == "2026-01-02"
    # Same instant with no offset stays on the UTC calendar day.
    assert _task_local_date("2026-01-01T23:30:00+00:00", 0) == "2026-01-01"


def test_task_local_date_blank_or_malformed_input():
    assert _task_local_date(None, 540) is None
    assert _task_local_date("not-a-date", 540) is None


def test_schedule_form_filter_defaults_on_malformed_input():
    """Every numeric field falls back to its documented default instead
    of raising when the form value can't be parsed as an int."""
    form = {
        "account_id": "  acc-a  ",
        "page": "not-a-number",
        "page_size": "not-a-number",
        "missed_page": "not-a-number",
        "action": "not-a-real-action",
        "date": "  2026-01-01  ",
        "tz_offset": "not-a-number",
        "missed_min_days": "not-a-number",
    }
    account_id, page, page_size, missed_page, action_filter, date_filter, tz_offset, missed_min_days = (
        _schedule_form_filter(form)
    )
    assert account_id == "acc-a"
    assert page == 1
    assert page_size == 20
    assert missed_page == 1
    assert action_filter is None  # not in the allowlist
    assert date_filter == "2026-01-01"
    assert tz_offset == 0
    assert missed_min_days is None


def test_schedule_form_filter_parses_valid_values():
    form = {
        "account_id": "acc-b",
        "page": "3",
        "page_size": "50",
        "missed_page": "2",
        "action": "post_to_group",
        "date": "",
        "tz_offset": "540",
        "missed_min_days": "7",
    }
    account_id, page, page_size, missed_page, action_filter, date_filter, tz_offset, missed_min_days = (
        _schedule_form_filter(form)
    )
    assert account_id == "acc-b"
    assert page == 3
    assert page_size == 50
    assert missed_page == 2
    assert action_filter == "post_to_group"
    assert date_filter is None
    assert tz_offset == 540
    assert missed_min_days == 7


def test_schedule_form_filter_empty_account_id_becomes_none():
    assert _schedule_form_filter({"account_id": "   "})[0] is None
