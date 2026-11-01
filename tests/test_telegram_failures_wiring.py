"""How failure tickets are wired into the rest of the system (2026-11-01): the
failed attempt → card, the Telegram calls (photo + caption edits), the listen
loop (replies, /loi, button presses on photo messages) and the scheduler."""
from __future__ import annotations

import asyncio
import os
from datetime import datetime, timedelta, timezone

import httpx
import pytest

import human_bot.service as svc
from human_bot import agent, daily_limits, data_sync, failure_tickets, network_check, schedule_store, telegram_failures, telegram_notify
from human_bot.actions import ActionResult
from human_bot.agent import TaskRequest
from human_bot.config import AccountStatus
from human_bot.runtime_config import add_telegram_recipient, set_account_paused
from human_bot.scheduling_config import SchedulingConfig
from tests.test_telegram_failures import _failed_task, _ticket_for, env  # noqa: F401  (fixtures/helpers)

ACC = "tu_iizuki"


# --- a failed attempt becomes a card ---------------------------------------------------------------------------

class _Session:
    def __init__(self):
        self.page = object()  # a page exists → the evidence screenshot is taken
        self.lock = asyncio.Lock()
        self.identity_dirty = False

    async def ensure_started(self): pass
    def is_alive(self): return True
    async def save_state(self): pass


@pytest.fixture
def attempt(monkeypatch, isolated_runtime_config, isolated_accounts_dir, isolated_db):
    sent = []

    async def fake_send_ticket(text, keyboard=None, *, photo_path=None, silent=True):
        sent.append({"text": text, "keyboard": keyboard, "photo": photo_path, "silent": silent})
        return [{"chat_id": "111", "message_id": 5, "photo": bool(photo_path)}]

    async def noop(*a, **k):
        return None

    async def fake_capture(*a, **k):
        return "/tmp/shot.png"

    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(agent.telegram_notify, "send_ticket", fake_send_ticket)
    monkeypatch.setattr(agent.telegram_notify, "send_message", noop)
    monkeypatch.setattr(agent.telegram_notify, "send_photo", noop)
    monkeypatch.setattr(agent.screenshots, "capture", fake_capture)
    monkeypatch.setattr(agent, "get_session", lambda account: _Session())
    monkeypatch.setattr(daily_limits, "can_proceed", lambda account, bucket, ignore_gap=False: (True, ""))

    def set_result(success, message=""):
        async def fn(page, req):
            return ActionResult(success=success, message=message)
        monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", fn))

    return sent, set_result


async def test_a_failed_attempt_sends_one_silent_card_with_buttons_and_the_screenshot(attempt):
    sent, set_result = attempt
    set_result(False, "error:Page.goto: Timeout 30000ms exceeded.")
    await agent.run_task(TaskRequest(
        action="post_to_group", account_id=ACC, target_url="https://facebook.com/groups/1", content="Nội dung",
        scheduled_task_id="TASK1", retries=1, source_kind="job", job_data={"title": "Thợ hàn", "attributes": {}},
    ))
    [card] = sent
    assert card["silent"] is True and card["photo"] == "/tmp/shot.png" and card["keyboard"]
    assert "Facebook tải quá chậm" in card["text"] and "lần thử 2" in card["text"] and 'Tin: "Thợ hàn"' in card["text"]
    [ticket] = failure_tickets.list_open()
    assert ticket["task_id"] == "TASK1" and ticket["retries"] == 1 and isinstance(ticket["log_id"], int)
    assert ticket["messages"] == [{"chat_id": "111", "message_id": 5, "photo": True}]      # remembered for replies/edits


async def test_a_successful_attempt_still_sends_the_plain_report_and_no_ticket(attempt, monkeypatch):
    sent, set_result = attempt
    set_result(True, "posted_to_group")
    plain = []

    async def fake_photo(path, caption="", *, silent=False):
        plain.append(caption)

    monkeypatch.setattr(agent.telegram_notify, "send_photo", fake_photo)
    await agent.run_task(TaskRequest(action="post_to_group", account_id=ACC, target_url="u", content="c"))
    assert sent == [] and failure_tickets.list_open() == [] and plain and "✅" in plain[0]


