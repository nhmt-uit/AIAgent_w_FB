"""Tests for human_bot/schedule_store.py's "missed" status — the
2026-09-14 addition backing /admin/schedule's "⚠️ Task quá hạn cần duyệt"
section: list_missed(), get_missed(), get_missed_reason(), mark_missed(),
restore_to_pending(), cancel_missed(). Isolated from the real scheduled/
directory by monkeypatching all 5 status-dir constants to tmp_path
subdirectories (per project rule: never touch real on-disk state in
tests)."""
from datetime import datetime, timedelta, timezone

import pytest

import human_bot.schedule_store as schedule_store


@pytest.fixture
def isolated_store(tmp_path, monkeypatch):
    monkeypatch.setattr(schedule_store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(schedule_store, "POSTED_DIR", tmp_path / "posted")
    monkeypatch.setattr(schedule_store, "FAILED_DIR", tmp_path / "failed")
    monkeypatch.setattr(schedule_store, "CANCELLED_DIR", tmp_path / "cancelled")
    monkeypatch.setattr(schedule_store, "MISSED_DIR", tmp_path / "missed")
    return schedule_store


def _make_task(store, when: datetime, content="hello", action="post_to_group") -> schedule_store.ScheduledTask:
    task = store.ScheduledTask(
        task_id=store.new_task_id(when.isoformat()),
        action=action,
        account_id="acc-a",
        scheduled_at=when.isoformat(),
        content=content,
        target_url="https://facebook.com/groups/1",
    )
    store.add(task)
    return task


def test_move_to_reads_source_dir_at_call_time_not_def_time(isolated_store):
    """Regression test for a real bug found 2026-09-14: _move_to()'s
    source_dir used to default to the module-level PENDING_DIR VALUE at
    function-definition (import) time, so monkeypatching
    schedule_store.PENDING_DIR afterward had no effect on that default —
    mark_missed() would silently write into the real, un-monkeypatched
    directory instead of the isolated tmp_path one. This must not
    regress: after monkeypatching, mark_missed() has to actually move
    the file out of the ISOLATED PENDING_DIR."""
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(hours=1))
    isolated_store.mark_missed(task.task_id, "test")
    assert isolated_store.get(task.task_id) is None  # gone from pending
    assert isolated_store.get_missed(task.task_id) is not None  # landed in missed
    # And the isolated PENDING_DIR itself has no leftover file.
    assert list((isolated_store.PENDING_DIR).glob("*.json")) == []


def test_mark_missed_writes_reason(isolated_store):
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(hours=1))
    isolated_store.mark_missed(task.task_id, "server was down")
    assert isolated_store.get_missed_reason(task.task_id) == "server was down"


def test_get_missed_reason_none_when_absent(isolated_store):
    assert isolated_store.get_missed_reason("nonexistent") is None


def test_list_missed_returns_only_missed_tasks(isolated_store):
    now = datetime.now(timezone.utc)
    t1 = _make_task(isolated_store, now - timedelta(hours=1), content="a")
    t2 = _make_task(isolated_store, now - timedelta(hours=2), content="b")
    still_pending = _make_task(isolated_store, now + timedelta(hours=1), content="c")
    isolated_store.mark_missed(t1.task_id, "r1")
    isolated_store.mark_missed(t2.task_id, "r2")
    missed = isolated_store.list_missed()
    assert {t.content for t in missed} == {"a", "b"}
    assert isolated_store.get(still_pending.task_id) is not None


def test_restore_to_pending_moves_back_and_applies_updates(isolated_store):
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(hours=1), content="old content")
    isolated_store.mark_missed(task.task_id, "test")
    new_time = (now + timedelta(hours=3)).isoformat()
    restored = isolated_store.restore_to_pending(task.task_id, content="new content", scheduled_at=new_time)
    assert restored is not None
    assert restored.content == "new content"
    assert restored.scheduled_at == new_time
    assert isolated_store.get_missed(task.task_id) is None
    back = isolated_store.get(task.task_id)
    assert back is not None
    assert back.content == "new content"


def test_restore_to_pending_returns_none_if_already_resolved(isolated_store):
    assert isolated_store.restore_to_pending("nonexistent", scheduled_at="2026-01-01T00:00:00+00:00") is None


def test_cancel_missed_moves_to_cancelled(isolated_store):
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(hours=1))
    isolated_store.mark_missed(task.task_id, "test")
    assert isolated_store.cancel_missed(task.task_id) is True
    assert isolated_store.get_missed(task.task_id) is None
    cancelled_files = list((isolated_store.CANCELLED_DIR).glob("*.json"))
    assert len(cancelled_files) == 1


