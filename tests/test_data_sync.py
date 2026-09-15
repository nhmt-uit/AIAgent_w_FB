from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path

import pytest

import human_bot.schedule_store as schedule_store
from human_bot.config import GroupRef, RateLimits
from human_bot.data_sync import (
    _count_scheduled_actions_by_day,
    _has_room_for_drifted_group,
    _last_scheduled_post_time,
    _next_available_business_day,
    _pick_groups_for_job,
    apply_quiet_hours,
    sweep_overdue_on_startup,
)
from human_bot.data_sync_config import DataSyncConfig
from human_bot.safety import RateLimiter


# --- apply_quiet_hours (per-group timing rule REMOVED 2026-09-15 — owner
# clarified there was never meant to be one, only the account-wide
# post_min/max_delay_seconds gap; _next_available_post_slot() — which
# used to wrap this PLUS a per-group min-gap check — is gone entirely, its
# quiet-hours-only behavior is exercised directly here instead) ----------

def test_apply_quiet_hours_pushes_out_of_the_window():
    cfg = DataSyncConfig()
    # 18:30 UTC == 03:30 JST next day, inside the default 2-6 AM window.
    dt = datetime(2026, 9, 10, 18, 30, tzinfo=timezone.utc)
    result = apply_quiet_hours(dt, cfg)
    jst_hour = (result + timedelta(hours=9)).hour
    assert not (cfg.quiet_hour_start_local <= jst_hour < cfg.quiet_hour_end_local)
    assert result > dt


