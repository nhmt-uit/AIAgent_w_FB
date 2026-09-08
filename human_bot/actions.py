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
from playwright.async_api import TimeoutError as PlaywrightTimeoutError

from human_bot.humanize import (
    human_click,
    human_type,
    pause_after_composer_open,
    pause_after_page_load,
    pause_between_ui_steps,
    reading_pause,
)
from human_bot.runtime_config import get_human_typing_config, get_mouse_config, get_pacing_config
from human_bot.safety import AnomalyDetected, detect_anomaly, is_content_unavailable


@dataclass
class ActionResult:
    success: bool
    message: str


async def _check_target_content_available(page: Page) -> str | None:
    """Returns a failure message if the current page is Facebook's "this
    content isn't available" dead-link page (target post deleted, made
    private, or in a group this account can't see), else None. Call this
    right after page.goto(post_url) and BEFORE trying to click anything
    on the post — otherwise Playwright just times out (~30s) hunting for
    a comment box that will never appear, and the eventual failure gets
    reported as a generic timeout instead of the real reason. Deliberately
    NOT routed through _check_anomaly_or_raise()/AnomalyDetected: a dead
    target post says nothing about this bot account's own standing, so it
    must never pause the account — see human_bot/safety.py's
    is_content_unavailable() docstring."""
    text = await page.inner_text("body")
    if is_content_unavailable(text or ""):
        return "target_content_unavailable"
    return None


async def _check_anomaly_or_raise(page: Page) -> None:
    text = await page.inner_text("body")
    signal = detect_anomaly(text or "", page.url or "")
    if signal:
        # Caller is responsible for turning this into a failed ActionResult
        # AND pausing the account — see human_bot/agent.py's run_task(),
        # which catches AnomalyDetected specifically to do that. Never
        # retry past this point (docs/skills/anomaly-detection.md).
        raise AnomalyDetected(signal)


# --- Posting -----------------------------------------------------------

