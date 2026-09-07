"""
Purpose of this file / Muc dich cua file nay:
EN: Central place for runtime-tunable settings that the /admin web UI can
edit without touching .env or restarting the service. Stored as JSON on
disk (runtime_config.json at the project root, gitignored — this is
machine-local tuning state, not a secret and not meant to be shared via
git). Precedence: a value present in the JSON file overrides the
.env/code default defined in human_bot/humanize.py's config dataclasses
(HumanTypingConfig, HumanPacingConfig, HumanMouseConfig); any key absent
from the JSON file still falls back to that default. See
docs/skills/human-like-interaction.md and
docs/research/human-behavior-simulation.md for what each field means.
VI: Noi tap trung cac thiet lap co the chinh qua giao dien web /admin ma
khong can sua file .env hay khoi dong lai service. Duoc luu duoi dang
JSON tren dia (runtime_config.json o thu muc goc du an, da duoc gitignore
— day la trang thai tuy chinh rieng cho tung may, khong phai bi mat va
khong can chia se qua git). Thu tu uu tien: gia tri co trong file JSON se
ghi de len gia tri mac dinh tu .env/code trong cac dataclass cau hinh
cua human_bot/humanize.py (HumanTypingConfig, HumanPacingConfig,
HumanMouseConfig); key nao thieu trong JSON thi van dung gia tri mac
dinh do.
"""
import dataclasses
import json
import os
from pathlib import Path
from typing import Any

from human_bot.humanize import HumanMouseConfig, HumanPacingConfig, HumanTypingConfig
from human_bot.data_sync_config import DataSyncConfig
from human_bot.scheduling_config import SchedulingConfig
from human_bot.media import MediaConfig

RUNTIME_CONFIG_PATH = Path(__file__).resolve().parent.parent / "runtime_config.json"

# Fields a human operator is allowed to tune from the admin UI, one
# allowlist per config section. An explicit allowlist (rather than "every
# dataclass field") means a future field added to one of the config
# classes doesn't silently become admin-editable without a deliberate
# decision to add it here too.
EDITABLE_HUMAN_TYPING_FIELDS: list[str] = [
    "enabled",
    "wpm",
    "char_delay_stdev_ratio",
    "min_char_delay_ms",
    "word_pause_min_ms",
    "word_pause_max_ms",
    "punctuation_pause_min_ms",
    "punctuation_pause_max_ms",
    "typo_probability",
    "typo_notice_delay_min_ms",
    "typo_notice_delay_max_ms",
    "word_typo_probability",
    "fatigue_factor_per_char",
]

EDITABLE_PACING_FIELDS: list[str] = [
    "enabled",
    "page_load_pause_min_ms",
    "page_load_pause_max_ms",
    "composer_open_pause_min_ms",
    "composer_open_pause_max_ms",
    "ui_step_pause_min_ms",
    "ui_step_pause_max_ms",
    "reading_wpm",
    "reading_pause_min_ms",
    "reading_pause_max_ms",
    "reading_buffer_min_ms",
    "reading_buffer_max_ms",
]

EDITABLE_MOUSE_FIELDS: list[str] = [
    "enabled",
    "min_steps",
    "max_steps",
    "step_delay_min_ms",
    "step_delay_max_ms",
    "curve_offset_ratio",
    "overshoot_probability",
    "overshoot_ratio",
    "min_distance_for_curve_px",
]

# base_url is deliberately excluded — that's a deployment-level setting
# (which data-ingestion instance to talk to), not something to flip
# casually from a web form. Change it via .env (DATA_INGESTION_BASE_URL)
# if it ever needs to change.
EDITABLE_DATA_SYNC_FIELDS: list[str] = [
    "enabled",
    "poll_interval_minutes",
    "due_check_interval_seconds",
    "post_gap_min_minutes",
    "post_gap_max_minutes",
    "comment_gap_min_minutes",
    "comment_gap_max_minutes",
    "quiet_hour_start_local",
    "quiet_hour_end_local",
    "candidate_min_confidence",
    "candidate_max_age_days",
    "cache_retention_days",
]


