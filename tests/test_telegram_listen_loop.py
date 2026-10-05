"""
Regression test (2026-10-05 self-review) for human_bot/service.py's
_telegram_listen_loop(): telegram_notify.get_updates() no-ops instantly
(empty list, no network I/O) whenever Telegram isn't configured/enabled.
An earlier version relied entirely on get_updates()'s own long-poll
timeout for pacing and had no sleep on that path, so the `while True`
loop busy-spun the event loop (pegging a CPU core, re-reading
runtime_config.json every iteration) for as long as the service ran
unconfigured. Fixed by checking is_configured() up front and sleeping
_TELEGRAM_LISTEN_IDLE_SLEEP_SECONDS before retrying.

2026-10-05 follow-up (multi-recipient admin list, replacing the single
TELEGRAM_CHAT_ID env var): "who gets a reply" is now
human_bot/runtime_config.py's get_telegram_recipients() — tests register
via add_telegram_recipient() (needs isolated_runtime_config) instead of
monkeypatch.setenv("TELEGRAM_CHAT_ID", ...); the reply itself is now sent
via telegram_notify.send_message_to(chat_id, ...) (a direct reply to the
asker), not the broadcast send_message().
"""
from __future__ import annotations

import asyncio

import pytest

import human_bot.service as svc
from human_bot import telegram_notify
from human_bot.runtime_config import add_telegram_recipient

# asyncio.CancelledError is a BaseException (not Exception) in Python
# 3.8+, so it passes straight through the loop's own
# `except Exception: ... sleep(5); continue` error handler instead of
# being swallowed by it — the clean way to stop a `while True` loop
# under test from inside a monkeypatched call.


async def test_listen_loop_sleeps_instead_of_busy_spinning_when_not_configured(monkeypatch, isolated_runtime_config):
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: False)
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise asyncio.CancelledError  # stop after exactly 1 iteration, once we've seen it sleep

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert sleep_calls == [svc._TELEGRAM_LISTEN_IDLE_SLEEP_SECONDS]


async def test_listen_loop_does_not_sleep_the_idle_interval_when_configured(monkeypatch):
    """Once configured, pacing comes from get_updates()'s own long-poll
    timeout, not the idle sleep — this loop must go straight to
    get_updates() instead of also sleeping first."""
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)

    async def fake_get_updates(offset, **kwargs):
        raise asyncio.CancelledError  # confirms get_updates() was reached without an idle sleep first

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    async def fail_if_called(seconds):
        raise AssertionError(f"must not idle-sleep when configured (slept {seconds}s)")

    monkeypatch.setattr(svc.asyncio, "sleep", fail_if_called)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()


async def test_listen_loop_sleeps_when_configured_but_get_updates_fails_fast(monkeypatch):
    """Regression test (round 3): a revoked/typo'd token still makes
    is_configured() return True, but every get_updates() call then hits
    a fast network error and returns [] almost instantly (never
    genuinely long-polling) — round 2's fix only covered the literal
    "not configured" case and still busy-spun here. Fixed by timing the
    get_updates() call and idle-sleeping when it returned far faster
    than a real ~30s long-poll ever would."""
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)

    async def fake_get_updates(offset, **kwargs):
        return []  # same shape get_updates() itself returns on a fast network error

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert sleep_calls == [svc._TELEGRAM_LISTEN_IDLE_SLEEP_SECONDS]