async def _attach_media(page: Page, scope, media_path: str, mouse, pacing) -> None:
    """Click the composer's "Photo/video" button and hand Playwright the
    local file path directly via the underlying (hidden) `<input
    type="file">`'s `set_input_files` — this is how Playwright always
    handles a file upload; it never actually drives the OS-level file
    picker dialog (which isn't reachable from a browser automation API at
    all), it intercepts the click that would open one.

    Recorded via Playwright Codegen against account "tu_iizuki",
    2026-09-04, TWICE — once via post_to_own_profile's composer (audience
    "Only me"), once via post_to_group's (a public group, no audience
    step at all) — specifically to find a selector that generalizes across
    both, after the first version of this function (own-profile-only,
    scoped to `scope.locator('input[type="file"]')` — `scope` being
    composer_dialog for own-profile or bare `page` for group, since a
    group's composer isn't wrapped in a [role=dialog]) turned out to
    SILENTLY fail for post_to_group: run_task() reported success but no
    image actually appeared on the live post — the unscoped page-wide
    `input[type="file"]` search almost certainly grabbed an unrelated
    hidden file input elsewhere on the page (Facebook has several), not
    the composer's own one, so set_input_files "succeeded" against the
    wrong element with no error to show for it.

    Both raw recordings independently used
    `page.locator("form").filter(has_text="...").locator('input[type="file"]')`
    — confirming Facebook really does wrap each composer in its own
    `<form>` — but the exact `has_text` value differs per context
    ("Create postTu NguyenFriends...", "...Only me...", "...Public...":
    account name + whatever audience/visibility text happens to be
    showing), which is exactly the kind of value this project avoids
    baking into a selector (see docs/skills/facebook-custom-actions.md,
    "How selectors get filled in"). This version scopes to the composer's
    own <form> WITHOUT that text dependency: the already-uniquely-resolved
    Photo/video button's nearest ancestor <form> — same structural
    relationship both recordings relied on, none of the fragile text.
    `scope` narrows which "Photo/video" button gets clicked in the first
    place (composer_dialog for own-profile, page for group — both
    confirmed live 2026-09-04), only the file-input lookup changed."""
    # NOTE (2026-09-04, found via a real failed run): a literal "/" inside
    # a regex passed to get_by_role(name=...) breaks Playwright's role
    # selector — it serializes the pattern into its own DSL as
    # `[name=/pattern/flags]`, where an unescaped "/" in the pattern itself
    # is parsed as the closing delimiter, producing
    # "InvalidSelectorError: unexpected symbol ... during parsing attribute
    # value". Same class of gotcha already worked around elsewhere in this
    # file for apostrophes (see "what.?s on your mind" below, "." instead
    # of "'") — same fix here: "." matches any single character, including
    # the literal "/", without tripping the DSL's own delimiter parsing.
    photo_button = scope.get_by_role(
        "button", name=re.compile("photo.video", re.IGNORECASE)
    )
    await human_click(page, photo_button, mouse)
    await pause_between_ui_steps(pacing)
    composer_form = photo_button.locator("xpath=ancestor::form[1]")
    await composer_form.locator('input[type="file"]').first.set_input_files(media_path)
    # Let the thumbnail actually finish uploading/rendering in the
    # composer before anything else (typing, clicking Post) happens.
    await pause_after_page_load(pacing)

    # Verify the attachment actually took — added 2026-09-07 after the
    # exact incident described above (set_input_files landing on the
    # wrong hidden <input>): run_task() reported success but no image
    # ever appeared on the live post, with nothing anywhere having
    # actually checked. An <img> rendering inside the SAME composer_form
    # just uploaded into is the signal the thumbnail attached to the
    # right composer, not a coincidence elsewhere on the page.
    # NEEDS LIVE CONFIRMATION — this generic `img` selector wasn't
    # captured by either Codegen recording this function is based on (see
    # docstring above); test_run_task a real image attach and narrow this
    # selector if Facebook renders the thumbnail differently than assumed.
    try:
        await composer_form.locator("img").first.wait_for(state="visible", timeout=8000)
    except PlaywrightTimeoutError:
        raise RuntimeError("media_attach_failed: khong thay anh xuat hien trong khung soan sau khi dinh kem")


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

    Standing rule (docs/skills/group-targeting.md): `page.goto(
    "https://www.facebook.com/")` below stays a direct goto — going to
    Facebook's own root URL is normal, ordinary user behavior. What comes
    right after it is a real click on the Facebook logo/home icon (added
    2026-09-04, selector captured from the Tier 1/2/3 `post_to_group`
    Codegen recordings — `page.get_by_role("link", name="Facebook")`, see
    `_go_home` in this module), so every subsequent navigation in this
    function starts from a real click rather than from the goto alone.
    """
    pacing = get_pacing_config()
    mouse = get_mouse_config()
    try:
        await page.goto("https://www.facebook.com/")
        await _check_anomaly_or_raise(page)
        # Land on the page and just... look at it for a while, like a
        # person actually would, before touching anything.
        await pause_after_page_load(pacing)
        await _go_home(page, mouse, pacing)

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
            await _attach_media(page, composer_dialog, media_path, mouse, pacing)

        # "Read it back" before submitting — scales with content length
        # instead of a flat pause, see human_bot/humanize.py's reading_pause().
        await reading_pause(content, pacing)
        # Confirmed live 2026-09-03. Scoped to composer_dialog (not
        # page-wide) and exact=True since "Post" is a common word that
        # could otherwise match unrelated buttons.
        post_button = composer_dialog.get_by_role("button", name="Post", exact=True)
        await human_click(page, post_button, mouse)

        # Verify the post actually submitted instead of assuming success
        # after a flat wait — added 2026-09-07 after a real incident where
        # a silently-failed step (a mis-attached image, see _attach_media)
        # still returned success=True because nothing here ever checked.
        # The dialog closing (its own "Post" button leaving the DOM) is
        # the signal a submit actually went through; still visible after a
        # generous timeout means something's wrong (a validation error,
        # still uploading media, disconnected...) — NEEDS LIVE
        # CONFIRMATION like every other selector in this file.
        try:
            await post_button.wait_for(state="hidden", timeout=15000)
        except PlaywrightTimeoutError:
            # Before assuming this is an ordinary stuck-submit failure,
            # check whether Facebook actually threw up a checkpoint/anomaly
            # modal over the composer — that leaves the Post button still
            # attached to the DOM (only visually covered), so the wait
            # above times out the same way a real stuck submit would.
            # Without this re-check the account would silently NOT get
            # paused despite being flagged mid-action — see
            # docs/skills/anomaly-detection.md.
            await _check_anomaly_or_raise(page)
            return ActionResult(success=False, message="post_button_still_visible_after_click")

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


# --- Group navigation: the 4-tier fallback chain ------------------------
# See docs/skills/group-targeting.md for the full design/reasoning. All
# four tiers recorded via Playwright Codegen against account "tu_iizuki",
# 2026-09-04: Tier 4 first (full recording, confirmed live with a real
# post), then Tiers 1-3 (partial recordings — navigation only, stopped
# before clicking Post, since the composer/post steps are identical across
# tiers and were already confirmed once via Tier 4's live test).

_GROUP_URL_ID_RE = re.compile(r"/groups/([^/?#]+)")


def _group_id_from_url(url: str) -> str | None:
    """Pull the group's numeric-id-or-vanity-slug path segment out of a
    facebook.com/groups/<id-or-slug> URL. Used to positively match the
    *correct* group's link on a shortcut/list/search-results page by its
    href, instead of by visible group name text — the project owner asked
    for this 2026-09-04 ("dò ID nhóm trùng với ID nhóm được yêu cầu đăng")
    specifically because a name can be truncated by the UI or shared by
    more than one group, while the id/slug in the URL is authoritative.
    See docs/skills/group-targeting.md, "Mandatory safety check after
    tiers 1-3"."""
    m = _GROUP_URL_ID_RE.search(url)
    return m.group(1) if m else None


