"""Tests for "⏻ Tắt" (2026-10-31): an operator switching an account off on
purpose, as opposed to "⚠ Tạm dừng" (suspected violation → cooldown on resume).
"""
from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

from human_bot import agent, browser_pool, daily_limits, data_sync, network_check, schedule_store
from human_bot.agent import TaskRequest
from human_bot.config import AccountStatus, get_account, get_all_accounts
from human_bot.runtime_config import (
    get_disabled_account_ids,
    get_disabled_info,
    get_resume_cooldown_info,
    resume_account,
    set_account_disabled,
    set_account_paused,
)
from human_bot.safety import RateLimiter
from human_bot.scheduling_config import SchedulingConfig

ACC = "tu_iizuki"  # the code-level default account


@pytest.fixture
def client(isolated_runtime_config, isolated_accounts_dir, isolated_schedule_dirs, monkeypatch):
    from tests.test_admin_post import _make_test_app
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return TestClient(_make_test_app(), follow_redirects=False)


# --- the flag ----------------------------------------------------------------------------

def test_switching_off_and_on_is_recorded_with_a_timestamp(isolated_runtime_config):
    assert get_disabled_account_ids() == set() and get_disabled_info(ACC) is None
    set_account_disabled(ACC, True)
    assert get_disabled_account_ids() == {ACC}
    assert get_disabled_info(ACC)["disabled_at"]
    first_stamp = get_disabled_info(ACC)["disabled_at"]
    set_account_disabled(ACC, True)                       # idempotent: the original time is kept
    assert get_disabled_info(ACC)["disabled_at"] == first_stamp
    set_account_disabled(ACC, False)
    assert get_disabled_account_ids() == set()
    set_account_disabled(ACC, False)                      # no error when already on


def test_a_hand_edited_plain_list_is_tolerated(isolated_runtime_config):
    isolated_runtime_config.write_text(json.dumps({"disabled_accounts": [ACC]}))
    assert get_disabled_account_ids() == {ACC} and get_disabled_info(ACC) == {"disabled_at": None}
    set_account_disabled("other", True)
    assert get_disabled_account_ids() == {ACC, "other"}   # converted, nothing lost


def test_the_account_becomes_disabled_not_paused(isolated_runtime_config, isolated_accounts_dir):
    assert get_all_accounts()[ACC].status == AccountStatus.ACTIVE
    set_account_disabled(ACC, True)
    assert get_all_accounts()[ACC].status == AccountStatus.DISABLED


def test_pausing_supersedes_and_clears_the_off_flag(isolated_runtime_config, isolated_accounts_dir):
    set_account_disabled(ACC, True)
    set_account_paused(ACC, True, reason="checkpoint")
    assert get_all_accounts()[ACC].status == AccountStatus.PAUSED
    assert get_disabled_account_ids() == set()            # so resuming later cannot land back on "off"
    resume_account(ACC)
    assert get_all_accounts()[ACC].status == AccountStatus.ACTIVE


def test_switching_back_on_has_no_cooldown_but_resuming_a_pause_does(isolated_runtime_config, isolated_accounts_dir):
    set_account_disabled(ACC, True)
    set_account_disabled(ACC, False)
    assert get_resume_cooldown_info(ACC) is None          # immediate, full limits
    set_account_paused(ACC, True, reason="suspected restriction")
    resume_account(ACC)
    assert get_resume_cooldown_info(ACC) is not None      # a pause still cools down


# --- run_task ----------------------------------------------------------------------------

async def test_a_switched_off_account_runs_nothing_and_says_so(isolated_runtime_config, isolated_accounts_dir, isolated_db, monkeypatch):
    set_account_disabled(ACC, True)
    touched = []
    monkeypatch.setattr(agent, "get_session", lambda account: touched.append(account) or None)
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id=ACC, target_url="u", content="x"))
    assert not result.success and result.message == f"account_disabled:{ACC}"
    assert touched == []                                   # no browser was ever requested
    assert RateLimiter(get_account(ACC)).next_allowed_at("post") is None


async def test_a_paused_account_keeps_its_own_message(isolated_runtime_config, isolated_accounts_dir, isolated_db):
    set_account_paused(ACC, True, reason="x")
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id=ACC, target_url="u", content="x"))
    assert result.message == f"account_paused:{ACC}"


# --- due tasks of a switched-off account ----------------------------------------------------