async def test_listen_loop_does_not_read_recipients_when_batch_is_empty(monkeypatch, isolated_runtime_config):
    """Regression test (self-review follow-up): an earlier version of
    this multi-recipient change called get_telegram_recipients() (a real
    runtime_config.json read+parse) on EVERY iteration regardless of
    whether there was anything to match against — reintroducing the
    exact "redundant disk read every idle cycle" problem this function's
    own docstring says round 5 already fixed for is_configured(). Must
    skip that read entirely when the batch is empty."""
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    read_calls = {"n": 0}
    real_get_telegram_recipients = svc.get_telegram_recipients

    def counting_get_telegram_recipients():
        read_calls["n"] += 1
        return real_get_telegram_recipients()

    monkeypatch.setattr(svc, "get_telegram_recipients", counting_get_telegram_recipients)

    async def fake_get_updates(offset, **kwargs):
        return []

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    async def fake_sleep(seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert read_calls["n"] == 0


def _update(update_id, chat_id="12345", text="hỏi gì đó"):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": text}}


async def test_listen_loop_does_not_idle_sleep_after_a_fast_real_reply(monkeypatch, isolated_runtime_config):
    """Regression test (round 4): the round-3 elapsed-time guard
    originally fired on ANY fast return, including a real message that
    was already waiting (also returns near-instantly) — throttling
    back-to-back real queries by up to _TELEGRAM_LISTEN_IDLE_SLEEP_SECONDS
    for no reason. Must only trigger when the fast return was EMPTY."""
    add_telegram_recipient("12345", "Test")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(svc, "get_all_accounts", lambda: {})
    monkeypatch.setattr(svc.data_sync, "get_all_sync_statuses", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})
    sent = []

    async def fake_send_message_to(chat_id, text, *, silent=False):
        sent.append((chat_id, text))

    monkeypatch.setattr(telegram_notify, "send_message_to", fake_send_message_to)

    call_count = {"n": 0}

    async def fake_get_updates(offset, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return [_update(1)]  # fast, real message already waiting
        raise asyncio.CancelledError  # 2nd call proves no idle sleep happened in between

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    async def fail_if_called(seconds):
        raise AssertionError(f"must not idle-sleep after a fast REAL reply (slept {seconds}s)")

    monkeypatch.setattr(svc.asyncio, "sleep", fail_if_called)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert len(sent) == 1


async def test_listen_loop_computes_reply_once_per_batch_not_once_per_message(monkeypatch, isolated_runtime_config):
    """Regression test (round 4): 2+ valid messages arriving in the SAME
    get_updates() batch used to rebuild the identical health-snapshot
    reply once per message — wasted DB/file work that scales with how
    many messages a user sends at once. Must compute it once and reuse
    it for every message in the batch."""
    add_telegram_recipient("12345", "Test")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    snapshot_calls = {"n": 0}

    def fake_get_all_accounts():
        snapshot_calls["n"] += 1
        return {}

    monkeypatch.setattr(svc, "get_all_accounts", fake_get_all_accounts)
    monkeypatch.setattr(svc.data_sync, "get_all_sync_statuses", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})
    sent = []

    async def fake_send_message_to(chat_id, text, *, silent=False):
        sent.append((chat_id, text))

    monkeypatch.setattr(telegram_notify, "send_message_to", fake_send_message_to)

    async def fake_get_updates(offset, **kwargs):
        if offset is None:
            return [_update(1), _update(2)]  # 2 valid messages in 1 batch
        raise asyncio.CancelledError

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    async def fail_if_sleep_called(seconds):
        raise AssertionError(f"must not reach the idle sleep in this scenario (slept {seconds}s)")

    monkeypatch.setattr(svc.asyncio, "sleep", fail_if_sleep_called)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert snapshot_calls["n"] == 1  # computed once, reused for both messages
    assert len(sent) == 2  # but each of the 2 messages still gets its own reply


async def test_listen_loop_isolates_a_failed_reply_from_the_rest_of_the_batch(monkeypatch, isolated_runtime_config):
    """Regression test (round 4): offset is advanced before a message's
    reply is built, so if building/sending that FIRST reply raises, the
    exception must not also abort replying to a 2nd, otherwise-valid
    message later in the same batch."""
    add_telegram_recipient("12345", "Test")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    call_n = {"n": 0}

    def fake_get_all_accounts():
        call_n["n"] += 1
        if call_n["n"] == 1:
            raise RuntimeError("boom — simulated DB hiccup building the 1st reply")
        return {}

    monkeypatch.setattr(svc, "get_all_accounts", fake_get_all_accounts)
    monkeypatch.setattr(svc.data_sync, "get_all_sync_statuses", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})
    sent = []

    async def fake_send_message_to(chat_id, text, *, silent=False):
        sent.append((chat_id, text))

    monkeypatch.setattr(telegram_notify, "send_message_to", fake_send_message_to)

    async def fake_get_updates(offset, **kwargs):
        if offset is None:
            return [_update(1), _update(2)]
        raise asyncio.CancelledError

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    async def fail_if_sleep_called(seconds):
        raise AssertionError(f"must not reach the idle sleep in this scenario (slept {seconds}s)")

    monkeypatch.setattr(svc.asyncio, "sleep", fail_if_sleep_called)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    # The 1st message's reply failed, but the 2nd message still got one.
    assert len(sent) == 1


