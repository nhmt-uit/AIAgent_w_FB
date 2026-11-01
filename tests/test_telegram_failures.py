"""Tests for Telegram failure tickets (2026-11-01): classification, the ticket
store, the card, the one-tap "Lên lịch lại" + undo, skip/posted, reply-to-edit,
/error, and how a failed attempt turns into a card."""
from __future__ import annotations

import os
import time
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import human_bot.admin as admin_module
from human_bot import db, failure_info, failure_tickets, schedule_store, telegram_failures
from human_bot.config import AccountStatus, RateLimits
from human_bot.failure_info import NO_RETRY, SAFE, UNCERTAIN, classify
from human_bot.runtime_config import set_account_disabled, set_account_paused

REAL_MESSAGES = {
    "error:Page.goto: net::ERR_INTERNET_DISCONNECTED at https://www.facebook.com/\nCall log:": ("network", SAFE),
    "error:Page.goto: net::ERR_NETWORK_CHANGED at https://www.facebook.com/": ("network", SAFE),
    'error:Page.goto: Timeout 30000ms exceeded.\nCall log:\n  - navigating to "https://www.facebook.com/"': ("slow_load", SAFE),
    "error:Page.goto: Target page, context or browser has been closed": ("browser_closed", SAFE),
    "error:Page.wait_for_timeout: Target page, context or browser has been closed": ("browser_closed_mid", UNCERTAIN),
    'error:Locator.wait_for: Timeout 30000ms exceeded.\nCall log:\n  - waiting for get_by_role("dialog")': ("ui_timeout", SAFE),
    "error:Locator.wait_for: Error: strict mode violation: get_by_role(...) resolved to 2 elements": ("ui_changed", SAFE),
    "post_button_still_visible_after_click": ("not_confirmed", UNCERTAIN),
    "comment_button_still_visible_after_click": ("not_confirmed", UNCERTAIN),
    "comment_box_still_has_content_after_click": ("not_confirmed", UNCERTAIN),
    "target_content_unavailable": ("target_gone", NO_RETRY),
    "anomaly_detected:checkpoint": ("anomaly", NO_RETRY),
    "wrong_identity:session_is_the_personal_profile": ("wrong_identity", NO_RETRY),
    "identity_unverified:x": ("identity_unverified", NO_RETRY),
    "identity_check_error:TimeoutError": ("identity_check", SAFE),
    "account_paused:tu_iizuki": ("account_paused", SAFE),            # refused before the browser — the retry button fixes the blocker
    "account_disabled:tu_iizuki": ("account_disabled", SAFE),
    "page_owner_off:tu_iizuki": ("page_owner_off", SAFE),
    "page_owner_missing:tu_iizuki": ("page_owner_missing", NO_RETRY),
    "error:Locator.wait_for: InvalidSelectorError: Error while parsing selector": ("code_bug", NO_RETRY),
    "error:'float' object cannot be interpreted as an integer": ("unknown_error", UNCERTAIN),   # unknown ⇒ could be after the click
    "error:Locator.element_handle: Timeout 15000ms exceeded.": ("unknown_error", UNCERTAIN),   # not a pre-click wait_for
    "media_attach_failed: khong thay anh": ("media", SAFE),
    "something else entirely": ("other", UNCERTAIN),
}


@pytest.mark.parametrize("message,expected", REAL_MESSAGES.items())
def test_classification(message, expected):
    info = classify(message)
    assert (info.code, info.safety) == expected
    assert info.cause and info.retryable == (expected[1] != NO_RETRY)


def test_the_technical_footnote_is_the_first_line_trimmed():
    assert failure_info.technical_line("error:x\nCall log:\n  - a") == "error:x"
    assert len(failure_info.technical_line("e" * 500)) <= 111 and failure_info.technical_line("") == ""


# --- ticket store -----------------------------------------------------------------------------

def test_store_roundtrip_and_lookups():
    t = failure_tickets.create(kind="failure", task_id="T1", account_id="a")
    assert failure_tickets.get(t["id"])["task_id"] == "T1" and t["status"] == failure_tickets.OPEN
    failure_tickets.add_message(t["id"], "111", 7, photo=True)
    failure_tickets.add_message(t["id"], "222", 8)
    assert failure_tickets.find_by_message("111", 7)["id"] == t["id"]
    assert failure_tickets.find_by_message("111", 99) is None and failure_tickets.find_by_message("999", 7) is None
    assert failure_tickets.find_by_task("T1")["id"] == t["id"]
    updated = failure_tickets.update(t["id"], status=failure_tickets.DISMISSED)
    assert updated["status"] == failure_tickets.DISMISSED and failure_tickets.list_open() == []
    assert failure_tickets.update("nope", status="x") is None


def test_find_by_task_prefers_the_newest_ticket():
    old = failure_tickets.create(task_id="T", account_id="a")
    time.sleep(0.01)
    new = failure_tickets.create(task_id="T", account_id="a")
    assert failure_tickets.find_by_task("T")["id"] == new["id"]