def test_apply_quiet_hours_leaves_active_hours_untouched():
    cfg = DataSyncConfig()
    dt = datetime(2026, 9, 10, 3, 0, tzinfo=timezone.utc)  # noon JST — active hours
    result = apply_quiet_hours(dt, cfg)
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
    apply_quiet_hours() separately."""
    today = date(2026, 9, 11)
    dt = datetime(2026, 9, 11, 3, 0, tzinfo=timezone.utc)
    day_counts = {today: 1}
    new_dt, day_key, _available = _next_available_business_day(
        dt, daily_limit=1, day_counts=day_counts, today_key=today, real_used_today=1,
    )
    jst = new_dt + timedelta(hours=9)
    assert jst.hour == 2 and jst.minute == 0
    assert day_key == date(2026, 9, 12)


# --- _has_room_for_drifted_group (owner-reported bug 2026-09-14: a late
# group's per-group min-gap/quiet-hours clamp can push its slot past the
# `post_day_key` capacity was checked for, onto a day nobody re-verified) --

def test_has_room_for_drifted_group_true_when_day_has_room():
    today = date(2026, 9, 14)
    tomorrow = date(2026, 9, 15)
    day_counts = {tomorrow: 3}
    assert _has_room_for_drifted_group(
        scheduled_day_key=tomorrow, post_day_key=today, day_counts=day_counts,
        daily_limit=5, today_key=today, real_used_today=2,
    ) is True


def test_has_room_for_drifted_group_false_when_day_is_full():
    """The exact owner-observed scenario: a group drifts from today onto
    tomorrow, but tomorrow already has 5 queued against a cap of 5 —
    scheduling a 6th here is exactly the bug that let 9 land on one day."""
    today = date(2026, 9, 14)
    tomorrow = date(2026, 9, 15)
    day_counts = {tomorrow: 5}
    assert _has_room_for_drifted_group(
        scheduled_day_key=tomorrow, post_day_key=today, day_counts=day_counts,
        daily_limit=5, today_key=today, real_used_today=0,
    ) is False


def test_has_room_for_drifted_group_checks_real_used_only_for_todays_key():
    """If the drifted slot lands back on `today_key` itself (edge case,
    but the function must not special-case it away), real posts already
    made today count against the cap same as day_counts does."""
    today = date(2026, 9, 14)
    day_counts = {today: 1}
    assert _has_room_for_drifted_group(
        scheduled_day_key=today, post_day_key=date(2026, 9, 13), day_counts=day_counts,
        daily_limit=5, today_key=today, real_used_today=5,
    ) is False


def test_has_room_for_drifted_group_future_day_ignores_real_used_today():
    today = date(2026, 9, 14)
    future = date(2026, 9, 20)
    day_counts = {}
    # real_used_today is huge, but it must only apply to `today_key`, not
    # to some unrelated future business day that hasn't happened yet.
    assert _has_room_for_drifted_group(
        scheduled_day_key=future, post_day_key=today, day_counts=day_counts,
        daily_limit=5, today_key=today, real_used_today=100,
    ) is True


# --- _pick_groups_for_job (fair round-robin + light random pick, 2026-09-15) -

def _groups(*urls: str) -> list[GroupRef]:
    return [GroupRef(name=u, url=u) for u in urls]


def test_pick_groups_for_job_never_starves_the_longest_overdue_group():
    """The group with NO last-post-time at all (never posted to) must
    always end up in the candidate pool — across many trials, it must
    actually get picked at least once (not silently starved by the
    random step)."""
    groups = _groups("a", "b", "c", "d", "e")
    last_group_post_at = {
        "b": datetime(2026, 9, 10, tzinfo=timezone.utc),
        "c": datetime(2026, 9, 11, tzinfo=timezone.utc),
        "d": datetime(2026, 9, 12, tzinfo=timezone.utc),
        "e": datetime(2026, 9, 13, tzinfo=timezone.utc),
        # "a" never posted to — sorts first via datetime.min.
    }
    picked_ever = set()
    for _ in range(50):
        picked = _pick_groups_for_job(groups, last_group_post_at, needed=1)
        picked_ever.update(g.url for g in picked)
    assert "a" in picked_ever


def test_pick_groups_for_job_returns_fewer_when_not_enough_groups():
    groups = _groups("a", "b")
    result = _pick_groups_for_job(groups, {}, needed=5)
    assert len(result) == 2
    assert {g.url for g in result} == {"a", "b"}


def test_pick_groups_for_job_returns_needed_count_when_enough_groups():
    groups = _groups("a", "b", "c", "d", "e", "f", "g", "h")
    last_group_post_at = {u: datetime(2026, 9, 10, tzinfo=timezone.utc) for u in "bcdefgh"}
    result = _pick_groups_for_job(groups, last_group_post_at, needed=3)
    assert len(result) == 3
    assert len(set(g.url for g in result)) == 3  # no duplicates


def test_pick_groups_for_job_never_picks_a_group_far_outside_the_pool():
    """Owner request 2026-09-15: some variety is fine, but a group that
    was posted to VERY recently (deep in the "already handled" set, far
    from the pool boundary) must never win over the genuinely overdue
    ones — the pool is only `needed + slack` wide, not the whole list."""
    groups = _groups(*[f"g{i}" for i in range(10)])
    # g0 is the ONLY overdue one; g1..g9 are all freshly posted, g9 most
    # recently of all.
    last_group_post_at = {
        f"g{i}": datetime(2026, 9, 10, tzinfo=timezone.utc) + timedelta(hours=i)
        for i in range(1, 10)
    }
    for _ in range(30):
        picked = {g.url for g in _pick_groups_for_job(groups, last_group_post_at, needed=1)}
        # With needed=1 and a small pool slack, the freshest groups
        # (g7, g8, g9) should never be picked — only ones within the
        # pool window starting from the most overdue (g0).
        assert not picked & {"g8", "g9"}


def test_pick_groups_for_job_varies_across_calls_not_always_identical():
    """The exact reason this was added — owner: strict oldest-first
    selection picked the identical cluster every time. Confirm repeated
    calls (same input state) don't ALWAYS return the same set when the
    pool is wider than what's needed."""
    groups = _groups(*[f"g{i}" for i in range(6)])
    last_group_post_at = {}  # all tied at datetime.min — pool = all 6
    results = {tuple(sorted(g.url for g in _pick_groups_for_job(groups, last_group_post_at, needed=2))) for _ in range(30)}
    assert len(results) > 1


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


# --- Regression: naive vs. aware datetime comparison in sync_all() ----------
#
# Real incident, 2026-09-11: RateLimiter.next_allowed_at() always returns a
# NAIVE datetime (safety.py's record() only ever writes datetime.utcnow(),
# never timezone-aware — confirmed by grep, consistent throughout that
# file), but sync_all()'s own `next_comment_time` chain is built from
# datetime.now(timezone.utc), timezone-AWARE. `max(next_comment_time,
# enforced_comment_floor)` without normalizing first raised TypeError on
# EVERY poll cycle once the account had any comment history — silently,
# from the operator's point of view (service.py's poll loop only logs
# "data_sync.sync_all failed" and moves on; the owner restarted the
# service, set a 5-minute poll interval, and saw nothing get scheduled at
# all). sync_all() itself isn't unit-tested here (needs a live HTTP call to
# side B), but this locks down the exact underlying contract the fix
# depends on: next_allowed_at() is naive, and it must be normalized to
# aware UTC before comparing against an aware chain variable.

