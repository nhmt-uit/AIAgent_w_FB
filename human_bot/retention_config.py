"""
Purpose of this file / Muc dich cua file nay:
EN: How long each kind of history is kept before its daily auto-cleanup
deletes it — configured on /admin/reports' "Cấu hình" tab and stored in
runtime_config.json (never .env; the old SCREENSHOT_RETENTION_DAYS /
SCHEDULE_RETENTION_DAYS / ACTION_LOG_RETENTION_DAYS env vars were removed
2026-09-28, owner request). A value of 0 (or below) means "never
auto-delete this kind" — deliberately the safe reading, since the
alternative reading ("delete everything older than 0 days") would wipe
data on what most people would assume is a "turn it off" value.

The 3 cleanups this drives run once at service startup and then every 24
hours (human_bot/service.py's _schedule_cleanup_loop /
_screenshot_cleanup_loop), each re-reading these values on every run — a
change saved in the UI applies at the next run, no restart needed, and a
too-aggressive typo can't delete anything instantly.
VI: Thoi han luu tung loai lich su truoc khi tu dong xoa hang ngay — cau hinh
o tab "Cau hinh" trang /admin/reports, luu trong runtime_config.json (khong
qua .env nua). 0 (hoac am) = khong bao gio tu xoa loai do.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class RetentionConfig:
    # Evidence screenshots (screenshots/) — ~5-6/day at ~600 KB each, so the
    # default keeps roughly 200 MB at the cap.
    screenshot_days: int = 60
    # Finished/failed/cancelled scheduled-task files (scheduled/posted,
    # failed, cancelled) + orphaned scheduled/missed/*.result.txt notes —
    # ~1.2 MB/month, trivially cheap to keep for ~6 months.
    schedule_days: int = 180
    # human_bot.db's action_log — the ONLY one that deletes report history
    # (everything on /admin/reports reads it), not just evidence files.
    action_log_days: int = 180
