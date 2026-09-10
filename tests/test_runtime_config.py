from __future__ import annotations

import json

from human_bot import runtime_config as rc


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