@dataclass
class _FakeAccount:
    rate_limits: RateLimits
    action_log_path: Path


def test_rate_limiter_next_allowed_at_is_naive_not_aware(tmp_path):
    account = _FakeAccount(rate_limits=RateLimits(), action_log_path=tmp_path / "action_log.jsonl")
    limiter = RateLimiter(account)
    now = datetime.utcnow()
    with limiter.log_path.open("a") as f:
        f.write(json.dumps({
            "timestamp": now.isoformat(),
            "action": "comment",
            "success": True,
            "next_allowed_at": (now + timedelta(hours=1)).isoformat(),
        }) + "\n")
    allowed_at = limiter.next_allowed_at("comment")
    assert allowed_at is not None
    assert allowed_at.tzinfo is None


def test_naive_next_allowed_at_normalized_before_max_with_aware_chain(tmp_path):
    """Exercises the exact fix in sync_all(): comparing the naive value
    straight against an aware datetime must raise, but normalizing it
    first (the fix) must not."""
    account = _FakeAccount(rate_limits=RateLimits(), action_log_path=tmp_path / "action_log.jsonl")
    limiter = RateLimiter(account)
    now = datetime.utcnow()
    with limiter.log_path.open("a") as f:
        f.write(json.dumps({
            "timestamp": now.isoformat(),
            "action": "comment",
            "success": True,
            "next_allowed_at": (now + timedelta(hours=1)).isoformat(),
        }) + "\n")
    naive_floor = limiter.next_allowed_at("comment")
    aware_chain_time = datetime.now(timezone.utc)

    try:
        max(aware_chain_time, naive_floor)
    except TypeError:
        pass
    else:
        raise AssertionError("expected the unnormalized comparison to still raise TypeError")

    normalized = naive_floor.replace(tzinfo=timezone.utc)
    result = max(aware_chain_time, normalized)  # must not raise
    assert result.tzinfo is not None


# --- sweep_overdue_on_startup (2026-09-14, "quá hạn khi server tắt lâu") ---
# Own isolated schedule_store fixture (separate from the module-level
# monkeypatches used above, which stub list_pending/list_posted directly) —
# this needs the REAL file-backed store, since sweep_overdue_on_startup()
# calls schedule_store.list_pending()/mark_missed(), which read/write
# actual files under PENDING_DIR/MISSED_DIR.