def test_message_copies_are_bounded_per_chat_and_the_store_is_pruned():
    t = failure_tickets.create(account_id="a")
    failure_tickets.add_message(t["id"], "2", 1)                      # another recipient's only copy
    for i in range(30):
        failure_tickets.add_message(t["id"], "1", i)
    msgs = failure_tickets.get(t["id"])["messages"]
    assert [m["message_id"] for m in msgs if m["chat_id"] == "1"] == list(range(22, 30))   # newest 8 of chat 1
    assert [m["message_id"] for m in msgs if m["chat_id"] == "2"] == [1]                   # chat 2 is not squeezed out by chat 1
    old = failure_tickets.create(account_id="a")
    failure_tickets.update(old["id"], status=failure_tickets.DISMISSED)
    tickets = failure_tickets._load()
    tickets[old["id"]]["updated_at"] = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    failure_tickets._save(tickets)
    failure_tickets.create(account_id="a")                 # creating prunes old resolved ones
    assert failure_tickets.get(old["id"]) is None and failure_tickets.get(t["id"]) is not None


def test_task_index_reads_once_and_prefers_the_newest():
    a = failure_tickets.create(task_id="T", account_id="a")
    time.sleep(0.01)
    b = failure_tickets.create(task_id="T", account_id="a")
    c = failure_tickets.create(task_id="U", account_id="a")
    index = failure_tickets.task_index()
    assert index["T"]["id"] == b["id"] and index["U"]["id"] == c["id"]


def test_a_corrupt_store_file_reads_as_empty():
    failure_tickets.STORE_PATH.parent.mkdir(parents=True, exist_ok=True)
    failure_tickets.STORE_PATH.write_text("{not json")
    assert failure_tickets.list_open() == []
    assert failure_tickets.create(account_id="a")["id"]


def test_concurrent_writers_do_not_lose_tickets():
    import threading
    ids = []

    def work():
        for _ in range(15):
            ids.append(failure_tickets.create(account_id="a")["id"])

    threads = [threading.Thread(target=work) for _ in range(4)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(set(ids)) == 60 and all(failure_tickets.get(i) for i in ids)


# --- schedule_store additions ----------------------------------------------------------------------

@dataclass
class _Acc:
    account_id: str
    display_name: str
    rate_limits: RateLimits
    action_log_path: Path
    status: AccountStatus = AccountStatus.ACTIVE
    page_name: str = ""
    sponsored_only: bool = False


@pytest.fixture
def env(tmp_path, monkeypatch, isolated_schedule_dirs, isolated_runtime_config, isolated_db):
    acc = _Acc("acc-a", "Acc A", RateLimits(posts_per_day=30, comments_per_day=30), tmp_path / "action_log.jsonl")
    acc.action_log_path.write_text("")
    registry = {"acc-a": acc}
    monkeypatch.setattr(telegram_failures, "get_all_accounts", lambda: registry)
    monkeypatch.setattr(admin_module, "get_all_accounts", lambda: registry)
    monkeypatch.setattr(telegram_failures, "_group_label", lambda aid, url: "Nhóm Thử" if url else "(tường cá nhân)")
    return registry


@pytest.fixture
def later_slot(monkeypatch):
    """The engine's earliest slot is usually "right now", which is inside the undo cutoff;
    undo tests need a slot comfortably in the future."""
    slot = datetime.now(timezone.utc) + timedelta(minutes=30)
    monkeypatch.setattr(admin_module, "_suggest_reschedule_at", lambda account, action, exclude_task_id=None: slot)
    return slot


def _failed_task(message="error:Page.goto: Timeout 30000ms exceeded.", action="post_to_group", age_hours=1, **kw):
    when = datetime.now(timezone.utc) - timedelta(hours=age_hours + 1)
    task = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(when.isoformat()), action=action, account_id="acc-a",
        scheduled_at=when.isoformat(), content="Nội dung bài", target_url="https://facebook.com/groups/1",
        source_kind="job", source_id="j1", job_data={"title": "Thợ hàn", "attributes": {}}, **kw,
    )
    schedule_store.add(task)
    schedule_store.mark_failed(task.task_id, message)
    stamp = (datetime.now(timezone.utc) - timedelta(hours=age_hours)).timestamp()
    os.utime(schedule_store.FAILED_DIR / f"{task.task_id}.result.txt", (stamp, stamp))
    return task


def _ticket_for(task, message=None, **extra):
    fields = telegram_failures.ticket_fields_for_failure(
        account_id=task.account_id, action=task.action, target_url=task.target_url, content=task.content,
        message=message or schedule_store.get_failed_reason(task.task_id) or "", task_id=task.task_id, log_id=extra.pop("log_id", None),
        screenshot=None, retries=task.retries, source_kind=task.source_kind, job_data=task.job_data, source_id=task.source_id,
    )
    fields["failed_at"] = (schedule_store.failed_at(task.task_id) or datetime.now(timezone.utc)).isoformat()
    fields.update(extra)
    return failure_tickets.create(**fields)


