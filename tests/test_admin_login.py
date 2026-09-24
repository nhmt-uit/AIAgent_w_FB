"""
HTTP-level tests for /admin's real session-based login (2026-09-24),
replacing the old HTTP Basic Auth. This is a deliberate, narrow exception
to the project's normal "admin.py routes aren't HTTP-tested" convention
(see tests/test_admin.py's own docstring) — auth/session bug classes
(open redirects, stale-session-still-granting-access, role-check
ordering, the login-toggle bypass leaking into the wrong routes) can only
be caught by exercising real requests through the real middleware stack;
no pure-function test on human_bot/runtime_config.py's resolve_login()
etc. (see tests/test_runtime_config.py) can verify that SessionMiddleware
+ NotLoggedIn + its exception handler actually cooperate correctly.

Deliberately builds a MINIMAL FastAPI app (admin_router + the same
SessionMiddleware/NotLoggedIn setup human_bot/service.py uses) instead of
importing human_bot.service.app directly — that module's real `lifespan`
launches real Playwright browsers and starts background network-polling
loops against side B on startup, which must never happen in a test run.
Everything actually being tested here (login, sessions, role gating)
lives entirely in human_bot/admin.py's router, so this is a faithful
subset, not a shortcut around what matters.
"""
from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

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
def client(isolated_runtime_config):
    """`isolated_runtime_config` (tests/conftest.py) keeps every MOD-account
    read/write in this test off the real runtime_config.json — required
    since /admin/mod-users' routes go through human_bot.runtime_config
    directly. `follow_redirects=False` throughout these tests on purpose:
    a 303's Location header (or an HX-Redirect header) IS the behavior
    under test, not something to silently chase through."""
    return TestClient(_make_test_app(), follow_redirects=False)


def _login(client: TestClient, username: str, password: str, next_path: str | None = None) -> object:
    data = {"username": username, "password": password}
    if next_path:
        data["next"] = next_path
    return client.post("/admin/login", data=data)


def test_login_disabled_reaches_every_page_directly(client, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    assert client.get("/admin").status_code == 200
    assert client.get("/admin/mod-users").status_code == 200  # even the ADMIN-only page — no partial protection when off


def test_login_enabled_no_session_redirects_to_login(client, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "boss-pass")
    resp = client.get("/admin")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/login?next=%2Fadmin"


def test_login_enabled_no_session_htmx_gets_hx_redirect_not_303(client, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "boss-pass")
    resp = client.get("/admin", headers={"hx-request": "true"})
    assert resp.status_code == 200
    assert resp.headers["hx-redirect"] == "/admin/login?next=%2Fadmin"


def test_correct_admin_login_reaches_mod_users_page(client, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "boss-pass")
    resp = _login(client, "boss", "boss-pass")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"
    assert client.get("/admin").status_code == 200
    assert client.get("/admin/mod-users").status_code == 200


def test_correct_mod_login_is_blocked_from_mod_users_page(client, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "boss-pass")
    add_resp = _login(client, "boss", "boss-pass")
    assert add_resp.status_code == 303
    modal_or_add = client.post("/admin/mod-users/add", data={
        "username": "mod1", "password": "mod-pass123", "password_confirm": "mod-pass123",
    })
    assert modal_or_add.status_code == 303  # created; plain form post, no hx-request header

    mod_client = TestClient(client.app, follow_redirects=False)
    login_resp = _login(mod_client, "mod1", "mod-pass123")
    assert login_resp.status_code == 303
    assert login_resp.headers["location"] == "/admin"

    assert mod_client.get("/admin").status_code == 200  # full access everywhere else
    forbidden = mod_client.get("/admin/mod-users")
    assert forbidden.status_code == 403


def test_wrong_password_shows_generic_error_redirect(client, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "boss-pass")
    resp = _login(client, "boss", "totally-wrong")
    assert resp.status_code == 303
    assert resp.headers["location"].startswith("/admin/login?")
    assert "error=1" in resp.headers["location"]
    # Still not authenticated afterwards.
    assert client.get("/admin").status_code == 303


def test_deleting_mod_user_revokes_access_on_their_very_next_request(client, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "boss-pass")
    _login(client, "boss", "boss-pass")
    client.post("/admin/mod-users/add", data={
        "username": "mod1", "password": "mod-pass123", "password_confirm": "mod-pass123",
    })

    mod_client = TestClient(client.app, follow_redirects=False)
    _login(mod_client, "mod1", "mod-pass123")
    assert mod_client.get("/admin").status_code == 200  # session works before deletion

    del_resp = client.post("/admin/mod-users/mod1/delete")
    assert del_resp.status_code == 303

    # The MOD's session cookie is unchanged, but the account behind it is
    # gone — their very next request must be treated as logged-out, not
    # wait for the cookie to expire.
    assert mod_client.get("/admin").status_code == 303


def test_edit_mod_password_non_htmx_falls_back_to_redirect_not_bare_fragment(client, monkeypatch):
    """2026-09-24 bugfix: this route used to always return the bare
    #mod-users-content HTML fragment, even for a plain (non-htmx) form
    submit — unlike every other mutating route on this page, which falls
    back to a full-page RedirectResponse so the form still works with JS
    disabled."""
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "boss-pass")
    _login(client, "boss", "boss-pass")
    client.post("/admin/mod-users/add", data={
        "username": "mod1", "password": "mod-pass123", "password_confirm": "mod-pass123",
    })

    ok_resp = client.post("/admin/mod-users/mod1/edit-password", data={
        "new_password": "new-pass456", "new_password_confirm": "new-pass456",
    })
    assert ok_resp.status_code == 303
    assert ok_resp.headers["location"] == "/admin/mod-users?saved=1"

    err_resp = client.post("/admin/mod-users/mod1/edit-password", data={
        "new_password": "short", "new_password_confirm": "short",
    })
    assert err_resp.status_code == 303
    assert err_resp.headers["location"].startswith("/admin/mod-users?error=")


def test_next_param_pointing_off_site_is_ignored(client, monkeypatch):
    monkeypatch.setenv("ADMIN_USERNAME", "boss")
    monkeypatch.setenv("ADMIN_PASSWORD", "boss-pass")
    resp = _login(client, "boss", "boss-pass", next_path="https://evil.example/steal")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin"  # fell back to the safe default, not the attacker-supplied URL
