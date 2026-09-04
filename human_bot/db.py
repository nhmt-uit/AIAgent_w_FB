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
    created_at         TEXT    NOT NULL
);
CREATE INDEX IF NOT EXISTS idx_action_log_account_time ON action_log(account_id, created_at);
CREATE INDEX IF NOT EXISTS idx_action_log_target ON action_log(target_url);
"""


def _connect() -> sqlite3.Connection:
    conn = sqlite3.connect(DB_PATH)
    conn.row_factory = sqlite3.Row
    return conn


def ensure_schema() -> None:
    conn = _connect()
    try:
        conn.executescript(_SCHEMA)
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
    created_at: str | None = None,
) -> None:
    """Record one attempted action, whatever the outcome. Called from the
    single choke point every action passes through — human_bot/agent.py's
    run_task() — so every manual post, queued post, scheduled fire, and
    /tasks call from n8n ends up here without each caller needing to log
    separately. Never let a logging failure break the actual task; callers
    should treat this as best-effort (see run_task()'s try/except around
    the call)."""
    conn = _connect()
    try:
        conn.execute(
            """
            INSERT INTO action_log
                (account_id, action, target_url, target_group_name, content,
                 success, message, source, source_kind, source_id, created_at)
            VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
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


def weekly_post_counts(account_id: str | None = None, limit_weeks: int = 12) -> list[sqlite3.Row]:
    """One row per (account, ISO week) with how many posts (own-profile +
    group) succeeded that week — the "tài khoản nào đăng bao nhiêu bài mỗi
    tuần" report."""
    conn = _connect()
    try:
        params: list = []
        where = "WHERE success = 1 AND action IN ('post_to_own_profile', 'post_to_group')"
        if account_id:
            where += " AND account_id = ?"
            params.append(account_id)
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


def group_post_counts(account_id: str | None = None) -> list[sqlite3.Row]:
    """One row per group with how many posts succeeded there — the "đăng
    nhóm nào nhiều nhất" report."""
    conn = _connect()
    try:
        params: list = []
        where = "WHERE success = 1 AND action = 'post_to_group'"
        if account_id:
            where += " AND account_id = ?"
            params.append(account_id)
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


def action_type_counts(account_id: str | None = None) -> list[sqlite3.Row]:
    """Success/failure breakdown per action type — a quick health check
    (e.g. a spike in failed post_to_group could mean a broken selector or
    an account restriction, see docs/agents/safety-monitor.md)."""
    conn = _connect()
    try:
        params: list = []
        where = ""
        if account_id:
            where = "WHERE account_id = ?"
            params.append(account_id)
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


def recent_activity(limit: int = 50, account_id: str | None = None) -> list[sqlite3.Row]:
    conn = _connect()
    try:
        if account_id:
            cur = conn.execute(
                "SELECT * FROM action_log WHERE account_id = ? ORDER BY id DESC LIMIT ?",
                (account_id, limit),
            )
        else:
            cur = conn.execute("SELECT * FROM action_log ORDER BY id DESC LIMIT ?", (limit,))
        return cur.fetchall()
    finally:
        conn.close()
