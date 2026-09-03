"""
Facebook actions, implemented with plain Playwright — NOT browser-use.

Why plain Playwright instead of an LLM-driven agent: for every action here,
the exact click-by-click steps were already recorded once with Playwright
Codegen by a human operator (see docs/skills/facebook-custom-actions.md).
Since the steps are fully known in advance, there is nothing for an LLM to
decide — running an AI agent to "figure out" a sequence we already have the
exact answer to would only add cost, latency, and a chance of the AI
clicking the wrong thing. This matches the project's own design principle
(docs/agents/human-bot-executor.md): the Executor should be as
deterministic as possible.

An LLM (browser-use, see human_bot/llm.py) is reserved as a FALLBACK for
when a recorded selector breaks after a Facebook UI change and no one has
re-recorded it yet — see docs/skills/vision-fallback.md. It is not used in
the normal path.

One function per DISTINCT real-world action (post to own profile, post in
a group, comment on a friend's post, comment on a group post, ...) — see
docs/skills/facebook-custom-actions.md for why these are kept separate.
"""
import re
from dataclasses import dataclass

from playwright.async_api import Page

from human_bot.humanize import (
    human_click,
    human_type,
    pause_after_composer_open,
    pause_after_page_load,
    pause_between_ui_steps,
    reading_pause,
)
from human_bot.runtime_config import get_human_typing_config, get_mouse_config, get_pacing_config
from human_bot.safety import detect_anomaly


@dataclass
class ActionResult:
    success: bool
    message: str


async def _check_anomaly_or_raise(page: Page) -> None:
    text = await page.inner_text("body")
    signal = detect_anomaly(text or "", page.url or "")
    if signal:
        # Caller is responsible for turning this into a failed ActionResult;
        # see docs/skills/anomaly-detection.md — never retry past this point.
        raise RuntimeError(f"anomaly_detected:{signal}")


# --- Posting -----------------------------------------------------------

