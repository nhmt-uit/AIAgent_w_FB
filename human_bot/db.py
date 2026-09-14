"""
Purpose of this file / Muc dich cua file nay:
EN: SQLite-backed history of every action human_bot has attempted (posts,
comments, likes — success or failure), so /admin/reports can answer
questions like "which account posted how many times this week" or "which
group gets posted into the most" without parsing log files by hand.
Deliberately plain sqlite3 (Python's own stdlib, no extra package to
install, no server process) — this project's whole storage philosophy so
far has been "the simplest thing that works for one person running a few
accounts" (see docs/architecture.md), and that still holds here: a single
local .db file is enough until there's a concrete reason (multiple writers,
much larger volume, needing it reachable from another machine) to reach
for something heavier. See docs/architecture.md section 3d for the
schema decision and the report queries this was designed around.
VI: Lich su moi hanh dong human_bot da thu (dang bai, comment, like — thanh
cong hay that bai) luu bang SQLite, de /admin/reports tra loi duoc cac cau
hoi kieu "tai khoan nao dang bao nhieu bai tuan nay" hay "nhom nao duoc
dang vao nhieu nhat" ma khong can doc log bang tay. Dung thang sqlite3 co
san trong Python (khong can cai them goi nao, khong can chay server rieng)
— dung triet ly luu tru xuyen suot du an nay: "don gian nhat co the, vua du
cho mot nguoi tu van hanh vai tai khoan" (xem docs/architecture.md). Mot
file .db cuc bo la du cho toi khi co ly do cu the (nhieu tien trinh cung
ghi, du lieu lon hon han, can truy cap tu may khac) moi can doi sang thu
nang hon. Xem docs/architecture.md muc 3d de biet quyet dinh schema va cac
cau truy van bao cao duoc thiet ke theo.
"""
from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

DB_PATH = Path(__file__).resolve().parent.parent / "human_bot.db"

