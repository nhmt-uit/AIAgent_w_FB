"""
HTTP-level tests for "Tài khoản Telegram" — a sub-tab of /admin/accounts
(2026-10-05, moved there from its own top-level /admin/telegram page per
owner request) — the admin-managed list of who receives
human_bot/telegram_notify.py's alerts and can query the 2-way health bot,
replacing the original single hardcoded TELEGRAM_CHAT_ID env var. Same
"minimal FastAPI app" pattern as the other admin.py HTTP test files.
"""
from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from human_bot import telegram_notify
from human_bot.admin import NotLoggedIn, router as admin_router
from human_bot.runtime_config import add_telegram_recipient, get_telegram_recipients


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


def test_telegram_tab_renders_with_no_recipients(client):
    resp = client.get("/admin/accounts?tab=telegram")
    assert resp.status_code == 200
    assert "Chưa có ai nhận báo động Telegram" in resp.text


def test_telegram_tab_lists_a_registered_recipient(client):
    add_telegram_recipient("931000937", "Tu")
    resp = client.get("/admin/accounts?tab=telegram")
    assert resp.status_code == 200
    assert "931000937" in resp.text
    assert "Tu" in resp.text


def test_telegram_tab_button_present_on_accounts_page(client):
    resp = client.get("/admin/accounts")
    assert "Tài khoản Telegram" in resp.text
    assert 'data-tab-target="tab-telegram"' in resp.text


def test_telegram_tab_marked_active_when_requested(client):
    resp = client.get("/admin/accounts?tab=telegram")
    # The "📨 Tài khoản Telegram" tab button itself gets the active class
    # when tab=telegram is requested server-side (client JS only toggles
    # it afterward on click — the initial render must already be correct
    # for someone following a non-htmx redirect straight to this tab).
    assert 'class="tab-btn active" data-tab-target="tab-telegram"' in resp.text


def test_telegram_add_valid_recipient(client):
    resp = client.post("/admin/accounts/telegram/add", data={"chat_id": "931000937", "label": "Tu"})
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/accounts?tab=telegram&saved=1"
    assert get_telegram_recipients() == [{"chat_id": "931000937", "label": "Tu"}]


def test_telegram_add_blank_chat_id_rejected_and_saves_nothing(client):
    resp = client.post("/admin/accounts/telegram/add", data={"chat_id": "", "label": "Tu"})
    assert resp.status_code == 303
    assert "tab=telegram" in resp.headers["location"]
    assert "telegram_error=" in resp.headers["location"]
    assert get_telegram_recipients() == []


def test_telegram_add_non_numeric_chat_id_rejected(client):
    resp = client.post("/admin/accounts/telegram/add", data={"chat_id": "not-a-number", "label": "Tu"})
    assert resp.status_code == 303
    assert "telegram_error=" in resp.headers["location"]
    assert get_telegram_recipients() == []


def test_telegram_add_duplicate_chat_id_rejected(client):
    add_telegram_recipient("931000937", "Tu")
    resp = client.post("/admin/accounts/telegram/add", data={"chat_id": "931000937", "label": "Tu lần 2"})
    assert resp.status_code == 303
    assert "telegram_error=" in resp.headers["location"]
    assert get_telegram_recipients() == [{"chat_id": "931000937", "label": "Tu"}]