async def test_listen_loop_sleeps_when_a_batch_has_messages_but_none_match_a_registered_chat_id(monkeypatch, isolated_runtime_config):
    """Regression test (round 5): round 4's elapsed-time guard only
    triggered on `not updates` (an EMPTY batch) — a stranger who
    discovered the bot's username sending messages from a DIFFERENT chat
    id keeps `updates` non-empty every poll (their messages are real and
    arrive fast), so the guard never engaged and this loop busy-spun
    calling get_updates() back-to-back with no delay, despite never
    actually replying to anything. Fixed by tracking whether anything
    was actually replied to, not just whether the batch was non-empty."""
    add_telegram_recipient("12345", "Test")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    async def fail_if_send_called(chat_id, text, *, silent=False):
        raise AssertionError("must not reply to a message from an unregistered chat id")

    monkeypatch.setattr(telegram_notify, "send_message_to", fail_if_send_called)

    async def fake_get_updates(offset, **kwargs):
        return [_update(1, chat_id="99999")]  # real message, but from a stranger's chat

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert sleep_calls == [svc._TELEGRAM_LISTEN_IDLE_SLEEP_SECONDS]


async def test_listen_loop_replies_to_a_non_text_message_too(monkeypatch, isolated_runtime_config):
    """Regression test (round 5): the loop's own docstring says it
    replies to "ANY" message (no slash-command needed, owner's "nhắn gì
    cũng được"), but it used to additionally require
    `message.get("text")` to be truthy — silently ignoring a sticker,
    photo, or voice note with no caption, contradicting that design."""
    add_telegram_recipient("12345", "Test")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(svc, "get_all_accounts", lambda: {})
    monkeypatch.setattr(svc.data_sync, "get_all_sync_statuses", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})
    sent = []

    async def fake_send_message_to(chat_id, text, *, silent=False):
        sent.append((chat_id, text))

    monkeypatch.setattr(telegram_notify, "send_message_to", fake_send_message_to)

    async def fake_get_updates(offset, **kwargs):
        if offset is None:
            return [{"update_id": 1, "message": {"chat": {"id": "12345"}, "sticker": {"file_id": "abc"}}}]
        raise asyncio.CancelledError

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert len(sent) == 1


async def test_listen_loop_reply_is_sent_only_to_the_asker_not_broadcast(monkeypatch, isolated_runtime_config):
    """2026-10-05 follow-up (multi-recipient admin list): with 2
    registered recipients, A asking a question must get a DIRECT reply
    (send_message_to(A, ...)) — B must not receive anything just because
    A asked. This is the whole reason send_message_to() exists separate
    from the broadcast send_message()."""
    add_telegram_recipient("111", "A")
    add_telegram_recipient("222", "B")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(svc, "get_all_accounts", lambda: {})
    monkeypatch.setattr(svc.data_sync, "get_all_sync_statuses", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})
    sent_to = []

    async def fake_send_message_to(chat_id, text, *, silent=False):
        sent_to.append(chat_id)

    monkeypatch.setattr(telegram_notify, "send_message_to", fake_send_message_to)

    async def fail_if_broadcast_called(text, *, silent=False):
        raise AssertionError("must not broadcast to every recipient when only 1 person asked")

    monkeypatch.setattr(telegram_notify, "send_message", fail_if_broadcast_called)

    async def fake_get_updates(offset, **kwargs):
        if offset is None:
            return [_update(1, chat_id="111")]  # only A asks
        raise asyncio.CancelledError

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert sent_to == ["111"]