_SCHEMA = """
CREATE TABLE IF NOT EXISTS action_log (
    id                 INTEGER PRIMARY KEY AUTOINCREMENT,
    account_id         TEXT    NOT NULL,
    action             TEXT    NOT NULL,
    target_url         TEXT,
    target_group_name  TEXT,
    content            TEXT,
    success            INTEGER NOT NULL,
    message            TEXT,
    source             TEXT    NOT NULL,
    source_kind        TEXT,
    source_id          TEXT,
    screenshot_path    TEXT,
    job_data           TEXT,
    retry_of_log_id    INTEGER,
    created_at         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_action_log_account_time ON action_log(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_action_log_target ON action_log(target_url);
-- Backs the "theo từng lần đăng" report (2026-09-12) — group rows into
-- one "job" by (source_kind, source_id, account_id). source_kind is
-- first in the index since every query filters on it (only 'job' rows
-- are ever grouped this way, candidates aren't), same left-to-right
-- reasoning as idx_action_log_account_time above.
CREATE INDEX IF NOT EXISTS idx_action_log_source ON action_log(source_kind, source_id, account_id);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema() -> None:
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
        # CREATE TABLE IF NOT EXISTS above only creates screenshot_path on
        # a brand-new database — an existing human_bot.db from before this
        # column existed needs it added explicitly. SQLite has no "ADD
        # COLUMN IF NOT EXISTS", so just attempt it and swallow the
        # "duplicate column" error every run after the first (added
        # 2026-09-07, screenshot-on-every-attempt feature).
        try:
            conn.execute("ALTER TABLE action_log ADD COLUMN screenshot_path TEXT")
        except sqlite3.OperationalError:
            pass
        # Same reasoning as screenshot_path above — added 2026-09-12 for
        # the "theo từng lần đăng" report (job's raw side-B data:
        # title/attributes — see agent.py's TaskRequest.job_data).
        try:
            conn.execute("ALTER TABLE action_log ADD COLUMN job_data TEXT")
        except sqlite3.OperationalError:
            pass
        # Same reasoning again — added 2026-09-12 alongside the "↻ Đăng
        # lại" 3-choice modal, so a report row can tell "đã được xử lý
        # rồi" (đăng ngay/đặt lịch/lên lịch lại) apart from "chưa ai đụng
        # vào" and stop offering the same failed row for retry forever.
        try:
            conn.execute("ALTER TABLE action_log ADD COLUMN retry_of_log_id INTEGER")
        except sqlite3.OperationalError:
            pass
        # Must run AFTER the ALTER TABLE above, not inside _SCHEMA's
        # executescript() — on an EXISTING database (column not there
        # yet), creating an index on a not-yet-added column fails outright
        # (caught this immediately: broke importing human_bot.db against
        # the real, already-populated database).
        conn.execute(
            "CREATE INDEX IF NOT EXISTS idx_action_log_retry_of ON action_log(retry_of_log_id)"
        )
        conn.commit()
    finally:
        conn.close()


# Run once at import time — every module that imports human_bot.db (agent.py,
# admin.py, service.py) gets a guaranteed-to-exist table without needing to
# remember to call this explicitly. CREATE TABLE/INDEX IF NOT EXISTS is cheap
# and safe to repeat across process restarts.
ensure_schema()


def log_action(
    *,
    account_id: str,
    action: str,
    success: bool,
    message: str = "",
    target_url: str | None = None,
    target_group_name: str | None = None,
    content: str | None = None,
    source: str = "api",
    source_kind: str | None = None,
    source_id: str | None = None,
    screenshot_path: str | None = None,
    job_data: dict | None = None,
    retry_of_log_id: int | None = None,
    created_at: str | None = None,
) -> None:
    """Record one attempted action, whatever the outcome. Called from the
    single choke point every action passes through — human_bot/agent.py's
    run_task() — so every manual post, queued post, scheduled fire, and
    /tasks call from n8n ends up here without each caller needing to log
    separately. Never let a logging failure break the actual task; callers
    should treat this as best-effort (see run_task()'s try/except around
    the call).

    `job_data` (added 2026-09-12): the RAW side-B origin data for this
    row's source — for source_kind='job' rows, the job's own
    title/attributes (human_bot/agent.py's TaskRequest.job_data,
    ultimately human_bot/schedule_store.py's ScheduledTask.job_data);
    for source_kind='candidate' rows, the candidate's own attributes
    (ScheduledTask.candidate_data — see data_sync.py's fire_due_tasks(),
    which passes `task.job_data or task.candidate_data` since exactly
    one of the two is ever set on a given task). Stored once per row
    (small, and simplest: no separate table to join), JSON-encoded.
    Backs both the "theo từng lần đăng" report (job_post_groups() below)
    and the "theo từng lần bình luận" one (candidate_comments() below),
    each grouping rows by (source_kind, source_id, account_id). None for
    anything that isn't an auto-scheduled job post or candidate reply
    (manual posts, own-profile posts, ...).

    `retry_of_log_id` (added 2026-09-12): the `id` of the action_log row
    this one is retrying — set when the task came from /admin/reports'
    "↻ Đăng lại" modal (any of its 3 choices — see
    human_bot/agent.py's TaskRequest.retry_of_log_id docstring for the
    exact plumbing). Backs successful_retry_log_ids() below, so a report
    row already retried successfully shows "Đã đăng lại" instead of
    offering the button again. None for anything not created that way."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO action_log
                (account_id, action, target_url, target_group_name, content,
                 success, message, source, source_kind, source_id, screenshot_path, job_data,
                 retry_of_log_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                account_id,
                action,
                target_url,
                target_group_name,
                content,
                1 if success else 0,
                message,
                source,
                source_kind,
                source_id,
                screenshot_path,
                json.dumps(job_data, ensure_ascii=False) if job_data else None,
                retry_of_log_id,
                created_at or datetime.now(timezone.utc).isoformat(),
            ),
        )
        conn.commit()
    finally:
        conn.close()


def list_accounts_with_activity() -> list[str]:
    conn = _connect()
    try:
        cur = conn.execute("SELECT DISTINCT account_id FROM action_log ORDER BY account_id")
        return [row["account_id"] for row in cur.fetchall()]
    finally:
        conn.close()


