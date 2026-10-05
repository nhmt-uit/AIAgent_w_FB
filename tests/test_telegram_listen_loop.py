"""
Regression test (2026-10-05 self-review) for human_bot/service.py's
_telegram_listen_loop(): telegram_notify.get_updates() no-ops instantly
(empty list, no network I/O) whenever Telegram isn't configured/enabled
— which is this project's actual current state (no bot token yet, see
tasks.md). An earlier version relied entirely on get_updates()'s own
long-poll timeout for pacing and had no sleep on that path, so the
`while True` loop busy-spun the event loop (pegging a CPU core,
re-reading runtime_config.json every iteration) for as long as the
service ran unconfigured. Fixed by checking is_configured() up front and
sleeping _TELEGRAM_LISTEN_IDLE_SLEEP_SECONDS before retrying.
"""
from __future__ import annotations

import asyncio

import pytest

import human_bot.service as svc
from human_bot import telegram_notify

# asyncio.CancelledError is a BaseException (not Exception) in Python
# 3.8+, so it passes straight through the loop's own
# `except Exception: ... sleep(5); continue` error handler instead of
# being swallowed by it — the clean way to stop a `while True` loop
# under test from inside a monkeypatched call.


async def test_listen_loop_sleeps_instead_of_busy_spinning_when_not_configured(monkeypatch):
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
    """Regression test (2026-10-05 self-review, round 3): a revoked/
    typo'd token still makes is_configured() return True, but every
    get_updates() call then hits a fast network error and returns []
    almost instantly (never genuinely long-polling) — round 2's fix only
    covered the literal "not configured" case and still busy-spun here.
    Fixed by timing the get_updates() call and idle-sleeping when it
    returned far faster than a real ~30s long-poll ever would."""
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


def _update(update_id, chat_id="12345", text="hỏi gì đó"):
    return {"update_id": update_id, "message": {"chat": {"id": chat_id}, "text": text}}


async def test_listen_loop_does_not_idle_sleep_after_a_fast_real_reply(monkeypatch):
    """Regression test (2026-10-05 self-review, round 4): the round-3
    elapsed-time guard originally fired on ANY fast return, including a
    real message that was already waiting (also returns near-instantly)
    — throttling back-to-back real queries by up to
    _TELEGRAM_LISTEN_IDLE_SLEEP_SECONDS for no reason. Must only trigger
    when the fast return was EMPTY."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(svc, "get_all_accounts", lambda: {})
    monkeypatch.setattr(svc.data_sync, "get_all_sync_statuses", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})
    sent = []

    async def fake_send_message(text, *, silent=False):
        sent.append(text)

    monkeypatch.setattr(telegram_notify, "send_message", fake_send_message)

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


async def test_listen_loop_computes_reply_once_per_batch_not_once_per_message(monkeypatch):
    """Regression test (2026-10-05 self-review, round 4): 2+ valid
    messages arriving in the SAME get_updates() batch used to rebuild
    the identical health-snapshot reply once per message — wasted
    DB/file work that scales with how many messages a user sends at
    once. Must compute it once and reuse it for every message in the batch."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    snapshot_calls = {"n": 0}

    def fake_get_all_accounts():
        snapshot_calls["n"] += 1
        return {}

    monkeypatch.setattr(svc, "get_all_accounts", fake_get_all_accounts)
    monkeypatch.setattr(svc.data_sync, "get_all_sync_statuses", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})
    sent = []

    async def fake_send_message(text, *, silent=False):
        sent.append(text)

    monkeypatch.setattr(telegram_notify, "send_message", fake_send_message)

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


async def test_listen_loop_isolates_a_failed_reply_from_the_rest_of_the_batch(monkeypatch):
    """Regression test (2026-10-05 self-review, round 4): offset is
    advanced before a message's reply is built, so if building/sending
    that FIRST reply raises, the exception must not also abort replying
    to a 2nd, otherwise-valid message later in the same batch."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
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

    async def fake_send_message(text, *, silent=False):
        sent.append(text)

    monkeypatch.setattr(telegram_notify, "send_message", fake_send_message)

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


async def test_listen_loop_sleeps_when_a_batch_has_messages_but_none_match_the_chat_id(monkeypatch):
    """Regression test (2026-10-05 self-review, round 5): round 4's
    elapsed-time guard only triggered on `not updates` (an EMPTY batch)
    — a stranger who discovered the bot's username sending messages
    from a DIFFERENT chat id keeps `updates` non-empty every poll (their
    messages are real and arrive fast), so the guard never engaged and
    this loop busy-spun calling get_updates() back-to-back with no
    delay, despite never actually replying to anything. Fixed by
    tracking whether anything was actually replied to, not just whether
    the batch was non-empty."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    sleep_calls = []

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)
        raise asyncio.CancelledError

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    async def fail_if_send_called(text, *, silent=False):
        raise AssertionError("must not reply to a message from an unconfigured chat id")

    monkeypatch.setattr(telegram_notify, "send_message", fail_if_send_called)

    async def fake_get_updates(offset, **kwargs):
        return [_update(1, chat_id="99999")]  # real message, but from a stranger's chat

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert sleep_calls == [svc._TELEGRAM_LISTEN_IDLE_SLEEP_SECONDS]


async def test_listen_loop_replies_to_a_non_text_message_too(monkeypatch):
    """Regression test (2026-10-05 self-review, round 5): the loop's own
    docstring says it replies to "ANY" message (no slash-command needed,
    owner's "nhắn gì cũng được"), but it used to additionally require
    `message.get("text")` to be truthy — silently ignoring a sticker,
    photo, or voice note with no caption, contradicting that design."""
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(svc, "get_all_accounts", lambda: {})
    monkeypatch.setattr(svc.data_sync, "get_all_sync_statuses", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})
    sent = []

    async def fake_send_message(text, *, silent=False):
        sent.append(text)

    monkeypatch.setattr(telegram_notify, "send_message", fake_send_message)

    async def fake_get_updates(offset, **kwargs):
        if offset is None:
            return [{"update_id": 1, "message": {"chat": {"id": "12345"}, "sticker": {"file_id": "abc"}}}]
        raise asyncio.CancelledError

    monkeypatch.setattr(telegram_notify, "get_updates", fake_get_updates)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_listen_loop()

    assert len(sent) == 1
