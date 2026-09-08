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
    reasoning: str = ""
    source_kind: str = ""  # "job" | "candidate" — which side-B endpoint this came from
    source_id: str = ""  # side-B's own record id, for traceability/debugging
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


def ensure_dirs() -> None:
    for d in (PENDING_DIR, POSTED_DIR, FAILED_DIR, CANCELLED_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _safe_pending_path(task_id: str) -> Path:
    """Resolve `task_id` strictly inside PENDING_DIR, same defensive
    reasoning as content_queue.py's _safe_pending_path."""
    ensure_dirs()
    safe_name = Path(task_id).name
    if not safe_name.endswith(".json"):
        safe_name += ".json"
    return PENDING_DIR / safe_name


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


def list_pending() -> list[ScheduledTask]:
    """All pending tasks, soonest-due first (filenames are timestamp-
    prefixed, so plain sort order is chronological)."""
    ensure_dirs()
    items = []
    for path in sorted(PENDING_DIR.glob("*.json")):
        task = _read(path)
        if task is not None:
            items.append(task)
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


def _move_to(task_id: str, target_dir: Path) -> Path | None:
    ensure_dirs()
    src = _safe_pending_path(task_id)
    if not src.is_file():
        return None
    dest = target_dir / src.name
    src.rename(dest)
    return dest


def cancel(task_id: str) -> bool:
    return _move_to(task_id, CANCELLED_DIR) is not None


def mark_posted(task_id: str, message: str) -> None:
    dest = _move_to(task_id, POSTED_DIR)
    if dest is not None:
        dest.with_suffix(".result.txt").write_text(message, encoding="utf-8")


def mark_failed(task_id: str, reason: str) -> None:
    dest = _move_to(task_id, FAILED_DIR)
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