def test_failed_task_helpers(env):
    task = _failed_task("boom", age_hours=3)
    assert schedule_store.get_failed(task.task_id).content == "Nội dung bài"
    assert schedule_store.get_failed_reason(task.task_id) == "boom"
    assert abs((datetime.now(timezone.utc) - schedule_store.failed_at(task.task_id)).total_seconds() - 3 * 3600) < 60
    recent = _failed_task("recent", age_hours=1)
    assert [t.task_id for t in schedule_store.list_failed()] == [recent.task_id, task.task_id]       # newest first
    assert [t.task_id for t in schedule_store.list_failed(since=datetime.now(timezone.utc) - timedelta(hours=2))] == [recent.task_id]


def test_restore_failed_to_pending_moves_it_back_with_the_changes(env):
    task = _failed_task()
    when = datetime.now(timezone.utc) + timedelta(hours=1)
    restored = schedule_store.restore_failed_to_pending(task.task_id, scheduled_at=when.isoformat(), retries=1)
    assert restored.retries == 1 and schedule_store.get(task.task_id).scheduled_at == when.isoformat()
    assert schedule_store.get_failed(task.task_id) is None and schedule_store.get_failed_reason(task.task_id) is None
    assert schedule_store.restore_failed_to_pending(task.task_id) is None            # gone → None, no error


# --- the card -------------------------------------------------------------------------------------------

def test_the_card_says_cause_safety_and_how_to_edit(env):
    t = _ticket_for(_failed_task())
    text = telegram_failures.render(t)
    assert "❌ Đăng bài thất bại — Acc A" in text and "Nhóm: Nhóm Thử" in text and 'Tin: "Thợ hàn"' in text
    assert "Facebook tải quá chậm" in text and "Chưa đăng gì" in text and "Trả lời tin này" in text
    assert "Nội dung: Nội dung bài" in text and "(error:Page.goto" in text and "lần thử" not in text


def test_the_card_always_fits_a_photo_caption(env):
    t = _ticket_for(_failed_task())
    failure_tickets.update(t["id"], content="x" * 5000, message="e" * 5000, subject="S" * 300, group_label="G" * 300)
    assert len(telegram_failures.render(failure_tickets.get(t["id"]))) <= 1024
    done = failure_tickets.update(t["id"], status=failure_tickets.RESCHEDULED, resolved_by="Tu", resched={"at": datetime.now(timezone.utc).isoformat()})
    assert len(telegram_failures.render(done)) <= 1024 and "Đã lên lịch lại" in telegram_failures.render(done)


def test_keyboard_depends_on_how_safe_a_retry_is(env):
    safe = _ticket_for(_failed_task())
    kb = telegram_failures.keyboard_for(safe)
    assert [b["callback_data"] for row in kb for b in row] == [f"fx|rs|{safe['id']}", f"fx|sk|{safe['id']}"]
    unsure = _ticket_for(_failed_task("post_button_still_visible_after_click"))
    data = [b["callback_data"] for row in telegram_failures.keyboard_for(unsure) for b in row]
    assert data == [f"fx|ok|{unsure['id']}", f"fx|fr|{unsure['id']}"] and "⚠️" in telegram_failures.render(unsure)
    no = _ticket_for(_failed_task("target_content_unavailable"))
    assert [b["callback_data"] for row in telegram_failures.keyboard_for(no) for b in row] == [f"fx|sk|{no['id']}"]
    assert "Trả lời tin này" not in telegram_failures.render(no)             # nothing to retry, nothing to edit


def test_every_callback_fits_64_bytes(env):
    t = _ticket_for(_failed_task())
    for tk in (t, failure_tickets.update(t["id"], status=failure_tickets.RESCHEDULED, resched={"task_id": "x"})):
        for row in telegram_failures.keyboard_for(tk) + telegram_failures._confirm_keyboard(tk["id"]):
            for b in row:
                assert len(b["callback_data"].encode()) <= 64


# --- one-tap reschedule + undo -----------------------------------------------------------------------------

def _press(verb, ticket, actor="Tu"):
    return telegram_failures.handle_callback(f"{verb}|{ticket['id']}", actor)


def test_one_tap_requeues_the_failed_task_at_a_real_slot(env):
    task = _failed_task()
    t = _ticket_for(task)
    result = _press("rs", t)
    assert result.toast == "Đã lên lịch lại" and result.ticket_id == t["id"]
    assert "Đã lên lịch lại lúc" in result.text and "bởi Tu" in result.text
    assert [b["callback_data"] for row in result.keyboard for b in row] == [f"fx|ud|{t['id']}"]
    pending = schedule_store.get(task.task_id)
    assert pending is not None and pending.retries == 1 and pending.content == "Nội dung bài"
    assert datetime.fromisoformat(pending.scheduled_at) >= datetime.now(timezone.utc) - timedelta(seconds=5)
    assert schedule_store.get_failed(task.task_id) is None
    assert failure_tickets.get(t["id"])["status"] == failure_tickets.RESCHEDULED