def test_telegram_add_htmx_error_preserves_typed_values(client):
    resp = client.post(
        "/admin/accounts/telegram/add", data={"chat_id": "not-a-number", "label": "Bryan"},
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert 'value="not-a-number"' in resp.text
    assert 'value="Bryan"' in resp.text


def test_telegram_add_redirect_error_shows_on_telegram_tab_not_accounts_tab(client):
    """Regression guard: the telegram tab's own error must use a
    DIFFERENT query param (`telegram_error`) than the accounts tab's
    `error` — reusing `error` would render the message inside the
    accounts panel's HTML, which is hidden while tab=telegram is active,
    making the error invisible to the user."""
    resp = client.post("/admin/accounts/telegram/add", data={"chat_id": "not-a-number", "label": "Tu"})
    redirect_target = resp.headers["location"]
    page = client.get(redirect_target)
    # The error renders INSIDE the (visible) telegram tab-panel, not the accounts one.
    telegram_panel_start = page.text.index('id="tab-telegram"')
    accounts_panel_start = page.text.index('id="tab-accounts"')
    error_pos = page.text.index("Chat ID phải là số")
    assert telegram_panel_start < error_pos
    assert not (accounts_panel_start < error_pos < page.text.index('id="tab-sync"'))


def test_telegram_delete(client):
    add_telegram_recipient("931000937", "Tu")
    resp = client.post("/admin/accounts/telegram/931000937/delete")
    assert resp.status_code == 303
    assert resp.headers["location"] == "/admin/accounts?tab=telegram&saved=1"
    assert get_telegram_recipients() == []


def test_telegram_delete_unknown_chat_id_is_a_noop(client):
    resp = client.post("/admin/accounts/telegram/never-existed/delete")
    assert resp.status_code == 303
    assert get_telegram_recipients() == []


def test_telegram_test_button_sends_to_exactly_that_chat_id(client, monkeypatch):
    add_telegram_recipient("931000937", "Tu")
    sent = []

    async def fake_send_message_to(chat_id, text, *, silent=False):
        sent.append(chat_id)
        return True

    monkeypatch.setattr(telegram_notify, "send_message_to", fake_send_message_to)
    resp = client.post("/admin/accounts/telegram/931000937/test")

    assert resp.status_code == 303
    assert sent == ["931000937"]
    assert "tested=931000937" in resp.headers["location"]
    assert "tab=telegram" in resp.headers["location"]


def test_telegram_test_button_reports_failure_not_a_false_success(client, monkeypatch):
    """Regression test (self-review follow-up): send_message_to() is
    best-effort/never-raises by design, so this route must check its
    RETURN VALUE (not just "it didn't raise") — otherwise the one button
    whose entire purpose is verifying a chat_id works would report
    success every single time it actually failed (wrong chat_id,
    revoked token, feature switched off)."""
    add_telegram_recipient("931000937", "Tu")

    async def fake_send_message_to(chat_id, text, *, silent=False):
        return False  # e.g. Telegram returned a non-200, or not configured

    monkeypatch.setattr(telegram_notify, "send_message_to", fake_send_message_to)
    resp = client.post("/admin/accounts/telegram/931000937/test")

    assert resp.status_code == 303
    assert "test_failed=931000937" in resp.headers["location"]
    assert "tested=" not in resp.headers["location"]


def test_old_standalone_telegram_page_no_longer_exists(client):
    """The top-level /admin/telegram page was removed (moved into
    /admin/accounts's "Tài khoản Telegram" tab per owner request)."""
    resp = client.get("/admin/telegram")
    assert resp.status_code == 404


# --- "Người mới nhắn bot, chưa thêm" (pending senders, 2026-10-05 follow-up) ---
# Owner: a /admin-only user has no way to know TELEGRAM_BOT_TOKEN to
# hand-build a getUpdates URL — these replace that instruction with a
# one-click "➕ Thêm" sourced from telegram_notify.record_pending_sender().

def test_pending_sender_shown_on_telegram_tab(client):
    telegram_notify.record_pending_sender("555", "Bryan")
    resp = client.get("/admin/accounts?tab=telegram")
    assert "555" in resp.text
    assert "Bryan" in resp.text
    assert "🔔" in resp.text


def test_no_pending_senders_section_when_none_recorded(client):
    resp = client.get("/admin/accounts?tab=telegram")
    assert "🔔" not in resp.text


def test_pending_sender_one_click_add(client):
    telegram_notify.record_pending_sender("555", "Bryan")
    resp = client.post("/admin/accounts/telegram/add", data={"chat_id": "555", "label": "Bryan"})
    assert resp.status_code == 303
    assert get_telegram_recipients() == [{"chat_id": "555", "label": "Bryan"}]


def test_adding_a_pending_sender_clears_it_from_the_pending_list(client):
    """Regression guard: once added, they must stop showing in the
    "chưa được thêm" section too — otherwise the same person would keep
    offering a redundant "➕ Thêm" after they're already a recipient."""
    telegram_notify.record_pending_sender("555", "Bryan")
    client.post("/admin/accounts/telegram/add", data={"chat_id": "555", "label": "Bryan"})

    assert telegram_notify.get_pending_senders() == {}
    resp = client.get("/admin/accounts?tab=telegram")
    assert "🔔" not in resp.text


def test_pending_sender_already_registered_is_not_shown_as_pending(client):
    """Defensive: a stale pending entry for someone who was already
    added by hand (not via the one-click button) must not re-offer
    adding them again."""
    add_telegram_recipient("555", "Bryan")
    telegram_notify.record_pending_sender("555", "Bryan")  # e.g. they messaged again after being added
    resp = client.get("/admin/accounts?tab=telegram")
    assert "🔔" not in resp.text


def test_telegram_tab_help_text_never_mentions_the_bot_token(client):
    """Regression guard for the whole point of this feature: a /admin
    user (who may not have access to .env) must never be told to go
    read TELEGRAM_BOT_TOKEN or hand-build a getUpdates URL."""
    resp = client.get("/admin/accounts?tab=telegram")
    assert "TOKEN" not in resp.text
    assert "getUpdates" not in resp.text


# --- Manual-add modal (owner follow-up, 2026-10-05: "form bên dưới cần ---
# --- bấm nút để hiện modal") ------------------------------------------------

def test_manual_add_is_a_button_not_an_inline_form(client):
    """The Chat ID/Tên gợi nhớ inputs must NOT be sitting directly on the
    page — only a button that opens them in a modal."""
    resp = client.get("/admin/accounts?tab=telegram")
    assert 'name="chat_id"' not in resp.text  # no bare input on the page itself
    assert 'hx-get="/admin/accounts/telegram/add-modal"' in resp.text
    assert "➕ Thêm thủ công" in resp.text


def test_add_modal_route_renders_the_form(client):
    resp = client.get("/admin/accounts/telegram/add-modal")
    assert resp.status_code == 200
    assert 'name="chat_id"' in resp.text
    assert 'name="label"' in resp.text
    assert 'hx-target="#modal-root"' in resp.text


def test_pending_senders_one_click_button_also_targets_modal_root(client):
    """The pending-sender one-click "➕ Thêm" button must post to
    #modal-root too (not directly to the list content) — this is what
    lets a rare validation error (e.g. a race with someone else adding
    that same chat_id first) pop up as a small modal instead of landing
    in the wrong place."""
    telegram_notify.record_pending_sender("555", "Bryan")
    resp = client.get("/admin/accounts?tab=telegram")
    pending_form_start = resp.text.index('<input type="hidden" name="chat_id" value="555">')
    pending_form_html = resp.text[max(0, pending_form_start - 300):pending_form_start]
    assert 'hx-target="#modal-root"' in pending_form_html
    assert 'hx-target="#telegram-recipients-content"' not in pending_form_html


def test_add_error_via_htmx_renders_the_modal_not_the_list(client):
    resp = client.post(
        "/admin/accounts/telegram/add", data={"chat_id": "not-a-number", "label": "Tu"},
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "modal-backdrop" in resp.text
    assert "Chat ID phải là số" in resp.text


def test_add_success_via_htmx_closes_the_modal_and_refreshes_the_list(client):
    """The success response must out-of-band-swap the list (so it shows
    the newly added recipient) while leaving #modal-root's own content
    empty — the same trick /admin/mod-users's add flow already uses to
    close a modal with no extra JS."""
    resp = client.post(
        "/admin/accounts/telegram/add", data={"chat_id": "555", "label": "Tu"},
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert 'id="telegram-recipients-content" hx-swap-oob="true"' in resp.text
    assert "555" in resp.text
    assert "modal-backdrop" not in resp.text  # no modal markup in the (sole) response


# --- Bot link in the help text (owner follow-up, 2026-10-05) ---------------

def test_help_text_shows_a_clickable_bot_link_when_username_cached(client):
    telegram_notify._cached_bot_username = "AIAgentSupport_bot"
    resp = client.get("/admin/accounts?tab=telegram")
    assert 'href="https://t.me/AIAgentSupport_bot"' in resp.text
    assert "@AIAgentSupport_bot" in resp.text


def test_help_text_falls_back_to_plain_text_when_username_not_cached(client):
    resp = client.get("/admin/accounts?tab=telegram")
    assert "https://t.me/" not in resp.text
    assert "bot Telegram của hệ thống" in resp.text


def test_add_modal_also_shows_the_bot_link(client):
    telegram_notify._cached_bot_username = "AIAgentSupport_bot"
    resp = client.get("/admin/accounts/telegram/add-modal")
    assert 'href="https://t.me/AIAgentSupport_bot"' in resp.text


# --- "saved" must not leak into the (hidden) accounts tab panel (self-review follow-up) ---

def test_telegram_tab_saved_redirect_does_not_show_a_flash_on_the_accounts_panel(client):
    """Regression test: a Telegram-tab action (add/delete/test) redirects
    to /admin/accounts?tab=telegram&saved=1 — `saved` is a generic query
    param also read by the accounts tab's OWN flash. Since tab-switching
    is pure client-side (see initTabs() — no refetch on click), an
    ungated `saved` would bake a stale "✅ Đã lưu." into the (hidden)
    accounts panel's HTML, surfacing the moment someone later clicks
    back to that tab even though no account was actually changed."""
    resp = client.get("/admin/accounts?tab=telegram&saved=1")
    accounts_panel_start = resp.text.index('id="tab-accounts"')
    sync_panel_start = resp.text.index('id="tab-sync"')
    accounts_panel_html = resp.text[accounts_panel_start:sync_panel_start]
    assert "Đã lưu" not in accounts_panel_html


def test_accounts_tab_saved_redirect_still_shows_its_own_flash(client):
    """The fix for the leak above must not also break the accounts tab's
    own legitimate flash when IT is the one that saved something."""
    resp = client.get("/admin/accounts?saved=1")  # tab defaults to "accounts"
    accounts_panel_start = resp.text.index('id="tab-accounts"')
    sync_panel_start = resp.text.index('id="tab-sync"')
    accounts_panel_html = resp.text[accounts_panel_start:sync_panel_start]
    assert "Đã lưu" in accounts_panel_html


# --- Self-heal retry for the bot-username lookup (self-review follow-up) ---

async def test_health_check_loop_retries_bot_username_lookup_while_uncached(monkeypatch, isolated_runtime_config):
    """refresh_bot_username() is fired once, in the background, at
    service startup — a transient failure there must not leave the
    admin UI's bot link stuck on its plain-text fallback forever.
    _telegram_health_check_loop() retries it on its own 6h cadence as
    long as it's still uncached."""
    import asyncio as asyncio_module
    import human_bot.service as svc

    monkeypatch.setattr(svc, "get_all_accounts", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})
    calls = {"n": 0}

    async def fake_refresh():
        calls["n"] += 1

    monkeypatch.setattr(telegram_notify, "refresh_bot_username", fake_refresh)

    async def fake_sleep(seconds):
        raise asyncio_module.CancelledError

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio_module.CancelledError):
        await svc._telegram_health_check_loop()

    assert calls["n"] == 1


async def test_health_check_loop_does_not_retry_once_username_is_cached(monkeypatch, isolated_runtime_config):
    import asyncio as asyncio_module
    import human_bot.service as svc

    telegram_notify._cached_bot_username = "AIAgentSupport_bot"
    monkeypatch.setattr(svc, "get_all_accounts", lambda: {})
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: {})

    async def fail_if_called():
        raise AssertionError("must not re-fetch once the username is already cached")

    monkeypatch.setattr(telegram_notify, "refresh_bot_username", fail_if_called)

    async def fake_sleep(seconds):
        raise asyncio_module.CancelledError

    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio_module.CancelledError):
        await svc._telegram_health_check_loop()


