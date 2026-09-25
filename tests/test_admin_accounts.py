"""
HTTP-level tests for /admin/accounts (2026-09-25 test-coverage plan,
Phase 3) — account CRUD, pause/resume, sync/sponsored-only toggles,
rate-limit overrides, and the Playwright-driven bootstrap-login flow.

Same "minimal FastAPI app" pattern as the other admin.py HTTP test
files. `client` always combines isolated_runtime_config AND
isolated_accounts_dir (not just one) — found during the Phase 2 audit
that some code paths reachable from this page (_suggest_reschedule_at
elsewhere, but also this page's own storage_state_path/action_log_path
checks on every registered account) construct a RateLimiter or touch
AccountConfig's derived paths, which resolve against the REAL
human_bot.config.ACCOUNTS_DIR unless isolated — a real accounts/<id>/
directory got created in the project tree that way once already.
no_real_bootstrap_login keeps the bootstrap-login routes from ever
touching a real (headed) Playwright browser.
"""
from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from human_bot.admin import NotLoggedIn, router as admin_router
from human_bot.runtime_config import (
    get_registered_accounts,
    get_sponsored_only_account_ids,
    get_sync_disabled_account_ids,
    save_registered_account,
)


def _make_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="test-only-secret-key",
        session_cookie="human_bot_admin_session",
        max_age=3600,
        same_site="lax",
        https_only=False,
    )

    @app.exception_handler(NotLoggedIn)
    async def _handle_not_logged_in(request, exc: NotLoggedIn) -> Response:
        login_url = "/admin/login"
        if exc.next_path:
            login_url += "?next=" + quote(exc.next_path, safe="")
        if request.headers.get("hx-request") == "true":
            return Response(status_code=200, headers={"HX-Redirect": login_url})
        return RedirectResponse(login_url, status_code=303)

    app.include_router(admin_router)
    return app


