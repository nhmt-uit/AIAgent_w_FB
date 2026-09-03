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
2. **"Groups you've joined" list** — via the Groups tab in the left nav,
   or directly at `https://www.facebook.com/groups/feed/` → the "Groups
   you've joined" section — then click the matching group from that list.
   This needs no per-account setup (works for any group the account is
   already a member of) and is scoped only to joined groups, so there's
   much less ambiguity than a global search — this is arguably the
   *default* path a real member would use, more than global search.
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

**Mandatory safety check after tiers 1-3:** shortcut and search both carry
real risk of landing on the *wrong* group (a similarly-named group, a
stale/renamed shortcut). After navigating via any of tiers 1-3, verify the
page actually corresponds to the intended group — compare against
`group_url` (the numeric ID if present in the URL, or the group name shown
on the page) — **before** proceeding to post. If it doesn't match, don't
guess: fall back to tier 4 with the authoritative `group_url` rather than
posting into whatever group was actually reached.

**Practical consequence for the Content Strategist Agent / whoever hands
off the task:** `group_url` must still always be supplied (it's the
required fallback and the thing tier 1-3 results get verified against) —
the *only* thing that changed is that `human_bot` no longer assumes it
will use that URL directly; it tries to get there more organically first.
If it's useful to refer to groups by a short name in `/admin` or in
conversation, keep that mapping (name → URL) as plain config data
(similar to `ACCOUNTS` in `human_bot/config.py`).

**Recording order (Codegen), since four tiers can't be recorded at once:**

1. ~~**Tier 4 (`goto` fallback) first**~~ — **done 2026-09-04**, confirmed
   live against account `tu_iizuki`. Implemented in
   `human_bot/actions.py`'s `post_to_group`. One gap: the test group used
   didn't have post approval enabled, so the pending-approval text signals
   in `_PENDING_APPROVAL_TEXT_SIGNALS` are still UNVERIFIED guesses —
   re-test against an approval-required group when convenient and fix
   that list from what's actually observed.
2. **Tier 2 ("Groups you've joined")** next — no per-account setup
   required, so it can be recorded on `tu_iizuki` immediately.
3. **Tier 1 (pinned shortcut)** once the project owner has pinned a test
   group on `tu_iizuki`.
4. **Tier 3 (search)** last — highest selector complexity and the
   disambiguation logic (matching the right result, handling zero/multiple
   matches) needs the most care.

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
  If the same content is meant for multiple groups, vary the wording per
  group (this is a Content Strategist Agent concern, not an Executor one)
  rather than posting the exact same string repeatedly.
- **Text-only posts get flagged more than posts with an image attached** —
  relevant to prioritizing the still-TODO `media_path` support for group
  posts specifically.
- **Posting into a group joined very recently reads as suspicious** — not
  something `human_bot` controls directly, but worth keeping in mind when
  choosing which test/production groups an account posts into first.
