---
title: System Architecture
audience: AI agents + engineers
language: English (technical file — see /README.md for project rules)
---

# System Architecture — human_bot (Facebook Automation)

## 1. Purpose

`human_bot` is the execution layer that performs real actions on Facebook
(post, comment, reply, like) on behalf of a multi-agent system orchestrated
by n8n. It is built on **plain [Playwright](https://playwright.dev/python/)**,
not an LLM-driven agent — every action's exact click-by-click steps are
recorded once by a human operator with Playwright Codegen (see
`docs/skills/facebook-custom-actions.md`), then implemented as deterministic
async functions. There is nothing for an AI to decide once the steps are
known, so running one for every action would only add cost, latency, and a
chance of misclicking.

[browser-use](https://github.com/browser-use/browser-use) (LLM-driven
browser automation) was the original design and is kept as a **reserved
fallback** (`human_bot/llm.py`) for when a recorded selector breaks and no
one has re-recorded it yet — see `docs/skills/vision-fallback.md`. It is
not used in the normal path. See `/docs/research/browser-use.md`
(Vietnamese, descriptive research notes) for the original technology
evaluation that led here.

## 2. Components

| Component | Role | Has browser? | Has independent judgment? |
|---|---|---|---|
| n8n | Orchestration: scheduling, triggers, queueing, retries, logging | No | No (rule-based workflow) |
| Content Strategist Agent | Decides *what* to post/comment and drafts the text | No | Yes (LLM) |
| human_bot Executor Agent | Executes one concrete, pre-decided action | Yes (plain Playwright) | No — intentionally deterministic, no LLM in the normal path |
| Safety Monitor | Watches results/logs for ban/restriction signals, pauses accounts | No | Partial (rule-based + optional LLM on screenshots) |

Full agent specs: `docs/agents/content-strategist.md`,
`docs/agents/human-bot-executor.md`, `docs/agents/safety-monitor.md`.

## 3. Data flow

```
n8n (schedule/trigger)
   │
   ▼
Content Strategist Agent (LLM only)
   │  produces a structured Task JSON:
   │  { action, account_id, target_url, content, media?, reasoning }
   ▼
n8n → HTTP POST /tasks → human_bot FastAPI service (long-running process)
   │
   ▼
human_bot Executor Agent (plain Playwright, no LLM)
   │  reuses the account's ALREADY-OPEN persistent browser (see section 3b)
   │  dispatches directly to the matching function in human_bot/actions.py
   │  (see skills/facebook-custom-actions.md) by action name — no AI
   │  decides which tool to call, agent.py's dispatch table does
   │  applies pacing rules (see skills/rate-limiting-pacing.md)
   │  watches for anomalies (see skills/anomaly-detection.md)
   ▼
TaskResult JSON { success, message, screenshot_path, timestamp }
   │
   ▼
n8n logs result → Safety Monitor inspects → may pause account
```

n8n never talks to a browser or to browser-use directly — it only ever
calls the one HTTP endpoint (`POST /tasks`) on the human_bot service.
Everything about "when to act" (the cron schedule, the trigger condition)
lives in n8n; everything about "how to act on Facebook" lives behind that
one endpoint.

## 3b. Persistent browser (runs 24/7, not launched per task)

`human_bot/service.py` is meant to run continuously (e.g. under systemd,
pm2, or a long-running Docker container) rather than being started fresh
for each task. On startup it pre-launches one already-logged-in Playwright
browser context per active account (see `human_bot/browser_pool.py`) and
keeps each one open for the life of the process. Each incoming
`POST /tasks` call reuses that same browser page instead of paying
browser-launch cost or restarting the account's session on every action.

This is a deliberate choice, not just a performance optimization: a
browser that opens and closes for every single action looks less like a
continuously-present human than one that stays open and simply acts from
time to time — see `docs/skills/rate-limiting-pacing.md`.

Trade-off: unlike an LLM agent's system prompt, there is no "reload" step
needed for a plain function — editing `human_bot/actions.py` takes effect
on the very next call automatically (Python re-imports are not needed
since the process reads the current code, but a running process DOES need
a restart to pick up an edited `.py` file — restart the whole service, or
call an account's `AccountSession.restart_session()` for a fresh browser
without restarting the process, e.g. if a page seems stuck).

## 3c. Side B integration — pull model, not push (poller/dedup/schedule store implemented 2026-09-04)

The original assumption in section 3 ("n8n (schedule/trigger)" feeding the
Content Strategist Agent) had side B (the team supplying source data)
**push** data to this system by calling `POST /tasks` directly. Side B has
since said they want the opposite: **this system pulls** — call an API on
side B's end, determine whether the data returned is new or already
processed, then post immediately or schedule it for later.

This doesn't replace anything already built — `POST /tasks` stays exactly
as-is (still useful for `/admin`'s manual posting and for anything that
genuinely wants to push a task in). It changes how the Content Strategist
Agent's raw input arrives: instead of being handed to `normalize_signal()`
(see `docs/agents/content-strategist.md`, "Implementation plan") by an
inbound request, it's *fetched* by a new component on our side. Sketch:

```
(new) B-data poller — runs inside human_bot/service.py's own long-running
process (it already stays up 24/7, see section 3b — no reason to add a
second service for this), on a timer:
   │
   ▼
Call side B's API (GET or whatever they expose)
   │
   ▼
Filter against a locally-tracked "already processed" state (which items
have we seen before — a small local store, same file-based style as
accounts/, content_queue/, runtime_config.json; exact shape depends on
what side B's data looks like, see open questions below)
   │  new items only
   ▼
Content Strategist Agent: normalize_signal() → draft content (as already
planned)
   │
   ▼
Post now (stage into content_queue/ for review, or call run_task()
directly in-process once trusted — see content-strategist.md) — OR write
into a new scheduled-tasks store with a target time, checked by a small
due-task loop on the same timer
```

### Decisions (2026-09-04, from the project owner)

1. **Dedup key: `id` + `timestamp`, cache partitioned by day.** Side B's
   data has both fields. Store fetched items in a local, per-day cache
   (e.g. `data_sync_cache/2026-09-04.json` — same file-based style as
   `content_queue/`). On each poll: compare each fetched item's `id`
   against the cache; a match means already-seen (skip it, don't
   re-post); no match means genuinely new (save it into today's cache
   file, then hand off to scheduling below). Old cache files (past
   whatever retention window side B's data realistically reaches back to
   — needs a number once the API is confirmed, see below) get pruned
   periodically so the store doesn't grow forever.
2. **Filtering: side B doesn't have this yet — the project owner will
   propose adding query filters** (so this system doesn't have to fetch
   and locally diff the *entire* dataset every poll) once their API is
   further along.
3. **Scheduling is entirely this system's own decision**, not something
   side B supplies. Design: a sequential, randomized chain — the first new
   item gets a randomized post time, each subsequent item's post time is
   `previous item's post time + a random gap` (drawn from a range, not a
   fixed offset) — same "randomize, never fixed cadence" principle as
   `docs/skills/rate-limiting-pacing.md` already states for action-to-
   action delays, just applied one level up (post-to-post, not just
   click-to-click within one post).
4. **Two distinct data shapes from side B, two different postings:**
   - **Group posts** — each new item gets posted into **every group this
     account has joined**, one at a time, spaced by the randomized gap
     from point 3 above (never all at once). This is a broadcast, so it
     directly runs into the exact risk flagged in
     `docs/skills/group-targeting.md`'s pacing notes ("near-identical text
     across many groups in a short window is the fastest flag") — **the
     Content Strategist Agent must vary the wording per group** when
     drafting for this fan-out, not reuse the identical string across
     every group's post. This is now a hard requirement, not a nice-to-
     have, given the broadcast design.
   - **Comment replies** — each new item carries a link to the target
     post; this system opens that link and replies there (maps to
     `comment_on_friend_post` or `comment_on_group_post` in
     `human_bot/actions.py` depending on whether the URL is a group post
     or not — both still TODO).

### Side B's real API (2026-09-04, from `data-ingestion`'s `docs/API.md`)

Base URL `http://localhost:3100` (per-deploy), JSON/UTF-8, all timestamps
ISO 8601 UTC. Auth: `Authorization: Bearer <API_TOKEN>` — **currently one
single unscoped token that opens the entire read+write surface**, not a
per-client scoped key; side B's own doc flags this as something to fix
before handing the token to a third party, worth keeping in mind for
whoever owns that `.env` value on our side too.

Three read endpoints, identical shape: `GET /api/jobs` (job postings),
`GET /api/candidates` (people looking for work), `GET /api/content`
(material to draft posts from). **Decided 2026-09-04: `/api/content` is
out of scope for this project** — it's for a separate fanpage-content use
case, not this system's job/candidate outreach flow. Noted here so it
isn't accidentally wired in later; only `/api/jobs` and `/api/candidates`
matter to `human_bot`.

- **"Group post" data → `/api/jobs`** — drafted from a job posting, not
  received pre-written. If a job record ever carries `attributes` with
  `canRepublish: false` (defined on `/api/content` items in the API doc;
  unconfirmed whether `/api/jobs` uses the same flag — verify against a
  real response before assuming either way) treat it the same: never
  republish verbatim, always compose original wording, credit
  `attributes.attribution` when quoting. This makes the "vary wording per
  group" requirement from earlier even more load-bearing regardless — not
  just an anti-spam nicety, potentially a same-source republish rule too.
- **"Reply comment" data → `/api/candidates`**, exactly matching this
  API's own documented use case ("Gợi ý cho tool comment/inbox ứng viên").
  Each candidate record's `url` is the link to their original Facebook
  post — reply there. The doc's recommended flow, worth following as-is:
  filter to `confidence >= 0.8` (below that, the classifier's own
  extraction is unreliable) and skip anyone already reached out to; the
  same phone number (`attributes.contact`) can appear under multiple
  `id`s (a person's post scraped from 3 groups = 3 different records) —
  **dedupe by `attributes.contact`, not just by `id`**, before deciding
  who to reply to, or the same person gets messaged multiple times.
  `seen_count` high usually means a spam broker repost, not a real
  candidate — deprioritize those. Filter by `published_at`, not
  `last_seen_at`, when excluding old posts — `since`/`last_seen_at`
  re-surfaces old records that were merely seen again elsewhere.

Pagination is keyset (`cursor` = last `id` seen, descending, `nextCursor`
`null` when done) — **not** offset-based, so it stays correct even if new
rows are inserted mid-pull. `id`/`external_id`/`nextCursor` are **strings**
(Postgres `BIGINT`, beyond JS's safe integer range) — treat them as
opaque strings in our dedup store too, never cast to a number. `since`
filters on `last_seen_at`; that field bumps whenever a record is
re-scraped, so `since` alone answers "what changed" not "what's brand
new" — pair it with our own `first_seen_at`/`id` check for the
"genuinely new" dedup logic from earlier.

`field`/`region`/`visa`/`jlpt` query params only match **exact strings**,
and `jobField`/`preferredRegion` are free text (the doc's own example:
`field=IT` misses `"IT - SE/BrSE Web Application (C#)"`) — safe to filter
server-side on `jlpt`/`visaType` (fixed enums), but `jobField`/
`preferredRegion` need a broad pull + local (keyword or LLM-assisted, see
below) matching on our side instead of trusting the query param alone.

**Marking content used (`POST /api/content/:id/mark-used`) needs an admin
session cookie, not the shared `API_TOKEN`** — a background service
authenticating only with the Bearer token gets `403`, not `401` (side B's
doc explicitly warns: don't write retry-on-401 logic for a 403, it's a
permissions problem, not an expired-token problem). Since our service has
no interactive login session, **track "already used/posted" state
entirely in our own local dedup cache** (already planned) rather than
depending on this endpoint — it may still be worth calling manually/from
`/admin` later, but not from the automated pull loop.

**Side B's own documented gap, relevant to us:** there is no "contacted"
state on their side yet (`candidate_leads` has no `contacted_at`) — if two
tools (or two runs after a lost local cache) reach out to the same
candidate, side B's API won't catch it. This makes our own local dedup
store (by `id` for posts, by `attributes.contact` for candidates) the
**only** thing preventing a double-contact, not a nice-to-have backstop.

Retention window for the day-partitioned cache: side B's data doesn't
document how far back a record might resurface, so start with a
conservative default (30-60 days) and adjust from observed behavior
rather than guessing a tighter number now.

### New items from the project owner (2026-09-04)

1. **`/admin` should manage the posting schedule**, not just fire
   immediate posts: list upcoming scheduled items (content, target
   group(s), scheduled time), with edit (reschedule, edit text, change
   target) and cancel. This is a UI on top of the scheduled-tasks store
   already planned above — needs that store to exist first.
2. **Category-aware group targeting, still being thought through**: post
   IT-related material into IT-interest groups, Tokutei-related material
   into Tokutei-interest groups, etc., instead of always broadcasting to
   every joined group. `attributes.jobField`/`visaType` on `/api/jobs` and
   `/api/content`'s `topicTags` are exactly the fields this would key off
   of. Not decided yet — noted here so it isn't lost; see "Where AI fits"
   below for how the free-text `jobField` problem interacts with this.
3. **Where AI actually needs to be involved:** the Content Strategist
   Agent (already planned, LLM-only, no browser access) remains the
   *only* place in this whole pipeline that needs AI — polling, dedup,
   pagination, scheduling, rate limiting, and every Facebook DOM
   interaction are deliberately deterministic code (see section 1's core
   design principle). What's new, now that real data is in view, is
   *what* that agent needs to do with it:
   - Draft original Vietnamese post text from `/api/content` /
     `/api/jobs` material (respecting `canRepublish`/`attribution`),
     varied per group when broadcasting the same underlying material.
   - Draft a personalized outreach comment/reply per `/api/candidates`
     record — this is also where the agent's own Guardrail 2 (never
     generic filler, must reference something specific to the target)
     does real work: a templated "apply here!" reply is exactly the
     spam pattern that guardrail exists to prevent, and now there's a
     concrete field (`desiredJobField`/`jlpt`/`preferredRegion`) to
     reference specifically instead.
   - For category→group routing (item 2 above): this should mostly stay
     **rule-based** (a small config mapping, same style as `ACCOUNTS` in
     `human_bot/config.py`), *not* an LLM call per item — most `jobField`
     values will match a known keyword. An LLM classification step (the
     Content Strategist Agent, or a smaller dedicated call) is only
     worth reaching for as a fallback on the long tail of free-text
     values that don't cleanly match anything — consistent with side B's
     own choice to only use an LLM (their doc notes `jobField` "do Claude
     sinh") where the input is genuinely unstructured, not for the parts
     that are already deterministic. Which model: whichever key is
     already reserved in `.env` (`ANTHROPIC_API_KEY`/`OPENAI_API_KEY`,
     via `human_bot/llm.py`'s existing provider-selection logic) —
     staying on Claude specifically would match side B's own pipeline,
     but isn't a hard requirement.

### Implemented (2026-09-04)

The poller, dedup, and schedule-management store described above are now
built, not just planned:

- `human_bot/data_sync_config.py` — `DataSyncConfig`: poll cadence, the
  `auto_fire_enabled` safety gate (default `False` — see below), randomized
  post/comment scheduling gaps, quiet hours, candidate filtering thresholds,
  cache retention. All but `base_url` are also editable live from
  `/admin` (Đồng bộ dữ liệu bên B) via `human_bot/runtime_config.py`.
- `human_bot/schedule_store.py` — `ScheduledTask`, file-based
  (`scheduled/pending|posted|failed|cancelled/`), same directory-as-status
  pattern as `content_queue.py`.
- `human_bot/data_sync.py` — the poller itself: `sync_once(account_id)`
  fetches `GET /api/jobs` and `GET /api/candidates` (keyset pagination,
  incremental `since=`), dedupes (day-partitioned id cache under
  `data_sync_cache/`, plus a separate flat index on
  `attributes.contact` so the same person isn't re-contacted across
  multiple posts), and writes `ScheduledTask`s — job posts broadcast
  across every group in the posting account's joined-groups list
  (`GroupRef(name, url)` — name kept alongside the URL so a human can
  tell which group is which; see `human_bot/config.py` and
  `/admin/groups`), candidate replies filtered by
  `candidate_min_confidence`/`candidate_max_age_days` and routed to
  `comment_on_group_post` or `comment_on_friend_post` by whether the
  candidate's `url` contains `/groups/`. `fire_due_tasks()` checks for due
  tasks and — **only if `auto_fire_enabled` is `True`** — calls
  `run_task()` to actually post; left `False` by default, matching this
  project's standing rule of never auto-triggering live Facebook actions
  without explicit human control (same reasoning as
  `docs/agents/content-strategist.md`'s staging-before-auto-post design).
  While the gate is off, everything up through scheduling still runs
  normally, so `/admin/schedule` shows exactly what *would* be posted.
- `human_bot/service.py` — two background loops added to the existing
  FastAPI `lifespan` (no new process): one calls `sync_once()` per active
  account every `poll_interval_minutes`, the other calls `fire_due_tasks()`
  every `due_check_interval_seconds`. Each iteration is wrapped so one
  failure (side B unreachable, one bad record) never kills the loop.
- `human_bot/admin.py` — new `/admin/schedule` page: list pending tasks
  (content, target, scheduled time, source), inline edit, cancel, and a
  manual "🚀 Đăng ngay" button that fires a single task immediately,
  bypassing `auto_fire_enabled` — the intended way to actually post while
  the safety gate stays off.

**Partially real as of 2026-09-05 — narrower than this section's original
plan.** `human_bot/content_strategist.py`'s `draft_group_post_variants()`
is a real, working slice of the Content Strategist Agent: when a job post
is broadcast to multiple groups, it drafts genuinely different wording per
group by calling Anthropic's Messages API directly over `httpx` (not
through `human_bot/llm.py`'s provider-selection helper — that pulls in the
optional, not-installed-by-default `browser-use` package just to
construct a `ChatAnthropic`, too heavy for one plain-text drafting call).
No `ANTHROPIC_API_KEY` in `.env`, or a failed call, silently falls back to
the same plain-template drafting that existed before — `data_sync.py`'s
behavior is unchanged until a real key is added and the service
restarted. This enforces "vary wording per group when broadcasting" (the
hard requirement from this section's decisions / `docs/skills/
group-targeting.md`) for the one case it's wired into.

Per the project owner's explicit scoping (2026-09-05): posting to one's
own profile is user-typed via `/admin/post` and posted once, so it is
**not** drafted by this agent at all — only the multi-group broadcast case
needed AI. `_draft_candidate_reply_placeholder` (candidate outreach
replies) is **still a plain template** — each candidate only gets one
message, so there was nothing to vary against; this was never built.

**Still not real, unchanged from the original plan:** `normalize_signal()`
(the input-adapter step in `docs/agents/content-strategist.md`'s
Implementation plan) does not exist — `data_sync.py` maps side-B fields to
the drafting call directly. The mechanical guardrails from that same plan
(near-duplicate check against recent posts, banned-word check) are **not
enforced in code** — only present as instructions inside the system
prompt, which is not the same thing (a prompt saying "don't do X" is not
enforcement; code checking for X is). `GET /api/jobs`'s
`attributes.canRepublish`/`attribution` applicability is also still
unconfirmed — see `docs/agents/content-strategist.md`'s "Status" section
for the full breakdown against the original plan's steps.

## 3d. Action history & reporting (SQLite, implemented 2026-09-04)

The project owner asked for reporting ("which account posted how many
times per week, into which groups") — plain files (`content_queue/`,
`scheduled/`) are fine for state that only needs to be read one item at a
time, but answering "how many" and "grouped by" questions against them
would mean writing ad-hoc scripts that re-parse every file on every
question. A real query surface was worth adding here specifically.

Chose SQLite over anything heavier, for the same reason as every other
storage decision in this project (see section 1): one person running a
handful of accounts, one process, no concurrent-writer problem to solve.
`sqlite3` is in Python's standard library — no new package, no server
process, no new deployment step. Reach for something heavier (Postgres,
a hosted DB) only if a concrete need shows up later: multiple processes
writing at once, another machine needing to query this data, or volume
that actually strains SQLite (which, for one local file, is a very high
bar).

`human_bot/db.py` — one table, `action_log` (account_id, action,
target_url, target_group_name, content, success, message, source,
source_kind, source_id, created_at). Every row is written from exactly
one place: `human_bot/agent.py`'s `run_task()`, which is already the
single choke point every action passes through — manual posts from
`/admin/post`, queued posts, `/admin/schedule`'s "Đăng ngay", the data-sync
poller's auto-fire, and direct `POST /tasks` calls (n8n) all end up
calling `run_task()`, so logging there once covers all of them rather
than needing five separate call sites to remember to log. Failed
attempts are logged too (paused account, unsupported action, rate
limited, or an exception from the action itself), not just successes —
useful for spotting a spike in one account's failures, not just counting
its wins. `TaskRequest` gained a `source` field (`manual` / `queue` /
`schedule_manual` / `schedule_auto` / `api`) plus `source_kind`/
`source_id` (carried through from a `ScheduledTask` when one exists) so a
report row can say *how* a post happened, not just that it did.

`/admin/reports` (`human_bot/admin.py`) reads this table: a KPI summary
row (total/succeeded/failed/success rate/active accounts), successful
posts per account per ISO week, posts per group, success/failure counts
per action type, and a paginated recent-activity log — all filterable by
account AND by a date-range picker (7/30/90 days/all time, added
2026-09-07) applied consistently across every table. `/admin` as a whole
(including this page) was visually upgraded 2026-09-04 — Tailwind Play
CDN for styling and htmx for in-place updates on the CRUD-heavy pages
(groups, schedule, reports, accounts), still Python/FastAPI rendering the
HTML server-side, no separate frontend. See README.md section 9 for the
full history of what's been added to `/admin` since.

## 3e. Account auto-pause (Safety Monitor behavior #1, implemented 2026-09-06/07)

`docs/agents/safety-monitor.md` specifies three behaviors; only the first
is real so far — see that file's "Status" section for the full breakdown.

Before this, `human_bot/safety.py`'s `detect_anomaly()` being triggered
only aborted the single in-flight action (a bare `RuntimeError`, caught by
`agent.py`'s generic exception handler) — the account was tried again
completely normally on the next task, with nothing stopping it from
hitting the same restriction repeatedly. Fixed by giving detection its own
exception type, `AnomalyDetected` (still raised from `actions.py`'s
`_check_anomaly_or_raise`), which `agent.py`'s `run_task()` now catches
specifically and turns into a **persistent** pause:
`human_bot/runtime_config.py`'s `set_account_paused(account_id, True)`
writes the override into `runtime_config.json`, and
`human_bot/config.py`'s `get_all_accounts()` applies it on top of every
account regardless of origin (a code-level `ACCOUNTS` entry or one
registered at `/admin/accounts`) — the same override pattern already used
for `joined_groups`. `run_task()`'s existing `account.status !=
AccountStatus.ACTIVE` check (already there, previously mostly
theoretical) is what actually blocks the next task, and it now has real
persisted state to check against — including across a service restart,
since the override lives on disk, not in a Python object's memory.

`/admin/accounts` surfaces and manages this: a status column
(Hoạt động/Tạm dừng), manual Tạm dừng/Kích hoạt lại buttons on every
account (not only ones paused automatically), and the dashboard
(`/admin`) shows a warning banner naming any currently-paused account —
the whole point of auto-pause is a human noticing promptly, so it isn't
buried one click deep at `/admin/accounts` alone. `/admin/post` also
warns if the account currently selected for composing is paused (doesn't
block scheduling — the task still safely queues behind `/admin/schedule`'s
own review step — just warns before it silently fails later).

**Not yet implemented** (behaviors #2 and #3 from
`docs/agents/safety-monitor.md`): throttling as an account's action
frequency *approaches* its configured limit (today it's binary — allowed
until `RateLimiter.can_proceed()` says no, no earlier warning), and
alerting a human operator (Slack/email/Telegram) when a pause happens —
today, finding out means opening `/admin` and seeing the warning banner or
noticing a failed task in `/admin/reports`, not receiving a push.

## 4. Why the Executor has no independent judgment

The human_bot Executor Agent is deliberately kept "dumb": it receives an
already-decided action and executes it with a standardized, pre-recorded
Playwright function, instead of reasoning freely about Facebook's UI and
content each time. This:
- makes behavior fully deterministic and predictable (same action → exact
  same steps, every time)
- costs nothing per action beyond the browser itself — no LLM call, no API
  key, in the normal path
- eliminates the chance of an agent improvising something that looks
  bot-like (e.g. rewording content live, clicking unexpected UI)

All "thinking" (what to post, when it's relevant, how to phrase it) lives in
the Content Strategist Agent, which never touches the browser.

## 5. Directory layout

```
AIAgent_w_FB/
  README.md                     # Vietnamese — project overview & how to continue
  docs/
    research/                   # Vietnamese — human-facing research notes
    architecture.md             # English — this file
    agents/                     # English — one spec per agent
    skills/                     # English — reusable skill definitions agents reload
  human_bot/                    # Python package — the Executor Agent implementation
    config.py                   # AccountConfig/RateLimits/GroupRef, get_all_accounts()
    actions.py                  # Playwright action functions (the normal path)
    humanize.py                  # human-like typing/pacing/mouse-movement config + helpers
    browser_pool.py              # persistent per-account Playwright sessions
    agent.py                     # dispatches Task JSON -> actions.py function
    safety.py                    # rate limiting + AnomalyDetected (see section 3e)
    service.py                   # FastAPI app + background loops (data sync, cleanup)
    runtime_config.py            # /admin-editable overrides, persisted to runtime_config.json
    admin.py                     # the /admin web UI (see README.md section 6 for full page list)
    content_queue.py             # file-based .txt post queue for /admin/post
    schedule_store.py            # file-based ScheduledTask store for /admin/schedule
    data_sync.py                 # side-B poller (see section 3c)
    data_sync_config.py          # DataSyncConfig for the poller above
    content_strategist.py        # AI drafting for multi-group broadcasts (see section 3c)
    media.py                     # random-meme auto-attach (media/memes/)
    db.py                        # SQLite action_log for /admin/reports (see section 3d)
    llm.py                       # reserved fallback (browser-use), not used by default
    prompt_loader.py              # reserved for the fallback path (see docs/skills/vision-fallback.md)
    bootstrap_login.py           # run by hand: one-time manual Facebook login
  accounts/                     # gitignored — per-account storage_state.json (secrets)
  content_queue/                # gitignored — pending/posted/failed/ .txt files
  scheduled/                    # gitignored — pending/posted/failed/cancelled/ ScheduledTask JSON
  data_sync_cache/              # gitignored — day-partitioned dedup cache for the poller
  media/memes/                  # meme images for the random-attach feature
  runtime_config.json           # gitignored — /admin's saved overrides
  human_bot.db                  # gitignored — SQLite action_log
  requirements.txt
  .env.example
```

Full per-file purpose (including manual/test-only scripts not listed
above): README.md section 8.

## 6. Language convention (why docs are split EN/VN)

- `README.md` and anything under `docs/research/` (descriptions, expectations,
  business context): **Vietnamese**, for the human team to read.
- Everything under `docs/agents/`, `docs/skills/`, `docs/architecture.md`,
  and all code/comments: **English**, because these files are the
  "knowledge base" an AI agent re-reads to (re)learn its role and skills —
  English keeps them precise and consistent for LLM consumption.