@pytest.fixture
def client(isolated_runtime_config, isolated_accounts_dir, isolated_schedule_dirs, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return TestClient(_make_test_app(), follow_redirects=False)


def _register(account_id="acc-a", display_name="Acc A") -> None:
    save_registered_account(account_id, display_name)


# --- accounts_page ---

def test_accounts_page_renders_with_no_accounts(client):
    resp = client.get("/admin/accounts")
    assert resp.status_code == 200


def test_accounts_page_lists_a_registered_account(client):
    _register("acc-a", "Acc A")
    resp = client.get("/admin/accounts")
    assert "acc-a" in resp.text
    assert "Acc A" in resp.text


def test_accounts_page_sync_tab_renders(client):
    _register("acc-a")
    resp = client.get("/admin/accounts?tab=sync")
    assert resp.status_code == 200


# --- accounts_add ---

def test_add_account_registers_it(client):
    resp = client.post("/admin/accounts/add", data={"account_id": "new_acc", "display_name": "New Acc"})
    assert resp.status_code == 303
    assert "saved=1" in resp.headers["location"]
    registered = {a["account_id"] for a in get_registered_accounts()}
    assert "new_acc" in registered


def test_add_account_rejects_invalid_id(client):
    resp = client.post("/admin/accounts/add", data={"account_id": "Not Valid!", "display_name": "X"})
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    registered = {a["account_id"] for a in get_registered_accounts()}
    assert not registered


def test_add_account_rejects_duplicate_id(client):
    _register("acc-a")
    resp = client.post("/admin/accounts/add", data={"account_id": "acc-a", "display_name": "Dup"})
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_add_account_applies_default_age_tier_rate_limits(client):
    """add_account falls back to DEFAULT_ACCOUNT_AGE_TIER ("under_1_month")
    when no/invalid age_tier is posted — owner decision 2026-09-15, so a
    direct API call skipping the field never silently gets the
    code-level RateLimits default (30 posts/day, the opposite of the
    safe assumption for a brand-new account)."""
    from human_bot.runtime_config import get_rate_limits_overrides
    resp = client.post("/admin/accounts/add", data={"account_id": "new_acc", "display_name": "X"})
    assert resp.status_code == 303
    overrides = get_rate_limits_overrides("new_acc")
    assert overrides["posts_per_day"] == 5  # ACCOUNT_AGE_TIERS["under_1_month"]'s own value
    assert overrides["comments_per_day"] == 7


# --- pause / resume ---

def test_pause_then_resume_account(client):
    from human_bot.config import get_all_accounts, AccountStatus
    _register("acc-a")
    resp = client.post("/admin/accounts/pause", data={"account_id": "acc-a"})
    assert resp.status_code == 303
    assert get_all_accounts()["acc-a"].status == AccountStatus.PAUSED

    resp = client.post("/admin/accounts/resume", data={"account_id": "acc-a"})
    assert resp.status_code == 303
    assert get_all_accounts()["acc-a"].status == AccountStatus.ACTIVE


# --- sync enable/disable ---

def test_sync_disable_then_enable(client):
    _register("acc-a")
    resp = client.post("/admin/accounts/sync-disable", data={"account_id": "acc-a"})
    assert resp.status_code == 303
    assert "acc-a" in get_sync_disabled_account_ids()

    resp = client.post("/admin/accounts/sync-enable", data={"account_id": "acc-a"})
    assert resp.status_code == 303
    assert "acc-a" not in get_sync_disabled_account_ids()


# --- sponsored-only enable/disable ---

def test_sponsored_only_enable_then_disable(client):
    _register("acc-a")
    resp = client.post("/admin/accounts/sponsored-only-enable", data={"account_id": "acc-a"})
    assert resp.status_code == 303
    assert "acc-a" in get_sponsored_only_account_ids()

    resp = client.post("/admin/accounts/sponsored-only-disable", data={"account_id": "acc-a"})
    assert resp.status_code == 303
    assert "acc-a" not in get_sponsored_only_account_ids()


# --- delete ---

def test_delete_account_removes_registration_and_cleans_up(client):
    import human_bot.schedule_store as schedule_store
    from datetime import datetime, timedelta, timezone
    from human_bot.runtime_config import (
        get_removed_account_ids, save_rate_limits_overrides, set_account_paused,
    )
    _register("acc-a")
    set_account_paused("acc-a", True)
    save_rate_limits_overrides("acc-a", {"posts_per_day": 5})
    task = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(datetime.now(timezone.utc).isoformat()),
        action="post_to_group", account_id="acc-a",
        scheduled_at=(datetime.now(timezone.utc) + timedelta(hours=1)).isoformat(),
        content="x", target_url="https://facebook.com/groups/1",
    )
    schedule_store.add(task)

    resp = client.post("/admin/accounts/delete", data={"account_id": "acc-a"})
    assert resp.status_code == 303
    assert "acc-a" in get_removed_account_ids()
    registered = {a["account_id"] for a in get_registered_accounts()}
    assert "acc-a" not in registered
    # Pending tasks for the deleted account must be cancelled, not left
    # dangling (would error the next time something tries to fire them).
    assert schedule_store.get(task.task_id) is None


def test_delete_nonexistent_account_is_a_graceful_no_op(client):
    resp = client.post("/admin/accounts/delete", data={"account_id": "ghost"})
    assert resp.status_code == 303


# --- rate limits modal / save ---

def test_rate_limits_modal_unknown_account_shows_error(client):
    resp = client.get("/admin/accounts/rate-limits-modal?account_id=ghost")
    assert "Không tìm thấy tài khoản" in resp.text


def test_rate_limits_modal_known_account_renders(client):
    _register("acc-a")
    resp = client.get("/admin/accounts/rate-limits-modal?account_id=acc-a")
    assert resp.status_code == 200


def test_rate_limits_save_persists_override(client):
    from human_bot.runtime_config import get_rate_limits_overrides
    _register("acc-a")
    resp = client.post("/admin/accounts/rate-limits", data={
        "account_id": "acc-a",
        "posts_per_day": "5", "comments_per_hour": "2", "comments_per_day": "10",
        "likes_per_hour": "3", "post_min_delay_seconds": "100", "post_max_delay_seconds": "200",
        "comment_min_delay_seconds": "50", "comment_max_delay_seconds": "100",
        "max_groups_per_post": "2",
    })
    assert resp.status_code == 303
    overrides = get_rate_limits_overrides("acc-a")
    assert overrides["posts_per_day"] == 5


