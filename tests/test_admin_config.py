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
from human_bot.runtime_config import (
    get_mouse_overrides,
    get_data_sync_overrides,
    get_secrets_overrides,
    get_job_post_openers,
    get_contact_cta,
    get_missing_info_suffixes,
    get_candidate_reply_templates,
    get_visa_type_names,
)
from human_bot.content_strategist import (
    _JOB_POST_OPENERS_DEFAULT,
    _CONTACT_CTA_DEFAULT,
    _MISSING_INFO_SUFFIXES_DEFAULT,
    _VISA_TYPE_NAMES_DEFAULT,
)
from human_bot.data_sync import _CANDIDATE_REPLY_TEMPLATES_DEFAULT


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
    for tab in ("behavior", "sync", "ai", "content"):
        resp = client.get(f"/admin/config?tab={tab}")
        assert resp.status_code == 200


def test_config_generic_save_button_hidden_on_content_tab_only(client):
    """Owner-reported 2026-10-01: the "Kho nội dung" tab has its own
    dedicated htmx save button and no dataclass-backed fields of its own
    at all — the generic full-page "Lưu cấu hình" submit (which only ever
    saves _CONFIG_SECTIONS fields) did nothing useful there and just
    confused "which button saves what". Initial server render must hide
    it only for tab=content; "ai" still needs it (its 2 AI on/off
    switches ARE real DataSyncConfig fields saved by that button, only
    the key/model card has its own separate htmx button). The client-side
    JS toggle for switching tabs WITHOUT a page reload isn't covered here
    — pytest doesn't execute browser JS — see initTabs()'s own comment."""
    for tab, expect_hidden in (("behavior", False), ("sync", False), ("ai", False), ("content", True)):
        resp = client.get(f"/admin/config?tab={tab}")
        has_hidden_attr = 'id="config-generic-save-actions" hidden' in resp.text
        assert has_hidden_attr == expect_hidden, f"tab={tab}"


def test_form_actions_hidden_attribute_is_not_overridden_by_display_flex(client):
    """Regression test for the REAL root cause of the bug above surviving
    a server restart (owner-reported 2026-10-01): `.form-actions { display:
    flex }` is an AUTHOR stylesheet rule, which overrides the `hidden`
    attribute's implicit UA-stylesheet `display:none` regardless of
    specificity — so the attribute alone never actually hid the button,
    even though it was correctly present in the HTML the whole time (the
    test above only checked for the attribute string, not real visibility,
    which is why it kept passing while the bug was still live). pytest
    can't render CSS to verify real visibility, so this checks the
    override rule itself is present — same fix pattern `.tab-panel[hidden]`
    already uses elsewhere on this page."""
    resp = client.get("/admin/config?tab=behavior")
    assert ".form-actions[hidden]" in resp.text


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


def test_config_save_int_field_survives_for_a_future_annotations_dataclass_too(client):
    """Regression test for a real incident found live 2026-10-06: the
    2026-09-07 fix above (config_save()'s own docstring) was verified
    against HumanMouseConfig, whose module does NOT use
    `from __future__ import annotations` — so `dataclasses.fields(cls)
    [i].type` really is the `int` class there, and the fix looked
    correct. DataSyncConfig's module DOES use postponed annotations, so
    that same raw `.type` is the STRING "int" instead, silently
    defeating the `is int` check for every one of ITS int fields. The
    very first time anyone saved ANY field in this tab,
    max_overflow_business_days (declared `int`, used in a `range()`
    call) got corrupted to a float and crashed every
    data_sync.sync_all() poll for 5 days straight before anyone noticed.
    Fixed by switching to typing.get_type_hints(), which resolves
    postponed annotations correctly regardless of module style."""
    resp = client.post("/admin/config", data={"data_sync__max_overflow_business_days": "2"})
    assert resp.status_code == 303
    overrides = get_data_sync_overrides()
    assert overrides["max_overflow_business_days"] == 2
    assert isinstance(overrides["max_overflow_business_days"], int)


