"""
Purpose of this file / Muc dich cua file nay:
EN: Polls side B's `data-ingestion` API (GET /api/jobs, GET /api/candidates
— see docs/architecture.md section 3c for the full contract) instead of
waiting for a pushed task, filters out anything already seen/handled using
a local day-partitioned cache, and turns genuinely-new records into
ScheduledTask entries (human_bot/schedule_store.py) with a randomized,
sequential post/comment time — never a burst, never a fixed cadence, same
principle as docs/skills/rate-limiting-pacing.md.

IMPORTANT — job posts broadcast to multiple groups are drafted by
human_bot/content_strategist.py's draft_group_post_variants(): genuinely
different wording per group via whichever AI provider is configured on
/admin/config's AI tab (Anthropic/OpenAI/Gemini/custom — see human_bot/
ai_client.py), silently falling back to a plain rotating-opener template
otherwise (see that module's docstring for the full fallback design).
Candidate outreach replies use side B's own GET /api/candidates/{id}/reply
(`_fetch_candidate_reply`, called from fire_due_tasks() right before a
candidate comment posts, agreed 2026-09-08) — falling back to the local
plain template (`_draft_candidate_reply_placeholder`, stashed on the task
at schedule time) if that call fails or comes back empty. Treat every
scheduled item this produces as a DRAFT to review/edit in /admin/schedule
before it fires — this is one of the reasons SchedulingConfig.auto_fire_enabled
defaults to False (see human_bot/scheduling_config.py).
VI: Goi dinh ky API cua ben B (data-ingestion) thay vi cho ho day task
sang, loc bo nhung gi da thay/da xu ly bang mot cache luu theo ngay tren
dia, va bien nhung ban ghi thuc su moi thanh ScheduledTask
(human_bot/schedule_store.py) voi thoi gian dang/comment duoc rai ngau
nhien, tuan tu — khong bao gio dang don, khong bao gio dang theo nhip co
dinh, cung nguyen tac voi docs/skills/rate-limiting-pacing.md.

QUAN TRONG — bai dang vao nhieu nhom duoc soan boi
human_bot/content_strategist.py's draft_group_post_variants(): that su
khac nhau moi nhom qua AI provider dang duoc cau hinh o /admin/config
(Anthropic/OpenAI/Gemini/custom), tu dong roi ve mau (template) don gian
neu chua co key. Tin nhan ung vien
(_draft_candidate_reply_placeholder ben duoi) van la mau don gian — moi
ung vien chi nhan 1 tin, khong co gi de bien tau. Coi moi muc lich sinh ra
o day la BAN NHAP can xem/sua trong /admin/schedule truoc khi no thuc su
chay — day cung la mot ly do SchedulingConfig.auto_fire_enabled mac dinh la
False.
"""
from __future__ import annotations

import json
import os
import random
import tempfile
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from human_bot import content_strategist, daily_limits, schedule_store
from human_bot.config import AccountConfig, GroupRef, get_account
from human_bot.data_sync_config import DataSyncConfig
from human_bot.scheduling_config import SchedulingConfig
from human_bot.runtime_config import get_data_sync_config, get_joined_groups, get_scheduling_config
from human_bot.safety import RateLimiter

CACHE_ROOT = Path(__file__).resolve().parent.parent / "data_sync_cache"
STATE_PATH = CACHE_ROOT / "_state.json"
CONTACTED_PATH = CACHE_ROOT / "_contacted_contacts.json"
SYNC_STATUS_PATH = CACHE_ROOT / "_sync_status.json"

MAX_PAGES_PER_ENDPOINT = 50  # defensive cap — real pulls should be tiny once `since` is narrow


def _atomic_write_json(path: Path, data: Any) -> None:
    """Write `data` as JSON to `path` atomically: write to a sibling temp
    file, then os.replace() it into place. Every JSON cache file this
    module owns (_state.json, the day-partitioned seen-cache,
    _contacted_contacts.json, _sync_status.json) used to write via plain
    `path.write_text(...)` — NOT atomic, so a process kill mid-write
    (routine in this project: the service is restarted after nearly
    every code change) can leave `path` truncated/invalid JSON.

    That combination caused a real production incident (2026-09-16):
    _state.json got corrupted this way, _load_sync_state() silently
    treated the read failure as "never synced before" (its documented,
    otherwise-reasonable defensive fallback), triggering a since-less
    refetch of side B's ENTIRE candidate/job history. That in turn
    permanently pinned the sync cursor to a single old, chronically-
    undeliverable item's timestamp (see _cursor()'s own docstring below)
    — every poll re-fetched and re-evaluated that whole history for 2+
    days, and at least 3 already-contacted candidates slipped past the
    local dedup cache and got a duplicate Facebook comment. os.replace()
    is atomic on both POSIX and Windows — the destination is either the
    old complete file or the new complete file, never something
    in-between, which closes off this failure mode at its source rather
    than just handling the corruption better after the fact."""
    path.parent.mkdir(parents=True, exist_ok=True)
    fd, tmp_name = tempfile.mkstemp(dir=str(path.parent), prefix=f".{path.name}.", suffix=".tmp")
    try:
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(data, f, indent=2, ensure_ascii=False)
        os.replace(tmp_name, path)
    except BaseException:
        Path(tmp_name).unlink(missing_ok=True)
        raise


# --- Dedup cache (day-partitioned, per docs/architecture.md section 3c) ---

def _ensure_cache_dir() -> None:
    CACHE_ROOT.mkdir(parents=True, exist_ok=True)


def _day_cache_path(day: date) -> Path:
    return CACHE_ROOT / f"{day.isoformat()}.json"


def _utc_today() -> date:
    """`date.today()` reads the SERVER's OS-configured local timezone,
    inconsistent with every other timestamp in this file (all explicit
    UTC, e.g. _mark_seen()'s own `seen_at` a few lines down) — if the
    server's system clock is ever set to something other than UTC (e.g.
    JST), the dedup cache's day-file boundaries would drift away from the
    UTC day boundary everything else uses. Used wherever this module
    needs "today" as a date, so day-file naming/retention stays anchored
    to UTC no matter how the host OS is configured."""
    return datetime.now(timezone.utc).date()


def _seen_key(kind: str, item_id: str) -> str:
    """The lookup key callers of _load_seen_ids() must use — NEVER the
    bare id alone. Added 2026-09-16 after finding a real, already-
    triggered collision in production data: job id "1042" and candidate
    id "1042" both genuinely exist (side B evidently uses separate id
    sequences per entity type, so an eventual collision was only a
    matter of time). The on-disk day-cache files are keyed by bare id
    with `kind` stored alongside in each entry's value (see
    _mark_seen()) — that part is UNCHANGED here, so no migration of
    existing cache files is needed; _load_seen_ids() below builds this
    composite key only in the MERGED in-memory dict it returns, reading
    each entry's own stored `kind` to do it. Before this fix, both of
    sync_all()'s dedup checks (`jid in seen` / `cid in seen`) queried
    one shared, kind-blind namespace — marking one seen could silently
    and permanently hide the OTHER kind's item with the same id, with
    no error or log anywhere. It happened to do no visible harm for
    1042 specifically only because both arrived in the SAME poll cycle
    (the in-memory `seen` snapshot used for filtering that whole cycle
    is loaded once at the top of sync_all(), before either got
    written) — a later poll seeing them at different times would not
    have been so lucky."""
    return f"{kind}:{item_id}"


def _load_seen_ids(retention_days: float) -> dict[str, dict]:
    """Merge every day-file within the retention window into one lookup
    dict, KEYED BY _seen_key(kind, id) — never the bare id, see that
    function's docstring for why. Small-scale by design (this project's
    data volume) — loading a few dozen small JSON files per sync is
    cheap; if that ever stops being true, this is the function to
    replace with an index file instead."""
    _ensure_cache_dir()
    seen: dict[str, dict] = {}
    cutoff = _utc_today() - timedelta(days=int(retention_days))
    for path in CACHE_ROOT.glob("*.json"):
        if path.name.startswith("_"):
            continue  # _state.json, _contacted_contacts.json — not a day file
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day < cutoff:
            continue
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError):
            continue
        if isinstance(data, dict):
            for raw_key, entry in data.items():
                kind = entry.get("kind", "") if isinstance(entry, dict) else ""
                # Back-compat with day-files written before this fix
                # (_mark_seen() used to store by bare id): if raw_key
                # already looks like _seen_key(kind, ...) it was written
                # by the NEW code — use it as-is. Otherwise it's a
                # legacy bare-id key; synthesize the composite key from
                # the entry's own stored `kind` so old marks still work
                # correctly instead of silently vanishing on upgrade.
                key = raw_key if kind and raw_key.startswith(f"{kind}:") else _seen_key(kind, raw_key)
                seen[key] = entry
    return seen


def _mark_seen(item_id: str, kind: str) -> None:
    """Stores under the COMPOSITE key (_seen_key(kind, item_id)), not the
    bare id — 2026-09-16 fix. Storing by bare id let a job and a
    candidate sharing the same id (confirmed real: job "1042" / candidate
    "1042") clobber EACH OTHER'S entry on disk the moment both got
    marked seen on the same day, since they'd both write to the exact
    same dict key within that day's file — see _seen_key()'s docstring
    for the full incident this was found investigating."""
    _ensure_cache_dir()
    path = _day_cache_path(_utc_today())
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data[_seen_key(kind, item_id)] = {"kind": kind, "seen_at": datetime.now(timezone.utc).isoformat()}
    _atomic_write_json(path, data)


def prune_old_cache(retention_days: float) -> int:
    """Delete day-files older than the retention window. Returns how many
    were removed. Side B's own data doesn't document how far back a
    record might resurface — see docs/architecture.md section 3c — so
    this is a conservative default, not a guarantee."""
    _ensure_cache_dir()
    cutoff = _utc_today() - timedelta(days=int(retention_days))
    removed = 0
    for path in CACHE_ROOT.glob("*.json"):
        if path.name.startswith("_"):
            continue
        try:
            day = date.fromisoformat(path.stem)
        except ValueError:
            continue
        if day < cutoff:
            path.unlink(missing_ok=True)
            removed += 1
    return removed


