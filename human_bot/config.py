"""
Account configuration and status store for human_bot.

See docs/skills/session-persistence.md and docs/skills/rate-limiting-pacing.md
for the reasoning behind these defaults.
"""
from __future__ import annotations

import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field, replace
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
    file can tell which group is which without opening the link.

    `id` is a stable identifier, independent of the group's position in
    whatever list it's stored in — /admin/groups' edit/delete used to
    reference a group by its index in that list, which could point at the
    wrong group if the list changed (another tab, a concurrent edit)
    between rendering the page and submitting the form. Auto-generated so
    every existing call site that builds a GroupRef without one keeps
    working unchanged."""
    name: str
    url: str
    id: str = field(default_factory=lambda: uuid.uuid4().hex[:8])


def new_group_id(existing_ids: Iterable[str] = ()) -> str:
    """A GroupRef.id guaranteed not to collide with any of `existing_ids`.
    GroupRef's own default_factory above (bare `uuid.uuid4().hex[:8]`) is
    only *probabilistically* unique — 8 hex chars is 2**32 possible
    values, so a collision within one account's handful of groups is
    astronomically unlikely (~n²/2**33 by the birthday bound), but not
    impossible. Every call site that actually adds a group to an
    account's list (human_bot/admin.py's groups_add, and
    human_bot/runtime_config.py's get_joined_groups() migrating legacy
    entries with no id yet) uses this instead, to make it a hard
    guarantee rather than a probability, per the project owner's request."""
    existing = set(existing_ids)
    while True:
        candidate = uuid.uuid4().hex[:8]
        if candidate not in existing:
            return candidate


@dataclass
class RateLimits:
    # 22/day = the "trên 12 tháng" (established, 12+ months old) tier in
    # ACCOUNT_AGE_TIERS below — this class default IS that tier's preset,
    # so an account with no explicit tier/override picked defaults to the
    # most-established assumption. Was 20 (raised from 5, 2026-09-04); set
    # to 22 on 2026-09-07 to align with the age-tier table the project
    # owner defined that day — see ACCOUNT_AGE_TIERS.
    posts_per_day: int = 22
    comments_per_hour: int = 5
    comments_per_day: int = 20
    likes_per_hour: int = 15
    # Minimum gap enforced between ANY two consecutive actions on this
    # account (see human_bot/safety.py's RateLimiter._last_action_gap_ok()
    # — refuses a task outright rather than sleeping/blocking). Raised
    # from 90-400s (which, until 2026-09-07, was defined but never
    # actually enforced anywhere — see docs/skills/anomaly-detection.md's
    # git history) to 1-2 hours per the project owner's explicit request,
    # after cross-referencing external reports suggesting even 10-20
    # minutes between actions reads as automated to Facebook's abuse
    # systems.
    min_delay_seconds: int = 3600
    max_delay_seconds: int = 7200


# --- Account-age rate-limit presets -----------------------------------------
#
# The project owner gave posts_per_day numbers per account-age tier
# (2026-09-07, after noticing the test account "tu_iizuki" — under a week
# old at the time — was running under the same limits as a fully
# established account). Every other field here (comments_per_hour/day,
# likes_per_hour, min/max_delay_seconds) is derived from that posts/day
# number, scaled by the same ratios the RateLimits() class default already
# implies at its own tier (over_12_months: posts=22 -> comments_hour=5,
# comments_day=20, likes_hour=15 — i.e. over_12_months below is IDENTICAL
# to RateLimits(), by construction) — and min/max_delay_seconds widens for
# younger tiers instead (a newer/less-trusted account should space actions
# out MORE, not just post less often). Applied at /admin/accounts, both
# when registering a new account (a dropdown) and per-account afterward
# (a quick-apply button in the "⏱️ Giới hạn" modal, for when an account
# ages into the next tier) — see human_bot/admin.py.
ACCOUNT_AGE_TIERS: dict[str, tuple[str, RateLimits]] = {
    "under_1_month": ("Dưới 1 tháng", RateLimits(
        posts_per_day=5, comments_per_hour=1, comments_per_day=5, likes_per_hour=4,
        min_delay_seconds=10800, max_delay_seconds=21600,  # 3-6h
    )),
    "under_3_months": ("Dưới 3 tháng", RateLimits(
        posts_per_day=8, comments_per_hour=2, comments_per_day=7, likes_per_hour=6,
        min_delay_seconds=7200, max_delay_seconds=14400,  # 2-4h
    )),
    "under_6_months": ("Dưới 6 tháng", RateLimits(
        posts_per_day=11, comments_per_hour=3, comments_per_day=10, likes_per_hour=8,
        min_delay_seconds=5400, max_delay_seconds=10800,  # 1.5-3h
    )),
    "under_12_months": ("Dưới 12 tháng", RateLimits(
        posts_per_day=18, comments_per_hour=4, comments_per_day=16, likes_per_hour=12,
        min_delay_seconds=4500, max_delay_seconds=9000,  # 1.25-2.5h
    )),
    "over_12_months": ("Trên 12 tháng", RateLimits(
        posts_per_day=22, comments_per_hour=5, comments_per_day=20, likes_per_hour=15,
        min_delay_seconds=3600, max_delay_seconds=7200,  # 1-2h — same as RateLimits()
    )),
}


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
    code change or restart. Code-level entries win on id collision.

    Also layers runtime_config.json's paused-account overrides on top —
    applies to EVERY account regardless of origin, since pausing is a
    safety action (see human_bot/safety.py's AnomalyDetected /
    human_bot/runtime_config.py's set_account_paused), not something that
    should require a code edit. Same for removed accounts: /admin/accounts'
    "Xoá" works on a code-level ACCOUNTS entry too (via set_account_removed)
    even though the Python constant itself can't be deleted at runtime —
    it just never shows up here again until re-registered. Same again for
    per-account rate-limit overrides (get_rate_limits_overrides) — applied
    here so human_bot/safety.py's RateLimiter, which just reads
    `account.rate_limits` off whatever it's given, picks them up with no
    separate call site to remember."""
    from human_bot.runtime_config import (
        get_paused_account_ids,
        get_rate_limits_overrides,
        get_registered_accounts,
        get_removed_account_ids,
    )

    result = dict(ACCOUNTS)
    for entry in get_registered_accounts():
        if entry["account_id"] not in result:
            result[entry["account_id"]] = AccountConfig(
                account_id=entry["account_id"], display_name=entry["display_name"]
            )
    for aid in get_removed_account_ids():
        result.pop(aid, None)
    paused_ids = get_paused_account_ids()
    for aid in paused_ids:
        if aid in result and result[aid].status != AccountStatus.PAUSED:
            result[aid] = replace(result[aid], status=AccountStatus.PAUSED)
    for aid, account in list(result.items()):
        overrides = get_rate_limits_overrides(aid)
        if overrides:
            result[aid] = replace(account, rate_limits=replace(account.rate_limits, **overrides))
    return result


def get_account(account_id: str) -> AccountConfig:
    accounts = get_all_accounts()
    if account_id not in accounts:
        raise ValueError(
            f"Unknown account_id: {account_id!r}. Register it at /admin/accounts "
            "or in human_bot/config.py"
        )
    return accounts[account_id]