async def test_due_tasks_of_an_off_account_go_to_overdue_instead_of_failing(isolated_schedule_dirs, isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    async def online(*a, **k):
        return True

    monkeypatch.setattr(network_check, "wait_for_internet", online)
    ran = []

    async def fake_run_task(request):
        ran.append(request.account_id)
        from human_bot.agent import TaskResult
        return TaskResult(success=True, message="ok", screenshot_path=None, timestamp="t")

    monkeypatch.setattr("human_bot.agent.run_task", fake_run_task)
    monkeypatch.setattr(daily_limits, "hard_cap_message", lambda *a, **k: None)
    store = isolated_schedule_dirs
    when = datetime.now(timezone.utc) - timedelta(minutes=2)
    task = store.ScheduledTask(
        task_id=store.new_task_id(when.isoformat()), action="post_to_group", account_id=ACC,
        scheduled_at=when.isoformat(), content="x", target_url="https://facebook.com/groups/1",
    )
    store.add(task)
    set_account_disabled(ACC, True)
    await data_sync.fire_due_tasks(SchedulingConfig(auto_fire_enabled=True))
    assert ran == []
    assert store.list_pending() == [] and store.list_posted() == []
    assert [t.task_id for t in store.list_missed()] == [task.task_id]
    assert "đang được tắt" in store.get_missed_reason(task.task_id)
    assert not list(store.FAILED_DIR.glob("*.json"))      # it did NOT fail — the admin can reschedule it


# --- admin ----------------------------------------------------------------------------------

def test_the_list_offers_off_and_pause_separately_for_an_active_account(client):
    html = client.get("/admin/accounts").text
    assert 'action="/admin/accounts/disable"' in html and "⏻ Tắt" in html
    assert 'action="/admin/accounts/pause"' in html and "⚠ Tạm dừng" in html
    assert "hạ nhiệt" in html                              # the pause button explains the consequence


def test_disabling_marks_the_row_off_and_offers_to_turn_it_back_on(client):
    client.post("/admin/accounts/disable", data={"account_id": ACC})
    assert get_all_accounts()[ACC].status == AccountStatus.DISABLED
    html = client.get("/admin/accounts").text
    assert "⏻ Đã tắt" in html and "Tắt chủ động" in html
    assert 'action="/admin/accounts/enable"' in html and "▶ Bật lại" in html
    assert "Kích hoạt lại" not in html and 'action="/admin/accounts/pause"' not in html
    client.post("/admin/accounts/enable", data={"account_id": ACC})
    assert get_all_accounts()[ACC].status == AccountStatus.ACTIVE
    assert get_resume_cooldown_info(ACC) is None


def test_a_paused_row_still_offers_the_cooldown_resume(client):
    client.post("/admin/accounts/pause", data={"account_id": ACC})
    html = client.get("/admin/accounts").text
    assert "▶ Kích hoạt lại" in html and "⏻ Đã tắt" not in html


def test_a_paused_account_cannot_be_switched_off_and_an_unknown_one_errors(client):
    client.post("/admin/accounts/pause", data={"account_id": ACC})
    resp = client.post("/admin/accounts/disable", data={"account_id": ACC})
    assert resp.status_code == 303 and "error=" in resp.headers["location"]
    assert get_all_accounts()[ACC].status == AccountStatus.PAUSED
    assert "error=" in client.post("/admin/accounts/disable", data={"account_id": "nope"}).headers["location"]


def test_switching_off_closes_the_idle_browser(client, monkeypatch):
    closed = []

    async def fake_close(account_id):
        closed.append(account_id)
        return True

    monkeypatch.setattr(browser_pool, "close_idle_session", fake_close)
    client.post("/admin/accounts/disable", data={"account_id": ACC})
    assert closed == [ACC]


def test_a_browser_that_will_not_close_does_not_block_switching_off(client, monkeypatch):
    async def boom(account_id):
        raise RuntimeError("chrome is stuck")

    monkeypatch.setattr(browser_pool, "close_idle_session", boom)
    client.post("/admin/accounts/disable", data={"account_id": ACC})
    assert get_all_accounts()[ACC].status == AccountStatus.DISABLED


async def test_close_idle_session_leaves_a_busy_or_missing_session_alone(monkeypatch):
    assert await browser_pool.close_idle_session("nobody") is False

    class _S:
        def __init__(self, locked):
            import asyncio
            self.lock = asyncio.Lock()
            self.page = object()
            self.closed = 0
            self._locked = locked

        async def close(self, save=True):
            self.closed += 1

    busy, idle = _S(True), _S(False)
    await busy.lock.acquire()
    monkeypatch.setitem(browser_pool._pool, "busy", busy)
    monkeypatch.setitem(browser_pool._pool, "idle", idle)
    assert await browser_pool.close_idle_session("busy") is False and busy.closed == 0
    assert await browser_pool.close_idle_session("idle") is True and idle.closed == 1


def test_deleting_an_account_clears_its_off_flag(client):
    client.post("/admin/accounts/add", data={"account_id": "temp_acc", "display_name": "T"})
    client.post("/admin/accounts/disable", data={"account_id": "temp_acc"})
    client.post("/admin/accounts/delete", data={"account_id": "temp_acc"})
    assert "temp_acc" not in get_disabled_account_ids()


def test_an_off_account_raises_no_health_warnings_and_reads_as_off(isolated_runtime_config, isolated_accounts_dir):
    from human_bot import admin
    set_account_disabled(ACC, True)
    account = get_all_accounts()[ACC]
    old = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    status = admin._account_warning_status(ACC, account, {ACC: old})   # 30 days silent, no session file
    assert status.kinds == set()                           # nothing to page anyone about
    severity, rows = admin._account_health_signals(ACC, account, {}, {ACC: old})
    assert severity == 2 and len(rows) == 1 and "Đã tắt" in rows[0][1]
    assert "Đã tắt" in admin._account_health_telegram_text(ACC, account, {}, {ACC: old})


def test_the_home_page_does_not_raise_the_red_pause_banner_for_an_off_account(client):
    client.post("/admin/accounts/disable", data={"account_id": ACC})
    html = client.get("/admin").text
    assert "Đã tắt" in html and "đang <strong>Tạm dừng</strong>" not in html


def test_the_sync_tab_and_the_post_page_explain_an_off_account(client):
    client.post("/admin/accounts/disable", data={"account_id": ACC})
    assert "đã tắt — không sync" in client.get("/admin/accounts?tab=sync").text
    post = client.get(f"/admin/post?account_id={ACC}").text
    assert "đang <strong>tắt</strong>" in post and "Task quá hạn" in post


# --- Pages whose owner is switched off --------------------------------------------------------

def _page(mode):
    from human_bot.runtime_config import save_registered_account
    save_registered_account("page_t", "Page T", "The Page", "Tu Nguyen", ACC, mode)


async def _run(monkeypatch, mode, owner_state):
    _page(mode)
    if owner_state == "off":
        set_account_disabled(ACC, True)
    elif owner_state == "paused":
        set_account_paused(ACC, True, reason="checkpoint")
    attempts = []

    class _Sess:
        def __init__(self):
            import asyncio
            self.page, self.lock = object(), asyncio.Lock()
            self.identity_dirty = False

        async def ensure_started(self): pass
        def is_alive(self): return True
        async def save_state(self): pass
        async def close(self, save=True): pass

    sessions = {}
    monkeypatch.setattr(agent, "get_session", lambda account: attempts.append(account.account_id) or sessions.setdefault(account.account_id, _Sess()))
    monkeypatch.setattr(daily_limits, "can_proceed", lambda account, bucket, ignore_gap=False: (True, ""))

    async def ok_identity(page, name, personal):
        return None

    async def noop(*a, **k):
        return None

    async def action(page, req):
        from human_bot.actions import ActionResult
        return ActionResult(success=True, message="posted_to_group")

    monkeypatch.setattr(agent.actions, "ensure_page_identity", ok_identity)
    monkeypatch.setattr(agent.actions, "switch_to_identity", noop)
    monkeypatch.setattr(agent.actions, "restore_personal_identity", noop)
    monkeypatch.setattr(agent.screenshots, "capture", noop)
    monkeypatch.setattr(agent.telegram_notify, "send_message", noop)
    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", action))
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id="page_t", target_url="u", content="x"))
    return result, attempts


