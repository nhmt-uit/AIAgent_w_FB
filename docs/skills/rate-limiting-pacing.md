---
skill: Rate Limiting & Human-like Pacing
used_by: [human-bot-executor, safety-monitor]
sources:
  # Re-found 2026-09-10 after the project owner asked where the numbers
  # below actually came from — the 2026-09-07 "external reports" note was
  # never pinned to real URLs at the time. All of these are marketing
  # blogs from companies selling Facebook auto-posting tools, NOT Meta's
  # own policy — Facebook has never published real limits. Treat every
  # number below as a rough, self-interested estimate, not a verified
  # fact. multiplegroupposter.com is the one overlap with
  # docs/skills/group-targeting.md's own sources.
  - https://www.lilachbullock.com/how-many-facebook-groups-can-you-post-in-each-day/
  - https://fbgroupbulkposter.com/blog/facebook-group-posting-limits-2026
  - https://multiplegroupposter.com/blog/facebook-group-posting-limits/
  - https://www.pilotposter.com/blog/facebook-group-posting-limits/
  - https://blog.jarveepro.com/Facebook-Marketing-Tips/How-Many-Facebook-Groups-Can-You-Post-to-in-One-Day-Real-Numbers,-Safe-Limits,-and-AI-Automation-Tips-(2026-Guide)/16039
  - https://multiplegroupposter.com/blog/facebook-auto-poster-safe-settings/
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: Action-speed limits and human-like pacing rules — read this to tune how fast/slow an account is allowed to act, or after an account gets flagged too often.
> VI: Giới hạn tốc độ hành động và quy tắc giãn cách giống người thật — đọc file này khi cần điều chỉnh tốc độ hành động của một tài khoản, hoặc sau khi tài khoản bị cảnh báo nhiều lần.

# Skill: Rate Limiting & Pacing

## Why

Facebook's Terms prohibit automated behavior that mimics or substitutes for
a real user, and its abuse systems key heavily on *pattern*: constant
speed, 24/7 activity, and perfectly even intervals are the clearest bot
signals — more than any single action. This skill exists to make human_bot's
behavior look paced like a person, not to guarantee undetectability.

## Default limits (per account, configurable in `human_bot/config.py`)

| Action | Default limit |
|---|---|
| Posts | 2–3 per day |
| Comments | 4–6 per hour, max ~20/day |
| Likes | up to 15/hour |
| Concurrent actions on the same account | 1 (never run two actions in parallel on one account) |

These are conservative starting points, not guarantees — tune down further
for new/low-trust accounts and up only gradually for old, established ones.

**What the sources above actually say (2026-09-10 re-check, numbers vary a
lot between them — self-interested marketing content, not Meta policy):**
brand-new accounts "should stay below 10 groups/day", cautious estimate
3–7/day; accounts under 6 months "20–40 posts/day"; 6–12 months
"40–80/day"; 12+ months "50–100+/day". Gap between individual actions:
"10–15 minutes" per post is called safe by one source, "30–60 seconds
randomized" for likes/shares by another. **These are all far more
permissive than `ACCOUNT_AGE_TIERS` below (5–22 posts/day, 1–6 hour gaps)
— see that table's own note for why the project hasn't adopted them.**

**Implemented (2026-09-07, retuned 2026-09-10):** `human_bot/config.py`'s
`ACCOUNT_AGE_TIERS` gives 5 ready-made `RateLimits` presets by
Facebook-account age (dưới 1 / 3 / 6 / 12 tháng, trên 12 tháng), so "tune
down for new accounts" is a dropdown/button instead of hand-typing
numbers per account. Picked when registering an account at
`/admin/accounts`, or applied later via a quick-apply button in that
account's "⏱️ Giới hạn" modal (for when it ages into the next tier).
`RateLimits()`'s own class default equals the "trên 12 tháng" preset.