# --- Sửa "tên gợi nhớ" (owner follow-up, 2026-10-05) -------------------------

def test_edit_modal_route_prefills_the_current_label(client):
    add_telegram_recipient("931000937", "Tu")
    resp = client.get("/admin/accounts/telegram/931000937/edit-modal")
    assert resp.status_code == 200
    assert 'value="Tu"' in resp.text
    assert "931000937" in resp.text  # shown as read-only context, not an editable input
    assert 'name="chat_id"' not in resp.text  # chat_id itself is never editable here


def test_edit_label_renames_it(client):
    add_telegram_recipient("931000937", "Tu")
    resp = client.post("/admin/accounts/telegram/931000937/edit", data={"label": "Tu (owner)"})
    assert resp.status_code == 303
    assert get_telegram_recipients() == [{"chat_id": "931000937", "label": "Tu (owner)"}]


def test_edit_label_via_htmx_closes_modal_and_refreshes_the_list(client):
    add_telegram_recipient("931000937", "Tu")
    resp = client.post(
        "/admin/accounts/telegram/931000937/edit", data={"label": "Tu (owner)"},
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert 'id="telegram-recipients-content" hx-swap-oob="true"' in resp.text
    assert "Tu (owner)" in resp.text
    assert "modal-backdrop" not in resp.text


def test_edit_label_unknown_chat_id_shows_error_in_modal_via_htmx(client):
    resp = client.post(
        "/admin/accounts/telegram/never-existed/edit", data={"label": "X"},
        headers={"hx-request": "true"},
    )
    assert resp.status_code == 200
    assert "modal-backdrop" in resp.text
    assert "Không tìm thấy" in resp.text


def test_edit_button_present_on_each_recipient_row(client):
    add_telegram_recipient("931000937", "Tu")
    resp = client.get("/admin/accounts?tab=telegram")
    assert 'hx-get="/admin/accounts/telegram/931000937/edit-modal"' in resp.text
    assert "✏️ Sửa" in resp.text


# --- "Thêm thủ công" moved to the top (owner follow-up, 2026-10-05) --------

def test_manual_add_button_appears_before_the_recipients_table(client):
    add_telegram_recipient("931000937", "Tu")
    resp = client.get("/admin/accounts?tab=telegram")
    telegram_panel_start = resp.text.index('id="tab-telegram"')
    telegram_panel_html = resp.text[telegram_panel_start:]
    add_btn_pos = telegram_panel_html.index("➕ Thêm thủ công")
    table_pos = telegram_panel_html.index('<table class="data-table">')
    assert add_btn_pos < table_pos


def test_manual_add_button_appears_before_the_pending_senders_section(client):
    telegram_notify.record_pending_sender("555", "Bryan")
    resp = client.get("/admin/accounts?tab=telegram")
    add_btn_pos = resp.text.index("➕ Thêm thủ công")
    pending_pos = resp.text.index("🔔")
    assert add_btn_pos < pending_pos