def _load_contacted_contacts() -> set[str]:
    """Separate, non-day-partitioned index of who's already been reached
    out to (by attributes.contact) — kept apart from the id-based cache
    above because the same person can appear under many different
    `id`s (their post scraped from several groups), and side B's own API
    doc explicitly does not track "contacted" state yet — see
    docs/architecture.md section 3c. This file is the only thing
    preventing a double-contact."""
    _ensure_cache_dir()
    if not CONTACTED_PATH.exists():
        return set()
    try:
        data = json.loads(CONTACTED_PATH.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return set()
    return set(data) if isinstance(data, list) else set()


def _mark_contacted(contact: str) -> None:
    contacts = _load_contacted_contacts()
    contacts.add(contact)
    _ensure_cache_dir()
    _atomic_write_json(CONTACTED_PATH, sorted(contacts))


def _load_sync_state() -> dict[str, Any]:
    if not STATE_PATH.exists():
        return {}
    try:
        data = json.loads(STATE_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _save_sync_state(state: dict[str, Any]) -> None:
    _ensure_cache_dir()
    _atomic_write_json(STATE_PATH, state)


# --- Last-sync outcome, per account (for /admin visibility) -----------------
#
# sync_all() used to return its outcome (or an {"error": ...} dict) purely
# to its caller — service.py's _data_sync_poll_loop() only wraps the call
# in try/except and never inspected the return value, so a handled error
# (e.g. missing DATA_INGESTION_API_TOKEN) vanished silently: no exception,
# no log, nothing on /admin. This file persists the outcome of every
# sync_all() call, per account_id (success or failure, handled or raised)
# so /admin/config can show "last sync: <time> — ok (N jobs, M candidates)
# / lỗi: <msg>" per account_id instead of requiring someone to infer it
# from whether new pending tasks showed up at /admin/schedule.

def _load_sync_status() -> dict[str, Any]:
    if not SYNC_STATUS_PATH.exists():
        return {}
    try:
        data = json.loads(SYNC_STATUS_PATH.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def _record_sync_status(account_id: str, status: dict[str, Any]) -> None:
    _ensure_cache_dir()
    all_status = _load_sync_status()
    all_status[account_id] = status
    _atomic_write_json(SYNC_STATUS_PATH, all_status)


def get_sync_status(account_id: str) -> dict[str, Any] | None:
    """Outcome of the most recent sync_all() call for this account_id, or
    None if it has never run. Shape: {"last_run_at": iso-str, "status": "ok"
    | "error", plus either the counts sync_all() normally returns or an
    "error" message}."""
    return _load_sync_status().get(account_id)


def get_all_sync_statuses() -> dict[str, Any]:
    return _load_sync_status()


# --- Fetching side B's API --------------------------------------------------

async def _fetch_all_pages(client: httpx.AsyncClient, path: str, params: dict) -> list[dict]:
    items: list[dict] = []
    cursor: str | None = None
    for _ in range(MAX_PAGES_PER_ENDPOINT):
        page_params = dict(params)
        if cursor:
            page_params["cursor"] = cursor
        resp = await client.get(path, params=page_params)
        resp.raise_for_status()
        data = resp.json()
        items.extend(data.get("items", []))
        cursor = data.get("nextCursor")
        if not cursor:
            break
    return items


def _is_too_old(published_at: str | None, max_age_days: float) -> bool:
    if not published_at:
        return False  # unknown age — don't exclude on a missing field
    try:
        published = datetime.fromisoformat(published_at.replace("Z", "+00:00"))
    except ValueError:
        return False
    return (datetime.now(timezone.utc) - published) > timedelta(days=max_age_days)


def _is_expired(expires_at: str | None, now_iso: str) -> bool:
    """2026-09-16, side B API addition to GET /api/jobs: expires_at is
    null when the job listing has no deadline. Compared as plain
    ISO-8601 UTC strings (both `expires_at` and `now_iso` are already in
    the same "...Z"/"...+00:00" UTC form side B sends and this module
    generates), same string-comparison approach sync_all() already uses
    for its own `latest_job_ts` cursor — no need for datetime parsing."""
    return bool(expires_at) and expires_at <= now_iso


def _cursor(latest_ts: str | None, deferred_items: list[dict], kind: str, max_holdback_days: float) -> str | None:
    """Where sync_all()'s jobs_since/candidates_since cursor for the NEXT
    poll comes from. Holding the cursor back to the earliest DEFERRED
    item's own timestamp (capacity-exhausted this poll, not yet marked
    seen) is what lets it be re-fetched next cycle instead of falling
    permanently out of side B's `since` window — safe to advance all the
    way to `latest_ts` only when nothing was deferred.

    `max_holdback_days` bounds how long any ONE item is allowed to hold
    the cursor hostage — added 2026-09-16 after a real incident: a
    single chronically-undeliverable candidate pinned candidates_since
    to a date over a week stale (root cause was actually _state.json
    corruption from a non-atomic write, see _atomic_write_json()'s
    docstring, but this cursor logic is what turned that one corrupted
    read into a multi-day-long, self-perpetuating loop), forcing EVERY
    poll to re-fetch and re-evaluate side B's ENTIRE history since then
    — during which at least 3 already-contacted candidates slipped past
    the local dedup cache and got duplicate Facebook comments. Past this
    many days, an individual deferred item is given up on (marked seen
    — same as any other permanently-skipped item, e.g. _is_expired()'s
    branch) rather than being allowed to freeze the whole pipeline
    indefinitely; the cursor advances past it using whatever OTHER
    deferred items (or `latest_ts`) remain. This is a real, accepted
    trade-off, not a free lunch: an item given up on this way is gone
    for good, same as any other permanently-skipped item — but a
    single stuck item blocking progress forever is strictly worse."""
    if not deferred_items:
        return latest_ts
    cutoff = datetime.now(timezone.utc) - timedelta(days=max_holdback_days)
    kept_ts = []
    for item in deferred_items:
        ts = item.get("last_seen_at") or item.get("published_at")
        if not ts:
            continue
        try:
            ts_dt = datetime.fromisoformat(ts.replace("Z", "+00:00"))
        except ValueError:
            kept_ts.append(ts)  # unparsable — don't silently drop it, fall back to old behavior
            continue
        if ts_dt < cutoff:
            item_id = str(item.get("id") or "")
            if item_id:
                _mark_seen(item_id, kind)
        else:
            kept_ts.append(ts)
    return min(kept_ts) if kept_ts else latest_ts


# --- Scheduling --------------------------------------------------------------

# Fixed +9h JST offset, not zoneinfo — same reasoning as admin.py's
# _fmt_jst() and safety.py's rate_limit_wait_message() (Japan has had no
# DST since 1951, so this is exact, not an approximation). This project's
# audience/operators are Japan-focused (see docs/architecture.md), so JST
# is the "local" this quiet-hours window actually means.
_JST_OFFSET = timedelta(hours=9)


def apply_quiet_hours(dt: datetime, cfg: DataSyncConfig) -> datetime:
    """Push a time that falls in the configured quiet window forward to
    the window's end. `dt` is always UTC (every caller builds it from
    datetime.now(timezone.utc) or a browser-converted UTC pick — see
    human_bot/admin.py's _datetime_picker_html()), but
    quiet_hour_start_local/end_local mean JST wall-clock hours (the
    operator's actual local time), NOT UTC hours — comparing dt.hour
    directly against them was the 2026-09-09 bug: an operator in Japan
    picking 10:00 JST sends 01:00 UTC, which itself falls inside the
    default 1-6 "quiet" window even though 10am is obviously not the
    middle of the night — so it got wrongly pushed to ~06:xx UTC, which
    is 15:xx JST, hours later than intended. Converting to JST first (via
    _JST_OFFSET above) before comparing/clamping, then converting the
    clamped result back to UTC, fixes this for both this manual-compose
    path and the auto side-B scheduler (data_sync.py's own loops, which
    never go through a browser at all — so a per-request browser
    timezone couldn't have fixed this on its own; the fix has to live
    here, applied uniformly to whatever's live in DataSyncConfig).
    Public (not `_`-prefixed) because human_bot/admin.py's
    manual "compose & schedule" flow (/admin/post) reuses it too — any
    scheduled task, auto or manual, gets the same quiet-hours treatment.

    IMPORTANT for callers building a chain of several scheduled items
    (post_gap/comment_gap loops in this file and admin.py's
    post_schedule_groups()): feed the RETURN VALUE back into the running
    "next_*_time" variable before adding the next gap, don't just clamp a
    throwaway copy for display. Fixed 2026-09-08 — previously every caller
    clamped a fresh copy each iteration while the underlying chain kept
    drifting through the quiet window unclamped, so several consecutive
    chain items landing inside the window each got an INDEPENDENT random
    minute here, collapsing what should have been post_gap/comment_gap-
    apart posts into a few minutes of each other. Clamping the chain
    itself means this only fires once per window entry — after that, the
    chain has already moved past window's end and later gaps compound on
    top of that corrected point normally, preserving the configured
    spacing between everything that follows."""
    jst = dt + _JST_OFFSET
    if cfg.quiet_hour_start_local <= jst.hour < cfg.quiet_hour_end_local:
        # Only hour/minute/second change here, never the date — the
        # window is always fully within one JST calendar day (e.g. 1-6),
        # so this can't accidentally jump the shifted "date" across
        # midnight before converting back below.
        jst = jst.replace(
            hour=int(cfg.quiet_hour_end_local), minute=random.randint(0, 30),
            second=0, microsecond=0,
        )
        dt = jst - _JST_OFFSET
    return dt


_COMMENT_ACTIONS = {"comment_on_group_post", "comment_on_friend_post"}
# Both map to RateLimiter's "post" bucket (agent.py's _ACTION_DISPATCH) —
# the account-wide post_min/max_delay_seconds gap applies across BOTH,
# not just post_to_group, so _last_scheduled_post_time() below (added
# 2026-09-15) has to look at both to floor next_post_time correctly.
_POST_ACTIONS = {"post_to_group", "post_to_own_profile"}

# How many EXTRA groups (beyond what a job actually needs) join the
# random-pick pool for group selection below (2026-09-15, owner request:
# strict oldest-first selection produced the exact same clusters every
# cycle — e.g. always 1,2,3 then 4,5,6 — which itself reads as a bot
# pattern even though the underlying rotation is fair). A small, fixed
# slack keeps the no-starvation guarantee intact (the longest-overdue
# groups are still always in the pool) while adding just enough variety
# that which exact groups land together isn't perfectly predictable.
_GROUP_SELECTION_POOL_SLACK = 2


def _parse_scheduled_at(iso: str) -> datetime | None:
    """Parse a ScheduledTask.scheduled_at ISO string, always returning a
    timezone-AWARE datetime (or None if unparseable) — added 2026-09-15.
    Every writer that goes through _parse_scheduled_at() at admin.py's
    compose/edit routes already normalizes to UTC (the datetime-local
    picker's JS always emits `.toISOString()`, which is always "Z"-
    suffixed), but /admin/schedule/update and .../missed/reschedule pass
    whatever raw string a form posts straight to schedule_store with no
    parsing at all — so a task's scheduled_at reaching here is only
    aware "by convention", not by any enforced guarantee. Comparing a
    naive datetime against an aware one raises TypeError, so every call
    site below that sorts/maxes parsed scheduled_at values goes through
    this instead of a bare datetime.fromisoformat()."""
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    return dt if dt.tzinfo is not None else dt.replace(tzinfo=timezone.utc)


def _count_scheduled_actions_by_day(account_id: str, actions: set[str]) -> dict[date, int]:
    """How many tasks whose `action` is in `actions` this account already
    has on the books per "ngày nghiệp vụ" (business day — 2 AM JST
    boundary, human_bot/daily_limits.py's business_day_key(); changed
    2026-09-11 from raw UTC calendar date, see the conversation this was
    changed from), counting both PENDING (not fired yet) and already-
    POSTED ones. Both matter for the daily cap below: posted ones already
    used up today's quota, and pending ones from an earlier sync reserve
    a later business day's quota too, so a later run the same business
    day doesn't schedule right on top of them. Using the SAME business-
    day definition daily_limits.py's real enforcement uses (rather than
    UTC midnight) is what makes it safe to schedule multiple business
    days ahead again below (_next_available_business_day()'s rollover) — a
    business day, once past, never retroactively changes, so a job
    locked into "ngày mai" can't get leapfrogged by a later-arriving one
    the way a rolling 24h window could. Includes every account's tasks in
    the pending/posted directories, filtered down to this one — small-
    scale by design, matching this project's other file-based stores
    (see human_bot/schedule_store.py). Generalized from a post_to_group-
    only version (2026-09-10) so the same function backs the capacity
    check for both post and comment distribution below."""
    counts: dict[date, int] = {}
    for task in schedule_store.list_pending() + schedule_store.list_posted():
        if task.account_id != account_id or task.action not in actions:
            continue
        scheduled = _parse_scheduled_at(task.scheduled_at)
        if scheduled is None:
            continue
        d = daily_limits.business_day_key(scheduled)
        counts[d] = counts.get(d, 0) + 1
    return counts


def _max_jobs_over_window(
    acc,
    day_post_counts: dict[date, int],
    today: date,
    real_used_today: int,
    max_overflow_business_days: int,
) -> int:
    """How many NEW jobs this account should be handed in one sync_all()
    poll — owner-specified formula (2026-09-17): sum this account's
    remaining post_to_group slots across "today" AND every business day
    _next_available_business_day() is allowed to overflow into
    (max_overflow_business_days, same window/same setting), THEN divide
    by max_groups_per_post (one job can broadcast into up to that many
    real posts) — rounding UP, because a day left with fewer slots than
    max_groups_per_post still fits one more job that simply posts into
    fewer groups (the existing "further capped to `available`" rule in
    sync_all()'s per-job loop below already does exactly that for a
    single job; this just makes the COUNT of jobs pulled from the
    backlog agree with it up front). Owner's own worked example: 3 slots
    today + 12 tomorrow + 12 day-after = 27, ÷ 3 groups/post = 9 (8 full
    jobs + 1 partial), not floor(27/3)=9 coincidentally exact — with a
    remainder the extra job is still counted (e.g. 25 slots ÷ 3 = 8
    remainder 1 ⇒ 9 jobs).

    Fixes a real gap found live 2026-09-17: `job_capacities` previously
    used ONLY today's leftover slot count as if it directly meant "number
    of jobs" (1 job == 1 slot, no group multiplier, no tomorrow/day-after
    at all) — never actually implemented the owner's already-agreed
    today+N-day/÷max_groups_per_post design despite the 2-day overflow
    window (`cfg.max_overflow_business_days`, data_sync_config.py) having
    existed since 2026-09-16 for the PER-JOB day-rollover check
    (_next_available_business_day()) further down. Confirmed live: account
    nhtu00 had 35 jobs pulled in one poll (its real today+2-day budget
    only supported 9), which is what natural per-post spacing then spread
    all the way out to a 4th business day — see the conversation this was
    fixed from for the full trace.

    `day_post_counts` must be this account's own
    `_count_scheduled_actions_by_day(aid, {"post_to_group"})` result —
    PENDING (from earlier polls, including today's own prior polls) AND
    POSTED both count, same reasoning as that function's own docstring:
    a slot already spoken for by an earlier poll must not be handed out
    again by this one, for tomorrow/day-after exactly as much as for
    today. `real_used_today` is `daily_limits.count_since_business_day_start()`
    — only meaningful for `today` itself (future business days have no
    real activity yet by definition)."""
    total_slots = 0
    for offset in range(max_overflow_business_days + 1):
        day = today + timedelta(days=offset)
        used = day_post_counts.get(day, 0)
        if day == today:
            used = max(used, real_used_today)
        total_slots += max(acc.rate_limits.posts_per_day - used, 0)
    per_job = acc.rate_limits.max_groups_per_post
    if per_job <= 0 or total_slots <= 0:
        return 0
    return -(-total_slots // per_job)  # ceil division


def _water_fill_distribute(items: list, capacities: dict[str, int]) -> tuple[dict[str, list], list]:
    """Split `items` across the accounts in `capacities` as evenly as
    possible WITHOUT ever giving an account more than its own remaining
    capacity for today (added 2026-09-10, per-project decision — a plain
    even split is wrong: e.g. 6 new candidates over accounts capped at
    {A: 2, B: 5} must give A exactly 2, not 3, and let B absorb the rest
    rather than exceeding A's quota).

    Classic water-filling / max-min fair share: repeatedly compute an
    equal floor-share among every account still "open" (capacity not yet
    exhausted), hand that share to ALL of them simultaneously (capped at
    each one's own remaining room), drop whichever hit their cap, and
    recompute the share for what's left among the accounts still open.
    Once fewer items remain than open accounts (share would floor to 0),
    the last few go one-by-one to whichever open account currently has
    the MOST remaining room — this is also what naturally reduces to
    "floor-split evenly, remainder to whoever has more headroom" when
    every account's capacity is generous enough that it's never actually
    the bottleneck.

    Returns (assignment, leftover): `leftover` is whatever couldn't be
    placed because every account's capacity for today is already
    exhausted — the caller must NOT mark those source items as seen (and
    must not advance the sync cursor past them), so they're picked up
    again next sync cycle once quota frees up — same "never drop, only
    delay" principle as this file's daily posts_per_day rollover."""
    assignment: dict[str, list] = {aid: [] for aid in capacities}
    assigned_count = {aid: 0 for aid in capacities}
    remaining_cap = {aid: max(0, cap) for aid, cap in capacities.items()}
    active = {aid for aid, cap in remaining_cap.items() if cap > 0}
    to_place = len(items)
    while to_place > 0 and active:
        share = to_place // len(active)
        if share == 0:
            ranked = sorted(active, key=lambda a: remaining_cap[a], reverse=True)
            for aid in ranked[:to_place]:
                assigned_count[aid] += 1
                remaining_cap[aid] -= 1
            to_place = 0
            break
        newly_full = []
        for aid in active:
            take = min(share, remaining_cap[aid])
            if take <= 0:
                continue
            assigned_count[aid] += take
            remaining_cap[aid] -= take
            to_place -= take
            if remaining_cap[aid] <= 0:
                newly_full.append(aid)
        # No stall risk here: `share >= 1` in this branch, and every
        # account in `active` has remaining_cap > 0 by construction, so
        # every account above takes at least 1 — to_place strictly
        # decreases each pass, and the `share == 0` branch above always
        # finishes off whatever's left once fewer items remain than
        # open accounts.
        active -= set(newly_full)

    it = iter(items)
    for aid, count in assigned_count.items():
        assignment[aid] = [next(it) for _ in range(count)]
    leftover = list(it)
    return assignment, leftover


def _distribute_jobs_with_sponsored_priority(
    jobs: list[dict],
    job_capacities: dict[str, int],
    sponsored_only_ids: set[str],
) -> tuple[dict[str, list], list]:
    """Split `jobs` into sponsored_by-having vs. ordinary ones and run
    `_water_fill_distribute()` TWICE — sponsored first against each
    account's FULL capacity, then ordinary jobs against whatever's left
    — instead of just sorting sponsored-first into one combined list and
    calling `_water_fill_distribute()` once (2026-09-16, owner decision).

    Why two calls: `_water_fill_distribute()` hands items out in
    CONTIGUOUS per-account blocks (see its own docstring) — the first N
    items in the input list go to whichever account is first in
    `job_capacities`, the next M to the second, and so on. Sorting
    sponsored-first into one list would risk every sponsored job landing
    on a single account (whichever happens to be first) instead of being
    spread fairly. Running water-fill once per priority tier keeps that
    tier's own fair-share behavior independent of the other tier.

    `sponsored_only_ids` (accounts with AccountConfig.sponsored_only set)
    are excluded from the SECOND (ordinary-jobs) call only — never from
    the first — so their quota can never be spent on an ordinary job,
    keeping it free for whenever a sponsored job actually arrives, even
    on a day where none has yet.

    Returns `(job_assignment, deferred_jobs)` in the same shape
    `_water_fill_distribute()` itself returns: sponsored items always
    come BEFORE ordinary items in each account's list, so the caller's
    existing sequential per-account scheduling loop (which grants
    earlier `next_post_time`/capacity to whatever's first) naturally
    posts sponsored jobs first without needing any change of its own.
    `deferred_jobs` merges leftovers from both calls — same "never drop,
    only delay" contract as _water_fill_distribute()'s own leftover."""
    sponsored_jobs = [j for j in jobs if j.get("sponsored_by")]
    ordinary_jobs = [j for j in jobs if not j.get("sponsored_by")]

    sponsored_assignment, deferred_sponsored = _water_fill_distribute(sponsored_jobs, job_capacities)
    ordinary_capacities = {
        aid: cap - len(sponsored_assignment.get(aid, []))
        for aid, cap in job_capacities.items()
        if aid not in sponsored_only_ids
    }
    ordinary_assignment, deferred_ordinary = _water_fill_distribute(ordinary_jobs, ordinary_capacities)

    job_assignment = {
        aid: sponsored_assignment.get(aid, []) + ordinary_assignment.get(aid, [])
        for aid in job_capacities
    }
    return job_assignment, deferred_sponsored + deferred_ordinary


def _effective_gap_minutes(cfg_min: float, cfg_max: float, account: AccountConfig, kind: str) -> tuple[float, float]:
    """Widen (cfg_min, cfg_max) if needed so the auto-scheduler's gap
    between two tasks never lands under this account's real RateLimiter
    floor for `kind` ("post" or "comment" — RateLimits.post_min/max_
    delay_seconds or comment_min/max_delay_seconds, split 2026-09-10; see
    safety.py's RateLimiter._last_action_gap_ok()). Without this,
    DataSyncConfig.comment_gap_min/max_minutes (default 10-45min) could
    be tighter than an account's real comment gap floor, so nearly every
    auto-scheduled batch would land tasks that fire, hit
    rate_limited:min_delay_seconds, and sit waiting anyway (harmless
    since 2026-09-08's auto-retry-with-warning fix, but pointless —
    spacing them out up front avoids the wait entirely). Never narrows
    cfg's own values, only raises the floor — a deliberately more
    generous cfg gap is left untouched."""
    if kind == "post":
        rl_min = account.rate_limits.post_min_delay_seconds / 60
        rl_max = account.rate_limits.post_max_delay_seconds / 60
    else:
        rl_min = account.rate_limits.comment_min_delay_seconds / 60
        rl_max = account.rate_limits.comment_max_delay_seconds / 60
    eff_min = max(cfg_min, rl_min)
    eff_max = max(cfg_max, rl_max, eff_min)
    return eff_min, eff_max


def _last_scheduled_time_per_group(account_id: str) -> dict[str, datetime]:
    """Most recent scheduled_at (pending or posted) per target group URL
    for this account — seeds _pick_groups_for_job()'s round-robin sort
    (least-recently-posted-first), so it also respects postings a
    PREVIOUS sync_all() call already queued, not only ones decided within
    the current call. (Used to also seed a per-group minimum-gap check —
    removed 2026-09-15, owner clarified there's no per-group timing rule,
    only the account-wide gap _last_scheduled_post_time() below floors.)"""
    latest: dict[str, datetime] = {}
    for task in schedule_store.list_pending() + schedule_store.list_posted():
        if task.account_id != account_id or task.action != "post_to_group" or not task.target_url:
            continue
        scheduled = _parse_scheduled_at(task.scheduled_at)
        if scheduled is None:
            continue
        if task.target_url not in latest or scheduled > latest[task.target_url]:
            latest[task.target_url] = scheduled
    return latest


def _last_scheduled_post_time(account_id: str) -> datetime | None:
    """Most recent scheduled_at (pending or posted) among this account's
    OWN post tasks (_POST_ACTIONS — post_to_group AND post_to_own_profile,
    both share RateLimiter's "post" bucket) — same "seed from a PREVIOUS
    sync_all() call, not just the current one" reasoning as
    _last_scheduled_comment_time() below, mirrored for posts.

    Added 2026-09-15 — owner-reported: posts scheduled from separate
    sync_all() polls landed as little as 30 minutes apart despite
    post_min/max_delay_seconds being 120-210 minutes for the account.
    Root cause: _last_scheduled_comment_time() (below) already existed
    and was already wired into next_comment_time's floor since
    2026-09-10 for the EXACT same reason — but no equivalent function or
    floor was ever added for next_post_time. Each poll's next_post_time
    started fresh from that poll's own `now`, with nothing checking what
    a PRIOR poll had already queued — identical bug, just never ported
    over to the post side."""
    latest: datetime | None = None
    for task in schedule_store.list_pending() + schedule_store.list_posted():
        if task.account_id != account_id or task.action not in _POST_ACTIONS:
            continue
        scheduled = _parse_scheduled_at(task.scheduled_at)
        if scheduled is None:
            continue
        if latest is None or scheduled > latest:
            latest = scheduled
    return latest


def _last_scheduled_comment_time(account_id: str) -> datetime | None:
    """Most recent scheduled_at (pending or posted) among this account's
    OWN comment tasks (_COMMENT_ACTIONS) — same "seed from a PREVIOUS
    sync_all() call, not just the current one" reasoning as
    _last_scheduled_time_per_group()/_last_scheduled_post_time() above,
    but account-wide rather than per-group: the comment gap floor
    (RateLimits.comment_min/max_delay_seconds, see safety.py's
    RateLimiter) is enforced per ACCOUNT, not per target post/group — see
    RateLimiter.next_allowed_at()'s docstring. (posts get BOTH: an
    account-wide floor via _last_scheduled_post_time() AND a per-group
    round-robin via _last_scheduled_time_per_group(), since post_to_group
    has a "which group" dimension comments don't.)

    Added 2026-09-10 after a real observed case: 3 comment tasks for the
    same account, scheduled from 3 separate sync_all() polls, landed only
    5-20 minutes apart despite comment_gap_min/max being 90-180 minutes —
    each poll's `next_comment_time` started fresh from that poll's own
    `now`, with nothing checking what a PRIOR poll had already queued."""
    latest: datetime | None = None
    for task in schedule_store.list_pending() + schedule_store.list_posted():
        if task.account_id != account_id or task.action not in _COMMENT_ACTIONS:
            continue
        scheduled = _parse_scheduled_at(task.scheduled_at)
        if scheduled is None:
            continue
        if latest is None or scheduled > latest:
            latest = scheduled
    return latest


def _overflow_days_remaining(current_day: date, today: date, max_overflow_business_days: int) -> int:
    """How many more business days _next_available_business_day() may
    search, counted from `current_day` up to and including the FIXED
    boundary `today + max_overflow_business_days` — not a flat N passed
    straight through regardless of where `current_day` already is.

    2026-09-18 fix: sync_all() used to pass `cfg.max_overflow_business_days`
    straight to `_next_available_business_day()` as `max_search_days` for
    EVERY job, meaning "N more days allowed from wherever this job's
    `next_post_time` currently stands" — but `next_post_time` drifts
    forward across jobs within the same poll (per-post spacing), so by
    the last job in a big batch it could already stand on, say, day+2,
    and still get N MORE days on top of that (up to day+4) — the "+N
    days" rule compounding per job instead of anchoring to one shared
    day. Confirmed live: account nhtu00 still had a few posts land 1
    business day past "today + max_overflow_business_days" even after
    _max_jobs_over_window() (this same conversation, one commit back)
    correctly capped how many JOBS got pulled in the first place — the
    job-count cap and the per-job day-search were each computed against
    a different implicit boundary.

    Returns 0 (search nothing, caller must defer) once `current_day` is
    already past the boundary — never negative, and never lets a job
    "borrow" days from beyond the fixed cutoff regardless of how far its
    own timeline has already drifted."""
    return max((today + timedelta(days=max_overflow_business_days) - current_day).days + 1, 0)


def _next_available_business_day(
    dt: datetime,
    daily_limit: int,
    day_counts: dict[date, int],
    today_key: date,
    real_used_today: int,
    max_search_days: int = 60,
) -> tuple[datetime, date, int]:
    """Tràn-ngày (2026-09-11, mang lại sau khi bỏ đi cùng đợt chuyển sang
    kẹp sàn cửa sổ trượt — xem git history cho lịch sử đầy đủ): đẩy `dt`
    tới ĐẦU "ngày nghiệp vụ" kế tiếp
    (human_bot/daily_limits.py's business_day_start(), mốc 2h sáng JST —
    KHÔNG phải nửa đêm UTC), lặp lại cho tới khi tìm được 1 ngày còn ít
    nhất 1 slot trống. AN TOÀN để khoá vào 1 ngày tương lai cụ thể ở đây
    (khác hẳn hồi còn cửa sổ trượt): một "ngày nghiệp vụ" đã qua thì
    KHÔNG BAO GIỜ tự thay đổi ngược lại, nên không có rủi ro job mới hơn
    "nẫng" mất slot của 1 ngày đã khoá cho job cũ.

    `real_used_today`: số hoạt động THẬT trong ngày nghiệp vụ HIỆN TẠI
    (`today_key`) — chỉ áp dụng cho đúng `today_key`, vì các ngày nghiệp
    vụ tương lai chưa có gì xảy ra thật (real = 0 mặc định cho chúng).

    `max_search_days` (mặc định 60, nhưng caller thật sự luôn truyền
    `DataSyncConfig.max_overflow_business_days` — mặc định 2, xem
    data_sync_config.py): giới hạn số ngày nghiệp vụ được phép dò tiếp.
    Hạ từ 60 xuống một con số nhỏ (2026-09-16, owner request) để 1
    backlog job thường lớn không thể tự đặt trước hàng chục ngày
    capacity tương lai, làm mất chỗ gần của 1 job `sponsored_by` mới tới
    cần ưu tiên — xem sync_all()'s tách sponsored/normal ở dưới.

    Trả về `(dt mới, business-day key của dt đó, số slot còn trống ở đó)`
    — số slot có thể là 0 nếu vượt quá `max_search_days` ngày tìm kiếm
    (cấu hình bệnh lý, VD daily_limit=0, HOẶC đơn giản là backlog đã lấp
    kín hết cửa sổ tìm kiếm hiện tại) — caller tự quyết định hoãn job
    trong trường hợp đó, không lặp vô hạn."""
    day_key = daily_limits.business_day_key(dt)
    for _ in range(max_search_days):
        real_used = real_used_today if day_key == today_key else 0
        available = daily_limit - max(day_counts.get(day_key, 0), real_used)
        if available > 0:
            return dt, day_key, available
        dt = daily_limits.business_day_start(dt) + timedelta(days=1)
        day_key = daily_limits.business_day_key(dt)
    return dt, day_key, 0


def _has_room_for_drifted_group(
    scheduled_day_key: date,
    post_day_key: date,
    day_counts: dict[date, int],
    daily_limit: int,
    today_key: date,
    real_used_today: int,
) -> bool:
    """Owner-reported bug 2026-09-14: for JOB posts, `_next_available_
    business_day()` above picks ONE business day (`post_day_key`) and
    checks capacity for it ONCE, before a job's groups are scheduled one
    by one. But each group's REAL slot then gets `apply_quiet_hours()`
    applied to it as the sequential chain (`next_post_time`) advances —
    a group landing right before the 2 AM JST quiet-hours window can get
    pushed to 6 AM, past the boundary into a DIFFERENT business day that
    `post_day_key`'s capacity check never covered. Observed live: 9 posts
    queued for one business day against a posts_per_day cap of 5, because
    a handful of late-drifting groups across several sync_all() calls
    each silently landed on that day without anyone re-checking it still
    had room. (An earlier version of this bug also involved a separate
    per-group minimum-gap check that has since been REMOVED entirely —
    2026-09-15, owner clarified there's no per-group timing rule at all,
    only the account-wide post_min/max_delay_seconds gap — but the
    quiet-hours drift is independent of that and still very much
    possible.)
    CANDIDATE comments had the exact same gap in an even more exposed
    form (found while fixing the job case, 2026-09-15) — that loop had NO
    day-capacity check at all beyond the once-at-the-top water-fill gate
    (comment_capacities), so this same helper is reused there too, called
    for every candidate rather than only "drifted" ones (see sync_all()'s
    comment loop for why).

    Called by sync_all()'s per-group job loop ONLY when a group's own
    `scheduled_day_key` differs from `post_day_key` — same-day groups are
    already covered by `available` (the group list itself is capped to
    it), so re-checking them here would be redundant; `post_day_key` is
    otherwise UNUSED inside this function (the comment loop passes
    `scheduled_day_key` for both, since it has no equivalent
    pre-committed "assumed day" to compare against). Returns whether
    `scheduled_day_key` still has room for one more post/comment; job
    callers stop scheduling further groups for that job the first time
    this comes back False (same "đăng vừa đủ, hết chỗ thì dừng" pattern
    already used when `available` itself runs out); the comment caller
    defers that one candidate and moves on to the next."""
    real_used = real_used_today if scheduled_day_key == today_key else 0
    return max(day_counts.get(scheduled_day_key, 0), real_used) < daily_limit


def _pick_groups_for_job(
    groups: list[GroupRef], last_group_post_at: dict[str, datetime], needed: int,
) -> list[GroupRef]:
    """Which `needed` groups (out of this account's full joined list) a
    job broadcasts to (2026-09-15, extracted for testability from
    sync_all()'s job loop — same reasoning as _has_room_for_drifted_group()
    above).

    Round-robin by longest-since-last-posted (`last_group_post_at` — a
    group never posted to at all sorts first via `datetime.min`, i.e.
    always gets priority over one posted to recently, so no group is ever
    starved), but picked via `random.sample()` from a pool slightly WIDER
    than `needed` (see _GROUP_SELECTION_POOL_SLACK) rather than a strict
    slice of the sorted list — owner request 2026-09-15: strict
    oldest-first selection produced the exact same clusters every single
    cycle (e.g. always groups 1,2,3 then 4,5,6 then 7,8,1...), which
    itself reads as a bot pattern even though the underlying rotation is
    fair. The wider pool keeps the no-starvation guarantee intact (the
    longest-overdue groups are still always IN the pool) while adding
    just enough variety that which exact groups land together isn't
    perfectly predictable. Returns fewer than `needed` if the account has
    fewer joined groups than that (never raises)."""
    sorted_by_oldest = sorted(
        groups,
        key=lambda g: last_group_post_at.get(g.url) or datetime.min.replace(tzinfo=timezone.utc),
    )
    pool = sorted_by_oldest[:needed + _GROUP_SELECTION_POOL_SLACK]
    return random.sample(pool, min(needed, len(pool)))


# --- Draft content (candidate outreach — see module docstring) --------------
# Job-post drafting (which needs per-group variation) lives in
# human_bot/content_strategist.py's draft_group_post_variants() instead.

def _format_attr(value: Any) -> str:
    """attributes.desiredJobField/preferredRegion come back from side B as
    a LIST (e.g. ["cơ khí", "thực phẩm"]), not a string — confirmed
    2026-09-08 against real API responses. Interpolating that list
    directly into an f-string used to render Python's repr
    (`['cơ khí', 'thực phẩm']`) straight into the comment text. Joining
    here is the one place every caller needs to go through instead of
    each re-implementing the same isinstance check."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value) if value else ""


# 10 variants so the same candidate attributes don't always produce the
# exact same sentence across different group posts (agreed 2026-09-08 —
# an identical comment repeated verbatim is a bot tell, same reasoning as
# the fingerprint-defense work already done for comment_on_group_post).
# Each template takes `field` (desiredJobField, always non-empty) and
# `region_clause` (either "" or " ở khu vực X" — built once by the
# caller so no template needs its own empty-region branch).
_CANDIDATE_REPLY_TEMPLATES = [
    "Chào bạn, mình thấy bạn đang tìm {field}{region_clause}, bên mình đang có một số vị trí có thể phù hợp, bạn nhắn tin trao đổi thêm nhé.",
    "Hii, bên mình đang tuyển {field}{region_clause}, ib mình gửi chi tiết nhé.",
    "Hi bạn, thấy bạn cần {field}{region_clause}, bên mình có vài vị trí đang tuyển, bạn inbox mình trao đổi thêm nha.",
    "Alo bạn, bên mình có một số đơn hàng {field}{region_clause} đang cần người, bạn qtam thì nhắn mình nhé.",
    "Bạn ơi, mình thấy bạn muốn làm {field}{region_clause}, bên mình đang tuyển vị trí tương tự, ib mình tư vấn thêm nhé.",
    "Nè bạn ơi, bên mình đang cần tuyển {field}{region_clause}, mình nghĩ nó phù hợp với bạn đó, bạn nhắn tin mình nhé.",
    "Hi bạn, có vị trí {field}{region_clause} đang tuyển bên mình, nt mình liền nha.",
    "Hi b, mình đang hỗ trợ tuyển {field}{region_clause}, thấy hợp với bạn á, bạn quan tâm thì ib nha",
    "Bạn ui, bên mình có việc {field}{region_clause} đang cần người gấp, bạn nt mình tư vấn chi tiết nha.",
    "Chào bạn, mình thấy bạn tìm {field}{region_clause}, bn ib mình trao đổi thêm he.",
]


def _draft_candidate_reply_placeholder(candidate: dict) -> str:
    attrs = candidate.get("attributes") or {}
    field_wanted = _format_attr(attrs.get("desiredJobField")) or "công việc phù hợp"
    region = _format_attr(attrs.get("preferredRegion"))
    region_clause = f" ở khu vực {region}" if region else ""
    template = random.choice(_CANDIDATE_REPLY_TEMPLATES)
    return template.format(field=field_wanted, region_clause=region_clause)


async def _fetch_candidate_reply(source_id: str, cfg: DataSyncConfig) -> str | None:
    """Fetch side B's own Claude-drafted public comment for one candidate
    (GET /api/candidates/{id}/reply, agreed 2026-09-08) — called from
    fire_due_tasks() right before a candidate comment actually posts,
    NOT from the sync loop, because side B only runs its (paid, several-
    seconds) drafting call when this endpoint is hit. Calling it here
    still means at most once per candidate: each ScheduledTask fires
    exactly once — mark_posted()/mark_failed() both move the task out of
    pending/, so schedule_store.due_tasks() never returns it again: no
    separate dedup cache needed. Returns None on any failure or an empty/
    missing "reply" field, so the caller falls back to the local
    template already stored on the task from schedule time.

    Called by fire_due_tasks() only in the branch where OUR OWN AI-provider
    rewrite (content_strategist.rewrite_candidate_reply(), stage 3) will
    NOT run for this candidate — stage 2 (this) and stage 3 are mutually
    exclusive by design as of 2026-09-10, see rewrite_candidate_reply()'s
    docstring for the full pipeline and why. Has no /admin/config toggle
    of its own; whether it gets called at all is decided entirely by that
    branch, based on DataSyncConfig.candidate_reply_ai_enabled and
    whether the active AI provider actually has a key configured."""
    token = os.environ.get("DATA_INGESTION_API_TOKEN", "")
    if not token or not source_id:
        return None
    try:
        async with httpx.AsyncClient(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        ) as client:
            resp = await client.get(f"/api/candidates/{source_id}/reply")
            resp.raise_for_status()
            data = resp.json()
    except Exception:
        return None
    reply = data.get("reply")
    return reply.strip() if isinstance(reply, str) and reply.strip() else None


# --- Main entry point ---------------------------------------------------------

async def sync_all(account_ids: list[str], cfg: DataSyncConfig | None = None) -> dict[str, dict[str, Any]]:
    """Fetch new jobs/candidates from side B ONCE for the whole poll
    cycle, then FAIR-DISTRIBUTE each genuinely-new item across
    `account_ids` (every currently-active, sync-enabled account) instead
    of each account independently re-fetching and racing to claim items
    first.

    Replaces the old per-account `sync_once(account_id, cfg)` (removed
    2026-09-10) — that design called this whole fetch+dedupe+schedule
    pipeline once PER ACCOUNT, in a loop, sharing one global "seen" id
    cache across every call. The first account processed each poll cycle
    would fetch a new job, schedule it to broadcast across its OWN
    joined groups, and mark the job's id "seen" globally — so every
    OTHER account's own sync_once() call, running moments later in the
    same loop, would see that id already in `seen` and silently skip it
    forever. With 2+ accounts, only whichever ran first ever got
    anything; every other account was starved with no error anywhere
    (the bug a real multi-account conversation surfaced). Fetching once
    and explicitly distributing here fixes that at the root.

    Distribution uses _water_fill_distribute(): each new job/candidate
    goes to whichever account(s) still have room today, split as evenly
    as capacity allows — never exceeding an account's own
    posts_per_day/comments_per_day headroom for today. Whatever can't be
    placed because EVERY account is already at capacity is left
    unmarked (not "seen") and the sync cursor is held back to their
    timestamp, so they're retried next cycle instead of being dropped.

    Never calls run_task() itself — see fire_due_tasks() / service.py
    for the separate, safety-gated step that actually posts. Safe to
    call repeatedly (idempotent aside from the randomized schedule times
    for genuinely-new items)."""
    cfg = cfg or get_data_sync_config()
    if not cfg.enabled:
        return {aid: {"skipped": "disabled"} for aid in account_ids}
    if not account_ids:
        return {}

    now_iso = datetime.now(timezone.utc).isoformat()
    token = os.environ.get("DATA_INGESTION_API_TOKEN", "")
    if not token:
        error = "DATA_INGESTION_API_TOKEN not set in .env"
        for aid in account_ids:
            _record_sync_status(aid, {"last_run_at": now_iso, "status": "error", "error": error})
        return {aid: {"error": error} for aid in account_ids}

    accounts: dict[str, AccountConfig] = {aid: get_account(aid) for aid in account_ids}

    state = _load_sync_state()
    jobs_since = state.get("jobs_since")
    candidates_since = state.get("candidates_since")

    try:
        async with httpx.AsyncClient(
            base_url=cfg.base_url,
            headers={"Authorization": f"Bearer {token}"},
            timeout=30,
        ) as client:
            jobs_params = {"limit": 200}
            if jobs_since:
                jobs_params["since"] = jobs_since
            candidates_params = {"limit": 200}
            if candidates_since:
                candidates_params["since"] = candidates_since

            jobs = await _fetch_all_pages(client, "/api/jobs", jobs_params)
            candidates = await _fetch_all_pages(client, "/api/candidates", candidates_params)
    except Exception as exc:
        for aid in account_ids:
            _record_sync_status(aid, {"last_run_at": now_iso, "status": "error", "error": str(exc)})
        raise

    seen = _load_seen_ids(cfg.cache_retention_days)
    contacted = _load_contacted_contacts()
    # "ngày nghiệp vụ" hiện tại (2 AM JST boundary), không phải ngày
    # dương lịch UTC thô — 2026-09-11, xem daily_limits.py's module
    # docstring + _count_scheduled_actions_by_day()'s docstring ngay
    # trên cho lý do đổi (khớp đúng với cách safety.py/daily_limits.py
    # thật sự enforce, cho phép mang lại cơ chế tràn-ngày an toàn).
    today = daily_limits.business_day_key(datetime.now(timezone.utc))

    # --- Jobs: figure out each account's remaining posts_per_day room today,
    # filter to genuinely-new jobs, then hand them out via water-filling.
    new_jobs = []
    latest_job_ts = jobs_since
    for job in jobs:
        job_ts = job.get("last_seen_at") or job.get("published_at")
        if job_ts and (latest_job_ts is None or job_ts > latest_job_ts):
            latest_job_ts = job_ts
        jid = str(job.get("id") or "")
        if not jid or _seen_key("job", jid) in seen:
            continue
        # expires_at (2026-09-16, side B API addition) — see _is_expired().
        # A job whose listing has already closed is fully handled here
        # (marked seen, like any other permanently-skipped item) rather
        # than deferred — re-fetching it every poll forever would be
        # pointless, it can only get MORE expired with time.
        if _is_expired(job.get("expires_at"), now_iso):
            _mark_seen(jid, "job")
            continue
        new_jobs.append(job)

    # Accounts with NO joined groups excluded entirely (2026-09-11, project
    # owner's call) — confirmed live as a real bug: such an account still
    # got a water-fill share of new jobs (job_capacities only checked
    # posts_per_day, nothing about groups), but the per-group posting loop
    # below has nothing to iterate (get_joined_groups(aid) == []), so the
    # job silently produced zero posts and was still _mark_seen()'d right
    # after — permanently lost, never retried, while also taking a share
    # away from another account that actually had groups to post into.
    # Kẹp sàn theo dữ liệu THẬT (2026-09-11) — lấy SỐ LỚN HƠN giữa "đã
    # lên lịch cho ngày nghiệp vụ hôm nay" và
    # daily_limits.count_since_business_day_start() (đếm THẬT từ mốc 2h
    # sáng JST, cùng định nghĩa "ngày" mà daily_limits.can_proceed() thật
    # sự dùng để chặn/cho phép — KHÔNG còn là cửa sổ trượt 24h nữa, xem
    # daily_limits.py's module docstring). Vì cả 2 số giờ cùng nói về
    # đúng 1 "ngày nghiệp vụ" cố định (không tự trôi như cửa sổ trượt),
    # so sánh này có ý nghĩa thật, và quan trọng hơn: một khi 1 ngày
    # nghiệp vụ đã qua, capacity của nó không bao giờ "mở lại" — đây
    # chính là điều kiện khiến việc khoá 1 job vào "ngày nghiệp vụ mai"
    # (tràn-ngày, xem _next_available_business_day() bên dưới) AN TOÀN trở
    # lại, không còn rủi ro đảo thứ tự đã gặp hồi còn dùng cửa sổ trượt.
    # Multi-day/group-aware capacity (2026-09-17, see _max_jobs_over_window()'s
    # docstring for the full "why" and the real incident this fixes) —
    # replaces the previous today-only, no-group-division count.
    job_capacities = {
        aid: _max_jobs_over_window(
            acc,
            _count_scheduled_actions_by_day(aid, {"post_to_group"}),
            today,
            daily_limits.count_since_business_day_start(acc, "post"),
            cfg.max_overflow_business_days,
        )
        for aid, acc in accounts.items()
        if get_joined_groups(aid)
    }

    sponsored_only_ids = {aid for aid, acc in accounts.items() if acc.sponsored_only}
    job_assignment, deferred_jobs = _distribute_jobs_with_sponsored_priority(
        new_jobs, job_capacities, sponsored_only_ids,
    )

    # --- Candidates: same idea, but the confidence/age/contact skip check
    # is account-independent, so it's applied ONCE up front — a candidate
    # that fails it is fully handled (marked seen right away, exactly like
    # before) and never enters the distributable pool at all.
    distributable_candidates = []
    latest_candidate_ts = candidates_since
    for cand in candidates:
        cand_ts = cand.get("last_seen_at") or cand.get("published_at")
        if cand_ts and (latest_candidate_ts is None or cand_ts > latest_candidate_ts):
            latest_candidate_ts = cand_ts
        cid = str(cand.get("id") or "")
        if not cid or _seen_key("candidate", cid) in seen:
            continue
        attrs = cand.get("attributes") or {}
        confidence = attrs.get("confidence")
        contact = attrs.get("contact")
        skip = (
            (confidence is not None and confidence < cfg.candidate_min_confidence)
            or _is_too_old(cand.get("published_at"), cfg.candidate_max_age_days)
            or not cand.get("url")
            or (contact and contact in contacted)
        )
        if skip:
            _mark_seen(cid, "candidate")  # fully handled — never re-evaluate
            continue
        distributable_candidates.append(cand)

    # Kẹp sàn theo dữ liệu THẬT — cùng lý do/cùng cách với job_capacities
    # ở trên. Không cần thêm gì khác cho comment: mỗi candidate luôn tạo
    # ĐÚNG 1 task (không "nở" ra nhiều nhóm như job), nên chỉ cần con số
    # capacity đúng là _water_fill_distribute() đã tự động defer đúng
    # phần vượt quá vào deferred_candidates (giữ cursor, lấy lại đúng thứ
    # tự ở poll sau) — không cần logic "đăng vừa đủ" như job.
    comment_capacities = {
        aid: acc.rate_limits.comments_per_day
        - max(
            _count_scheduled_actions_by_day(aid, _COMMENT_ACTIONS).get(today, 0),
            daily_limits.count_since_business_day_start(acc, "comment"),
        )
        for aid, acc in accounts.items()
    }
    candidate_assignment, deferred_candidates = _water_fill_distribute(distributable_candidates, comment_capacities)

    # --- Actually schedule each account's assigned share, using THAT
    # account's own joined groups / gap settings / existing day-so-far
    # state — same per-account logic as before, just fed a subset of
    # items instead of the full new-jobs/new-candidates list.
    results: dict[str, dict[str, Any]] = {}
    now = datetime.now(timezone.utc)
    for aid, account in accounts.items():
        post_gap_min, post_gap_max = _effective_gap_minutes(
            cfg.post_gap_min_minutes, cfg.post_gap_max_minutes, account, "post"
        )
        comment_gap_min, comment_gap_max = _effective_gap_minutes(
            cfg.comment_gap_min_minutes, cfg.comment_gap_max_minutes, account, "comment"
        )
        next_post_time = now + timedelta(minutes=random.uniform(post_gap_min, post_gap_max))
        next_comment_time = now + timedelta(minutes=random.uniform(comment_gap_min, comment_gap_max))

        # Floor next_post_time the SAME way next_comment_time is floored
        # just below (added 2026-09-10 for comments; the identical gap
        # for posts went unnoticed until 2026-09-15 — see
        # _last_scheduled_post_time()'s docstring for the observed
        # incident this fixes): without this, each poll's next_post_time
        # starts fresh from THAT poll's own `now`, so two polls'
        # independently-random gaps can land close together by chance —
        # confirmed live: posts only 30 minutes apart despite
        # post_min/max_delay_seconds being 120-210 minutes for the
        # account. Same NOTE as the comment case applies: this doesn't
        # eliminate every possible collision (a post that hasn't fired
        # yet only gets its own real RateLimiter floor once it actually
        # fires), just the specific "started fresh every poll" gap.
        last_post_at = _last_scheduled_post_time(aid)
        if last_post_at is not None:
            next_post_time = max(next_post_time, last_post_at + timedelta(minutes=post_gap_min))
        enforced_post_floor = RateLimiter(account).next_allowed_at("post")
        if enforced_post_floor is not None:
            # Same naive-vs-aware normalization as enforced_comment_floor
            # below — RateLimiter.next_allowed_at() always returns a
            # naive datetime (safety.py logs with datetime.utcnow()).
            if enforced_post_floor.tzinfo is None:
                enforced_post_floor = enforced_post_floor.replace(tzinfo=timezone.utc)
            next_post_time = max(next_post_time, enforced_post_floor)

        # Floor next_comment_time against two things this poll's fresh
        # `now + random(...)` above knows nothing about — added 2026-09-10
        # alongside _last_scheduled_comment_time() (see its docstring for
        # the observed 3-comments-5-minutes-apart incident this fixes):
        #   1. A comment already queued by a PREVIOUS sync_all() poll —
        #      without this, each poll's own next_comment_time starts
        #      fresh from ITS now, so two polls' independently-random
        #      gaps can land close together by chance.
        #   2. This account's REAL RateLimiter floor for the comment
        #      bucket (safety.py's next_allowed_at("comment")) — the last
        #      comment that actually FIRED may have posted later than its
        #      own scheduled_at (rate-limit wait, quiet hours, a service
        #      restart, ...), so its real enforcement floor can be later
        #      than "that task's scheduled_at + comment_gap_min" would
        #      suggest. Read-only (RateLimiter.next_allowed_at() never
        #      appends to the action log), safe to call just to peek.
        # NOTE: this does NOT eliminate every possible collision — a
        # comment that hasn't fired YET will only get its own real
        # RateLimiter floor recorded once it actually posts (safety.py's
        # record() rolls that gap fresh, at fire time, independently of
        # whatever this scheduler guessed) — see the conversation this
        # was written from for the full reasoning. Deliberately left
        # unaddressed for now (project owner's call, 2026-09-10): fixing
        # that would mean pinning record()'s gap to a value decided here
        # at schedule time instead of re-rolling it fresh at fire time,
        # which trades away the point of having a fire-time-independent
        # safety net at all — not done without a separate decision.
        last_comment_at = _last_scheduled_comment_time(aid)
        if last_comment_at is not None:
            next_comment_time = max(next_comment_time, last_comment_at + timedelta(minutes=comment_gap_min))
        enforced_comment_floor = RateLimiter(account).next_allowed_at("comment")
        if enforced_comment_floor is not None:
            # RateLimiter.next_allowed_at() parses a NAIVE datetime (see
            # safety.py — every timestamp it reads/writes is
            # datetime.utcnow(), never timezone-aware), but next_comment_time
            # here is timezone-AWARE (built from datetime.now(timezone.utc)
            # above) — comparing them directly raises TypeError. Confirmed
            # live 2026-09-11: this crashed sync_all() on EVERY poll cycle
            # once the account had any comment history at all (silent from
            # the operator's point of view — service.py's poll loop just
            # logs "data_sync.sync_all failed" and moves on, so nothing
            # ever got scheduled, with no obvious error visible outside the
            # log file). Normalize to aware UTC before comparing, same
            # pattern already used in daily_limits.py's
            # count_since_business_day_start() for the identical reason.
            if enforced_comment_floor.tzinfo is None:
                enforced_comment_floor = enforced_comment_floor.replace(tzinfo=timezone.utc)
            next_comment_time = max(next_comment_time, enforced_comment_floor)

        scheduled_posts = 0
        scheduled_comments = 0

        daily_post_limit = account.rate_limits.posts_per_day
        day_post_counts = _count_scheduled_actions_by_day(aid, {"post_to_group"})
        last_group_post_at = _last_scheduled_time_per_group(aid)
        # Frozen for this whole poll (2026-09-11) — scheduling doesn't
        # itself create real Facebook activity, so the account's real
        # "ngày nghiệp vụ hôm nay" post count can't change mid-loop; only
        # day_post_counts (this poll's own scheduling decisions) needs
        # live incrementing below.
        real_recent_posts = daily_limits.count_since_business_day_start(account, "post")
        # Jobs that ran out even the 60-business-day search bound in
        # _next_available_business_day() (pathological config, e.g.
        # daily_limit=0) — separate from the outer water-fill's
        # `deferred_jobs`, but needs merging into it before the cursor
        # holdback below, or a job skipped here (never _mark_seen()'d)
        # could still fall out of side B's own `since` window and never
        # get re-fetched at all.
        deferred_jobs_inner: list[dict] = []

        for job in job_assignment.get(aid, []):
            jid = str(job.get("id") or "")
            # Tràn-ngày (2026-09-11, mang lại sau khi chuyển capacity
            # sang "ngày nghiệp vụ" — xem _next_available_business_day()'s
            # docstring): tìm ngày nghiệp vụ sớm nhất (bắt đầu từ chỗ
            # `next_post_time` đang đứng) còn ít nhất 1 slot, đẩy
            # next_post_time sang đúng ngày đó nếu cần. available==0 chỉ
            # còn xảy ra khi vượt quá mốc `today + cfg.max_overflow_business_days`
            # — hoãn cả job trong trường hợp đó.
            #
            # max_search_days ĐỘNG theo NGÀY CỐ ĐỊNH, không phải hằng số
            # cfg.max_overflow_business_days truyền thẳng như trước
            # (2026-09-18 fix — real gap tìm thấy live: account nhtu00 dù
            # đã có _max_jobs_over_window() giới hạn đúng SỐ job lấy về,
            # vẫn có vài bài rớt lố 1 ngày qua khỏi "hôm nay + 2"). Lý do:
            # cfg.max_overflow_business_days truyền thẳng nghĩa là "được
            # tràn thêm N ngày kể từ vị trí next_post_time đang đứng" —
            # mà next_post_time tự trôi dần qua từng job trong CÙNG 1 lần
            # sync (do khoảng cách đăng bắt buộc), nên tới job cuối hàng
            # đợi, nó có thể đã đứng ở ngày 20 rồi và vẫn được cấp thêm 2
            # ngày NỮA (tới 22) — quy tắc "+N ngày" bị cộng dồn qua nhiều
            # job thay vì neo vào 1 mốc chung. Sửa: tính lại số ngày còn
            # được phép dò MỖI LẦN, đo từ vị trí job hiện tại tới đúng mốc
            # `today + cfg.max_overflow_business_days` (không đổi) — cạn
            # mốc thì trả 0, hoãn thẳng, không tràn thêm nữa dù job đứng ở
            # đâu.
            current_day = daily_limits.business_day_key(next_post_time)
            max_search_days = _overflow_days_remaining(current_day, today, cfg.max_overflow_business_days)
            next_post_time, post_day_key, available = _next_available_business_day(
                next_post_time, daily_post_limit, day_post_counts, today, real_recent_posts,
                max_search_days,
            )
            if available <= 0:
                deferred_jobs_inner.append(job)
                continue
            # max_groups_per_post == 0 is a legitimately saveable admin
            # setting (accounts_rate_limits_save() only rejects negative
            # values) — without this check, _pick_groups_for_job() below
            # returns [], the per-group loop never runs, and
            # groups_posted_this_job stays 0 forever, permanently
            # deferring every job for this account (2026-09-15 regression
            # from the "only mark_seen if >=1 group posted" fix below —
            # before that fix this was harmless since _mark_seen() ran
            # unconditionally). Same defer-and-move-on as `available<=0`.
            if account.rate_limits.max_groups_per_post <= 0:
                deferred_jobs_inner.append(job)
                continue
            # Capped to account.rate_limits.max_groups_per_post — PER
            # ACCOUNT, not a global setting (2026-09-11, project owner's
            # call: an account in fewer/newer groups may want a tighter
            # cap than one with many established groups, same as every
            # other RateLimits field). Broadcasting one job to EVERY
            # joined group unconditionally (previous behavior) is a
            # cross-posting pattern real anti-spam systems recognize
            # regardless of how much the content is reworded per group.
            # Further capped to `available` — 2026-09-11, project owner's
            # call: if only 2 real slots remain but the cap is 3, post to
            # those 2 now rather than deferring the whole job — the job
            # is then considered fully handled (marked seen) even though
            # it only reached 2/3 groups; it is NOT retried later to
            # "top up" the missing group.
            #
            # Selection itself: see _pick_groups_for_job()'s docstring —
            # fair round-robin (last_group_post_at seeded above from
            # schedule_store, updated live as this loop runs) with a
            # light random pick within the most-overdue pool.
            groups = _pick_groups_for_job(
                get_joined_groups(aid), last_group_post_at,
                needed=min(account.rate_limits.max_groups_per_post, available),
            )
            # Template only here, at SCHEDULE time — never AI (2026-09-10,
            # AI drafting moved to fire_due_tasks(), see
            # content_strategist.draft_single_post()'s docstring for why).
            # This content is what /admin/schedule shows in the meantime,
            # and what stays in place if AI is off/fails at fire time.
            variants = content_strategist.template_variants(job, groups)
            # Job attributes stashed on each task for fire_due_tasks() to
            # redraft with AI later — see schedule_store.ScheduledTask.
            # job_data's docstring. Small subset only, same shape
            # content_strategist._job_summary() builds for the AI prompt.
            job_data = {
                "title": job.get("title"),
                "attributes": job.get("attributes") or {},
                # Stashed purely for /admin/schedule + reports traceability
                # (2026-09-16) — lets an operator see which tasks were
                # actually sponsored-priority after the fact; not read by
                # any scheduling logic itself.
                "sponsored_by": job.get("sponsored_by"),
            }
            groups_posted_this_job = 0
            for group, content in zip(groups, variants):
                # Clamp the CHAIN variable itself (not a throwaway copy) —
                # see apply_quiet_hours()'s docstring for why this matters.
                # No per-group timing rule beyond this (removed 2026-09-15
                # — owner clarified there never was meant to be one; the
                # account-wide post_min/max_delay_seconds gap, applied via
                # the chain advancing below, is the only timing constraint
                # a group's slot needs to satisfy). The daily posts_per_day
                # cap for `post_day_key` (the day `available` was computed
                # for) is already accounted for above — but THIS group's
                # own slot can still land on a DIFFERENT business day than
                # `post_day_key` (see the comment below), which `available`
                # never checked capacity for.
                next_post_time = apply_quiet_hours(next_post_time, cfg)
                scheduled_at = next_post_time
                # Keyed by the SLOT'S OWN business day, not `post_day_key`
                # above — the quiet-hours clamp just above can still push a
                # slot past 2 AM JST into the next business day, which
                # `available` was never computed for (it only ever checked
                # `post_day_key`). Owner-reported bug 2026-09-14: this let
                # posts_per_day be silently exceeded on the day a
                # late-drifting group landed on (observed: 9 posts queued
                # for one business day against a cap of 5) — nothing here
                # re-verified capacity for that OTHER day before counting
                # the group against it. Fixed by checking here: if this
                # group drifted to a different day AND that day is already
                # at/over cap, stop this job right here (same "đăng vừa
                # đủ" pattern already used when `available` itself runs out
                # mid-job) — the remaining groups (this one included) are
                # simply not scheduled this round, no retry/top-up later.
                scheduled_day_key = daily_limits.business_day_key(scheduled_at)
                if scheduled_day_key != post_day_key and not _has_room_for_drifted_group(
                    scheduled_day_key, post_day_key, day_post_counts, daily_post_limit, today, real_recent_posts,
                ):
                    break
                day_post_counts[scheduled_day_key] = day_post_counts.get(scheduled_day_key, 0) + 1
                last_group_post_at[group.url] = scheduled_at
                # Sponsored jobs get a distinguishable reasoning prefix
                # (2026-09-16) — same traceability motivation as job_data's
                # sponsored_by key above.
                job_kind = f"sponsored job (by {job.get('sponsored_by')})" if job.get("sponsored_by") else "job"
                task = schedule_store.ScheduledTask(
                    task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
                    action="post_to_group",
                    account_id=aid,
                    scheduled_at=scheduled_at.isoformat(),
                    content=content,
                    target_url=group.url,
                    # media_path intentionally left unset here (TODO 2026-09-04):
                    # once side B's job JSON schema is confirmed to carry its own
                    # image (field name not yet known — nothing in the docs/
                    # sample payloads seen so far), map it here, e.g.
                    # media_path=job.get("image_url"). An explicit media_path set
                    # here always wins over the random-meme default — see
                    # human_bot/agent.py's run_task() — so this is the one place
                    # to change; no other file needs to know about it.
                    reasoning=f"auto: new {job_kind} {jid} broadcast to joined group '{group.name}'" if group.name
                    else f"auto: new {job_kind} {jid} broadcast to joined group",
                    source_kind="job",
                    source_id=jid,
                    job_data=job_data,
                )
                schedule_store.add(task)
                scheduled_posts += 1
                groups_posted_this_job += 1
                next_post_time = next_post_time + timedelta(minutes=random.uniform(post_gap_min, post_gap_max))
            # Only mark seen if at least one group actually got scheduled
            # (2026-09-14 — see the check above) — a job that hit the
            # day-full check on its very FIRST group would otherwise be
            # marked "handled" despite posting nothing at all, permanently
            # losing it (same class of bug already fixed for accounts with
            # 0 joined groups, see the comment near job_capacities above).
            if groups_posted_this_job > 0:
                _mark_seen(jid, "job")
            else:
                deferred_jobs_inner.append(job)

        # Merge into the OUTER deferred_jobs (mutates the same list the
        # water-fill call above returned) so the cursor holdback below
        # sees jobs deferred INSIDE this account's loop too, not just the
        # ones water-fill excluded outright before this loop even started
        # — otherwise a job skipped here (never _mark_seen()'d) could
        # still fall out of side B's own `since` window and never get
        # re-fetched at all.
        deferred_jobs.extend(deferred_jobs_inner)

        # Live-tracked comment capacity per business day (2026-09-15,
        # owner-reported: this loop used to have NO day-capacity check at
        # all — comment_capacities above only gates the WATER-FILL count
        # once, against TODAY, before this loop even starts; nothing
        # re-verified capacity as `next_comment_time` drifts forward
        # across candidates, so the exact same "group trôi sang ngày
        # khác không được kiểm tra lại" bug fixed for job posts just
        # below (see groups_posted_this_job above) was ALSO possible here
        # — actually more exposed, since posts at least had
        # _next_available_business_day()'s once-per-job check; comments
        # had nothing analogous per-item at all). Same fix shape: seed
        # from the real current state, then keep it live as this
        # account's own candidates get scheduled.
        day_comment_counts = _count_scheduled_actions_by_day(aid, _COMMENT_ACTIONS)
        real_recent_comments = daily_limits.count_since_business_day_start(account, "comment")
        deferred_candidates_inner: list[dict] = []

        for cand in candidate_assignment.get(aid, []):
            cid = str(cand.get("id") or "")
            attrs = cand.get("attributes") or {}
            url = cand.get("url")
            contact = attrs.get("contact")
            action = "comment_on_group_post" if "/groups/" in url else "comment_on_friend_post"
            # Clamp the CHAIN variable itself (not a throwaway copy) — see
            # apply_quiet_hours()'s docstring for why this matters.
            next_comment_time = apply_quiet_hours(next_comment_time, cfg)
            scheduled_at = next_comment_time
            scheduled_day_key = daily_limits.business_day_key(scheduled_at)
            # `post_day_key` is passed as `scheduled_day_key` itself here
            # (not a separately-checked "assumed day" like jobs have) —
            # unlike a job's groups, no earlier step picked a day for this
            # candidate to assume it lands on, so every candidate's
            # ACTUAL day gets checked, not just ones that "drifted" from
            # some prior decision. _has_room_for_drifted_group() ignores
            # its `post_day_key` argument internally either way (see its
            # docstring) — reused as-is rather than duplicating the exact
            # same cap/real-used arithmetic a third time.
            if not _has_room_for_drifted_group(
                scheduled_day_key, scheduled_day_key, day_comment_counts,
                account.rate_limits.comments_per_day, today, real_recent_comments,
            ):
                # Ngày này đã hết hạn mức comment — hoãn ứng viên này,
                # KHÔNG mark_seen, thử lại ở lần đồng bộ sau. `continue`
                # (không `break`) — cùng lý do job loop dùng `continue`
                # ở nhánh `available <= 0`: mỗi ứng viên còn lại trong
                # danh sách PHẢI được xét/hoãn RIÊNG (dồn hết vào
                # deferred_candidates_inner) để cursor holdback bên dưới
                # thấy đủ, không âm thầm bỏ sót ứng viên nào — `break` sẽ
                # để những ứng viên SAU candidate này lọt qua mà không hề
                # được ghi nhận là "đã hoãn" lẫn "đã xử lý".
                deferred_candidates_inner.append(cand)
                continue
            day_comment_counts[scheduled_day_key] = day_comment_counts.get(scheduled_day_key, 0) + 1
            task = schedule_store.ScheduledTask(
                task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
                action=action,
                account_id=aid,
                scheduled_at=scheduled_at.isoformat(),
                content=_draft_candidate_reply_placeholder(cand),
                target_url=url,
                reasoning=f"auto: reply to candidate {cid}",
                source_kind="candidate",
                source_id=cid,
                # Stashed for fire_due_tasks()'s AI rewrite stage — see
                # schedule_store.ScheduledTask.candidate_data's docstring.
                candidate_data={"attributes": attrs},
            )
            schedule_store.add(task)
            scheduled_comments += 1
            next_comment_time = next_comment_time + timedelta(minutes=random.uniform(comment_gap_min, comment_gap_max))
            _mark_seen(cid, "candidate")
            if contact:
                _mark_contacted(contact)

        # Same merge reasoning as deferred_jobs.extend(deferred_jobs_inner)
        # above — a candidate deferred INSIDE this loop (day full) must
        # also hold the cursor back, or it falls out of side B's `since`
        # window and is lost for good.
        deferred_candidates.extend(deferred_candidates_inner)

        result = {
            "jobs_fetched": len(jobs),
            "candidates_fetched": len(candidates),
            "scheduled_posts": scheduled_posts,
            "scheduled_comments": scheduled_comments,
        }
        results[aid] = result
        _record_sync_status(aid, {"last_run_at": now_iso, "status": "ok", **result})

    jobs_cursor = _cursor(latest_job_ts, deferred_jobs, "job", cfg.max_cursor_holdback_days)
    candidates_cursor = _cursor(latest_candidate_ts, deferred_candidates, "candidate", cfg.max_cursor_holdback_days)
    if jobs_cursor:
        state["jobs_since"] = jobs_cursor
    if candidates_cursor:
        state["candidates_since"] = candidates_cursor
    _save_sync_state(state)
    prune_old_cache(cfg.cache_retention_days)

    return results


def sweep_overdue_on_startup() -> dict[str, Any]:
    """Called EXACTLY ONCE, from human_bot/service.py's lifespan(), before
    the recurring fire_due_tasks() loop ever gets its first turn — pulls
    every pending task whose scheduled_at is already in the past AT THIS
    STARTUP MOMENT out of schedule_store's pending/ and into missed/ (see
    ScheduledTask... no, schedule_store.MISSED_DIR's docstring), instead
    of letting fire_due_tasks() auto-fire them the instant the service
    comes back up.

    Owner-reported gap (2026-09-14): if the service is off for a long
    stretch, every task whose time already passed becomes "due"
    simultaneously the moment it restarts — fire_due_tasks() itself
    already prevents a burst on any ONE account+action-type (its own
    rate-limiter gap check), but nothing stopped a pile of DIFFERENT
    accounts (or a post AND a comment on the same account, which don't
    share a gap) from firing back-to-back with zero real spacing, the
    instant the service woke up. The fix isn't "throttle the burst" —
    it's "don't auto-fire something that was already scheduled for a time
    that's now gone": an admin should look at each one and decide
    (reschedule it — by hand or via the same "find the next free slot"
    logic /admin/reports' "🔄 Lên lịch lại" uses — or drop it), same as a
    real ops team would triage a backlog rather than let it dump out
    unsupervised.

    Deliberately a ONE-TIME snapshot comparison, NOT a recurring "how
    overdue is too overdue" threshold check — explicit owner instruction:
    a task that merely becomes due mid-run (normal poll_interval lag, or
    a backlog from one rate-limited account) must NOT be treated as
    "missed"; only lateness that already existed the instant the process
    came up counts. Compares against `datetime.now(timezone.utc)` taken
    right here, once, not against anything from the previous run."""
    now = datetime.now(timezone.utc)
    swept = 0
    for task in schedule_store.list_pending():
        try:
            scheduled = datetime.fromisoformat(task.scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if scheduled.tzinfo is None:
            scheduled = scheduled.replace(tzinfo=timezone.utc)
        if scheduled <= now:
            schedule_store.mark_missed(
                task.task_id,
                f"Đã quá giờ đăng dự kiến ({task.scheduled_at}) lúc service khởi động lại "
                f"({now.isoformat()}) — có thể do service từng bị tắt. Cần admin duyệt lại.",
            )
            swept += 1
    return {"checked_at": now.isoformat(), "swept": swept}


async def fire_due_tasks(cfg: SchedulingConfig | None = None) -> dict[str, Any]:
    """Check human_bot/schedule_store.py for anything due and, ONLY if
    cfg.auto_fire_enabled, actually run it via human_bot/agent.py's
    run_task() (in-process — not an HTTP call back to our own /tasks).
    Applies to EVERY due task regardless of source — auto-scheduled from
    side B, or composed by hand at /admin/post — which is exactly why
    this gate lives in human_bot/scheduling_config.py rather than
    DataSyncConfig (moved 2026-09-07). When auto_fire_enabled is False,
    due tasks are left pending so a human can still fire them manually
    from /admin/schedule ("Đăng ngay" always works regardless of this
    gate — it's an explicit human click, same trust level as any other
    /admin action)."""
    cfg = cfg or get_scheduling_config()
    due = schedule_store.due_tasks()
    if not due:
        return {"due": 0, "fired": 0}
    if not cfg.auto_fire_enabled:
        return {"due": len(due), "fired": 0, "reason": "auto_fire_enabled is False"}

    from human_bot import daily_limits
    from human_bot.agent import TaskRequest, run_task, rate_limit_bucket_for, resolve_group_name  # local import — avoid import cycle at module load
    from human_bot.safety import rate_limit_wait_message

    data_sync_cfg = get_data_sync_config()
    fired = 0
    for task in due:
        # Cheap pre-check BEFORE calling run_task(): we already know
        # exactly when this account is allowed to act again FOR THIS
        # SAME action_type bucket ("post"/"comment"/"like" — the gap is
        # tracked per bucket, not account-wide, see safety.py's
        # RateLimiter.next_allowed_at()) — rate_limit_wait_message() just
        # re-reads its action log, no browser/Playwright involved. If
        # still blocked, skip run_task() entirely this cycle — just
        # refresh the pending task's warning banner with the current
        # remaining wait. Without this, a due task sitting on a
        # rate-limited account would get a full run_task() call (and an
        # action_log DB row) every single due_check_interval_seconds
        # (default 60s) for the ENTIRE min_delay_seconds gap (up to
        # several hours) — e.g. ~120 rows for a 2h wait — even though the
        # outcome was already knowable without attempting anything. Only
        # calls run_task() for real once the gap has actually elapsed.
        #
        # ALSO checks the hard posts_per_day/comments_per_hour/
        # comments_per_day/likes_per_hour caps (2026-09-11 — a real
        # incident: rate_limit_wait_message() only ever covers the soft
        # min_delay_seconds gap, so a task blocked by a HARD cap sailed
        # straight past this pre-check every single cycle — 44 rows in
        # 24 minutes for one blocked comment task, each one paying for a
        # full AI rewrite call first. A hard cap can stay blocked far
        # longer than the soft gap (up to the whole rolling 24h/1h
        # window), so skipping run_task() here matters even more for
        # this case, not less. daily_limits.hard_cap_message() explains
        # why in more detail (2026-09-11: moved off safety.py's own
        # rate_limit_hard_cap_message()/can_proceed(), which check a
        # rolling 24h/1h window — daily_limits.py's posts_per_day/
        # comments_per_day check is now against a "business day" instead,
        # see that module's docstring for the full reasoning).
        account = get_account(task.account_id)
        bucket = rate_limit_bucket_for(task.action)
        warning = None
        if account and bucket:
            warning = rate_limit_wait_message(account, bucket) or daily_limits.hard_cap_message(account, bucket)
        if warning:
            schedule_store.update(task.task_id, last_warning=warning)
            continue

        content = task.content
        if task.source_kind == "candidate" and task.action in ("comment_on_group_post", "comment_on_friend_post"):
            # 3-stage pipeline, stage 2/3 MUTUALLY EXCLUSIVE — see
            # content_strategist.rewrite_candidate_reply()'s docstring
            # for the full picture and why:
            #   1. content already = task.content, the local template
            #      drafted at schedule time — starting baseline.
            use_own_ai = (
                data_sync_cfg.candidate_reply_ai_enabled and content_strategist.ai_provider_configured()
            )
            if use_own_ai:
                #   3. OUR OWN AI-provider rewrite of stage 1's template —
                #      stage 2 (side B's /reply) is skipped entirely here,
                #      no point paying for both drafts when we're about
                #      to rewrite it ourselves anyway. Returns `content`
                #      UNCHANGED (never empty) on any failure, so this
                #      call is always safe to assign back.
                content = await content_strategist.rewrite_candidate_reply(
                    content, task.candidate_data, ai_enabled=True,
                )
            else:
                #   2. side B's own /reply draft — called here (not
                #      stage 3) either because the toggle is off, or it's
                #      on but the active AI provider has no key to actually
                #      rewrite with. See _fetch_candidate_reply()'s
                #      docstring for why here (not the sync loop) is the
                #      one-call-per-candidate point. Replaces stage 1's
                #      text if it returns one.
                fresh_reply = await _fetch_candidate_reply(task.source_id, data_sync_cfg)
                if fresh_reply:
                    content = fresh_reply
        elif (
            task.source_kind == "job" and task.action == "post_to_group"
            and task.job_data and data_sync_cfg.job_post_ai_enabled
        ):
            # Same "right before it actually posts" reasoning as the
            # candidate branch above, moved here 2026-09-10 — see
            # content_strategist.draft_single_post()'s docstring for the
            # full history/trade-off. Only even attempted when the toggle
            # is on; task.content (the template stashed at schedule time)
            # is left untouched otherwise, no wasted recomputation.
            group_name = resolve_group_name(task.account_id, task.target_url)
            content = await content_strategist.draft_single_post(
                task.job_data, content, group_name, ai_enabled=True,
            )

        request = TaskRequest(
            action=task.action,
            account_id=task.account_id,
            target_url=task.target_url,
            content=content,
            media_path=task.media_path,
            audience=task.audience,
            reasoning=task.reasoning,
            source="schedule_auto",
            source_kind=task.source_kind,
            source_id=task.source_id,
            # candidate tasks never set task.job_data (only job tasks do) —
            # task.candidate_data is their equivalent "raw side-B origin
            # data" slot (see schedule_store.ScheduledTask's docstrings).
            # Exactly one of the two is ever populated for a given task, so
            # sharing the single job_data column/field for both (2026-09-12,
            # "theo từng lần bình luận" report) needs no schema change.
            job_data=task.job_data or task.candidate_data,
            retry_of_log_id=task.retry_of_log_id,
        )
        result = await run_task(request)
        if result.success:
            schedule_store.mark_posted(task.task_id, result.message)
        elif result.message.startswith("rate_limited:"):
            # Rare fallback: the pre-check above just said this account
            # was free, but a concurrent action (e.g. a manual "Đăng
            # ngay" click on another due task) claimed the slot first,
            # so run_task()'s own check still caught it. Same
            # stay-pending-with-warning handling as the pre-check.
            warning = rate_limit_wait_message(account, bucket) if account and bucket else None
            schedule_store.update(task.task_id, last_warning=warning or result.message)
        else:
            schedule_store.mark_failed(task.task_id, result.message)
        fired += 1
    return {"due": len(due), "fired": fired}
