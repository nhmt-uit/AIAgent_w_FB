"""
Purpose of this file / Muc dich cua file nay:
EN: Holds the fields /admin/config is allowed to override outside of
.env — the AI provider selection + one API key/model (+ base URL for
"custom") per provider, used by content_strategist.py's AI job-post
drafting and candidate-reply rewriting (dispatched via human_bot/
ai_client.py). Empty string means "no override saved"; human_bot/
runtime_config.py's get_active_ai_provider_config() falls back to
ANTHROPIC_API_KEY/OPENAI_API_KEY env vars for those two providers, same
override-wins-when-set precedence every other runtime_config.py section
already uses (Gemini/custom have no established env var in this project,
so they're admin-UI-only).

Deliberately its own tiny config, not folded into DataSyncConfig or the
generic behavior-tuning fields in runtime_config.py's _CONFIG_SECTIONS
table — every field stored in runtime_config.json so far has been
non-secret tuning (typing speed, gap minutes...); this is the first
ACTUAL secret going into that file, requested 2026-09-10 so the key can
be set/rotated from /admin without touching .env or restarting the
service. runtime_config.json is already gitignored (never committed), so
this doesn't put the key at risk of a git leak — but the file now
genuinely contains sensitive content, not merely "machine-local tuning
state"; treat backups/copies of it accordingly.

Multi-provider support (Anthropic/OpenAI/Gemini/custom OpenAI-compatible
endpoint) added 2026-09-10 per explicit request — each provider gets its
own key/model fields (rather than one shared pair) so switching providers
on /admin/config never requires re-entering a key that was already saved
for a provider used previously.
VI: Cac truong /admin/config duoc phep ghi de ngoai .env — chon nha cung
cap AI + key/model tuong ung, dung cho content_strategist.py. Yeu cau
2026-09-10.
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class SecretsConfig:
    ai_provider: str = "anthropic"  # "anthropic" | "openai" | "gemini" | "custom"
    anthropic_api_key: str = ""
    anthropic_model: str = ""
    openai_api_key: str = ""
    openai_model: str = ""
    gemini_api_key: str = ""
    gemini_model: str = ""
    custom_api_key: str = ""
    custom_base_url: str = ""  # only used when ai_provider == "custom"
    custom_model: str = ""