def test_config_save_job_min_confidence_stays_float(client):
    """job_min_confidence (2026-10-08, /admin/schedule's "Chờ duyệt" tab)
    is a DataSyncConfig field too — same postponed-annotations module as
    max_overflow_business_days above, so this exercises the same
    get_type_hints() fix for a FLOAT field in that module, not just int."""
    resp = client.post("/admin/config", data={"data_sync__job_min_confidence": "0.95"})
    assert resp.status_code == 303
    overrides = get_data_sync_overrides()
    assert overrides["job_min_confidence"] == 0.95
    assert isinstance(overrides["job_min_confidence"], float)


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
    assert get_secrets_overrides().get("anthropic_api_key", "") == ""
    assert "sk-ant-original" not in resp.text


def test_ai_provider_clear_key_reverts_the_whole_bundle_to_default(client):
    """Owner-confirmed design (2026-09-25, after I initially "fixed" this
    the other way and had to reverse it): provider + model + key travel
    together as ONE bundle — clearing the key means abandoning that whole
    custom bundle and going back to the default/.env state (ai_provider
    back to its "anthropic" dataclass default, model blank), not just
    blanking the key while keeping a half-custom provider/model
    selection around. Confirmed with a concrete scenario: switch to
    OpenAI with its own key+model, clear the key, provider must fall
    back to "anthropic" — not stay on "openai" with no key."""
    client.post("/admin/config/ai-provider", data={
        "ai_provider": "openai", "openai_api_key": "sk-openai-original", "openai_model": "gpt-4o",
    })
    client.post("/admin/config/ai-provider/clear-key", data={"provider": "openai"})
    overrides = get_secrets_overrides()
    assert overrides == {}
    from human_bot.runtime_config import get_active_ai_provider_config
    active = get_active_ai_provider_config()
    assert active.provider == "anthropic"
    assert active.model == ""


# --- "Kho nội dung" tab (2026-10-01) -----------------------------------------

_VALID_CONTENT_LIBRARY_FORM = {
    "opener_text_0": "TÌM NHÂN SỰ MỚI",
    "opener_visa_0": "",
    "opener_text_1": "CHỈ DÀNH CHO KỸ SƯ",
    "opener_visa_1": "gijinkoku",
    "cta_0": "Nhắn tin ngay nhé",
    "suffix_0": "hỏi thêm nha",
    "reply_template_0": "Chào {field}{region_clause}, nhắn mình nhé.",
    "visa_code_0": "gijinkoku",
    "visa_names_0": "Kỹ Sư\nGijinkoku",
}


def test_content_library_save_persists_all_five_lists(client):
    resp = client.post("/admin/config/content-library", data=_VALID_CONTENT_LIBRARY_FORM)
    assert resp.status_code == 200
    assert "Đã lưu Kho nội dung" in resp.text

    assert get_job_post_openers([]) == [
        {"text": "TÌM NHÂN SỰ MỚI", "visa_restrictions": []},
        {"text": "CHỈ DÀNH CHO KỸ SƯ", "visa_restrictions": ["gijinkoku"]},
    ]
    assert get_contact_cta([]) == ["Nhắn tin ngay nhé"]
    assert get_missing_info_suffixes([]) == ["hỏi thêm nha"]
    assert get_candidate_reply_templates([]) == ["Chào {field}{region_clause}, nhắn mình nhé."]
    assert get_visa_type_names({}) == {"gijinkoku": ["Kỹ Sư", "Gijinkoku"]}