async def test_early_refusals_and_an_unconfigured_bot_create_no_ticket(attempt, monkeypatch, isolated_accounts_dir):
    sent, set_result = attempt
    set_result(False, "boom")
    set_account_paused(ACC, True, reason="x")
    await agent.run_task(TaskRequest(action="post_to_group", account_id=ACC, target_url="u", content="c"))   # refused before Facebook
    assert sent == [] and failure_tickets.list_open() == []
    from human_bot.runtime_config import resume_account
    resume_account(ACC)
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: False)
    await agent.run_task(TaskRequest(action="post_to_group", account_id=ACC, target_url="u", content="c"))
    assert sent == [] and failure_tickets.list_open() == []


async def test_a_card_that_cannot_be_sent_never_fails_the_task(attempt, monkeypatch):
    sent, set_result = attempt
    set_result(False, "boom")

    async def broken(*a, **k):
        raise RuntimeError("telegram exploded")

    monkeypatch.setattr(agent.telegram_notify, "send_ticket", broken)
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id=ACC, target_url="u", content="c"))
    assert result.success is False and result.message == "boom"


# --- the scheduler carries the ids and parks tasks of a paused account ------------------------------------------------

async def test_fire_due_tasks_hands_the_task_id_to_the_attempt_and_parks_paused_accounts(isolated_schedule_dirs, isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    async def online(*a, **k):
        return True

    monkeypatch.setattr(network_check, "wait_for_internet", online)
    monkeypatch.setattr(daily_limits, "hard_cap_message", lambda *a, **k: None)
    seen = []

    async def fake_run_task(request):
        seen.append((request.scheduled_task_id, request.retries))
        from human_bot.agent import TaskResult
        return TaskResult(success=True, message="ok", screenshot_path=None, timestamp="t")

    monkeypatch.setattr("human_bot.agent.run_task", fake_run_task)
    store = isolated_schedule_dirs
    when = datetime.now(timezone.utc) - timedelta(minutes=2)
    task = store.ScheduledTask(
        task_id=store.new_task_id(when.isoformat()), action="post_to_group", account_id=ACC, scheduled_at=when.isoformat(),
        content="x", target_url="https://facebook.com/groups/1", retries=2,
    )
    store.add(task)
    await data_sync.fire_due_tasks(SchedulingConfig(auto_fire_enabled=True))
    assert seen == [(task.task_id, 2)]
    again = store.ScheduledTask(
        task_id=store.new_task_id(when.isoformat()), action="post_to_group", account_id=ACC, scheduled_at=when.isoformat(),
        content="y", target_url="https://facebook.com/groups/1",
    )
    store.add(again)
    set_account_paused(ACC, True, reason="checkpoint")
    await data_sync.fire_due_tasks(SchedulingConfig(auto_fire_enabled=True))
    assert len(seen) == 1                                                       # nothing ran for the paused account
    assert [t.task_id for t in store.list_missed()] == [again.task_id] and "tạm dừng" in store.get_missed_reason(again.task_id)
    assert not list(store.FAILED_DIR.glob("*.json"))                            # parked for review, NOT silently failed


# --- telegram_notify ---------------------------------------------------------------------------------------------------

_RealClient = httpx.AsyncClient


def _mock_client(monkeypatch, handler):
    monkeypatch.setattr(httpx, "AsyncClient", lambda timeout=None: _RealClient(transport=httpx.MockTransport(handler)))


async def test_send_ticket_to_sends_a_photo_with_a_caption_and_the_keyboard(monkeypatch, isolated_runtime_config, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    shot = tmp_path / "s.png"
    shot.write_bytes(b"png")
    seen = {}

    def handler(request):
        seen["url"], seen["body"] = str(request.url), request.content
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 42}})

    _mock_client(monkeypatch, handler)
    kb = [[{"text": "a", "callback_data": "b"}]]
    ref = await telegram_notify.send_ticket_to("111", "caption " * 300, kb, photo_path=str(shot))
    assert ref == {"chat_id": "111", "message_id": 42, "photo": True}
    assert seen["url"].endswith("/sendPhoto") and b"inline_keyboard" in seen["body"] and b'name="caption"' in seen["body"]