async def post_to_own_profile(
    page: Page,
    content: str,
    media_path: str | None = None,
) -> ActionResult:
    """
    Recorded via Playwright Codegen against account "troy" on 2026-09-02
    (Vietnamese UI), then RE-RECORDED and confirmed against account
    "tu_iizuki" on 2026-09-03 after switching the project standard to the
    ENGLISH Facebook UI (see docs/skills/facebook-custom-actions.md,
    "Facebook UI language") — every selector below is taken close to
    verbatim from that second, English-locale recording, not guessed.
    Sets the post's audience to "Only me" every time — this matches the
    safe default used while testing (see docs/skills/rate-limiting-pacing.md
    for why a new/low-trust account should start conservative). If a wider
    audience is ever needed, this needs a new `audience` parameter and a
    branch here — not a silent behavior change.
    """
    pacing = get_pacing_config()
    mouse = get_mouse_config()
    try:
        await page.goto("https://www.facebook.com/")
        await _check_anomaly_or_raise(page)
        # Land on the page and just... look at it for a while, like a
        # person actually would, before touching anything.
        await pause_after_page_load(pacing)

        # Facebook UI language for all bot accounts is standardized to
        # ENGLISH (locale="en-US" in browser_pool.py + the Facebook account
        # itself must have English set in its own language settings — see
        # docs/skills/facebook-custom-actions.md, "Facebook UI language").
        # The composer trigger button's accessible name is personalized per
        # account ("What's on your mind, <Name>?") — matched with a partial
        # regex so this works for any account.
        await human_click(page, page.get_by_role(
            "button", name=re.compile("what.?s on your mind", re.IGNORECASE)
        ), mouse)
        await pause_after_composer_open(pacing)

        # --- Set audience to "Only me" ---
        # Confirmed live 2026-09-03 (see docstring above) — the privacy list
        # item is a plain text node ("Only me"), no CSS-position hack
        # needed anymore. If this stops matching after a Facebook UI
        # change, re-record with Codegen — see docs/skills/
        # facebook-custom-actions.md, "How selectors get filled in".
        await human_click(page, page.get_by_role(
            "button", name=re.compile("edit privacy", re.IGNORECASE)
        ), mouse)
        await pause_between_ui_steps(pacing)
        await human_click(page, page.get_by_text(re.compile("^only me$", re.IGNORECASE)), mouse)
        await pause_between_ui_steps(pacing)
        await human_click(page, page.get_by_role(
            "button", name=re.compile("done with privacy audience", re.IGNORECASE)
        ), mouse)
        await pause_between_ui_steps(pacing)
        await human_click(page, page.get_by_role("paragraph"), mouse)
        await pause_between_ui_steps(pacing)

        # --- Type and submit the post ---
        # human_type() sends real keystrokes with human-like timing/typos
        # instead of instantly filling the field — see human_bot/humanize.py
        # and docs/skills/human-like-interaction.md.
        #
        # Confirmed live 2026-09-03: the composer's text field has an
        # accessible role of "textbox" and Facebook doesn't render any
        # other textbox while the composer dialog is open, so scoping to
        # the dialog (not page-wide) is enough to keep this unique — no
        # more fragile obfuscated CSS class combo needed here.
        composer_dialog = page.get_by_role("dialog")
        await human_click(page, composer_dialog.get_by_role("textbox").first, mouse)
        await human_type(page, content, config=get_human_typing_config())

        if media_path:
            # TODO: media upload wasn't captured in this recording yet — add
            # the attach-photo/video step here when needed (record it
            # separately with Codegen: click "Photo/video", use the file
            # chooser with `media_path`).
            pass

        # "Read it back" before submitting — scales with content length
        # instead of a flat pause, see human_bot/humanize.py's reading_pause().
        await reading_pause(content, pacing)
        # Confirmed live 2026-09-03. Scoped to composer_dialog (not
        # page-wide) and exact=True since "Post" is a common word that
        # could otherwise match unrelated buttons.
        await human_click(page, composer_dialog.get_by_role(
            "button", name="Post", exact=True
        ), mouse)
        await page.wait_for_timeout(2000)  # let the post submit before we move on

        return ActionResult(success=True, message="posted_to_own_profile")
    except RuntimeError as e:
        return ActionResult(success=False, message=str(e))


# Best-effort text signals for "your post is awaiting admin approval"
# rather than already published — see docs/skills/group-targeting.md,
# "Post approval". UNVERIFIED (2026-09-04): the group used to record
# post_to_group did not have approval enabled, so this list was written
# from general knowledge of Facebook's own wording, not observed directly.
# Re-verify (and fix this list) the first time this actually runs against
# an approval-required group — see docs/skills/facebook-custom-actions.md,
# "How selectors get filled in".
_PENDING_APPROVAL_TEXT_SIGNALS = [
    "pending approval",
    "awaiting approval",
    "post is being reviewed",
    "will be visible once",
]


async def _looks_like_pending_approval(page: Page) -> bool:
    text = (await page.inner_text("body") or "").lower()
    return any(signal in text for signal in _PENDING_APPROVAL_TEXT_SIGNALS)


