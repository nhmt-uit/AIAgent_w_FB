"""How the phase-2 pieces are wired in (2026-11-01): a burst of failed attempts becomes
one group card, the group card / streak alert buttons through the Telegram listen loop,
the /error summary card, and the old Vietnamese command names."""
from __future__ import annotations

import pytest

import human_bot.service as svc
from human_bot import agent, failure_tickets, schedule_store, telegram_batches, telegram_notify, telegram_streaks
from human_bot.agent import TaskRequest
from human_bot.runtime_config import add_telegram_recipient
from tests.test_telegram_failures import _failed_task, _ticket_for, env, later_slot  # noqa: F401  (fixtures/helpers)
from tests.test_telegram_failures_wiring import _run_batch, _update, attempt  # noqa: F401  (fixtures/helpers)

ACC = "tu_iizuki"
SLOW = "error:Page.goto: Timeout 30000ms exceeded."


def _single_cards(sent):
    """The per-failure cards (silent); the loud streak alert is a different message."""
    return [x for x in sent if x["silent"] is True and x["text"].startswith("❌")]


async def _fail_once(attempt, n, message=SLOW):
    sent, set_result = attempt
    set_result(False, message)
    await agent.run_task(TaskRequest(
        action="post_to_group", account_id=ACC, target_url=f"https://facebook.com/groups/{n}", content=f"Bài {n}",
        scheduled_task_id=f"TASK{n}",
    ))
    return sent


# --- a failed attempt: single card -> single card -> ONE group card ---------------------------------------------

async def test_the_third_failure_of_one_cause_becomes_a_group_card_and_later_ones_edit_it(attempt, monkeypatch):
    edits = []

    async def edit(chat_id, message_id, *, text=None, keyboard=None, photo=False):
        edits.append((chat_id, message_id, text, photo))
        return True

    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    sent = await _fail_once(attempt, 1)
    await _fail_once(attempt, 2)
    assert [s["photo"] for s in sent] == ["/tmp/shot.png", "/tmp/shot.png"]                   # two ordinary cards with their screenshot
    await _fail_once(attempt, 3)
    group = [s for s in sent if s["text"].startswith("⚠️ 3 lỗi cùng nguyên nhân")]
    assert len(group) == 1 and group[0]["photo"] is None and group[0]["silent"] is True
    assert any(b["callback_data"].startswith("fb|ra|") for row in group[0]["keyboard"] for b in row)
    cards_before = len(_single_cards(sent))
    sends_before = len(sent)
    await _fail_once(attempt, 4)
    assert len(sent) == sends_before and len(_single_cards(sent)) == cards_before                             # nothing new is sent for the 4th
    assert edits and "4 lỗi cùng nguyên nhân" in edits[-1][2] and edits[-1][3] is False                       # the group card was edited in place
    [burst] = failure_tickets.list_open(kind=failure_tickets.BATCH)
    assert len(burst["members"]) == 4 and burst["messages"] == [{"chat_id": "111", "message_id": 5, "photo": False}]


async def test_failures_of_different_causes_each_keep_their_own_card(attempt):
    sent = await _fail_once(attempt, 1)
    await _fail_once(attempt, 2, "error:Page.goto: net::ERR_INTERNET_DISCONNECTED at https://www.facebook.com/")
    await _fail_once(attempt, 3, "target_content_unavailable")
    await _fail_once(attempt, 4)
    assert len(_single_cards(sent)) == 4 and failure_tickets.list_open(kind=failure_tickets.BATCH) == []


async def test_a_group_card_nobody_received_gives_the_failure_a_card_of_its_own(attempt, monkeypatch):
    async def nobody(batch, is_new):
        return False

    monkeypatch.setattr(telegram_batches, "announce", nobody)
    sent = await _fail_once(attempt, 1)
    await _fail_once(attempt, 2)
    await _fail_once(attempt, 3)
    assert len(_single_cards(sent)) == 3


async def test_grouping_that_breaks_never_costs_a_failure_its_card(attempt, monkeypatch):
    def broken(ticket):
        raise RuntimeError("store unreadable")

    monkeypatch.setattr(telegram_batches, "attach", broken)
    sent = await _fail_once(attempt, 1)
    await _fail_once(attempt, 2)
    await _fail_once(attempt, 3)
    assert len(_single_cards(sent)) == 3