async def _confirms_group(page: Page, group_url: str) -> bool:
    """Post-navigation half of the same safety check: does the page we
    actually ended up on match the group we meant to reach? Compared
    against `page.url` rather than trusting that the pre-click href match
    in `_click_group_by_id` guarantees the click didn't land somewhere
    unexpected (a preview card, an interstitial, a redirect). Returns True
    when the id can't be determined at all (nothing to check against) so
    this never blocks a legitimate vanity-URL group.

    FIXED 2026-09-04 — real bug seen live: this used to check `page.url`
    exactly once, immediately after the click returned. Facebook's own
    navigation is client-side (SPA routing), and `page.url` can still show
    the OLD page for a beat after a real click has already landed and
    started loading the group — so this check would fire mid-transition,
    see the old URL, and (correctly, given what it saw) report "not the
    right group". The tier loop in post_to_group then falls through to
    the NEXT tier, which starts with a Home-icon click — navigating AWAY
    from the group that had, in fact, been reached correctly. That's
    exactly the "vào đúng Group rồi lại thoát ra" (enters the right group
    then leaves again) the project owner reported. Fix: poll for the URL
    to update (page.wait_for_url) instead of a single immediate read,
    giving the SPA navigation time to actually finish."""
    group_id = _group_id_from_url(group_url)
    if not group_id:
        return True
    if group_id in page.url:
        return True
    try:
        await page.wait_for_url(f"**/groups/{group_id}**", timeout=6000)
        return True
    except Exception:  # noqa: BLE001 — Playwright's TimeoutError, or any
        # other navigation hiccup: either way, we didn't confirm the
        # right group, so report False and let the caller fall through.
        return False