async def test_send_ticket_to_falls_back_to_text_when_the_photo_is_missing_or_rejected(monkeypatch, isolated_runtime_config, tmp_path):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    calls = []

    def handler(request):
        calls.append(str(request.url).rsplit("/", 1)[-1])
        if calls[-1] == "sendPhoto":
            return httpx.Response(400, json={"ok": False})
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 7}})

    _mock_client(monkeypatch, handler)
    assert (await telegram_notify.send_ticket_to("1", "hi", None, photo_path="/no/such/file.png"))["photo"] is False
    shot = tmp_path / "s.png"
    shot.write_bytes(b"png")
    ref = await telegram_notify.send_ticket_to("1", "hi", [[{"text": "a", "callback_data": "b"}]], photo_path=str(shot))
    assert ref == {"chat_id": "1", "message_id": 7, "photo": False} and calls == ["sendMessage", "sendPhoto", "sendMessage"]


async def test_send_ticket_reaches_every_recipient_and_skips_a_failing_one(monkeypatch, isolated_runtime_config):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    add_telegram_recipient("1", "A")
    add_telegram_recipient("2", "B")
    import json as _json

    def handler(request):
        chat = _json.loads(request.content)["chat_id"]
        return httpx.Response(200, json={"ok": True, "result": {"message_id": 10}}) if chat == "1" else httpx.Response(403, json={"ok": False})

    _mock_client(monkeypatch, handler)
    refs = await telegram_notify.send_ticket("hello", [[{"text": "a", "callback_data": "b"}]])
    assert refs == [{"chat_id": "1", "message_id": 10, "photo": False}]


async def test_editing_a_photo_message_uses_the_caption_method(monkeypatch, isolated_runtime_config):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "t")
    import json as _json
    calls = []

    def handler(request):
        calls.append((str(request.url).rsplit("/", 1)[-1], _json.loads(request.content)))
        return httpx.Response(200, json={"ok": True, "result": True})

    _mock_client(monkeypatch, handler)
    await telegram_notify.edit_message("1", 5, text="new" * 500, keyboard=[], photo=True)
    await telegram_notify.edit_message("1", 5, text="new", keyboard=[], photo=False)
    await telegram_notify.edit_message("1", 5, keyboard=[], photo=True)                 # keyboard only works for both kinds
    assert [c[0] for c in calls] == ["editMessageCaption", "editMessageText", "editMessageReplyMarkup"]
    assert len(calls[0][1]["caption"]) == 1024 and "text" not in calls[0][1]


# --- listen loop ----------------------------------------------------------------------------------------------------------

def _update(update_id, **message):
    base = {"chat": {"id": "12345", "type": "private"}}
    base.update(message)
    return {"update_id": update_id, "message": base}


async def _run_batch(monkeypatch, updates):
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    sent = []

    async def to(chat_id, text, *, silent=False):
        sent.append(text)
        return True

    monkeypatch.setattr(telegram_notify, "send_message_to", to)

    async def fake_updates(offset, **k):
        if offset is None:
            return updates
        raise asyncio.CancelledError

    monkeypatch.setattr(telegram_notify, "get_updates", fake_updates)

    async def no_sleep(s):
        pass

    monkeypatch.setattr(svc.asyncio, "sleep", no_sleep)
    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()
    return sent


