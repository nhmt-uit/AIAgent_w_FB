from __future__ import annotations

import httpx
import pytest

from human_bot import telegram_notify
from human_bot.runtime_config import save_telegram_overrides

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


def _configure(monkeypatch, *, enabled: bool = True) -> None:
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.setenv("TELEGRAM_CHAT_ID", "12345")
    if not enabled:
        save_telegram_overrides({"enabled": False})


def test_is_configured_false_when_no_token(monkeypatch, isolated_runtime_config):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram_notify.is_configured() is False


def test_is_configured_false_when_chat_id_missing(monkeypatch, isolated_runtime_config):
    monkeypatch.setenv("TELEGRAM_BOT_TOKEN", "test-token")
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
    assert telegram_notify.is_configured() is False


def test_is_configured_false_when_disabled_via_admin_switch(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch, enabled=False)
    assert telegram_notify.is_configured() is False


def test_is_configured_true_when_token_and_chat_id_and_enabled(monkeypatch, isolated_runtime_config):
    _configure(monkeypatch)
    assert telegram_notify.is_configured() is True


async def test_send_message_no_token_never_touches_network(monkeypatch, isolated_runtime_config):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)

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


async def test_send_photo_uploads_file_bytes(monkeypatch, isolated_runtime_config, tmp_path):
    _configure(monkeypatch)
    img_path = tmp_path / "shot.png"
    img_path.write_bytes(b"fake-png-bytes")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["content"] = request.content
        return httpx.Response(200, json={"ok": True})

    _patch_async_client(monkeypatch, handler)
    await telegram_notify.send_photo(str(img_path), caption="caption text")

    assert captured["url"] == "https://api.telegram.org/bottest-token/sendPhoto"
    assert b"fake-png-bytes" in captured["content"]


async def test_send_photo_falls_back_to_message_when_file_missing(monkeypatch, isolated_runtime_config, tmp_path):
    _configure(monkeypatch)
    sent = []

    async def fake_send_message(text, *, silent=False):
        sent.append((text, silent))

    monkeypatch.setattr(telegram_notify, "send_message", fake_send_message)
    await telegram_notify.send_photo(str(tmp_path / "missing.png"), caption="caption text", silent=True)

    assert sent == [("caption text", True)]


async def test_get_updates_returns_empty_when_not_configured(monkeypatch, isolated_runtime_config):
    monkeypatch.delenv("TELEGRAM_BOT_TOKEN", raising=False)
    monkeypatch.delenv("TELEGRAM_CHAT_ID", raising=False)
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
