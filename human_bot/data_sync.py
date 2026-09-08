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
different wording per group via an Anthropic call when ANTHROPIC_API_KEY
is set in .env, silently falling back to a plain rotating-opener template
otherwise (see that module's docstring for the full fallback design).
Candidate outreach replies (`_draft_candidate_reply_placeholder` below)
are still a plain template — each candidate only gets one message, so
there is nothing to vary against (see the conversation that scoped
content_strategist.py to just the group-broadcast case). Treat every
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
khac nhau moi nhom qua Anthropic khi co ANTHROPIC_API_KEY trong .env, tu
dong roi ve mau (template) don gian neu chua co key. Tin nhan ung vien
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


def _load_seen_ids(retention_days: float) -> dict[str, dict]:
    """Merge every day-file within the retention window into one lookup
    dict. Small-scale by design (this project's data volume) — loading a
    few dozen small JSON files per sync is cheap; if that ever stops being
    true, this is the function to replace with an index file instead."""
    _ensure_cache_dir()
    seen: dict[str, dict] = {}
    cutoff = date.today() - timedelta(days=int(retention_days))
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
    path = _day_cache_path(date.today())
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
    cutoff = date.today() - timedelta(days=int(retention_days))
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
# sync_once() used to return its outcome (or an {"error": ...} dict) purely
# to its caller — service.py's _data_sync_poll_loop() only wraps the call
# in try/except and never inspected the return value, so a handled error
# (e.g. missing DATA_INGESTION_API_TOKEN) vanished silently: no exception,
# no log, nothing on /admin. This file persists the outcome of every
# sync_once() call (success or failure, handled or raised) so /admin/config
# can show "last sync: <time> — ok (N jobs, M candidates) / lỗi: <msg>" per
# account_id instead of requiring someone to infer it from whether new
# pending tasks showed up at /admin/schedule.

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
    """Outcome of the most recent sync_once() call for this account_id, or
    None if it has never run. Shape: {"last_run_at": iso-str, "status": "ok"
    | "error", plus either the counts sync_once() normally returns or an
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

def apply_quiet_hours(dt: datetime, cfg: DataSyncConfig) -> datetime:
    """Push a time that falls in the configured quiet window forward to
    the window's end, same UTC-as-local simplification the rest of this
    project currently makes (no per-account timezone config yet — see
    docs/skills/rate-limiting-pacing.md, this is a known limitation, not
    an oversight). Public (not `_`-prefixed) because human_bot/admin.py's
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
    if cfg.quiet_hour_start_local <= dt.hour < cfg.quiet_hour_end_local:
        dt = dt.replace(
            hour=int(cfg.quiet_hour_end_local), minute=random.randint(0, 30),
            second=0, microsecond=0,
        )
    return dt


def _count_scheduled_group_posts_by_day(account_id: str) -> dict[date, int]:
    """How many `post_to_group` tasks this account already has on the
    books per calendar date (UTC — same simplification apply_quiet_hours
    makes), counting both PENDING (not fired yet) and already-POSTED
    ones. Both matter for the daily cap below: posted ones already used
    up today's quota, and pending ones from an earlier sync_once() call
    reserve tomorrow's (or later) quota too, so a later call in the same
    day doesn't schedule right on top of them. Includes every account's
    tasks in the pending/posted directories, filtered down to this one —
    small-scale by design, matching this project's other file-based
    stores (see human_bot/schedule_store.py)."""
    counts: dict[date, int] = {}
    for task in schedule_store.list_pending() + schedule_store.list_posted():
        if task.account_id != account_id or task.action != "post_to_group":
            continue
        try:
            scheduled = datetime.fromisoformat(task.scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        d = scheduled.date()
        counts[d] = counts.get(d, 0) + 1
    return counts


def _effective_gap_minutes(cfg_min: float, cfg_max: float, account: AccountConfig) -> tuple[float, float]:
    """Widen (cfg_min, cfg_max) if needed so the auto-scheduler's gap
    between two tasks never lands under this account's real RateLimiter
    floor (RateLimits.min_delay_seconds/max_delay_seconds — enforced
    across EVERY action type on the account, not just within one chain;
    see safety.py's RateLimiter._last_action_gap_ok()). Without this,
    DataSyncConfig.comment_gap_min/max_minutes (default 10-45min) is
    routinely tighter than an account's real min_delay_seconds (1-2h+,
    raised 2026-09-07 — see RateLimits' own docstring), so nearly every
    auto-scheduled batch would land tasks that fire, hit
    rate_limited:min_delay_seconds, and sit waiting anyway (harmless
    since 2026-09-08's auto-retry-with-warning fix, but pointless —
    spacing them out up front avoids the wait entirely). Never narrows
    cfg's own values, only raises the floor — a deliberately more
    generous cfg gap is left untouched."""
    rl_min = account.rate_limits.min_delay_seconds / 60
    rl_max = account.rate_limits.max_delay_seconds / 60
    eff_min = max(cfg_min, rl_min)
    eff_max = max(cfg_max, rl_max, eff_min)
    return eff_min, eff_max


def _last_scheduled_time_per_group(account_id: str) -> dict[str, datetime]:
    """Most recent scheduled_at (pending or posted) per target group URL
    for this account — seeds the per-group minimum-gap check below so it
    also respects postings a PREVIOUS sync_once() call already queued,
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


def _draft_candidate_reply_placeholder(candidate: dict) -> str:
    attrs = candidate.get("attributes") or {}
    field_wanted = _format_attr(attrs.get("desiredJobField")) or "công việc phù hợp"
    region = _format_attr(attrs.get("preferredRegion"))
    text = f"Chào bạn, mình thấy bạn đang tìm {field_wanted}"
    if region:
        text += f" ở khu vực {region}"
    text += ", bên mình đang có một số vị trí có thể phù hợp, bạn nhắn tin trao đổi thêm nhé."
    return text


# TODO(side B contract): "suggestedReply" is a PLACEHOLDER name, agreed
# 2026-09-08 to keep as a stand-in until side B actually ships this field
# — NOT YET CONFIRMED in any real response seen so far (checked
# 2026-09-08 against live /api/candidates, no such field present). Once
# side B tells us the real field name, update this constant to match —
# that is the ONLY change needed here; _draft_candidate_reply() below
# already prefers it over the local template whenever it's a non-empty
# string. Until then this constant matches nothing, so every candidate
# keeps falling through to the local template exactly like today.
SIDE_B_REPLY_FIELD = "suggestedReply"


def _draft_candidate_reply(candidate: dict) -> str:
    """Priority order (agreed 2026-09-08, see the conversation that
    decided this): (1) side B's own suggested reply, once they actually
    send SIDE_B_REPLY_FIELD — highest quality, side B has more context on
    the candidate than we do; (2) TODO — an LLM-drafted reply tailored to
    this candidate's specific ask (visa type, region, urgency...), still
    to be researched/designed, not implemented yet; (3) the local
    template (_draft_candidate_reply_placeholder) as the last-resort
    fallback, same as the only behavior that existed before this."""
    side_b_reply = candidate.get(SIDE_B_REPLY_FIELD)
    if isinstance(side_b_reply, str) and side_b_reply.strip():
        return side_b_reply.strip()
    return _draft_candidate_reply_placeholder(candidate)


# --- Main entry point ---------------------------------------------------------

async def sync_once(account_id: str, cfg: DataSyncConfig | None = None) -> dict[str, Any]:
    """Fetch new jobs/candidates for one account, dedupe, and write new
    ScheduledTask entries — then always records the outcome via
    _record_sync_status(), success or failure, BEFORE returning/re-raising,
    so /admin/config can show it. This wraps _sync_once_inner() rather than
    recording inline at every return point, so no future edit to that
    function's body can accidentally add a new return path that skips
    recording (a real gap before this: the "missing API token" case used to
    return an {"error": ...} dict that service.py's poll loop never
    inspected, so it vanished with no trace anywhere)."""
    now_iso = datetime.now(timezone.utc).isoformat()
    try:
        result = await _sync_once_inner(account_id, cfg)
    except Exception as exc:
        _record_sync_status(account_id, {"last_run_at": now_iso, "status": "error", "error": str(exc)})
        raise
    if "error" in result:
        _record_sync_status(account_id, {"last_run_at": now_iso, "status": "error", "error": result["error"]})
    elif "skipped" not in result:
        _record_sync_status(account_id, {"last_run_at": now_iso, "status": "ok", **result})
    return result


async def _sync_once_inner(account_id: str, cfg: DataSyncConfig | None) -> dict[str, Any]:
    """Fetch new jobs/candidates for one account, dedupe, and write new
    ScheduledTask entries. Never calls run_task() itself — see
    human_bot/data_sync.py's fire_due_tasks() / human_bot/service.py for
    the separate, safety-gated step that actually posts. Safe to call
    repeatedly (idempotent aside from the randomized schedule times for
    genuinely-new items)."""
    cfg = cfg or get_data_sync_config()
    if not cfg.enabled:
        return {"skipped": "disabled"}

    account: AccountConfig = get_account(account_id)
    token = os.environ.get("DATA_INGESTION_API_TOKEN", "")
    if not token:
        return {"error": "DATA_INGESTION_API_TOKEN not set in .env"}

    state = _load_sync_state()
    jobs_since = state.get(f"{account_id}_jobs_since")
    candidates_since = state.get(f"{account_id}_candidates_since")

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

    seen = _load_seen_ids(cfg.cache_retention_days)
    contacted = _load_contacted_contacts()

    now = datetime.now(timezone.utc)
    post_gap_min, post_gap_max = _effective_gap_minutes(cfg.post_gap_min_minutes, cfg.post_gap_max_minutes, account)
    comment_gap_min, comment_gap_max = _effective_gap_minutes(
        cfg.comment_gap_min_minutes, cfg.comment_gap_max_minutes, account
    )
    next_post_time = now + timedelta(minutes=random.uniform(post_gap_min, post_gap_max))
    next_comment_time = now + timedelta(minutes=random.uniform(comment_gap_min, comment_gap_max))

    scheduled_posts = 0
    scheduled_comments = 0
    latest_job_ts = jobs_since
    latest_candidate_ts = candidates_since

    # Daily posts_per_day cap + per-group minimum gap (agreed 2026-09-08 —
    # broadcasting every new job to every joined group could otherwise
    # pile up far more posts on one account in one day than a real person
    # would ever make, regardless of how generous post_gap_min/max is).
    # Seeded from what's ALREADY on the books (other pending/posted
    # tasks) so a second sync_once() call the same day doesn't ignore
    # what the first one already committed.
    daily_post_limit = account.rate_limits.posts_per_day
    day_post_counts = _count_scheduled_group_posts_by_day(account_id)
    last_group_post_at = _last_scheduled_time_per_group(account_id)

    for job in jobs:
        jid = str(job.get("id") or "")
        job_ts = job.get("last_seen_at") or job.get("published_at")
        if job_ts and (latest_job_ts is None or job_ts > latest_job_ts):
            latest_job_ts = job_ts
        if not jid or jid in seen:
            continue
        groups = get_joined_groups(account.account_id)
        # One drafting call for ALL of this job's groups at once (not one
        # per group) — content_strategist.draft_group_post_variants() needs
        # the full group list up front to guarantee the variants it returns
        # are actually different from each other, not just independently
        # generated and coincidentally similar.
        variants = await content_strategist.draft_group_post_variants(job, groups)
        for group, content in zip(groups, variants):
            # Clamp the CHAIN variable itself (not a throwaway copy) — see
            # apply_quiet_hours()'s docstring for why this matters. Also
            # enforces the daily posts_per_day cap (overflow rolls to the
            # next day) and a minimum gap since this same group's last
            # scheduled post — see _next_available_post_slot()'s docstring.
            next_post_time = _next_available_post_slot(
                next_post_time, cfg, daily_post_limit, day_post_counts, group.url, last_group_post_at,
            )
            scheduled_at = next_post_time
            day_post_counts[scheduled_at.date()] = day_post_counts.get(scheduled_at.date(), 0) + 1
            last_group_post_at[group.url] = scheduled_at
            task = schedule_store.ScheduledTask(
                task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
                action="post_to_group",
                account_id=account_id,
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
            )
            schedule_store.add(task)
            scheduled_posts += 1
            next_post_time = next_post_time + timedelta(minutes=random.uniform(post_gap_min, post_gap_max))
        _mark_seen(jid, "job")

    for cand in candidates:
        cid = str(cand.get("id") or "")
        cand_ts = cand.get("last_seen_at") or cand.get("published_at")
        if cand_ts and (latest_candidate_ts is None or cand_ts > latest_candidate_ts):
            latest_candidate_ts = cand_ts
        if not cid or cid in seen:
            continue

        attrs = cand.get("attributes") or {}
        confidence = attrs.get("confidence")
        url = cand.get("url")
        contact = attrs.get("contact")

        skip = (
            (confidence is not None and confidence < cfg.candidate_min_confidence)
            or _is_too_old(cand.get("published_at"), cfg.candidate_max_age_days)
            or not url
            or (contact and contact in contacted)
        )
        _mark_seen(cid, "candidate")  # mark seen either way — never re-evaluate the same id again
        if skip:
            continue

        action = "comment_on_group_post" if "/groups/" in url else "comment_on_friend_post"
        # Clamp the CHAIN variable itself (not a throwaway copy) — see
        # apply_quiet_hours()'s docstring for why this matters.
        next_comment_time = apply_quiet_hours(next_comment_time, cfg)
        scheduled_at = next_comment_time
        task = schedule_store.ScheduledTask(
            task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
            action=action,
            account_id=account_id,
            scheduled_at=scheduled_at.isoformat(),
            content=_draft_candidate_reply(cand),
            target_url=url,
            reasoning=f"auto: reply to candidate {cid}",
            source_kind="candidate",
            source_id=cid,
        )
        schedule_store.add(task)
        scheduled_comments += 1
        next_comment_time = next_comment_time + timedelta(minutes=random.uniform(comment_gap_min, comment_gap_max))
        if contact:
            _mark_contacted(contact)

    if latest_job_ts:
        state[f"{account_id}_jobs_since"] = latest_job_ts
    if latest_candidate_ts:
        state[f"{account_id}_candidates_since"] = latest_candidate_ts
    _save_sync_state(state)
    prune_old_cache(cfg.cache_retention_days)

    return {
        "jobs_fetched": len(jobs),
        "candidates_fetched": len(candidates),
        "scheduled_posts": scheduled_posts,
        "scheduled_comments": scheduled_comments,
    }


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

    from human_bot.agent import TaskRequest, run_task, rate_limit_bucket_for  # local import — avoid import cycle at module load
    from human_bot.safety import rate_limit_wait_message

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
        account = get_account(task.account_id)
        bucket = rate_limit_bucket_for(task.action)
        warning = rate_limit_wait_message(account, bucket) if account and bucket else None
        if warning:
            schedule_store.update(task.task_id, last_warning=warning)
            continue

        request = TaskRequest(
            action=task.action,
            account_id=task.account_id,
            target_url=task.target_url,
            content=task.content,
            media_path=task.media_path,
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