def test_content_library_opener_restricted_to_multiple_visas(client):
    """2026-10-01, owner's request: a native <select multiple> submits one
    value per selected <option> under the same field name — a list value
    in httpx's `data=` dict is how the test client reproduces that (NOT a
    list of (key, value) tuples, which this httpx version mis-encodes as
    an empty body — caught while verifying this end-to-end by hand)."""
    resp = client.post("/admin/config/content-library", data={
        "opener_text_0": "KỸ SƯ HOẶC CHẤT LƯỢNG CAO",
        "opener_visa_0": ["gijinkoku", "koudo_jinzai"],
        "opener_text_1": "MỌI VISA",
        "cta_0": "ib mình nha",
        "suffix_0": "hỏi thêm",
        "reply_template_0": "Yo {field}{region_clause}",
        "visa_code_0": "gijinkoku", "visa_names_0": "Kỹ Sư",
        "visa_code_1": "koudo_jinzai", "visa_names_1": "Chất Lượng Cao",
    })
    assert resp.status_code == 200
    assert "Đã lưu Kho nội dung" in resp.text, resp.text
    assert get_job_post_openers([]) == [
        {"text": "KỸ SƯ HOẶC CHẤT LƯỢNG CAO", "visa_restrictions": ["gijinkoku", "koudo_jinzai"]},
        {"text": "MỌI VISA", "visa_restrictions": []},
    ]

    from human_bot import content_strategist as cs
    for visa in ("gijinkoku", "koudo_jinzai"):
        job = {"title": "T", "attributes": {"visaType": visa}}
        openers_seen = {cs._draft_job_post_placeholder(job, variant_seed=i).split(" - ")[0] for i in range(4)}
        assert "KỸ SƯ HOẶC CHẤT LƯỢNG CAO" in openers_seen
    job_other = {"title": "T", "attributes": {"visaType": "tokutei"}}
    openers_seen_other = {cs._draft_job_post_placeholder(job_other, variant_seed=i).split(" - ")[0] for i in range(4)}
    assert openers_seen_other == {"MỌI VISA"}


def test_content_library_save_rejects_empty_cta_list_and_saves_nothing(client):
    form = dict(_VALID_CONTENT_LIBRARY_FORM)
    form["cta_0"] = "   "  # blank after strip -> list ends up empty
    resp = client.post("/admin/config/content-library", data=form)
    assert resp.status_code == 200
    assert "Câu mời nhắn tin: cần ít nhất 1 dòng" in resp.text
    # Nothing saved — not even the other 4 valid lists in the same submit,
    # same "all or nothing" stance as every other save route in this file.
    assert get_contact_cta(_CONTACT_CTA_DEFAULT) == _CONTACT_CTA_DEFAULT
    assert get_job_post_openers(_JOB_POST_OPENERS_DEFAULT) == _JOB_POST_OPENERS_DEFAULT


def test_content_library_save_rejects_reply_template_with_bad_placeholder(client):
    form = dict(_VALID_CONTENT_LIBRARY_FORM)
    form["reply_template_0"] = "Chào {ten_khong_hop_le}, nhắn mình nhé."
    resp = client.post("/admin/config/content-library", data=form)
    assert resp.status_code == 200
    assert "dùng sai placeholder" in resp.text
    assert get_candidate_reply_templates(_CANDIDATE_REPLY_TEMPLATES_DEFAULT) == _CANDIDATE_REPLY_TEMPLATES_DEFAULT


def test_content_library_save_rejects_openers_all_visa_restricted(client):
    form = dict(_VALID_CONTENT_LIBRARY_FORM)
    form["opener_visa_0"] = "gijinkoku"  # both rows now restricted -> 0 unrestricted left
    resp = client.post("/admin/config/content-library", data=form)
    assert resp.status_code == 200
    assert "cần ít nhất 1 dòng KHÔNG giới hạn visa" in resp.text
    assert get_job_post_openers(_JOB_POST_OPENERS_DEFAULT) == _JOB_POST_OPENERS_DEFAULT


def test_content_library_save_rejects_visa_code_with_no_names(client):
    form = dict(_VALID_CONTENT_LIBRARY_FORM)
    form["visa_names_0"] = "   \n  "  # blank after stripping each line
    resp = client.post("/admin/config/content-library", data=form)
    assert resp.status_code == 200
    assert "chưa có cách gọi nào" in resp.text
    assert get_visa_type_names(_VISA_TYPE_NAMES_DEFAULT) == _VISA_TYPE_NAMES_DEFAULT