async def test_listen_loop_rereads_recipients_every_cycle_so_a_new_one_works_without_restart(monkeypatch, isolated_runtime_config):
    """The whole point of moving to an admin-managed list: a recipient
    added via /admin while the service is already running must be able
    to query on the VERY NEXT poll cycle — recipients must be reread
    every iteration, not cached once when the loop function started."""
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(svc, "get_all_accounts", lambda: {})
    monkeypatch.setattr(svc.data_sync, "get_all_sync_statuses", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})
    sent_to = []

    async def fake_send_message_to(chat_id, text, *, silent=False):
        sent_to.append(chat_id)

    monkeypatch.setattr(telegram_notify, "send_message_to", fake_send_message_to)

    call_count = {"n": 0}

    async def fake_get_updates(offset, **kwargs):
        call_count["n"] += 1
        if call_count["n"] == 1:
            return []  # nobody registered yet on the 1st poll
        if call_count["n"] == 2:
            # Simulates an admin adding a recipient BETWEEN poll cycles,
            # with no service restart in between.
            add_telegram_recipient("777", "Thêm lúc service đang chạy")
            return [_update(2, chat_id="777")]
        raise asyncio.CancelledError

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    async def fake_sleep(seconds):
        pass  # let the loop keep going through its 3 scripted iterations above

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert sent_to == ["777"]


async def test_listen_loop_records_an_unregistered_sender_as_pending(monkeypatch, isolated_runtime_config):
    """2026-10-05 follow-up (owner: a /admin-only user has no way to know
    TELEGRAM_BOT_TOKEN to hand-build a getUpdates URL): an unregistered
    sender must be recorded via telegram_notify.record_pending_sender()
    so the admin UI can offer a one-click add instead."""
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)

    async def fake_get_updates(offset, **kwargs):
        update = _update(1, chat_id="555")
        update["message"]["from"] = {"first_name": "Bryan", "username": "bryan_ill"}
        return [update]

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    async def fake_sleep(seconds):
        raise asyncio.CancelledError  # stop right after recording the pending sender — no reply was sent, so this loop would otherwise idle-sleep for real

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    pending = telegram_notify.get_pending_senders()
    assert pending["555"]["name"] == "Bryan"


async def test_listen_loop_pending_sender_name_prefers_group_title_over_member_name(monkeypatch, isolated_runtime_config):
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)

    async def fake_get_updates(offset, **kwargs):
        return [{
            "update_id": 1,
            "message": {
                "chat": {"id": "-100123", "title": "Nhóm Telegram team"},
                "from": {"first_name": "Bryan"},
                "text": "hi",
            },
        }]

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    async def fake_sleep(seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    pending = telegram_notify.get_pending_senders()
    assert pending["-100123"]["name"] == "Nhóm Telegram team"


async def test_listen_loop_records_a_channel_post_as_a_pending_sender(monkeypatch, isolated_runtime_config):
    """Regression test (self-review follow-up): a Telegram CHANNEL
    delivers its posts as update["channel_post"], never
    update["message"] — without checking both, a channel the bot was
    added to as admin could never be discovered as a pending sender at
    all, defeating the whole point of this feature for that chat type."""
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)

    async def fake_get_updates(offset, **kwargs):
        return [{
            "update_id": 1,
            "channel_post": {
                "chat": {"id": "-100999", "title": "Kênh thông báo", "type": "channel"},
                "text": "hello from the channel",
            },
        }]

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    async def fake_sleep(seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    pending = telegram_notify.get_pending_senders()
    assert pending["-100999"]["name"] == "Kênh thông báo"


async def test_listen_loop_pending_sender_name_falls_back_to_username_then_chat_id(monkeypatch, isolated_runtime_config):
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)

    async def fake_get_updates(offset, **kwargs):
        update = _update(1, chat_id="555")
        update["message"]["from"] = {"username": "bryan_ill"}  # no first_name/last_name
        return [update]

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    async def fake_sleep(seconds):
        raise asyncio.CancelledError

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert telegram_notify.get_pending_senders()["555"]["name"] == "@bryan_ill"


async def test_listen_loop_does_not_record_a_registered_recipient_as_pending(monkeypatch, isolated_runtime_config):
    from human_bot.runtime_config import add_telegram_recipient

    add_telegram_recipient("111", "Already registered")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(svc, "get_all_accounts", lambda: {})
    monkeypatch.setattr(svc.data_sync, "get_all_sync_statuses", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})

    async def fake_send_message_to(chat_id, text, *, silent=False):
        pass

    monkeypatch.setattr(telegram_notify, "send_message_to", fake_send_message_to)

    async def fake_get_updates(offset, **kwargs):
        if offset is None:
            return [_update(1, chat_id="111")]
        raise asyncio.CancelledError

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert telegram_notify.get_pending_senders() == {}
