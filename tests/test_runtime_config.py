from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

from human_bot import runtime_config as rc
from human_bot.config import ACCOUNT_AGE_TIERS


# --- _get_config / _get_overrides / _save_overrides round-trip -------------

def test_get_human_typing_config_defaults_when_no_file(isolated_runtime_config):
    assert not isolated_runtime_config.exists()
    cfg = rc.get_human_typing_config()
    from human_bot.humanize import HumanTypingConfig
    assert cfg == HumanTypingConfig()


def test_save_overrides_then_get_config_reflects_partial_change(isolated_runtime_config):
    rc.save_human_typing_overrides({"wpm": 999})
    cfg = rc.get_human_typing_config()
    assert cfg.wpm == 999
    # Untouched fields stay at their code default.
    from human_bot.humanize import HumanTypingConfig
    assert cfg.typo_probability == HumanTypingConfig().typo_probability


def test_save_overrides_drops_non_editable_field(isolated_runtime_config):
    rc.save_human_typing_overrides({"wpm": 42, "totally_made_up_field": "x"})
    stored = json.loads(isolated_runtime_config.read_text())
    assert "totally_made_up_field" not in stored["human_typing"]
    assert stored["human_typing"]["wpm"] == 42


def test_save_overrides_replaces_whole_section_not_merges(isolated_runtime_config):
    """_save_overrides() docstring: only known editable fields in the new
    `values` are kept for that section — a second save with a different
    single field does not keep the first save's field around."""
    rc.save_human_typing_overrides({"wpm": 42})
    rc.save_human_typing_overrides({"typo_probability": 0.5})
    stored = json.loads(isolated_runtime_config.read_text())
    assert "wpm" not in stored["human_typing"]
    assert stored["human_typing"]["typo_probability"] == 0.5


def test_corrupt_json_file_falls_back_to_defaults(isolated_runtime_config):
    isolated_runtime_config.write_text("{not valid json")
    cfg = rc.get_human_typing_config()
    from human_bot.humanize import HumanTypingConfig
    assert cfg == HumanTypingConfig()


def test_non_dict_json_file_falls_back_to_defaults(isolated_runtime_config):
    isolated_runtime_config.write_text("[1, 2, 3]")
    assert rc._read_all() == {}


# --- max_overflow_business_days (data_sync) ---------------------------------

def test_data_sync_config_defaults_max_overflow_business_days_to_2(isolated_runtime_config):
    from human_bot.data_sync_config import DataSyncConfig
    assert DataSyncConfig().max_overflow_business_days == 2


def test_save_data_sync_overrides_roundtrips_max_overflow_business_days(isolated_runtime_config):
    rc.save_data_sync_overrides({"max_overflow_business_days": 5})
    cfg = rc.get_data_sync_config()
    assert cfg.max_overflow_business_days == 5


# --- Per-account sponsored_only (side-B poller priority) --------------------

def test_get_sponsored_only_account_ids_defaults_empty(isolated_runtime_config):
    assert rc.get_sponsored_only_account_ids() == set()


def test_set_account_sponsored_only_roundtrip(isolated_runtime_config):
    rc.set_account_sponsored_only("acc-a", True)
    assert rc.get_sponsored_only_account_ids() == {"acc-a"}
    rc.set_account_sponsored_only("acc-a", False)
    assert rc.get_sponsored_only_account_ids() == set()


def test_set_account_sponsored_only_does_not_affect_other_accounts(isolated_runtime_config):
    rc.set_account_sponsored_only("acc-a", True)
    rc.set_account_sponsored_only("acc-b", True)
    rc.set_account_sponsored_only("acc-a", False)
    assert rc.get_sponsored_only_account_ids() == {"acc-b"}


def test_get_all_accounts_layers_sponsored_only_flag(isolated_runtime_config, monkeypatch):
    from human_bot import config as cfg_mod
    monkeypatch.setitem(
        cfg_mod.ACCOUNTS, "acc-a",
        cfg_mod.AccountConfig(account_id="acc-a", display_name="A"),
    )
    rc.set_account_sponsored_only("acc-a", True)
    accounts = cfg_mod.get_all_accounts()
    assert accounts["acc-a"].sponsored_only is True


# --- Secrets / multi-provider AI config -------------------------------------