def _read_all() -> dict[str, Any]:
    if not RUNTIME_CONFIG_PATH.exists():
        return {}
    try:
        with RUNTIME_CONFIG_PATH.open(encoding="utf-8") as f:
            data = json.load(f)
        return data if isinstance(data, dict) else {}
    except (json.JSONDecodeError, OSError):
        # A corrupt/unreadable file must never crash posting — fall back
        # to code/.env defaults and let the admin UI surface the problem.
        return {}


def _get_overrides(section_key: str, editable_fields: list[str]) -> dict[str, Any]:
    data = _read_all()
    overrides = data.get(section_key, {})
    return {k: v for k, v in overrides.items() if k in editable_fields}


def _get_config(config_cls, section_key: str, editable_fields: list[str]):
    base = config_cls()
    overrides = _get_overrides(section_key, editable_fields)
    return dataclasses.replace(base, **overrides) if overrides else base


def _save_overrides(section_key: str, editable_fields: list[str], values: dict[str, Any]) -> None:
    """Persist admin-edited values for one config section. Only known
    editable fields for that section are kept — anything else in `values`
    is silently dropped (defensive against a stray/unexpected form field)."""
    clean = {k: v for k, v in values.items() if k in editable_fields}
    data = _read_all()
    data[section_key] = clean
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- Typing ---------------------------------------------------------------

def get_human_typing_overrides() -> dict[str, Any]:
    return _get_overrides("human_typing", EDITABLE_HUMAN_TYPING_FIELDS)


def get_human_typing_config() -> HumanTypingConfig:
    """The config actually used when typing: .env/code defaults with any
    admin-saved JSON overrides layered on top."""
    return _get_config(HumanTypingConfig, "human_typing", EDITABLE_HUMAN_TYPING_FIELDS)


def save_human_typing_overrides(values: dict[str, Any]) -> None:
    _save_overrides("human_typing", EDITABLE_HUMAN_TYPING_FIELDS, values)


# --- Pacing -----------------------------------------------------------------

def get_pacing_overrides() -> dict[str, Any]:
    return _get_overrides("pacing", EDITABLE_PACING_FIELDS)


def get_pacing_config() -> HumanPacingConfig:
    """The config actually used for contextual pauses (page load, composer
    open, UI-step, reading-back-before-submit)."""
    return _get_config(HumanPacingConfig, "pacing", EDITABLE_PACING_FIELDS)


def save_pacing_overrides(values: dict[str, Any]) -> None:
    _save_overrides("pacing", EDITABLE_PACING_FIELDS, values)


# --- Mouse movement ---------------------------------------------------------

def get_mouse_overrides() -> dict[str, Any]:
    return _get_overrides("mouse", EDITABLE_MOUSE_FIELDS)


def get_mouse_config() -> HumanMouseConfig:
    """The config actually used for Bezier-curve mouse movement before clicks."""
    return _get_config(HumanMouseConfig, "mouse", EDITABLE_MOUSE_FIELDS)


def save_mouse_overrides(values: dict[str, Any]) -> None:
    _save_overrides("mouse", EDITABLE_MOUSE_FIELDS, values)


# --- Data sync (side-B poller) ---------------------------------------------

def get_data_sync_overrides() -> dict[str, Any]:
    return _get_overrides("data_sync", EDITABLE_DATA_SYNC_FIELDS)


def get_data_sync_config() -> DataSyncConfig:
    """The config actually used by human_bot/data_sync.py: .env/code
    defaults (including base_url, which is NOT admin-editable) with any
    admin-saved JSON overrides for the editable fields layered on top."""
    return _get_config(DataSyncConfig, "data_sync", EDITABLE_DATA_SYNC_FIELDS)


def save_data_sync_overrides(values: dict[str, Any]) -> None:
    _save_overrides("data_sync", EDITABLE_DATA_SYNC_FIELDS, values)


