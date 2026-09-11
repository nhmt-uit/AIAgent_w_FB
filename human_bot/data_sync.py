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
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from human_bot import content_strategist, schedule_store
from human_bot.config import AccountConfig, get_account
from human_bot.data_sync_config import DataSyncConfig
from human_bot.scheduling_config import SchedulingConfig
from human_bot.runtime_config import get_data_sync_config, get_joined_groups, get_scheduling_config
from human_bot.safety import RateLimiter

CACHE_ROOT = Path(__file__).resolve().parent.parent / "data_sync_cache"
STATE_PATH = CACHE_ROOT / "_state.json"
CONTACTED_PATH = CACHE_ROOT / "_contacted_contacts.json"
SYNC_STATUS_PATH = CACHE_ROOT / "_sync_status.json"

MAX_PAGES_PER_ENDPOINT = 50  # defensive cap — real pulls should be tiny once `since` is narrow


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


def _load_seen_ids(retention_days: float) -> dict[str, dict]:
    """Merge every day-file within the retention window into one lookup
    dict. Small-scale by design (this project's data volume) — loading a
    few dozen small JSON files per sync is cheap; if that ever stops being
    true, this is the function to replace with an index file instead."""
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
            seen.update(data)
    return seen


def _mark_seen(item_id: str, kind: str) -> None:
    _ensure_cache_dir()
    path = _day_cache_path(_utc_today())
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.exists() else {}
    except (OSError, json.JSONDecodeError):
        data = {}
    data[str(item_id)] = {"kind": kind, "seen_at": datetime.now(timezone.utc).isoformat()}
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


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
    CONTACTED_PATH.write_text(
        json.dumps(sorted(contacts), indent=2, ensure_ascii=False), encoding="utf-8"
    )


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
    STATE_PATH.write_text(json.dumps(state, indent=2, ensure_ascii=False), encoding="utf-8")


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
    SYNC_STATUS_PATH.write_text(json.dumps(all_status, indent=2, ensure_ascii=False), encoding="utf-8")


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


