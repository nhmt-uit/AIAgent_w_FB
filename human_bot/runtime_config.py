"""
Purpose of this file / Muc dich cua file nay:
EN: Central place for runtime-tunable settings that the /admin web UI can
edit without touching .env or restarting the service. Stored as JSON on
disk (runtime_config.json at the project root, gitignored — this is
machine-local tuning state, not a secret and not meant to be shared via
git). Precedence: a value present in the JSON file overrides the
.env/code default defined in human_bot/humanize.py's HumanTypingConfig;
any key absent from the JSON file still falls back to that default. See
docs/skills/human-like-interaction.md for what each field means.
VI: Noi tap trung cac thiet lap co the chinh qua giao dien web /admin ma
khong can sua file .env hay khoi dong lai service. Duoc luu duoi dang
JSON tren dia (runtime_config.json o thu muc goc du an, da duoc gitignore
— day la trang thai tuy chinh rieng cho tung may, khong phai bi mat va
khong can chia se qua git). Thu tu uu tien: gia tri co trong file JSON se
ghi de len gia tri mac dinh tu .env/code trong human_bot/humanize.py; key
nao thieu trong JSON thi van dung gia tri mac dinh do.
"""
import dataclasses
import json
from pathlib import Path
from typing import Any

from human_bot.humanize import HumanTypingConfig

RUNTIME_CONFIG_PATH = Path(__file__).resolve().parent.parent / "runtime_config.json"

# Fields a human operator is allowed to tune from the admin UI. An explicit
# allowlist (rather than "every dataclass field") means a future field
# added to HumanTypingConfig doesn't silently become admin-editable
# without a deliberate decision to add it here too.
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
    "fatigue_factor_per_char",
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


def get_human_typing_overrides() -> dict[str, Any]:
    """Raw override dict as currently saved (for pre-filling the admin form)."""
    data = _read_all()
    overrides = data.get("human_typing", {})
    return {k: v for k, v in overrides.items() if k in EDITABLE_HUMAN_TYPING_FIELDS}


def get_human_typing_config() -> HumanTypingConfig:
    """The config actually used when posting: .env/code defaults with any
    admin-saved JSON overrides layered on top. Call this instead of
    constructing HumanTypingConfig() directly in action functions."""
    base = HumanTypingConfig()
    overrides = get_human_typing_overrides()
    return dataclasses.replace(base, **overrides) if overrides else base


def save_human_typing_overrides(values: dict[str, Any]) -> None:
    """Persist admin-edited values. Only known editable fields are kept —
    anything else in `values` is silently dropped (defensive against a
    stray/unexpected form field)."""
    clean = {k: v for k, v in values.items() if k in EDITABLE_HUMAN_TYPING_FIELDS}
    data = _read_all()
    data["human_typing"] = clean
    RUNTIME_CONFIG_PATH.write_text(
        json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8"
    )
