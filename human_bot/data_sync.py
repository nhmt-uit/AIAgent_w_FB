"""
Purpose of this file / Muc dich cua file nay:
EN: Polls side B's `data-ingestion` API (GET /api/jobs, GET /api/candidates
— see docs/architecture.md section 3c for the full contract) instead of
waiting for a pushed task, filters out anything already seen/handled using
a local day-partitioned cache, and turns genuinely-new records into
ScheduledTask entries (human_bot/schedule_store.py) with a randomized,
sequential post/comment time — never a burst, never a fixed cadence, same
principle as docs/skills/rate-limiting-pacing.md.

IMPORTANT — the content drafted here (`_draft_job_post_placeholder`,
`_draft_candidate_reply_placeholder`) is a plain template, NOT the real
Content Strategist Agent (still TODO — see docs/agents/
content-strategist.md). It fills real fields in so it's not garbage, but
it does not vary wording per group beyond a small rotating set of opening
phrases, and does not use an LLM to compose original text. Treat every
scheduled item this produces as a DRAFT to review/edit in /admin/schedule
before it fires — this is one of the reasons DataSyncConfig.auto_fire_enabled
defaults to False (see human_bot/data_sync_config.py).
VI: Goi dinh ky API cua ben B (data-ingestion) thay vi cho ho day task
sang, loc bo nhung gi da thay/da xu ly bang mot cache luu theo ngay tren
dia, va bien nhung ban ghi thuc su moi thanh ScheduledTask
(human_bot/schedule_store.py) voi thoi gian dang/comment duoc rai ngau
nhien, tuan tu — khong bao gio dang don, khong bao gio dang theo nhip co
dinh, cung nguyen tac voi docs/skills/rate-limiting-pacing.md.

QUAN TRONG — noi dung soan o day chi la mau (template) gian don, KHONG
PHAI Content Strategist Agent that (con TODO). No dien du lieu that vao
nen khong phai rac, nhung chua bien tau theo tung nhom (ngoai mot vai
cach mo dau xoay vong), va khong dung AI de viet lai. Coi moi muc lich
sinh ra o day la BAN NHAP can xem/sua trong /admin/schedule truoc khi no
thuc su chay — day cung la mot ly do DataSyncConfig.auto_fire_enabled
mac dinh la False.
"""
from __future__ import annotations

import json
import os
import random
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any

import httpx

from human_bot import schedule_store
from human_bot.config import AccountConfig, get_account
from human_bot.data_sync_config import DataSyncConfig
from human_bot.runtime_config import get_data_sync_config, get_joined_groups

CACHE_ROOT = Path(__file__).resolve().parent.parent / "data_sync_cache"
STATE_PATH = CACHE_ROOT / "_state.json"
CONTACTED_PATH = CACHE_ROOT / "_contacted_contacts.json"

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

def _apply_quiet_hours(dt: datetime, cfg: DataSyncConfig) -> datetime:
    """Push a time that falls in the configured quiet window forward to
    the window's end, same UTC-as-local simplification the rest of this
    project currently makes (no per-account timezone config yet — see
    docs/skills/rate-limiting-pacing.md, this is a known limitation, not
    an oversight)."""
    if cfg.quiet_hour_start_local <= dt.hour < cfg.quiet_hour_end_local:
        dt = dt.replace(
            hour=int(cfg.quiet_hour_end_local), minute=random.randint(0, 30),
            second=0, microsecond=0,
        )
    return dt


# --- Draft content (placeholder — see module docstring) ---------------------

_JOB_POST_OPENERS = [
    "[Tin tuyển dụng]",
    "Cơ hội việc làm mới:",
    "Thông tin tuyển dụng:",
]


def _draft_job_post_placeholder(job: dict, variant_seed: int = 0) -> str:
    attrs = job.get("attributes") or {}
    opener = _JOB_POST_OPENERS[variant_seed % len(_JOB_POST_OPENERS)]
    title = job.get("title") or attrs.get("jobField") or "vị trí đang tuyển"
    lines = [f"{opener} {title}"]
    if attrs.get("company"):
        lines.append(f"Công ty: {attrs['company']}")
    if attrs.get("location"):
        lines.append(f"Địa điểm: {attrs['location']}")
    if attrs.get("visaType"):
        lines.append(f"Visa: {attrs['visaType']}")
    if attrs.get("jlpt"):
        lines.append(f"Yêu cầu JLPT: {attrs['jlpt']}")
    salary = attrs.get("salary")
    if isinstance(salary, dict) and salary.get("min"):
        lines.append(
            f"Lương: {salary.get('min')}-{salary.get('max')} "
            f"{salary.get('currency', '')}/{salary.get('period', '')}"
        )
    if job.get("url"):
        lines.append(f"Chi tiết: {job['url']}")
    return "\n".join(lines)


