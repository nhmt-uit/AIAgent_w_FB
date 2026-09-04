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
class GroupRef:
    """A Facebook group this account is a member of — kept as name+url
    together (not url alone) so a human glancing at /admin/groups or this
    file can tell which group is which without opening the link."""
    name: str
    url: str


@dataclass
class RateLimits:
    posts_per_day: int = 20  # raised from 5, 2026-09-04, per project owner request
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
    # Groups this account is a member of, used by the side-B data-sync poller
    # (human_bot/data_sync.py) to broadcast job posts — see
    # docs/architecture.md section 3c ("post to ALL joined groups"). This is
    # only the code-level default; day-to-day editing happens at
    # /admin/groups, which overrides this via
    # human_bot/runtime_config.py's get_joined_groups()/save_joined_groups().
    # Prefer the numeric-id group URL form — see
    # docs/skills/group-targeting.md, "Numeric ID vs. custom (vanity) group
    # URL". Populate manually per account as groups are joined/pinned.
    joined_groups: list[GroupRef] = field(default_factory=list)

    @property
    def storage_state_path(self) -> Path:
        return ACCOUNTS_DIR / self.account_id / "storage_state.json"

    @property
    def action_log_path(self) -> Path:
        return ACCOUNTS_DIR / self.account_id / "action_log.jsonl"


# Code-level defaults — permanent accounts committed to the repo. An
# account added at runtime (after bootstrap_login.py) no longer needs an
# entry here: register it at /admin/accounts instead, which saves it via
# human_bot/runtime_config.py and get_all_accounts() below picks it up
# immediately, no restart needed. Still fine to add one here by hand if
# you want it committed as a permanent default.
ACCOUNTS: dict[str, AccountConfig] = {
    "tu_iizuki": AccountConfig(account_id="tu_iizuki", display_name="Tu (iizuki test)"),
    # "example_page": AccountConfig(account_id="example_page", display_name="Example Page"),
}


def get_all_accounts() -> dict[str, AccountConfig]:
    """ACCOUNTS (code defaults) plus any account registered from
    /admin/accounts — the merged set every caller should use instead of
    ACCOUNTS directly, so a newly registered account shows up without a
    code change or restart. Code-level entries win on id collision."""
    from human_bot.runtime_config import get_registered_accounts

    result = dict(ACCOUNTS)
    for entry in get_registered_accounts():
        if entry["account_id"] not in result:
            result[entry["account_id"]] = AccountConfig(
                account_id=entry["account_id"], display_name=entry["display_name"]
            )
    return result


def get_account(account_id: str) -> AccountConfig:
    accounts = get_all_accounts()
    if account_id not in accounts:
        raise ValueError(
            f"Unknown account_id: {account_id!r}. Register it at /admin/accounts "
            "or in human_bot/config.py"
        )
    return accounts[account_id]
