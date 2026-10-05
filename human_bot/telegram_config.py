"""
Purpose of this file / Muc dich cua file nay:
EN: The ONE admin-editable field for Telegram alerts (human_bot/
telegram_notify.py) — a quick on/off switch at /admin/config, separate
from the bot token/chat_id themselves (those stay in .env, same as
DATA_INGESTION_API_TOKEN — a credential an operator sets up once, not
something edited often enough to need a UI). This lets the owner mute
every Telegram message without touching .env or restarting the service,
the same reason every other on/off toggle in this project
(DataSyncConfig.*_ai_enabled, MediaConfig.attach_random_meme_default)
lives in runtime_config.json instead of .env.
VI: Truong duy nhat co the chinh qua /admin/config cho bao dong Telegram
— bat/tat nhanh, rieng voi token/chat_id (van nam trong .env).
"""
from __future__ import annotations

from dataclasses import dataclass


@dataclass
class TelegramConfig:
    enabled: bool = True