async def test_a_page_with_its_own_session_still_runs_when_the_owner_is_just_off(isolated_runtime_config, isolated_accounts_dir, isolated_db, monkeypatch):
    result, attempts = await _run(monkeypatch, "own_session", "off")
    assert result.success and attempts == ["page_t"]


async def test_an_owner_session_page_cannot_use_a_switched_off_owner(isolated_runtime_config, isolated_accounts_dir, isolated_db, monkeypatch):
    result, attempts = await _run(monkeypatch, "owner_session", "off")
    assert not result.success and result.message == f"page_owner_off:{ACC}"
    assert attempts == []                                  # the owner's session was never opened
    assert RateLimiter(get_account("page_t")).next_allowed_at("post") is None


async def test_auto_does_not_fall_back_to_a_switched_off_owner(isolated_runtime_config, isolated_accounts_dir, isolated_db, monkeypatch):
    _page("auto")
    set_account_disabled(ACC, True)

    class _Sess:
        page = object()

        def __init__(self):
            import asyncio
            self.lock = asyncio.Lock()
            self.identity_dirty = False

        async def ensure_started(self): pass
        def is_alive(self): return True
        async def save_state(self): pass
        async def close(self, save=True): pass

    used = []
    monkeypatch.setattr(agent, "get_session", lambda account: used.append(account.account_id) or _Sess())
    monkeypatch.setattr(daily_limits, "can_proceed", lambda account, bucket, ignore_gap=False: (True, ""))

    async def bad_identity(page, name, personal):
        return "identity_unverified:x"

    async def noop(*a, **k):
        return None

    monkeypatch.setattr(agent.actions, "ensure_page_identity", bad_identity)
    monkeypatch.setattr(agent.screenshots, "capture", noop)
    monkeypatch.setattr(agent.telegram_notify, "send_message", noop)
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id="page_t", target_url="u", content="x"))
    assert not result.success and used == ["page_t"]       # only the Page's own session was tried


