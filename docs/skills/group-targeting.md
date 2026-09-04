---
skill: Facebook Group Targeting & Posting Strategy
used_by: [human-bot-executor, content-strategist, safety-monitor]
sources:
  - https://github.com/rimiti/facebook-automation
  - https://github.com/ByamB4/fb-group-auto-post
  - https://multiplegroupposter.com/blog/automate-facebook-posts/
  - https://roihacks.com/facebook-group-post-approval/
  - https://groupboss.io/blog/customize-facebook-group-link/
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: How `post_to_group` (and any future group-targeted action) decides
> HOW to reach the target group (a 4-tier fallback chain, not one fixed
> method) and WHAT to do once a group requires post approval — read this
> before recording or debugging the Codegen for `post_to_group`.
> VI: Cách `post_to_group` (và các hành động nhắm vào nhóm sau này) quyết
> định ĐI VÀO nhóm bằng cách nào (chuỗi 4 lớp dự phòng, không cố định một
> cách) và làm gì khi nhóm đó yêu cầu duyệt bài — đọc file này trước khi
> ghi hoặc gỡ lỗi Codegen cho `post_to_group`.

# Skill: Facebook Group Targeting & Posting Strategy

## Standing rule (project-wide, not just groups): goto facebook.com, then click the Home icon, then step-by-step — every task

