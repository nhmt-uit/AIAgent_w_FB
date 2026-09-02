---
skill: Vision Fallback for UI Changes (reserved, not yet implemented)
used_by: [human-bot-executor]
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: The planned fallback strategy for when a recorded Playwright selector can't find an element — NOT wired up yet in the default path (which uses plain Playwright, no LLM). Read this when deciding whether to build this fallback, or when a selector keeps failing after a Facebook UI change in the meantime.
> VI: Chiến lược dự phòng dự kiến khi một selector Playwright đã ghi lại không tìm thấy phần tử — CHƯA được nối vào luồng chính (luồng chính dùng Playwright thuần, không có AI). Đọc file này khi cân nhắc xây dựng phần dự phòng này, hoặc khi một selector liên tục lỗi sau khi Facebook đổi giao diện trong lúc chưa có nó.

# Skill: Vision Fallback (reserved)

## Current status

As of the pivot to plain Playwright (see `docs/architecture.md` section
1), `human_bot/actions.py` has **no automatic fallback** when a recorded
selector breaks — it fails hard and returns `ActionResult(success=False,
...)`. The plan below describes how an LLM-assisted fallback (via
`human_bot/llm.py`, currently only wired for a possible future
browser-use path) could be added later, without making the normal,
zero-LLM-cost path depend on it.

## Why a fallback might be worth adding later

Facebook's DOM structure and class names change often and are frequently
obfuscated/randomized, which can break a recorded selector even when the
visible UI hasn't meaningfully changed to a human. Today the fix is: a
human re-records the broken step with Playwright Codegen (see
`docs/skills/facebook-custom-actions.md`, "When Facebook's UI changes").
That is simple and reliable but requires a human in the loop every time.

## Planned strategy, if/when built

1. Attempt the recorded selector first, always — this costs nothing and
   works the vast majority of the time.
2. If it fails, take a `page.screenshot(...)` and pass it to an LLM (via
   `human_bot/llm.py`'s `get_llm()`) with a prompt describing what element
   is needed (e.g. "the blue Post button in the bottom-right of the
   composer"), asking for its approximate coordinates or a better
   selector.
3. Interact via whatever the LLM resolves, not by guessing a new CSS
   selector by hand.
4. If the fallback also fails, treat it as a hard failure — return
   `ActionResult(success=False, message="ui_element_not_found")` and stop.
   Do not fall back further into raw JavaScript DOM manipulation for
   state-changing actions like posting/commenting — too easy to get
   subtly wrong on a page you can't fully verify.
5. Log every fallback usage (screenshot + what it resolved to) — this is
   the fastest way to notice "Facebook changed something" and turn it into
   a proper Codegen re-recording, which should always be the goal;
   the fallback exists to keep things running in the meantime, not to
   replace re-recording permanently.

## Cost note

Every fallback invocation is an LLM API call — unlike the normal
zero-cost Playwright path. If this gets built, log fallback frequency per
action so a selector that fails often gets prioritized for re-recording
instead of quietly eating LLM cost forever.