# --- Scheduling (fire gate — applies to ANY scheduled task) -----------------
#
# auto_fire_enabled moved here from the "data_sync" section (2026-09-07):
# it gates human_bot/data_sync.py's fire_due_tasks(), which fires EVERY due
# task in /admin/schedule regardless of source — including ones composed
# by hand at /admin/post — so it never really belonged under "Đồng bộ dữ
# liệu bên B". A value saved under the old "data_sync" key (from before
# this move) is still honored as a one-time fallback below, so an
# operator's existing choice isn't silently reset to the off-by-default
# value the first time this runs after upgrading.

EDITABLE_SCHEDULING_FIELDS: list[str] = [
    "auto_fire_enabled",
]


def get_scheduling_overrides() -> dict[str, Any]:
    """Admin-saved overrides for the "scheduling" section, falling back to
    a value still left under the old "data_sync" section (from before
    auto_fire_enabled moved here, 2026-09-07) if this section has never
    been saved itself. Applying the fallback HERE — not only in
    get_scheduling_config() below — matters: /admin/config's checkbox is
    rendered straight from this function's return value, so if the
    fallback lived only in get_scheduling_config(), the checkbox would
    show unchecked/default while the config actually in effect (and the
    live status banner on /admin/post and /admin/schedule, which does
    call get_scheduling_config()) showed enabled — an inconsistency a
    user hit right after this section was introduced."""
    overrides = _get_overrides("scheduling", EDITABLE_SCHEDULING_FIELDS)
    if "auto_fire_enabled" not in overrides:
        legacy = _get_overrides("data_sync", ["auto_fire_enabled"])
        if "auto_fire_enabled" in legacy:
            overrides = {**overrides, "auto_fire_enabled": legacy["auto_fire_enabled"]}
    return overrides


def get_scheduling_config() -> SchedulingConfig:
    """The config actually used to gate human_bot/data_sync.py's
    fire_due_tasks(): .env/code default with get_scheduling_overrides()
    (including its legacy "data_sync" fallback) layered on top. Built from
    that function directly rather than the generic _get_config() helper,
    since _get_config() would call the private _get_overrides() and skip
    the legacy fallback."""
    overrides = get_scheduling_overrides()
    base = SchedulingConfig()
    return dataclasses.replace(base, **overrides) if overrides else base


def save_scheduling_overrides(values: dict[str, Any]) -> None:
    _save_overrides("scheduling", EDITABLE_SCHEDULING_FIELDS, values)


# --- Media (attach-random-meme toggle, human_bot/media.py) ------------------

EDITABLE_MEDIA_FIELDS: list[str] = [
    "attach_random_meme_default",
]


def get_media_overrides() -> dict[str, Any]:
    return _get_overrides("media", EDITABLE_MEDIA_FIELDS)


def get_media_config() -> MediaConfig:
    """The config actually used by human_bot/agent.py's run_task() to
    decide whether to auto-attach a random meme."""
    return _get_config(MediaConfig, "media", EDITABLE_MEDIA_FIELDS)


def save_media_overrides(values: dict[str, Any]) -> None:
    _save_overrides("media", EDITABLE_MEDIA_FIELDS, values)


# --- Joined groups (per-account, admin-editable) ----------------------------
#
# AccountConfig.joined_groups (human_bot/config.py) is a code default —
# fine for one or two accounts set up by hand, but every group join/leave
# would otherwise need a code change + restart. This mirrors that default
# in runtime_config.json instead, under a per-account key, editable from
# /admin/groups without touching code. A runtime entry for an account_id
# fully replaces that account's code-default list (not merged) — the admin
# page always shows/edits the *effective* list, so there's one source of
# truth on screen at a time. Each group is stored as {"name": ..., "url":
# ...} — name+url together, not the URL alone, so a human looking at the
# admin page or this JSON file can tell which group is which without
# opening every link.

_JOINED_GROUPS_KEY = "joined_groups"