async def _click_group_by_id(page: Page, group_url: str, mouse) -> bool:
    """Click the on-page link whose href contains the same group id/slug
    as `group_url`. Works across Tier 1 (pinned shortcut), Tier 2 ("Your
    groups" list) and Tier 3 (search results) — in all three, Facebook
    renders the group card/shortcut as a real `<a href="/groups/<id>/...">`
    anchor, so one href-substring match covers every tier rather than
    needing per-tier name-text selectors (which is what the three
    Codegen recordings originally used — see the tier functions below for
    why that was swapped out). Returns False, meaning "this tier couldn't
    find the group, fall through to the next one", if no matching link is
    on the page at all.

    FIXED 2026-09-04 — real bug seen live: the project owner reported
    cases where a group visibly sat in the pinned-shortcuts list, the page
    even scrolled toward it, but nothing got clicked. Root cause: matching
    bare `a[href*="/groups/<id>"]` with no visibility filter can resolve
    `.first` to a hidden duplicate of the same href that Facebook keeps in
    the DOM (an alternate-layout copy, a collapsed "see more" flyout not
    yet expanded, etc.) rather than the one actually on screen —
    human_click()'s `wait_for(state="visible")` then just sits there until
    it times out on an element that will never become visible, silently
    swallowed by the tier loop's `except Exception: continue` in
    post_to_group. Appending Playwright's `:visible` pseudo-class filters
    the match down to elements actually rendered on screen before we ever
    try to click one."""
    group_id = _group_id_from_url(group_url)
    if not group_id:
        return False
    locator = page.locator(f'a[href*="/groups/{group_id}"]:visible')
    if await locator.count() == 0:
        return False
    await human_click(page, locator.first, mouse)
    return True


async def _go_home(page: Page, mouse, pacing) -> None:
    """Click the Facebook logo/home icon. Recorded 2026-09-04 identically
    across all three Tier 1/2/3 Codegen sessions
    (`page.get_by_role("link", name="Facebook")`), always the very first
    click right after landing on facebook.com/ — see docs/skills/
    group-targeting.md, "Standing rule": going to facebook.com's own root
    URL is normal, but everything after that should proceed via real
    clicks, starting with this one, so the resulting navigation carries a
    proper Referer instead of relying on goto alone."""
    await human_click(page, page.get_by_role("link", name="Facebook"), mouse)
    await pause_between_ui_steps(pacing)


async def _tier1_pinned_shortcut(page: Page, group_url: str, mouse, pacing) -> bool:
    """Tier 1: click the group's own pinned shortcut in the left sidebar.
    Only works if this account has pinned the target group — confirmed
    2026-09-04 against tu_iizuki, which does have one pinned. The original
    Codegen recording matched the shortcut by its (truncated) visible
    name (`get_by_role("link", name="CHUYỂN VIỆC KỸ SƯ TẠI NH")`); swapped
    for `_click_group_by_id` per the id-matching safety check above."""
    await _go_home(page, mouse, pacing)
    return await _click_group_by_id(page, group_url, mouse)


async def _tier2_your_groups(page: Page, group_url: str, mouse, pacing) -> bool:
    """Tier 2: Groups tab → "Your groups" list → the matching group.
    Recorded 2026-09-04 against tu_iizuki. Needs no per-account setup —
    works for any group the account has already joined. (The live UI's
    actual label is "Your groups" — an earlier draft of docs/skills/
    group-targeting.md guessed "Groups you've joined", which was wrong.)"""
    await _go_home(page, mouse, pacing)
    await human_click(page, page.get_by_label("Shortcuts").get_by_role(
        "link", name="Groups"
    ), mouse)
    await pause_between_ui_steps(pacing)
    await human_click(page, page.get_by_role("link", name="Your groups"), mouse)
    await pause_between_ui_steps(pacing)
    return await _click_group_by_id(page, group_url, mouse)


async def _tier3_search(page: Page, group_url: str, group_name: str | None, mouse, pacing) -> bool:
    """Tier 3: Facebook's own search, filtered to "My groups". Recorded
    2026-09-04 against tu_iizuki. Needs the group's saved display name
    (from /admin/groups, see human_bot/runtime_config.py's
    get_joined_groups) as the search query — if the caller didn't supply
    one, this tier is skipped entirely (returns False immediately) rather
    than searching with nothing."""
    if not group_name:
        return False
    await _go_home(page, mouse, pacing)
    search_box = page.get_by_role("combobox", name="Search Facebook")
    await human_click(page, search_box, mouse)
    await human_type(page, group_name, config=get_human_typing_config())
    await search_box.press("Enter")
    await pause_after_page_load(pacing)
    await human_click(page, page.get_by_role(
        "link", name="Groups results", exact=True
    ), mouse)
    await pause_between_ui_steps(pacing)
    # Filter to groups this account has actually joined — narrows the
    # result set and matches what a real member searching for their own
    # group would naturally do next.
    my_groups_switch = page.get_by_role("switch", name="My groups")
    if await my_groups_switch.count() > 0:
        await human_click(page, my_groups_switch, mouse)
        await pause_after_page_load(pacing)
    return await _click_group_by_id(page, group_url, mouse)


