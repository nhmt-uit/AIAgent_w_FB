"""
Purpose of this file / Muc dich cua file nay:
EN: Saves an evidence screenshot for every posting attempt — success or
failure — and prunes old ones after a retention window. Called from the
single choke point every action passes through, human_bot/agent.py's
run_task() (same reasoning as human_bot/db.py's action_log: one call
site, not one per action function). A screenshot on SUCCESS is proof the
action actually did what it claims (see human_bot/actions.py's
post-submit verification, added alongside this); a screenshot on FAILURE
is what actually lets a human debug what Facebook's UI showed at the
moment something went wrong, instead of guessing from a text message
alone. Same directory-per-account, gitignored, auto-pruned storage
pattern as accounts/, scheduled/, data_sync_cache/ — see cleanup_old()
below, run daily from human_bot/service.py exactly like
human_bot/schedule_store.py's cleanup_old().
VI: Luu anh chup man hinh lam bang chung cho moi lan thu dang bai — ca
thanh cong lan that bai — va tu dong don anh cu sau mot khoang thoi gian
giu lai. Goi tu dung 1 cho duy nhat ma moi hanh dong deu di qua,
human_bot/agent.py's run_task() (cung ly do voi human_bot/db.py's
action_log: mot noi goi, khong phai moi ham hanh dong tu goi rieng). Anh
luc THANH CONG la bang chung hanh dong that su lam dung nhu no bao cao
(xem buoc xac minh sau khi dang o human_bot/actions.py, them cung luc voi
file nay); anh luc THAT BAI la thu giup con nguoi debug duoc Facebook
dang hien gi luc loi xay ra, thay vi doan mo tu mot dong thong bao loi.
Cung kieu luu theo thu muc rieng tung tai khoan, gitignore, tu don dep
nhu accounts/, scheduled/, data_sync_cache/ — xem cleanup_old() ben duoi,
chay hang ngay tu human_bot/service.py giong het
human_bot/schedule_store.py's cleanup_old().
"""
from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from pathlib import Path

from playwright.async_api import Page

SCREENSHOTS_ROOT = Path(__file__).resolve().parent.parent / "screenshots"


async def capture(page: Page, account_id: str, action: str, success: bool) -> str | None:
    """Best-effort — a screenshot failure (page already closed/crashed,
    disk full, whatever) must never break the actual task, so this always
    returns None on any error instead of raising. Filename carries
    account/action/success/timestamp so a directory listing alone is
    readable without opening every file."""
    try:
        account_dir = SCREENSHOTS_ROOT / account_id
        account_dir.mkdir(parents=True, exist_ok=True)
        stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%f")[:-3] + "Z"
        status = "success" if success else "fail"
        safe_action = "".join(c if c.isalnum() or c in "-_" else "_" for c in action)
        path = account_dir / f"{stamp}_{safe_action}_{status}.png"
        await page.screenshot(path=str(path))
        return str(path)
    except Exception:  # noqa: BLE001 — evidence-gathering must never fail the task itself
        return None


def cleanup_old(retention_days: int | None = None) -> int:
    """Permanently delete screenshots older than `retention_days`
    (default: SCREENSHOT_RETENTION_DAYS in .env, or 30) — mirrors
    human_bot/schedule_store.py's cleanup_old() exactly. Returns the
    number of files removed, for logging/visibility. A row in
    /admin/reports whose screenshot got pruned this way just shows no
    image link anymore — the text history in human_bot.db is untouched."""
    if retention_days is None:
        retention_days = int(os.environ.get("SCREENSHOT_RETENTION_DAYS", "30") or "30")
    if not SCREENSHOTS_ROOT.is_dir():
        return 0
    cutoff = datetime.now(timezone.utc) - timedelta(days=retention_days)
    removed = 0
    for path in SCREENSHOTS_ROOT.rglob("*.png"):
        try:
            if not path.is_file():
                continue
            mtime = datetime.fromtimestamp(path.stat().st_mtime, tz=timezone.utc)
            if mtime < cutoff:
                path.unlink()
                removed += 1
        except OSError:
            continue
    return removed
