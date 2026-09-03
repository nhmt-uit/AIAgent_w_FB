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
from pathlib import Path
from typing import Any

from human_bot.humanize import HumanMouseConfig, HumanPacingConfig, HumanTypingConfig

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