def test_rate_limits_save_rejects_negative_value(client):
    from human_bot.runtime_config import get_rate_limits_overrides
    _register("acc-a")
    resp = client.post("/admin/accounts/rate-limits", data={
        "account_id": "acc-a",
        "posts_per_day": "-1", "comments_per_hour": "2", "comments_per_day": "10",
        "likes_per_hour": "3", "post_min_delay_seconds": "100", "post_max_delay_seconds": "200",
        "comment_min_delay_seconds": "50", "comment_max_delay_seconds": "100",
        "max_groups_per_post": "2",
    })
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert not get_rate_limits_overrides("acc-a")


def test_rate_limits_save_rejects_min_greater_than_max(client):
    _register("acc-a")
    resp = client.post("/admin/accounts/rate-limits", data={
        "account_id": "acc-a",
        "posts_per_day": "5", "comments_per_hour": "2", "comments_per_day": "10",
        "likes_per_hour": "3", "post_min_delay_seconds": "999", "post_max_delay_seconds": "1",
        "comment_min_delay_seconds": "50", "comment_max_delay_seconds": "100",
        "max_groups_per_post": "2",
    })
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_rate_limits_reset_clears_override(client):
    from human_bot.runtime_config import get_rate_limits_overrides, save_rate_limits_overrides
    _register("acc-a")
    save_rate_limits_overrides("acc-a", {"posts_per_day": 5})
    resp = client.post("/admin/accounts/rate-limits", data={"account_id": "acc-a", "reset": "1"})
    assert resp.status_code == 303
    assert not get_rate_limits_overrides("acc-a")


# --- bootstrap-login flow (no real Playwright) ---

def test_bootstrap_login_modal_renders(client):
    resp = client.get("/admin/accounts/bootstrap-login-modal?account_id=acc-a")
    assert resp.status_code == 200
    assert "acc-a" in resp.text


def test_bootstrap_login_start_rejects_invalid_account_id(client, no_real_bootstrap_login):
    calls, _state = no_real_bootstrap_login
    resp = client.post("/admin/accounts/bootstrap-login/start", data={"account_id": "Not Valid!"})
    assert resp.status_code == 200
    assert "không hợp lệ" in resp.text
    assert calls["start"] == []


def test_bootstrap_login_start_fires_and_status_polls(client, no_real_bootstrap_login):
    calls, state = no_real_bootstrap_login
    resp = client.post("/admin/accounts/bootstrap-login/start", data={"account_id": "acc-a"})
    assert resp.status_code == 200
    # start() is fired via asyncio.create_task() (fire-and-forget) — the
    # response itself only reflects status() read BEFORE that task has
    # necessarily run, so this checks the polling status route separately
    # rather than assuming start() already completed by response time.
    state["status"] = "waiting_confirm"
    resp2 = client.get("/admin/accounts/bootstrap-login/status?account_id=acc-a")
    assert "Đăng nhập thủ công" in resp2.text
    assert "Đã đăng nhập xong" in resp2.text


def test_bootstrap_login_confirm_success(client, no_real_bootstrap_login):
    calls, state = no_real_bootstrap_login
    state["confirm_ok"] = True
    resp = client.post("/admin/accounts/bootstrap-login/confirm", data={"account_id": "acc-a"})
    assert resp.status_code == 200
    assert "Đã lưu phiên đăng nhập" in resp.text
    assert calls["confirm"] == ["acc-a"]


def test_bootstrap_login_confirm_failure_offers_retry(client, no_real_bootstrap_login):
    calls, state = no_real_bootstrap_login
    state["confirm_ok"] = False
    state["confirm_error"] = "trang không phản hồi"
    resp = client.post("/admin/accounts/bootstrap-login/confirm", data={"account_id": "acc-a"})
    assert resp.status_code == 200
    assert "trang không phản hồi" in resp.text
    assert "Mở lại trình duyệt" in resp.text


def test_bootstrap_login_cancel(client, no_real_bootstrap_login):
    calls, _state = no_real_bootstrap_login
    resp = client.post("/admin/accounts/bootstrap-login/cancel", data={"account_id": "acc-a"})
    assert resp.status_code == 200
    assert calls["cancel"] == ["acc-a"]