def _base_where(account_id: str | None, since: str | None) -> tuple[str, list]:
    """Shared WHERE-clause builder for the account/date-range filters every
    report query below takes — `since` is an ISO 8601 UTC cutoff (rows with
    created_at >= since), None means "all time". Kept as one function so
    the two filters compose the same way (and in the same param order)
    everywhere, instead of each query hand-rolling its own AND chain."""
    clauses: list[str] = []
    params: list = []
    if account_id:
        clauses.append("account_id = ?")
        params.append(account_id)
    if since:
        clauses.append("created_at >= ?")
        params.append(since)
    where = ("WHERE " + " AND ".join(clauses)) if clauses else ""
    return where, params


def weekly_post_counts(
    account_id: str | None = None, since: str | None = None, limit_weeks: int = 12
) -> list[sqlite3.Row]:
    """One row per (account, ISO week) with how many posts (own-profile +
    group) succeeded that week — the "tài khoản nào đăng bao nhiêu bài mỗi
    tuần" report."""
    conn = _connect()
    try:
        where, params = _base_where(account_id, since)
        extra = "success = 1 AND action IN ('post_to_own_profile', 'post_to_group')"
        where = f"{where} AND {extra}" if where else f"WHERE {extra}"
        cur = conn.execute(
            f"""
            SELECT account_id, strftime('%Y-W%W', created_at) AS week, COUNT(*) AS total
            FROM action_log
            {where}
            GROUP BY account_id, week
            ORDER BY week DESC, account_id
            LIMIT ?
            """,
            (*params, limit_weeks * 20),  # generous cap: weeks x a handful of accounts
        )
        return cur.fetchall()
    finally:
        conn.close()


def group_post_counts(account_id: str | None = None, since: str | None = None) -> list[sqlite3.Row]:
    """One row per group with how many posts succeeded there — the "đăng
    nhóm nào nhiều nhất" report."""
    conn = _connect()
    try:
        where, params = _base_where(account_id, since)
        extra = "success = 1 AND action = 'post_to_group'"
        where = f"{where} AND {extra}" if where else f"WHERE {extra}"
        cur = conn.execute(
            f"""
            SELECT account_id, target_group_name, target_url, COUNT(*) AS total
            FROM action_log
            {where}
            GROUP BY account_id, target_url
            ORDER BY total DESC
            """,
            params,
        )
        return cur.fetchall()
    finally:
        conn.close()


def action_type_counts(account_id: str | None = None, since: str | None = None) -> list[sqlite3.Row]:
    """Success/failure breakdown per action type — a quick health check
    (e.g. a spike in failed post_to_group could mean a broken selector or
    an account restriction, see docs/agents/safety-monitor.md).

    `rate_limited:` rows excluded (2026-09-11, same reasoning as
    summary_stats() above) — otherwise a busy account's normal rate-limit
    defers pile up under "Thất bại" next to actual broken-selector/timeout
    failures, with no way to tell them apart in this table."""
    conn = _connect()
    try:
        where, params = _base_where(account_id, since)
        extra = "(message IS NULL OR message NOT LIKE 'rate_limited:%')"
        where = f"{where} AND {extra}" if where else f"WHERE {extra}"
        cur = conn.execute(
            f"""
            SELECT action, success, COUNT(*) AS total
            FROM action_log
            {where}
            GROUP BY action, success
            ORDER BY action, success DESC
            """,
            params,
        )
        return cur.fetchall()
    finally:
        conn.close()


