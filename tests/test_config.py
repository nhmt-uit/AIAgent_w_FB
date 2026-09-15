from __future__ import annotations

from human_bot import config, runtime_config as rc


# --- get_all_accounts() layering an active post-resume cooldown over the
# account's real rate_limits override (2026-09-15 rewrite) ------------------
#
# Uses the real code-level "tu_iizuki" account (human_bot.config.ACCOUNTS)
# rather than a fake one — get_all_accounts() only ever adds runtime
# overrides on top of whatever's in ACCOUNTS/registered accounts, so this
# is exactly the integration point human_bot/safety.py's RateLimiter
# actually reads from in production.

def test_get_all_accounts_applies_cooldown_floor_over_real_override(isolated_runtime_config):
    rc.save_rate_limits_overrides("tu_iizuki", {"posts_per_day": 30, "comments_per_day": 35})
    rc.set_account_paused("tu_iizuki", True, reason="test")
    rc.resume_account("tu_iizuki")

    cfg = rc.get_safety_cooldown_config()
    accounts = config.get_all_accounts()
    assert accounts["tu_iizuki"].rate_limits.posts_per_day == cfg.posts_per_day
    assert accounts["tu_iizuki"].rate_limits.comments_per_day == cfg.comments_per_day

    # The real override underneath must be completely unaffected by having
    # been shadowed — this is the whole point of the 2026-09-15 rewrite.
    assert rc.get_rate_limits_overrides("tu_iizuki") == {"posts_per_day": 30, "comments_per_day": 35}


def test_get_all_accounts_reflects_real_override_once_cooldown_finishes(isolated_runtime_config):
    from datetime import datetime, timedelta, timezone
    import json

    rc.save_rate_limits_overrides("tu_iizuki", {"posts_per_day": 30, "comments_per_day": 35})
    rc.set_account_paused("tu_iizuki", True, reason="test")
    rc.resume_account("tu_iizuki")

    # Backdate past the full cooldown_days.
    data = json.loads(isolated_runtime_config.read_text())
    started = datetime.now(timezone.utc) - timedelta(days=15)
    data["resume_cooldown"]["tu_iizuki"]["started_at"] = started.isoformat()
    isolated_runtime_config.write_text(json.dumps(data))

    accounts = config.get_all_accounts()
    assert accounts["tu_iizuki"].rate_limits.posts_per_day == 30
    assert accounts["tu_iizuki"].rate_limits.comments_per_day == 35


def test_get_all_accounts_max_groups_per_post_survives_cooldown(isolated_runtime_config):
    """Cooldown/tier presets never define max_groups_per_post — it must
    keep whatever the account already had, not get reset to some cooldown
    default (there isn't one)."""
    rc.save_rate_limits_overrides("tu_iizuki", {"max_groups_per_post": 2})
    rc.set_account_paused("tu_iizuki", True, reason="test")
    rc.resume_account("tu_iizuki")

    accounts = config.get_all_accounts()
    assert accounts["tu_iizuki"].rate_limits.max_groups_per_post == 2
