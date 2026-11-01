"""Group cards for failures (2026-11-01, failure tickets phase 2): a burst of one cause
becomes ONE card, "Lên lịch lại tất cả" with undo, "Bỏ qua tất cả" with a confirm, and
the /error summary card."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from human_bot.config import AccountStatus
from human_bot import db, failure_tickets, schedule_store, telegram_actions, telegram_batches, telegram_failures, telegram_notify
from tests.test_telegram_failures import _failed_task, _ticket_for, env, later_slot  # noqa: F401  (fixtures/helpers)

SLOW = "error:Page.goto: Timeout 30000ms exceeded."                      # slow_load, safe
NET = "error:Page.goto: net::ERR_INTERNET_DISCONNECTED at https://www.facebook.com/"   # network, safe
UNSURE = "post_button_still_visible_after_click"                          # not_confirmed, uncertain
GONE = "target_content_unavailable"                                        # target_gone, no retry


def _fail(message=SLOW, age_hours=0.05, **kw):
    """A failure the way the agent makes it: the task fails, its ticket is created, then attach()."""
    ticket = _ticket_for(_failed_task(message, age_hours=age_hours, **kw))
    return ticket, telegram_batches.attach(ticket)


def _batch(*tickets, scope="list"):
    return failure_tickets.create(kind=failure_tickets.BATCH, scope=scope, category=None, members=[t["id"] for t in tickets], last_resched=None, last_dismiss=None)


def _press(verb, batch, actor="Tu"):
    return telegram_batches.handle_callback(f"{verb}|{batch['id']}", actor)


def _data(keyboard):
    return [b["callback_data"] for row in keyboard for b in row]


# --- joining a burst ------------------------------------------------------------------------------------------------

def test_the_third_failure_of_one_cause_within_minutes_starts_a_burst_and_later_ones_join_it(env):
    (t1, a1), (t2, a2) = _fail(), _fail()
    assert a1 == (None, False) and a2 == (None, False)                            # one and two: ordinary cards
    t3, (burst, is_new) = _fail()
    assert is_new and burst["kind"] == failure_tickets.BATCH and burst["scope"] == "burst" and burst["category"] == "slow_load"
    assert burst["members"] == [t1["id"], t2["id"], t3["id"]]                       # the two earlier ones are folded in, oldest first
    t4, (same, is_new_again) = _fail()
    assert not is_new_again and same["id"] == burst["id"] and failure_tickets.get(burst["id"])["members"][-1] == t4["id"]


def test_failures_of_other_causes_or_from_long_ago_do_not_count(env):
    _fail(); _fail()
    _t, (burst, _new) = _fail(NET)                                                 # another cause
    assert burst is None
    _t, (burst, _new) = _fail(age_hours=1)                                         # same cause but an hour ago → outside the window
    assert burst is None


def test_handled_failures_do_not_count_towards_a_burst(env):
    t1, _ = _fail()
    _fail()
    telegram_failures.dismiss_ticket(t1, "Tu")
    _t3, (burst, _new) = _fail()
    assert burst is None                                                            # only two are still open


def test_a_burst_whose_members_were_all_handled_is_not_joined_by_the_next_failure(env):
    _fail(); _fail()
    t3, (burst, _new) = _fail()
    for m in failure_tickets.get_many(burst["members"]):
        telegram_failures.dismiss_ticket(m, "Tu")
    t4, (joined, is_new) = _fail()
    assert joined is None                                                           # fresh start: one open failure only


def test_group_and_streak_tickets_are_never_counted_as_failures(env):
    t1, _ = _fail(); t2, _ = _fail(); _t3, (burst, _n) = _fail()
    assert burst is not None and failure_tickets.get(burst["id"])["status"] == failure_tickets.OPEN
    assert burst["id"] not in [t["id"] for t in failure_tickets.list_open()]        # list_open() = failures only
    assert burst["id"] in [t["id"] for t in failure_tickets.list_open(kind=failure_tickets.BATCH)]
    assert telegram_failures.open_failure_count() == 3                               # the footer counts the failures, not the card


# --- the card ------------------------------------------------------------------------------------------------------------

def test_the_card_names_the_cause_accounts_times_and_what_is_left(env):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    text = telegram_batches.render(burst)
    assert "⚠️ 3 lỗi cùng nguyên nhân" in text and "Facebook tải quá chậm" in text and "Chưa đăng gì" in text
    assert "Acc A ×3" in text and "Còn chờ: 3 · đã lên lịch lại: 0" in text and "/error" in text and "Lúc:" in text
    assert _data(telegram_batches.keyboard_for(burst)) == [f"fb|ra|{burst['id']}", f"fb|sa|{burst['id']}"]
    kb = telegram_batches.keyboard_for(burst)
    assert "(3)" in kb[0][0]["text"] and "(3)" in kb[0][1]["text"]


def test_only_safe_failures_are_grouped_the_others_each_keep_their_own_card_and_screenshot(env):
    for message in (UNSURE, GONE, "something else entirely"):                          # uncertain / no retry / unrecognised
        results = [_fail(message)[1] for _ in range(4)]
        assert results == [(None, False)] * 4
    assert failure_tickets.list_open(kind=failure_tickets.BATCH) == []


def test_a_group_card_of_mixed_safety_offers_bulk_only_for_the_safe_ones(env):
    safe, _ = _fail(); unsure, _ = _fail(UNSURE); other, _ = _fail()
    batch = _batch(safe, unsure, other)
    assert "chỉ lỗi an toàn mới được thử lại hàng loạt" in telegram_batches.render(batch)
    assert "(2)" in telegram_batches.keyboard_for(batch)[0][0]["text"] and "(3)" in telegram_batches.keyboard_for(batch)[0][1]["text"]
    unsafe_only = _batch(unsure)
    assert _data(telegram_batches.keyboard_for(unsafe_only)) == [f"fb|sa|{unsafe_only['id']}"]
    r = _press("ra", unsafe_only)                                                      # a forged/stale "reschedule all" does nothing
    assert r.alert and r.toast.startswith("Chưa làm được 1 lỗi")
    assert schedule_store.list_pending() == []


def test_every_callback_fits_64_bytes(env):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    for kb in (telegram_batches.keyboard_for(burst),):
        assert all(len(d.encode()) <= 64 for d in _data(kb))
    confirm = _press("sa", burst)
    assert all(len(d.encode()) <= 64 for d in _data(confirm.keyboard))


# --- Lên lịch lại tất cả ---------------------------------------------------------------------------------------------------

def test_reschedule_all_requeues_every_safe_member_one_after_another(env):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    r = _press("ra", burst)
    assert r.toast == "Đã lên lịch lại 3 lỗi" and r.ticket_id == burst["id"] and not r.alert
    pending = schedule_store.list_pending()
    assert len(pending) == 3 and all(t.retries == 1 for t in pending)
    assert len({t.scheduled_at for t in pending}) == 3                                 # each got its own slot — they do not pile onto one
    assert schedule_store.list_failed() == []
    assert set(r.also_sync) == set(burst["members"])                                    # every member's own card is refreshed too
    assert all(failure_tickets.get(m)["status"] == failure_tickets.RESCHEDULED for m in burst["members"])
    assert failure_tickets.get(burst["id"])["status"] == failure_tickets.DONE
    assert "Đã lên lịch lại 3 lỗi" in r.text and "Còn chờ: 0 · đã lên lịch lại: 3" in r.text
    assert _data(r.keyboard) == [f"fb|ua|{burst['id']}"] and "(3)" in r.keyboard[0][0]["text"]


def test_reschedule_all_skips_what_a_blind_retry_could_harm_and_says_why(env, later_slot):
    safe, _ = _fail(); capped, _ = _fail(retries=2); unsure, _ = _fail(UNSURE); stale, _ = _fail(age_hours=60)
    batch = _batch(safe, capped, unsure, stale)
    r = _press("ra", batch)
    assert r.toast.startswith("Đã lên lịch lại 1 lỗi, chưa làm được 3")
    statuses = {t["id"]: failure_tickets.get(t["id"])["status"] for t in (safe, capped, unsure, stale)}
    assert statuses[safe["id"]] == failure_tickets.RESCHEDULED
    assert [statuses[t["id"]] for t in (capped, unsure, stale)] == [failure_tickets.OPEN] * 3          # left for /error
    assert "đã thử lại 2 lần" in r.text and "chưa rõ bài đã lên chưa" in r.text and "lỗi đã quá cũ" in r.text
    assert failure_tickets.get(batch["id"])["status"] == failure_tickets.OPEN
    assert set(r.also_sync) == {safe["id"]}


def test_reschedule_all_refuses_a_member_whose_post_went_out_meanwhile_and_one_whose_account_is_off(env, later_slot):
    posted_task = _failed_task(age_hours=0.05)
    posted = _ticket_for(posted_task)
    db.log_action(account_id="acc-a", action="post_to_group", success=True, target_url=posted_task.target_url, content=posted_task.content)
    batch = _batch(posted)
    r = _press("ra", batch)
    assert r.alert and "bài đã đăng thành công" in r.toast and failure_tickets.get(posted["id"])["status"] == failure_tickets.OPEN
    other = _ticket_for(_failed_task(age_hours=0.05))
    failure_tickets.update(other["id"], content="khác", source_id="other-job")
    env["acc-a"].status = AccountStatus.DISABLED
    r = _press("ra", _batch(failure_tickets.get(other["id"])))
    assert r.alert and "tài khoản đang tắt/tạm dừng" in r.toast
    assert schedule_store.list_pending() == []


def test_reschedule_all_with_nothing_open_says_so(env):
    t, _ = _fail()
    telegram_failures.dismiss_ticket(t, "Tu")
    r = _press("ra", _batch(t))
    assert r.toast == "Không còn lỗi nào đang chờ" and schedule_store.list_pending() == []


def test_one_member_that_blows_up_does_not_stop_the_others(env, later_slot, monkeypatch):
    a, _ = _fail(); b, _ = _fail()
    real = telegram_failures.requeue_for_bulk

    def flaky(ticket, actor):
        if ticket["id"] == a["id"]:
            raise RuntimeError("disk full")
        return real(ticket, actor)

    monkeypatch.setattr(telegram_failures, "requeue_for_bulk", flaky)
    r = _press("ra", _batch(a, b))
    assert "Đã lên lịch lại 1 lỗi, chưa làm được 1" in r.toast and failure_tickets.get(b["id"])["status"] == failure_tickets.RESCHEDULED


def test_a_second_tap_on_the_same_card_does_not_requeue_twice(env, later_slot):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    _press("ra", burst)
    again = _press("ra", burst)
    assert again.toast == "Không còn lỗi nào đang chờ" and len(schedule_store.list_pending()) == 3


# --- Hoàn tác ---------------------------------------------------------------------------------------------------------------------

def test_undo_all_puts_every_task_back_and_reopens_the_card(env, later_slot):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    _press("ra", burst)
    r = _press("ua", burst)
    assert r.toast == "Đã hoàn tác 3 lỗi" and schedule_store.list_pending() == [] and len(schedule_store.list_failed()) == 3
    assert all(failure_tickets.get(m)["status"] == failure_tickets.OPEN for m in burst["members"])
    assert failure_tickets.get(burst["id"])["status"] == failure_tickets.OPEN and failure_tickets.get(burst["id"])["last_resched"] is None
    assert _data(r.keyboard) == [f"fb|ra|{burst['id']}", f"fb|sa|{burst['id']}"]       # back to the original choices
    assert all(schedule_store.failed_at(t.task_id) is not None for t in schedule_store.list_failed())


def test_undo_all_leaves_alone_a_task_that_is_about_to_run_or_already_ran(env, later_slot):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    _press("ra", burst)
    first, second = failure_tickets.get_many(burst["members"])[:2]
    schedule_store.update(first["resched"]["task_id"], scheduled_at=(datetime.now(timezone.utc) + timedelta(seconds=10)).isoformat())
    schedule_store.mark_posted(second["resched"]["task_id"], "ok")
    r = _press("ua", burst)
    assert r.toast.startswith("Đã hoàn tác 1 lỗi, 2 không hoàn tác được")
    assert failure_tickets.get(first["id"])["status"] == failure_tickets.RESCHEDULED
    assert failure_tickets.get(second["id"])["status"] == failure_tickets.RESCHEDULED


def test_a_member_undone_by_hand_is_not_touched_again(env, later_slot):
    a, _ = _fail(); b, _ = _fail()
    batch = _batch(a, b)
    _press("ra", batch)
    telegram_failures.handle_callback(f"ud|{a['id']}", "Tu")                              # undone from its own card
    r = _press("ua", batch)
    assert r.toast == "Đã hoàn tác 1 lỗi" and schedule_store.list_pending() == []


def test_undo_with_nothing_to_undo(env):
    t, _ = _fail()
    assert _press("ua", _batch(t)).toast == "Không có gì để hoàn tác"


# --- Bỏ qua tất cả ----------------------------------------------------------------------------------------------------------------

def test_skip_all_asks_first_then_dismisses_every_open_member(env):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    ask = _press("sa", burst)
    assert ask.alert and "Bỏ qua 3 lỗi" in ask.toast and _data(ask.keyboard) == [f"fb|sc|{burst['id']}|3", f"fb|bk|{burst['id']}"]
    assert all(failure_tickets.get(m)["status"] == failure_tickets.OPEN for m in burst["members"])     # asking changed nothing
    assert _press("bk", burst).keyboard                                                              # "Quay lại" restores the choices
    r = _press("sc|3", burst) if False else telegram_batches.handle_callback(f"sc|{burst['id']}|3", "Tu")
    assert r.toast == "Đã bỏ qua 3 lỗi" and set(r.also_sync) == set(burst["members"])
    assert all(failure_tickets.get(m)["status"] == failure_tickets.DISMISSED for m in burst["members"])
    assert failure_tickets.get(burst["id"])["status"] == failure_tickets.DONE and r.keyboard == []
    assert len(schedule_store.list_failed()) == 3                                                     # nothing was deleted


def test_skip_all_leaves_members_already_handled_alone(env):
    a, _ = _fail(); b, _ = _fail()
    telegram_failures.dismiss_ticket(a, "An")
    r = _press("sc", _batch(a, b))
    assert r.toast == "Đã bỏ qua 1 lỗi" and failure_tickets.get(a["id"])["resolved_by"] == "An"


# --- routing, a vanished card, replies -----------------------------------------------------------------------------------------

def test_the_dispatcher_routes_fb_buttons_to_the_group_cards(env, later_slot):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    r = telegram_actions.handle_callback(f"fb|ra|{burst['id']}", "card text", "Tu")
    assert r.toast == "Đã lên lịch lại 3 lỗi"
    gone = telegram_actions.handle_callback("fb|ra|nope", "", "Tu")
    assert "không còn" in gone.toast and gone.keyboard == []
    not_a_batch = telegram_actions.handle_callback(f"fb|ra|{_fail()[0]['id']}", "", "Tu")           # a forged button: a failure id as a batch id
    assert "không còn" in not_a_batch.toast and schedule_store.list_pending() != [] and len(schedule_store.list_pending()) == 3


def test_replying_to_a_group_card_explains_instead_of_editing(env):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    outcome = telegram_failures.apply_reply(burst, "nội dung mới", "Tu")
    assert outcome.ticket_id is None and "/error" in outcome.message and schedule_store.list_pending() == []


def test_old_group_cards_are_pruned_but_failures_are_kept(env):
    t, _ = _fail()
    old_card = _batch(t)
    store = failure_tickets._load()
    store[old_card["id"]]["created_at"] = (datetime.now(timezone.utc) - timedelta(days=5)).isoformat()
    failure_tickets._save(store)
    failure_tickets.create(account_id="x")                                                           # creating prunes
    assert failure_tickets.get(old_card["id"]) is None and failure_tickets.get(t["id"]) is not None


# --- the /error summary card ----------------------------------------------------------------------------------------------------------

def test_the_error_list_gets_a_summary_card_only_when_several_safe_failures_wait(env):
    _failed_task(age_hours=1); _failed_task(NET, age_hours=2)
    assert telegram_batches.build_list_batch() is None                                           # two are not worth a bulk card
    _failed_task(SLOW, age_hours=3); _failed_task(UNSURE, age_hours=4)
    batch = telegram_batches.build_list_batch()
    assert batch["scope"] == "list" and len(batch["members"]) == 3                               # the uncertain one is not a member
    members = failure_tickets.get_many(batch["members"])
    assert [m["failed_at"] for m in members] == sorted(m["failed_at"] for m in members)           # oldest first
    text = telegram_batches.render(batch)
    assert text.startswith("📋 3 lỗi an toàn đang chờ thử lại") and "Facebook tải quá chậm" in text and "Máy mất mạng" in text
    assert _data(telegram_batches.keyboard_for(batch))[0] == f"fb|ra|{batch['id']}"


# --- showing it ------------------------------------------------------------------------------------------------------------------------------

async def test_a_new_card_is_sent_to_everyone_and_remembered(env, monkeypatch):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    sent = []

    async def send_ticket(text, keyboard=None, *, photo_path=None, silent=True):
        sent.append((text, keyboard, photo_path, silent))
        return [{"chat_id": "111", "message_id": 5, "photo": False}, {"chat_id": "222", "message_id": 6, "photo": False}]

    monkeypatch.setattr(telegram_notify, "send_ticket", send_ticket)
    assert await telegram_batches.announce(burst, True) is True
    [(text, keyboard, photo, silent)] = sent
    assert "3 lỗi cùng nguyên nhân" in text and keyboard and photo is None and silent is True
    assert [(m["chat_id"], m["message_id"]) for m in failure_tickets.get(burst["id"])["messages"]] == [("111", 5), ("222", 6)]


async def test_a_card_nobody_received_reports_false_so_the_caller_can_fall_back(env, monkeypatch):
    _fail(); _fail(); _t, (burst, _n) = _fail()

    async def send_ticket(*a, **k):
        return []

    monkeypatch.setattr(telegram_notify, "send_ticket", send_ticket)
    assert await telegram_batches.announce(burst, True) is False


async def test_a_growing_burst_is_edited_in_place_not_resent(env, monkeypatch):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    failure_tickets.add_message(burst["id"], "111", 5)
    t4, (same, _new) = _fail()
    edits, sends = [], []

    async def edit(chat_id, message_id, *, text=None, keyboard=None, photo=False):
        edits.append((chat_id, message_id, text, photo))
        return True

    async def send_ticket(*a, **k):
        sends.append(1)
        return []

    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    monkeypatch.setattr(telegram_notify, "send_ticket", send_ticket)
    assert await telegram_batches.announce(same, False) is True
    assert sends == [] and len(edits) == 1 and edits[0][:2] == ("111", 5) and "4 lỗi cùng nguyên nhân" in edits[0][2] and edits[0][3] is False


async def test_sync_copies_renders_a_group_card_with_its_own_text_and_buttons(env, monkeypatch):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    failure_tickets.add_message(burst["id"], "111", 5)
    edits = []

    async def edit(chat_id, message_id, *, text=None, keyboard=None, photo=False):
        edits.append((text, keyboard))
        return True

    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    await telegram_failures.sync_copies(burst["id"])
    [(text, keyboard)] = edits
    assert text == telegram_batches.render(failure_tickets.get(burst["id"])) and _data(keyboard)[0].startswith("fb|ra|")
    _press("sc", burst)
    edits.clear()
    await telegram_failures.sync_copies(burst["id"])
    assert edits[0][1] == [] and "Đã bỏ qua 3 lỗi" in edits[0][0]


# --- review fixes (2026-11-01) ------------------------------------------------------------------------------------------------

def test_a_second_tap_that_re_queues_nothing_keeps_the_undo_of_the_first(env, later_slot):
    a, _ = _fail(); b, _ = _fail(); unsure, _ = _fail(UNSURE)
    batch = _batch(a, b, unsure)
    _press("ra", batch)
    again = _press("ra", batch)                                                          # e.g. another recipient's stale copy
    assert again.alert and "chưa rõ bài đã lên chưa" in again.toast
    assert _data(again.keyboard) == [f"fb|sa|{batch['id']}", f"fb|ua|{batch['id']}"] and "Đã lên lịch lại 2 lỗi" in again.text
    assert _press("ua", batch).toast == "Đã hoàn tác 2 lỗi"


def test_skipping_the_rest_keeps_the_undo_of_an_earlier_re_queue(env, later_slot):
    a, _ = _fail(); b, _ = _fail(); unsure, _ = _fail(UNSURE)
    batch = _batch(a, b, unsure)
    _press("ra", batch)
    done = _press("sc", batch)
    assert "Đã lên lịch lại 2 lỗi" in done.text and "Đã bỏ qua 1 lỗi" in done.text and _data(done.keyboard) == [f"fb|ua|{batch['id']}"]
    assert failure_tickets.get(unsure["id"])["status"] == failure_tickets.DISMISSED
    undone = _press("ua", batch)
    assert undone.toast == "Đã hoàn tác 2 lỗi" and failure_tickets.get(unsure["id"])["status"] == failure_tickets.DISMISSED


def test_a_later_bulk_re_queue_adds_to_the_undo_instead_of_replacing_it(env, later_slot):
    a, _ = _fail(); b, _ = _fail(); c, _ = _fail()
    batch = _batch(a, b)
    _press("ra", batch)
    failure_tickets.update(batch["id"], members=[a["id"], b["id"], c["id"]])               # a burst member that joined afterwards
    r = _press("ra", batch)
    assert "Đã lên lịch lại 3 lỗi" in r.text and "(3)" in r.keyboard[-1][0]["text"]
    assert _press("ua", batch).toast == "Đã hoàn tác 3 lỗi"


def test_every_safe_cause_still_groups_and_the_status_follows_the_members(env):
    _fail(NET); _fail(NET); _t, (burst, _n) = _fail(NET)
    assert burst["category"] == "network" and failure_tickets.get(burst["id"])["status"] == failure_tickets.OPEN
    _press("sc", burst)
    assert failure_tickets.get(burst["id"])["status"] == failure_tickets.DONE


async def test_handling_one_member_on_its_own_card_refreshes_the_group_card(env, monkeypatch):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    members = failure_tickets.get_many(burst["members"])
    failure_tickets.add_message(burst["id"], "111", 5)
    failure_tickets.add_message(members[0]["id"], "111", 6, photo=True)
    edits = []

    async def edit(chat_id, message_id, *, text=None, keyboard=None, photo=False):
        edits.append((chat_id, message_id, text))
        return True

    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    telegram_failures.dismiss_ticket(members[0], "Tu")
    await telegram_failures.sync_with_groups(members[0]["id"], skip=("111", 6))
    [(chat, message, text)] = edits                                                      # the member's own message was the clicked one → skipped
    assert (chat, message) == ("111", 5) and "Còn chờ: 2" in text and "đã bỏ qua/ghi nhận: 1" in text
    edits.clear()
    await telegram_failures.sync_changed([members[1]["id"]], exclude=(burst["id"],))     # the caller already edited that group card
    assert edits == []


async def test_a_group_card_without_a_copy_anywhere_is_not_resynced(env, monkeypatch):
    _fail(); _fail(); _t, (burst, _n) = _fail()

    async def edit(*a, **k):
        raise AssertionError("no message to edit")

    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    await telegram_failures.sync_with_groups(burst["members"][0])


async def test_a_card_that_was_delivered_but_not_remembered_still_counts_as_sent(env, monkeypatch):
    _fail(); _fail(); _t, (burst, _n) = _fail()

    async def send_ticket(*a, **k):
        return [{"chat_id": "111", "message_id": 5, "photo": False}]

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(telegram_notify, "send_ticket", send_ticket)
    monkeypatch.setattr(failure_tickets, "add_message", broken)
    assert await telegram_batches.announce(burst, True) is True                              # delivered → the caller must not send a duplicate


def test_the_summary_card_can_reuse_the_failures_the_caller_already_has(env, monkeypatch):
    for hours in (1, 2, 3):
        _failed_task(age_hours=hours)
    tickets = telegram_failures.open_failures()
    monkeypatch.setattr(telegram_failures, "open_failures", lambda *a, **k: (_ for _ in ()).throw(AssertionError("scanned again")))
    batch = telegram_batches.build_list_batch(tickets)
    assert batch is not None and len(batch["members"]) == 3
    items, overflow = telegram_failures.build_list(tickets=tickets)
    assert len(items) == 3 and overflow == 0


def test_a_ticket_can_be_deleted_and_group_cards_found_by_member(env):
    t, _ = _fail()
    batch = _batch(t)
    assert [b["id"] for b in failure_tickets.batches_containing(t["id"])] == [batch["id"]]
    failure_tickets.delete(batch["id"])
    failure_tickets.delete("nope")                                                          # unknown → no error
    assert failure_tickets.get(batch["id"]) is None and failure_tickets.batches_containing(t["id"]) == []


# --- review round 2 (2026-11-01) ------------------------------------------------------------------------------------------------

def test_skip_all_never_dismisses_what_the_person_was_not_asked_about(env):
    a, _ = _fail(); b, _ = _fail()
    batch = _batch(a, b)
    ask = _press("sa", batch)
    assert _data(ask.keyboard)[0] == f"fb|sc|{batch['id']}|2"
    c, _ = _fail()
    failure_tickets.update(batch["id"], members=[a["id"], b["id"], c["id"]])               # a failure joined while the question was open
    again = telegram_batches.handle_callback(f"sc|{batch['id']}|2", "Tu")
    assert again.alert and "nay có 3 lỗi" in again.toast and _data(again.keyboard)[0] == f"fb|sc|{batch['id']}|3"
    assert all(failure_tickets.get(m["id"])["status"] == failure_tickets.OPEN for m in (a, b, c))
    done = telegram_batches.handle_callback(f"sc|{batch['id']}|3", "Tu")
    assert done.toast == "Đã bỏ qua 3 lỗi"


def test_a_cause_that_tends_to_repeat_is_not_retried_in_bulk(env, later_slot):
    UI = 'error:Locator.wait_for: Timeout 30000ms exceeded.\nCall log:\n  - waiting for get_by_role("dialog")'
    _fail(UI); _fail(UI); _t, (burst, _n) = _fail(UI)
    assert burst is not None
    text = telegram_batches.render(burst)
    assert "hay lặp lại" in text and "không thử lại hàng loạt" in text
    assert _data(telegram_batches.keyboard_for(burst)) == [f"fb|sa|{burst['id']}"]          # no "reschedule all"
    r = _press("ra", burst)                                                                     # a stale/forged press changes nothing
    assert r.alert and "lỗi hay lặp lại" in r.toast and schedule_store.list_pending() == []
    single = telegram_failures.keyboard_for(failure_tickets.get_many(burst["members"])[0])
    assert [b["callback_data"].split("|")[1] for row in single for b in row] == ["rs", "sk"]  # ...but each one is still a tap on its own card


def test_a_failure_already_in_an_open_burst_never_starts_a_second_one(env):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    failure_tickets.update(burst["id"], last_member_at=(datetime.now(timezone.utc) - timedelta(hours=2)).isoformat())   # its window has lapsed
    _t4, (second, _new) = _fail()
    assert second is None                                                                          # 3 are still open but already grouped; only 1 is free
    _fail(); _t6, (second, new) = _fail()
    assert new and set(second["members"]).isdisjoint(burst["members"])                           # a new burst holds only failures not grouped yet


async def test_a_group_card_nobody_could_update_does_not_count_as_reported(env, monkeypatch):
    _fail(); _fail(); _t, (burst, _n) = _fail()
    failure_tickets.add_message(burst["id"], "111", 5)

    async def failing(*a, **k):
        return False

    monkeypatch.setattr(telegram_notify, "edit_message", failing)
    assert await telegram_batches.announce(burst, False) is False                                # the caller then gives the failure its own card


def test_replying_to_a_streak_alert_says_what_it_is(env):
    from human_bot import telegram_streaks
    alert = telegram_streaks.create_ticket("acc-a", "post_to_group", 3, SLOW)
    outcome = telegram_failures.apply_reply(alert, "x", "Tu")
    assert outcome.ticket_id is None and "cảnh báo lỗi liên tiếp" in outcome.message


# --- review round 3 (2026-11-01) ------------------------------------------------------------------------------------------------

def test_a_failure_that_landed_together_with_the_one_that_started_the_burst_is_not_counted_twice(env, later_slot):
    _fail(); _fail(); t3, (burst, _n) = _fail()
    again, is_new = telegram_batches.attach(t3)                                       # its own attach() arrives after another thread already grouped it
    assert not is_new and again["id"] == burst["id"] and again["members"].count(t3["id"]) == 1 and len(again["members"]) == 3
    failure_tickets.update(burst["id"], members=burst["members"] + [t3["id"]])         # ...and even a stored duplicate is read once
    assert len(telegram_batches.members_of(failure_tickets.get(burst["id"]))) == 3
    r = _press("ra", burst)
    assert r.toast == "Đã lên lịch lại 3 lỗi" and len(schedule_store.list_pending()) == 3


def test_the_burst_window_never_moves_backwards(env):
    _fail(); _fail(); _t3, (burst, _n) = _fail()
    latest = telegram_batches._parse(failure_tickets.get(burst["id"])["last_member_at"])
    late = _ticket_for(_failed_task(age_hours=0.2))                                     # a failure recorded late, with an older failed_at
    failure_tickets.update(late["id"], failed_at=(latest - timedelta(minutes=5)).isoformat())
    joined, _new = telegram_batches.attach(failure_tickets.get(late["id"]))
    assert telegram_batches._parse(joined["last_member_at"]) >= latest


async def test_a_failure_joining_while_the_card_is_still_being_sent_edits_it_instead_of_sending_another(env, monkeypatch):
    import asyncio
    _fail(); _fail(); _t3, (burst, _n) = _fail()
    sent, edited = [], []

    async def slow_send(text, keyboard=None, *, photo_path=None, silent=True):
        sent.append(text)
        await asyncio.sleep(0.05)                                                        # failure 4 arrives during this
        return [{"chat_id": "111", "message_id": 5, "photo": False}]

    async def edit(chat_id, message_id, *, text=None, keyboard=None, photo=False):
        edited.append(text)
        return True

    monkeypatch.setattr(telegram_notify, "send_ticket", slow_send)
    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    _t4, (same, _new) = _fail()
    first = asyncio.create_task(telegram_batches.announce(burst, True))
    await asyncio.sleep(0.01)
    second = asyncio.create_task(telegram_batches.announce(same, False))               # holds the pre-send copy with no messages yet
    assert await first is True and await second is True
    assert len(sent) == 1 and len(edited) == 1 and "4 lỗi cùng nguyên nhân" in edited[0]


def test_the_error_summary_card_is_reused_not_stored_again_each_time(env):
    for hours in (1, 2, 3):
        _failed_task(age_hours=hours)
    first = telegram_batches.build_list_batch()
    second = telegram_batches.build_list_batch()
    assert first["id"] == second["id"] and len(failure_tickets.list_open(kind=failure_tickets.BATCH)) == 1
    _failed_task(age_hours=4)
    third = telegram_batches.build_list_batch()
    assert third["id"] == first["id"] and len(third["members"]) == 4                         # the same card, with the new failure added


def test_a_card_that_vanishes_during_a_bulk_action_does_not_break_the_answer(env, later_slot, monkeypatch):
    a, _ = _fail(); b, _ = _fail()
    batch = _batch(a, b)
    real = failure_tickets.update
    monkeypatch.setattr(failure_tickets, "update", lambda tid, **f: None if tid == batch["id"] else real(tid, **f))   # pruned meanwhile
    r = _press("ra", batch)
    assert r.toast == "Đã lên lịch lại 2 lỗi" and r.text and len(schedule_store.list_pending()) == 2
    assert _press("sc", batch).text


def test_long_skip_lists_still_fit_a_telegram_popup(env):
    assert len(telegram_batches._toast("x" * 500)) <= 195 and telegram_batches._toast("short") == "short"
    reasons = telegram_batches._SKIP_REASON
    why = ", ".join(f"{text} ×9" for text in reasons.values())
    assert len(telegram_batches._toast(f"Chưa làm được 99 lỗi: {why}. Xem từng lỗi ở /error.")) <= 195


def test_an_unwritable_ticket_store_is_reported_not_pretended(env, monkeypatch):
    t, _ = _fail()
    monkeypatch.setattr(failure_tickets, "_save", lambda tickets: False)
    assert failure_tickets.update(t["id"], status=failure_tickets.DISMISSED) is None            # not a ticket that only exists in memory


def test_requeue_tells_the_truth_when_only_the_ticket_could_not_be_saved(env, later_slot, monkeypatch):
    task = _failed_task(age_hours=0.05)
    t = _ticket_for(task)
    monkeypatch.setattr(failure_tickets, "update", lambda tid, **f: None)
    r = telegram_failures.handle_callback(f"rs|{t['id']}", "Tu")
    assert r.alert and "đừng bấm lại" in r.toast and schedule_store.get(task.task_id) is not None     # it IS queued; the person is told not to repeat it