def summary_stats(account_id: str | None = None, since: str | None = None) -> dict:
    """One-row KPI overview for the top of /admin/reports: total
    successful/failed actions in the filtered window, the resulting
    success rate, and how many distinct accounts had any activity at all
    — a glance-and-go answer to "is everything roughly healthy" before
    reading the detailed tables below.

    `rate_limited:` rows excluded from total/succeeded/failed/success_rate
    (2026-09-11, owner request — see /admin/reports' "Đăng lại" warning
    fix, same conversation) — a run_task() call refused by RateLimiter
    before ever opening a browser (see agent.py's run_task(): the
    can_proceed() check happens before get_session()/action_fn()) isn't a
    real attempt at anything, so it shouldn't drag down "Thất bại"/"Tỉ lệ
    thành công" the same way an actual broken-selector or timeout failure
    does. `active_accounts` stays computed from ALL rows including
    rate-limited ones — an account that got rate-limited still clearly had
    activity, just not a completed one."""
    conn = _connect()
    try:
        where, params = _base_where(account_id, since)
        not_rate_limited = "(message IS NULL OR message NOT LIKE 'rate_limited:%')"
        cur = conn.execute(
            f"""
            SELECT
                SUM(CASE WHEN {not_rate_limited} THEN 1 ELSE 0 END) AS total,
                SUM(CASE WHEN {not_rate_limited} AND success THEN 1 ELSE 0 END) AS succeeded,
                COUNT(DISTINCT account_id) AS active_accounts
            FROM action_log
            {where}
            """,
            params,
        )
        row = cur.fetchone()
        total = row["total"] or 0
        succeeded = row["succeeded"] or 0
        failed = total - succeeded
        success_rate = round(succeeded / total * 100, 1) if total else None
        return {
            "total": total,
            "succeeded": succeeded,
            "failed": failed,
            "success_rate": success_rate,
            "active_accounts": row["active_accounts"] or 0,
        }
    finally:
        conn.close()


def recent_activity(
    limit: int = 50, offset: int = 0, account_id: str | None = None, since: str | None = None
) -> list[sqlite3.Row]:
    conn = _connect()
    try:
        where, params = _base_where(account_id, since)
        cur = conn.execute(
            f"SELECT * FROM action_log {where} ORDER BY id DESC LIMIT ? OFFSET ?",
            (*params, limit, offset),
        )
        return cur.fetchall()
    finally:
        conn.close()


def get_action_log(log_id: int) -> sqlite3.Row | None:
    """One action_log row by id — used by /admin/reports' "Đăng lại" button
    to re-read the account/action/target_url/content of a past attempt so
    it can be resubmitted as a new task."""
    conn = _connect()
    try:
        cur = conn.execute("SELECT * FROM action_log WHERE id = ?", (log_id,))
        return cur.fetchone()
    finally:
        conn.close()


def recent_activity_count(account_id: str | None = None, since: str | None = None) -> int:
    """Total matching rows for `recent_activity`'s filters, so
    /admin/reports can render "Trang X/Y" instead of guessing whether
    there's more to page through."""
    conn = _connect()
    try:
        where, params = _base_where(account_id, since)
        cur = conn.execute(f"SELECT COUNT(*) AS total FROM action_log {where}", params)
        return cur.fetchone()["total"] or 0
    finally:
        conn.close()


# --- "Theo từng lần đăng" report (2026-09-12) -------------------------------
#
# One row per (source_id, account_id) — every per-group post_to_group
# action_log row for the SAME side-B job, gathered into one job — instead
# of recent_activity()'s one-row-per-group flat list. Backed by
# idx_action_log_source (see _SCHEMA above). Only ever groups
# source_kind='job' rows (candidates have no per-group fan-out to gather).