def test_cancel_missed_false_when_absent(isolated_store):
    assert isolated_store.cancel_missed("nonexistent") is False


def test_mark_posted_from_missed_dir(isolated_store):
    """2026-09-25: mark_posted()/mark_failed() gained an optional
    source_dir so /admin/schedule's "⚠️ Task quá hạn" tab can get its own
    "🚀 Đăng ngay" button — firing a task straight out of MISSED_DIR
    without first bouncing it through pending/ via restore_to_pending()."""
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(hours=1))
    isolated_store.mark_missed(task.task_id, "quá hạn")
    isolated_store.mark_posted(task.task_id, "posted ok", source_dir=isolated_store.MISSED_DIR)
    assert isolated_store.get_missed(task.task_id) is None
    posted_files = list(isolated_store.POSTED_DIR.glob("*.json"))
    assert len(posted_files) == 1
    result_txt = isolated_store.POSTED_DIR / f"{task.task_id}.result.txt"
    assert result_txt.read_text(encoding="utf-8") == "posted ok"
    # The original miss-reason .result.txt is left behind in MISSED_DIR,
    # same "leave audit note behind" convention as cancel_missed().
    assert (isolated_store.MISSED_DIR / f"{task.task_id}.result.txt").read_text(encoding="utf-8") == "quá hạn"


def test_mark_failed_from_missed_dir(isolated_store):
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(hours=1))
    isolated_store.mark_missed(task.task_id, "quá hạn")
    isolated_store.mark_failed(task.task_id, "lỗi thật", source_dir=isolated_store.MISSED_DIR)
    assert isolated_store.get_missed(task.task_id) is None
    failed_files = list(isolated_store.FAILED_DIR.glob("*.json"))
    assert len(failed_files) == 1


def test_mark_posted_default_source_dir_still_pending(isolated_store):
    """Regression guard: the new source_dir param must default to the
    original PENDING_DIR behavior for every pre-existing caller."""
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(hours=1))
    isolated_store.mark_posted(task.task_id, "posted ok")
    assert isolated_store.get(task.task_id) is None
    assert len(list(isolated_store.POSTED_DIR.glob("*.json"))) == 1


def test_list_pending_sorts_by_current_scheduled_at_not_stale_task_id(isolated_store):
    """Regression test for a real production report, 2026-09-16: a missed
    (overdue) post originally due 2026-09-15 was rescheduled forward to
    2026-09-17 via "Đặt lịch" (restore_to_pending), but /admin/schedule
    still showed it FIRST — ahead of ordinary 2026-09-16 posts. task_id's
    timestamp prefix is set once at creation (new_task_id()) and never
    regenerated on reschedule, so sorting by filename/task_id kept using
    the stale 2026-09-15 prefix instead of the real, now-later
    scheduled_at. list_pending() must sort by each task's CURRENT
    scheduled_at instead."""
    now = datetime.now(timezone.utc)
    sep_16 = _make_task(isolated_store, now.replace(2026, 9, 16, 8, 0, 0), content="16th")
    overdue = _make_task(isolated_store, now.replace(2026, 9, 15, 8, 0, 0), content="was overdue")
    isolated_store.mark_missed(overdue.task_id, "server was down")
    rescheduled_to_17th = now.replace(2026, 9, 17, 8, 0, 0).isoformat()
    isolated_store.restore_to_pending(overdue.task_id, scheduled_at=rescheduled_to_17th)

    pending = isolated_store.list_pending()
    assert [t.content for t in pending] == ["16th", "was overdue"]


def test_list_pending_sorts_by_current_scheduled_at_after_plain_edit(isolated_store):
    """Same bug, reached via the other code path: editing a PENDING
    task's time forward through update() (the /admin/schedule inline
    "Sửa" form) must also re-sort it, not leave it pinned at its
    original position by task_id."""
    now = datetime.now(timezone.utc)
    earlier = _make_task(isolated_store, now + timedelta(hours=1), content="earlier")
    later = _make_task(isolated_store, now + timedelta(hours=2), content="later")
    isolated_store.update(earlier.task_id, scheduled_at=(now + timedelta(hours=5)).isoformat())

    pending = isolated_store.list_pending()
    assert [t.content for t in pending] == ["later", "earlier"]