def get_joined_groups(account_id: str) -> list["GroupRef"]:
    """Effective list of joined groups for this account: a
    runtime_config.json override if one has ever been saved for this
    account_id, else the code default from human_bot/config.py's
    AccountConfig.

    Any saved entry missing an `id` (data written before GroupRef gained
    that field) gets one generated on the spot (GroupRef's own
    default_factory) AND immediately persisted back — a fresh random id
    on every read, never saved, would mean /admin/groups' edit/delete
    modal (opened with one id baked in) never matches by the time the
    form is submitted."""
    from human_bot.config import GroupRef, get_account, new_group_id

    data = _read_all()
    overrides = data.get(_JOINED_GROUPS_KEY, {})
    if account_id in overrides and isinstance(overrides[account_id], list):
        result = []
        used_ids: set[str] = set()
        needs_migration = False
        for item in overrides[account_id]:
            if isinstance(item, dict) and str(item.get("url", "")).strip():
                gid = str(item.get("id", "")).strip()
                if not gid:
                    # new_group_id(), not GroupRef's own bare
                    # default_factory — checked against every id already
                    # used in this account's list (including ones just
                    # generated earlier in this same migration pass), not
                    # just probabilistically unique.
                    gid = new_group_id(used_ids)
                    needs_migration = True
                used_ids.add(gid)
                result.append(GroupRef(
                    id=gid,
                    name=str(item.get("name", "")).strip(),
                    url=str(item["url"]).strip(),
                ))
        if needs_migration:
            save_joined_groups(account_id, result)
        return result
    try:
        return list(get_account(account_id).joined_groups)
    except ValueError:
        return []


def save_joined_groups(account_id: str, groups: list["GroupRef"]) -> None:
    data = _read_all()
    overrides = data.get(_JOINED_GROUPS_KEY, {})
    if not isinstance(overrides, dict):
        overrides = {}
    overrides[account_id] = [
        {"id": g.id, "name": g.name.strip(), "url": g.url.strip()} for g in groups if g.url.strip()
    ]
    data[_JOINED_GROUPS_KEY] = overrides
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- Registered accounts (admin-added, no code edit needed) ----------------
#
# human_bot/config.py's ACCOUNTS dict is still the code-level default (fine
# for a permanent, committed account). This mirrors the joined_groups
# pattern above so a NEW account — after running bootstrap_login.py to
# create its storage_state.json — can be registered from /admin/accounts
# instead of hand-editing config.py and restarting the service. Stored as
# a list (not a dict) to preserve registration order. human_bot/config.py's
# get_all_accounts() merges this with ACCOUNTS; a runtime-registered
# account only gets the code defaults for rate_limits/joined_groups (tune
# those afterwards at /admin/config / /admin/groups) — registering an
# account_id that already exists in ACCOUNTS is a no-op here (code wins),
# and /admin/accounts blocks that case up front.

_ACCOUNTS_KEY = "accounts"


def get_registered_accounts() -> list[dict[str, str]]:
    data = _read_all()
    raw = data.get(_ACCOUNTS_KEY, [])
    if not isinstance(raw, list):
        return []
    result = []
    for item in raw:
        if isinstance(item, dict) and str(item.get("account_id", "")).strip():
            account_id = str(item["account_id"]).strip()
            display_name = str(item.get("display_name", "")).strip() or account_id
            result.append({"account_id": account_id, "display_name": display_name})
    return result


def save_registered_account(account_id: str, display_name: str) -> None:
    accounts = [a for a in get_registered_accounts() if a["account_id"] != account_id]
    accounts.append({"account_id": account_id, "display_name": display_name.strip() or account_id})
    data = _read_all()
    data[_ACCOUNTS_KEY] = accounts
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def delete_registered_account(account_id: str) -> None:
    data = _read_all()
    data[_ACCOUNTS_KEY] = [a for a in get_registered_accounts() if a["account_id"] != account_id]
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- Account pause state (safety, applies to ANY account) -------------------
#
# Overrides AccountConfig.status regardless of whether the account came
# from human_bot/config.py's ACCOUNTS dict or was registered at
# /admin/accounts — same reasoning as joined_groups above: pausing is a
# runtime safety action ("stop the bot on this account right now"), not
# something that should ever require a code edit + restart. Set
# automatically by human_bot/agent.py's run_task() when
# human_bot/safety.py's AnomalyDetected fires (a page showed a Facebook
# restriction/checkpoint signal), and clearable by a human at
# /admin/accounts once they've confirmed the account is actually fine.

