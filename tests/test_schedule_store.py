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


def test_due_tasks_unaffected_by_missed(isolated_store):
    """A task moved to missed/ must never show up as "due" again — the
    recurring fire_due_tasks() loop only ever reads list_pending()."""
    now = datetime.now(timezone.utc)
    task = _make_task(isolated_store, now - timedelta(hours=1))
    isolated_store.mark_missed(task.task_id, "test")
    assert isolated_store.due_tasks(now) == []