def test_list_pending_sort_handles_naive_scheduled_at(isolated_store):
    """scheduled_at can legitimately be naive (no tzinfo) — form values
    from /admin/schedule/update and the missed-reschedule form are passed
    through with no normalization (same real data shape covered by
    test_data_sync.py's test_last_scheduled_post_time_does_not_crash_on_a_
    naive_scheduled_at). The sort must treat it as UTC, not crash by
    comparing it against an aware sibling task's time."""
    now = datetime.now(timezone.utc)
    aware_task = _make_task(isolated_store, now + timedelta(hours=1), content="aware")
    naive_when = (now + timedelta(minutes=30)).replace(tzinfo=None)
    naive_task = isolated_store.ScheduledTask(
        task_id=isolated_store.new_task_id(naive_when.isoformat()),
        action="post_to_group", account_id="acc-a",
        scheduled_at=naive_when.isoformat(),
        content="naive", target_url="https://facebook.com/groups/1",
    )
    isolated_store.add(naive_task)

    pending = isolated_store.list_pending()
    assert [t.content for t in pending] == ["naive", "aware"]


def test_list_missed_sorts_by_current_scheduled_at(isolated_store):
    now = datetime.now(timezone.utc)
    t1 = _make_task(isolated_store, now - timedelta(hours=1), content="a")
    t2 = _make_task(isolated_store, now - timedelta(hours=3), content="b")
    isolated_store.mark_missed(t1.task_id, "r1")
    isolated_store.mark_missed(t2.task_id, "r2")
    missed = isolated_store.list_missed()
    assert [t.content for t in missed] == ["b", "a"]


def test_due_tasks_unaffected_by_missed(isolated_store):
    """A task moved to missed/ must never show up as "due" again — the
    recurring fire_due_tasks() loop only ever reads list_pending()."""
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(hours=1))
    isolated_store.mark_missed(task.task_id, "test")
    assert isolated_store.due_tasks(now) == []


# --- missed_overdue_days() / cancel_stale_missed() (2026-09-24, owner
# request: /admin/schedule's "⚠️ Task quá hạn" tab had no age filter and
# no auto-cleanup at all — a task nobody reviewed just sat in MISSED_DIR
# forever) ------------------------------------------------------------

def test_missed_overdue_days_measures_from_original_scheduled_at():
    now = datetime(2026, 9, 24, 12, 0, tzinfo=timezone.utc)
    task = schedule_store.ScheduledTask(
        task_id="x", action="post_to_group", account_id="acc-a",
        scheduled_at=(now - timedelta(days=5, hours=1)).isoformat(),
    )
    assert schedule_store.missed_overdue_days(task, now) == 5


def test_cancel_stale_missed_only_cancels_past_the_threshold(isolated_store):
    """A missed task 40 days overdue gets auto-cancelled at the 30-day
    default; one only 10 days overdue is left alone for the admin to
    still review."""
    now = datetime.now(timezone.utc)
    stale = _make_task(isolated_store, now - timedelta(days=40), content="stale")
    recent = _make_task(isolated_store, now - timedelta(days=10), content="recent")
    isolated_store.mark_missed(stale.task_id, "server was down")
    isolated_store.mark_missed(recent.task_id, "server was down")

    count = isolated_store.cancel_stale_missed(max_age_days=30, now=now)

    assert count == 1
    assert isolated_store.get_missed(stale.task_id) is None  # moved out
    assert isolated_store.get_missed(recent.task_id) is not None  # untouched
    cancelled = [t.content for t in isolated_store.list_pending()]  # sanity: not silently rescheduled
    assert cancelled == []
    cancelled_files = list(isolated_store.CANCELLED_DIR.glob("*.json"))
    assert len(cancelled_files) == 1


def test_cancel_stale_missed_leaves_a_note_on_the_orphaned_result_file(isolated_store):
    """cancel_missed() (reused internally) deliberately leaves the
    ORIGINAL .result.txt behind in MISSED_DIR as history — this appends
    a short note there so a later look at that history doesn't read as
    "an admin decided this" when nobody did."""
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(days=40))
    isolated_store.mark_missed(task.task_id, "Đã quá giờ đăng dự kiến — cần admin duyệt lại.")

    isolated_store.cancel_stale_missed(max_age_days=30, now=now)

    note_path = (isolated_store.MISSED_DIR / task.task_id).with_suffix(".result.txt")
    text = note_path.read_text(encoding="utf-8")
    assert "Đã quá giờ đăng dự kiến" in text  # original reason preserved
    assert "Tự động huỷ" in text  # new note appended, not overwritten


def test_cancel_stale_missed_returns_zero_when_nothing_is_stale(isolated_store):
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(days=2))
    isolated_store.mark_missed(task.task_id, "test")
    assert isolated_store.cancel_stale_missed(max_age_days=30, now=now) == 0
    assert isolated_store.get_missed(task.task_id) is not None
