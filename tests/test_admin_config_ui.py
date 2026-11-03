"""/admin/config after the 2026-11-02 UI round: numbers read as numbers, min/max pairs as one row, rows that differ
from the default say so, the human-simulation settings folded away, the sync tab grouped, plain labels, and the two AI
switches that save the moment they are flipped (so that tab has one save button).

The page script (dirty count, reset, discard) is checked in a real browser in test_admin_config_browser.py."""
from __future__ import annotations

import html as html_lib
import re

import pytest
from fastapi.testclient import TestClient

import human_bot.admin as admin_module
from human_bot import runtime_config
from human_bot.data_sync_config import DataSyncConfig
from human_bot.humanize import HumanTypingConfig
from tests.test_admin_config import _make_test_app


def default_of(cls, field: str) -> str:
    """A setting's default as the page prints it — read from the config class, because some defaults come from the
    environment (a .env), so a test must not hard-code them."""
    return admin_module._num_text(getattr(cls(), field))


@pytest.fixture
def client(isolated_runtime_config, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return TestClient(_make_test_app(), follow_redirects=False)


def page(client, tab="behavior") -> str:
    resp = client.get(f"/admin/config?tab={tab}")
    assert resp.status_code == 200
    return resp.text


def _row(text: str, field_name: str) -> str:
    """The HTML of the settings row that holds the input named `field_name` (a pair's row holds two)."""
    rows = re.split(r'(?=<div class="field-row")', text)
    found = [r for r in rows if f'name="{field_name}"' in r]
    assert len(found) == 1, field_name
    return found[0].split("</div>\n</div>")[0]


def _all_inputs(text: str) -> dict[str, str]:
    """name -> value of every settings input on the page ("true" for a ticked switch; unticked ones are absent)."""
    out = {}
    for m in re.finditer(r'<input type="(number|checkbox)" (?:step="any" )?name="(\w+__\w+)" value="([^"]*)"([^>]*)>', text):
        kind, name, value, rest = m.groups()
        if kind == "checkbox":
            if " checked" in rest:
                out[name] = "true"
        else:
            out[name] = value
    return out


# --- numbers ----------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("value, text", [(15.0, "15"), (0.0005, "0.0005"), (0.35, "0.35"), (7000.0, "7000"), (8, "8"), (True, "true"),
                                         (False, "false"), (100000.0, "100000"), (1.5, "1.5"), (0.0, "0")])
def test_numbers_read_as_numbers(value, text):
    assert admin_module._num_text(value) == text


def test_whole_number_settings_no_longer_show_a_decimal_point(client):
    text = page(client, "sync")
    assert f'name="data_sync__poll_interval_minutes" value="{default_of(DataSyncConfig, "poll_interval_minutes")}"' in text
    assert re.search(r'name="data_sync__\w+" value="\d+\.0"', text) is None                  # no whole number printed with a ".0"
    assert f'name="data_sync__candidate_min_confidence" value="{default_of(DataSyncConfig, "candidate_min_confidence")}"' in text


# --- nothing is lost --------------------------------------------------------------------------------------------------------

def test_every_editable_setting_is_on_the_page_exactly_once(client):
    text = "".join(page(client, tab) for tab in ("behavior",)) + page(client, "sync") + page(client, "ai")
    names = re.findall(r'<input type="(?:number|checkbox)"[^>]*? name="(\w+__\w+)"', text)
    expected = [f"{prefix}__{f}" for _k, prefix, _t, _c, fields, *_ in admin_module._CONFIG_SECTIONS for f in fields]
    # (each page above includes the other tabs' panels too: count per name on ONE render)
    one = page(client)
    on_page = re.findall(r'<input type="(?:number|checkbox)"[^>]*? name="(\w+__\w+)"', one)
    assert sorted(on_page) == sorted(expected) and len(set(on_page)) == len(on_page) and names


def test_saving_what_the_page_shows_changes_nothing(client, isolated_runtime_config):
    """Round trip: post every box and switch exactly as rendered; the stored settings must equal the defaults, with the
    same types (the old float formatting once turned ints into floats — see config_save)."""
    runtime_config.save_human_typing_overrides({"wpm": 55.0, "enabled": False})
    runtime_config.save_data_sync_overrides({"poll_interval_minutes": 30.0, "max_overflow_business_days": 3})
    form = _all_inputs(page(client))
    assert form["typing__wpm"] == "55" and "typing__enabled" not in form and form["data_sync__max_overflow_business_days"] == "3"
    assert client.post("/admin/config", data=form).status_code == 303
    assert runtime_config.get_human_typing_overrides()["wpm"] == 55.0 and runtime_config.get_human_typing_overrides()["enabled"] is False
    saved = runtime_config.get_data_sync_overrides()
    assert saved["poll_interval_minutes"] == 30.0 and saved["max_overflow_business_days"] == 3 and isinstance(saved["max_overflow_business_days"], int)
    for _k, prefix, _t, cls, fields, _labels, getter, _save in admin_module._CONFIG_SECTIONS:
        defaults, now = cls(), getter()
        for f in fields:
            if f in now and not isinstance(getattr(defaults, f), bool):
                assert type(now[f]) is type(getattr(defaults, f)), (prefix, f)