def test_undo_puts_everything_back_exactly(env, later_slot):
    task = _failed_task("error:Page.goto: Timeout 30000ms exceeded.")
    t = _ticket_for(task)
    _press("rs", t)
    result = _press("ud", failure_tickets.get(t["id"]), "An")
    assert "Đã hoàn tác" in result.toast and "Đã lên lịch lại" not in result.text
    assert [b["callback_data"] for row in result.keyboard for b in row] == [f"fx|rs|{t['id']}", f"fx|sk|{t['id']}"]
    assert schedule_store.get(task.task_id) is None
    back = schedule_store.get_failed(task.task_id)
    assert back.retries == 0 and schedule_store.get_failed_reason(task.task_id) == "error:Page.goto: Timeout 30000ms exceeded."
    assert failure_tickets.get(t["id"])["status"] == failure_tickets.OPEN
    assert _press("rs", failure_tickets.get(t["id"])).toast == "Đã lên lịch lại"          # and it can be re-queued again


def test_undo_restores_the_original_slot_and_failure_time(env, later_slot):
    task = _failed_task(age_hours=5)
    original_failed_at = schedule_store.failed_at(task.task_id)
    t = _ticket_for(task)
    _press("rs", t)
    assert schedule_store.get(task.task_id).scheduled_at != task.scheduled_at
    _press("ud", failure_tickets.get(t["id"]))
    back = schedule_store.get_failed(task.task_id)
    assert back.scheduled_at == task.scheduled_at and back.retry_of_log_id == task.retry_of_log_id
    assert abs((schedule_store.failed_at(task.task_id) - original_failed_at).total_seconds()) < 2   # the 48h window does not restart


def test_undo_after_the_task_already_ran_is_refused(env):
    task = _failed_task()
    t = _ticket_for(task)
    _press("rs", t)
    schedule_store.mark_posted(task.task_id, "ok")                                   # it fired in the meantime
    result = _press("ud", failure_tickets.get(t["id"]))
    assert "đã chạy rồi" in result.toast and result.keyboard == []
    assert failure_tickets.get(t["id"])["status"] == failure_tickets.RESCHEDULED


def test_a_second_tap_or_another_recipient_sees_the_truth_not_a_second_action(env):
    task = _failed_task()
    t = _ticket_for(task)
    _press("rs", t, "Tu")
    again = _press("rs", t, "An")                                                    # `t` is the stale snapshot
    assert again.toast == "Đã được xử lý rồi" and "bởi Tu" in again.text
    assert len(schedule_store.list_pending()) == 1 and schedule_store.get(task.task_id).retries == 1


def test_dismiss_and_confirmed_posted(env):
    t = _ticket_for(_failed_task())
    r = _press("sk", t)
    assert "Đã bỏ qua — bởi Tu" in r.text and r.keyboard == []
    task2 = _failed_task("post_button_still_visible_after_click")
    t2 = _ticket_for(task2)
    r2 = _press("ok", t2)
    assert "Đã ghi nhận bài đã lên" in r2.text
    posted = [p.task_id for p in schedule_store.list_posted()]
    assert task2.task_id in posted and schedule_store.get_failed(task2.task_id) is None   # bookkeeping matches reality


def test_an_unknown_ticket_or_verb(env):
    assert "không còn" in telegram_failures.handle_callback("rs|deadbeef", "Tu").toast
    t = _ticket_for(_failed_task())
    assert telegram_failures.handle_callback(f"zz|{t['id']}", "Tu").toast == "Nút không hợp lệ"


# --- uncertain outcomes -----------------------------------------------------------------------------------------

def test_an_uncertain_failure_needs_a_confirm_before_requeueing(env):
    task = _failed_task("post_button_still_visible_after_click")
    t = _ticket_for(task)
    first = _press("fr", t)
    assert first.alert and "ĐÃ lên" in first.toast and first.text is None
    assert [b["callback_data"] for row in first.keyboard for b in row] == [f"fx|fc|{t['id']}", f"fx|bk|{t['id']}"]
    assert schedule_store.get(task.task_id) is None                                  # nothing happened yet
    forged = _press("rs", t)                                                         # even a stale/forged one-tap asks first
    assert forged.text is None and "fx|fc|" in forged.keyboard[0][0]["callback_data"]
    back = _press("bk", t)
    assert [b["callback_data"] for row in back.keyboard for b in row][0] == f"fx|ok|{t['id']}"
    done = _press("fc", t)
    assert done.toast == "Đã lên lịch lại" and schedule_store.get(task.task_id) is not None


# --- refusals ------------------------------------------------------------------------------------------------------

def test_a_cause_a_retry_cannot_fix_is_refused(env):
    t = _ticket_for(_failed_task("target_content_unavailable"))
    r = _press("rs", t)
    assert r.alert and "Không thử lại được" in r.toast and failure_tickets.get(t["id"])["status"] == failure_tickets.OPEN