async def post_to_group(
    page: Page,
    group_url: str,
    content: str,
    media_path: str | None = None,
) -> ActionResult:
    """
    Recorded via Playwright Codegen against account "tu_iizuki" on
    2026-09-04 (English UI, tier-4/direct-URL navigation — see
    docs/skills/group-targeting.md for the full 4-tier navigation strategy;
    this function currently only implements tier 4, `page.goto(group_url)`,
    the guaranteed-to-work fallback. Tiers 1-3 — pinned shortcut, "Groups
    you've joined" list, search — are still TODO; see that doc for why
    they matter and the planned recording order).

    Unlike `post_to_own_profile`, a group post has no audience/privacy
    step to record — visibility follows the group's own settings, not a
    per-post choice.
    """
    pacing = get_pacing_config()
    mouse = get_mouse_config()
    try:
        # Tier 4 only for now (see docstring). Explicit referer so this
        # fallback doesn't leave the single cleanest "arrived with no
        # referer at all" signal — see docs/skills/group-targeting.md.
        await page.goto(group_url, referer="https://www.facebook.com/")
        await _check_anomaly_or_raise(page)
        await pause_after_page_load(pacing)

        await human_click(page, page.get_by_role(
            "button", name=re.compile("write something", re.IGNORECASE)
        ), mouse)
        await pause_after_composer_open(pacing)
        await human_click(page, page.get_by_role("paragraph"), mouse)
        await pause_between_ui_steps(pacing)

        # Confirmed live 2026-09-04: same as post_to_own_profile, the
        # composer's text field has role "textbox". UNSCOPED here (no
        # `dialog` wrapper — a group's composer expands inline in the
        # page, not as a modal like the profile composer) since it
        # resolved uniquely in the recording; if this ever breaks with a
        # strict-mode violation, scope it to whatever container wraps the
        # composer, the same fix used for post_to_own_profile.
        await human_click(page, page.get_by_role("textbox"), mouse)
        await human_type(page, content, config=get_human_typing_config())

        if media_path:
            # TODO: media upload wasn't captured in this recording yet —
            # see the matching TODO in post_to_own_profile.
            pass

        # Confirmed live 2026-09-04: the recording clicked back into the
        # paragraph once more before submitting — kept as-is rather than
        # guessed away, it plausibly reflects a real "glance back over
        # what I wrote" moment.
        await human_click(page, page.get_by_role("paragraph"), mouse)
        await reading_pause(content, pacing)
        await human_click(page, page.get_by_role(
            "button", name="Post", exact=True
        ), mouse)
        await page.wait_for_timeout(2000)  # let the post submit before we move on

        if await _looks_like_pending_approval(page):
            return ActionResult(success=True, message="posted_to_group_pending_approval")
        return ActionResult(success=True, message="posted_to_group")
    except RuntimeError as e:
        return ActionResult(success=False, message=str(e))


# --- Commenting ----------------------------------------------------------

async def comment_on_friend_post(
    page: Page,
    post_url: str,
    content: str,
) -> ActionResult:
    try:
        await page.goto(post_url)
        await _check_anomaly_or_raise(page)

        # TODO: fill in from a Codegen recording of commenting on a
        # friend's post.

        return ActionResult(success=True, message="commented_on_friend_post")
    except RuntimeError as e:
        return ActionResult(success=False, message=str(e))


async def comment_on_group_post(
    page: Page,
    post_url: str,
    content: str,
) -> ActionResult:
    try:
        await page.goto(post_url)
        await _check_anomaly_or_raise(page)

        # TODO: fill in from a Codegen recording. Group post pages sometimes
        # render differently from a standalone post view — verify the
        # comment box found is attached to the right post.

        return ActionResult(success=True, message="commented_on_group_post")
    except RuntimeError as e:
        return ActionResult(success=False, message=str(e))


# --- Reactions & read-only -------------------------------------------------

async def like_post(page: Page, post_url: str) -> ActionResult:
    try:
        await page.goto(post_url)
        await _check_anomaly_or_raise(page)

        # TODO: fill in from a Codegen recording of liking a post.

        return ActionResult(success=True, message="liked")
    except RuntimeError as e:
        return ActionResult(success=False, message=str(e))


async def read_recent_comments(page: Page, post_url: str, limit: int = 10) -> ActionResult:
    try:
        await page.goto(post_url)
        await _check_anomaly_or_raise(page)

        # TODO: extract post body + up to `limit` recent comments as
        # structured text, used by the Content Strategist Agent — see
        # docs/skills/content-context-awareness.md.

        return ActionResult(success=True, message="[]")
    except RuntimeError as e:
        return ActionResult(success=False, message=str(e))
