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
import asyncio
import dataclasses
import json
import os
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

from human_bot.humanize import HumanMouseConfig, HumanPacingConfig, HumanScrollConfig, HumanTypingConfig
from human_bot.config import ACCOUNT_AGE_TIERS, COOLDOWN_WEEK2_STEP_UP_TIER, RateLimits
from human_bot.data_sync_config import DataSyncConfig
from human_bot.scheduling_config import SchedulingConfig
from human_bot.media import MediaConfig
from human_bot.safety_cooldown_config import SafetyCooldownConfig
from human_bot.secrets_config import SecretsConfig

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
    "click_delay_min_ms",
    "click_delay_max_ms",
    "jitter_px",
]

EDITABLE_SCROLL_FIELDS: list[str] = [
    "enabled",
    "step_delay_min_ms",
    "step_delay_max_ms",
    "max_step_px",
    "deceleration_ratio",
    "max_iterations",
]

# base_url is deliberately excluded — that's a deployment-level setting
# (which data-ingestion instance to talk to), not something to flip
# casually from a web form. Change it via .env (DATA_INGESTION_BASE_URL)
# if it ever needs to change.
EDITABLE_SAFETY_COOLDOWN_FIELDS: list[str] = [
    "enabled",
    "cooldown_days",
    "posts_per_day",
    "comments_per_hour",
    "comments_per_day",
    "likes_per_hour",
    "min_delay_seconds",
    "max_delay_seconds",
]

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
    "max_overflow_business_days",
    "job_post_ai_enabled",
    "candidate_reply_ai_enabled",
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
    notify_config_changed()


# --- Wake signal for human_bot/service.py's background loops ---------------
#
# A saved config change must apply the moment it's saved, not whenever a
# background loop next happens to wake up on its own — see
# human_bot/service.py's _data_sync_poll_loop()/_data_sync_fire_loop() for
# the incident this fixes (2026-09-08): those loops used to compute one
# `asyncio.sleep(interval)` from whatever config was current when the
# sleep STARTED, so raising the poll interval, or flipping `enabled` back
# on, from /admin/config had no effect until that stale sleep happened to
# run out — up to the PREVIOUS interval's full length later, with no way
# to apply it short of restarting the whole service (a human changing a
# setting in the admin UI must never require that).
#
# This lives here rather than in human_bot/service.py because both
# human_bot/admin.py (the writer, via _save_overrides() above and the
# few per-account setters below that don't go through it) and
# human_bot/service.py (the reader/waiter) already import
# human_bot/runtime_config.py — putting it in service.py instead would
# make admin.py import service.py, a circular import (service.py already
# imports admin.py's router). asyncio.Event() is safe to construct here at
# module import time (outside any running loop) on Python 3.10+, which
# this project targets — it only binds to a loop the first time it's
# awaited, not at construction.
_config_changed_event = asyncio.Event()


def get_config_changed_event() -> asyncio.Event:
    return _config_changed_event


def notify_config_changed() -> None:
    """Call after any write that a background loop's timing/gating
    decisions depend on. Safe to call more times than strictly necessary
    (a loop simply re-reads current config a bit early and finds nothing
    changed) — never call it from a hot path that isn't an explicit
    config write."""
    _config_changed_event.set()


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


# --- Scrolling ----------------------------------------------------------

def get_scroll_overrides() -> dict[str, Any]:
    return _get_overrides("scroll", EDITABLE_SCROLL_FIELDS)


def get_scroll_config() -> HumanScrollConfig:
    """The config actually used for eased wheel-scroll before a click
    (human_bot/humanize.py's human_scroll_to(), called from human_click())."""
    return _get_config(HumanScrollConfig, "scroll", EDITABLE_SCROLL_FIELDS)


def save_scroll_overrides(values: dict[str, Any]) -> None:
    _save_overrides("scroll", EDITABLE_SCROLL_FIELDS, values)


# --- Secrets (admin-managed API keys) --------------------------------------
# See human_bot/secrets_config.py's docstring for why this is its own
# section instead of folded into a behavior-tuning table.