def test_retries_are_capped(env):
    t = _ticket_for(_failed_task(retries=telegram_failures.MAX_RETRIES))
    r = _press("rs", t)
    assert r.alert and "vẫn lỗi" in r.toast and schedule_store.list_pending() == []


def test_only_an_active_account_is_requeued(env):
    task = _failed_task()
    t = _ticket_for(task)
    env["acc-a"].status = AccountStatus.PAUSED
    assert "TẠM DỪNG" in _press("rs", t).toast
    env["acc-a"].status = AccountStatus.DISABLED
    off = _press("rs", t)
    assert "TẮT" in off.toast and any("fx|en|" in b["callback_data"] for row in off.keyboard for b in row)
    env["acc-a"].status = AccountStatus.ACTIVE
    assert schedule_store.list_pending() == []


def test_the_refusal_for_an_off_account_carries_its_own_enable_button_and_it_works(env):
    t = _ticket_for(_failed_task("account_disabled:acc-a"))
    env["acc-a"].status = AccountStatus.DISABLED
    set_account_disabled("acc-a", True)
    refused = _press("rs", t)
    assert refused.alert and "đang TẮT" in refused.toast
    assert any("fx|en|" in b["callback_data"] for row in refused.keyboard for b in row)
    res = _press("en", t)                                                            # the account row is a fake; the flag write is real
    assert "Đã bật lại acc-a" in res.toast
    from human_bot.runtime_config import get_disabled_account_ids
    assert "acc-a" not in get_disabled_account_ids()
    env["acc-a"].status = AccountStatus.ACTIVE
    assert _press("en", t).toast == "Không có tài khoản nào đang tắt để bật"       # a second press changes nothing
    assert _press("rs", t).toast == "Đã lên lịch lại"                               # and the failure is now one tap from re-queued


def test_a_paused_account_offers_a_confirmed_resume_with_the_cooldown_warning(env):
    from human_bot.runtime_config import get_resume_cooldown_info
    t = _ticket_for(_failed_task("account_paused:acc-a"))
    env["acc-a"].status = AccountStatus.PAUSED
    set_account_paused("acc-a", True, reason="checkpoint")
    refused = _press("rs", t)
    assert "TẠM DỪNG" in refused.toast and "hạ nhiệt" in refused.toast
    assert any("fx|rv|" in b["callback_data"] for row in refused.keyboard for b in row)
    ask = _press("rv", t)
    assert ask.alert and "hạ nhiệt" in ask.toast or "giới hạn thấp" in ask.toast
    assert [b["callback_data"] for row in ask.keyboard for b in row] == [f"fx|rc|{t['id']}", f"fx|bk|{t['id']}"]
    assert get_resume_cooldown_info("acc-a") is None                                  # asking changed nothing
    done = _press("rc", t)
    assert "đang hạ nhiệt" in done.toast and get_resume_cooldown_info("acc-a") is not None


def test_a_page_that_needs_its_owners_session_is_blocked_by_the_owner_not_itself(env):
    owner = _Acc("owner", "Owner", RateLimits(), env["acc-a"].action_log_path, status=AccountStatus.DISABLED)
    page = _Acc("acc-a", "Page", RateLimits(posts_per_day=30), env["acc-a"].action_log_path, page_name="P")
    page.owner_account_id, page.page_session_mode = "owner", "owner_session"
    env.update({"owner": owner, "acc-a": page})
    t = _ticket_for(_failed_task("page_owner_off:owner"))
    refused = _press("rs", t)
    assert "Tài khoản cá nhân sở hữu Page owner đang TẮT" in refused.toast
    set_account_disabled("owner", True)
    _press("en", t)                                                                    # enables the OWNER, not the Page
    from human_bot.runtime_config import get_disabled_account_ids
    assert "owner" not in get_disabled_account_ids()
    page.page_session_mode = "own_session"                                            # a Page with its own session is not blocked by an off owner
    assert telegram_failures._blocking_account(t) is None


def test_the_duplicate_guard_also_matches_the_same_job_when_ai_reworded_the_post(env):
    task = _failed_task()
    t = _ticket_for(task)
    db.log_action(
        account_id="acc-a", action="post_to_group", success=True, target_url=task.target_url,
        content="Một bản AI viết lại hoàn toàn khác", source_kind="job", source_id="j1",
    )
    r = _press("rs", t)
    assert r.alert and "đã được đăng thành công" in r.toast
    other_job = _ticket_for(_failed_task())
    failure_tickets.update(other_job["id"], source_id="another-job")
    assert _press("rs", failure_tickets.get(other_job["id"])).toast == "Đã lên lịch lại"


def test_a_text_already_posted_elsewhere_is_not_posted_twice(env):
    task = _failed_task()
    t = _ticket_for(task)
    db.log_action(account_id="acc-a", action="post_to_group", success=True, target_url=task.target_url, content=task.content)
    r = _press("rs", t)
    assert r.alert and "đã được đăng thành công" in r.toast and schedule_store.get(task.task_id) is None


