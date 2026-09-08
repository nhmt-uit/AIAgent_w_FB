"""
Purpose of this file / Muc dich cua file nay:
EN: Config for what happens right after a human resumes an account that
was auto-paused by human_bot/safety.py's AnomalyDetected. Based on a real
external report (Facebook group post shared 2026-09-07, r/socialmedia-
adjacent community discussing group-posting restrictions): accounts that
resumed their previous behavior immediately after a restriction lifted got
flagged again quickly, while one operator who deliberately stayed quiet
for an extra week past the lifted restriction had 3 clean months
afterward. So "resume" here does not mean "back to full speed
immediately" — it means "run at a reduced rate for `cooldown_days`, then
automatically return to whatever rate limit applied before the pause."
See docs/skills/anomaly-detection.md and human_bot/runtime_config.py's
resume_account()/_expire_resume_cooldown_if_due().
VI: Cau hinh cho giai doan ngay sau khi con nguoi kich hoat lai mot tai
khoan bi tam dung tu dong boi AnomalyDetected (human_bot/safety.py). Dua
tren mot chia se thuc te ben ngoai (bai dang nhom Facebook, 2026-09-07):
tai khoan quay lai hanh vi cu ngay sau khi het han che thi de bi dinh lai
rat nhanh, trong khi mot nguoi co tinh "im" them 1 tuan sau khi het han
che thi 3 thang sau khong bi gi. Nen "kich hoat lai" o day khong co nghia
la chay full toc do ngay - ma la chay voi gioi han giam trong
`cooldown_days` ngay, roi tu dong tro lai gioi han truoc do.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SafetyCooldownConfig:
    # Master toggle — when False, "Kích hoạt lại" behaves exactly like
    # before this feature existed (just clears the pause, no reduced
    # limits applied).
    enabled: bool = True

    # How many days after resume to keep the reduced limits below in
    # effect, before automatically restoring whatever rate limit override
    # (or lack of one) existed right before the account was paused.
    cooldown_days: int = 7

    # Reduced RateLimits (human_bot/config.py's RateLimits shape) applied
    # for `cooldown_days` after resume. Deliberately much lower than the
    # RateLimits defaults (20 posts/day, 1-2h between actions) — the goal
    # during cooldown is "prove to Facebook this account behaves normally
    # again", not "resume the full broadcast schedule". min/max_delay_seconds
    # here should stay >= RateLimits' own defaults, since cooldown is
    # meant to be MORE conservative, never less.
    posts_per_day: int = 1
    comments_per_hour: int = 1
    comments_per_day: int = 2
    likes_per_hour: int = 2
    min_delay_seconds: int = 7200
    max_delay_seconds: int = 14400