EDITABLE_SECRETS_FIELDS: list[str] = [
    "ai_provider",
    "anthropic_api_key", "anthropic_model",
    "openai_api_key", "openai_model",
    "gemini_api_key", "gemini_model",
    "custom_api_key", "custom_base_url", "custom_model",
]


def get_secrets_overrides() -> dict[str, Any]:
    return _get_overrides("secrets", EDITABLE_SECRETS_FIELDS)


def get_secrets_config() -> SecretsConfig:
    return _get_config(SecretsConfig, "secrets", EDITABLE_SECRETS_FIELDS)


def save_secrets_overrides(values: dict[str, Any]) -> None:
    _save_overrides("secrets", EDITABLE_SECRETS_FIELDS, values)


@dataclasses.dataclass
class ActiveAIProviderConfig:
    """What human_bot/ai_client.py needs to actually make a call: which
    provider, its key, its model, and (for "custom" only) its base URL —
    resolved from whichever provider is currently selected in
    SecretsConfig.ai_provider, so ai_client.py never has to know about
    SecretsConfig's per-provider field naming."""
    provider: str
    api_key: str
    model: str
    base_url: str = ""


# provider -> (key field, model field, base_url field or None)
_AI_PROVIDER_FIELD_MAP: dict[str, tuple[str, str, str | None]] = {
    "anthropic": ("anthropic_api_key", "anthropic_model", None),
    "openai": ("openai_api_key", "openai_model", None),
    "gemini": ("gemini_api_key", "gemini_model", None),
    "custom": ("custom_api_key", "custom_model", "custom_base_url"),
}

# Env var fallback per provider, mirroring the override-wins-when-set
# precedence every other section here already uses. Gemini/custom have no
# established env var in this project, so they're admin-UI-only.
_AI_PROVIDER_ENV_FALLBACK: dict[str, str] = {
    "anthropic": "ANTHROPIC_API_KEY",
    "openai": "OPENAI_API_KEY",
}


def get_active_ai_provider_config() -> ActiveAIProviderConfig:
    """Resolves the currently selected AI provider's key/model/base_url —
    the single source of truth human_bot/ai_client.py's call_ai_text()
    reads from, so content_strategist.py's prompt-building code never
    needs to know which provider is active."""
    cfg = get_secrets_config()
    provider = (cfg.ai_provider or "anthropic").strip().lower()
    key_field, model_field, base_url_field = _AI_PROVIDER_FIELD_MAP.get(
        provider, _AI_PROVIDER_FIELD_MAP["anthropic"]
    )
    api_key = getattr(cfg, key_field, "").strip()
    if not api_key:
        env_var = _AI_PROVIDER_ENV_FALLBACK.get(provider)
        if env_var:
            api_key = os.environ.get(env_var, "").strip()
    model = getattr(cfg, model_field, "").strip()
    base_url = getattr(cfg, base_url_field, "").strip() if base_url_field else ""
    return ActiveAIProviderConfig(provider=provider, api_key=api_key, model=model, base_url=base_url)


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


# --- Safety cooldown (reduced limits right after an account is resumed) -----
# See human_bot/safety_cooldown_config.py's docstring for the "why" (a real
# external report of accounts getting re-flagged after resuming full-speed
# too soon post-restriction).

def get_safety_cooldown_overrides() -> dict[str, Any]:
    return _get_overrides("safety_cooldown", EDITABLE_SAFETY_COOLDOWN_FIELDS)


def get_safety_cooldown_config() -> SafetyCooldownConfig:
    return _get_config(SafetyCooldownConfig, "safety_cooldown", EDITABLE_SAFETY_COOLDOWN_FIELDS)


def save_safety_cooldown_overrides(values: dict[str, Any]) -> None:
    _save_overrides("safety_cooldown", EDITABLE_SAFETY_COOLDOWN_FIELDS, values)


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


def _pause_status(entry: Any) -> str | None:
    """Each account_status entry is either the legacy bare string "paused"
    (accounts paused before 2026-09-07) or a dict {"status", "reason",
    "paused_at"} (added so /admin/accounts can show *why* and *when* an
    account got paused — a project-owner request after a real Facebook
    checkpoint incident, so a human deciding when it's safe to resume has
    actual information instead of a blind guess). Both forms are read
    transparently; a legacy string is never rewritten in place, only
    replaced the next time set_account_paused() runs for that account."""
    if isinstance(entry, str):
        return entry
    if isinstance(entry, dict):
        return entry.get("status")
    return None


