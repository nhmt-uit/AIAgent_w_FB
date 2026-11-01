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
    assert _data(telegram_streaks.keyboard_for(alert)) == [f"fa|off|{alert['id']}", f"fa|ps|{alert['id']}", f"fa|ok|{alert['id']}"]
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
