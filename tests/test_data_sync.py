from __future__ import annotations

from datetime import date, datetime, timedelta, timezone

import human_bot.schedule_store as schedule_store
from human_bot.data_sync import (
    _count_scheduled_actions_by_day,
    _next_available_business_day,
    _next_available_post_slot,
)
from human_bot.data_sync_config import DataSyncConfig


# --- _next_available_post_slot (quiet hours + per-group gap only, no capacity) ---

def test_next_available_post_slot_pushes_out_of_quiet_hours():
    cfg = DataSyncConfig()
    # 03:00 UTC == 12:00 JST — well outside quiet hours (2-6 AM JST
    # default), so this exact case doesn't clamp; use a real quiet-hours
    # UTC time instead: 18:30 UTC == 03:30 JST next day, inside 2-6 AM.
    dt = datetime(2026, 9, 10, 18, 30, tzinfo=timezone.utc)
    result = _next_available_post_slot(dt, cfg, "https://group.a", {})
    jst_hour = (result + timedelta(hours=9)).hour
    assert cfg.quiet_hour_end_local <= jst_hour < cfg.quiet_hour_start_local + 24 or jst_hour >= cfg.quiet_hour_end_local
    assert result > dt


def test_next_available_post_slot_leaves_active_hours_untouched():
    cfg = DataSyncConfig()
    dt = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)  # noon JST — active hours
    result = _next_available_post_slot(dt, cfg, "https://group.a", {})
    assert result == dt


def test_next_available_post_slot_enforces_per_group_min_gap():
    cfg = DataSyncConfig()
    dt = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)
    last_group_post_at = {"https://group.a": dt}
    result = _next_available_post_slot(dt, cfg, "https://group.a", last_group_post_at)
    expected_min = dt + timedelta(minutes=cfg.post_gap_min_minutes)
    assert result >= expected_min


def test_next_available_post_slot_different_group_unaffected_by_gap():
    cfg = DataSyncConfig()
    dt = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)
    last_group_post_at = {"https://group.a": dt}
    result = _next_available_post_slot(dt, cfg, "https://group.b", last_group_post_at)
    assert result == dt


# --- _next_available_business_day (day-rollover, business-day keyed) --------

def test_next_available_business_day_no_rollover_when_room_today():
    today = date(2026, 9, 11)
    dt = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)  # inside today's business day
    day_counts = {today: 1}
    new_dt, day_key, available = _next_available_business_day(
        dt, daily_limit=5, day_counts=day_counts, today_key=today, real_used_today=1,
    )
    assert new_dt == dt
    assert day_key == today
    assert available == 4  # 5 - max(1 scheduled, 1 real) = 4


def test_next_available_business_day_partial_capacity_matches_owners_example():
    """The exact scenario from the conversation: 5 slots/day, 3 already
    used (scheduled == real, both counted), 2 left — a job capped at 3
    groups should only get 2, not 0 (deferred) or 3 (over capacity)."""
    today = date(2026, 9, 11)
    dt = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
    day_counts = {today: 3}
    _new_dt, day_key, available = _next_available_business_day(
        dt, daily_limit=5, day_counts=day_counts, today_key=today, real_used_today=3,
    )
    assert day_key == today  # no rollover — there IS room today
    assert available == 2
    groups_to_post = min(3, available)  # max_groups_per_post=3, capped further by available
    assert groups_to_post == 2


def test_next_available_business_day_rolls_over_when_full():
    today = date(2026, 9, 11)
    dt = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
    day_counts = {today: 3}
    new_dt, day_key, available = _next_available_business_day(
        dt, daily_limit=3, day_counts=day_counts, today_key=today, real_used_today=3,
    )
    assert day_key == date(2026, 9, 12)  # rolled to the NEXT business day
    assert available == 3  # nothing scheduled there yet, real_used_today doesn't apply (different day)
    assert new_dt > dt


def test_next_available_business_day_future_day_ignores_real_used_today():
    """real_used_today only applies to `today_key` itself — a future
    business day starts from a clean slate regardless of how busy today
    was, since nothing real has happened there yet."""
    today = date(2026, 9, 11)
    tomorrow = date(2026, 9, 12)
    dt = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
    # Today full (3/3), tomorrow already has 1 scheduled from a prior poll.
    day_counts = {today: 3, tomorrow: 1}
    _new_dt, day_key, available = _next_available_business_day(
        dt, daily_limit=3, day_counts=day_counts, today_key=today, real_used_today=3,
    )
    assert day_key == tomorrow
    assert available == 2  # 3 - max(1 scheduled, 0 real for a future day) = 2


def test_next_available_business_day_gives_up_after_60_days_when_pathological():
    today = date(2026, 9, 11)
    dt = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
    _new_dt, _day_key, available = _next_available_business_day(
        dt, daily_limit=0, day_counts={}, today_key=today, real_used_today=0,
    )
    assert available == 0


def test_next_available_business_day_rollover_lands_at_2am_jst_boundary():
    """Confirms the rollover jumps to the business-day START (2 AM JST),
    not UTC midnight — the caller then runs this through
    _next_available_post_slot()'s quiet-hours clamp separately."""
    today = date(2026, 9, 11)
    dt = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
    day_counts = {today: 1}
    new_dt, day_key, _available = _next_available_business_day(
        dt, daily_limit=1, day_counts=day_counts, today_key=today, real_used_today=1,
    )
    jst = new_dt + timedelta(hours=9)
    assert jst.hour == 2 and jst.minute == 0
    assert day_key == date(2026, 9, 12)


# --- _count_scheduled_actions_by_day (business-day keyed, not raw UTC date) ---

class _FakeTask:
    def __init__(self, account_id, action, scheduled_at):
        self.account_id = account_id
        self.action = action
        self.scheduled_at = scheduled_at


def test_count_scheduled_actions_by_day_groups_by_business_day_not_utc_date(monkeypatch):
    # 2026-09-11T00:30:00+00:00 is 09:30 JST on 9/11 — well after the 2
    # AM JST boundary, so business day 9/11 (SAME as its UTC calendar
    # date here — chosen deliberately below to also test a mismatch).
    same_day = _FakeTask("acc1", "post_to_group", "2026-09-11T00:30:00+00:00")
    # 2026-09-11T16:30:00+00:00 is 01:30 JST on 9/12 — BEFORE the 2 AM
    # JST boundary, so it belongs to business day 9/11 even though its
    # own UTC calendar date is already 9/11 turning into 9/12 wall-clock
    # wise. This is the exact case the old _utc_today()-based version
    # would have miscounted.
    late_utc_but_still_business_day_11 = _FakeTask("acc1", "post_to_group", "2026-09-11T16:30:00+00:00")
    other_account = _FakeTask("acc2", "post_to_group", "2026-09-11T00:30:00+00:00")
    wrong_action = _FakeTask("acc1", "comment_on_group_post", "2026-09-11T00:30:00+00:00")

    monkeypatch.setattr(schedule_store, "list_pending", lambda: [same_day, late_utc_but_still_business_day_11])
    monkeypatch.setattr(schedule_store, "list_posted", lambda: [other_account, wrong_action])

    counts = _count_scheduled_actions_by_day("acc1", {"post_to_group"})
    assert counts == {date(2026, 9, 11): 2}


def test_count_scheduled_actions_by_day_no_matching_tasks(monkeypatch):
    monkeypatch.setattr(schedule_store, "list_pending", lambda: [])
    monkeypatch.setattr(schedule_store, "list_posted", lambda: [])
    assert _count_scheduled_actions_by_day("acc1", {"post_to_group"}) == {}