# --- pairs ------------------------------------------------------------------------------------------------------------------

def test_min_max_settings_are_found_from_their_labels():
    found = {}
    for key, prefix, _t, _c, fields, labels, *_ in admin_module._CONFIG_SECTIONS:
        pairs = admin_module._config_pairs(prefix, list(fields), labels)
        for lo, (hi, label, unit) in pairs.items():
            assert lo in fields and hi in fields and lo != hi and label and unit
        found[prefix] = sorted((lo, hi) for lo, (hi, _l, _u) in pairs.items())
    # EVERY pair, by name: rewording a label must not silently turn a pair back into two rows
    assert found == {
        "scheduling": [],
        "typing": [("punctuation_pause_min_ms", "punctuation_pause_max_ms"), ("typo_notice_delay_min_ms", "typo_notice_delay_max_ms"),
                   ("word_pause_min_ms", "word_pause_max_ms")],
        "pacing": [("composer_open_pause_min_ms", "composer_open_pause_max_ms"), ("page_load_pause_min_ms", "page_load_pause_max_ms"),
                   ("reading_buffer_min_ms", "reading_buffer_max_ms"), ("reading_pause_min_ms", "reading_pause_max_ms"),
                   ("ui_step_pause_min_ms", "ui_step_pause_max_ms")],
        "mouse": [("click_delay_min_ms", "click_delay_max_ms"), ("min_steps", "max_steps"), ("step_delay_min_ms", "step_delay_max_ms")],
        "scroll": [("step_delay_min_ms", "step_delay_max_ms")],
        "data_sync": [("comment_gap_min_minutes", "comment_gap_max_minutes"), ("post_gap_min_minutes", "post_gap_max_minutes"),
                      ("quiet_hour_start_local", "quiet_hour_end_local")],
        "media": [],
        "safety_cooldown": [("min_delay_seconds", "max_delay_seconds")],
        "telegram": [],
    }
    typing = admin_module._config_pairs("typing", list(admin_module.EDITABLE_HUMAN_TYPING_FIELDS), admin_module._TYPING_LABELS)
    assert typing["word_pause_min_ms"] == ("word_pause_max_ms", "Ngừng thêm sau mỗi từ (ms)", "ms")
    assert "min_char_delay_ms" not in typing                                                  # "minimum gap", not a min/max pair
    assert admin_module._config_pairs("mouse", list(admin_module.EDITABLE_MOUSE_FIELDS), admin_module._MOUSE_LABELS)["min_steps"][0] == "max_steps"
    sync = admin_module._config_pairs("data_sync", list(admin_module.EDITABLE_DATA_SYNC_FIELDS), admin_module._DATA_SYNC_LABELS)
    assert {"post_gap_min_minutes", "comment_gap_min_minutes", "quiet_hour_start_local"} <= set(sync)
    cooldown = admin_module._config_pairs("safety_cooldown", list(admin_module.EDITABLE_SAFETY_COOLDOWN_FIELDS), admin_module._SAFETY_COOLDOWN_LABELS)
    assert cooldown["min_delay_seconds"][1].endswith("ở TUẦN 1 hạ nhiệt (mọi tier)") and "(giây)" in cooldown["min_delay_seconds"][1]


def test_a_pair_is_one_row_with_two_boxes_the_unit_and_the_default_range(client):
    text = page(client, "sync")
    row = _row(text, "data_sync__post_gap_min_minutes")
    assert 'name="data_sync__post_gap_max_minutes"' in row and row.count('type="number"') == 2
    assert "Khoảng cách giữa 2 bài đăng nhóm liên tiếp (phút)" in row and '<span class="pair-sep">đến</span>' in row and '<span class="pair-unit">phút</span>' in row
    assert f'data-default="{default_of(DataSyncConfig, "post_gap_min_minutes")}"' in row and f'data-default="{default_of(DataSyncConfig, "post_gap_max_minutes")}"' in row and 'aria-label="từ"' in row and 'aria-label="đến"' in row
    quiet = _row(text, "data_sync__quiet_hour_start_local")
    assert "Khung giờ yên tĩnh" in quiet and 'name="data_sync__quiet_hour_end_local"' in quiet and 'class="pair-unit">giờ<' in quiet


