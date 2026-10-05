from __future__ import annotations

import httpx
import pytest

from human_bot import telegram_notify
from human_bot.runtime_config import add_telegram_recipient, save_telegram_overrides

_RealAsyncClient = httpx.AsyncClient


def _patch_async_client(monkeypatch, handler) -> None:
    """Same MockTransport-swap pattern tests/test_ai_client.py uses for
    ai_client.py — redirects every httpx.AsyncClient(...) call inside
    telegram_notify.py to a fake transport instead of real network I/O.
    Must capture the real class up front (_RealAsyncClient, above) rather
    than reading httpx.AsyncClient inside the lambda, since by the time
    the lambda runs that attribute has already been monkeypatched to
    itself and would recurse."""
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda timeout=None: _RealAsyncClient(transport=httpx.MockTransport(handler)),
    )


def _configure(monkeypatch, *, enabled: bool = True, recipients=(("12345", "Test"),)) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    for chat_id, label in recipients:
        add_telegram_recipient(chat_id, label)
    if not enabled:
        save_telegram_overrides({"enabled": False})


def test_is_configured_false_when_no_token(monkeypatch, isolated_runtime_config):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert telegram_notify.is_configured() is False


def test_is_configured_true_even_with_zero_recipients_registered(monkeypatch, isolated_runtime_config):
    """2026-10-05 follow-up (multi-recipient admin list, replacing the
    single TELEGRAM_CHAT_ID env var): is_configured() must NOT depend on
    the recipients list being non-empty — get_updates()/the 2-way listen
    loop must keep polling even with zero recipients, so a brand new one
    added via /admin while the service is already running can query
    immediately without a restart. Broadcasting to an empty list is
    already a harmless no-op on its own."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    assert telegram_notify.is_configured() is True


def test_is_configured_false_when_disabled_via_admin_switch(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch, enabled=False)
    assert telegram_notify.is_configured() is False


def test_is_configured_true_when_token_and_enabled(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch)
    assert telegram_notify.is_configured() is True


async def test_send_message_no_token_never_touches_network(monkeypatch, isolated_runtime_config):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    add_telegram_recipient("12345", "Test")

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not make a network call when not configured")

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.send_message("hello")  # no raise = pass


async def test_send_message_posts_expected_payload(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(200, json={"ok": True})

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.send_message("xin chào", silent=True)

    assert captured["url"] == "https://api.telegram.org/bottest-token/sendMessage"
    assert captured["body"]["chat_id"] == "12345"
    assert captured["body"]["text"] == "xin chào"
    assert captured["body"]["disable_notification"] == "true"


async def test_send_message_broadcasts_to_every_registered_recipient(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch, recipients=(("111", "A"), ("222", "B"), ("333", "C")))
    seen_chat_ids = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode()))
        seen_chat_ids.append(body["chat_id"])
        return httpx.Response(200, json={"ok": True})

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.send_message("hello")

    assert sorted(seen_chat_ids) == ["111", "222", "333"]


async def test_send_message_one_recipient_failing_does_not_block_the_others(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch, recipients=(("111", "Broken"), ("222", "OK")))
    seen_chat_ids = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode()))
        if body["chat_id"] == "111":
            raise httpx.ConnectError("boom — simulated bad/blocked recipient")
        seen_chat_ids.append(body["chat_id"])
        return httpx.Response(200, json={"ok": True})

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.send_message("hello")  # must not raise

    assert seen_chat_ids == ["222"]


async def test_send_message_broadcasts_nothing_when_no_recipients_registered(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch, recipients=())

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not make a network call with zero registered recipients")

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.send_message("hello")  # no raise = pass


async def test_send_message_truncates_to_telegram_cap(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["body"] = dict(httpx.QueryParams(request.content.decode()))
        return httpx.Response(200, json={"ok": True})

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.send_message("x" * 5000)

    assert len(captured["body"]["text"]) == 4096


async def test_send_message_swallows_network_error(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.send_message("hello")  # no raise = pass


async def test_send_message_swallows_non_200(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(429, text="rate limited")

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.send_message("hello")  # no raise = pass


async def test_send_message_to_targets_exactly_the_given_chat_id(monkeypatch, isolated_runtime_config):
    """send_message_to() (2026-10-05, the 2-way query's direct reply) must
    send to exactly the chat_id passed in — ignoring the registered
    recipients list entirely (the caller already decided who to reply
    to), and must work even for a chat_id that ISN'T registered."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    add_telegram_recipient("999", "Someone else entirely")
    seen_chat_ids = []

    def handler(request: httpx.Request) -> httpx.Response:
        body = dict(httpx.QueryParams(request.content.decode()))
        seen_chat_ids.append(body["chat_id"])
        return httpx.Response(200, json={"ok": True})

    _patch_async_client(monkeypatch, handler)
    ok = await telegram_notify.send_message_to("555", "trả lời riêng")

    assert seen_chat_ids == ["555"]
    assert ok is True


async def test_send_message_to_returns_false_on_non_200(monkeypatch, isolated_runtime_config):
    """send_message_to() must report real success/failure (not just
    "didn't raise") — admin.py's "🧪 Gửi thử" button relies on this
    return value to avoid showing a false "✅ đã gửi" when the send
    actually failed."""
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(400, text="chat not found")

    _patch_async_client(monkeypatch, handler)
    ok = await telegram_notify.send_message_to("555", "hello")

    assert ok is False


async def test_send_message_to_returns_false_on_network_error(monkeypatch, isolated_runtime_config):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _patch_async_client(monkeypatch, handler)
    ok = await telegram_notify.send_message_to("555", "hello")

    assert ok is False


async def test_send_message_to_no_token_never_touches_network(monkeypatch, isolated_runtime_config):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not make a network call when not configured")

    _patch_async_client(monkeypatch, handler)
    ok = await telegram_notify.send_message_to("555", "hello")  # no raise = pass
    assert ok is False


async def test_send_photo_uploads_file_bytes_to_every_recipient(monkeypatch, isolated_runtime_config, tmp_path):
    _configure(monkeypatch, recipients=(("111", "A"), ("222", "B")))
    img_path = tmp_path / "shot.png"
    img_path.write_bytes(b"fake-png-bytes")
    seen_chat_ids = []

    def handler(request: httpx.Request) -> httpx.Response:
        assert b"fake-png-bytes" in request.content
        seen_chat_ids.append(request.url)  # just to count calls; chat_id is in the multipart body
        return httpx.Response(200, json={"ok": True})

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.send_photo(str(img_path), caption="caption text")

    assert len(seen_chat_ids) == 2
    assert all(str(u) == "https://api.telegram.org/bottest-token/sendPhoto" for u in seen_chat_ids)


async def test_send_photo_falls_back_to_broadcast_message_when_file_missing(monkeypatch, isolated_runtime_config, tmp_path):
    _configure(monkeypatch)
    sent = []

    async def fake_send_message(text, *, silent=False):
        sent.append((text, silent))

    monkeypatch.setattr(telegram_notify, "send_message", fake_send_message)
    await telegram_notify.send_photo(str(tmp_path / "missing.png"), caption="caption text", silent=True)

    assert sent == [("caption text", True)]


async def test_get_updates_returns_empty_when_not_configured(monkeypatch, isolated_runtime_config):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    assert await telegram_notify.get_updates(None) == []


async def test_get_updates_parses_result_and_passes_offset(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch)
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["params"] = dict(request.url.params)
        return httpx.Response(200, json={"ok": True, "result": [{"update_id": 42}]})

    _patch_async_client(monkeypatch, handler)
    result = await telegram_notify.get_updates(41, timeout=5)

    assert result == [{"update_id": 42}]
    assert captured["params"]["offset"] == "41"
    assert captured["params"]["timeout"] == "5"


async def test_get_updates_swallows_network_error(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch)

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _patch_async_client(monkeypatch, handler)
    assert await telegram_notify.get_updates(None) == []


def test_record_pending_sender_then_get():
    telegram_notify.record_pending_sender("111", "Tu")
    pending = telegram_notify.get_pending_senders()
    assert pending["111"]["name"] == "Tu"
    assert "last_seen" in pending["111"]


def test_record_pending_sender_updates_an_existing_entrys_last_seen():
    telegram_notify.record_pending_sender("111", "Tu")
    first_seen = telegram_notify.get_pending_senders()["111"]["last_seen"]
    telegram_notify.record_pending_sender("111", "Tu (đổi tên)")
    updated = telegram_notify.get_pending_senders()["111"]
    assert updated["name"] == "Tu (đổi tên)"
    assert updated["last_seen"] >= first_seen


def test_get_pending_senders_returns_a_copy_not_the_live_dict():
    telegram_notify.record_pending_sender("111", "Tu")
    snapshot = telegram_notify.get_pending_senders()
    snapshot["222"] = {"name": "injected", "last_seen": "x"}
    assert "222" not in telegram_notify.get_pending_senders()


def test_get_pending_senders_inner_dicts_are_also_copies(monkeypatch):
    """Regression test (self-review follow-up): a shallow dict(...) copy
    still shares the INNER {"name", "last_seen"} dicts by reference with
    the live module state — mutating one returned from here must never
    corrupt _pending_senders itself."""
    telegram_notify.record_pending_sender("111", "Tu")
    snapshot = telegram_notify.get_pending_senders()
    snapshot["111"]["name"] = "corrupted"
    assert telegram_notify.get_pending_senders()["111"]["name"] == "Tu"


def test_clear_pending_sender_removes_it():
    telegram_notify.record_pending_sender("111", "Tu")
    telegram_notify.clear_pending_sender("111")
    assert telegram_notify.get_pending_senders() == {}


def test_clear_pending_sender_unknown_chat_id_is_a_noop():
    telegram_notify.clear_pending_sender("never-existed")  # no raise


def test_record_pending_sender_evicts_the_oldest_once_at_cap():
    for i in range(telegram_notify._PENDING_SENDERS_CAP):
        telegram_notify.record_pending_sender(str(i), f"Sender {i}")
    assert len(telegram_notify.get_pending_senders()) == telegram_notify._PENDING_SENDERS_CAP

    telegram_notify.record_pending_sender("new-sender", "Someone new")

    pending = telegram_notify.get_pending_senders()
    assert len(pending) == telegram_notify._PENDING_SENDERS_CAP  # still capped
    assert "0" not in pending  # the oldest (recorded first) was evicted
    assert "new-sender" in pending


# --- refresh_bot_username() / get_cached_bot_username() (2026-10-05 follow-up) ---

def test_get_cached_bot_username_none_before_any_refresh():
    assert telegram_notify.get_cached_bot_username() is None


async def test_refresh_bot_username_no_token_never_touches_network(monkeypatch, isolated_runtime_config):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)

    def handler(request: httpx.Request) -> httpx.Response:
        raise AssertionError("must not call getMe without a token")

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.refresh_bot_username()
    assert telegram_notify.get_cached_bot_username() is None


async def test_refresh_bot_username_caches_the_username_on_success(monkeypatch, isolated_runtime_config):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.path == "/bottest-token/getMe"
        return httpx.Response(200, json={"ok": True, "result": {"id": 1, "username": "AIAgentSupport_bot"}})

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.refresh_bot_username()
    assert telegram_notify.get_cached_bot_username() == "AIAgentSupport_bot"


async def test_refresh_bot_username_leaves_cache_unchanged_on_non_200(monkeypatch, isolated_runtime_config):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, text="unauthorized")

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.refresh_bot_username()  # must not raise
    assert telegram_notify.get_cached_bot_username() is None


async def test_refresh_bot_username_swallows_network_error(monkeypatch, isolated_runtime_config):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")

    def handler(request: httpx.Request) -> httpx.Response:
        raise httpx.ConnectError("boom")

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.refresh_bot_username()  # must not raise
    assert telegram_notify.get_cached_bot_username() is None
