"""
Purpose of this file / Muc dich cua file nay:
EN: Single entry point for calling whichever text-generation AI provider is
currently selected on /admin/config's AI tab (Anthropic, OpenAI, Google
Gemini, or a "custom" OpenAI-compatible endpoint — DeepSeek/Groq/OpenRouter/
a local LLM server/etc.), so human_bot/content_strategist.py's prompt-
building and JSON-validation logic never needs to know which provider is
active. Added 2026-09-10, splitting the previously Anthropic-only httpx
calls (duplicated once for job-post drafting, once for candidate-reply
rewriting) out into one shared, provider-dispatching function.

call_ai_text() raises AIProviderError (or lets the underlying httpx error
propagate) on any failure — no key configured, no model configured, or the
HTTP call itself failing. It never falls back to anything on its own;
content_strategist.py's callers already catch broad exceptions and fall
back to the plain-template drafting, same "safe-by-default" behavior that
existed before multi-provider support.
VI: Noi duy nhat goi API cua nha cung cap AI dang duoc chon o /admin/config,
de content_strategist.py khong can biet dang dung provider nao.
"""
from __future__ import annotations

import httpx

from human_bot.runtime_config import get_active_ai_provider_config

# Used only when the admin hasn't typed a model name for the active
# provider — "custom" has no sane guess for an arbitrary endpoint, so it's
# left out on purpose (missing model there is a configuration error, not
# something to silently paper over).
_DEFAULT_MODELS: dict[str, str] = {
    "anthropic": "claude-sonnet-4-5",
    "openai": "gpt-4o-mini",
    "gemini": "gemini-2.5-flash",
}


class AIProviderError(RuntimeError):
    """No API key or no model configured for the active provider. Callers
    (content_strategist.py) already catch broad Exception around every AI
    call and fall back to template text, so this needs no special handling
    upstream — it's just a clearer log message than a raw KeyError/None
    would give."""


async def call_ai_text(system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    """Calls whichever provider is currently active and returns its raw
    text response. Raises on any problem — missing key/model, or the HTTP
    call itself failing (bad status, network error, unexpected response
    shape)."""
    cfg = get_active_ai_provider_config()
    if not cfg.api_key:
        raise AIProviderError(f"no API key configured for AI provider '{cfg.provider}'")
    model = cfg.model or _DEFAULT_MODELS.get(cfg.provider, "")
    if not model:
        raise AIProviderError(f"no model configured for AI provider '{cfg.provider}'")

    if cfg.provider == "anthropic":
        return await _call_anthropic(cfg.api_key, model, system_prompt, user_prompt, max_tokens)
    if cfg.provider == "gemini":
        return await _call_gemini(cfg.api_key, model, system_prompt, user_prompt, max_tokens)
    if cfg.provider in ("openai", "custom"):
        base_url = cfg.base_url.strip() or "https://api.openai.com/v1"
        return await _call_openai_compatible(cfg.api_key, model, system_prompt, user_prompt, max_tokens, base_url)
    raise AIProviderError(f"unknown AI provider '{cfg.provider}'")


async def _call_anthropic(api_key: str, model: str, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            "https://api.anthropic.com/v1/messages",
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "system": system_prompt,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()
    return "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )


async def _call_openai_compatible(
    api_key: str, model: str, system_prompt: str, user_prompt: str, max_tokens: int, base_url: str,
) -> str:
    """Standard Chat Completions shape — used for both "openai" (fixed
    base_url) and "custom" (admin-supplied base_url), since a "custom"
    endpoint is defined here as exactly "something that speaks the OpenAI
    Chat Completions API", the most common shape third-party/local LLM
    servers expose."""
    url = base_url.rstrip("/") + "/chat/completions"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            url,
            headers={
                "Authorization": f"Bearer {api_key}",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": max_tokens,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
            },
        )
        response.raise_for_status()
        data = response.json()
    return data["choices"][0]["message"]["content"]


async def _call_gemini(api_key: str, model: str, system_prompt: str, user_prompt: str, max_tokens: int) -> str:
    url = f"https://generativelanguage.googleapis.com/v1beta/models/{model}:generateContent"
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            url,
            params={"key": api_key},
            json={
                "systemInstruction": {"parts": [{"text": system_prompt}]},
                "contents": [{"role": "user", "parts": [{"text": user_prompt}]}],
                "generationConfig": {"maxOutputTokens": max_tokens},
            },
        )
        response.raise_for_status()
        data = response.json()
    parts = data["candidates"][0]["content"]["parts"]
    return "".join(p.get("text", "") for p in parts)