**Added 2026-09-04**, from the project owner directly, then **clarified
2026-09-04** after an initial version of this section over-corrected.
The clarified shape (owner's own words): *"chắc chắn đầu tiên chúng ta
cần goto("https://www.facebook.com/"), đây là điều bình thường với một
người dùng. Tiếp theo đó, đã ở trong facebook rồi, dù đang đứng ở đâu,
chúng ta cũng cần click vào icon FB để về đúng home. Rồi sau đó mới lần
lượt từng bước đi đến đích cần đến."* — i.e. every task, whether the
browser was already open or not, does exactly this:

1. `page.goto("https://www.facebook.com/")` — **this step is fine as a
   direct goto and does NOT need to become a click.** Typing/opening
   facebook.com's own root URL is completely normal, ordinary user
   behavior (a bookmark, a habit, a typed address) — it's not the thing
   that reads as bot-like. Do this unconditionally at the start of every
   action, regardless of whether the persistent page (see
   `browser_pool.py`) was already sitting on some other Facebook page
   from a previous task or genuinely blank.
2. **Then**, now inside Facebook, click the Facebook logo / home icon —
   a real UI click — to (re-)land on the home feed. This step is what
   actually matters for the anti-bot reasoning: it guarantees the
   navigation *after* this point starts from a real click with a proper
   `Referer`, not from a goto, and it's done every time regardless of
   where the page already was.
3. From the home feed, proceed step by step through further real clicks
   (Groups tab → "Your groups" → target group; the composer
   button; etc.) to the actual destination.

**Two explicit exceptions — go directly to the destination URL, skip
steps 1-3 entirely:**

- **Tier 4** below (`page.goto(group_url, referer=...)`) — the
  guaranteed-to-work last resort, only reached after tiers 1-3 (all real,
  step-by-step navigation starting from the home-icon click) have already
  been tried and failed to confirm the right group.
- **Commenting/replying on a specific existing post** (friend's post,
  group post — still-TODO actions in `actions.py`) — a real user reaches
  a specific post directly (from a notification, a shared link, a search
  result), so `page.goto(post_url)` there is itself the normal, expected
  pattern, not a shortcut past normal behavior. No home-icon detour
  needed for these.

`post_to_own_profile`'s current `await page.goto("https://www.facebook.com/")`
is therefore already correct as step 1 — it does **not** need to change.
What it's still missing is step 2 (the home-icon click) before proceeding
to the composer button; that's the follow-up once the Home-icon selector
exists (see the corrected Tier 2 recording steps below), not a rewrite of
the goto itself.

## Four ways a human reaches a group — chosen strategy: a fallback chain, not one fixed method

**Revised 2026-09-04.** The first version of this doc argued for using
*only* direct URL navigation (`page.goto(group_url)`), on the reasoning
that search/shortcuts add fragile selectors for little benefit. That
missed something the project owner raised directly: doing the *exact same*
navigation, the *exact same* way, on *every single* group-posting task is
itself a distinguishing pattern — real people don't reach groups the same
way every time. There's a concrete technical reason this matters, not just
a vague "bots are predictable" intuition: `page.goto(url)` sends the
request with **no `Referer` header** (same as typing an address or opening
a bookmark), whereas a real user clicking through Facebook's own UI
carries a `Referer` pointing at the previous facebook.com page. A bot that
*always* arrives at a group with no referer, every time, is a cleaner
signal than the referer's absence on any single request.

So `post_to_group` uses a **fallback chain across four real navigation
methods**, tried in this order, each one only reached if the one before it
isn't available or doesn't confirm the right group:

1. **Pinned shortcut** in the left sidebar (Facebook's own "Shortcuts"
   list on the home feed) — fastest and most personalized, but only works
   if this specific account has pinned the target group. The project
   owner is setting this up per-account going forward.
2. **"Your groups" list** — via the Groups tab in the left nav → **"Your
   groups"** (corrected 2026-09-04 — this is the actual label in the live
   English UI; earlier drafts of this doc called it "Groups you've
   joined", which was a guess, not confirmed against the real UI) → then
   click the matching group from that list, matched by group name, or by
   numeric group ID when the list exposes it. This needs no per-account
   setup (works for any group the account is already a member of) and is
   scoped only to joined groups, so there's much less ambiguity than a
   global search — this is arguably the *default* path a real member
   would use, more than global search.
3. **Global Facebook search** — type the group's name into Facebook's own
   search bar and pick the matching result. Reached only if the group
   wasn't found via the joined-groups list (e.g. that list is paginated or
   the group's display name doesn't match what's expected). The most
   fragile tier: ranking can shift, multiple groups can share a similar
   name.
4. **Direct URL (`page.goto(group_url, referer="https://www.facebook.com/")`)**
   — the guaranteed-to-work last resort when none of the above panned out.
   Always set an explicit `referer` here rather than leaving it empty —
   near-zero cost, and it avoids the single cleanest version of the
   no-referer signal described above.

**Mandatory safety check after tiers 1-3 — implemented 2026-09-04:**
shortcut and search both carry real risk of landing on the *wrong* group
(a similarly-named group, a stale/renamed shortcut). `post_to_group`
verifies this two ways rather than one: it matches the group's on-page
link by id/slug *before* clicking (`_click_group_by_id`), then re-checks
the landed page's own URL against that same id *after* navigating
(`_confirms_group`), in case the click still didn't land where expected.
If either check fails, the tier is treated as a miss and the chain falls
through — eventually to tier 4 with the authoritative `group_url` — rather
than posting into whatever group was actually reached.

**Practical consequence for the Content Strategist Agent / whoever hands
off the task:** `group_url` must still always be supplied (it's the
required fallback and the thing tier 1-3 results get verified against) —
the *only* thing that changed is that `human_bot` no longer assumes it
will use that URL directly; it tries to get there more organically first.
If it's useful to refer to groups by a short name in `/admin` or in
conversation, keep that mapping (name → URL) as plain config data
(similar to `ACCOUNTS` in `human_bot/config.py`).

**Recording order (Codegen) — ALL FOUR TIERS DONE (2026-09-04):**

All four tiers were recorded via Playwright Codegen against account
`tu_iizuki` and are merged into `human_bot/actions.py`'s `post_to_group`:
Tier 4 first (a complete recording, confirmed live with a real post — one
gap: the test group didn't have post approval enabled, so the
pending-approval text signals in `_PENDING_APPROVAL_TEXT_SIGNALS` are
still UNVERIFIED guesses; re-test against an approval-required group when
convenient), then Tiers 1-3 (navigation-only recordings — each was
deliberately stopped right after opening the composer and typing sample
text, never clicking Post, since the composer/posting steps are identical
across every tier and were already confirmed once via Tier 4).

Rather than matching each tier's group-list/shortcut click by visible
name text (what the raw Codegen recordings did — Facebook's own UI labels
truncate a long group name, e.g. "CHUYỂN VIỆC KỸ SƯ TẠI NH…"), the merged
implementation matches by group id/slug pulled from the link's own `href`
(`_click_group_by_id`/`_group_id_from_url` in `actions.py`) — the project
owner asked for this specifically ("dò ID nhóm trùng với ID nhóm được yêu
cầu đăng"), since the id in the URL is authoritative while a visible name
can be truncated or shared by more than one group. This doubles as the
"mandatory safety check" below, done proactively (matched before the
click, not just verified after) — backed up by `_confirms_group`, which
re-checks `page.url` after navigating in case a click still landed
somewhere unexpected.

`post_to_group` tries the tiers in order — 1 (pinned shortcut) → 2 ("Your
groups" list) → 3 (search, needs a `group_name` to search with — see
`_tier3_search`) → 4 (direct URL, guaranteed fallback) — using whichever
one first lands on a page confirmed to be the right group. See
`post_to_group`'s docstring in `actions.py` for the tier-by-tier
implementation trace.

## Numeric ID vs. custom (vanity) group URL

A Facebook group's original URL is `facebook.com/groups/<numeric id>`; an
admin can later set a custom/vanity URL (`facebook.com/groups/<name>`,
allowed only under 5,000 members — see `groupboss.io` in Sources). Either
form works fine with `page.goto()`. Prefer storing the **numeric ID** form
where you have a choice: Facebook's own general pattern (true for
profiles and pages as well, not specific to groups) is that the numeric ID
is the permanent identifier and a vanity URL is an alias on top of it — if
a group's vanity name is ever changed or removed, the numeric-ID URL still
resolves, while a stored vanity URL could go stale. This project's own
research pass could not find an authoritative source confirming this
redirect behavior specifically for groups (not just pages/profiles) — if
it ever matters in practice, verify it directly (open both URL forms for
the same group) rather than trusting this note blindly.

## Post approval — group posts can be silently pending, not published

Unlike `post_to_own_profile`, a group can require admin approval before a
post appears (`facebook.com/help/131887213640898`; see `roihacks.com` in
Sources). Research did not turn up a documented, reliable DOM signal for
"pending approval" vs. "published" — this needs to be captured directly:

**When recording `post_to_group` with Codegen, do it against at least one
group known to require approval, not only an open group.** Note exactly
what the page shows right after clicking Post (a toast/banner mentioning
"pending", "review", "awaiting approval", or similar; the composer closing
normally either way is not proof of publication). `actions.py`'s
`post_to_group` should check for that signal the same way
`_check_anomaly_or_raise` checks page text for restriction signals, and
return a distinct result — e.g. `ActionResult(success=True,
message="posted_pending_approval")` — rather than reporting a flat
`success=True` that implies the post is already visible. The Safety
Monitor and the Content Strategist Agent's context log both care about
this distinction (a "pending" post shouldn't count as confirmed reach yet).

## Safety pacing specific to groups (on top of `skills/rate-limiting-pacing.md`)

From research into how these tools get flagged in practice
(`multiplegroupposter.com` in Sources) — general rate-limiting/pacing
already lives in `skills/rate-limiting-pacing.md`; these are the
group-specific additions:

- **Identical content posted to many groups in a short window is the
  fastest flag** ("near-duplicate text across 20+ groups within an hour").
  **This is no longer a hypothetical** — `docs/architecture.md` section
  3c confirms side B's "group post" data gets broadcast into every group
  this account has joined, one at a time. Content variation per group is
  therefore a **hard requirement** on the Content Strategist Agent (not
  optional), and posts must be spaced by the randomized inter-post gap
  described there — never fired back-to-back.
- **Text-only posts get flagged more than posts with an image attached** —
  relevant to prioritizing the still-TODO `media_path` support for group
  posts specifically.
- **Posting into a group joined very recently reads as suspicious** — not
  something `human_bot` controls directly, but worth keeping in mind when
  choosing which test/production groups an account posts into first.