def test_get_secrets_config_defaults(isolated_runtime_config):
    cfg = rc.get_secrets_config()
    assert cfg.ai_provider == "anthropic"
    assert cfg.anthropic_api_key == ""
    assert cfg.openai_api_key == ""


def test_save_and_get_secrets_overrides_roundtrip(isolated_runtime_config):
    rc.save_secrets_overrides({"ai_provider": "openai", "openai_api_key": "sk-test", "openai_model": "gpt-4o-mini"})
    cfg = rc.get_secrets_config()
    assert cfg.ai_provider == "openai"
    assert cfg.openai_api_key == "sk-test"
    assert cfg.openai_model == "gpt-4o-mini"
    # Anthropic fields untouched by this save.
    assert cfg.anthropic_api_key == ""


def test_active_ai_provider_config_uses_admin_override_over_env(isolated_runtime_config, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    rc.save_secrets_overrides({"ai_provider": "anthropic", "anthropic_api_key": "admin-key"})
    active = rc.get_active_ai_provider_config()
    assert active.provider == "anthropic"
    assert active.api_key == "admin-key"


def test_active_ai_provider_config_falls_back_to_env_when_no_override(isolated_runtime_config, monkeypatch):
    monkeypatch.setenv("ANTHROPIC_API_KEY", "env-key")
    rc.save_secrets_overrides({"ai_provider": "anthropic"})
    active = rc.get_active_ai_provider_config()
    assert active.api_key == "env-key"


def test_active_ai_provider_config_openai_env_fallback(isolated_runtime_config, monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "env-openai-key")
    rc.save_secrets_overrides({"ai_provider": "openai"})
    active = rc.get_active_ai_provider_config()
    assert active.provider == "openai"
    assert active.api_key == "env-openai-key"


def test_active_ai_provider_config_gemini_has_no_env_fallback(isolated_runtime_config, monkeypatch):
    # An unrelated ANTHROPIC_API_KEY being set must not leak into gemini's key.
    monkeypatch.setenv("ANTHROPIC_API_KEY", "should-not-be-used")
    rc.save_secrets_overrides({"ai_provider": "gemini"})
    active = rc.get_active_ai_provider_config()
    assert active.provider == "gemini"
    assert active.api_key == ""


def test_active_ai_provider_config_custom_includes_base_url(isolated_runtime_config):
    rc.save_secrets_overrides({
        "ai_provider": "custom",
        "custom_api_key": "ck",
        "custom_model": "deepseek-chat",
        "custom_base_url": "https://api.deepseek.com/v1",
    })
    active = rc.get_active_ai_provider_config()
    assert active.provider == "custom"
    assert active.api_key == "ck"
    assert active.model == "deepseek-chat"
    assert active.base_url == "https://api.deepseek.com/v1"


def test_active_ai_provider_config_unknown_provider_falls_back_to_anthropic_mapping(isolated_runtime_config):
    rc.save_secrets_overrides({"ai_provider": "not-a-real-provider", "anthropic_api_key": "fallback-key"})
    active = rc.get_active_ai_provider_config()
    assert active.provider == "not-a-real-provider"
    assert active.api_key == "fallback-key"


# --- Per-account age tier ----------------------------------------------------

def test_get_account_age_tier_defaults_to_under_1_month(isolated_runtime_config):
    assert rc.get_account_age_tier("acc1") == "under_1_month"
    assert rc.DEFAULT_ACCOUNT_AGE_TIER == "under_1_month"


def test_set_and_get_account_age_tier_roundtrip(isolated_runtime_config):
    rc.set_account_age_tier("acc1", "under_6_months")
    assert rc.get_account_age_tier("acc1") == "under_6_months"
    # A different account is unaffected.
    assert rc.get_account_age_tier("acc2") == "under_1_month"


def test_set_account_age_tier_rejects_invalid_key(isolated_runtime_config):
    rc.set_account_age_tier("acc1", "not_a_real_tier")
    assert rc.get_account_age_tier("acc1") == "under_1_month"


def test_clear_account_age_tier(isolated_runtime_config):
    rc.set_account_age_tier("acc1", "over_12_months")
    rc.clear_account_age_tier("acc1")
    assert rc.get_account_age_tier("acc1") == "under_1_month"


# --- Post-resume cooldown (2-week floor/step-up rewrite, 2026-09-15) --------

def _backdate_cooldown(path, account_id: str, days_ago: float) -> None:
    """Test-only helper: rewrites account_id's resume_cooldown
    `started_at` to simulate `days_ago` days having already passed,
    without needing to mock datetime.now() everywhere the cooldown code
    calls it."""
    data = json.loads(path.read_text())
    started = datetime.now(timezone.utc) - timedelta(days=days_ago)
    data["resume_cooldown"][account_id]["started_at"] = started.isoformat()
    path.write_text(json.dumps(data))


def test_resume_account_starts_week1_floor_cooldown(isolated_runtime_config):
    rc.set_account_paused("acc1", True, reason="test")
    rc.resume_account("acc1")

    cfg = rc.get_safety_cooldown_config()
    effective = rc.get_active_cooldown_rate_limits("acc1")
    assert effective is not None
    assert effective.posts_per_day == cfg.posts_per_day
    assert effective.comments_per_day == cfg.comments_per_day

    info = rc.get_resume_cooldown_info("acc1")
    assert info is not None
    assert info["week"] == 1


def test_cooldown_week2_steps_established_tier_up_one_notch(isolated_runtime_config):
    rc.set_account_age_tier("acc1", "under_12_months")
    rc.set_account_paused("acc1", True, reason="test")
    rc.resume_account("acc1")
    _backdate_cooldown(isolated_runtime_config, "acc1", days_ago=8)  # into week 2 of 14

    effective = rc.get_active_cooldown_rate_limits("acc1")
    _, expected = ACCOUNT_AGE_TIERS["under_3_months"]  # the configured step-up target
    assert effective == expected

    info = rc.get_resume_cooldown_info("acc1")
    assert info["week"] == 2


def test_cooldown_week2_stays_on_floor_for_newest_tier(isolated_runtime_config):
    rc.set_account_age_tier("acc1", "under_1_month")  # nothing lower to step up from
    rc.set_account_paused("acc1", True, reason="test")
    rc.resume_account("acc1")
    _backdate_cooldown(isolated_runtime_config, "acc1", days_ago=8)

    cfg = rc.get_safety_cooldown_config()
    effective = rc.get_active_cooldown_rate_limits("acc1")
    assert effective.posts_per_day == cfg.posts_per_day
    assert effective.comments_per_day == cfg.comments_per_day


def test_cooldown_expires_after_full_duration_leaving_real_override_untouched(isolated_runtime_config):
    # The account's REAL, admin-set limits — must survive the whole
    # cooldown untouched (2026-09-15 rewrite's whole point).
    rc.save_rate_limits_overrides("acc1", {"posts_per_day": 30, "comments_per_day": 35})
    rc.set_account_age_tier("acc1", "over_12_months")
    rc.set_account_paused("acc1", True, reason="test")
    rc.resume_account("acc1")
    _backdate_cooldown(isolated_runtime_config, "acc1", days_ago=15)  # past cooldown_days=14

    assert rc.get_active_cooldown_rate_limits("acc1") is None
    assert rc.get_resume_cooldown_info("acc1") is None
    # Never touched — restored automatically just by no longer shadowing it.
    assert rc.get_rate_limits_overrides("acc1") == {"posts_per_day": 30, "comments_per_day": 35}


def test_nested_pause_resume_mid_cooldown_does_not_corrupt_base_tier(isolated_runtime_config):
    """Regression test for the real bug found 2026-09-15 (see
    get_active_cooldown_rate_limits()'s module docstring in
    runtime_config.py): pausing and resuming a SECOND time while the
    first cooldown was still active used to re-snapshot the CURRENTLY
    reduced rate limits as "prior_overrides", permanently losing the
    account's true original settings. The rewrite has no snapshot to
    corrupt — base_tier always comes from the stable get_account_age_tier(),
    never from momentary rate_limits — so a second resume mid-cooldown
    must leave both the tier AND the real override exactly as they were."""
    rc.save_rate_limits_overrides("acc1", {"posts_per_day": 30, "comments_per_hour": 9, "comments_per_day": 35, "likes_per_hour": 20})
    rc.set_account_age_tier("acc1", "over_12_months")

    # 1st pause/resume — cooldown #1 starts.
    rc.set_account_paused("acc1", True, reason="first pause")
    rc.resume_account("acc1")
    assert rc.get_resume_cooldown_info("acc1")["week"] == 1

    # 2nd pause/resume WHILE cooldown #1 is still active (not expired).
    rc.set_account_paused("acc1", True, reason="second pause")
    rc.resume_account("acc1")

    # The tier used for phasing must be unaffected by having been
    # resumed while already reduced.
    info = rc.get_resume_cooldown_info("acc1")
    assert info is not None
    assert info["base_tier"] == "over_12_months"

    # And, crucially, the true original override must still be intact —
    # this is what silently became {1,1,2,2} forever under the old bug.
    assert rc.get_rate_limits_overrides("acc1") == {
        "posts_per_day": 30, "comments_per_hour": 9, "comments_per_day": 35, "likes_per_hour": 20,
    }

    # And once THIS cooldown finishes too, the real override reappears.
    _backdate_cooldown(isolated_runtime_config, "acc1", days_ago=15)
    assert rc.get_active_cooldown_rate_limits("acc1") is None
    assert rc.get_rate_limits_overrides("acc1") == {
        "posts_per_day": 30, "comments_per_hour": 9, "comments_per_day": 35, "likes_per_hour": 20,
    }


def test_get_rate_limits_overrides_never_touches_cooldown(isolated_runtime_config):
    """2026-09-15 rewrite: reading the raw override must be a pure read
    now — no more lazy expire-and-restore side effect baked into it."""
    rc.save_rate_limits_overrides("acc1", {"posts_per_day": 10})
    rc.set_account_paused("acc1", True, reason="test")
    rc.resume_account("acc1")
    # Reading the raw override mid-cooldown must return the UNCHANGED
    # stored value, not the cooldown-reduced numbers and not None.
    assert rc.get_rate_limits_overrides("acc1") == {"posts_per_day": 10}
    assert rc.get_resume_cooldown_info("acc1") is not None  # cooldown itself untouched by the read


def test_clear_resume_cooldown_drops_record_without_touching_override(isolated_runtime_config):
    rc.save_rate_limits_overrides("acc1", {"posts_per_day": 10})
    rc.set_account_paused("acc1", True, reason="test")
    rc.resume_account("acc1")
    rc.clear_resume_cooldown("acc1")
    assert rc.get_resume_cooldown_info("acc1") is None
    assert rc.get_active_cooldown_rate_limits("acc1") is None
    assert rc.get_rate_limits_overrides("acc1") == {"posts_per_day": 10}


def test_get_all_active_cooldown_account_ids(isolated_runtime_config):
    assert rc.get_all_active_cooldown_account_ids() == []
    rc.set_account_paused("acc1", True, reason="test")
    rc.resume_account("acc1")
    rc.set_account_paused("acc2", True, reason="test")
    rc.resume_account("acc2")
    assert sorted(rc.get_all_active_cooldown_account_ids()) == ["acc1", "acc2"]


def test_disabling_safety_cooldown_hides_the_info_banner_too(isolated_runtime_config):
    """Regression for a real inconsistency found in review (2026-09-15,
    same session as the rewrite): get_active_cooldown_rate_limits()
    checked cfg.enabled but get_resume_cooldown_info() did not, so
    toggling the feature off mid-cooldown left /admin/accounts still
    showing "🧊 Đang hạ nhiệt" for an account that, per the OTHER
    function, was already back to full speed. Both must agree."""
    rc.set_account_paused("acc1", True, reason="test")
    rc.resume_account("acc1")
    assert rc.get_active_cooldown_rate_limits("acc1") is not None
    assert rc.get_resume_cooldown_info("acc1") is not None

    import dataclasses
    # Read-merge-write, not a partial dict (a bare {"enabled": False}
    # would silently drop every other field via _save_overrides()'s
    # "replace the whole section" behavior — see the project's own
    # no-live-config-partial-writes convention).
    cfg = rc.get_safety_cooldown_config()
    rc.save_safety_cooldown_overrides({**dataclasses.asdict(cfg), "enabled": False})
    assert rc.get_active_cooldown_rate_limits("acc1") is None
    assert rc.get_resume_cooldown_info("acc1") is None

    # And the dormant record isn't destroyed by having been checked while
    # disabled — re-enabling picks it back up from the same started_at.
    rc.save_safety_cooldown_overrides({**dataclasses.asdict(cfg), "enabled": True})
    info = rc.get_resume_cooldown_info("acc1")
    assert info is not None
    assert info["week"] == 1