def job_post_groups(
    account_id: str | None = None, since: str | None = None, limit: int = 20, offset: int = 0
) -> list[sqlite3.Row]:
    """One summary row per job: how many groups it went to, how many of
    those succeeded, when the first/last group post landed, and the raw
    side-B job data (MAX() just to pick the one — and only — non-NULL
    value out of the group; every row for the same job shares the exact
    same job_data, written once per row at log time purely because that's
    simpler than a separate jobs table for what's still small, per-row
    data — see log_action()'s docstring)."""
    conn = _connect()
    try:
        where, params = _base_where(account_id, since)
        extra = "source_kind = 'job'"
        where = f"{where} AND {extra}" if where else f"WHERE {extra}"
        cur = conn.execute(
            f"""
            SELECT
                source_id,
                account_id,
                MIN(created_at) AS first_posted_at,
                MAX(created_at) AS last_posted_at,
                COUNT(*) AS total_groups,
                SUM(success) AS succeeded_groups,
                MAX(job_data) AS job_data
            FROM action_log
            {where}
            GROUP BY source_id, account_id
            ORDER BY last_posted_at DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        )
        return cur.fetchall()
    finally:
        conn.close()


def job_post_groups_count(account_id: str | None = None, since: str | None = None) -> int:
    """Total distinct (source_id, account_id) groups matching
    job_post_groups()'s own filters — for "Trang X/Y", same idea as
    recent_activity_count()."""
    conn = _connect()
    try:
        where, params = _base_where(account_id, since)
        extra = "source_kind = 'job'"
        where = f"{where} AND {extra}" if where else f"WHERE {extra}"
        cur = conn.execute(
            f"SELECT COUNT(*) AS total FROM (SELECT 1 FROM action_log {where} GROUP BY source_id, account_id)",
            params,
        )
        return cur.fetchone()["total"] or 0
    finally:
        conn.close()


def job_post_group_detail(source_id: str, account_id: str) -> list[sqlite3.Row]:
    """Every per-group row for one job — target group, content actually
    posted THERE (may differ per group — see content_strategist.
    template_variants()), success/failure, and exactly when THAT group
    was posted to, oldest first."""
    conn = _connect()
    try:
        cur = conn.execute(
            """
            SELECT * FROM action_log
            WHERE source_id = ? AND account_id = ? AND source_kind = 'job'
            ORDER BY created_at
            """,
            (source_id, account_id),
        )
        return cur.fetchall()
    finally:
        conn.close()


# --- "Theo từng lần bình luận" report (2026-09-12, flattened 2026-09-12) ---
#
# Unlike job_post_groups() above, this is a FLAT one-row-per-action_log-row
# list, not grouped by (source_id, account_id) — a candidate only ever gets
# ONE comment (data_sync.py's sync_all() marks the candidate "seen" right
# after scheduling it, so it's never re-picked-up), so there's no per-group
# fan-out to collapse the way a job's multiple group-posts need (owner
# request: "chỉ có 1 bình luận cho từng bài viết nên không cần gom nhóm lại
# đâu, thể hiện rõ ra luôn"). A retried (via "Đăng lại") candidate just shows
# up as its own extra row, same as any other action_log entry would.

def candidate_comments(
    account_id: str | None = None, since: str | None = None, limit: int = 20, offset: int = 0
) -> list[sqlite3.Row]:
    """One row per candidate comment attempt — newest first."""
    conn = _connect()
    try:
        where, params = _base_where(account_id, since)
        extra = "source_kind = 'candidate'"
        where = f"{where} AND {extra}" if where else f"WHERE {extra}"
        cur = conn.execute(
            f"""
            SELECT * FROM action_log
            {where}
            ORDER BY created_at DESC
            LIMIT ? OFFSET ?
            """,
            (*params, limit, offset),
        )
        return cur.fetchall()
    finally:
        conn.close()


def candidate_comments_count(account_id: str | None = None, since: str | None = None) -> int:
    """Total rows matching candidate_comments()'s own filters — for
    "Trang X/Y", same idea as recent_activity_count()."""
    conn = _connect()
    try:
        where, params = _base_where(account_id, since)
        extra = "source_kind = 'candidate'"
        where = f"{where} AND {extra}" if where else f"WHERE {extra}"
        cur = conn.execute(f"SELECT COUNT(*) AS total FROM action_log {where}", params)
        return cur.fetchone()["total"] or 0
    finally:
        conn.close()


def successful_retry_log_ids(log_ids: list[int]) -> set[int]:
    """Which of `log_ids` already have a SUCCESSFUL retry logged against
    them (retry_of_log_id — see log_action()'s docstring) — one batched
    query per report page render instead of one per row. A retry that
    itself FAILED is deliberately not included: the original row should
    still offer "↻ Đăng lại" again in that case, same as any other failed
    row (2026-09-12, backs /admin/reports' "Đã đăng lại" status text)."""
    if not log_ids:
        return set()
    conn = _connect()
    try:
        placeholders = ",".join("?" for _ in log_ids)
        cur = conn.execute(
            f"SELECT DISTINCT retry_of_log_id FROM action_log "
            f"WHERE retry_of_log_id IN ({placeholders}) AND success = 1",
            log_ids,
        )
        return {row["retry_of_log_id"] for row in cur.fetchall()}
    finally:
        conn.close()