async def post_to_group(
    page: Page,
    group_url: str,
    content: str,
    media_path: str | None = None,
    group_name: str | None = None,
) -> ActionResult:
    """
    Full 4-tier fallback chain — see docs/skills/group-targeting.md.
    Recorded via Playwright Codegen against account "tu_iizuki",
    2026-09-04 (English UI): Tier 4 first (complete recording, confirmed
    live with a real post), then Tiers 1-3 (navigation-only recordings —
    each was deliberately stopped before clicking Post, since the
    composer/posting steps are identical across every tier and don't need
    re-confirming per tier).

    Tries tiers 1 → 2 → 3 → 4 in order, using whichever one first lands on
    a page confirmed (by group id/slug, not name — see
    `_click_group_by_id` / `_confirms_group`) to be the right group. Any
    tier that can't find the group, or whose selectors break outright
    (e.g. after a Facebook UI change), falls through to the next one
    rather than failing the whole task. Tier 4 (`page.goto(group_url)`) is
    the guaranteed-to-work last resort if 1-3 all miss.

    `group_name` is only used by Tier 3 (the search query text) — pass the
    group's saved display name from /admin/groups when available; Tier 3
    is simply skipped if it's not supplied.

    Unlike `post_to_own_profile`, a group post has no audience/privacy
    step to record — visibility follows the group's own settings, not a
    per-post choice.
    """
    pacing = get_pacing_config()
    mouse = get_mouse_config()
    try:
        # Standing rule (docs/skills/group-targeting.md): goto facebook.com
        # itself is normal/expected user behavior and stays a direct goto;
        # everything after this is real clicks, starting inside each tier
        # function with a Home-icon click.
        await page.goto("https://www.facebook.com/")
        await _check_anomaly_or_raise(page)
        await pause_after_page_load(pacing)

        reached = False
        for tier in (
            lambda: _tier1_pinned_shortcut(page, group_url, mouse, pacing),
            lambda: _tier2_your_groups(page, group_url, mouse, pacing),
            lambda: _tier3_search(page, group_url, group_name, mouse, pacing),
        ):
            try:
                if await tier() and await _confirms_group(page, group_url):
                    reached = True
                    break
            except Exception:
                # A broken selector in one tier (FB UI change, A/B test,
                # this account not having a pinned shortcut, etc.) falls
                # through to the next tier instead of failing the task.
                continue

        if not reached:
            # Tier 4: guaranteed-to-work last resort. Explicit referer so
            # this doesn't leave the single cleanest "arrived with no
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
            # Reuses _attach_media (see its docstring) — UNVERIFIED for
            # this function specifically, since the Codegen recording for
            # the attach step was only done against post_to_own_profile's
            # composer. Scoped to `page` (not a dialog wrapper) since this
            # composer expands inline, same reasoning as the textbox click
            # right above.
            await _attach_media(page, page, media_path, mouse, pacing)

        # Confirmed live 2026-09-04: the recording clicked back into the
        # paragraph once more before submitting — kept as-is rather than
        # guessed away, it plausibly reflects a real "glance back over
        # what I wrote" moment.
        await human_click(page, page.get_by_role("paragraph"), mouse)
        await reading_pause(content, pacing)
        post_button = page.get_by_role("button", name="Post", exact=True)
        await human_click(page, post_button, mouse)

        # Same verification as post_to_own_profile (see its comment) —
        # NEEDS LIVE CONFIRMATION. This composer is inline (no dialog
        # wrapper), so "the Post button leaves the DOM" is the best
        # generic signal available without a live recording of a
        # successful vs. failed submit to compare against; still applies
        # equally to the pending-approval case below, since that only
        # affects whether the post is visible yet, not whether the
        # composer closes on submit.
        try:
            await post_button.wait_for(state="hidden", timeout=15000)
        except PlaywrightTimeoutError:
            # Same reasoning as post_to_own_profile's identical check: a
            # checkpoint/anomaly modal popping up mid-submit leaves the
            # Post button attached to the DOM (only visually covered), so
            # re-check before assuming this is an ordinary stuck submit.
            await _check_anomaly_or_raise(page)
            return ActionResult(success=False, message="post_button_still_visible_after_click")

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
        unavailable = await _check_target_content_available(page)
        if unavailable:
            return ActionResult(success=False, message=unavailable)

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
    """
    Recorded via Playwright Codegen against account "tu_iizuki" (English
    UI) commenting on a real post inside a group — see
    `codegen_comment_group.py` in the repo root for the raw recording.
    **Confirmed live 2026-09-08**: re-recorded against a group the
    account is actually a member of ("Việc làm Kỹ Sư Nhật Bản"), comment
    verified visible on the post after a page refresh. (An earlier
    2026-09-07 recording, against a group the account hadn't joined yet
    — see docs/skills/group-targeting.md re: `multi_permalinks` URLs —
    ran the identical click/type/submit sequence for real but couldn't
    confirm visibility; same selectors, superseded by this confirmation.)

    `page.goto(post_url)` straight to the post's permalink, same
    "goto is the guaranteed-to-work path" reasoning as post_to_group's
    Tier 4. Clicking the post's own body text (role "paragraph") first to
    reveal the comment textbox, THEN typing into it, mirrors the exact
    two-step reveal post_to_group's inline composer already uses.
    """
    pacing = get_pacing_config()
    mouse = get_mouse_config()
    try:
        await page.goto(post_url)
        await _check_anomaly_or_raise(page)
        unavailable = await _check_target_content_available(page)
        if unavailable:
            return ActionResult(success=False, message=unavailable)
        await pause_after_page_load(pacing)

        await human_click(page, page.get_by_role("paragraph").first, mouse)
        await pause_between_ui_steps(pacing)

        # Regex match ("comment" OR "answer", not the recording's exact
        # "Write a public comment…") since wording varies by group
        # privacy ("Write a comment…") AND by post type — confirmed live
        # 2026-09-08 that a Q&A-style group post renders "Write an
        # answer…" instead, causing a 30s timeout here before this was
        # widened. The "Post comment"-labeled submit button below is NOT
        # widened the same way — a Q&A post's compact composer showed no
        # such text button in that screenshot (icon-only send control),
        # so a Q&A post will still fail at that step; this only fixes the
        # textbox-not-found timeout, not full Q&A support.
        comment_box = page.get_by_role("textbox", name=re.compile("comment|answer", re.IGNORECASE))
        await human_click(page, comment_box, mouse)
        await human_type(page, content, config=get_human_typing_config())

        await reading_pause(content, pacing)
        post_comment_button = page.get_by_role("button", name="Post comment", exact=True)
        await human_click(page, post_comment_button, mouse)

        # Verify the comment actually submitted instead of assuming
        # success — same reasoning/pattern as post_to_own_profile's and
        # post_to_group's own verification: the button only rendering
        # while the box has content (per the recording) means it leaving
        # the DOM is the best generic "it went through" signal without a
        # live recording of a failed submit to compare against — NEEDS
        # LIVE CONFIRMATION.
        try:
            await post_comment_button.wait_for(state="hidden", timeout=15000)
        except PlaywrightTimeoutError:
            # Same reasoning as post_to_own_profile/post_to_group's
            # identical check: a checkpoint/anomaly modal popping up
            # mid-submit can leave this button attached to the DOM (only
            # visually covered) rather than actually removing it.
            await _check_anomaly_or_raise(page)
            return ActionResult(success=False, message="comment_button_still_visible_after_click")

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