def _count_scheduled_actions_by_day(account_id: str, actions: set[str]) -> dict[date, int]:
    """How many tasks whose `action` is in `actions` this account already
    has on the books per calendar date (UTC — same simplification
    apply_quiet_hours makes), counting both PENDING (not fired yet) and
    already-POSTED ones. Both matter for the daily cap below: posted ones
    already used up today's quota, and pending ones from an earlier sync
    reserve tomorrow's (or later) quota too, so a later run the same day
    doesn't schedule right on top of them. Includes every account's tasks
    in the pending/posted directories, filtered down to this one —
    small-scale by design, matching this project's other file-based
    stores (see human_bot/schedule_store.py). Generalized from a
    post_to_group-only version (2026-09-10) so the same function backs
    the capacity check for both post and comment distribution below."""
    counts: dict[date, int] = {}
    for task in schedule_store.list_pending() + schedule_store.list_posted():
        if task.account_id != account_id or task.action not in actions:
            continue
        try:
            scheduled = datetime.fromisoformat(task.scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        d = scheduled.date()
        counts[d] = counts.get(d, 0) + 1
    return counts


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
    for this account — seeds the per-group minimum-gap check below so it
    also respects postings a PREVIOUS sync_all() call already queued,
    not only ones decided within the current call."""
    latest: dict[str, datetime] = {}
    for task in schedule_store.list_pending() + schedule_store.list_posted():
        if task.account_id != account_id or task.action != "post_to_group" or not task.target_url:
            continue
        try:
            scheduled = datetime.fromisoformat(task.scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if task.target_url not in latest or scheduled > latest[task.target_url]:
            latest[task.target_url] = scheduled
    return latest


def _last_scheduled_comment_time(account_id: str) -> datetime | None:
    """Most recent scheduled_at (pending or posted) among this account's
    OWN comment tasks (_COMMENT_ACTIONS) — same "seed from a PREVIOUS
    sync_all() call, not just the current one" reasoning as
    _last_scheduled_time_per_group() above, but account-wide rather than
    per-group: unlike posts, the comment gap floor (RateLimits.
    comment_min/max_delay_seconds, see safety.py's RateLimiter) is
    enforced per ACCOUNT, not per target post/group — see
    RateLimiter.next_allowed_at()'s docstring.

    Added 2026-09-10 after a real observed case: 3 comment tasks for the
    same account, scheduled from 3 separate sync_all() polls, landed only
    5-20 minutes apart despite comment_gap_min/max being 90-180 minutes —
    each poll's `next_comment_time` started fresh from that poll's own
    `now`, with nothing checking what a PRIOR poll had already queued."""
    latest: datetime | None = None
    for task in schedule_store.list_pending() + schedule_store.list_posted():
        if task.account_id != account_id or task.action not in _COMMENT_ACTIONS:
            continue
        try:
            scheduled = datetime.fromisoformat(task.scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if latest is None or scheduled > latest:
            latest = scheduled
    return latest


def _next_available_post_slot(
    dt: datetime,
    cfg: DataSyncConfig,
    daily_limit: int,
    day_counts: dict[date, int],
    group_url: str,
    last_group_post_at: dict[str, datetime],
) -> datetime:
    """Push `dt` forward until it satisfies, together: quiet hours, this
    account's RateLimits.posts_per_day (overflow rolls to the START of
    the next day rather than being dropped — decided 2026-09-08), and a
    minimum cfg.post_gap_min_minutes gap since the last post scheduled
    to this SAME group (the sequential chain in the caller only
    guarantees spacing between the overall last two posts, not
    specifically between two posts landing on the same group).

    Iterates because satisfying one constraint can violate another (e.g.
    rolling to the next day can land back inside quiet hours, or push
    past another group's minimum gap) — bounded so a pathological config
    (e.g. daily_limit=0) can't loop forever; whatever `dt` lands on after
    the cap is used as-is rather than crashing."""
    for _ in range(60):
        moved = False

        clamped = apply_quiet_hours(dt, cfg)
        if clamped != dt:
            dt, moved = clamped, True

        last_for_group = last_group_post_at.get(group_url)
        if last_for_group is not None:
            min_gap = timedelta(minutes=cfg.post_gap_min_minutes)
            if dt - last_for_group < min_gap:
                dt, moved = last_for_group + min_gap, True

        if day_counts.get(dt.date(), 0) >= daily_limit:
            dt = datetime.combine(dt.date() + timedelta(days=1), datetime.min.time(), tzinfo=dt.tzinfo)
            moved = True

        if not moved:
            break
    return dt


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
    today = _utc_today()

    # --- Jobs: figure out each account's remaining posts_per_day room today,
    # filter to genuinely-new jobs, then hand them out via water-filling.
    new_jobs = []
    latest_job_ts = jobs_since
    for job in jobs:
        job_ts = job.get("last_seen_at") or job.get("published_at")
        if job_ts and (latest_job_ts is None or job_ts > latest_job_ts):
            latest_job_ts = job_ts
        jid = str(job.get("id") or "")
        if jid and jid not in seen:
            new_jobs.append(job)

    # Accounts with NO joined groups excluded entirely (2026-09-11, project
    # owner's call) — confirmed live as a real bug: such an account still
    # got a water-fill share of new jobs (job_capacities only checked
    # posts_per_day, nothing about groups), but the per-group posting loop
    # below has nothing to iterate (get_joined_groups(aid) == []), so the
    # job silently produced zero posts and was still _mark_seen()'d right
    # after — permanently lost, never retried, while also taking a share
    # away from another account that actually had groups to post into.
    job_capacities = {
        aid: acc.rate_limits.posts_per_day
        - _count_scheduled_actions_by_day(aid, {"post_to_group"}).get(today, 0)
        for aid, acc in accounts.items()
        if get_joined_groups(aid)
    }
    job_assignment, deferred_jobs = _water_fill_distribute(new_jobs, job_capacities)

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
        if not cid or cid in seen:
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

    comment_capacities = {
        aid: acc.rate_limits.comments_per_day
        - _count_scheduled_actions_by_day(aid, _COMMENT_ACTIONS).get(today, 0)
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
            next_comment_time = max(next_comment_time, enforced_comment_floor)

        scheduled_posts = 0
        scheduled_comments = 0

        daily_post_limit = account.rate_limits.posts_per_day
        day_post_counts = _count_scheduled_actions_by_day(aid, {"post_to_group"})
        last_group_post_at = _last_scheduled_time_per_group(aid)

        for job in job_assignment.get(aid, []):
            jid = str(job.get("id") or "")
            # Capped to account.rate_limits.max_groups_per_post — PER
            # ACCOUNT, not a global setting (2026-09-11, project owner's
            # call: an account in fewer/newer groups may want a tighter
            # cap than one with many established groups, same as every
            # other RateLimits field). Broadcasting one job to EVERY
            # joined group unconditionally (previous behavior) is a
            # cross-posting pattern real anti-spam systems recognize
            # regardless of how much the content is reworded per group.
            # Round-robin by longest-since-last-posted (last_group_post_at,
            # seeded above from schedule_store and updated live as this
            # loop runs, so it also rotates correctly across multiple jobs
            # in the SAME sync_all() call) rather than random or a fixed
            # first-N — random risks some groups going long unfed while a
            # couple get hit repeatedly; a fixed first-N never rotates
            # past whichever groups happen to sort first. A group never
            # posted to at all (not in last_group_post_at) sorts first
            # (datetime.min), i.e. always gets priority over one posted to
            # recently.
            groups = sorted(
                get_joined_groups(aid),
                key=lambda g: last_group_post_at.get(g.url) or datetime.min.replace(tzinfo=timezone.utc),
            )[:account.rate_limits.max_groups_per_post]
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
            job_data = {"title": job.get("title"), "attributes": job.get("attributes") or {}}
            for group, content in zip(groups, variants):
                # Clamp the CHAIN variable itself (not a throwaway copy) —
                # see apply_quiet_hours()'s docstring for why this matters.
                # Also enforces the daily posts_per_day cap (overflow rolls
                # to the next day) and a minimum gap since this same
                # group's last scheduled post — see
                # _next_available_post_slot()'s docstring.
                next_post_time = _next_available_post_slot(
                    next_post_time, cfg, daily_post_limit, day_post_counts, group.url, last_group_post_at,
                )
                scheduled_at = next_post_time
                day_post_counts[scheduled_at.date()] = day_post_counts.get(scheduled_at.date(), 0) + 1
                last_group_post_at[group.url] = scheduled_at
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
                    reasoning=f"auto: new job {jid} broadcast to joined group '{group.name}'" if group.name
                    else f"auto: new job {jid} broadcast to joined group",
                    source_kind="job",
                    source_id=jid,
                    job_data=job_data,
                )
                schedule_store.add(task)
                scheduled_posts += 1
                next_post_time = next_post_time + timedelta(minutes=random.uniform(post_gap_min, post_gap_max))
            _mark_seen(jid, "job")

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

        result = {
            "jobs_fetched": len(jobs),
            "candidates_fetched": len(candidates),
            "scheduled_posts": scheduled_posts,
            "scheduled_comments": scheduled_comments,
        }
        results[aid] = result
        _record_sync_status(aid, {"last_run_at": now_iso, "status": "ok", **result})

    # Hold the cursor back to the earliest DEFERRED item's own timestamp
    # (capacity-exhausted, not yet marked seen) so it's re-fetched next
    # cycle instead of falling permanently out of the `since` window —
    # only safe to advance all the way to the latest fetched timestamp
    # when nothing was deferred.
    def _cursor(latest_ts, deferred_items):
        if not deferred_items:
            return latest_ts
        deferred_ts = [d.get("last_seen_at") or d.get("published_at") for d in deferred_items]
        deferred_ts = [t for t in deferred_ts if t]
        return min(deferred_ts) if deferred_ts else latest_ts

    jobs_cursor = _cursor(latest_job_ts, deferred_jobs)
    candidates_cursor = _cursor(latest_candidate_ts, deferred_candidates)
    if jobs_cursor:
        state["jobs_since"] = jobs_cursor
    if candidates_cursor:
        state["candidates_since"] = candidates_cursor
    _save_sync_state(state)
    prune_old_cache(cfg.cache_retention_days)

    return results


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

    from human_bot.agent import TaskRequest, run_task, rate_limit_bucket_for, resolve_group_name  # local import — avoid import cycle at module load
    from human_bot.safety import rate_limit_hard_cap_message, rate_limit_wait_message

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
        # this case, not less. rate_limit_hard_cap_message() explains why
        # in more detail, including why this can trigger even though
        # data_sync.py's own scheduler never over-books a single calendar
        # day.
        account = get_account(task.account_id)
        bucket = rate_limit_bucket_for(task.action)
        warning = None
        if account and bucket:
            warning = rate_limit_wait_message(account, bucket) or rate_limit_hard_cap_message(account, bucket)
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
