"""
Purpose of this file / Muc dich cua file nay:
EN: File-based store for scheduled tasks produced by the side-B data-sync
poller (human_bot/data_sync.py) — one JSON file per scheduled item, same
directory-as-status-machine pattern as human_bot/content_queue.py
(pending/posted/failed/cancelled), so nothing is ever silently deleted and
the whole history stays inspectable on disk. This is also what
/admin/schedule (human_bot/admin.py) reads and writes, so a human can
review, edit, or cancel anything the poller scheduled before it fires.
VI: Kho luu lich dang dua tren file, sinh ra tu bo dong bo du lieu ben B
(human_bot/data_sync.py) — moi muc lich la mot file JSON, dung chung kieu
"thu muc la trang thai" giong human_bot/content_queue.py
(pending/posted/failed/cancelled), nen khong co gi bi xoa am tham va toan
bo lich su van xem lai duoc tren dia. Day cung la noi /admin/schedule
(human_bot/admin.py) doc va ghi, de con nguoi xem lai, sua, hoac huy bat
ky muc nao truoc khi no thuc su chay.
"""
from __future__ import annotations

import json
import os
import uuid
from dataclasses import asdict, dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

SCHEDULE_ROOT = Path(__file__).resolve().parent.parent / "scheduled"
PENDING_DIR = SCHEDULE_ROOT / "pending"
POSTED_DIR = SCHEDULE_ROOT / "posted"
FAILED_DIR = SCHEDULE_ROOT / "failed"
CANCELLED_DIR = SCHEDULE_ROOT / "cancelled"
# Tasks swept out of pending/ at service STARTUP ONLY (2026-09-14) — see
# human_bot/service.py's sweep_overdue_on_startup() docstring for the full
# reasoning: a task whose scheduled_at was already in the past the moment
# the service came back up (e.g. after being off for hours) must NOT
# silently auto-fire — it lands here instead, for an admin to review at
# /admin/schedule and either reschedule (pick a time by hand, or let the
# system suggest the next free slot — same as /admin/reports' "🔄 Lên lịch
# lại") or delete. A task that merely becomes due mid-run (normal
# poll-interval lag, or a backlog from an account being rate-limited) is
# NEVER swept here — only the one-time startup check looks at this at all.
MISSED_DIR = SCHEDULE_ROOT / "missed"


@dataclass
class ScheduledTask:
    """One task waiting to fire — matches human_bot.agent.TaskRequest's
    fields plus scheduling/provenance metadata. `task_id` is also the
    filename (without directory/extension)."""
    task_id: str
    action: str
    account_id: str
    scheduled_at: str  # ISO 8601 UTC
    content: str | None = None
    target_url: str | None = None
    media_path: str | None = None
    # post_to_own_profile only — see human_bot.agent.TaskRequest.audience.
    audience: str = "public"
    reasoning: str = ""
    source_kind: str = ""  # "job" | "candidate" — which side-B endpoint this came from
    source_id: str = ""  # side-B's own record id, for traceability/debugging
    # source_kind == "job" only — the job's own {"title", "attributes"}
    # (see content_strategist._job_summary's shape), stashed here at
    # schedule time so fire_due_tasks() can redraft this ONE task's post
    # with AI right before it actually fires (2026-09-10 — AI drafting
    # moved from schedule-time to fire-time, see data_sync.py's sync_all()
    # docstring) without needing another round-trip to side B for data
    # already fetched once. None for every other action/source_kind.
    job_data: dict | None = None
    # source_kind == "candidate" only — the candidate's own {"attributes"}
    # (desiredJobField/preferredRegion...), stashed here at schedule time
    # so fire_due_tasks() can hand it to content_strategist.
    # rewrite_candidate_reply() as grounding context, right before this
    # task fires — same reasoning/timing as job_data above. None for
    # every other action/source_kind.
    candidate_data: dict | None = None
    created_at: str = field(default_factory=lambda: datetime.now(timezone.utc).isoformat())
    # Set instead of moving the task to failed/ when a fire attempt hits
    # RateLimiter's min_delay_seconds gap specifically (not other failure
    # reasons) — a rate-limit gap says nothing wrong with the post itself,
    # it just fired too soon after the account's last action, so the task
    # stays in pending/ and /admin/schedule shows this as a banner with a
    # suggested reschedule time instead of silently landing in failed/.
    # Cleared on the next successful edit/fire. See data_sync.py's
    # fire_due_tasks() and admin.py's schedule_fire_now()/schedule_update().
    last_warning: str | None = None
    # The action_log row id this task is a retry OF — set by
    # human_bot/admin.py's "📅 Đặt lịch"/"🔄 Lên lịch lại" flows (added
    # 2026-09-12) when the admin creates this task from a FAILED
    # /admin/reports row, carried through to the resulting action_log row
    # once this task fires (agent.py's TaskRequest.retry_of_log_id →
    # db.log_action()) so the report can show "Đã lên lịch lại"/"Đã đăng
    # lại" instead of offering the same failed row for retry again. None
    # for a task composed fresh (not from a report row).
    retry_of_log_id: int | None = None


