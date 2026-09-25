"""
HTTP-level tests for /admin/groups (2026-09-25 test-coverage plan,
Phase 4) — per-account joined-group CRUD, backing the side-B data-sync
poller's broadcast list. Same "minimal FastAPI app" pattern as the other
admin.py HTTP test files.
"""
from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from human_bot.admin import NotLoggedIn, router as admin_router
from human_bot.runtime_config import get_joined_groups


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
def client(isolated_runtime_config, isolated_accounts_dir, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return TestClient(_make_test_app(), follow_redirects=False)


def test_groups_page_renders_with_no_accounts(client):
    resp = client.get("/admin/groups")
    assert resp.status_code == 200


def test_add_group_persists_it(client):
    resp = client.post("/admin/groups/add", data={
        "account_id": "acc-a", "name": "IT Jobs", "url": "https://www.facebook.com/groups/12345",
    })
    assert resp.status_code == 303
    assert "saved=1" in resp.headers["location"]
    groups = get_joined_groups("acc-a")
    assert len(groups) == 1
    assert groups[0].name == "IT Jobs"
    assert groups[0].url == "https://www.facebook.com/groups/12345"


def test_add_group_rejects_blank_url(client):
    resp = client.post("/admin/groups/add", data={"account_id": "acc-a", "name": "x", "url": ""})
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]
    assert get_joined_groups("acc-a") == []


def test_update_group_keeps_same_id(client):
    client.post("/admin/groups/add", data={"account_id": "acc-a", "name": "Old", "url": "https://x/1"})
    group_id = get_joined_groups("acc-a")[0].id

    resp = client.post("/admin/groups/update", data={
        "account_id": "acc-a", "group_id": group_id, "name": "New", "url": "https://x/2",
    })
    assert resp.status_code == 303
    groups = get_joined_groups("acc-a")
    assert len(groups) == 1
    assert groups[0].id == group_id  # editing, not replacing
    assert groups[0].name == "New"
    assert groups[0].url == "https://x/2"


def test_update_group_missing_group_id_is_rejected(client):
    resp = client.post("/admin/groups/update", data={"account_id": "acc-a", "group_id": "", "name": "x", "url": "https://x/1"})
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_update_nonexistent_group_is_rejected(client):
    resp = client.post("/admin/groups/update", data={
        "account_id": "acc-a", "group_id": "nonexistent", "name": "x", "url": "https://x/1",
    })
    assert resp.status_code == 303
    assert "error=" in resp.headers["location"]


def test_delete_group_removes_only_that_one(client):
    client.post("/admin/groups/add", data={"account_id": "acc-a", "name": "A", "url": "https://x/1"})
    client.post("/admin/groups/add", data={"account_id": "acc-a", "name": "B", "url": "https://x/2"})
    groups = get_joined_groups("acc-a")
    keep_id, remove_id = groups[0].id, groups[1].id

    resp = client.post("/admin/groups/delete", data={"account_id": "acc-a", "group_id": remove_id})
    assert resp.status_code == 303
    remaining = get_joined_groups("acc-a")
    assert len(remaining) == 1
    assert remaining[0].id == keep_id


def test_groups_are_isolated_per_account(client):
    client.post("/admin/groups/add", data={"account_id": "acc-a", "name": "A", "url": "https://x/1"})
    client.post("/admin/groups/add", data={"account_id": "acc-b", "name": "B", "url": "https://x/2"})
    assert len(get_joined_groups("acc-a")) == 1
    assert len(get_joined_groups("acc-b")) == 1
    assert get_joined_groups("acc-a")[0].name == "A"
