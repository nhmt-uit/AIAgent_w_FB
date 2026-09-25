"""
HTTP-level tests for /admin/config (2026-09-25 test-coverage plan,
Phase 4) — behavior/data-sync settings and the AI-provider key card.
Same "minimal FastAPI app" pattern as the other admin.py HTTP test
files.
"""
from __future__ import annotations

from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

from human_bot.admin import NotLoggedIn, router as admin_router
from human_bot.runtime_config import get_mouse_overrides, get_secrets_overrides


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
def client(isolated_runtime_config, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return TestClient(_make_test_app(), follow_redirects=False)


def test_config_page_renders(client):
    resp = client.get("/admin/config")
    assert resp.status_code == 200


def test_config_page_each_tab_renders(client):
    for tab in ("behavior", "sync", "ai"):
        resp = client.get(f"/admin/config?tab={tab}")
        assert resp.status_code == 200


def test_config_save_int_field_survives_as_real_int_not_float(client):
    """Regression test for a real 2026-09-07 bug (see config_save()'s own
    docstring): blindly casting every numeric field to float used to turn
    HumanMouseConfig.min_steps/max_steps (both declared `int`) into
    8 -> 8.0, later crashing human_mouse_move()'s `range(1, steps + 1)`
    with "'float' object cannot be interpreted as an integer" — only on
    the rare click distance that clamps to exactly one of those bounds.
    config_save() now casts each field to whatever type its dataclass
    actually declares."""
    resp = client.post("/admin/config", data={"mouse__min_steps": "12", "mouse__max_steps": "25"})
    assert resp.status_code == 303
    assert "saved=1" in resp.headers["location"]
    overrides = get_mouse_overrides()
    assert overrides["min_steps"] == 12
    assert isinstance(overrides["min_steps"], int)
    assert overrides["max_steps"] == 25
    assert isinstance(overrides["max_steps"], int)


def test_config_save_float_field_stays_float(client):
    from human_bot.runtime_config import get_pacing_overrides
    resp = client.post("/admin/config", data={"pacing__page_load_pause_min_ms": "1234.5"})
    assert resp.status_code == 303
    overrides = get_pacing_overrides()
    assert overrides["page_load_pause_min_ms"] == 1234.5


def test_config_save_bool_field_toggle(client):
    from human_bot.runtime_config import get_scheduling_overrides
    resp = client.post("/admin/config", data={"scheduling__auto_fire_enabled": "true"})
    assert resp.status_code == 303
    assert get_scheduling_overrides()["auto_fire_enabled"] is True

    # Unchecked checkboxes simply aren't sent in the form at all — must
    # be correctly interpreted as False, not left untouched/ignored.
    resp2 = client.post("/admin/config", data={})
    assert resp2.status_code == 303
    assert get_scheduling_overrides()["auto_fire_enabled"] is False


def test_config_save_blank_numeric_field_does_not_crash_or_zero_out(client):
    """A blank field is simply left out of THIS submission's saved values
    (not cast to 0) — verified within one request. NOTE: config_save()
    saves each section wholesale (_save_overrides() replaces the whole
    section — same "REPLACES, not merge" rule as every other
    save_*_overrides() in this project), so this does NOT mean a blank
    field survives an unrelated LATER, separate submission — the real
    admin page always resubmits every field's current value together
    (see config_form()'s render_rows(), value=current-or-default), which
    is what actually keeps this safe in practice. A test sending only
    one field per request (unlike the real page) is not representative
    of a second submission's effect on the first's fields."""
    resp = client.post("/admin/config", data={"mouse__min_steps": "9", "mouse__max_steps": ""})
    assert resp.status_code == 303
    overrides = get_mouse_overrides()
    assert overrides["min_steps"] == 9
    assert "max_steps" not in overrides  # left out, not coerced to 0


# --- AI provider key card ---

def test_ai_provider_save_persists_key_and_never_echoes_it_back_in_html(client):
    resp = client.post("/admin/config/ai-provider", data={
        "ai_provider": "anthropic", "anthropic_api_key": "sk-ant-supersecrettoken1234",
    })
    assert resp.status_code == 200
    assert get_secrets_overrides()["anthropic_api_key"] == "sk-ant-supersecrettoken1234"
    # The raw key must never appear anywhere in the response HTML — only
    # the masked version (_mask_api_key: first 7 chars + "..." + last 4)
    # in the status badge.
    assert "sk-ant-supersecrettoken1234" not in resp.text
    assert "sk-ant-...1234" in resp.text


def test_ai_provider_save_blank_key_is_rejected_and_saves_nothing(client):
    """2026-09-25 fix (owner-confirmed design after a bug report): there
    is no "leave blank to keep the current key" partial-edit mode — every
    save must supply provider + model + key together as a complete set.
    A blank key for the ACTIVE provider is rejected outright (error,
    nothing saved), rather than the old behavior of silently wiping it."""
    client.post("/admin/config/ai-provider", data={"ai_provider": "anthropic", "anthropic_api_key": "sk-ant-original"})
    resp = client.post("/admin/config/ai-provider", data={"ai_provider": "anthropic", "anthropic_api_key": ""})
    assert resp.status_code == 200
    assert "Cần nhập API key" in resp.text
    # Rejected — the previously saved key must survive untouched.
    assert get_secrets_overrides()["anthropic_api_key"] == "sk-ant-original"


def test_ai_provider_save_switching_provider_drops_the_previous_ones_key(client):
    """Owner-confirmed intended design (2026-09-25): only ONE provider's
    key is ever "active" at a time — switching to and saving a different
    provider is meant to replace the whole secrets section, so the
    previous provider's key is expected to disappear. Not a bug."""
    client.post("/admin/config/ai-provider", data={"ai_provider": "openai", "openai_api_key": "sk-openai-original"})
    assert get_secrets_overrides()["openai_api_key"] == "sk-openai-original"

    client.post("/admin/config/ai-provider", data={"ai_provider": "anthropic", "anthropic_api_key": "sk-ant-new"})
    assert "openai_api_key" not in get_secrets_overrides()
    assert get_secrets_overrides()["anthropic_api_key"] == "sk-ant-new"


def test_ai_provider_save_rejects_unknown_provider_falls_back_to_anthropic(client):
    resp = client.post("/admin/config/ai-provider", data={"ai_provider": "not-a-real-provider", "anthropic_api_key": "sk-ant-x"})
    assert resp.status_code == 200
    assert get_secrets_overrides()["ai_provider"] == "anthropic"


def test_ai_provider_clear_key_removes_it(client):
    client.post("/admin/config/ai-provider", data={"ai_provider": "anthropic", "anthropic_api_key": "sk-ant-original"})
    resp = client.post("/admin/config/ai-provider/clear-key", data={"provider": "anthropic"})
    assert resp.status_code == 200
    assert get_secrets_overrides()["anthropic_api_key"] == ""
    assert "sk-ant-original" not in resp.text


def test_ai_provider_clear_key_preserves_provider_and_model(client):
    """2026-09-25 fix (real bug, found in a final review pass): clear-key
    used to call save_secrets_overrides() with ONLY the key field, which
    (being a REPLACE not a merge) silently wiped ai_provider and the
    active provider's model/base_url too. Now a proper read-merge-write —
    only the key field itself should change."""
    client.post("/admin/config/ai-provider", data={
        "ai_provider": "anthropic", "anthropic_api_key": "sk-ant-original", "anthropic_model": "claude-opus-4-5",
    })
    client.post("/admin/config/ai-provider/clear-key", data={"provider": "anthropic"})
    overrides = get_secrets_overrides()
    assert overrides["anthropic_api_key"] == ""
    assert overrides["ai_provider"] == "anthropic"
    assert overrides["anthropic_model"] == "claude-opus-4-5"
