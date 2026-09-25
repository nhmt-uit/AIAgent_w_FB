"""
HTTP-level tests for /admin/reports (2026-09-25 test-coverage plan,
Phase 2) — second-highest-churn section of admin.py after /admin/schedule
(Phase 1). Same "minimal FastAPI app" pattern as
tests/test_admin_login.py/test_admin_schedule.py; uses the isolated_db
fixture (tests/conftest.py) for every human_bot.db read/write, and
isolated_schedule_dirs for reports_reschedule_confirm (which creates a
real ScheduledTask). no_real_run_task keeps reports_repost from ever
dispatching a real browser action.
"""
from __future__ import annotations

import sqlite3
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

import human_bot.schedule_store as schedule_store
from human_bot import db
from human_bot.admin import NotLoggedIn, router as admin_router
from human_bot.config import AccountConfig


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
def client(isolated_runtime_config, isolated_schedule_dirs, isolated_db, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return TestClient(_make_test_app(), follow_redirects=False)


def _last_log_id(db_path) -> int:
    conn = sqlite3.connect(db_path)
    try:
        row = conn.execute("SELECT id FROM action_log ORDER BY id DESC LIMIT 1").fetchone()
        return row[0]
    finally:
        conn.close()


def _log(isolated_db, **kwargs) -> int:
    defaults = dict(account_id="acc-a", action="post_to_group", success=False, message="", content="hello", target_url="https://facebook.com/groups/1")
    defaults.update(kwargs)
    db.log_action(**defaults)
    return _last_log_id(isolated_db)


# --- reports_page: basic rendering + stats ---

def test_reports_page_renders_with_no_data(client):
    resp = client.get("/admin/reports")
    assert resp.status_code == 200


def test_reports_page_tables_tab_shows_action_counts(client, isolated_db):
    _log(isolated_db, account_id="acc-a", action="post_to_group", success=True)
    _log(isolated_db, account_id="acc-a", action="post_to_group", success=True)
    resp = client.get("/admin/reports?tab=tables")
    assert resp.status_code == 200


def test_reports_page_recent_tab_shows_logged_rows(client, isolated_db):
    """The "Hoạt động gần đây" table's own <td> shows each row's
    `message` (the run's own result text), not `content` (the composed
    post/comment body) — see reports_page's recent_html builder
    (admin.py, `_expandable_text(r['message'])`)."""
    _log(isolated_db, account_id="acc-a", action="post_to_group", success=True, message="hello world unique marker")
    resp = client.get("/admin/reports?tab=recent")
    assert resp.status_code == 200
    assert "hello world unique marker" in resp.text


def test_reports_page_account_filter(client, isolated_db):
    _log(isolated_db, account_id="acc-a", message="marker-a")
    _log(isolated_db, account_id="acc-b", message="marker-b")
    resp = client.get("/admin/reports?tab=recent&account_id=acc-a")
    assert "marker-a" in resp.text
    assert "marker-b" not in resp.text


def test_reports_page_unknown_tab_falls_back_to_tables(client):
    resp = client.get("/admin/reports?tab=not-a-real-tab")
    assert resp.status_code == 200


# --- reports_repost ---

def test_repost_missing_log_id(client):
    resp = client.post("/admin/reports/repost", data={})
    assert resp.status_code in (200, 303)


def test_repost_log_id_not_found(client):
    resp = client.post("/admin/reports/repost", data={"log_id": "999999"})
    assert resp.status_code in (200, 303)


def test_repost_rejects_a_successful_row(client, isolated_db):
    """Only a FAILED attempt with real content can be reposted — see
    _REPOSTABLE_ACTIONS/success check in reports_repost()."""
    log_id = _log(isolated_db, success=True)
    resp = client.post("/admin/reports/repost", data={"log_id": str(log_id)})
    assert resp.status_code in (200, 303)
    if resp.status_code == 303:
        assert "error=" in resp.headers["location"]


def test_repost_rejects_a_non_repostable_action(client, isolated_db):
    log_id = _log(isolated_db, action="like_post", success=False)
    resp = client.post("/admin/reports/repost", data={"log_id": str(log_id)})
    assert resp.status_code in (200, 303)
    if resp.status_code == 303:
        assert "error=" in resp.headers["location"]


def test_repost_succeeds_and_calls_run_task(client, isolated_db, no_real_run_task):
    calls, _results = no_real_run_task
    log_id = _log(isolated_db, action="post_to_group", success=False, content="retry me")
    resp = client.post("/admin/reports/repost", data={"log_id": str(log_id)})
    assert resp.status_code in (200, 303)
    assert len(calls) == 1
    assert calls[0].retry_of_log_id == log_id
    assert calls[0].content == "retry me"


def test_repost_rate_limited_shows_warning_not_error(client, isolated_db, no_real_run_task):
    """2026-09-11 owner request: a rate-limited repost must surface as a
    warning, never as a red "Đăng lại thất bại" error."""
    from human_bot.agent import TaskResult
    calls, results = no_real_run_task
    results.append(TaskResult(success=False, message="rate_limited: too soon", screenshot_path=None, timestamp="x"))
    log_id = _log(isolated_db, action="post_to_group", success=False, content="retry me")

    resp = client.post("/admin/reports/repost", data={"log_id": str(log_id)})
    assert resp.status_code in (200, 303)
    if resp.status_code == 303:
        assert "warning=" in resp.headers["location"]
        assert "error=" not in resp.headers["location"]


def test_repost_real_failure_shows_error(client, isolated_db, no_real_run_task):
    from human_bot.agent import TaskResult
    calls, results = no_real_run_task
    results.append(TaskResult(success=False, message="something broke", screenshot_path=None, timestamp="x"))
    log_id = _log(isolated_db, action="post_to_group", success=False, content="retry me")

    resp = client.post("/admin/reports/repost", data={"log_id": str(log_id)})
    assert resp.status_code in (200, 303)
    if resp.status_code == 303:
        assert "error=" in resp.headers["location"]


# --- reports_reschedule_suggest / _confirm ---

def test_reschedule_suggest_unknown_log_id_returns_empty(client):
    resp = client.get("/admin/reports/reschedule-suggest?log_id=999999")
    assert resp.status_code == 200
    assert resp.text == ""


def test_reschedule_suggest_missing_account_shows_error_modal(client, isolated_db):
    log_id = _log(isolated_db, account_id="ghost-account", success=False, content="x")
    resp = client.get(f"/admin/reports/reschedule-suggest?log_id={log_id}")
    assert "Không tìm thấy tài khoản" in resp.text


def test_reschedule_suggest_with_known_account_shows_suggested_time(client, isolated_db, monkeypatch):
    import human_bot.admin as admin_module
    monkeypatch.setattr(admin_module, "get_all_accounts", lambda: {"acc-a": AccountConfig(account_id="acc-a", display_name="A")})
    log_id = _log(isolated_db, account_id="acc-a", success=False, content="x")
    resp = client.get(f"/admin/reports/reschedule-suggest?log_id={log_id}")
    assert "Lên lịch lại" in resp.text
    assert f'value="{log_id}"' in resp.text


def test_reschedule_confirm_creates_a_pending_task(client, isolated_db, monkeypatch):
    import human_bot.admin as admin_module
    monkeypatch.setattr(admin_module, "get_all_accounts", lambda: {"acc-a": AccountConfig(account_id="acc-a", display_name="A")})
    log_id = _log(isolated_db, account_id="acc-a", action="post_to_group", success=False, content="reschedule me")

    resp = client.post("/admin/reports/reschedule-confirm", data={
        "log_id": str(log_id), "scheduled_at": "2026-12-01T00:00:00+00:00",
    })
    assert resp.status_code in (200, 303)
    pending = schedule_store.list_pending()
    assert len(pending) == 1
    assert pending[0].content == "reschedule me"
    assert pending[0].account_id == "acc-a"


def test_reschedule_confirm_rejects_a_successful_row(client, isolated_db):
    log_id = _log(isolated_db, success=True)
    resp = client.post("/admin/reports/reschedule-confirm", data={
        "log_id": str(log_id), "scheduled_at": "2026-12-01T00:00:00+00:00",
    })
    assert resp.status_code in (200, 303)
    assert len(schedule_store.list_pending()) == 0