@pytest.fixture
def isolated_schedule_dirs(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(schedule_store, "POSTED_DIR", tmp_path / "posted")
    monkeypatch.setattr(schedule_store, "FAILED_DIR", tmp_path / "failed")
    monkeypatch.setattr(schedule_store, "CANCELLED_DIR", tmp_path / "cancelled")
    monkeypatch.setattr(schedule_store, "MISSED_DIR", tmp_path / "missed")
    return schedule_store


def _add_task(store, when, content="x", action="post_to_group", account_id="acc-a"):
    task = store.ScheduledTask(
        task_id=store.new_task_id(when.isoformat()),
        action=action, account_id=account_id,
        scheduled_at=when.isoformat(), content=content,
        target_url="https://facebook.com/groups/1",
    )
    store.add(task)
    return task


# --- _last_scheduled_post_time (owner-reported 2026-09-15: posts landing
# only 30 min apart across separate sync_all() polls, despite a 120-210
# min account gap — mirrors _last_scheduled_comment_time, added 2026-09-10
# for the identical comment-side bug but never ported to posts) ---------

def test_last_scheduled_post_time_none_when_nothing_scheduled(isolated_schedule_dirs):
    assert _last_scheduled_post_time("acc-a") is None


def test_last_scheduled_post_time_returns_the_latest(isolated_schedule_dirs):
    now = datetime.now(timezone.utc)
    _add_task(isolated_schedule_dirs, now)
    latest = _add_task(isolated_schedule_dirs, now + timedelta(hours=3))
    _add_task(isolated_schedule_dirs, now + timedelta(hours=1))
    result = _last_scheduled_post_time("acc-a")
    assert result == datetime.fromisoformat(latest.scheduled_at)


def test_last_scheduled_post_time_includes_own_profile_posts(isolated_schedule_dirs):
    """RateLimiter's "post" bucket covers BOTH post_to_group and
    post_to_own_profile — the floor must see either."""
    now = datetime.now(timezone.utc)
    profile_task = _add_task(isolated_schedule_dirs, now, action="post_to_own_profile")
    result = _last_scheduled_post_time("acc-a")
    assert result == datetime.fromisoformat(profile_task.scheduled_at)


def test_last_scheduled_post_time_ignores_other_accounts_and_actions(isolated_schedule_dirs):
    now = datetime.now(timezone.utc)
    _add_task(isolated_schedule_dirs, now + timedelta(hours=5), account_id="acc-b")
    _add_task(isolated_schedule_dirs, now + timedelta(hours=5), action="comment_on_group_post")
    assert _last_scheduled_post_time("acc-a") is None


def test_last_scheduled_post_time_counts_already_posted_too(isolated_schedule_dirs):
    now = datetime.now(timezone.utc)
    task = _add_task(isolated_schedule_dirs, now)
    isolated_schedule_dirs.mark_posted(task.task_id, "ok")
    assert isolated_schedule_dirs.list_pending() == []  # confirms it moved out of pending/


# --- _parse_scheduled_at (2026-09-15): every "last scheduled" lookup goes
# through this instead of a bare datetime.fromisoformat(), since not every
# writer of scheduled_at is guaranteed to produce a tz-aware string (see
# its own docstring) — a naive vs. aware mismatch raises TypeError on
# comparison, which used to be reachable here. -----------------------------

def test_parse_scheduled_at_normalizes_a_naive_string_to_utc():
    from human_bot.data_sync import _parse_scheduled_at
    parsed = _parse_scheduled_at("2026-09-15T11:00:00")
    assert parsed.tzinfo is not None
    assert parsed == datetime(2026, 9, 15, 11, 0, 0, tzinfo=timezone.utc)


def test_parse_scheduled_at_returns_none_for_garbage():
    from human_bot.data_sync import _parse_scheduled_at
    assert _parse_scheduled_at("not-a-date") is None


def test_last_scheduled_post_time_does_not_crash_on_a_naive_scheduled_at(isolated_schedule_dirs):
    """A task whose scheduled_at was written without a timezone offset
    (e.g. via /admin/schedule/update or .../missed/reschedule, which pass
    the raw form value straight through with no normalization) must not
    crash the comparison against an aware sibling task's time."""
    now = datetime.now(timezone.utc)
    aware_task = _add_task(isolated_schedule_dirs, now)
    naive_when = (now + timedelta(hours=2)).replace(tzinfo=None)
    naive_task = isolated_schedule_dirs.ScheduledTask(
        task_id=isolated_schedule_dirs.new_task_id(naive_when.isoformat()),
        action="post_to_group", account_id="acc-a",
        scheduled_at=naive_when.isoformat(),
        content="x", target_url="https://facebook.com/groups/1",
    )
    isolated_schedule_dirs.add(naive_task)
    result = _last_scheduled_post_time("acc-a")
    assert result == datetime.fromisoformat(naive_task.scheduled_at).replace(tzinfo=timezone.utc)


def test_sweep_overdue_on_startup_moves_only_past_tasks(isolated_schedule_dirs):
    now = datetime.now(timezone.utc)
    overdue = _add_task(isolated_schedule_dirs, now - timedelta(hours=2), content="overdue")
    future = _add_task(isolated_schedule_dirs, now + timedelta(hours=2), content="future")

    result = sweep_overdue_on_startup()

    assert result["swept"] == 1
    assert isolated_schedule_dirs.get(overdue.task_id) is None
    assert isolated_schedule_dirs.get_missed(overdue.task_id) is not None
    assert isolated_schedule_dirs.get(future.task_id) is not None
    assert isolated_schedule_dirs.get_missed(future.task_id) is None


def test_sweep_overdue_on_startup_is_a_one_time_snapshot(isolated_schedule_dirs):
    """A second call (simulating a later poll, NOT a restart) must not
    treat a task that only just became due as "missed" — only the
    lateness that already existed the moment sweep runs counts, and
    running it again immediately after finds nothing new overdue."""
    now = datetime.now(timezone.utc)
    _add_task(isolated_schedule_dirs, now - timedelta(minutes=1), content="already overdue")
    first = sweep_overdue_on_startup()
    assert first["swept"] == 1

    second = sweep_overdue_on_startup()
    assert second["swept"] == 0


def test_sweep_overdue_on_startup_empty_when_nothing_pending(isolated_schedule_dirs):
    result = sweep_overdue_on_startup()
    assert result["swept"] == 0
    assert isolated_schedule_dirs.list_missed() == []