def test_an_old_failure_needs_a_confirm_and_comments_go_stale_sooner(env):
    old_post = _ticket_for(_failed_task(age_hours=60))
    first = _press("rs", old_post)
    assert first.alert and "60 giờ" in first.toast and first.text is None
    assert _press("fc", old_post).toast == "Đã lên lịch lại"
    comment = _ticket_for(_failed_task(action="comment_on_group_post", age_hours=30))        # < 48h but > 24h
    assert _press("rs", comment).text is None
    young_comment = _ticket_for(_failed_task(action="comment_on_group_post", age_hours=5))
    assert _press("rs", young_comment).toast == "Đã lên lịch lại"


# --- no failed task file: rebuild from the log row --------------------------------------------------------------

def test_a_manual_failure_is_rebuilt_from_its_log_row_and_undo_cancels_it(env, later_slot):
    log_id = db.log_action(
        account_id="acc-a", action="post_to_group", success=False, message="error:Page.goto: Timeout 30000ms exceeded.",
        target_url="https://facebook.com/groups/9", content="Bài thủ công", source="manual", source_kind="job", source_id="77",
        job_data={"title": "Thợ điện", "attributes": {}},
    )
    fields = telegram_failures.ticket_fields_for_failure(
        account_id="acc-a", action="post_to_group", target_url="https://facebook.com/groups/9", content="Bài thủ công",
        message="error:Page.goto: Timeout 30000ms exceeded.", task_id=None, log_id=log_id, screenshot=None, retries=0,
        source_kind="job", job_data={"title": "Thợ điện", "attributes": {}},
    )
    t = failure_tickets.create(**fields)
    r = _press("rs", t)
    assert r.toast == "Đã lên lịch lại"
    [task] = schedule_store.list_pending()
    assert task.content == "Bài thủ công" and task.retry_of_log_id == log_id and task.retries == 1
    assert task.source_id == "77" and task.job_data == {"title": "Thợ điện", "attributes": {}} and task.ai_redraft is True
    _press("ud", failure_tickets.get(t["id"]))
    assert schedule_store.list_pending() == [] and failure_tickets.get(t["id"])["status"] == failure_tickets.OPEN
    assert [c.task_id for c in schedule_store.list_failed()] == []                    # nothing resurrected in failed/


# --- reply to edit ---------------------------------------------------------------------------------------------------

def test_a_reply_requeues_with_the_new_text_and_keeps_ai_from_rewriting_it(env):
    task = _failed_task()
    t = _ticket_for(task)
    out = telegram_failures.apply_reply(t, "  Nội dung MỚI  ", "Tu")
    assert "nội dung mới" in out.message and out.ticket_id == t["id"]
    pending = schedule_store.get(task.task_id)
    assert pending.content == "Nội dung MỚI" and pending.ai_redraft is False and pending.retries == 1
    assert "với nội dung mới" in telegram_failures.render(failure_tickets.get(t["id"]))


def test_replying_again_changes_the_queued_text_and_undo_restores_the_original(env, later_slot):
    task = _failed_task()
    t = _ticket_for(task)
    telegram_failures.apply_reply(t, "Bản 1", "Tu")
    out = telegram_failures.apply_reply(failure_tickets.get(t["id"]), "Bản 2", "Tu")
    assert "Đã đổi nội dung bài đang chờ" in out.message and schedule_store.get(task.task_id).content == "Bản 2"
    _press("ud", failure_tickets.get(t["id"]))
    back = schedule_store.get_failed(task.task_id)
    assert back.content == "Nội dung bài" and back.ai_redraft is True and back.retries == 0   # the ORIGINAL, not "Bản 1"


def test_a_reply_shows_what_it_scheduled_and_offers_undo(env):
    t = _ticket_for(_failed_task())
    out = telegram_failures.apply_reply(t, "Bài đã sửa xong", "Tu")
    assert "“Bài đã sửa xong”" in out.message
    assert [b["callback_data"] for row in out.keyboard for b in row] == [f"fx|ud|{t['id']}"]
    again = telegram_failures.apply_reply(failure_tickets.get(t["id"]), "Lại sửa", "Tu")
    assert "“Lại sửa”" in again.message and again.keyboard


def test_a_rebuilt_manual_job_keeps_its_exact_words(env):
    log_id = db.log_action(
        account_id="acc-a", action="post_to_group", success=False, message="error:Page.goto: Timeout 30000ms exceeded.",
        target_url="https://facebook.com/groups/9", content="Chữ của admin", source="manual", source_kind="job", source_id="manual-ab12",
        job_data={"title": "t", "attributes": {}},
    )
    t = failure_tickets.create(**telegram_failures.ticket_fields_for_failure(
        account_id="acc-a", action="post_to_group", target_url="https://facebook.com/groups/9", content="Chữ của admin",
        message="error:Page.goto: Timeout 30000ms exceeded.", task_id=None, log_id=log_id, screenshot=None, retries=0,
        source_kind="job", job_data={"title": "t", "attributes": {}}, source_id="manual-ab12",
    ))
    _press("rs", t)
    assert schedule_store.list_pending()[0].ai_redraft is False        # fire-time AI must not rewrite what the admin typed