def get_paused_account_ids() -> set[str]:
    data = _read_all()
    raw = data.get(_ACCOUNT_STATUS_KEY, {})
    if not isinstance(raw, dict):
        return set()
    return {aid for aid, entry in raw.items() if _pause_status(entry) == "paused"}


def get_pause_info(account_id: str) -> dict[str, Any] | None:
    """Returns {"reason": str|None, "paused_at": iso-str|None} if the
    account is currently paused, else None. Shown at /admin/accounts so a
    human can judge when it's actually safe to resume, instead of just
    seeing a bare "⏸ Tạm dừng" badge with no context — see
    docs/skills/anomaly-detection.md."""
    data = _read_all()
    raw = data.get(_ACCOUNT_STATUS_KEY, {})
    if not isinstance(raw, dict):
        return None
    entry = raw.get(account_id)
    if _pause_status(entry) != "paused":
        return None
    if isinstance(entry, dict):
        return {"reason": entry.get("reason"), "paused_at": entry.get("paused_at")}
    return {"reason": None, "paused_at": None}  # legacy bare-string entry


def set_account_paused(account_id: str, paused: bool, reason: str | None = None) -> None:
    data = _read_all()
    raw = data.get(_ACCOUNT_STATUS_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    if paused:
        raw[account_id] = {
            "status": "paused",
            "reason": reason,
            "paused_at": datetime.now(timezone.utc).isoformat(),
        }
    else:
        raw.pop(account_id, None)
    data[_ACCOUNT_STATUS_KEY] = raw
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def resume_account(account_id: str) -> None:
    """What /admin/accounts' "▶ Kích hoạt lại" button actually calls —
    clears the pause AND starts a reduced-rate-limit cooldown period (see
    human_bot/safety_cooldown_config.py) instead of jumping straight back
    to full speed. Captures the pause's reason/paused_at (if any) before
    clearing it, so the cooldown record still has that context even after
    the account_status entry itself is gone."""
    info = get_pause_info(account_id) or {"reason": None, "paused_at": None}
    set_account_paused(account_id, False)
    _start_resume_cooldown(account_id, reason=info["reason"], paused_at=info["paused_at"])


# --- Account removal (applies to ANY account, including code-level ones) ---
#
# A runtime-registered account can just be dropped from _ACCOUNTS_KEY
# (delete_registered_account, above) — but a code-level ACCOUNTS entry in
# human_bot/config.py can't actually be removed from a running process,
# and the project owner asked for "Xoá" to work on EVERY account, not
# only ones added through /admin/accounts. This list is the same kind of
# override as account_status above: get_all_accounts() drops any id
# found here from its result entirely, regardless of where the
# AccountConfig itself came from.
#
# Undo path: register the same account_id again at /admin/accounts. As of
# 2026-09-07, human_bot/admin.py's accounts_delete() also actively wipes
# that account's joined_groups, rate_limits override, and resume_cooldown
# record (via save_joined_groups([]), save_rate_limits_overrides({}), and
# clear_resume_cooldown() below) SO THAT a later re-registration starts
# clean instead of silently inheriting whatever was left over from before
# the delete — a real bug found and fixed that day (a still-running
# resume_cooldown, in particular, could reach back and overwrite a freshly
# re-registered account's rate limits once its `until` naturally passed).
# Only accounts/<id>/storage_state.json (the real Facebook login session),
# action_log.jsonl/the action_log DB table, and screenshots/<id>/ survive
# a delete untouched — deliberately, since those are either real login
# data or historical records worth keeping.

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


# --- Per-account age tier ----------------------------------------------------
#
# Which human_bot/config.py ACCOUNT_AGE_TIERS key this account is currently
# assigned to — set at registration (the "Tuổi tài khoản Facebook" dropdown
# in /admin/accounts' add-account modal) or later via the rate-limits
# modal's quick-apply tier buttons (human_bot/admin.py). Deliberately a
# SEPARATE, stable field from the account's actual rate_limits override
# below, never inferred from it — see the "Post-resume cooldown" section
# further down for exactly why that distinction matters: it's what makes
# a post-resume cooldown safe to restart any number of times without ever
# losing track of "which tier does this account really belong to".
#
# An account custom-edited by hand in the rate-limits modal (not via a
# tier button) keeps whatever age tier it last had — typing numbers that
# happen not to match any tier doesn't erase "which tier this account is
# nominally at" for cooldown purposes, it only changes what its NORMAL
# (non-cooldown) rate limits are.
_ACCOUNT_AGE_TIER_KEY = "account_age_tier"
DEFAULT_ACCOUNT_AGE_TIER = "under_1_month"


def get_account_age_tier(account_id: str) -> str:
    """Always a valid human_bot/config.py ACCOUNT_AGE_TIERS key — falls
    back to DEFAULT_ACCOUNT_AGE_TIER (the safest/lowest tier, per owner
    decision 2026-09-15) for an account that's never had one explicitly
    set, or if the stored value is somehow no longer a real tier key
    (e.g. ACCOUNT_AGE_TIERS itself changed since it was saved)."""
    data = _read_all()
    raw = data.get(_ACCOUNT_AGE_TIER_KEY, {})
    if not isinstance(raw, dict):
        return DEFAULT_ACCOUNT_AGE_TIER
    tier = raw.get(account_id)
    return tier if tier in ACCOUNT_AGE_TIERS else DEFAULT_ACCOUNT_AGE_TIER


def set_account_age_tier(account_id: str, tier_key: str) -> None:
    if tier_key not in ACCOUNT_AGE_TIERS:
        return
    data = _read_all()
    raw = data.get(_ACCOUNT_AGE_TIER_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    raw[account_id] = tier_key
    data[_ACCOUNT_AGE_TIER_KEY] = raw
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


def clear_account_age_tier(account_id: str) -> None:
    """Used by /admin/accounts' "Xoá" (accounts_delete()) — same "leave
    nothing for a future re-registration to silently inherit" reasoning
    as clear_resume_cooldown()/save_rate_limits_overrides(account_id, {})
    right there."""
    data = _read_all()
    raw = data.get(_ACCOUNT_AGE_TIER_KEY, {})
    if not isinstance(raw, dict) or account_id not in raw:
        return
    raw.pop(account_id, None)
    data[_ACCOUNT_AGE_TIER_KEY] = raw
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
    "post_min_delay_seconds",
    "post_max_delay_seconds",
    "comment_min_delay_seconds",
    "comment_max_delay_seconds",
    "max_groups_per_post",
]


def get_rate_limits_overrides(account_id: str) -> dict[str, Any]:
    # No cooldown-expiry check here anymore (2026-09-15 rewrite) — a
    # post-resume cooldown no longer ever reads or writes this section at
    # all (see the "Post-resume cooldown" block below for why); it's
    # purely the admin's own manually-set override, untouched by
    # anything cooldown-related in either direction.
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


# --- Post-resume cooldown (reduced rate limits right after "Kích hoạt lại") -
#
# See human_bot/safety_cooldown_config.py for the "why" and the 2-week
# floor/step-up shape. human_bot/config.py's get_all_accounts() is the
# only reader that matters — it calls get_active_cooldown_rate_limits()
# below and layers the result OVER get_rate_limits_overrides(), last, so
# human_bot/safety.py's RateLimiter (which just reads `account.
# rate_limits`) picks up whichever is currently in effect with no
# separate call site to remember. Not itself an EDITABLE_*_FIELDS-style
# admin section — this key just records state (which tier, since when),
# the *policy* (cooldown_days, the floor numbers) lives in
# SafetyCooldownConfig / "safety_cooldown" instead, and the step-up
# mapping lives in human_bot/config.py's COOLDOWN_WEEK2_STEP_UP_TIER.
#
# Rewritten 2026-09-15 after a real, confirmed bug: the previous design
# stored a "prior_overrides" snapshot — whatever get_rate_limits_
# overrides() returned AT THE MOMENT resume_account() ran — to restore
# once the cooldown ended. That snapshot is only correct if the account
# was NOT already mid-cooldown at that exact moment. Sequence that broke
# it, reproduced live with an isolated runtime_config.json (never the
# real one): pause → resume (cooldown #1 correctly snapshots the TRUE
# original limits, e.g. 30/9/35/20) → paused AGAIN before cooldown #1's
# `until` passed → resume AGAIN — cooldown #2's snapshot reads the
# CURRENTLY-ACTIVE reduced numbers (1/1/2/2, cooldown #1 hadn't expired
# yet), overwriting the true original forever; every later expiry then
# just restored the account back to 1/1/2/2 in a loop, permanently, even
# though `resume_cooldown`'s own `until` field kept showing a real,
# correctly-computed future end date the whole time — a real project
# account (tu_iizuki) was found stuck exactly like this.
#
# Root fix: never snapshot/restore a `rate_limits` value at all anymore.
# The account's real override is simply never touched during the whole
# cooldown — get_active_cooldown_rate_limits() computes the floor/step-up
# numbers fresh every time from (base_tier, started_at, now) and
# get_all_accounts() only ever layers them OVER the stored override in
# memory, never writing them INTO it. So a repeat pause/resume mid-
# cooldown is trivially safe now: it just resets `started_at` to now
# (see resume_account() below) — there is no snapshot left to corrupt,
# and once cooldown_days elapses the account's own real override
# reappears exactly as it always was, with zero special-case "restore"
# step needed.
_RESUME_COOLDOWN_KEY = "resume_cooldown"


def _live_cooldown_entry(account_id: str) -> tuple[dict[str, Any], float] | None:
    """(entry, elapsed_days) for account_id's resume_cooldown record if
    it's still within SafetyCooldownConfig.cooldown_days of its
    `started_at` — expires (drops) the record first if that's already
    passed, or if `started_at` is missing/unparseable (defensive: never
    get an account stuck in cooldown forever over a malformed
    timestamp). Returns None in every case where there's nothing live —
    caller doesn't need to distinguish "never had one" from "just
    expired".

    Also the single place that checks SafetyCooldownConfig.enabled
    (2026-09-15 fix — was only checked in get_active_cooldown_rate_
    limits(), not here, so toggling it off mid-cooldown left
    get_resume_cooldown_info() still showing a "🧊 Đang hạ nhiệt" banner
    for an account that was, per the other function, already back to
    full speed — inconsistent). Disabled means "treat as if there is no
    active cooldown" for BOTH callers, but deliberately does NOT expire
    or touch the stored record — a still-valid, merely dormant record
    picks back up exactly where it was if re-enabled later, rather than
    losing progress or getting silently deleted while the feature
    happens to be off."""
    cfg = get_safety_cooldown_config()
    if not cfg.enabled:
        return None
    data = _read_all()
    raw = data.get(_RESUME_COOLDOWN_KEY, {})
    if not isinstance(raw, dict):
        return None
    entry = raw.get(account_id)
    if not isinstance(entry, dict):
        return None
    started = None
    try:
        started = datetime.fromisoformat(entry.get("started_at", ""))
    except (TypeError, ValueError):
        pass
    if started is not None and started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    elapsed_days = (
        (datetime.now(timezone.utc) - started).total_seconds() / 86400
        if started is not None else None
    )
    if started is None or elapsed_days >= cfg.cooldown_days:
        raw.pop(account_id, None)
        data[_RESUME_COOLDOWN_KEY] = raw
        RUNTIME_CONFIG_PATH.write_text(
            json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
        )
        return None
    return entry, elapsed_days


def get_active_cooldown_rate_limits(account_id: str) -> RateLimits | None:
    """The floor (week 1, or the whole cooldown for "under_1_month" —
    see COOLDOWN_WEEK2_STEP_UP_TIER) or step-up (week 2, other tiers)
    RateLimits currently in effect for account_id's cooldown, or None if
    it has none / cooldown is disabled / the stored tier is somehow
    invalid (defensive fallback to "under_1_month", the safest tier,
    rather than crashing get_all_accounts() over a corrupted value).
    Computed fresh every call — never reads or writes the account's real
    rate_limits override (see this section's module comment for why).
    The enabled check lives in _live_cooldown_entry() (shared with
    get_resume_cooldown_info()), not duplicated here."""
    live = _live_cooldown_entry(account_id)
    if live is None:
        return None
    cfg = get_safety_cooldown_config()
    entry, elapsed_days = live
    base_tier = entry.get("base_tier")
    if base_tier not in ACCOUNT_AGE_TIERS:
        base_tier = DEFAULT_ACCOUNT_AGE_TIER
    half = cfg.cooldown_days / 2
    if elapsed_days < half:
        step_up_tier = None
    else:
        step_up_tier = COOLDOWN_WEEK2_STEP_UP_TIER.get(base_tier)
    if step_up_tier is None:
        return RateLimits(
            posts_per_day=cfg.posts_per_day,
            comments_per_hour=cfg.comments_per_hour,
            comments_per_day=cfg.comments_per_day,
            likes_per_hour=cfg.likes_per_hour,
            post_min_delay_seconds=cfg.min_delay_seconds,
            post_max_delay_seconds=cfg.max_delay_seconds,
            comment_min_delay_seconds=cfg.min_delay_seconds,
            comment_max_delay_seconds=cfg.max_delay_seconds,
        )
    _label, preset = ACCOUNT_AGE_TIERS[step_up_tier]
    return preset


def get_resume_cooldown_info(account_id: str) -> dict[str, Any] | None:
    """For /admin/accounts to show "🧊 Đang hạ nhiệt tới <ngày> (tuần
    1/2), vì: <lý do>" — None if the account has no active cooldown
    (never paused, or the cooldown already finished)."""
    live = _live_cooldown_entry(account_id)
    if live is None:
        return None
    entry, elapsed_days = live
    cfg = get_safety_cooldown_config()
    started = datetime.fromisoformat(entry["started_at"])
    if started.tzinfo is None:
        started = started.replace(tzinfo=timezone.utc)
    return {
        "until": (started + timedelta(days=cfg.cooldown_days)).isoformat(),
        "week": 1 if elapsed_days < cfg.cooldown_days / 2 else 2,
        "base_tier": entry.get("base_tier"),
        "reason": entry.get("reason"),
        "paused_at": entry.get("paused_at"),
    }


def _start_resume_cooldown(account_id: str, reason: str | None, paused_at: str | None) -> None:
    """Always (re)starts the cooldown clock at `now`, unconditionally —
    including when one is ALREADY active for this account (a pause
    followed by another resume before the first cooldown finished): per
    owner decision 2026-09-15, that's treated as a brand new cooldown,
    not a continuation, since it's simplest to reason about and safest
    (another round of "prove it's behaving normally" can't hurt). Safe
    to do because `base_tier` always comes from get_account_age_tier() —
    a stable, separately-set field (see that function's docstring) —
    never from the account's current (possibly cooldown-reduced) rate
    limits, which is exactly what made the old design corruptible."""
    cfg = get_safety_cooldown_config()
    if not cfg.enabled:
        return
    data = _read_all()
    raw = data.get(_RESUME_COOLDOWN_KEY, {})
    if not isinstance(raw, dict):
        raw = {}
    raw[account_id] = {
        "base_tier": get_account_age_tier(account_id),
        "started_at": datetime.now(timezone.utc).isoformat(),
        "reason": reason,
        "paused_at": paused_at,
    }
    data[_RESUME_COOLDOWN_KEY] = raw
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- Per-account data-sync opt-out (side-B poller only) ---------------------
#
# DataSyncConfig.enabled (above) is a global on/off switch for the whole
# poller — it can't exclude a single account while leaving the rest synced.
# Account status (ACTIVE/PAUSED) can't do it either: PAUSED blocks EVERY
# action for that account (agent.py's run_task() rejects any status !=
# ACTIVE), not just the side-B sync. This override sits between the two —
# an ACTIVE account listed here still posts/comments normally via
# /admin/post or the /tasks API, it's just skipped by
# human_bot/service.py's _data_sync_poll_loop(). A PAUSED account is never
# synced regardless of this list (see get_all_accounts()'s status check,
# which already keeps a paused account out of _data_sync_poll_loop's
# active_accounts filter) — so this only ever *adds* an exclusion on top
# of, never overrides, the PAUSED gate.

_SYNC_DISABLED_ACCOUNTS_KEY = "sync_disabled_accounts"


def get_sync_disabled_account_ids() -> set[str]:
    data = _read_all()
    raw = data.get(_SYNC_DISABLED_ACCOUNTS_KEY, [])
    if not isinstance(raw, list):
        return set()
    return {str(aid) for aid in raw if str(aid).strip()}


def set_account_sync_enabled(account_id: str, enabled: bool) -> None:
    ids = get_sync_disabled_account_ids()
    if enabled:
        ids.discard(account_id)
    else:
        ids.add(account_id)
    data = _read_all()
    data[_SYNC_DISABLED_ACCOUNTS_KEY] = sorted(ids)
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )


# --- Per-account "sponsored-only" (side-B poller only) ----------------------
#
# 2026-09-16, owner request: sponsored_by jobs must always be scheduled
# ahead of ordinary jobs but must never exceed posts_per_day (see
# data_sync.py's sync_all()) — so a job that arrives late in the day,
# after ordinary jobs already claimed that day's whole quota on every
# account, would still get bumped to tomorrow. Marking an account
# sponsored-only means data_sync.py's sync_all() never assigns it an
# ordinary job (any day, not just today — see its second
# _water_fill_distribute() call), so that account's quota stays free to
# react immediately whenever a sponsored job actually shows up. Same
# bare-id-list pattern as _SYNC_DISABLED_ACCOUNTS_KEY above — this is
# also layered onto AccountConfig.sponsored_only in
# human_bot/config.py's get_all_accounts(), unlike the sync-disable list,
# since data_sync.py's own code needs to read it as a plain
# account.sponsored_only attribute, not call back into this module.

_SPONSORED_ONLY_ACCOUNTS_KEY = "sponsored_only_accounts"


def get_sponsored_only_account_ids() -> set[str]:
    data = _read_all()
    raw = data.get(_SPONSORED_ONLY_ACCOUNTS_KEY, [])
    if not isinstance(raw, list):
        return set()
    return {str(aid) for aid in raw if str(aid).strip()}


