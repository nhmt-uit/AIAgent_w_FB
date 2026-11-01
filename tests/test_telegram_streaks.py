"""Buttons on the "N failures in a row" alert (2026-11-01, failure tickets phase 2):
[⏻ Tắt] one tap, [⚠ Tạm dừng] after a confirm, [👌 Đã biết]; the card follows the
account's LIVE status."""
from __future__ import annotations

import pytest

from human_bot import failure_tickets, telegram_actions, telegram_notify, telegram_streaks
from human_bot.config import AccountStatus, get_all_accounts
from human_bot.runtime_config import get_resume_cooldown_info

ACC = "tu_iizuki"
MESSAGE = "error:Locator.wait_for: Timeout 30000ms exceeded.\nCall log:\n  - waiting for get_by_role(\"dialog\")"


@pytest.fixture
def alert(isolated_runtime_config, isolated_accounts_dir):
    return telegram_streaks.create_ticket(ACC, "post_to_group", 3, MESSAGE)


def _press(verb, ticket, actor="Tu"):
    return telegram_streaks.handle_callback(f"{verb}|{ticket['id']}", actor)


def _data(keyboard):
    return [b["callback_data"] for row in keyboard for b in row]


def _status():
    return get_all_accounts()[ACC].status


def test_the_alert_names_the_account_the_streak_and_the_cause(alert):
    text = telegram_streaks.render(alert)
    assert "🔴" in text and "thất bại 3 lần LIÊN TIẾP" in text and "Không thấy ô/nút cần bấm" in text and "Tài khoản đang hoạt động" in text
    assert alert["kind"] == failure_tickets.STREAK and alert not in failure_tickets.list_open()      # never counted as a failure
    assert _data(telegram_streaks.keyboard_for(alert)) == [
        f"fa|off|{alert['id']}", f"fa|ps|{alert['id']}", f"fa|ok|{alert['id']}", f"fa|sn1|{alert['id']}", f"fa|snm|{alert['id']}",
    ]
    assert all(len(d.encode()) <= 64 for d in _data(telegram_streaks.keyboard_for(alert)))


def test_switching_off_is_one_tap_and_offers_to_switch_back_on(alert):
    r = _press("off", alert)
    assert _status() == AccountStatus.DISABLED and r.toast == "Đã tắt tài khoản" and r.close_session_of == ACC
    assert "Tu đã TẮT tài khoản này" in r.text
    assert _data(r.keyboard) == [f"fa|on|{alert['id']}"] and r.ticket_id == alert["id"]
    back = _press("on", alert)
    assert _status() == AccountStatus.ACTIVE and back.keyboard == [] and "Tu đã bật lại" in back.text
    assert get_resume_cooldown_info(ACC) is None                                    # switching off/on has no cooldown


def test_pausing_asks_first_and_changes_nothing_until_confirmed(alert):
    ask = _press("ps", alert)
    assert ask.alert and "hạ nhiệt" in ask.toast and _data(ask.keyboard) == [f"fa|pc|{alert['id']}", f"fa|bk|{alert['id']}"]
    assert _status() == AccountStatus.ACTIVE
    assert _data(_press("bk", alert).keyboard)[0].startswith("fa|off|")               # "Quay lại" restores the choices
    r = _press("pc", alert)
    assert _status() == AccountStatus.PAUSED and r.close_session_of == ACC and "TẠM DỪNG" in r.text
    assert _data(r.keyboard) == [f"fa|rv|{alert['id']}"]


def test_resuming_a_paused_account_asks_first_and_starts_the_cooldown(alert):
    _press("pc", alert)
    ask = _press("rv", alert)
    assert ask.alert and "giới hạn thấp" in ask.toast and _status() == AccountStatus.PAUSED
    r = _press("rc", alert)
    assert _status() == AccountStatus.ACTIVE and get_resume_cooldown_info(ACC) is not None
    assert r.keyboard == [] and "kích hoạt lại" in r.text


def test_acknowledging_just_removes_the_buttons(alert):
    r = _press("ok", alert)
    assert r.keyboard == [] and "Tu đã xem" in r.text and _status() == AccountStatus.ACTIVE


