"""
Purpose of this file / Muc dich cua file nay:
EN: Config for the side-B data-sync poller (human_bot/data_sync.py) — poll
cadence, the safety gate that separates "fetch + dedupe" from "actually
post to Facebook", the randomized scheduling gaps between posts/comments,
candidate filtering thresholds, and dedup-cache retention. Same
env-override + /admin-editable pattern as human_bot/humanize.py's config
dataclasses (HumanTypingConfig, HumanPacingConfig, HumanMouseConfig) — see
human_bot/runtime_config.py for how the /admin overrides layer on top of
these .env/code defaults. See docs/architecture.md section 3c for the
full design this config drives.
VI: Cau hinh cho bo dong bo du lieu tu ben B (human_bot/data_sync.py) —
nhip goi API, cong tac an toan tach rieng "lay + chong trung" voi "thuc
su dang len Facebook", khoang cach ngau nhien giua cac luot dang/comment,
nguong loc ung vien, va thoi gian giu cache chong trung. Dung chung mot
kieu env-override + chinh duoc qua /admin voi cac dataclass cau hinh
trong human_bot/humanize.py — xem human_bot/runtime_config.py de biet
cach /admin ghi de len cac gia tri mac dinh .env/code nay. Xem
docs/architecture.md muc 3c de biet toan bo thiet ke ma file cau hinh
nay dieu khien.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_float(name: str, default: float) -> float:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


def _env_str(name: str, default: str) -> str:
    raw = os.environ.get(name)
    return default if raw is None or raw.strip() == "" else raw.strip()


@dataclass
class DataSyncConfig:
    # Master switch for the whole poller (fetch + dedupe + schedule). Safe
    # to leave on — this alone never touches Facebook, only side B's API.
    enabled: bool = field(default_factory=lambda: _env_bool("DATA_SYNC_ENABLED", True))

    # SAFETY GATE — separate from `enabled` on purpose. When False, the
    # poller still fetches/dedupes/schedules normally so you can review
    # what it *would* post in /admin/schedule, but the due-task loop will
    # never actually call run_task() — nothing reaches Facebook until this
    # is explicitly turned on. See docs/agents/content-strategist.md,
    # "Implementation plan" — same "stage before trusting" principle.
    auto_fire_enabled: bool = field(
        default_factory=lambda: _env_bool("DATA_SYNC_AUTO_FIRE_ENABLED", False)
    )

    # How often to call side B's API for new jobs/candidates.
    poll_interval_minutes: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_POLL_INTERVAL_MINUTES", 15.0)
    )
    # How often to check whether any scheduled task has become due.
    due_check_interval_seconds: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_DUE_CHECK_INTERVAL_SECONDS", 60.0)
    )

    # Randomized gap between one scheduled group post and the next (a
    # sequential chain, not a fixed cadence — see docs/architecture.md
    # section 3c and docs/skills/rate-limiting-pacing.md).
    post_gap_min_minutes: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_POST_GAP_MIN_MINUTES", 20.0)
    )
    post_gap_max_minutes: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_POST_GAP_MAX_MINUTES", 90.0)
    )
    # Same idea, for candidate outreach comments (kept as a separate chain
    # from posts — different action type, different rate-limit row in
    # docs/skills/rate-limiting-pacing.md).
    comment_gap_min_minutes: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_COMMENT_GAP_MIN_MINUTES", 10.0)
    )
    comment_gap_max_minutes: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_COMMENT_GAP_MAX_MINUTES", 45.0)
    )

    # Avoid scheduling into implausible waking hours (local time) — see
    # docs/skills/rate-limiting-pacing.md, "avoid 1am-6am". A time that
    # lands inside this window gets pushed forward to the window's end
    # instead, rather than skipped.
    quiet_hour_start_local: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_QUIET_HOUR_START", 1.0)
    )
    quiet_hour_end_local: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_QUIET_HOUR_END", 6.0)
    )

    # /api/candidates filtering — see docs/architecture.md section 3c,
    # following side B's own documented recommendation.
    candidate_min_confidence: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_CANDIDATE_MIN_CONFIDENCE", 0.8)
    )
    candidate_max_age_days: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_CANDIDATE_MAX_AGE_DAYS", 14.0)
    )

    # How long a fetched item's id stays in the local dedup cache before
    # being pruned — conservative default, side B's data doesn't document
    # how far back a record might resurface (see docs/architecture.md
    # section 3c).
    cache_retention_days: float = field(
        default_factory=lambda: _env_float("DATA_SYNC_CACHE_RETENTION_DAYS", 45.0)
    )

    base_url: str = field(
        default_factory=lambda: _env_str("DATA_INGESTION_BASE_URL", "http://localhost:3100")
    )