# --- rows that differ from the default ---------------------------------------------------------------------------------------

def test_a_row_at_its_default_says_nothing_and_a_changed_one_offers_the_default(client):
    runtime_config.save_human_typing_overrides({"wpm": 55.0})
    runtime_config.save_data_sync_overrides({"post_gap_max_minutes": 120.0})
    text = page(client, "behavior")
    changed = _row(text, "typing__wpm")
    assert f'data-reset-wrap>đã chỉnh · mặc định <b>{default_of(HumanTypingConfig, "wpm")}</b>' in changed and "↺ đặt lại" in changed and " hidden" not in changed.split("data-reset-wrap")[1].split(">")[0]
    untouched = _row(text, "typing__char_delay_stdev_ratio")
    assert "data-reset-wrap hidden" in untouched
    pair = _row(page(client, "sync"), "data_sync__post_gap_min_minutes")
    assert f'mặc định <b>{default_of(DataSyncConfig, "post_gap_min_minutes")} – {default_of(DataSyncConfig, "post_gap_max_minutes")}</b>' in pair and "data-reset-wrap hidden" not in pair


def test_a_switch_off_its_default_offers_the_default_too(client):
    runtime_config.save_scheduling_overrides({"auto_fire_enabled": True})
    row = _row(page(client), "scheduling__auto_fire_enabled")
    assert "mặc định <b>tắt</b>" in row and "data-reset-wrap hidden" not in row and 'data-default="false"' in row
    assert "data-reset-wrap hidden" in _row(page(client), "media__attach_random_meme_default")


def test_the_technical_key_is_a_tooltip_not_a_line_of_text(client):
    text = page(client, "sync")
    assert 'title="poll_interval_minutes"' in text and "· key:" not in text and "mặc định: 15" not in text
    assert 'title="post_gap_min_minutes · post_gap_max_minutes"' in text


# --- layout ------------------------------------------------------------------------------------------------------------------

def test_behaviour_tab_leads_with_what_an_owner_changes_and_folds_the_simulation_away(client):
    runtime_config.save_human_typing_overrides({"wpm": 55.0})
    text = page(client)
    panel = text.split('id="tab-behavior"')[1].split('id="tab-sync"')[0]
    titles = [html_lib.unescape(t).split(" ", 1)[1] for t in re.findall(r"<h2>([^<]+)</h2>", panel)]          # (drop the emoji)
    assert titles == ["Lên lịch & tự động đăng", "Ảnh đính kèm", "Hạ nhiệt sau khi kích hoạt lại tài khoản", "Báo động Telegram",
                      "Gõ phím", "Khoảng chờ theo ngữ cảnh", "Di chuyển chuột", "Cuộn trang"]
    adv = text.split('<details class="cfg-adv">')[1].split("</details>")[0]
    assert "<details class=\"cfg-adv\" open" not in text and "4 nhóm · 43 mục" in adv and "đã chỉnh 1" in adv
    assert adv.count('<div class="card') == 4 and 'name="typing__wpm"' in adv
    assert 'name="scheduling__auto_fire_enabled"' not in adv                                   # the one that matters stays out of the fold


def test_the_advanced_badge_is_hidden_when_nothing_was_changed_and_counts_rows_not_boxes(client):
    assert "data-adv-changed hidden>đã chỉnh 0" in page(client).split('<details class="cfg-adv">')[1].split("</summary>")[0]
    runtime_config.save_pacing_overrides({"page_load_pause_min_ms": 8000.0, "page_load_pause_max_ms": 12000.0})     # one pair: ONE row
    runtime_config.save_mouse_overrides({"jitter_px": 3.0})
    summary = page(client).split('<details class="cfg-adv">')[1].split("</summary>")[0]
    assert "data-adv-changed>đã chỉnh 2" in summary and " hidden" not in summary.split("data-adv-changed")[1].split(">")[0]


def test_sync_tab_is_grouped_and_the_rare_ones_are_folded(client):
    text = page(client, "sync").split('id="tab-sync"')[1].split('id="tab-ai"')[0]
    assert re.findall(r'<div class="cfg-group-title">([^<]+)</div>', text) == ["Chu kỳ", "Nhịp đăng", "Chọn việc để đăng"]
    folded = text.split('<details class="cfg-adv cfg-adv-inline">')[1].split("</details>")[0]
    for name in ("cache_retention_days", "max_overflow_business_days", "max_cursor_holdback_days"):
        assert f'name="data_sync__{name}"' in folded
    assert 'name="data_sync__poll_interval_minutes"' not in folded and 'name="data_sync__job_post_ai_enabled"' not in text