| Tier | posts/day | comments/day | post gap | comment gap |
|---|---|---|---|---|
| Dưới 1 tháng | 5 | 7 | 2–3.5h | 1.5–3h |
| Dưới 3 tháng | 8 | 10 | 1.75–2.5h | 1–2h |
| Dưới 6 tháng | 12 | 15 | 1.25–1.6h | 0.6–1.25h |
| Dưới 12 tháng | 20 | 25 | 0.75–0.95h | 0.35–0.75h |
| Trên 12 tháng | 30 | 35 | 0.5–0.62h | 0.25–0.5h |

`posts_per_day`/`comments_per_day` and both gap columns are numbers the
project owner specified directly (2026-09-10); `comments_per_hour`/
`likes_per_hour` (not shown above) are still derived by scaling ratios,
same as before. **`min_delay_seconds`/`max_delay_seconds` split into
separate `post_*`/`comment_*` pairs this same day** — found while
debugging why a real account's job/candidate sync backlog never drained:
`comments_per_day` has always been set higher than `posts_per_day` at
every tier, but a single shared gap for both made the comment count
mathematically unable to fit inside a day (e.g. 35 comments needing a
shared 1-2h gap would need up to 68 hours). Each tier's post/comment max
gap above was also trimmed down from the owner's own first draft, just
enough that its target daily count fits inside an 18-hour active window
(quiet hours are 2am-6am = 20h awake, minus a 10% safety margin) — see
`ACCOUNT_AGE_TIERS`'s docstring for the exact reasoning. `like` reuses
the `comment_*` pair (no separate schedule/numbers exist for it).

**Deliberately more conservative than the blog sources above** (which
suggest far higher daily volumes and much shorter gaps) — those sources
are written by companies selling automation tools, have no visibility
into Meta's real detection thresholds, and openly contradict each other
by 2-10x. Until there's a real incident (or a more trustworthy source)
pointing the other way, this project treats the *narrowest* published
"safe" number as a ceiling, not the widest.

## Pacing rules

1. Delay between actions is **randomized**, not fixed — draw from a range
   (`RateLimits.post_min/max_delay_seconds` for posts, `comment_min/max_
   delay_seconds` for comments/likes — split into separate pairs
   2026-09-10, see the tier table above) rather than sleeping a constant
   duration. **This is
   now actually enforced** by `human_bot/safety.py`'s `RateLimiter`
   (`_last_action_gap_ok()`, checked inside `can_proceed()`) — before
   2026-09-07 these two fields existed but were never wired up anywhere
   (the one call site, `RateLimiter.jittered_delay()`, was a blocking
   `time.sleep()` left commented out in `human_bot/agent.py`, since a
   multi-hour blocking sleep inside a request handler would hang the
   caller). The fix follows the "Enforcement point" rule below: on the
   next action, if the randomized gap from the previous one hasn't
   elapsed yet, the task is **refused immediately** with
   `rate_limited:min_delay_seconds gap not elapsed yet, wait ~Ns` —
   never a blocking wait. Raised from an earlier, unenforced 90-400s
   default to 1-2 hours after cross-referencing external reports (shared
   2026-09-07) suggesting even 10-20 minutes between Facebook actions
   reads as automated to its abuse systems.
2. Concentrate activity within plausible waking hours for the account's
   apparent timezone; avoid scheduling dense activity between roughly
   2am–6am local time (`DataSyncConfig.quiet_hour_start/end_local`,
   changed from 1am to 2am start on 2026-09-10 per the project owner).
3. Never schedule action batches that repeat at an exact fixed cadence
   (e.g. "every exactly 30 minutes") — jitter the schedule itself, not just
   the action delay.
4. Vary action order/mix where possible (a like, then later a comment)
   rather than always the same action type back-to-back.

## Enforcement point

The human_bot Executor Agent must check the account's rolling usage against
these limits **before** opening the browser for a new task (see
`docs/agents/human-bot-executor.md`, step 2) and refuse the task rather
than queue and wait.

## Relationship to Safety Monitor

The Safety Monitor (see `docs/agents/safety-monitor.md`) treats an account
that is *repeatedly* hitting its limit as a signal to tighten that
account's limits further, independent of whether an actual anomaly has
occurred yet.
