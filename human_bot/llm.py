"""
Picks which LLM the human_bot Executor Agent uses, based on whichever API
key is set in .env, so switching providers never means editing code.

Priority: ANTHROPIC_API_KEY > OPENAI_API_KEY > BROWSER_USE_API_KEY
(ChatBrowserUse). Anthropic/OpenAI are tried first because, as of this
writing, browser-use's free-tier BROWSER_USE_API_KEY cannot call their own
LLM Gateway ("Free tier accounts are not allowed to use the LLM Gateway" —
see cloud.browser-use.com/settings to upgrade if you want to use
ChatBrowserUse instead). If you have a paid browser-use plan, ChatBrowserUse
still works as the fallback.
"""
from __future__ import annotations

import os


def get_llm():
    if os.environ.get("ANTHROPIC_API_KEY"):
        from browser_use import ChatAnthropic

        return ChatAnthropic(model="claude-sonnet-4-0", temperature=0.0)

    if os.environ.get("OPENAI_API_KEY"):
        from browser_use import ChatOpenAI

        return ChatOpenAI(model="gpt-4.1-mini")

    if os.environ.get("BROWSER_USE_API_KEY"):
        from browser_use import ChatBrowserUse

        return ChatBrowserUse()

    raise RuntimeError(
        "No LLM API key found. Set ANTHROPIC_API_KEY, OPENAI_API_KEY, or "
        "BROWSER_USE_API_KEY in .env — see .env.example."
    )