def test_a_sync_setting_nobody_grouped_still_shows_up_under_advanced(client, monkeypatch):
    monkeypatch.setattr(admin_module, "_SYNC_GROUPS", [(t, [f for f in fs if f != "candidate_max_age_days"], adv) for t, fs, adv in admin_module._SYNC_GROUPS])
    text = page(client, "sync").split('id="tab-sync"')[1].split('id="tab-ai"')[0]
    assert 'name="data_sync__candidate_max_age_days"' in text.split('<details class="cfg-adv cfg-adv-inline">')[1]


# --- words ------------------------------------------------------------------------------------------------------------------

def test_labels_and_help_are_plain_words_not_paths_or_constants():
    for _k, prefix, _t, _c, fields, labels, *_ in admin_module._CONFIG_SECTIONS:
        for f in fields:
            label = labels.get(f, "")
            assert len(label) <= 95, (prefix, f, len(label))
            assert "/admin/" not in label and "COOLDOWN_" not in label and "TELEGRAM_BOT_TOKEN" not in label, (prefix, f)
    for key, help_text in admin_module._FIELD_HELP.items():
        prefix, field = key.split("__", 1)
        assert any(p == prefix and field in fields for _k, p, _t, _c, fields, *_ in admin_module._CONFIG_SECTIONS), key
        assert "/admin/" not in help_text and "COOLDOWN_" not in help_text and "TELEGRAM_BOT_TOKEN" not in help_text, key


def test_the_auto_fire_setting_says_what_off_means_in_plain_words(client):
    row = _row(page(client), "scheduling__auto_fire_enabled")
    assert "Tự động đăng khi đến giờ" in row and "Tắt = chỉ đặt lịch" in row and "Lịch đăng" in row and "/admin" not in row


# --- the AI tab: one save button, switches save themselves --------------------------------------------------------------------

def test_the_ai_switches_are_instant_and_the_page_save_bar_is_not_on_that_tab(client):
    text = page(client, "ai")
    card = text.split('id="ai-toggle-card"')[1].split("</form>")[0]
    assert card.count('hx-post="/admin/config/ai-toggle"') == 2 and 'hx-vals=\'js:{field: "job_post_ai_enabled", value: event.target.checked}\'' in card
    assert "data-default" not in card and "data-field-row" not in card and "không cần bấm Lưu" in card
    assert 'id="config-generic-save-actions" hidden' in text


def test_flipping_an_ai_switch_saves_it_and_touches_nothing_else(client):
    runtime_config.save_data_sync_overrides({"poll_interval_minutes": 30.0, "post_gap_max_minutes": 120.0})
    off = client.post("/admin/config/ai-toggle", data={"field": "job_post_ai_enabled"})                  # a switch that is off sends nothing
    assert off.status_code == 200 and "✅ Đã lưu." in off.text and 'id="ai-toggle-card"' in off.text
    saved = runtime_config.get_data_sync_overrides()
    assert saved == {"poll_interval_minutes": 30.0, "post_gap_max_minutes": 120.0, "job_post_ai_enabled": False}
    on = client.post("/admin/config/ai-toggle", data={"field": "job_post_ai_enabled", "data_sync__job_post_ai_enabled": "true"})
    assert runtime_config.get_data_sync_overrides()["job_post_ai_enabled"] is True and 'name="data_sync__job_post_ai_enabled" value="true" checked' in on.text
    client.post("/admin/config/ai-toggle", data={"field": "candidate_reply_ai_enabled"})
    assert runtime_config.get_data_sync_overrides()["job_post_ai_enabled"] is True                       # the other switch is left alone
    assert runtime_config.get_data_sync_overrides()["candidate_reply_ai_enabled"] is False


def test_the_ai_switch_route_refuses_any_other_field(client):
    resp = client.post("/admin/config/ai-toggle", data={"field": "poll_interval_minutes", "data_sync__poll_interval_minutes": "1"})
    assert resp.status_code == 400 and runtime_config.get_data_sync_overrides() == {}
    assert client.post("/admin/config/ai-toggle", data={}).status_code == 400


# --- the sticky save bar ------------------------------------------------------------------------------------------------------

def test_the_save_bar_counts_changes_and_can_drop_them(client):
    text = page(client)
    bar = text.split('id="config-generic-save-actions"')[1].split("</form>")[0]
    assert 'data-dirty-note>Chưa có thay đổi</span>' in bar and "data-discard hidden" in bar and "Lưu cấu hình</button>" in bar
    assert "<form method=\"post\" action=\"/admin/config\" data-config-form>" in text
    css = admin_module._PAGE_STYLE
    assert ".form-actions.savebar { @apply sticky bottom-0" in css and ".form-actions.savebar[hidden] { @apply hidden; }" in css
    assert "initConfigForm" in text and "beforeunload" in text