def test_content_library_save_rejects_empty_visa_names_and_saves_nothing(client):
    """Empty dict isn't a usable override (get_visa_type_names() treats it
    same as "no override saved" and falls back to default) — rejecting
    this loudly avoids a silent "my edit did nothing" surprise."""
    form = dict(_VALID_CONTENT_LIBRARY_FORM)
    form["visa_code_0"] = ""  # the only visa row, now blank -> dict ends up empty
    resp = client.post("/admin/config/content-library", data=form)
    assert resp.status_code == 200
    assert "Tên gọi các loại visa: cần ít nhất 1 mã" in resp.text
    assert get_visa_type_names(_VISA_TYPE_NAMES_DEFAULT) == _VISA_TYPE_NAMES_DEFAULT
    # All-or-nothing — the otherwise-valid opener/cta/... edits in the same
    # submit must not have been saved either.
    assert get_contact_cta(_CONTACT_CTA_DEFAULT) == _CONTACT_CTA_DEFAULT


def test_content_library_save_rejects_duplicate_visa_code_and_saves_nothing(client):
    form = dict(_VALID_CONTENT_LIBRARY_FORM)
    form["visa_code_1"] = "gijinkoku"  # same code as visa_code_0
    form["visa_names_1"] = "Tên Khác"
    resp = client.post("/admin/config/content-library", data=form)
    assert resp.status_code == 200
    assert "bị lặp lại" in resp.text
    assert get_visa_type_names(_VISA_TYPE_NAMES_DEFAULT) == _VISA_TYPE_NAMES_DEFAULT


def test_content_library_opener_select_keeps_orphaned_visa_restriction_visible(client):
    """A restriction referencing a visa code no longer in "Tên gọi visa"
    must still show up as its own <option> (and stay selected) — a native
    <select> can only submit one of its own <option> values, so losing
    this would silently un-restrict the opener on the next unrelated
    save."""
    resp = client.get("/admin/config?tab=content")
    assert resp.status_code == 200
    import re
    from human_bot.runtime_config import save_job_post_openers, save_visa_type_names
    save_job_post_openers([
        {"text": "CHỈ CHO MÃ ĐÃ XOÁ", "visa_restrictions": ["mot_ma_khong_con_ton_tai"]},
        {"text": "KHÔNG GIỚI HẠN", "visa_restrictions": []},
    ])
    save_visa_type_names({"gijinkoku": ["Kỹ Sư"]})  # the orphaned code is NOT in here
    resp = client.get("/admin/config?tab=content")
    assert resp.status_code == 200
    assert re.search(
        r'<option value="mot_ma_khong_con_ton_tai" selected>', resp.text,
    ), "orphaned visa_restriction must still render as a selected option, not silently fall back to 'Không giới hạn'"


def test_content_library_opener_row_select_and_input_have_bounded_widths(client):
    """Owner-reported 2026-10-01: long visa labels (e.g. "Nhân Lực Chất
    Lượng Cao (koudo_jinzai)") on the <select> with no width cap, paired
    with the text input having no min-width, squeezed the input down to
    near-nothing and pushed "Xoá" past the row's edge. Regression-checks
    the 3 CSS properties that fix it, not just that the page renders."""
    resp = client.get("/admin/config?tab=content")
    assert "max-width:200px" in resp.text  # caps the <select>'s own width
    assert "min-width:160px" in resp.text  # floor so the text input can't collapse away
    assert "flex-wrap:wrap" in resp.text   # last resort: wrap instead of overflow


def test_content_library_reset_restores_default_and_removes_override(client, isolated_runtime_config):
    client.post("/admin/config/content-library", data=_VALID_CONTENT_LIBRARY_FORM)
    assert get_contact_cta(_CONTACT_CTA_DEFAULT) == ["Nhắn tin ngay nhé"]

    resp = client.post("/admin/config/content-library/reset", data={"list_name": "cta"})
    assert resp.status_code == 200
    assert "Đã khôi phục mặc định" in resp.text
    assert get_contact_cta(_CONTACT_CTA_DEFAULT) == _CONTACT_CTA_DEFAULT

    import json
    stored = json.loads(isolated_runtime_config.read_text())
    assert "content_contact_cta" not in stored  # key removed outright, not reset-to-default-value
    # Resetting one list must not touch the others saved in the same submit.
    assert get_job_post_openers([]) == [
        {"text": "TÌM NHÂN SỰ MỚI", "visa_restrictions": []},
        {"text": "CHỈ DÀNH CHO KỸ SƯ", "visa_restrictions": ["gijinkoku"]},
    ]
