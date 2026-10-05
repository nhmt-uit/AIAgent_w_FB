"""
HTTP-level tests for GET /admin (admin_home()) — the "sức khoẻ tài khoản"
card added 2026-10-02 (admin-UI improvement idea #3, see tasks.md). Same
"minimal FastAPI app" pattern as the other admin.py HTTP test files.
isolated_accounts_dir also covers bootstrap_login_sessions.ACCOUNTS_DIR
(get_session_expiry() reads storage_state.json from there) — see its
2026-10-02 docstring update in conftest.py.

human_bot.config.ACCOUNTS always has a hardcoded "tu_iizuki" entry (not
something these tests control), so assertions about one specific
registered account (especially negative "X not in resp.text" ones) are
scoped to that account's own card snippet, not the whole page — tu_iizuki
has no storage_state.json/action_log rows in the isolated fixtures either,
so it always renders its own (unrelated) "chưa có.../không đọc được..."
lines that would otherwise collide with a true assertion about the
account under test.
"""
from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from human_bot import db
from human_bot.admin import NotLoggedIn, router as admin_router
from human_bot.runtime_config import save_registered_account, set_account_paused


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
def client(isolated_runtime_config, isolated_accounts_dir, isolated_db, isolated_sync_status, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return TestClient(_make_test_app(), follow_redirects=False)


def _card_html(resp_text: str, display_name: str) -> str:
    """Isolates one account's health-card snippet — anchored on the
    `<h3>`'s exact markup (not a bare display_name match, which also
    matches the top pause-warning banner's own mention of the same name
    when the account is paused) so assertions don't accidentally match
    the banner OR the always-present hardcoded "tu_iizuki" account's own
    (unrelated) card."""
    anchor = f">{display_name} <span"
    start = resp_text.index(anchor)
    next_card = resp_text.find('<div class="card"', start)
    return resp_text[start:next_card if next_card != -1 else None]


def test_admin_home_renders_ok(client):
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert "Bảng điều khiển" in resp.text


def test_admin_home_shows_active_account_with_no_history_as_neutral(client):
    save_registered_account("acc-a", "Account A")
    resp = client.get("/admin")
    assert resp.status_code == 200
    card = _card_html(resp.text, "Account A")
    assert "🟢 Hoạt động" in card
    assert "Chưa mở phiên trình duyệt nào" in card
    assert "Chưa đồng bộ dữ liệu lần nào" in card
    assert "Chưa có lượt đăng/bình luận thành công nào" in card
    # No storage_state.json saved for this account -> session unreadable.
    assert "Không đọc được phiên đăng nhập" in card


def test_admin_home_paused_account_shows_reason_and_no_silence_warning(client):
    save_registered_account("acc-a", "Account A")
    set_account_paused("acc-a", True, reason="checkpoint thật")
    db.log_action(
        account_id="acc-a", action="post_to_group", success=True,
        created_at="2020-01-01T00:00:00+00:00",  # ancient -> would be "im lặng" if NOT paused
    )
    resp = client.get("/admin")
    assert resp.status_code == 200
    card = _card_html(resp.text, "Account A")
    assert "Tạm dừng" in card
    assert "checkpoint thật" in card
    # Paused already explains the silence — must not ALSO show the "im lặng" warning.
    assert "Im lặng" not in card


def test_admin_home_active_account_silent_over_48h_warns(client):
    from datetime import datetime, timedelta, timezone
    save_registered_account("acc-a", "Account A")
    old = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    db.log_action(account_id="acc-a", action="post_to_group", success=True, created_at=old)
    resp = client.get("/admin")
    assert resp.status_code == 200
    card = _card_html(resp.text, "Account A")
    assert "🟡 Im lặng" in card


def test_admin_home_active_account_recent_success_shows_green(client):
    from datetime import datetime, timezone
    save_registered_account("acc-a", "Account A")
    recent = datetime.now(timezone.utc).isoformat()
    db.log_action(account_id="acc-a", action="post_to_group", success=True, created_at=recent)
    resp = client.get("/admin")
    assert resp.status_code == 200
    card = _card_html(resp.text, "Account A")
    assert "🟢 Thành công gần nhất" in card
    assert "🟡 Im lặng" not in card


def test_admin_home_sync_error_shows_warning(client):
    from human_bot import data_sync
    save_registered_account("acc-a", "Account A")
    data_sync._record_sync_status("acc-a", {
        "last_run_at": "2026-10-02T00:00:00+00:00", "status": "error", "error": "boom",
    })
    resp = client.get("/admin")
    assert resp.status_code == 200
    card = _card_html(resp.text, "Account A")
    assert "🟡 Đồng bộ lỗi" in card


def test_admin_home_orders_paused_account_before_active_account(client):
    """Xấu nhất lên đầu, đúng pattern RPA fleet dashboard đã tham khảo."""
    save_registered_account("acc-healthy", "Healthy Account")
    save_registered_account("acc-paused", "Paused Account")
    set_account_paused("acc-paused", True, reason="test")
    resp = client.get("/admin")
    assert resp.status_code == 200
    assert resp.text.index("Paused Account") < resp.text.index("Healthy Account")


def test_admin_home_session_expiry_reads_real_auth_cookies_only(client, isolated_accounts_dir):
    import json
    save_registered_account("acc-a", "Account A")
    acc_dir = isolated_accounts_dir / "acc-a"
    acc_dir.mkdir(parents=True)
    far_future = 9999999999  # year ~2286, safely "not expiring soon"
    (acc_dir / "storage_state.json").write_text(json.dumps({
        "cookies": [
            {"name": "wd", "domain": ".facebook.com", "expires": 1},  # must be ignored
            {"name": "c_user", "domain": "facebook.com", "expires": far_future},
            {"name": "xs", "domain": "facebook.com", "expires": far_future},
        ],
        "origins": [],
    }), encoding="utf-8")
    resp = client.get("/admin")
    assert resp.status_code == 200
    card = _card_html(resp.text, "Account A")
    assert "phiên đăng nhập còn" in card.lower()
    assert "Không đọc được phiên đăng nhập" not in card