async def test_a_paused_owner_still_blocks_every_page_of_it(isolated_runtime_config, isolated_accounts_dir, isolated_db, monkeypatch):
    result, attempts = await _run(monkeypatch, "own_session", "paused")
    assert not result.success and result.message.startswith(f"account_paused:{ACC}") and attempts == []


def test_the_page_list_says_when_its_owner_is_off(client):
    from human_bot.runtime_config import save_registered_account
    save_registered_account("page_t", "Page T", "The Page", "Tu Nguyen", ACC, "owner_session")
    client.post("/admin/accounts/disable", data={"account_id": ACC})
    assert "đang tắt — không dùng được phiên của tài khoản đó" in client.get("/admin/accounts").text


# --- review round (2026-10-31) -------------------------------------------------------------------

def test_refusals_of_an_off_account_never_count_towards_the_failure_streak(isolated_db):
    """db.consecutive_failure_streak() skips rows that never touched Facebook —
    an account switched off must not trigger the "N lần fail liên tiếp" alert."""
    from human_bot import db
    for message in ("account_disabled:x", "page_owner_off:x", "page_owner_missing:x"):
        for _ in range(8):
            db.log_action(account_id="a", action="post_to_group", success=False, message=message)
    assert db.consecutive_failure_streak("a", "post_to_group") == 0
    db.log_action(account_id="a", action="post_to_group", success=False, message="post_button_still_visible_after_click")
    assert db.consecutive_failure_streak("a", "post_to_group") == 1


async def test_close_idle_session_holds_the_lock_while_closing(monkeypatch):
    import asyncio
    states = []

    class _S:
        def __init__(self):
            self.lock = asyncio.Lock()
            self.page = object()

        async def close(self, save=True):
            states.append(self.lock.locked())   # a task trying to start now must wait for us
            self.page = None

    s = _S()
    monkeypatch.setitem(browser_pool._pool, "x", s)
    assert await browser_pool.close_idle_session("x") is True
    assert states == [True] and not s.lock.locked()


def test_enable_validates_like_disable(client):
    assert "error=" in client.post("/admin/accounts/enable", data={"account_id": "nope"}).headers["location"]
    assert "error=" in client.post("/admin/accounts/enable", data={"account_id": ACC}).headers["location"]   # not off
    client.post("/admin/accounts/disable", data={"account_id": ACC})
    assert "saved=1" in client.post("/admin/accounts/enable", data={"account_id": ACC}).headers["location"]


def test_an_auto_page_with_no_session_and_an_off_owner_says_it_cannot_run(client):
    from human_bot.runtime_config import save_registered_account
    save_registered_account("page_t", "Page T", "The Page", "Tu Nguyen", ACC, "auto")
    client.post("/admin/accounts/disable", data={"account_id": ACC})
    assert "Page chưa chạy được" in client.get("/admin/accounts").text