def test_a_stale_button_never_changes_an_account_that_moved_on(alert):
    _press("off", alert)
    again = _press("off", alert)                                                       # already off
    assert "không còn ở trạng thái hoạt động" in again.toast and _status() == AccountStatus.DISABLED
    assert "không còn ở trạng thái hoạt động" in _press("ps", alert).toast and "không còn ở trạng thái hoạt động" in _press("pc", alert).toast
    assert _status() == AccountStatus.DISABLED                                          # a pause must not override "off" by a stale tap
    assert "không còn đang tạm dừng" in _press("rc", alert).toast
    _press("on", alert)
    assert "không còn đang tắt" in _press("on", alert).toast


def test_the_card_follows_the_live_status_when_the_admin_changes_it(alert):
    from human_bot.runtime_config import set_account_paused
    set_account_paused(ACC, True, reason="checkpoint")                                   # done in /admin, not from this card
    assert "đang TẠM DỪNG" in telegram_streaks.render(alert)
    assert _data(telegram_streaks.keyboard_for(alert)) == [f"fa|rv|{alert['id']}"]


def test_a_forged_or_vanished_button_is_harmless(alert, isolated_runtime_config):
    assert "không còn" in telegram_streaks.handle_callback("off|nope", "Tu").toast
    failure = failure_tickets.create(kind="failure", account_id=ACC)
    assert "không còn" in telegram_streaks.handle_callback(f"off|{failure['id']}", "Tu").toast and _status() == AccountStatus.ACTIVE
    assert telegram_streaks.handle_callback(f"zzz|{alert['id']}", "Tu").toast == "Nút không hợp lệ"


def test_the_dispatcher_routes_fa_buttons(alert):
    r = telegram_actions.handle_callback(f"fa|ok|{alert['id']}", "old text", "Tu")
    assert "Tu đã xem" in r.text