_ACCOUNT_STATUS_KEY = "account_status"


def get_paused_account_ids() -> set[str]:
    data = _read_all()
    raw = data.get(_ACCOUNT_STATUS_KEY, {})
    if not isinstance(raw, dict):
        return set()
    return {aid for aid, status in raw.items() if status == "paused"}


def set_account_paused(account_id: str, paused: bool) -> None:
    data = _read_all()
    raw = data.get(_ACCOUNT_STATUS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    if paused:
        raw[account_id] = "paused"
    else:
        raw.pop(account_id, None)
    data[_ACCOUNT_STATUS_KEY] = raw
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- Account removal (applies to ANY account, including code-level ones) ---
#
# A runtime-registered account can just be dropped from _ACCOUNTS_KEY
# (delete_registered_account, above) — but a code-level ACCOUNTS entry in
# human_bot/config.py can't actually be removed from a running process,
# and the project owner asked for "Xoá" to work on EVERY account, not
# only ones added through /admin/accounts. This list is the same kind of
# override as account_status above: get_all_accounts() drops any id
# found here from its result entirely, regardless of where the
# AccountConfig itself came from. Undo path for a code-level account:
# just register it again at /admin/accounts with the same account_id —
# it'll come back with the same effective defaults (rate limits and
# joined_groups already living in their own overrides, unaffected by
# this).

_REMOVED_ACCOUNTS_KEY = "removed_accounts"


def get_removed_account_ids() -> set[str]:
    data = _read_all()
    raw = data.get(_REMOVED_ACCOUNTS_KEY, [])
    if not isinstance(raw, list):
        return set()
    return {str(aid) for aid in raw if str(aid).strip()}


def set_account_removed(account_id: str, removed: bool) -> None:
    ids = get_removed_account_ids()
    if removed:
        ids.add(account_id)
    else:
        ids.discard(account_id)
    data = _read_all()
    data[_REMOVED_ACCOUNTS_KEY] = sorted(ids)
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- Per-account rate limit overrides ---------------------------------------
#
# human_bot/config.py's AccountConfig.rate_limits (a RateLimits dataclass:
# posts_per_day, comments_per_hour, comments_per_day, likes_per_hour,
# min_delay_seconds, max_delay_seconds) is a code-level default — the same
# 6 numbers for every account unless hand-customized in config.py. This
# lets /admin/accounts override any of those fields per account_id instead
# — a new/low-trust account might want tighter limits, an established one
# might tolerate looser ones — without a code edit or restart. Applied by
# human_bot/config.py's get_all_accounts(), same layering as account_status
# and joined_groups: human_bot/safety.py's RateLimiter just reads
# `account.rate_limits` off whatever AccountConfig it's given, so it picks
# this up automatically with no separate call site to remember.

_RATE_LIMITS_KEY = "rate_limits"
EDITABLE_RATE_LIMITS_FIELDS: list[str] = [
    "posts_per_day",
    "comments_per_hour",
    "comments_per_day",
    "likes_per_hour",
    "min_delay_seconds",
    "max_delay_seconds",
]


def get_rate_limits_overrides(account_id: str) -> dict[str, Any]:
    data = _read_all()
    raw = data.get(_RATE_LIMITS_KEY, {})
    if not isinstance(raw, dict):
        return {}
    overrides = raw.get(account_id, {})
    if not isinstance(overrides, dict):
        return {}
    return {k: v for k, v in overrides.items() if k in EDITABLE_RATE_LIMITS_FIELDS}


def save_rate_limits_overrides(account_id: str, values: dict[str, Any]) -> None:
    """`values` empty (or every field cleared) removes the override
    entirely, falling back to the account's code-level default — the
    "Khôi phục mặc định" case in /admin/accounts' rate-limits modal."""
    clean = {k: v for k, v in values.items() if k in EDITABLE_RATE_LIMITS_FIELDS}
    data = _read_all()
    raw = data.get(_RATE_LIMITS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    if clean:
        raw[account_id] = clean
    else:
        raw.pop(account_id, None)
    data[_RATE_LIMITS_KEY] = raw
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