def ensure_dirs() -> None:
    for d in (PENDING_DIR, POSTED_DIR, FAILED_DIR, CANCELLED_DIR, MISSED_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _safe_path_in(task_id: str, directory: Path) -> Path:
    """Resolve `task_id` strictly inside `directory`, same defensive
    reasoning as content_queue.py's _safe_pending_path."""
    ensure_dirs()
    safe_name = Path(task_id).name
    if not safe_name.endswith(".json"):
        safe_name += ".json"
    return directory / safe_name


def _safe_pending_path(task_id: str) -> Path:
    return _safe_path_in(task_id, PENDING_DIR)


def new_task_id(scheduled_at: str) -> str:
    """A sortable-by-schedule-time id: <scheduled_at as compact UTC
    stamp>_<short uuid>. Sorting filenames therefore sorts by when the
    task is due, which is exactly the order /admin/schedule and the
    due-task checker want to read them in."""
    dt = datetime.fromisoformat(scheduled_at.replace("Z", "+00:00"))
    stamp = dt.astimezone(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    return f"{stamp}_{uuid.uuid4().hex[:8]}"


def add(task: ScheduledTask) -> str:
    ensure_dirs()
    path = _safe_pending_path(task.task_id)
    path.write_text(json.dumps(asdict(task), indent=2, ensure_ascii=False), encoding="utf-8")
    return task.task_id


def _read(path: Path) -> ScheduledTask | None:
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    known = {f for f in ScheduledTask.__dataclass_fields__}
    return ScheduledTask(**{k: v for k, v in data.items() if k in known})


def get(task_id: str) -> ScheduledTask | None:
    return _read(_safe_pending_path(task_id))


def _scheduled_at_sort_key(task: ScheduledTask) -> datetime:
    """Sort key for list_pending()/list_missed() — parses the task's
    CURRENT scheduled_at field rather than trusting task_id's timestamp
    prefix, which goes stale the moment a task is rescheduled (update()
    and restore_to_pending() both change scheduled_at in place without
    renaming the file/regenerating task_id — see the 2026-09-16 fix note
    on list_pending() below). A task with an unparsable scheduled_at
    (shouldn't happen in practice) sorts last instead of crashing the
    whole list or silently jumping to the front. A naive scheduled_at
    (no timezone — /admin/schedule/update and the missed-task reschedule
    form both pass the raw form value through with no normalization, a
    known real data shape, see test_last_scheduled_post_time_does_not_
    crash_on_a_naive_scheduled_at in test_data_sync.py) is treated as
    UTC, same convention data_sync.py's _last_scheduled_post_time()
    already uses — otherwise comparing it against an aware sibling
    crashes the whole sort."""
    try:
        dt = datetime.fromisoformat(task.scheduled_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return datetime.max.replace(tzinfo=timezone.utc)
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt


def list_pending() -> list[ScheduledTask]:
    """All pending tasks, soonest-due first by their CURRENT scheduled_at
    (not by filename/task_id).

    2026-09-16 fix: this used to just be `sorted(PENDING_DIR.glob(...))`
    on the assumption that task_id's timestamp prefix (set once, at
    creation — see new_task_id()) always matches the task's current
    scheduled_at. That assumption breaks the moment a task is
    rescheduled: a real production report found a missed post moved
    forward to 2026-09-17 via "Đặt lịch" still sorting AHEAD of every
    2026-09-16 post, because restore_to_pending()/update() only rewrite
    scheduled_at inside the JSON — they never rename the file or call
    new_task_id() again, so the stale (earlier) task_id prefix kept
    winning the filename sort. Fixed by sorting on the real scheduled_at
    read back out of each file's content instead."""
    ensure_dirs()
    items = []
    for path in sorted(PENDING_DIR.glob("*.json")):
        task = _read(path)
        if task is not None:
            items.append(task)
    items.sort(key=_scheduled_at_sort_key)
    return items


def list_posted() -> list[ScheduledTask]:
    """All already-fired tasks — mirrors list_pending() but reads
    POSTED_DIR. _move_to() only renames the file on posting, it never
    touches the JSON content, so every ScheduledTask field (including
    scheduled_at) survives intact; only the companion .result.txt is new.
    Added for human_bot/data_sync.py's daily-post-cap check, which needs
    to count a day's posts that have ALREADY fired, not just ones still
    pending, so the cap isn't meaningless for the rest of a day after the
    quota already fired once."""
    ensure_dirs()
    items = []
    for path in sorted(POSTED_DIR.glob("*.json")):
        task = _read(path)
        if task is not None:
            items.append(task)
    return items


def get_missed(task_id: str) -> ScheduledTask | None:
    return _read(_safe_path_in(task_id, MISSED_DIR))


def get_missed_reason(task_id: str) -> str | None:
    """The .result.txt mark_missed() wrote alongside this task's JSON —
    same sibling-file pattern as mark_posted()/mark_failed() — for
    /admin/schedule's "⚠️ Task quá hạn" section to show WHY."""
    path = _safe_path_in(task_id, MISSED_DIR).with_suffix(".result.txt")
    try:
        return path.read_text(encoding="utf-8")
    except OSError:
        return None


def list_missed() -> list[ScheduledTask]:
    """Tasks the startup sweep pulled out of pending/ — see MISSED_DIR's
    docstring. Soonest-originally-due first, by scheduled_at (same fix
    and same reasoning as list_pending(), 2026-09-16) rather than by
    filename/task_id."""
    ensure_dirs()
    items = []
    for path in sorted(MISSED_DIR.glob("*.json")):
        task = _read(path)
        if task is not None:
            items.append(task)
    items.sort(key=_scheduled_at_sort_key)
    return items


def mark_missed(task_id: str, reason: str) -> bool:
    """Move a pending task to MISSED_DIR — called ONLY by the one-time
    startup sweep (human_bot/service.py's sweep_overdue_on_startup()),
    never by the recurring due-task check. Same "never silently delete"
    pattern as mark_posted()/mark_failed(): the task's own JSON is
    untouched, just relocated, plus a sibling .result.txt explaining why."""
    dest = _move_to(task_id, MISSED_DIR)
    if dest is not None:
        dest.with_suffix(".result.txt").write_text(reason, encoding="utf-8")
    return dest is not None


def missed_overdue_days(task: ScheduledTask, now: datetime | None = None) -> int:
    """How many full days ago `task`'s ORIGINAL scheduled_at was —
    2026-09-24, owner request for a "quá hạn ≥ N ngày" filter on
    /admin/schedule's "⚠️ Task quá hạn" tab. Shared with
    cancel_stale_missed() below so the filter and the auto-cleanup
    threshold always agree on what "N days overdue" means (both measure
    from scheduled_at, not from whenever the startup sweep happened to
    move the file into MISSED_DIR — a task swept today after sitting
    overdue for a week already reads as 7 days overdue, not 0).
    Uses the same naive/aware-safe parsing as _scheduled_at_sort_key()
    (a naive scheduled_at is treated as UTC)."""
    now = now or datetime.now(timezone.utc)
    return (now - _scheduled_at_sort_key(task)).days


# Default threshold for cancel_stale_missed() below — matches the widest
# option (30 ngày) of /admin/schedule's own "quá hạn ≥ N ngày" filter
# (owner's explicit choice, 2026-09-24: a missed task nobody looked at
# for a whole month is not coming back).
STALE_MISSED_MAX_AGE_DAYS = 30


def cancel_stale_missed(max_age_days: int = STALE_MISSED_MAX_AGE_DAYS, now: datetime | None = None) -> int:
    """Auto-cancel any MISSED_DIR task whose original scheduled_at is
    more than `max_age_days` in the past — owner request 2026-09-24:
    MISSED_DIR previously had NO cleanup of its own at all (unlike
    posted/failed/cancelled, which cleanup_old() prunes after
    SCHEDULE_RETENTION_DAYS) — a task nobody reviews just sits there
    forever, see MISSED_DIR's own docstring above ("chờ bạn duyệt").

    Reuses cancel_missed() so this is exactly "the same 🗑️ Xoá click a
    human would eventually make", not a separate/harsher deletion path —
    the task's own JSON moves to CANCELLED_DIR (still on disk, still
    readable, and still subject to cleanup_old()'s normal retention
    later — "giữ lại lịch sử" for now, not forever), and the ORIGINAL
    miss reason's .result.txt is left behind in MISSED_DIR exactly as
    cancel_missed() already does for a manual cancel. The only addition
    here: appends a short note to that leftover .result.txt recording
    that THIS particular cancel was automatic, so a later look at the
    history doesn't read as "an admin decided this", when nobody did.

    Called from human_bot/service.py's daily `_schedule_cleanup_loop()`
    (same cadence as cleanup_old() — this is disk/backlog housekeeping,
    not something that needs a tight interval). Returns how many were
    cancelled, for logging."""
    now = now or datetime.now(timezone.utc)
    count = 0
    for task in list_missed():
        if missed_overdue_days(task, now) < max_age_days:
            continue
        if not cancel_missed(task.task_id):
            continue
        count += 1
        note_path = _safe_path_in(task.task_id, MISSED_DIR).with_suffix(".result.txt")
        try:
            existing = note_path.read_text(encoding="utf-8")
        except OSError:
            existing = ""
        note = (
            f"\n\n[Tự động huỷ lúc {now.isoformat()} — quá hạn hơn "
            f"{max_age_days} ngày mà chưa được xử lý.]"
        )
        try:
            note_path.write_text(existing + note, encoding="utf-8")
        except OSError:
            pass  # best-effort note only — the cancel itself already succeeded
    return count


def restore_to_pending(task_id: str, **fields_to_update) -> ScheduledTask | None:
    """The admin-review resolution for a MISSED task (/admin/schedule's
    "⚠️ Task quá hạn" section, added 2026-09-14) — "Đặt lịch" (pick a new
    time by hand) or "Lên lịch lại" (auto-suggested slot, same
    _suggest_reschedule_at() /admin/reports' retry flow uses) both funnel
    through here: read the task back out of MISSED_DIR, apply whatever
    changed (at minimum a new scheduled_at), write it into PENDING_DIR via
    add() (so it re-enters the normal due-task check next poll), and
    remove the leftover file (+ its .result.txt, if any) from MISSED_DIR.
    Returns the updated task, or None if it's no longer there (already
    resolved by another click)."""
    task = get_missed(task_id)
    if task is None:
        return None
    known = set(ScheduledTask.__dataclass_fields__) - {"task_id"}
    for k, v in fields_to_update.items():
        if k in known:
            setattr(task, k, v)
    add(task)
    src = _safe_path_in(task_id, MISSED_DIR)
    src.unlink(missing_ok=True)
    src.with_suffix(".result.txt").unlink(missing_ok=True)
    return task


def due_tasks(now: datetime | None = None) -> list[ScheduledTask]:
    now = now or datetime.now(timezone.utc)
    result = []
    for task in list_pending():
        try:
            scheduled = datetime.fromisoformat(task.scheduled_at.replace("Z", "+00:00"))
        except ValueError:
            continue
        if scheduled <= now:
            result.append(task)
    return result


def update(task_id: str, **fields_to_update) -> ScheduledTask | None:
    """Edit a pending task in place (content, scheduled_at, target_url,
    ...) — used by /admin/schedule's edit form. Unknown keys are ignored.
    Returns the updated task, or None if it no longer exists (already
    fired/cancelled — the admin page should re-render rather than assume
    success)."""
    task = get(task_id)
    if task is None:
        return None
    known = set(ScheduledTask.__dataclass_fields__) - {"task_id"}
    for k, v in fields_to_update.items():
        if k in known:
            setattr(task, k, v)
    add(task)
    return task


def _move_to(task_id: str, target_dir: Path, source_dir: Path | None = None) -> Path | None:
    # source_dir resolved to PENDING_DIR here, at CALL time, not as the
    # parameter's own default — a default value binds to the module
    # global's value at function-DEFINITION time, so a test that
    # monkeypatches schedule_store.PENDING_DIR to an isolated tmp_path
    # would silently keep writing into the real one instead (caught this
    # immediately: a monkeypatched test moved 0 files, wrote to the real
    # scheduled/pending/ before the fix).
    if source_dir is None:
        source_dir = PENDING_DIR
    ensure_dirs()
    src = _safe_path_in(task_id, source_dir)
    if not src.is_file():
        return None
    dest = target_dir / src.name
    src.rename(dest)
    return dest


def cancel(task_id: str) -> bool:
    return _move_to(task_id, CANCELLED_DIR) is not None


def cancel_missed(task_id: str) -> bool:
    """"Xoá"/"Huỷ" for a task sitting in MISSED_DIR (admin decided it's no
    longer needed) — same CANCELLED_DIR destination as cancel() above, so
    it's still on-disk for audit, just from a different source directory.
    Leaves behind the .result.txt the startup sweep wrote (still useful
    context for why this was ever missed) rather than trying to move it
    too — cancel()'s own targets never carry one either."""
    return _move_to(task_id, CANCELLED_DIR, source_dir=MISSED_DIR) is not None


def mark_posted(task_id: str, message: str, source_dir: Path | None = None) -> None:
    """`source_dir` (2026-09-25, owner request: a "🚀 Đăng ngay" button
    directly on MISSED_DIR items) lets this fire straight from
    MISSED_DIR too, same as cancel_missed() already does for cancel() —
    default None keeps the original PENDING_DIR behavior for every
    existing caller."""
    dest = _move_to(task_id, POSTED_DIR, source_dir=source_dir)
    if dest is not None:
        dest.with_suffix(".result.txt").write_text(message, encoding="utf-8")


def mark_failed(task_id: str, reason: str, source_dir: Path | None = None) -> None:
    """See mark_posted()'s `source_dir` docstring above — same reasoning."""
    dest = _move_to(task_id, FAILED_DIR, source_dir=source_dir)
    if dest is not None:
        dest.with_suffix(".result.txt").write_text(reason, encoding="utf-8")


def cleanup_old(retention_days: int | None = None) -> dict[str, int]:
    """Permanently delete files from posted/, failed/, cancelled/ older
    than `retention_days` (default: SCHEDULE_RETENTION_DAYS in .env, or
    30) — these are terminal states nothing reads back from at runtime
    (reporting already lives in human_bot.db's action_log, see
    human_bot/db.py, and survives this untouched), so kept on disk only
    as an inspectable audit trail. Bounded here on purpose, mirroring
    DataSyncConfig.cache_retention_days's reasoning — otherwise these
    directories grow forever as the schedule gets busier over time (see
    the conversation that raised this: dense schedules should not mean
    "hard to work with" or ever-growing folders). PENDING_DIR is
    deliberately untouched — a task waiting to fire is never cleanup
    material regardless of age. Returns a per-directory count of files
    removed, for logging/visibility."""
    if retention_days is None:
        retention_days = int(os.environ.get("SCHEDULE_RETENTION_DAYS", "30") or "30")
    ensure_dirs()
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = {"posted": 0, "failed": 0, "cancelled": 0}
    for label, directory in (("posted", POSTED_DIR), ("failed", FAILED_DIR), ("cancelled", CANCELLED_DIR)):
        for path in directory.glob("*"):
            if not path.is_file():
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                path.unlink()
                removed[label] += 1
    return removed
