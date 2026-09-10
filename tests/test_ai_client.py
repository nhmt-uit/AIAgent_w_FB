from __future__ import annotations

import json

import httpx
import pytest

from human_bot import ai_client
from human_bot.runtime_config import ActiveAIProviderConfig


def _patch_provider(monkeypatch, **kwargs):
    cfg = ActiveAIProviderConfig(provider="anthropic", api_key="", model="", base_url="")
    cfg = ActiveAIProviderConfig(**{**cfg.__dict__, **kwargs})
    monkeypatch.setattr(ai_client, "get_active_ai_provider_config", lambda: cfg)
    return cfg


def _mock_transport(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


_RealAsyncClient = httpx.AsyncClient


def _patch_async_client(monkeypatch, handler) -> None:
    """Redirects every `httpx.AsyncClient(timeout=...)` call inside
    ai_client.py to use a MockTransport instead of real network I/O. Must
    capture the real class (_RealAsyncClient, above, bound at import time)
    rather than reading httpx.AsyncClient inside the lambda — by the time
    the lambda runs, that attribute has already been monkeypatched to the
    lambda itself, which would recurse into itself instead of ever
    constructing a real client."""
    monkeypatch.setattr(
        httpx, "AsyncClient",
        lambda timeout=None: _RealAsyncClient(transport=_mock_transport(handler)),
    )


@pytest.mark.asyncio
async def test_call_ai_text_raises_when_no_api_key(monkeypatch):
    _patch_provider(monkeypatch, provider="anthropic", api_key="", model="claude-sonnet-4-5")
    with pytest.raises(ai_client.AIProviderError):
        await ai_client.call_ai_text("system", "user", max_tokens=100)


@pytest.mark.asyncio
async def test_call_ai_text_raises_when_no_model_and_no_default(monkeypatch):
    _patch_provider(monkeypatch, provider="custom", api_key="ck", model="", base_url="https://x.example/v1")
    with pytest.raises(ai_client.AIProviderError):
        await ai_client.call_ai_text("system", "user", max_tokens=100)


@pytest.mark.asyncio
async def test_anthropic_request_shape(monkeypatch):
    _patch_provider(monkeypatch, provider="anthropic", api_key="sk-ant-test", model="claude-sonnet-4-5")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"content": [{"type": "text", "text": '{"posts": ["ok"]}'}]})

    _patch_async_client(monkeypatch, handler)
    text = await ai_client.call_ai_text("sys-prompt", "user-prompt", max_tokens=64)

    assert text == '{"posts": ["ok"]}'
    assert captured["url"] == "https://api.anthropic.com/v1/messages"
    assert captured["headers"]["x-api-key"] == "sk-ant-test"
    assert captured["headers"]["anthropic-version"] == "2023-06-01"
    assert captured["body"]["model"] == "claude-sonnet-4-5"
    assert captured["body"]["system"] == "sys-prompt"
    assert captured["body"]["messages"] == [{"role": "user", "content": "user-prompt"}]


@pytest.mark.asyncio
async def test_openai_request_shape(monkeypatch):
    _patch_provider(monkeypatch, provider="openai", api_key="sk-openai-test", model="gpt-4o-mini")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["headers"] = dict(request.headers)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"choices": [{"message": {"content": "hello"}}]})

    _patch_async_client(monkeypatch, handler)
    text = await ai_client.call_ai_text("sys-prompt", "user-prompt", max_tokens=64)

    assert text == "hello"
    assert captured["url"] == "https://api.openai.com/v1/chat/completions"
    assert captured["headers"]["authorization"] == "Bearer sk-openai-test"
    assert captured["body"]["model"] == "gpt-4o-mini"
    assert captured["body"]["messages"] == [
        {"role": "system", "content": "sys-prompt"},
        {"role": "user", "content": "user-prompt"},
    ]


@pytest.mark.asyncio
async def test_custom_provider_uses_configured_base_url(monkeypatch):
    _patch_provider(
        monkeypatch, provider="custom", api_key="ck", model="deepseek-chat",
        base_url="https://api.deepseek.com/v1",
    )
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        return httpx.Response(200, json={"choices": [{"message": {"content": "custom-ok"}}]})

    _patch_async_client(monkeypatch, handler)
    text = await ai_client.call_ai_text("sys", "user", max_tokens=32)

    assert text == "custom-ok"
    assert captured["url"] == "https://api.deepseek.com/v1/chat/completions"


@pytest.mark.asyncio
async def test_gemini_request_shape(monkeypatch):
    _patch_provider(monkeypatch, provider="gemini", api_key="AIza-test", model="gemini-2.5-flash")
    captured = {}

    def handler(request: httpx.Request) -> httpx.Response:
        captured["url"] = str(request.url)
        captured["body"] = json.loads(request.content)
        return httpx.Response(200, json={"candidates": [{"content": {"parts": [{"text": "gemini-ok"}]}}]})

    _patch_async_client(monkeypatch, handler)
    text = await ai_client.call_ai_text("sys-prompt", "user-prompt", max_tokens=32)

    assert text == "gemini-ok"
    assert captured["url"].startswith(
        "https://generativelanguage.googleapis.com/v1beta/models/gemini-2.5-flash:generateContent"
    )
    assert "key=AIza-test" in captured["url"]
    assert captured["body"]["systemInstruction"]["parts"][0]["text"] == "sys-prompt"
    assert captured["body"]["contents"][0]["parts"][0]["text"] == "user-prompt"


@pytest.mark.asyncio
async def test_anthropic_http_error_propagates(monkeypatch):
    _patch_provider(monkeypatch, provider="anthropic", api_key="sk-bad", model="claude-sonnet-4-5")

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(401, json={"error": "unauthorized"})

    _patch_async_client(monkeypatch, handler)
    with pytest.raises(httpx.HTTPStatusError):
        await ai_client.call_ai_text("sys", "user", max_tokens=32)