async def test_replying_to_a_failure_card_requeues_with_the_new_text_and_refreshes_the_copies(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    task = _failed_task()
    t = _ticket_for(task)
    failure_tickets.add_message(t["id"], "12345", 50, photo=True)
    failure_tickets.add_message(t["id"], "99999", 60)                                    # another recipient's copy
    edits = []

    async def edit(chat_id, message_id, *, text=None, keyboard=None, photo=False):
        edits.append((chat_id, message_id, photo, "với nội dung mới" in (text or "")))
        return True

    buttons = []

    async def with_buttons(chat_id, text, keyboard, *, silent=True):
        buttons.append((text, keyboard))
        return True

    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    monkeypatch.setattr(telegram_notify, "send_message_with_buttons", with_buttons)
    sent = await _run_batch(monkeypatch, [_update(1, text="Bài sửa lại", reply_to_message={"message_id": 50})])
    assert schedule_store.get(task.task_id).content == "Bài sửa lại" and schedule_store.get(task.task_id).ai_redraft is False
    assert sent == [] and len(buttons) == 1 and "“Bài sửa lại”" in buttons[0][0] and "fx|ud|" in buttons[0][1][0][0]["callback_data"]
    assert ("12345", 50, True, True) in edits and ("99999", 60, False, True) in edits   # both copies show the new state; photo flag respected


async def test_a_reply_to_something_else_falls_through_to_the_normal_handling(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    sent = await _run_batch(monkeypatch, [_update(1, text="hello", reply_to_message={"message_id": 777})])
    assert len(sent) == 1 and "/lich" in sent[0]                                          # the usual /help answer


async def test_a_reply_from_a_group_chat_is_not_treated_as_an_edit(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    task = _failed_task()
    t = _ticket_for(task)
    failure_tickets.add_message(t["id"], "12345", 50)
    update = {"update_id": 1, "message": {"chat": {"id": "12345", "type": "group"}, "text": "x", "reply_to_message": {"message_id": 50}}}
    await _run_batch(monkeypatch, [update])
    assert schedule_store.get(task.task_id) is None


async def test_loi_sends_one_card_per_failure_and_remembers_each_message(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    _failed_task(age_hours=1)
    _failed_task("post_button_still_visible_after_click", age_hours=2)
    cards = []

    async def send_ticket_to(chat_id, text, keyboard=None, *, photo_path=None, silent=True):
        cards.append((text, keyboard))
        return {"chat_id": chat_id, "message_id": 100 + len(cards), "photo": False}

    monkeypatch.setattr(telegram_notify, "send_ticket_to", send_ticket_to)
    await _run_batch(monkeypatch, [_update(1, text="/loi")])
    assert len(cards) == 2 and all(k for _t, k in cards)
    assert failure_tickets.find_by_message("12345", 101) is not None and failure_tickets.find_by_message("12345", 102) is not None


async def test_loi_with_nothing_to_do_says_so(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    sent = await _run_batch(monkeypatch, [_update(1, text="/loi")])
    assert sent == ["✅ Không có lỗi nào đang chờ xử lý trong 48 giờ qua."]


async def test_loi_is_listed_in_the_menu_and_refused_in_a_group(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    from human_bot import telegram_commands
    assert "loi" in [c for c, _d in telegram_commands.COMMANDS] and "/loi" in telegram_commands.help_text()
    add_telegram_recipient("12345", "Tu")
    group = {"update_id": 1, "message": {"chat": {"id": "12345", "type": "group"}, "text": "/loi"}}
    sent = await _run_batch(monkeypatch, [group])
    assert sent == ["Các nút thao tác chỉ dùng được trong chat riêng với bot."]


async def test_pressing_a_button_on_a_photo_card_edits_the_caption_and_syncs_the_other_copy(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    task = _failed_task()
    t = _ticket_for(task)
    failure_tickets.add_message(t["id"], "12345", 50, photo=True)
    failure_tickets.add_message(t["id"], "99999", 60)
    edits, answers = [], []

    async def edit(chat_id, message_id, *, text=None, keyboard=None, photo=False):
        edits.append((chat_id, message_id, photo, text))
        return True

    async def answer(callback_id, text="", *, alert=False):
        answers.append((text, alert))
        return True

    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    monkeypatch.setattr(telegram_notify, "answer_callback_query", answer)
    update = {"update_id": 1, "callback_query": {
        "id": "cb", "from": {"id": "12345", "first_name": "Tu"}, "data": f"fx|rs|{t['id']}",
        "message": {"message_id": 50, "chat": {"id": "12345"}, "photo": [{"file_id": "x"}], "caption": "old caption"},
    }}
    await _run_batch(monkeypatch, [update])
    assert answers == [("Đã lên lịch lại", False)]
    clicked = [e for e in edits if e[:2] == ("12345", 50)]
    assert clicked and clicked[0][2] is True and "Đã lên lịch lại" in clicked[0][3]          # caption edit on the photo message
    other = [e for e in edits if e[:2] == ("99999", 60)]
    assert other and other[0][2] is False and "Đã lên lịch lại" in other[0][3]               # the other recipient's copy refreshed
    assert len([e for e in edits if e[:2] == ("12345", 50)]) == 1                           # the clicked one is not edited twice


async def test_a_refusal_is_shown_as_a_popup_that_stays(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    t = _ticket_for(_failed_task("target_content_unavailable"))
    failure_tickets.add_message(t["id"], "12345", 50)
    answers = []

    async def answer(callback_id, text="", *, alert=False):
        answers.append(alert)
        return True

    async def edit(*a, **k):
        return True

    monkeypatch.setattr(telegram_notify, "answer_callback_query", answer)
    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    update = {"update_id": 1, "callback_query": {"id": "cb", "from": {"id": "12345"}, "data": f"fx|rs|{t['id']}",
              "message": {"message_id": 50, "chat": {"id": "12345"}, "text": "card"}}}
    await _run_batch(monkeypatch, [update])
    assert answers == [True]


async def test_a_card_that_cannot_be_built_falls_back_to_the_plain_report(attempt, monkeypatch):
    sent, set_result = attempt
    set_result(False, "error:Page.goto: Timeout 30000ms exceeded.")
    plain = []

    async def fake_photo(path, caption="", *, silent=False):
        plain.append(caption)

    monkeypatch.setattr(agent.telegram_notify, "send_photo", fake_photo)

    def boom(**kw):
        raise RuntimeError("data_sync_cache is read-only")

    monkeypatch.setattr(failure_tickets, "create", boom)
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id=ACC, target_url="u", content="c"))
    assert result.success is False and sent == []
    assert plain and "❌" in plain[0] and "Timeout 30000ms" in plain[0]          # the failure still reaches the owner


async def test_a_card_nobody_received_falls_back_to_the_plain_report(attempt, monkeypatch):
    sent, set_result = attempt
    set_result(False, "error:Page.goto: Timeout 30000ms exceeded.")
    plain = []

    async def nobody(text, keyboard=None, *, photo_path=None, silent=True):
        return []                                                                      # every recipient's send failed

    async def fake_photo(path, caption="", *, silent=False):
        plain.append(caption)

    monkeypatch.setattr(agent.telegram_notify, "send_ticket", nobody)
    monkeypatch.setattr(agent.telegram_notify, "send_photo", fake_photo)
    await agent.run_task(TaskRequest(action="post_to_group", account_id=ACC, target_url="u", content="c"))
    assert plain and "❌" in plain[0]


async def test_the_ticket_carries_media_and_audience_from_the_request(attempt, monkeypatch):
    sent, _set_result = attempt

    async def fails(page, req):
        return ActionResult(success=False, message="error:Page.goto: Timeout 30000ms exceeded.")

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_own_profile", ("post", fails))
    await agent.run_task(TaskRequest(
        action="post_to_own_profile", account_id=ACC, content="c", media_path="/media/memes/m.png", audience="friends",
    ))
    [ticket] = failure_tickets.list_open()
    assert ticket["media_path"] == "/media/memes/m.png" and ticket["audience"] == "friends"
