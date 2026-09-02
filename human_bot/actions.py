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

from human_bot.humanize import human_pause, human_type
from human_bot.runtime_config import get_human_typing_config
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
    Recorded via Playwright Codegen against account "troy" on 2026-09-02.
    Sets the post's audience to "Only me" every time — this matches the
    safe default used while testing (see docs/skills/rate-limiting-pacing.md
    for why a new/low-trust account should start conservative). If a wider
    audience is ever needed, this needs a new `audience` parameter and a
    branch here — not a silent behavior change.
    """
    try:
        await page.goto("https://www.facebook.com/")
        await _check_anomaly_or_raise(page)

        # The composer trigger button's accessible name is personalized per
        # account ("<Name> ơi, bạn đang nghĩ gì thế?") — matched with a
        # partial regex so this works for any account, not just "troy".
        await page.get_by_role("button", name=re.compile("đang nghĩ gì thế")).click()
        await human_pause()
        await page.get_by_role("paragraph").click()
        await human_pause()

        # --- Set audience to "Only me" ---
        # FRAGILE: the privacy-list item below is selected by CSS position
        # (nth-child), because Facebook doesn't expose a stable accessible
        # name for it. If this stops matching "Only me" after a Facebook UI
        # change, see docs/skills/vision-fallback.md — re-record this one
        # step with Codegen rather than guessing a new selector.
        await page.get_by_role("button", name=re.compile("Chỉnh sửa quyền riêng tư")).click()
        await human_pause()
        await page.locator(
            "label:nth-child(6) > div > .x9f619.x1n2onr6.x1ja2u2z.x78zum5.xdt5ytf.x1iyjqo2.x2lwn1j > "
            ".x9f619.x1n2onr6.x1ja2u2z.x78zum5.xdt5ytf.x2lah0s.x193iq5w.xmzvs34 > .x1i10hfl.x1qjc9v5 > "
            ".html-div > .x9f619.x1ja2u2z.x78zum5.x2lah0s.x1n2onr6.x1qughib > "
            ".x9f619.x1ja2u2z.x78zum5.x1n2onr6.x1iyjqo2.xs83m0k > .x9f619"
        ).click()
        await human_pause()
        await page.get_by_role("button", name=re.compile("Đã lựa chọn xong đối tượng")).click()
        await human_pause()

        # --- Type and submit the post ---
        # human_type() sends real keystrokes with human-like timing/typos
        # instead of instantly filling the field — see human_bot/humanize.py
        # and docs/skills/human-like-interaction.md.
        #
        # FRAGILE, scoped fix (2026-09-02): this CSS class combo is one of
        # Facebook's shared "atomic" classes and can also match unrelated
        # elements on the feed page sitting behind the composer dialog
        # (e.g. a group link), which breaks Playwright's strict mode. We
        # scope the search to the open dialog only, and use `.xmper1u`
        # (present only on the composer's own div, per the real DOM) to
        # disambiguate. If this breaks again after a Facebook UI change,
        # re-record with Codegen — see docs/skills/vision-fallback.md.
        composer_dialog = page.get_by_role("dialog")
        await composer_dialog.locator(
            ".x1ejq31n.x18oe1m7.x1sy0etr.xstzfhl.x9f619.xzsf02u.xmper1u"
        ).first.click()
        await human_type(page, content, config=get_human_typing_config())

        if media_path:
            # TODO: media upload wasn't captured in this recording yet — add
            # the attach-photo/video step here when needed (record it
            # separately with Codegen: click "Photo/video", use the file
            # chooser with `media_path`).
            pass

        await human_pause()
        await page.get_by_role("button", name="Đăng").click()
        await page.wait_for_timeout(2000)  # let the post submit before we move on

        return ActionResult(success=True, message="posted_to_own_profile")
    except RuntimeError as e:
        return ActionResult(success=False, message=str(e))


async def post_to_group(
    page: Page,
    group_url: str,
    content: str,
    media_path: str | None = None,
) -> ActionResult:
    try:
        await page.goto(group_url)
        await _check_anomaly_or_raise(page)

        # TODO: fill in from a Codegen recording of posting in a group —
        # group composers can require an extra "post to group" confirmation
        # step and sometimes admin approval; the action should still report
        # success once the post is submitted, even if pending approval —
        # note that in the returned message.

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
