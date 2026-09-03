"""
Account configuration and status store for human_bot.

See docs/skills/session-persistence.md and docs/skills/rate-limiting-pacing.md
for the reasoning behind these defaults.
"""
from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from pathlib import Path

ACCOUNTS_DIR = Path(__file__).resolve().parent.parent / "accounts"


class AccountStatus(str, Enum):
    ACTIVE = "active"
    PAUSED = "paused"  # set by the Safety Monitor — requires human review


@dataclass
class RateLimits:
    posts_per_day: int = 5
    comments_per_hour: int = 5
    comments_per_day: int = 20
    likes_per_hour: int = 15
    min_delay_seconds: int = 90
    max_delay_seconds: int = 400


@dataclass
class AccountConfig:
    account_id: str
    display_name: str
    status: AccountStatus = AccountStatus.ACTIVE
    rate_limits: RateLimits = field(default_factory=RateLimits)

    @property
    def storage_state_path(self) -> Path:
        return ACCOUNTS_DIR / self.account_id / "storage_state.json"

    @property
    def action_log_path(self) -> Path:
        return ACCOUNTS_DIR / self.account_id / "action_log.jsonl"


# TODO: replace this in-memory dict with a real store (DB or JSON file) once
# more than one or two accounts are in play. Kept simple here on purpose —
# see README.md "Next steps".
ACCOUNTS: dict[str, AccountConfig] = {
    "tu_iizuki": AccountConfig(account_id="tu_iizuki", display_name="Tu (iizuki test)"),
    # "example_page": AccountConfig(account_id="example_page", display_name="Example Page"),
}


def get_account(account_id: str) -> AccountConfig:
    if account_id not in ACCOUNTS:
        raise ValueError(f"Unknown account_id: {account_id!r}. Register it in human_bot/config.py")
    return ACCOUNTS[account_id]
