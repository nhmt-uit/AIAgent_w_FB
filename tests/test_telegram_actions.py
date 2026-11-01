"""Tests for human_bot/telegram_actions.py (2026-10-16, Telegram Vòng 2):
the message builders, the two-step button flow and each action."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import human_bot.admin as admin_module
from human_bot import schedule_store, telegram_actions
from human_bot.config import GroupRef, RateLimits
from human_bot.runtime_config import get_scheduling_config, save_scheduling_overrides


@dataclass
class _FakeAccount:
    account_id: str
    rate_limits: RateLimits
    action_log_path: Path
    display_name: str = "Acc"
    sponsored_only: bool = False


@pytest.fixture
def accounts(tmp_path, monkeypatch, isolated_schedule_dirs, isolated_runtime_config):
    acc = _FakeAccount("acc-a", RateLimits(posts_per_day=30, comments_per_day=30), tmp_path / "action_log.jsonl")
    acc.action_log_path.write_text("")
    registry = {"acc-a": acc}
    monkeypatch.setattr(telegram_actions, "get_all_accounts", lambda: registry)
    monkeypatch.setattr(admin_module, "get_all_accounts", lambda: registry)
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: [GroupRef(name="Group A", url="https://facebook.com/groups/a")])
    return registry


def _missed(content="nội dung", reason="Mất mạng: không kết nối được internet", action="comment_on_group_post"):
    when = datetime.now(timezone.utc) - timedelta(hours=2)
    task = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(when.isoformat()), action=action, account_id="acc-a",
        scheduled_at=when.isoformat(), content=content, target_url="https://www.facebook.com/groups/123/",
    )
    schedule_store.add(task)
    schedule_store.mark_missed(task.task_id, reason)
    return task


def _review(contents=("bài 1",)):
    review = schedule_store.NeedsReviewJob(
        review_id=schedule_store.new_review_id(), account_id="acc-a",
        groups=[{"id": f"g{i}", "name": f"G{i}", "url": f"https://facebook.com/groups/{i}"} for i in range(len(contents))],
        contents=list(contents), confidence=0.5, reasoning="needs review: test", source_id="job-1",
        job_data={"title": "Thợ hàn", "attributes": {}, "sponsored_by": None},
    )
    schedule_store.add_needs_review(review)
    return review


def _datas(keyboard):
    return [b["callback_data"] for row in keyboard for b in row]


# --- building messages ------------------------------------------------------------

def test_quahan_items_have_reschedule_and_cancel_buttons(accounts):
    task = _missed()
    [item] = telegram_actions.build_items("overdue")
    assert "Bài lỡ giờ đăng" in item.text and "Lý do: mất mạng" in item.text and "nội dung" in item.text
    assert "Việc: Bình luận" in item.text and "post_to" not in item.text and "comment_on" not in item.text
    assert "(hôm nay)" in item.text or "(hôm qua)" in item.text       # the task is 2 hours old: which one depends on the JST time of day (exact labels are tested below)
    assert _datas(item.keyboard) == [f"rs|{task.task_id}", f"cm|{task.task_id}"]


def test_the_lateness_label_agrees_with_the_printed_date():
    now = datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc)                                  # 10:00 JST on the 1st
    late_last_night = (now - timedelta(hours=11)).isoformat()                                # 23:00 JST on the 31st — only 11 hours ago
    assert telegram_actions._lateness(late_last_night, now) == "hôm qua"
    assert telegram_actions._lateness((now - timedelta(hours=1)).isoformat(), now) == "hôm nay"
    assert telegram_actions._lateness((now - timedelta(days=3)).isoformat(), now) == "3 ngày trước"
    assert telegram_actions._lateness("garbage", now) == "?"


def test_quahan_items_are_capped(accounts):
    for _ in range(telegram_actions.MAX_ITEMS + 3):
        _missed()
    items = telegram_actions.build_items("overdue")
    assert len(items) == telegram_actions.MAX_ITEMS + 2  # an intro, the cards, then a "còn N bài nữa" note
    assert items[0].keyboard is None and f"Có {telegram_actions.MAX_ITEMS + 3} bài lỡ giờ đăng" in items[0].text and "Lên lịch lại" in items[0].text
    assert items[-1].keyboard is None and "còn 3 bài lỡ giờ nữa" in items[-1].text and "/overdue" in items[-1].text
    assert all(i.keyboard for i in items[1:-1])


def test_quahan_with_nothing_overdue_says_so(accounts):
    [item] = telegram_actions.build_items("overdue")
    assert "Không có bài nào lỡ giờ đăng" in item.text and item.keyboard is None


def test_choduyet_items_and_empty_state(accounts):
    assert "Không có tin tuyển dụng nào đang chờ duyệt" in telegram_actions.build_items("review")[0].text
    review = _review()
    [item] = telegram_actions.build_items("review")
    assert "Thợ hàn" in item.text and "0.50" in item.text and "thang 0–1" in item.text and "Tin tuyển dụng chờ duyệt" in item.text
    assert _datas(item.keyboard) == [f"ap|{review.review_id}", f"rj|{review.review_id}"]


def test_choduyet_tolerates_a_non_numeric_confidence(accounts):
    review = _review()
    review.confidence = "abc"
    schedule_store.add_needs_review(review)
    assert "không rõ" in telegram_actions.build_items("review")[0].text


def test_autofire_items_reflect_the_current_state(accounts):
    save_scheduling_overrides({"auto_fire_enabled": True})
    [pause] = telegram_actions.build_items("pause")
    assert _datas(pause.keyboard) == ["af|off"]
    [already_on] = telegram_actions.build_items("resume")
    assert already_on.keyboard is None and "BẬT sẵn" in already_on.text
    save_scheduling_overrides({"auto_fire_enabled": False})
    [resume] = telegram_actions.build_items("resume")
    assert _datas(resume.keyboard) == ["af|on"]
    [already_off] = telegram_actions.build_items("pause")
    assert already_off.keyboard is None and "TẮT sẵn" in already_off.text


def test_commands_without_buttons_build_nothing(accounts):
    assert telegram_actions.build_items("schedule") == []


# --- two-step flow --------------------------------------------------------------------

def test_first_tap_only_asks_for_confirmation_and_changes_nothing(accounts):
    task = _missed()
    result = telegram_actions.handle_callback(f"rs|{task.task_id}", "orig", "Tu")
    assert result.text is None  # the message text is untouched
    assert _datas(result.keyboard)[0] == f"rs!|{task.task_id}"
    assert _datas(result.keyboard)[1] == f"bk|mt|{task.task_id}"
    assert "Lên lịch lại (khoảng" in result.keyboard[0][0]["text"]
    assert schedule_store.get_missed(task.task_id) is not None  # nothing happened yet


def test_back_restores_the_main_buttons(accounts):
    task = _missed()
    result = telegram_actions.handle_callback(f"bk|mt|{task.task_id}", "orig", "Tu")
    assert _datas(result.keyboard) == [f"rs|{task.task_id}", f"cm|{task.task_id}"]


# --- executing -------------------------------------------------------------------------

def test_reschedule_moves_a_missed_task_back_to_pending_with_a_future_slot(accounts):
    task = _missed()
    result = telegram_actions.handle_callback(f"rs!|{task.task_id}", "orig", "Tu")
    assert result.keyboard == [] and "Đã lên lịch lại" in result.text and "bởi Tu" in result.text
    assert schedule_store.get_missed(task.task_id) is None
    pending = schedule_store.get(task.task_id)
    assert pending is not None
    assert datetime.fromisoformat(pending.scheduled_at) >= datetime.now(timezone.utc) - timedelta(seconds=5)


def test_a_second_tap_on_the_same_task_is_reported_as_already_handled(accounts):
    task = _missed()
    telegram_actions.handle_callback(f"rs!|{task.task_id}", "orig", "Tu")
    again = telegram_actions.handle_callback(f"rs!|{task.task_id}", "orig", "An")
    assert "đã được xử lý ở nơi khác" in again.text and again.keyboard == []
    confirm_again = telegram_actions.handle_callback(f"rs|{task.task_id}", "orig", "An")
    assert "đã được xử lý ở nơi khác" in confirm_again.text


def test_cancel_missed_moves_it_to_cancelled(accounts):
    task = _missed()
    result = telegram_actions.handle_callback(f"cm!|{task.task_id}", "orig", "Tu")
    assert "Đã huỷ" in result.text
    assert schedule_store.get_missed(task.task_id) is None and schedule_store.get(task.task_id) is None


def test_approve_review_creates_tasks_through_the_same_core_as_admin(accounts):
    review = _review(contents=("bài 1", "bài 2"))
    confirm = telegram_actions.handle_callback(f"ap|{review.review_id}", "orig", "Tu")
    assert "tạo 2 bài đăng" in confirm.keyboard[0][0]["text"] and confirm.toast
    result = telegram_actions.handle_callback(f"ap!|{review.review_id}", "orig", "Tu")
    assert "tạo 2 bài chờ đăng" in result.text and result.keyboard == []
    assert schedule_store.get_needs_review(review.review_id) is None
    pending = schedule_store.list_pending()
    assert [t.content for t in pending] == ["bài 1", "bài 2"] and all(t.action == "post_to_group" for t in pending)
    again = telegram_actions.handle_callback(f"ap!|{review.review_id}", "orig", "An")
    assert "đã được xử lý ở nơi khác" in again.text
    assert len(schedule_store.list_pending()) == 2  # no duplicate tasks from the second tap


def test_reject_review(accounts):
    review = _review()
    result = telegram_actions.handle_callback(f"rj!|{review.review_id}", "orig", "Tu")
    assert "Đã bỏ qua" in result.text
    assert schedule_store.get_needs_review(review.review_id) is None and schedule_store.list_pending() == []


def test_pause_and_resume_autofire_persists_and_broadcasts(accounts):
    save_scheduling_overrides({"auto_fire_enabled": True})
    paused = telegram_actions.handle_callback("af!|off", "orig", "Tu")
    assert get_scheduling_config().auto_fire_enabled is False
    assert "TẠM DỪNG" in paused.broadcast and "Tu" in paused.broadcast
    same = telegram_actions.handle_callback("af!|off", "orig", "An")
    assert same.broadcast is None and "Đã ở trạng thái này" in same.text  # nothing re-announced
    resumed = telegram_actions.handle_callback("af!|on", "orig", "An")
    assert get_scheduling_config().auto_fire_enabled is True and "BẬT LẠI" in resumed.broadcast


def test_malformed_or_forged_callback_data_is_rejected_safely(accounts):
    for data in ("", "zz|x", "rs!|", "bk", "rs|../../etc/passwd", "ap!|nonexistent"):
        result = telegram_actions.handle_callback(data, "orig", "Tu")
        assert result.toast or result.text  # answered, never raised


def test_every_button_fits_telegrams_64_byte_limit(accounts):
    task = _missed()
    review = _review()
    for kind, ident in (("mt", task.task_id), ("rv", review.review_id), ("af", "off")):
        for data in _datas(telegram_actions._main_keyboard(kind, ident)):
            assert len(data.encode()) <= 64
    for verb in ("rs", "cm", "ap", "rj"):
        ident = task.task_id if verb in ("rs", "cm") else review.review_id
        for data in _datas(telegram_actions._confirm_keyboard(verb, ident, "x")):
            assert len(data.encode()) <= 64


def test_autofire_with_a_garbled_id_never_changes_anything(accounts):
    """Code review 2026-10-16: any id other than on/off used to count as
    "off" and would pause all auto-posting."""
    save_scheduling_overrides({"auto_fire_enabled": True})
    for data in ("af!|", "af!|xyz", "af|xyz", "af!|ON"):
        result = telegram_actions.handle_callback(data, "orig", "Tu")
        assert result.toast == "Nút không hợp lệ" and result.broadcast is None
    assert get_scheduling_config().auto_fire_enabled is True


def test_approve_failure_midway_rolls_back_and_keeps_the_review(accounts, monkeypatch):
    """The review is claimed (file removed) before its groups are scheduled;
    a failure on group 2 must not leave group 1 scheduled and the review lost."""
    review = _review(contents=("bài 1", "bài 2"))
    real = admin_module._suggest_reschedule_at
    calls = {"n": 0}

    def flaky(account, action, exclude_task_id=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(account, action, exclude_task_id)

    monkeypatch.setattr(admin_module, "_suggest_reschedule_at", flaky)
    with pytest.raises(RuntimeError):
        admin_module.approve_needs_review_core(review.review_id, "", None)
    assert schedule_store.list_pending() == []  # group 1's task was undone
    assert schedule_store.get_needs_review(review.review_id) is not None  # review can be approved again


def test_approve_with_no_groups_puts_the_review_back_instead_of_losing_it(accounts):
    review = _review()
    review.groups = []
    schedule_store.add_needs_review(review)
    result = telegram_actions.handle_callback(f"ap!|{review.review_id}", "orig", "Tu")
    assert result.keyboard and "Không chọn được nhóm" in result.toast  # buttons stay usable
    assert schedule_store.get_needs_review(review.review_id) is not None
    assert schedule_store.list_pending() == []


def test_failed_rollback_does_not_restore_the_review_to_avoid_double_posting(accounts, monkeypatch):
    review = _review(contents=("bài 1", "bài 2"))
    real = admin_module._suggest_reschedule_at
    calls = {"n": 0}

    def flaky(account, action, exclude_task_id=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(account, action, exclude_task_id)

    monkeypatch.setattr(admin_module, "_suggest_reschedule_at", flaky)
    monkeypatch.setattr(schedule_store, "cancel", lambda task_id: False)  # task 1 was already picked up
    with pytest.raises(RuntimeError):
        admin_module.approve_needs_review_core(review.review_id, "", None)
    assert schedule_store.get_needs_review(review.review_id) is None


def test_reject_and_cancel_lose_a_race_gracefully(accounts, monkeypatch):
    review = _review()
    task = _missed()
    real_rename = Path.rename

    def vanishing_rename(self, target):
        raise FileNotFoundError(self)

    monkeypatch.setattr(Path, "rename", vanishing_rename)
    assert schedule_store.reject_needs_review(review.review_id) is False
    assert schedule_store.cancel_missed(task.task_id) is False
    monkeypatch.setattr(Path, "rename", real_rename)
    again = telegram_actions.handle_callback(f"cm!|{task.task_id}", "orig", "Tu")
    assert "Đã huỷ" in again.text


def test_reschedule_for_a_removed_account_keeps_the_buttons(accounts):
    task = _missed()
    accounts.clear()
    result = telegram_actions.handle_callback(f"rs!|{task.task_id}", "orig", "Tu")
    assert _datas(result.keyboard) == [f"rs|{task.task_id}", f"cm|{task.task_id}"]
    assert schedule_store.get_missed(task.task_id) is not None


def test_a_too_long_callback_data_raises_instead_of_being_silently_dropped():
    with pytest.raises(ValueError):
        telegram_actions._btn("x", "a" * 65)