async def test_the_streak_alert_is_a_loud_card_with_buttons(attempt):
    sent = await _fail_once(attempt, 1, "something else entirely")
    await _fail_once(attempt, 2, "something else entirely")
    await _fail_once(attempt, 3, "something else entirely")
    loud = [s for s in sent if s["silent"] is False]
    assert len(loud) == 1 and "thất bại 3 lần LIÊN TIẾP" in loud[0]["text"]
    assert [b["callback_data"].split("|")[1] for row in loud[0]["keyboard"] for b in row] == ["off", "ps", "ok", "sn1", "snm"]
    [alert] = failure_tickets.list_open(kind=failure_tickets.STREAK)
    assert alert["account_id"] == ACC and alert["messages"]


# --- button presses through the listen loop ---------------------------------------------------------------------------

def _callback(data, message_id=50, chat="12345", text="card text"):
    return {"update_id": 1, "callback_query": {
        "id": "cb", "from": {"id": chat, "first_name": "Tu"}, "data": data,
        "message": {"message_id": message_id, "chat": {"id": chat}, "text": text},
    }}


async def test_a_group_card_press_refreshes_the_members_cards_in_every_chat(env, later_slot, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    members = [_ticket_for(_failed_task(age_hours=0.05)) for _ in range(3)]
    batch = failure_tickets.create(kind="batch", scope="list", category=None, members=[m["id"] for m in members], last_resched=None, last_dismiss=None)
    failure_tickets.add_message(batch["id"], "12345", 50)
    failure_tickets.add_message(members[0]["id"], "12345", 61, photo=True)
    failure_tickets.add_message(members[0]["id"], "99999", 71)
    edits, answers = [], []

    async def edit(chat_id, message_id, *, text=None, keyboard=None, photo=False):
        edits.append((chat_id, message_id, photo, text))
        return True

    async def answer(callback_id, text="", *, alert=False):
        answers.append((text, alert))
        return True

    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    monkeypatch.setattr(telegram_notify, "answer_callback_query", answer)
    await _run_batch(monkeypatch, [_callback(f"fb|ra|{batch['id']}")])
    assert answers == [("Đã lên lịch lại 3 lỗi", False)] and len(schedule_store.list_pending()) == 3
    clicked = [e for e in edits if e[:2] == ("12345", 50)]
    assert len(clicked) == 1 and "Đã lên lịch lại 3 lỗi" in clicked[0][3]
    mine = [e for e in edits if e[:2] == ("12345", 61)]
    theirs = [e for e in edits if e[:2] == ("99999", 71)]
    assert mine and mine[0][2] is True and "Đã lên lịch lại" in mine[0][3]                  # the member's own photo card, caption edited
    assert theirs and theirs[0][2] is False and "Đã lên lịch lại" in theirs[0][3]            # another recipient's copy too


async def test_a_streak_alert_press_switches_the_account_off_and_closes_its_idle_browser(isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    from human_bot.config import AccountStatus, get_all_accounts
    add_telegram_recipient("12345", "Tu")
    alert = telegram_streaks.create_ticket(ACC, "post_to_group", 3, SLOW)
    closed, edits = [], []

    async def close(account_id):
        closed.append(account_id)
        return True

    async def edit(chat_id, message_id, *, text=None, keyboard=None, photo=False):
        edits.append((text, keyboard))
        return True

    async def answer(*a, **k):
        return True

    monkeypatch.setattr(svc, "close_idle_session", close)
    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    monkeypatch.setattr(telegram_notify, "answer_callback_query", answer)
    await _run_batch(monkeypatch, [_callback(f"fa|off|{alert['id']}")])
    assert get_all_accounts()[ACC].status == AccountStatus.DISABLED and closed == [ACC]
    assert "TẮT" in edits[0][0] and edits[0][1][0][0]["callback_data"] == f"fa|on|{alert['id']}"


async def test_a_browser_that_will_not_close_does_not_fail_the_switch_off(isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    from human_bot.config import AccountStatus, get_all_accounts
    add_telegram_recipient("12345", "Tu")
    alert = telegram_streaks.create_ticket(ACC, "post_to_group", 3, SLOW)

    async def close(account_id):
        raise RuntimeError("chrome hung")

    async def edit(*a, **k):
        return True

    async def answer(*a, **k):
        return True

    monkeypatch.setattr(svc, "close_idle_session", close)
    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    monkeypatch.setattr(telegram_notify, "answer_callback_query", answer)
    await _run_batch(monkeypatch, [_callback(f"fa|off|{alert['id']}")])
    assert get_all_accounts()[ACC].status == AccountStatus.DISABLED


# --- /error opens with the summary card ----------------------------------------------------------------------------------

async def _error_cards(monkeypatch):
    cards = []

    async def send_ticket_to(chat_id, text, keyboard=None, *, photo_path=None, silent=True):
        cards.append((text, keyboard))
        return {"chat_id": chat_id, "message_id": 100 + len(cards), "photo": False}

    monkeypatch.setattr(telegram_notify, "send_ticket_to", send_ticket_to)
    await _run_batch(monkeypatch, [_update(1, text="/error")])
    return cards


async def test_error_opens_with_a_reschedule_all_card_when_several_safe_failures_wait(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    for hours in (1, 2, 3):
        _failed_task(age_hours=hours)
    cards = await _error_cards(monkeypatch)
    assert len(cards) == 4 and cards[0][0].startswith("📋 3 lỗi an toàn") and cards[1][0].startswith("❌")
    assert cards[0][1][0][0]["callback_data"].startswith("fb|ra|")
    [batch] = failure_tickets.list_open(kind=failure_tickets.BATCH)
    assert failure_tickets.find_by_message("12345", 101)["id"] == batch["id"]                  # the card is remembered for later refreshes
    assert failure_tickets.find_by_message("12345", 102)["kind"] == "failure"


async def test_error_with_only_a_couple_of_failures_shows_just_their_cards(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    _failed_task(age_hours=1); _failed_task(age_hours=2)
    cards = await _error_cards(monkeypatch)
    assert len(cards) == 2 and all(c[0].startswith("❌") for c in cards) and failure_tickets.list_open(kind=failure_tickets.BATCH) == []


async def test_the_open_failure_count_ignores_group_cards_and_alerts(env, isolated_runtime_config):  # noqa: F811
    from human_bot import telegram_failures
    _failed_task(age_hours=1)
    failure_tickets.create(kind="batch", scope="list", members=[], last_resched=None, last_dismiss=None)
    failure_tickets.create(kind="streak", account_id=ACC, streak=3, message="x")
    assert telegram_failures.open_failure_count() == 1


# --- the old Vietnamese names -----------------------------------------------------------------------------------------------------

async def test_the_old_vietnamese_commands_still_answer(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    sent = await _run_batch(monkeypatch, [_update(1, text="/loi")])
    assert sent == ["✅ Không có lỗi nào đang chờ xử lý trong 48 giờ qua."]


async def test_the_bot_menu_registers_the_english_names(monkeypatch):
    from human_bot import telegram_commands
    registered = []

    async def fake_set(commands):
        registered.append([c for c, _d in commands])
        return True

    monkeypatch.setattr(telegram_notify, "set_my_commands", fake_set)
    await telegram_notify.set_my_commands(telegram_commands.COMMANDS)
    assert registered == [["schedule", "report", "health", "error", "overdue", "review", "pause", "resume", "help"]]


# --- review fixes (2026-11-01) ------------------------------------------------------------------------------------------------

async def test_a_failure_card_that_was_delivered_but_not_remembered_is_not_reported_twice(attempt, monkeypatch):
    plain = []

    async def spy(*a, **k):
        plain.append(a)

    def broken(*a, **k):
        raise OSError("disk full")

    monkeypatch.setattr(agent.telegram_notify, "send_message", spy)
    monkeypatch.setattr(agent.telegram_notify, "send_photo", spy)
    monkeypatch.setattr(failure_tickets, "add_message", broken)
    sent = await _fail_once(attempt, 1)
    assert len(sent) == 1 and plain == []                                              # delivered once; no duplicate plain report


async def test_a_group_card_that_was_delivered_but_not_remembered_is_not_reported_twice(attempt, monkeypatch):
    plain = []

    async def spy(*a, **k):
        plain.append(a)

    monkeypatch.setattr(agent.telegram_notify, "send_message", spy)
    monkeypatch.setattr(agent.telegram_notify, "send_photo", spy)
    await _fail_once(attempt, 1)
    await _fail_once(attempt, 2)
    monkeypatch.setattr(failure_tickets, "add_message", lambda *a, **k: (_ for _ in ()).throw(OSError("disk full")))
    sent = await _fail_once(attempt, 3)
    assert any(s["text"].startswith("⚠️ 3 lỗi") for s in sent) and plain == []


async def test_error_scans_the_failed_tasks_once_and_drops_a_summary_card_nobody_received(env, monkeypatch, isolated_runtime_config):  # noqa: F811
    from human_bot import telegram_failures
    add_telegram_recipient("12345", "Tu")
    for hours in (1, 2, 3):
        _failed_task(age_hours=hours)
    scans = []
    real = telegram_failures.open_failures
    monkeypatch.setattr(telegram_failures, "open_failures", lambda *a, **k: (scans.append(1), real(*a, **k))[1])

    async def send_ticket_to(chat_id, text, keyboard=None, *, photo_path=None, silent=True):
        return None if text.startswith("📋") else {"chat_id": chat_id, "message_id": 100, "photo": False}

    monkeypatch.setattr(telegram_notify, "send_ticket_to", send_ticket_to)
    await _run_batch(monkeypatch, [_update(1, text="/error")])
    assert scans == [1]                                                               # one scan for the single cards AND the summary
    assert failure_tickets.list_open(kind=failure_tickets.BATCH) == []                # the card that reached nobody was removed again


async def test_handling_a_member_through_the_listen_loop_refreshes_the_group_card_too(env, later_slot, monkeypatch, isolated_runtime_config):  # noqa: F811
    add_telegram_recipient("12345", "Tu")
    members = [_ticket_for(_failed_task(age_hours=0.05)) for _ in range(3)]
    batch = failure_tickets.create(kind="batch", scope="list", category=None, members=[m["id"] for m in members], last_resched=None, last_dismiss=None)
    failure_tickets.add_message(batch["id"], "12345", 50)
    failure_tickets.add_message(members[0]["id"], "12345", 61)
    edits = []

    async def edit(chat_id, message_id, *, text=None, keyboard=None, photo=False):
        edits.append((chat_id, message_id, text))
        return True

    async def answer(*a, **k):
        return True

    monkeypatch.setattr(telegram_notify, "edit_message", edit)
    monkeypatch.setattr(telegram_notify, "answer_callback_query", answer)
    await _run_batch(monkeypatch, [_callback(f"fx|rs|{members[0]['id']}", message_id=61)])
    group = [e for e in edits if e[:2] == ("12345", 50)]
    assert len(group) == 1 and "Còn chờ: 2 · đã lên lịch lại: 1" in group[0][2]       # the group card now counts the member
    assert len([e for e in edits if e[:2] == ("12345", 61)]) == 1                     # and the clicked message is edited once


# --- phase 3: "this group keeps failing" and muting ---------------------------------------------------------------------------

GROUP_A, GROUP_B = "https://facebook.com/groups/111", "https://facebook.com/groups/222"
UI_FAIL = 'error:Locator.wait_for: Timeout 30000ms exceeded.\nCall log:\n  - waiting for get_by_role("dialog")'


async def _post(attempt, target, ok, message="", n=[0]):  # noqa: B006 — a counter for unique task ids
    sent, set_result = attempt
    set_result(ok, message)
    n[0] += 1
    await agent.run_task(TaskRequest(action="post_to_group", account_id=ACC, target_url=target, content=f"Bài {n[0]}", scheduled_task_id=f"G{n[0]}"))
    return sent


def _alerts(sent, mark):
    return [s for s in sent if s["silent"] is False and s["text"].startswith(mark)]


async def test_a_group_that_keeps_failing_gets_one_loud_card_while_the_account_is_fine_elsewhere(attempt):
    sent = None
    for target, ok in ((GROUP_A, False), (GROUP_B, True), (GROUP_A, False), (GROUP_B, True)):
        sent = await _post(attempt, target, ok, "" if ok else UI_FAIL)
    assert _alerts(sent, "🟠") == []                                                 # two failures of the group so far
    sent = await _post(attempt, GROUP_A, False, UI_FAIL)
    [card] = _alerts(sent, "🟠")
    assert "lỗi 3 lần liên tiếp" in card["text"] and "/admin/groups" in card["text"]
    assert [b["callback_data"].split("|")[1] for row in card["keyboard"] for b in row] == ["ok", "sn1", "snm"]
    assert _alerts(sent, "🔴") == []                                                 # the account itself is not failing in a row
    sent = await _post(attempt, GROUP_B, True)
    sent = await _post(attempt, GROUP_A, False, UI_FAIL)
    assert len(_alerts(sent, "🟠")) == 1                                             # exactly once, not on every later failure
    [ticket] = [t for t in failure_tickets.list_open(kind=failure_tickets.STREAK) if t.get("scope") == "group"]
    assert ticket["target_url"] == GROUP_A and ticket["messages"]


async def test_failures_that_say_nothing_about_the_group_do_not_make_it_look_bad(attempt):
    slow = "error:Page.goto: Timeout 30000ms exceeded."
    sent = None
    for target, ok in ((GROUP_A, False), (GROUP_B, True), (GROUP_A, False), (GROUP_B, True), (GROUP_A, False)):
        sent = await _post(attempt, target, ok, "" if ok else slow)
    assert _alerts(sent, "🟠") == [] and _alerts(sent, "🔴") == []


async def test_when_the_account_alert_fires_the_group_alert_stays_quiet(attempt):
    sent = None
    for _ in range(3):
        sent = await _post(attempt, GROUP_A, False, UI_FAIL)                         # 3 in a row for the account AND for the group
    assert len(_alerts(sent, "🔴")) == 1 and _alerts(sent, "🟠") == []
    assert "Nhóm gần nhất:" in _alerts(sent, "🔴")[0]["text"]                        # ...so the one alert says which group it was


async def test_a_muted_group_stays_quiet_and_alerts_again_when_the_time_is_up(attempt):
    from datetime import datetime, timedelta, timezone
    from human_bot import telegram_streaks
    telegram_streaks.snooze(telegram_streaks.group_key(ACC, GROUP_A), datetime.now(timezone.utc) + timedelta(hours=1))
    sent = None
    for target, ok in ((GROUP_A, False), (GROUP_B, True), (GROUP_A, False), (GROUP_B, True), (GROUP_A, False)):
        sent = await _post(attempt, target, ok, "" if ok else UI_FAIL)
    assert _alerts(sent, "🟠") == []                                                 # muted
    [record] = failure_tickets.list_open(kind=telegram_streaks.SNOOZE)
    failure_tickets.update(record["id"], until=(datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat())   # the hour is up
    sent = await _post(attempt, GROUP_B, True)
    sent = await _post(attempt, GROUP_A, False, UI_FAIL)
    assert len(_alerts(sent, "🟠")) == 1                                             # still failing → told again
    assert failure_tickets.list_open(kind=telegram_streaks.SNOOZE) == []


async def test_a_network_failure_after_the_group_alert_does_not_send_it_again(attempt):
    sent = None
    for target, ok in ((GROUP_A, False), (GROUP_B, True), (GROUP_A, False), (GROUP_B, True), (GROUP_A, False)):
        sent = await _post(attempt, target, ok, "" if ok else UI_FAIL)
    assert len(_alerts(sent, "🟠")) == 1
    for _ in range(3):                                                                # the network drops: each failure leaves the group's streak at 3
        sent = await _post(attempt, GROUP_A, False, "error:Page.goto: net::ERR_INTERNET_DISCONNECTED at x")
    assert len(_alerts(sent, "🟠")) == 1


async def test_a_comment_failure_alert_does_not_pretend_a_post_url_is_a_group(attempt, monkeypatch):
    sent, set_result = attempt

    async def fail(page, req):
        from human_bot.actions import ActionResult
        return ActionResult(success=False, message=UI_FAIL)

    monkeypatch.setitem(agent._ACTION_DISPATCH, "comment_on_group_post", ("comment", fail))
    for i in range(3):
        await agent.run_task(TaskRequest(action="comment_on_group_post", account_id=ACC, target_url="https://facebook.com/groups/1/posts/456", content="c", scheduled_task_id=f"C{i}"))
    [card] = _alerts(sent, "🔴")
    assert "Nhóm gần nhất" not in card["text"] and "456" not in card["text"]


async def test_a_problem_while_checking_the_alerts_never_breaks_the_task(attempt, monkeypatch):
    from human_bot import telegram_streaks

    def broken(*a, **k):
        raise ValueError("damaged record")

    monkeypatch.setattr(telegram_streaks, "should_alert", broken)
    sent, set_result = attempt
    set_result(False, UI_FAIL)
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id=ACC, target_url=GROUP_A, content="c", scheduled_task_id="X1"))
    assert result.success is False                                                    # the task's own result still comes back