def test_a_reply_after_the_task_ran_or_to_a_handled_ticket(env):
    task = _failed_task()
    t = _ticket_for(task)
    telegram_failures.apply_reply(t, "x", "Tu")
    schedule_store.mark_posted(task.task_id, "ok")
    assert "đã chạy rồi" in telegram_failures.apply_reply(failure_tickets.get(t["id"]), "y", "Tu").message
    dismissed = _ticket_for(_failed_task())
    failure_tickets.update(dismissed["id"], status=failure_tickets.DISMISSED)
    assert "đã được xử lý" in telegram_failures.apply_reply(failure_tickets.get(dismissed["id"]), "y", "Tu").message


def test_reply_validation_and_refusals(env):
    t = _ticket_for(_failed_task())
    assert "trống" in telegram_failures.apply_reply(t, "   ", "Tu").message
    assert "tối đa" in telegram_failures.apply_reply(t, "x" * 5000, "Tu").message
    assert schedule_store.list_pending() == []
    no = _ticket_for(_failed_task("target_content_unavailable"))
    assert "Không thử lại được" in telegram_failures.apply_reply(no, "mới", "Tu").message
    env["acc-a"].status = AccountStatus.PAUSED
    assert "TẠM DỪNG" in telegram_failures.apply_reply(t, "mới", "Tu").message


def test_a_reply_to_an_uncertain_failure_warns_about_a_possible_duplicate(env):
    t = _ticket_for(_failed_task("post_button_still_visible_after_click"))
    assert "có thể đã lên" in telegram_failures.apply_reply(t, "Bản mới", "Tu").message


# --- /error ---------------------------------------------------------------------------------------------------------------

def test_open_failures_lists_recent_unresolved_ones_and_makes_tickets_on_the_fly(env):
    fresh = _failed_task("error:Page.goto: Timeout 30000ms exceeded.", age_hours=2)
    _failed_task("boom", age_hours=100)                                                  # outside the 48h window
    items, overflow = telegram_failures.build_list()
    assert overflow == 0 and len(items) == 1
    ticket, text, keyboard, photo = items[0]
    assert ticket["task_id"] == fresh.task_id and "Facebook tải quá chậm" in text and keyboard
    assert failure_tickets.find_by_task(fresh.task_id) is not None                      # made on the fly
    assert telegram_failures.open_failure_count() == 1


def test_resolved_tickets_and_overflow(env):
    for i in range(7):
        _failed_task(age_hours=1 + i / 10)
    items, overflow = telegram_failures.build_list()
    assert len(items) == telegram_failures.MAX_LIST_ITEMS and overflow == 2
    for ticket, *_ in items:
        failure_tickets.update(ticket["id"], status=failure_tickets.DISMISSED)
    assert telegram_failures.open_failure_count() == 2


def test_a_task_that_failed_again_after_a_requeue_gets_a_fresh_card(env):
    task = _failed_task()
    t = _ticket_for(task)
    _press("rs", t)
    time.sleep(0.05)
    schedule_store.mark_failed(task.task_id, "error:Locator.wait_for: Timeout 30000ms exceeded.")     # it ran and failed again
    os.utime(schedule_store.FAILED_DIR / f"{task.task_id}.result.txt", (time.time() + 30, time.time() + 30))
    items, _ = telegram_failures.build_list()
    assert len(items) == 1 and items[0][0]["id"] != t["id"] and "Không thấy ô/nút" in items[0][1]


