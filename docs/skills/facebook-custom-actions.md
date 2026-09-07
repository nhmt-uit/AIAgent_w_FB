---
skill: Facebook Custom Actions (plain Playwright functions)
used_by: [human-bot-executor]
source: https://playwright.dev/python/
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: Defines the exact contract for every Facebook action human_bot can perform (post, comment, like, read comments) — read this whenever an action fails or Facebook's UI changes.
> VI: Quy định chính xác từng hành động human_bot có thể làm trên Facebook (đăng bài, comment, like, đọc comment) — đọc file này khi một hành động bị lỗi hoặc khi Facebook đổi giao diện.

# Skill: Facebook Custom Actions

## Why plain Playwright, not an LLM-driven agent

Every action here has already been performed once by a human operator and
recorded step-by-step with **Playwright Codegen** — the exact sequence of
clicks/fills is fully known in advance. There is nothing left for an AI to
decide, so each action is implemented as a plain deterministic `async`
function in `human_bot/actions.py` instead of an LLM "tool" an agent
chooses to call. See `docs/architecture.md` section 1 for the full
reasoning, and `docs/skills/vision-fallback.md` for the one place an LLM
is still reserved (as a fallback, not the default path).

## Why one function per real-world context, not one generic "post"/"comment"

Posting to your own profile, posting in a group, commenting on a friend's
post, and commenting on a group post are treated as **separate actions**,
each its own function in `human_bot/actions.py` — not a single generic
`post`/`comment` action with a "where" parameter. Facebook's composer and
comment-box DOM genuinely differ between these contexts, and keeping them
separate means each function's steps can be fixed independently without
risking the others, and the Content Strategist Agent's Task JSON `action`
field is unambiguous about exactly what is about to happen (useful for
audit logs).

## Function signature pattern

```python
from playwright.async_api import Page

async def post_to_own_profile(
    page: Page,
    content: str,
    media_path: str | None = None,
) -> ActionResult:
    await page.goto("https://www.facebook.com/")
    # ... standardized click/type sequence, recorded via Codegen ...
    return ActionResult(success=True, message="posted_to_own_profile")
```

`ActionResult` is a small local dataclass (`success: bool, message: str`)
defined in `human_bot/actions.py` — not browser-use's `ActionResult`.

## Required actions for this project

| Action (function name) | Purpose | Notes |
|---|---|---|
| `post_to_own_profile(page, content, media_path?)` | Post a status update on the account's own personal profile | No target URL needed — always the account's own timeline. **Implemented** (recorded 2026-09-02). |
| `post_to_group(page, group_url, content, media_path?)` | Publish a new post inside a specific Facebook group | **Tier 4 (direct URL) implemented and confirmed live 2026-09-04** — no audience/privacy step (unlike `post_to_own_profile`), visibility follows the group's own settings. Pending-approval detection is UNVERIFIED (recorded against a group with approval off). **See `skills/group-targeting.md`** for the 4-tier navigation fallback chain — tiers 1-3 (pinned shortcut, joined-groups list, search) still TODO. |
| `comment_on_friend_post(page, post_url, content)` | Comment on a friend's post (newsfeed or their profile) | TODO — not yet recorded. |
| `comment_on_group_post(page, post_url, content)` | Comment on a post inside a group | Group post pages can render differently — verify the comment box found belongs to the right post. TODO — not yet recorded. |
| `like_post(page, post_url)` | React to a post, friend's or group's | Lowest-risk action; useful for warming up a new account. TODO — not yet recorded. |
| `read_recent_comments(page, post_url, limit=10)` | Read-only: extract recent comments for context | Used by Content Strategist Agent, not just Executor. TODO — not yet recorded. |

## How selectors get filled in

Each `TODO` function's actual Facebook DOM steps come from a real
**Playwright Codegen** recording made by the operator (not guessed) — run:

```
python3 -m playwright codegen --load-storage=accounts/<account_id>/storage_state.json \
  --save-storage=accounts/<account_id>/storage_state.json \
  -o codegen_<action_name>.py https://www.facebook.com
```

then perform the action by hand once in the opened browser. The generated
script's Playwright locators (`get_by_role`, `.locator()`, `.fill()`,
`.click()`) are used close to verbatim inside the matching `async def` in
`human_bot/actions.py` — this is now a direct, low-effort translation
since both the recording and the action run on the same real Playwright
API (no more translating into a different framework's API).

## Facebook UI language — must be English

**Every Facebook account human_bot drives must have its display language
set to English** (Settings → Language and region → Facebook language, or
the account's UI language dropdown on the login/settings page). This is a
project-wide decision made 2026-09-03, after a real test run against a
freshly-registered account failed at the very first step: the composer
button read "What's on your mind" (English) instead of the Vietnamese text
the recorded selector expected, because that account had no Vietnamese
language preference set.

Two things enforce this together — both must match, and the account
setting is the one that actually wins if they disagree:

1. `browser_pool.py` passes `locale="en-US"` to every browser context, so
   Facebook doesn't have to guess a language from IP/device.
2. The Facebook **account itself** must also have English set in its own
   saved settings — an account-level language preference can override the
   browser's locale, so step 1 alone is not reliable by itself.

Why English and not Vietnamese: English is Facebook's primary language —
new UI rollouts and copy changes land there first and the translation is
always complete, whereas the Vietnamese translation can lag behind or be
worded differently across rollout groups (this project's own selectors
were originally recorded in Vietnamese against account "troy" and already
needed a bilingual fallback once a second account came back in English —
see `human_bot/actions.py`). Since human_type() posts whatever content
string it's given regardless of UI language, standardizing the *interface*
language costs nothing for the *content*, which stays Vietnamese as
normal.

Practical effect: every selector in `human_bot/actions.py` should be
written against the **English** UI text going forward. `post_to_own_profile`
was re-recorded with Codegen against an English-language account
("tu_iizuki") on 2026-09-03 and its selectors are now confirmed-live, not
guessed — see the function's docstring. The other four actions
(`post_to_group`, `comment_on_friend_post`, `comment_on_group_post`,
`like_post`) are still unrecorded TODOs; record those directly in English
from the start (no need to record a Vietnamese pass first).

## Implementation notes

- Prefer role/accessible-name locators (`page.get_by_role("button",
  name=...)`) over raw CSS class selectors where Codegen offers both —
  Facebook's class names are obfuscated and rotate frequently, while
  accessible names are comparatively stable. Use `re.compile(...)` for
  partial/personalized names (e.g. a composer button whose label includes
  the account's display name).
- Always take a `page.screenshot(path=...)` right before and right after a
  state-changing step (post/comment submit) so failures are debuggable.
- Every action function must catch its own exceptions and return
  `ActionResult(success=False, message=<reason>)` rather than letting the
  caller retry blindly.
- See `skills/anomaly-detection.md` — every action must check for anomaly
  signals right after `page.goto(...)`, before proceeding.
- See `skills/vision-fallback.md` for the reserved (not yet wired up)
  fallback strategy for when a recorded selector can't be found.

## When Facebook's UI changes

Re-record the broken step(s) with Codegen and update the matching function
in `human_bot/actions.py` directly, then restart the human_bot service (or
call `AccountSession.restart_session()` for just the affected account) so
it picks up the new code. There is no separate "prompt" to reload — the
Python file itself is the source of truth now.
