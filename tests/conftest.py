"""
Shared pytest fixtures. Nothing here (or in any test under tests/) may
touch real project state — runtime_config.json, accounts/, or
data_sync_cache/ — see feedback_no_live_config_test_writes: tests must be
isolated from the live runtime config, not exercised against it.
"""
from __future__ import annotations

import pytest

from human_bot import runtime_config
from human_bot import schedule_store


@pytest.fixture
def isolated_runtime_config(tmp_path, monkeypatch):
    """Redirects human_bot.runtime_config's on-disk JSON store to a throwaway
    file under tmp_path, so every get_*/save_*_overrides() call in a test
    reads/writes there instead of the real runtime_config.json."""
    fake_path = tmp_path / "runtime_config.json"
    monkeypatch.setattr(runtime_config, "RUNTIME_CONFIG_PATH", fake_path)
    return fake_path


@pytest.fixture
def isolated_schedule_dirs(tmp_path, monkeypatch):
    """Redirects every schedule_store.py status directory (pending/posted/
    failed/cancelled/missed) to throwaway tmp_path subdirs. Moved here
    2026-09-25 from tests/test_admin.py (where it was first defined) so
    every test file touching schedule_store can share it, not just that
    one."""
    monkeypatch.setattr(schedule_store, "PENDING_DIR", tmp_path / "pending")
    monkeypatch.setattr(schedule_store, "POSTED_DIR", tmp_path / "posted")
    monkeypatch.setattr(schedule_store, "FAILED_DIR", tmp_path / "failed")
    monkeypatch.setattr(schedule_store, "CANCELLED_DIR", tmp_path / "cancelled")
    monkeypatch.setattr(schedule_store, "MISSED_DIR", tmp_path / "missed")
    return schedule_store


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    """Redirects human_bot.db's sqlite store to a throwaway file under
    tmp_path — every query function in db.py goes through its single
    _connect() helper, which reads DB_PATH at call time, so this
    monkeypatch covers all of them. Creates the schema right away so
    callers don't have to remember to."""
    from human_bot import db
    fake_path = tmp_path / "human_bot.db"
    monkeypatch.setattr(db, "DB_PATH", fake_path)
    db.ensure_schema()
    return fake_path


@pytest.fixture
def isolated_accounts_dir(tmp_path, monkeypatch):
    """Redirects human_bot.config.ACCOUNTS_DIR to a throwaway tmp_path dir,
    for tests that need at least one real registered account (accounts,
    groups, post composer) without touching the real accounts/ directory."""
    from human_bot import config
    fake_dir = tmp_path / "accounts"
    fake_dir.mkdir()
    monkeypatch.setattr(config, "ACCOUNTS_DIR", fake_dir)
    return fake_dir


@pytest.fixture
def isolated_screenshots_root(tmp_path, monkeypatch):
    """Redirects human_bot.screenshots.SCREENSHOTS_ROOT to a throwaway
    tmp_path dir, for tests of the GET /admin/screenshot route."""
    from human_bot import screenshots
    fake_dir = tmp_path / "screenshots"
    fake_dir.mkdir()
    monkeypatch.setattr(screenshots, "SCREENSHOTS_ROOT", fake_dir)
    return fake_dir


@pytest.fixture
def no_real_run_task(monkeypatch):
    """Replaces human_bot.admin.run_task with a fake async that never
    touches the real Playwright browser pool — the 3 routes that call it
    directly (schedule_fire_now, schedule_missed_fire_now, reports_repost)
    must never dispatch a real browser action from a test. Returns a list
    that records every TaskRequest passed in, and a mutable dict the test
    can use to control the next call's TaskResult via `result_queue`."""
    from human_bot import admin as admin_module
    from human_bot.agent import TaskResult

    calls = []
    results = []  # test pushes TaskResult objects here; default: one success

    async def fake_run_task(req):
        calls.append(req)
        if results:
            return results.pop(0)
        return TaskResult(success=True, message="ok (fake)", screenshot_path=None, timestamp="2026-01-01T00:00:00+00:00")

    monkeypatch.setattr(admin_module, "run_task", fake_run_task)
    return calls, results


@pytest.fixture
def no_real_bootstrap_login(monkeypatch):
    """Replaces the 4 bootstrap_login_sessions functions admin.py's
    /admin/accounts bootstrap-login routes call — the only other place in
    admin.py that launches a real (headed) Playwright browser, besides
    run_task(). Matches the real module's exact shapes
    (bootstrap_login_sessions.py): start()/confirm()/cancel() are async,
    status() is sync; status() and confirm() return (value, error) tuples,
    start() and cancel() return nothing."""
    from human_bot import bootstrap_login_sessions as bls

    calls = {"start": [], "status": [], "confirm": [], "cancel": []}
    state = {"status": "waiting", "error": None, "confirm_ok": True, "confirm_error": None}

    async def fake_start(account_id):
        calls["start"].append(account_id)

    def fake_status(account_id):
        calls["status"].append(account_id)
        return state["status"], state["error"]

    async def fake_confirm(account_id):
        calls["confirm"].append(account_id)
        return state["confirm_ok"], state["confirm_error"]

    async def fake_cancel(account_id):
        calls["cancel"].append(account_id)

    monkeypatch.setattr(bls, "start", fake_start)
    monkeypatch.setattr(bls, "status", fake_status)
    monkeypatch.setattr(bls, "confirm", fake_confirm)
    monkeypatch.setattr(bls, "cancel", fake_cancel)
    return calls, state