def set_account_sponsored_only(account_id: str, sponsored_only: bool) -> None:
    ids = get_sponsored_only_account_ids()
    if sponsored_only:
        ids.add(account_id)
    else:
        ids.discard(account_id)
    data = _read_all()
    data[_SPONSORED_ONLY_ACCOUNTS_KEY] = sorted(ids)
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
    notify_config_changed()


def get_all_active_cooldown_account_ids() -> list[str]:
    """Every account_id with a resume_cooldown record on disk right now
    — used only by human_bot/service.py's daily maintenance loop to know
    whether there's any work to do at all (see that loop's docstring),
    and which accounts to nudge via get_active_cooldown_rate_limits()
    (which does the real, lazy expiry check). Does NOT itself check
    whether each entry is still live vs already past cooldown_days —
    intentionally cheap, just a raw key listing."""
    data = _read_all()
    raw = data.get(_RESUME_COOLDOWN_KEY, {})
    return list(raw.keys()) if isinstance(raw, dict) else []


def clear_resume_cooldown(account_id: str) -> None:
    """Drops account_id's resume_cooldown record outright. Used by
    /admin/accounts' "Xoá" (human_bot/admin.py's accounts_delete()):
    without this, a cooldown still running at delete time would keep
    sitting in runtime_config.json and could confuse a later
    re-registration of the same account_id (e.g. get_resume_cooldown_info()
    showing a stale "đang hạ nhiệt" banner for an account that, as far as
    the fresh registration is concerned, was never paused). Since 2026-09-15
    this section no longer reads or writes rate_limits at all (see this
    module's "Post-resume cooldown" comment), so — unlike before that
    rewrite — dropping this record can no longer reach back and corrupt a
    future re-registration's rate limits; this is purely about not
    showing a stale cooldown banner."""
    data = _read_all()
    raw = data.get(_RESUME_COOLDOWN_KEY, {})
    if not isinstance(raw, dict) or account_id not in raw:
        return
    raw.pop(account_id, None)
    data[_RESUME_COOLDOWN_KEY] = raw
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )

