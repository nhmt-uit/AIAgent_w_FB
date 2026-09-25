"""
HTTP-level tests for /admin/post (2026-09-25 test-coverage plan, Phase
4) — the manual post composer, which creates ScheduledTask entries in
schedule_store.PENDING_DIR (never posts directly). Same "minimal FastAPI
app" pattern as the other admin.py HTTP test files.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

import human_bot.schedule_store as schedule_store
from human_bot.admin import NotLoggedIn, router as admin_router


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
def client(isolated_runtime_config, isolated_schedule_dirs, isolated_accounts_dir, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return TestClient(_make_test_app(), follow_redirects=False)


def test_post_page_renders(client):
    resp = client.get("/admin/post")
    assert resp.status_code == 200


# --- schedule-profile ---

def test_schedule_profile_creates_pending_task(client):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = client.post("/admin/post/schedule-profile", data={
        "account_id": "acc-a", "content": "hello profile", "scheduled_at": future, "audience": "friends",
    })
    assert resp.status_code == 303
    assert "scheduled=1" in resp.headers["location"]
    pending = schedule_store.list_pending()
    assert len(pending) == 1
    assert pending[0].action == "post_to_own_profile"
    assert pending[0].account_id == "acc-a"
    assert pending[0].content == "hello profile"
    assert pending[0].audience == "friends"


def test_schedule_profile_rejects_blank_content(client):
    resp = client.post("/admin/post/schedule-profile", data={"account_id": "acc-a", "content": "", "scheduled_at": ""})
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert schedule_store.list_pending() == []


def test_schedule_profile_invalid_audience_falls_back_to_public(client):
    resp = client.post("/admin/post/schedule-profile", data={
        "account_id": "acc-a", "content": "x", "scheduled_at": "", "audience": "not-a-real-value",
    })
    assert resp.status_code == 303
    assert schedule_store.list_pending()[0].audience == "public"


def test_schedule_profile_blank_scheduled_at_means_now(client):
    before = datetime.now(timezone.utc)
    resp = client.post("/admin/post/schedule-profile", data={"account_id": "acc-a", "content": "x", "scheduled_at": ""})
    assert resp.status_code == 303
    scheduled_at = datetime.fromisoformat(schedule_store.list_pending()[0].scheduled_at)
    assert abs((scheduled_at - before).total_seconds()) < 5


def test_schedule_profile_invalid_scheduled_at_is_rejected(client):
    resp = client.post("/admin/post/schedule-profile", data={
        "account_id": "acc-a", "content": "x", "scheduled_at": "not-a-real-date",
    })
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert schedule_store.list_pending() == []


# --- schedule-groups ---

def test_schedule_groups_creates_one_task_per_content_group_pair(client):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = client.post("/admin/post/schedule-groups", data={
        "account_id": "acc-a", "start_at": future,
        "content_0": "block one", "groups_0": ["https://x/g1", "https://x/g2"],
    })
    assert resp.status_code == 303
    assert "scheduled=2" in resp.headers["location"]
    pending = schedule_store.list_pending()
    assert len(pending) == 2
    assert {t.target_url for t in pending} == {"https://x/g1", "https://x/g2"}
    assert all(t.action == "post_to_group" and t.content == "block one" for t in pending)


def test_schedule_groups_skips_blocks_with_no_groups_selected(client):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = client.post("/admin/post/schedule-groups", data={
        "account_id": "acc-a", "start_at": future, "content_0": "no groups picked",
    })
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert schedule_store.list_pending() == []


def test_schedule_groups_rejects_invalid_start_at(client):
    resp = client.post("/admin/post/schedule-groups", data={
        "account_id": "acc-a", "start_at": "not-a-date", "content_0": "x", "groups_0": ["https://x/1"],
    })
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_schedule_groups_spaces_out_multiple_groups_over_time(client):
    """Each successive group in the broadcast gets a LATER scheduled_at
    than the last (never a burst) — see post_schedule_groups()'s own
    pacing loop via apply_quiet_hours()/post_gap_min/max_minutes."""
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    client.post("/admin/post/schedule-groups", data={
        "account_id": "acc-a", "start_at": future,
        "content_0": "x", "groups_0": ["https://x/g1", "https://x/g2", "https://x/g3"],
    })
    pending = sorted(schedule_store.list_pending(), key=lambda t: t.scheduled_at)
    assert len(pending) == 3
    times = [datetime.fromisoformat(t.scheduled_at) for t in pending]
    assert times[0] < times[1] < times[2]


# --- schedule-comment ---

def test_schedule_comment_on_group_url_uses_group_action(client):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = client.post("/admin/post/schedule-comment", data={
        "account_id": "acc-a", "target_url": "https://www.facebook.com/groups/123/posts/456",
        "content": "nice post", "scheduled_at": future,
    })
    assert resp.status_code == 303
    task = schedule_store.list_pending()[0]
    assert task.action == "comment_on_group_post"
    assert task.content == "nice post"


def test_schedule_comment_on_friend_url_uses_friend_action(client):
    future = (datetime.now(timezone.utc) + timedelta(hours=1)).isoformat()
    resp = client.post("/admin/post/schedule-comment", data={
        "account_id": "acc-a", "target_url": "https://www.facebook.com/someone/posts/456",
        "content": "nice post", "scheduled_at": future,
    })
    assert resp.status_code == 303
    task = schedule_store.list_pending()[0]
    assert task.action == "comment_on_friend_post"


def test_schedule_comment_rejects_missing_url_or_content(client):
    resp = client.post("/admin/post/schedule-comment", data={"account_id": "acc-a", "target_url": "", "content": "x"})
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert schedule_store.list_pending() == []


# --- retry_of_log_id threading (all 3 compose forms) ---

def test_schedule_profile_threads_retry_of_log_id(client):
    resp = client.post("/admin/post/schedule-profile", data={
        "account_id": "acc-a", "content": "x", "scheduled_at": "", "retry_of_log_id": "42",
    })
    assert resp.status_code == 303
    assert schedule_store.list_pending()[0].retry_of_log_id == 42


def test_schedule_profile_invalid_retry_of_log_id_becomes_none(client):
    resp = client.post("/admin/post/schedule-profile", data={
        "account_id": "acc-a", "content": "x", "scheduled_at": "", "retry_of_log_id": "not-a-number",
    })
    assert resp.status_code == 303
    assert schedule_store.list_pending()[0].retry_of_log_id is None