def test_the_content_tabs_reply_template_boxes_are_two_lines_not_a_tall_box_each(client):
    text = page(client, "content")
    assert text.count("min-height:64px") >= 10


# --- review fixes ----------------------------------------------------------------------------------------------------------

def test_a_stale_page_cannot_flip_an_ai_switch_back(client):
    """The AI switches save themselves; a page opened BEFORE one was flipped elsewhere must not undo it on its next save."""
    runtime_config.save_data_sync_overrides({"job_post_ai_enabled": False, "candidate_reply_ai_enabled": True})
    form = _all_inputs(page(client, "sync"))
    assert "data_sync__job_post_ai_enabled" not in form                                      # (it is off, so the page sends nothing for it)
    stale = {**form, "data_sync__job_post_ai_enabled": "true", "data_sync__poll_interval_minutes": "20"}      # a stale page still showing it ON
    assert client.post("/admin/config", data=stale).status_code == 303
    saved = runtime_config.get_data_sync_overrides()
    assert saved["job_post_ai_enabled"] is False and saved["candidate_reply_ai_enabled"] is True and saved["poll_interval_minutes"] == 20.0
    runtime_config.save_data_sync_overrides({})
    assert client.post("/admin/config", data={"data_sync__poll_interval_minutes": "20"}).status_code == 303
    assert "job_post_ai_enabled" not in runtime_config.get_data_sync_overrides()             # never set: stays unset (default), not written as False


def test_numbers_keep_every_digit_they_were_stored_with():
    for value in (0.123456789012, 1234567890.5, 1e-05, 0.1 + 0.2, 15.0, 123456789012.0):
        assert float(admin_module._num_text(value)) == value, value
    assert admin_module._num_text(15.0) == "15" and admin_module._num_text(0.35) == "0.35"


def test_saving_an_unchanged_page_keeps_long_decimals_exactly(client):
    runtime_config.save_data_sync_overrides({"candidate_min_confidence": 0.123456789012})
    assert client.post("/admin/config", data=_all_inputs(page(client, "sync"))).status_code == 303
    assert runtime_config.get_data_sync_overrides()["candidate_min_confidence"] == 0.123456789012


def test_ai_switches_post_only_themselves_and_keep_focus_and_report_a_failed_save(client):
    text = page(client, "ai")
    card = text.split('id="ai-toggle-card"')[1].split('id="tab-content"')[0]
    assert card.count('hx-params="field,value"') == 2 and 'id="ai-toggle-job_post_ai_enabled"' in card and "hx-include" not in card
    assert "undefined" not in card                                                           # (listing the checkbox in hx-params posts "undefined" for an unticked one)
    assert "htmx:responseError" in text and "htmx:sendError" in text and "data-save-error" in text


def test_discard_and_the_badge_are_scripted_per_box_not_per_form(client):
    script = page(client)
    assert "form.reset()" not in script and "el.defaultChecked" in script and "data-adv-changed" in script


def test_one_helper_decides_what_differs_from_the_default():
    differs = admin_module._differs_from_default
    assert not differs(15, 15.0) and differs(15, 16) and differs(True, False) and not differs(True, True) and differs("a", "b") and not differs("a", "a")
    assert not differs(None, None) and differs(None, 1)


def test_the_sync_card_is_built_by_the_shared_card_helper(client):
    card = admin_module._config_card_html("🔄", "T", "<p>x</p>", grid=False)
    assert '<div class="card">' in card and "field-grid" not in card and "<p>x</p>" in card
    assert "field-grid" in admin_module._config_card_html("🔄", "T", "<p>x</p>")


def test_the_switch_route_reads_an_explicit_value(client):
    runtime_config.save_data_sync_overrides({})
    client.post("/admin/config/ai-toggle", data={"field": "job_post_ai_enabled", "value": "false"})
    assert runtime_config.get_data_sync_overrides() == {"job_post_ai_enabled": False}
    client.post("/admin/config/ai-toggle", data={"field": "job_post_ai_enabled", "value": "true"})
    assert runtime_config.get_data_sync_overrides() == {"job_post_ai_enabled": True}
    client.post("/admin/config/ai-toggle", data={"field": "job_post_ai_enabled", "value": "undefined"})      # never "on" by accident
    assert runtime_config.get_data_sync_overrides() == {"job_post_ai_enabled": False}
