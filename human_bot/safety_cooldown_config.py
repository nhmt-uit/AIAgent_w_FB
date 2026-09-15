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
immediately" — it means "run at a reduced rate for `cooldown_days` days,
then automatically return to whatever rate limit applied before the
pause."

Rewritten to 2 stepped weeks (2026-09-15, owner design, after a real bug
where nested pause/resume cycles permanently lost an account's true
rate limits — see human_bot/runtime_config.py's
get_active_cooldown_rate_limits()'s docstring for the full incident):
week 1 (days 0 to cooldown_days/2) is the flat floor below, for EVERY
account regardless of age tier; week 2 (cooldown_days/2 to cooldown_days)
steps established tiers up one notch (human_bot/config.py's
COOLDOWN_WEEK2_STEP_UP_TIER) instead of leaving them at the newest-
account floor the whole time. After `cooldown_days`, the account's real
rate-limit override (never touched during the whole cooldown) simply
applies again on its own — nothing to restore.
See docs/skills/anomaly-detection.md and human_bot/runtime_config.py's
resume_account()/get_active_cooldown_rate_limits().
VI: Cau hinh cho giai doan ngay sau khi con nguoi kich hoat lai mot tai
khoan bi tam dung tu dong boi AnomalyDetected (human_bot/safety.py). Dua
tren mot chia se thuc te ben ngoai (bai dang nhom Facebook, 2026-09-07):
tai khoan quay lai hanh vi cu ngay sau khi het han che thi de bi dinh lai
rat nhanh, trong khi mot nguoi co tinh "im" them 1 tuan sau khi het han
che thi 3 thang sau khong bi gi. Nen "kich hoat lai" o day khong co nghia
la chay full toc do ngay - ma la chay voi gioi han giam trong
`cooldown_days` ngay, roi tu dong tro lai gioi han truoc do.

Viet lai thanh 2 tuan co nac (2026-09-15, owner thiet ke, sau 1 bug that
mat vinh vien rate-limit goc khi tam dung/kich hoat lai chong lap nhau —
xem docstring cua get_active_cooldown_rate_limits() trong
human_bot/runtime_config.py de biet toan bo su co): tuan 1 (ngay 0 den
cooldown_days/2) la muc san co dinh ben duoi, ap dung cho MOI tai khoan
bat ke tuoi; tuan 2 (cooldown_days/2 den cooldown_days) nhich cac tier
da "truong thanh" len 1 nac (human_bot/config.py's
COOLDOWN_WEEK2_STEP_UP_TIER) thay vi giu nguyen muc san ca 2 tuan. Sau
`cooldown_days`, override rate-limit that cua tai khoan (chua bao gio bi
dung toi suot qua trinh ha nhiet) tu no ap dung lai — khong can khoi
phuc gi ca.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SafetyCooldownConfig:
    # Master toggle — when False, "Kích hoạt lại" behaves exactly like
    # before this feature existed (just clears the pause, no reduced
    # limits applied).
    enabled: bool = True

    # Total days after resume the cooldown lasts — split into 2 equal
    # halves (cooldown_days/2 each) by get_active_cooldown_rate_limits():
    # week 1 = the flat floor below for every tier, week 2 = the
    # per-tier step-up (COOLDOWN_WEEK2_STEP_UP_TIER in human_bot/
    # config.py). After this many days, the account's real rate-limit
    # override (untouched this whole time) simply applies again.
    cooldown_days: int = 14

    # Floor RateLimits (human_bot/config.py's RateLimits shape) applied
    # for week 1 of the cooldown (and the whole cooldown for
    # "under_1_month" accounts, which have no lower tier to step up
    # from in week 2 — see COOLDOWN_WEEK2_STEP_UP_TIER). Deliberately
    # much lower than even the newest-account tier preset (5 posts/day)
    # — the goal right after resuming is "prove to Facebook this account
    # behaves normally again", not "resume the full broadcast schedule".
    # min/max_delay_seconds here should stay >= every tier preset's own
    # delay range, since this floor is meant to be MORE conservative
    # than any of them, never less.
    posts_per_day: int = 1
    comments_per_hour: int = 1
    comments_per_day: int = 2
    likes_per_hour: int = 2
    min_delay_seconds: int = 7200
    max_delay_seconds: int = 14400
