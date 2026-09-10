"""
Shared pytest fixtures. Nothing here (or in any test under tests/) may
touch real project state — runtime_config.json, accounts/, or
data_sync_cache/ — see feedback_no_live_config_test_writes: tests must be
isolated from the live runtime config, not exercised against it.
"""
from __future__ import annotations

import pytest

from human_bot import runtime_config


@pytest.fixture
def isolated_runtime_config(tmp_path, monkeypatch):
    """Redirects human_bot.runtime_config's on-disk JSON store to a throwaway
    file under tmp_path, so every get_*/save_*_overrides() call in a test
    reads/writes there instead of the real runtime_config.json."""
    fake_path = tmp_path / "runtime_config.json"
    monkeypatch.setattr(runtime_config, "RUNTIME_CONFIG_PATH", fake_path)
    return fake_path