def test_an_open_ticket_whose_failed_file_vanished_is_dropped_but_not_while_in_flight(env):
    task = _failed_task()
    t = _ticket_for(task)
    schedule_store.restore_failed_to_pending(task.task_id, scheduled_at=datetime.now(timezone.utc).isoformat())   # re-queued in the admin
    # the card goes out inside run_task() BEFORE the scheduler moves the task to failed/ — a brand-new ticket
    # must not be treated as stale just because its file is not there yet
    assert telegram_failures.build_list()[0] == [] and failure_tickets.get(t["id"])["status"] == failure_tickets.OPEN
    tickets = failure_tickets._load()
    tickets[t["id"]]["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat()
    failure_tickets._save(tickets)
    assert telegram_failures.build_list()[0] == []
    assert failure_tickets.get(t["id"])["status"] == failure_tickets.DISMISSED


def test_an_empty_list_says_so(env):
    assert "Không có lỗi" in telegram_failures.empty_list_item().text
    from human_bot import telegram_commands
    footer = telegram_commands._queue_footer(datetime.now(timezone.utc))
    assert "Không có bài lỡ giờ, lỗi hay tin nào đang chờ xử lý" in footer and "/error" not in footer     # nothing to point at


# --- db ------------------------------------------------------------------------------------------------------------------

def test_log_action_returns_the_row_id_and_success_lookup_is_exact(isolated_db):
    first = db.log_action(account_id="a", action="post_to_group", success=True, target_url="u", content="c")
    second = db.log_action(account_id="a", action="post_to_group", success=False, target_url="u", content="c")
    assert isinstance(first, int) and second == first + 1
    before = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert db.success_logged_after("a", "u", "c", before)["id"] == first
    assert db.success_logged_after("a", "u", "other", before) is None and db.success_logged_after("b", "u", "c", before) is None
    assert db.success_logged_after("a", "u", "c", (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()) is None


# --- review round 2 (2026-11-01) --------------------------------------------------------------------------

def test_undo_is_refused_once_the_requeued_task_is_about_to_run(env):
    """The earliest slot is often "now": pulling it back while the scheduler is starting it
    could race a post in progress, so undo closes shortly before the due time."""
    task = _failed_task()
    t = _ticket_for(task)
    _press("rs", t)                                                                  # the real engine → due ~now
    result = _press("ud", failure_tickets.get(t["id"]))
    assert "sắp chạy/đang chạy" in result.toast and result.keyboard == []
    assert schedule_store.get(task.task_id) is not None and failure_tickets.get(t["id"])["status"] == failure_tickets.RESCHEDULED


def test_two_recipients_tapping_at_once_requeue_only_once(env):
    import threading
    log_id = db.log_action(account_id="acc-a", action="post_to_group", success=False, message="error:Page.goto: Timeout 30000ms exceeded.",
                           target_url="https://facebook.com/groups/9", content="C", source="manual")
    t = failure_tickets.create(**telegram_failures.ticket_fields_for_failure(
        account_id="acc-a", action="post_to_group", target_url="https://facebook.com/groups/9", content="C",
        message="error:Page.goto: Timeout 30000ms exceeded.", task_id=None, log_id=log_id, screenshot=None, retries=0,
        source_kind=None, job_data=None,
    ))
    results = []
    barrier = threading.Barrier(2)

    def tap(actor):
        barrier.wait()
        results.append(telegram_failures.handle_callback(f"rs|{t['id']}", actor))

    threads = [threading.Thread(target=tap, args=(n,)) for n in ("Tu", "An")]
    [x.start() for x in threads]
    [x.join() for x in threads]
    assert len(schedule_store.list_pending()) == 1                                    # NOT queued twice
    assert sorted(r.toast for r in results) == ["Đã lên lịch lại", "Đã được xử lý rồi"]


def test_a_retry_rebuilt_from_the_log_keeps_the_image_and_audience(env):
    log_id = db.log_action(account_id="acc-a", action="post_to_own_profile", success=False, message="error:Page.goto: Timeout 30000ms exceeded.", content="C", source="manual")
    t = failure_tickets.create(**telegram_failures.ticket_fields_for_failure(
        account_id="acc-a", action="post_to_own_profile", target_url=None, content="C",
        message="error:Page.goto: Timeout 30000ms exceeded.", task_id=None, log_id=log_id, screenshot=None, retries=0,
        source_kind=None, job_data=None, media_path="/media/memes/x.png", audience="friends",
    ))
    _press("rs", t)
    [task] = schedule_store.list_pending()
    assert task.media_path == "/media/memes/x.png" and task.audience == "friends"


def test_a_damaged_ticket_store_is_moved_aside_not_overwritten():
    failure_tickets.create(account_id="keep-me")
    failure_tickets.STORE_PATH.write_text("{ definitely not json")
    new = failure_tickets.create(account_id="after")
    assert failure_tickets.get(new["id"]) is not None
    aside = list(failure_tickets.STORE_PATH.parent.glob(f"{failure_tickets.STORE_PATH.name}.corrupt-*"))
    assert len(aside) == 1 and aside[0].read_text() == "{ definitely not json"       # kept for inspection


def test_creating_a_ticket_that_cannot_be_saved_raises_so_the_caller_can_fall_back(monkeypatch):
    monkeypatch.setattr(failure_tickets, "_save", lambda tickets: False)
    with pytest.raises(RuntimeError):
        failure_tickets.create(account_id="a")


def test_a_network_error_after_the_page_opened_is_not_assumed_safe():
    during = classify("error:Locator.click: net::ERR_CONNECTION_RESET")
    assert (during.code, during.safety) == ("network_mid", UNCERTAIN)
    assert classify("error:Page.goto: net::ERR_INTERNET_DISCONNECTED at https://x").safety == SAFE


def test_the_duplicate_check_ignores_unrelated_posts_when_the_content_is_empty(isolated_db):
    db.log_action(account_id="a", action="post_to_group", success=True, target_url="u", content="", source_kind="job", source_id="other")
    before = (datetime.now(timezone.utc) - timedelta(hours=1)).isoformat()
    assert db.success_logged_after("a", "u", "", before) is None                         # empty content never matches by itself
    assert db.success_logged_after("a", "u", None, before) is None
    assert db.success_logged_after("a", "u", "", before, source_id="other", source_kind="job") is not None   # but the same job does