async def test_the_loud_alert_goes_out_with_buttons_and_is_remembered(isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    sent = []

    async def send_ticket(text, keyboard=None, *, photo_path=None, silent=True):
        sent.append((text, keyboard, silent))
        return [{"chat_id": "111", "message_id": 9, "photo": False}]

    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(telegram_notify, "send_ticket", send_ticket)
    await telegram_streaks.send_alert(ACC, "post_to_group", 3, MESSAGE)
    [(text, keyboard, silent)] = sent
    assert silent is False and "LIÊN TIẾP" in text and _data(keyboard)[0].startswith("fa|off|")        # loud, like before
    [ticket] = failure_tickets.list_open(kind=failure_tickets.STREAK)
    assert ticket["messages"] == [{"chat_id": "111", "message_id": 9, "photo": False}]


async def test_the_alert_falls_back_to_plain_text_when_the_card_reaches_nobody(isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    plain = []

    async def send_ticket(*a, **k):
        return []

    async def send_message(text, silent=True):
        plain.append((text, silent))
        return True

    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(telegram_notify, "send_ticket", send_ticket)
    monkeypatch.setattr(telegram_notify, "send_message", send_message)
    await telegram_streaks.send_alert(ACC, "post_to_group", 3, "boom")
    assert plain == [(f"🔴 {ACC} · post_to_group thất bại 3 lần LIÊN TIẾP\nLần gần nhất: boom", False)]
    assert failure_tickets.list_open(kind=failure_tickets.STREAK) == []                       # the card nobody holds is not left behind


async def test_the_alert_falls_back_when_the_card_cannot_be_built(isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    plain = []

    async def send_message(text, silent=True):
        plain.append(silent)
        return True

    def broken(*a, **k):
        raise RuntimeError("store unwritable")

    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(telegram_streaks, "create_ticket", broken)
    monkeypatch.setattr(telegram_notify, "send_message", send_message)
    await telegram_streaks.send_alert(ACC, "post_to_group", 3, "boom")
    assert plain == [False]


async def test_nothing_is_sent_when_telegram_is_not_configured(monkeypatch):
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: False)
    await telegram_streaks.send_alert(ACC, "post_to_group", 3, "boom")        # no ticket, no network (httpx guard would raise)


async def test_an_alert_that_was_delivered_but_not_remembered_is_not_sent_twice(isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    plain = []

    async def send_ticket(*a, **k):
        return [{"chat_id": "111", "message_id": 9, "photo": False}]

    async def send_message(text, silent=True):
        plain.append(text)
        return True

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(telegram_notify, "send_ticket", send_ticket)
    monkeypatch.setattr(telegram_notify, "send_message", send_message)
    monkeypatch.setattr(failure_tickets, "add_message", broken)
    await telegram_streaks.send_alert(ACC, "post_to_group", 3, "boom")
    assert plain == []                                                                  # the card reached the recipients


async def test_one_recipient_failing_does_not_lose_the_references_of_the_others(isolated_runtime_config, monkeypatch):
    from human_bot.runtime_config import add_telegram_recipient
    add_telegram_recipient("111", "A")
    add_telegram_recipient("222", "B")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)

    async def send_to(chat_id, text, keyboard=None, *, photo_path=None, silent=True):
        if chat_id == "222":
            raise RuntimeError("boom")
        return {"chat_id": chat_id, "message_id": 7, "photo": False}

    monkeypatch.setattr(telegram_notify, "send_ticket_to", send_to)
    refs = await telegram_notify.send_ticket("x", None)
    assert refs == [{"chat_id": "111", "message_id": 7, "photo": False}]


def test_the_pause_question_fits_a_telegram_popup(alert):
    assert len(_press("ps", alert).toast) <= 200


# --- snoozing, and the "this group keeps failing" alert (phase 3) -----------------------------------------------------------

from datetime import datetime, timedelta, timezone  # noqa: E402

GROUP = "https://www.facebook.com/groups/1383875949915495"


@pytest.fixture
def group_alert(isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    from human_bot import telegram_failures
    monkeypatch.setattr(telegram_failures, "_group_label", lambda aid, url: "Nhóm Thợ Hàn")
    monkeypatch.setattr(telegram_failures, "group_label", lambda aid, url: "Nhóm Thợ Hàn")
    return telegram_streaks.create_group_ticket(ACC, GROUP, 3, MESSAGE)


def test_snooze_times_are_an_hour_or_the_next_six_in_the_morning_jst():
    jst = timezone(timedelta(hours=9))

    def at(h, m=0):
        return datetime(2026, 11, 1, h, m, tzinfo=jst).astimezone(timezone.utc)

    assert telegram_streaks.snooze_until("1h", at(10)) == at(11)
    assert telegram_streaks.snooze_until("morning", at(10)) == datetime(2026, 11, 2, 6, 0, tzinfo=jst).astimezone(timezone.utc)
    assert telegram_streaks.snooze_until("morning", at(3)) == at(6)                       # 3 hours to go: that same morning
    assert telegram_streaks.snooze_until("morning", at(5, 30)) == datetime(2026, 11, 2, 6, 0, tzinfo=jst).astimezone(timezone.utc)   # <1h away: the next one


def test_without_a_snooze_the_alert_fires_exactly_when_the_streak_reaches_the_threshold(isolated_runtime_config):
    key = telegram_streaks.account_key(ACC, "post_to_group")
    assert [telegram_streaks.should_alert(key, n, 3) for n in (1, 2, 3, 4)] == [False, False, True, False]


def test_a_snooze_mutes_until_it_runs_out_then_alerts_again_only_if_still_failing(isolated_runtime_config):
    key = telegram_streaks.account_key(ACC, "post_to_group")
    now = datetime.now(timezone.utc)
    telegram_streaks.snooze(key, now + timedelta(hours=1))
    assert telegram_streaks.should_alert(key, 3, 3, now) is False and telegram_streaks.should_alert(key, 4, 3, now + timedelta(minutes=59)) is False
    after = now + timedelta(hours=1, minutes=1)
    assert telegram_streaks.should_alert(key, 4, 3, after) is True                        # still failing: tell again (even past the exact threshold)
    assert telegram_streaks.should_alert(key, 4, 3, after) is False                       # ...but only once - the used-up snooze was cleared
    telegram_streaks.snooze(key, now + timedelta(hours=1))
    assert telegram_streaks.should_alert(key, 1, 3, after) is False                      # the streak ended meanwhile: nothing to say
    assert len(failure_tickets.list_open(kind=telegram_streaks.SNOOZE)) == 1             # (the used-up record is harmless until a streak gets this far again)
    assert telegram_streaks.should_alert(key, 3, 3, after) is True                        # a NEW streak reaching the threshold alerts, like without any snooze
    assert failure_tickets.list_open(kind=telegram_streaks.SNOOZE) == []


def test_a_new_snooze_replaces_the_old_one_and_each_key_is_separate(isolated_runtime_config):
    now = datetime.now(timezone.utc)
    a, b = telegram_streaks.account_key(ACC, "post_to_group"), telegram_streaks.group_key(ACC, GROUP)
    telegram_streaks.snooze(a, now + timedelta(hours=1))
    telegram_streaks.snooze(a, now + timedelta(hours=5))
    assert len(failure_tickets.list_open(kind=telegram_streaks.SNOOZE)) == 1
    assert telegram_streaks.should_alert(a, 3, 3, now + timedelta(hours=2)) is False
    assert telegram_streaks.should_alert(b, 3, 3, now) is True                            # another key is not muted


def test_pressing_im_mutes_that_alert_and_says_until_when(alert):
    r = _press("sn1", alert)
    assert r.toast.startswith("Đã im đến") and "🔕 Tu đã tắt tiếng loại cảnh báo này đến" in r.text
    assert _data(r.keyboard) == [f"fa|off|{alert['id']}", f"fa|ps|{alert['id']}", f"fa|un|{alert['id']}"]   # muting keeps the account choices and can be undone
    assert telegram_streaks.should_alert(telegram_streaks.account_key(ACC, "post_to_group"), 3, 3) is False
    other = telegram_streaks.create_ticket(ACC, "comment_on_group_post", 3, MESSAGE)
    assert telegram_streaks.should_alert(telegram_streaks.account_key(ACC, "comment_on_group_post"), 3, 3) is True   # a different action is not muted
    morning = _press("snm", other)
    assert "đến" in morning.text and failure_tickets.get(other["id"])["snooze_until"] > failure_tickets.get(alert["id"])["snooze_until"]


def test_the_account_alert_shows_the_group_of_the_latest_failure(isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    from human_bot import telegram_failures
    monkeypatch.setattr(telegram_failures, "group_label", lambda aid, url: "Nhóm Thợ Hàn")
    ticket = telegram_streaks.create_ticket(ACC, "post_to_group", 3, MESSAGE, target_url=GROUP)
    assert "Nhóm gần nhất: Nhóm Thợ Hàn" in telegram_streaks.render(ticket)


def test_the_group_alert_names_the_group_says_what_it_might_be_and_where_to_edit_it(group_alert):
    text = telegram_streaks.render(group_alert)
    assert 'Nhóm "Nhóm Thợ Hàn" lỗi 3 lần liên tiếp' in text and "bị nhóm chặn" in text and "chờ quản trị viên duyệt" in text and "/admin/groups" in text
    assert "ngưng" in text and "Bot vẫn thử các bài sau" in text                               # owner's choice: only reported, not stopped
    assert _data(telegram_streaks.keyboard_for(group_alert)) == [
        f"fa|ok|{group_alert['id']}", f"fa|sn1|{group_alert['id']}", f"fa|snm|{group_alert['id']}",
    ]
    assert group_alert not in failure_tickets.list_open()                                       # never counted as a failure


def test_a_group_alert_has_no_account_buttons_even_if_forged(group_alert):
    for verb in ("off", "ps", "pc", "on", "rv", "rc"):
        assert _press(verb, group_alert).toast == "Nút không hợp lệ" and _status() == AccountStatus.ACTIVE
    assert "Tu đã xem" in _press("ok", group_alert).text
    r = _press("sn1", group_alert)
    assert _data(r.keyboard) == [f"fa|un|{group_alert['id']}"] and telegram_streaks.should_alert(telegram_streaks.group_key(ACC, GROUP), 3, 3) is False


def test_snoozing_an_alert_without_a_key_is_refused(isolated_runtime_config, isolated_accounts_dir):
    old = failure_tickets.create(kind=failure_tickets.STREAK, account_id=ACC, action="post_to_group", streak=3, message="x", handled=None)
    assert _press("sn1", old).toast == "Không tắt tiếng được tin này"


async def test_a_group_alert_goes_out_loud_with_buttons(group_alert, monkeypatch):
    sent = []

    async def send_ticket(text, keyboard=None, *, photo_path=None, silent=True):
        sent.append((text, keyboard, silent))
        return [{"chat_id": "111", "message_id": 9, "photo": False}]

    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(telegram_notify, "send_ticket", send_ticket)
    await telegram_streaks.send_group_alert(ACC, GROUP, 3, MESSAGE)
    [(text, keyboard, silent)] = sent
    assert silent is False and text.startswith("🟠 Nhóm") and _data(keyboard)[0].startswith("fa|ok|")
    assert len(failure_tickets.list_open(kind=failure_tickets.STREAK)) == 2                    # the fixture's + this one, each with its snooze key


def test_un_muting_brings_the_alert_back_and_the_buttons(alert):
    _press("sn1", alert)
    key = telegram_streaks.account_key(ACC, "post_to_group")
    assert telegram_streaks.should_alert(key, 3, 3) is False
    r = _press("un", alert)
    assert r.toast == "Đã bật lại cảnh báo" and "tắt tiếng" not in r.text
    assert _data(r.keyboard)[:3] == [f"fa|off|{alert['id']}", f"fa|ps|{alert['id']}", f"fa|ok|{alert['id']}"] and len(_data(r.keyboard)) == 5
    assert telegram_streaks.should_alert(key, 3, 3) is True
    assert "không đang bị tắt tiếng" in _press("un", alert).toast                         # nothing to undo any more


def test_a_muted_group_card_can_be_un_muted_too(group_alert):
    _press("snm", group_alert)
    assert _data(_press("un", group_alert).keyboard) == [f"fa|ok|{group_alert['id']}", f"fa|sn1|{group_alert['id']}", f"fa|snm|{group_alert['id']}"]


def test_the_check_costs_no_disk_read_below_the_threshold_and_survives_a_damaged_record(isolated_runtime_config, monkeypatch):
    key = telegram_streaks.account_key(ACC, "post_to_group")
    monkeypatch.setattr(failure_tickets, "list_open", lambda *a, **k: (_ for _ in ()).throw(AssertionError("read the store")))
    assert telegram_streaks.should_alert(key, 2, 3) is False and telegram_streaks.should_alert(key, 0, 3) is False
    monkeypatch.undo()
    failure_tickets.create(kind=telegram_streaks.SNOOZE, key=key, until="not a date")
    assert telegram_streaks.should_alert(key, 3, 3) is True                                 # a damaged record counts as run out - and is cleared
    assert failure_tickets.list_open(kind=telegram_streaks.SNOOZE) == []


def test_two_snoozes_at_once_leave_exactly_one(isolated_runtime_config):
    import threading
    key = telegram_streaks.group_key(ACC, GROUP)
    now = datetime.now(timezone.utc)
    threads = [threading.Thread(target=telegram_streaks.snooze, args=(key, now + timedelta(hours=1 + i))) for i in range(6)]
    [t.start() for t in threads]
    [t.join() for t in threads]
    assert len(failure_tickets.list_open(kind=telegram_streaks.SNOOZE)) == 1


def test_acting_on_the_account_ends_that_cards_mute_so_it_cannot_stay_muted_unseen(alert):
    key = telegram_streaks.account_key(ACC, "post_to_group")
    _press("sn1", alert)
    assert telegram_streaks.should_alert(key, 3, 3) is False
    r = _press("off", alert)                                                                 # switch the account off from the muted card
    assert _status() == AccountStatus.DISABLED and "tắt tiếng" not in r.text
    assert failure_tickets.list_open(kind=telegram_streaks.SNOOZE) == []
    _press("on", alert)
    assert telegram_streaks.should_alert(key, 3, 3) is True                                  # alerts are live again


def test_un_muting_an_old_card_does_not_lift_a_newer_cards_mute(isolated_runtime_config, isolated_accounts_dir):
    key = telegram_streaks.account_key(ACC, "post_to_group")
    a = telegram_streaks.create_ticket(ACC, "post_to_group", 3, MESSAGE)
    _press("sn1", a)
    b = telegram_streaks.create_ticket(ACC, "post_to_group", 3, MESSAGE)                      # a later streak, its own card
    _press("snm", b)
    r = _press("un", a)                                                                       # the OLD card's button
    assert r.toast == "Đã bật lại cảnh báo" and failure_tickets.get(a["id"])["handled"] is None
    assert telegram_streaks.should_alert(key, 3, 3) is False                                  # B's mute is untouched
    _press("un", b)
    assert telegram_streaks.should_alert(key, 3, 3) is True


def test_unsnooze_reports_whether_anything_was_lifted(isolated_runtime_config):
    key = telegram_streaks.group_key(ACC, GROUP)
    assert telegram_streaks.unsnooze(key) is False
    telegram_streaks.snooze(key, datetime.now(timezone.utc) + timedelta(hours=1), "t1")
    assert telegram_streaks.unsnooze(key, "t2") is False and telegram_streaks.unsnooze(key, "t1") is True