def _draft_candidate_reply_placeholder(candidate: dict) -> str:
    attrs = candidate.get("attributes") or {}
    field_wanted = attrs.get("desiredJobField") or "công việc phù hợp"
    region = attrs.get("preferredRegion")
    text = f"Chào bạn, mình thấy bạn đang tìm {field_wanted}"
    if region:
        text += f" ở khu vực {region}"
    text += ", bên mình đang có một số vị trí có thể phù hợp, bạn nhắn tin trao đổi thêm nhé."
    return text


# --- Main entry point ---------------------------------------------------------

async def sync_once(account_id: str, cfg: DataSyncConfig | None = None) -> dict[str, Any]:
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
    next_post_time = now + timedelta(
        minutes=random.uniform(cfg.post_gap_min_minutes, cfg.post_gap_max_minutes)
    )
    next_comment_time = now + timedelta(
        minutes=random.uniform(cfg.comment_gap_min_minutes, cfg.comment_gap_max_minutes)
    )

    scheduled_posts = 0
    scheduled_comments = 0
    latest_job_ts = jobs_since
    latest_candidate_ts = candidates_since

    for i, job in enumerate(jobs):
        jid = str(job.get("id") or "")
        job_ts = job.get("last_seen_at") or job.get("published_at")
        if job_ts and (latest_job_ts is None or job_ts > latest_job_ts):
            latest_job_ts = job_ts
        if not jid or jid in seen:
            continue
        for group in get_joined_groups(account.account_id):
            scheduled_at = _apply_quiet_hours(next_post_time, cfg)
            task = schedule_store.ScheduledTask(
                task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
                action="post_to_group",
                account_id=account_id,
                scheduled_at=scheduled_at.isoformat(),
                content=_draft_job_post_placeholder(job, variant_seed=i),
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
            next_post_time = next_post_time + timedelta(
                minutes=random.uniform(cfg.post_gap_min_minutes, cfg.post_gap_max_minutes)
            )
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
        scheduled_at = _apply_quiet_hours(next_comment_time, cfg)
        task = schedule_store.ScheduledTask(
            task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
            action=action,
            account_id=account_id,
            scheduled_at=scheduled_at.isoformat(),
            content=_draft_candidate_reply_placeholder(cand),
            target_url=url,
            reasoning=f"auto: reply to candidate {cid}",
            source_kind="candidate",
            source_id=cid,
        )
        schedule_store.add(task)
        scheduled_comments += 1
        next_comment_time = next_comment_time + timedelta(
            minutes=random.uniform(cfg.comment_gap_min_minutes, cfg.comment_gap_max_minutes)
        )
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


async def fire_due_tasks(cfg: DataSyncConfig | None = None) -> dict[str, Any]:
    """Check human_bot/schedule_store.py for anything due and, ONLY if
    cfg.auto_fire_enabled, actually run it via human_bot/agent.py's
    run_task() (in-process — not an HTTP call back to our own /tasks).
    When auto_fire_enabled is False, due tasks are left pending so a
    human can still fire them manually from /admin/schedule ("Đăng ngay"
    always works regardless of this gate — it's an explicit human click,
    same trust level as any other /admin action)."""
    cfg = cfg or get_data_sync_config()
    due = schedule_store.due_tasks()
    if not due:
        return {"due": 0, "fired": 0}
    if not cfg.auto_fire_enabled:
        return {"due": len(due), "fired": 0, "reason": "auto_fire_enabled is False"}

    from human_bot.agent import TaskRequest, run_task  # local import — avoid import cycle at module load

    fired = 0
    for task in due:
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
        else:
            schedule_store.mark_failed(task.task_id, result.message)
        fired += 1
    return {"due": len(due), "fired": fired}
