"""Nhóm đã tham gia, Quản lý tài khoản MOD, Đăng nhập and the rate-limit dialog after the 2026-11-02 UI round: rows instead of
tables, what each group got so far, a search box for a long list, show/hide for passwords, and the delays in words."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import human_bot.admin as admin_module
from human_bot import db, runtime_config
from human_bot.config import GroupRef, RateLimits
from tests.test_admin_post import _make_test_app

NOW = datetime(2026, 11, 3, 12, 0, tzinfo=timezone.utc)


@pytest.fixture
def client(isolated_runtime_config, isolated_schedule_dirs, isolated_accounts_dir, isolated_db, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    runtime_config.save_registered_account("acc-a", "Acc A")
    runtime_config.save_registered_account("acc-b", "Acc B")
    return TestClient(_make_test_app(), follow_redirects=False)


def log(url, *, ok=True, account="acc-a", action="post_to_group", message="", at=None):
    return db.log_action(account_id=account, action=action, success=ok, message=message, target_url=url, content="x",
                         created_at=(at or datetime.now(timezone.utc)).isoformat())


def groups_page(client, account="acc-a") -> str:
    resp = client.get(f"/admin/groups?account_id={account}")
    assert resp.status_code == 200
    return resp.text


def body(text: str) -> str:
    """The page's HTML without its <style>/<script> (class names and attributes also appear in those)."""
    html_body = text.split("<body", 1)[1]
    return re.sub(r"<(script|style)\b.*?</\1>", "", html_body, flags=re.S)


def group_rows(text: str) -> list[str]:
    return re.findall(r'<div class="sched-item" data-filter-row.*?(?=<div class="sched-item" data-filter-row|<div class="empty-state" data-list-filter-empty)', body(text), re.S)


def save_groups(*groups, account="acc-a"):
    runtime_config.save_joined_groups(account, [GroupRef(name=n, url=u) for n, u in groups])


# --- time in words ------------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("delta, text", [
    (timedelta(seconds=10), "vừa xong"), (timedelta(minutes=5), "5 phút trước"), (timedelta(hours=3, minutes=20), "3 giờ trước"),
    (timedelta(hours=30), "hôm qua"), (timedelta(days=6, hours=2), "6 ngày trước"),
    (timedelta(hours=47), "2 ngày trước"),                         # by calendar day in Japan, not 24-48 hours: two days ago, not "yesterday"
])
def test_ago_in_words(delta, text):
    assert admin_module._ago_vi((NOW - delta).isoformat(), NOW) == text
    assert admin_module._ago_vi((NOW - delta).replace(tzinfo=None).isoformat(), NOW) == text          # a timestamp without an offset is UTC


def test_ago_gives_nothing_for_nothing_or_nonsense():
    assert admin_module._ago_vi(None, NOW) == "" and admin_module._ago_vi("", NOW) == "" and admin_module._ago_vi("garbage", NOW) == ""


def test_what_a_group_got_in_one_line():
    stats = admin_module._group_stats_text
    ago = (NOW - timedelta(days=3)).isoformat()
    assert stats(None) == "chưa đăng lần nào" and stats({"ok": 0, "failed": 0, "last_ok": None}) == "chưa đăng lần nào"
    assert stats({"ok": 7, "failed": 0, "last_ok": ago}, NOW) == "Đã đăng 7 bài · gần nhất 3 ngày trước"
    assert stats({"ok": 7, "failed": 2, "last_ok": ago}, NOW) == "Đã đăng 7 bài · gần nhất 3 ngày trước · 2 lần lỗi"
    assert stats({"ok": 0, "failed": 2, "last_ok": None}, NOW) == "Chưa đăng được bài nào · 2 lần lỗi"


# --- db.group_activity -----------------------------------------------------------------------------------------------------------

def test_group_activity_counts_per_group_for_one_account(isolated_db):
    a, b = "https://www.facebook.com/groups/1", "https://www.facebook.com/groups/2"
    first, last = NOW - timedelta(days=5), NOW - timedelta(days=1)
    log(a, at=first); log(a, at=last); log(a, ok=False, message="error:x"); log(a, ok=False, message="rate_limited: gap")      # a deferral is not a failure
    log(b, ok=False, message="error:y"); log(a, account="acc-b"); log(a, action="comment_on_group_post")
    rows = {r["target_url"]: r for r in db.group_activity("acc-a")}
    assert (rows[a]["ok"], rows[a]["failed"], rows[a]["last_ok"]) == (2, 1, last.isoformat())
    assert (rows[b]["ok"], rows[b]["failed"], rows[b]["last_ok"]) == (0, 1, None)
    assert db.group_activity("nobody") == [] and len(rows) == 2


# --- Nhóm đã tham gia --------------------------------------------------------------------------------------------------------------

def test_the_group_list_is_rows_with_the_name_first_and_what_each_got(client):
    save_groups(("Nhóm Một", "https://www.facebook.com/groups/1111"), ("Nhóm Hai", "https://www.facebook.com/groups/2222"))
    log("https://www.facebook.com/groups/1111"); log("https://www.facebook.com/groups/1111"); log("https://www.facebook.com/groups/1111", ok=False, message="error:x")
    text = groups_page(client)
    assert "<table" not in body(text) and len(group_rows(text)) == 2
    one = next(r for r in group_rows(text) if "Nhóm Một" in r)
    assert '<a class="sched-target" href="https://www.facebook.com/groups/1111" target="_blank"' in one and ">Nhóm Một</a>" in one
    assert '<div class="grp-url">https://www.facebook.com/groups/1111</div>' in one and "Đã đăng 2 bài · gần nhất vừa xong · 1 lần lỗi" in one
    assert "chưa đăng lần nào" in next(r for r in group_rows(text) if "Nhóm Hai" in r)


def test_the_log_may_hold_the_other_form_of_a_groups_url(client):
    save_groups(("Nhóm", "https://www.facebook.com/groups/1111"))
    log("https://m.facebook.com/groups/1111/", at=datetime.now(timezone.utc) - timedelta(hours=5))        # a different spelling of the same group
    log("https://www.facebook.com/groups/1111")
    assert "Đã đăng 2 bài · gần nhất vừa xong" in groups_page(client)


def test_a_name_that_is_a_vanity_url_says_so_and_a_missing_name_is_marked(client):
    save_groups(("Số", "https://www.facebook.com/groups/1234567890"), ("Tên", "https://www.facebook.com/groups/vieclam"), ("", "https://www.facebook.com/groups/99"))
    rows = group_rows(groups_page(client))
    flagged = [r for r in rows if 'class="grp-flag"' in r]
    assert len(flagged) == 1 and "vieclam" in flagged[0] and "tên tuỳ chỉnh</span>" in flagged[0] and "bền hơn" in flagged[0]
    unnamed = next(r for r in rows if "groups/99" in r)
    assert 'class="sched-target muted"' in unnamed and "(chưa đặt tên)" in unnamed and 'class="grp-flag"' not in unnamed


def test_names_and_urls_are_escaped_everywhere_in_a_row(client):
    save_groups(('<b>"x"</b>', 'https://www.facebook.com/groups/1?a=1&b="2"'))
    text = body(groups_page(client))
    assert "<b>" not in text and "&lt;b&gt;" in text
    assert re.search(r'data-search="[^"]*&lt;b&gt;', text) and 'data-search="<' not in text
    assert "Xoá nhóm &lt;b&gt;" in text                                                          # the confirm question names it, escaped


def test_the_menu_has_copy_and_a_confirmed_delete_and_the_edit_button_opens_the_dialog(client):
    save_groups(("Nhóm", "https://www.facebook.com/groups/1"))
    row = group_rows(groups_page(client))[0]
    assert "✎ Sửa" in row and "hx-get=\"/admin/groups/edit-modal?account_id=acc-a&group_id=" in row
    assert "📋 Copy URL" in row and 'hx-post="/admin/groups/delete"' in row and 'hx-confirm="Xoá nhóm Nhóm khỏi danh sách?"' in row and "menu-item danger" in row


def test_a_short_list_has_no_search_box_and_a_long_one_does(client):
    save_groups(*[(f"G{i}", f"https://www.facebook.com/groups/{i}") for i in range(8)])
    assert 'type="search"' not in body(groups_page(client))
    save_groups(*[(f"G{i}", f"https://www.facebook.com/groups/{i}") for i in range(9)])
    long = body(groups_page(client))
    assert 'type="search"' in long and "data-list-filter-count" in long and "data-list-filter-empty hidden" in long and "input[type=search]" in admin_module._PAGE_STYLE


def test_the_two_accounts_lists_are_kept_apart(client):
    save_groups(("Của A", "https://www.facebook.com/groups/1"))
    save_groups(("Của B", "https://www.facebook.com/groups/2"), account="acc-b")
    log("https://www.facebook.com/groups/1", account="acc-b")                                       # B posted to A's group URL: not A's
    assert "chưa đăng lần nào" in body(groups_page(client)) and "Của B" not in groups_page(client) and "Của B" in groups_page(client, "acc-b")


def test_empty_states_point_to_the_next_step(client):
    save_groups()
    assert "Bấm \"➕ Thêm nhóm mới\"" in groups_page(client)


def test_group_editing_still_works_through_the_new_rows(client):
    save_groups(("Cũ", "https://www.facebook.com/groups/1"))
    gid = runtime_config.get_joined_groups("acc-a")[0].id
    assert "Cũ" in client.get(f"/admin/groups/edit-modal?account_id=acc-a&group_id={gid}").text
    client.post("/admin/groups/update", data={"account_id": "acc-a", "group_id": gid, "name": "Mới", "url": "https://www.facebook.com/groups/1"})
    assert [g.name for g in runtime_config.get_joined_groups("acc-a")] == ["Mới"]
    client.post("/admin/groups/delete", data={"account_id": "acc-a", "group_id": gid})
    assert runtime_config.get_joined_groups("acc-a") == []


# --- MOD accounts ------------------------------------------------------------------------------------------------------------------

def test_mod_page_is_a_list_with_the_intro_under_the_title(client):
    runtime_config.add_mod_user("mod_lan", "secret1")
    text = client.get("/admin/mod-users").text
    assert re.search(r"<h1>Quản lý tài khoản MOD</h1>\s*<p class=\"page-desc\">Tài khoản MOD có đủ quyền như ADMIN", text)
    body = text.split('id="mod-users-content"')[1]
    assert "<table" not in body and "1 tài khoản MOD" in body and "➕ Thêm tài khoản MOD" in body
    assert "mod_lan</span>" in body and "Tạo lúc" in body and "🔑 Đổi mật khẩu" in body and "🗑 Xoá tài khoản" in body
    assert "hx-confirm=\"Xoá tài khoản MOD 'mod_lan'?" in body and 'action="/admin/mod-users/mod_lan/delete"' in body


def test_mod_page_with_nobody_yet_says_what_to_do(client):
    body = client.get("/admin/mod-users").text.split('id="mod-users-content"')[1]
    assert 'class="empty-state"' in body and "Bấm “➕ Thêm tài khoản MOD”" in body and "0 tài khoản MOD" in body


def test_deleting_a_mod_still_works_from_the_menu(client):
    runtime_config.add_mod_user("mod_lan", "secret1")
    resp = client.post("/admin/mod-users/mod_lan/delete", headers={"hx-request": "true"})
    assert resp.status_code == 200 and runtime_config.get_mod_users() == [] and "Chưa có tài khoản MOD nào" in resp.text


# --- passwords ---------------------------------------------------------------------------------------------------------------------

def test_password_boxes_have_a_show_hide_button_and_keep_their_names():
    box = admin_module._password_input_html("password")
    assert '<input type="password" name="password" aria-label="Mật khẩu" autocomplete="current-password" required>' in box
    assert box.count('class="pw-toggle"') == 1 and 'aria-label="Hiện mật khẩu"' in box and "i.type==='password'" in box
    assert 'autocomplete="new-password"' in admin_module._password_input_html("p", autocomplete="new-password", extra=' minlength="6"') and 'minlength="6"' in admin_module._password_input_html("p", extra=' minlength="6"')


def test_login_page_labels_fields_and_can_show_the_password():
    page = admin_module._login_layout(admin_module._login_page_html("/admin/x", False))
    assert 'name="username" required autofocus autocomplete="username"' in page and 'name="password" aria-label="Mật khẩu" autocomplete="current-password" required' in page
    assert page.count('class="pw-toggle"') == 1 and 'name="next" value="/admin/x"' in page and "field-stack" not in body(page)
    assert "Trang quản trị human_bot" in page and "tên đăng nhập hoặc mật khẩu không đúng" not in page.lower()
    assert "Tên đăng nhập hoặc mật khẩu không đúng" in admin_module._login_page_html("/admin", True)


def test_mod_dialogs_keep_the_field_names_the_routes_read_and_add_the_toggle(client):
    add = client.get("/admin/mod-users/add-modal").text
    for name in ("username", "password", "password_confirm"):
        assert f'name="{name}"' in add
    assert add.count('class="pw-toggle"') == 2 and add.count('minlength="6"') == 2 and "Ít nhất 6 ký tự." in add
    runtime_config.add_mod_user("mod_lan", "secret1")
    edit = client.get("/admin/mod-users/mod_lan/edit-password-modal").text
    assert 'name="new_password"' in edit and 'name="new_password_confirm"' in edit and edit.count('class="pw-toggle"') == 2
    refill = admin_module._mod_user_add_modal_html(username='a"b', error="Lỗi")
    assert 'value="a&quot;b"' in refill and "Lỗi" in refill                                      # an error keeps what was typed (escaped), not the passwords


# --- the rate-limit dialog ----------------------------------------------------------------------------------------------------------

@pytest.mark.parametrize("seconds, text", [(0, "0 giây"), (45, "45 giây"), (60, "1 phút"), (1800, "30 phút"), (2232, "37 phút 12 giây"),
                                           (3600, "1 giờ"), (3900, "1 giờ 5 phút"), (7200, "2 giờ"), (14400, "4 giờ")])
def test_seconds_in_words(seconds, text):
    assert admin_module._duration_vi(seconds) == text


def _modal(limits=None, override=False) -> str:
    return admin_module._rate_limits_modal_html("acc-a", limits or RateLimits(), override)


def test_the_rate_limit_dialog_groups_the_fields_and_keeps_every_name():
    text = _modal()
    assert re.findall(r'<div class="cfg-group-title">([^<]+)</div>', text) == ["Số lượng tối đa", "Khoảng chờ giữa 2 hành động"]
    for name in admin_module._RATE_LIMITS_LABELS:
        assert text.count(f'name="{name}"') == 1, name
    assert "key:" not in text and 'title="posts_per_day"' in text and 'name="tier_key"' in text


def test_the_two_delays_are_pairs_that_say_what_they_mean_in_words():
    limits = RateLimits(post_min_delay_seconds=1800, post_max_delay_seconds=2232, comment_min_delay_seconds=900, comment_max_delay_seconds=1800)
    rows = re.findall(r'<div class="field-row" data-duration-pair>.*?(?=<div class="field-row"|<div class="form-actions)', _modal(limits), re.S)
    assert len(rows) == 2
    assert "Giữa 2 bài đăng" in rows[0] and "≈ 30 phút – 37 phút 12 giây" in rows[0] and rows[0].count('type="number"') == 2 and 'class="pair-unit">giây<' in rows[0]
    assert "Giữa 2 comment" in rows[1] and "≈ 15 phút – 30 phút" in rows[1]
    assert 'name="post_min_delay_seconds" value="1800"' in rows[0] and 'name="comment_max_delay_seconds" value="1800"' in rows[1]


def test_the_age_presets_and_the_buttons_survive_the_new_layout():
    text = _modal(override=True)
    assert text.count("data-apply-tier") == len(admin_module.ACCOUNT_AGE_TIERS) and "Áp nhanh theo tuổi tài khoản Facebook" in text
    assert 'data-tier_key="' in text and "data-max_groups_per_post" not in text                  # a tier leaves the group limit alone
    assert 'name="reset" value="1"' in text and "Khôi phục mặc định" in text and 'class="form-actions rl-actions"' in text and "giá trị tuỳ chỉnh riêng" in text


def test_the_rate_limit_save_route_reads_what_the_dialog_posts(client):
    """A round trip through the dialog's own field names: every number box of the rendered dialog, with a new value, is saved."""
    names = re.findall(r'<input type="number"[^>]*? name="(\w+)"', _modal())
    values = {name: str(10 + i) for i, name in enumerate(names)}
    assert client.post("/admin/accounts/rate-limits", data={"account_id": "acc-a", "tier_key": "", **values}, headers={"hx-request": "true"}).status_code == 200
    saved = runtime_config.get_rate_limits_overrides("acc-a")
    assert {k: str(v) for k, v in saved.items()} == values


# --- styles ------------------------------------------------------------------------------------------------------------------------

def test_css_for_rows_passwords_and_the_dialog_is_there():
    css = admin_module._PAGE_STYLE
    for rule in (".grp-line { @apply grid", ".grp-flag {", ".pw-field { @apply flex", ".pw-toggle[aria-pressed=\"true\"]", ".form-col { @apply flex flex-col gap-4; }",
                 ".rl-tier-buttons {", ".rl-actions {", ".sched-item[hidden] { @apply hidden; }"):
        assert rule in css, rule
    assert "initListFilter" in css and "initDurationHint" in css and 'input.dispatchEvent(new Event("input", { bubbles: true }))' in css


# --- review fixes ------------------------------------------------------------------------------------------------------------------

def test_calendar_days_in_japan_not_elapsed_hours():
    """Within 24 hours it is minutes / hours; after that it counts calendar days in Japan, like the Telegram bot."""
    now = datetime(2026, 11, 3, 0, 0, tzinfo=timezone.utc)                       # 09:00 JST on the 3rd
    assert admin_module._ago_vi(datetime(2026, 11, 1, 1, 0, tzinfo=timezone.utc).isoformat(), now) == "2 ngày trước"      # 10:00 JST on the 1st, 47 h ago
    assert admin_module._ago_vi(datetime(2026, 11, 2, 14, 30, tzinfo=timezone.utc).isoformat(), now) == "9 giờ trước"     # 23:30 JST on the 2nd
    assert admin_module._ago_vi(datetime(2026, 11, 1, 23, 30, tzinfo=timezone.utc).isoformat(), now) == "hôm qua"         # 24.5 h ago, 08:30 JST on the 2nd


def test_an_unreadable_timestamp_leaves_no_dangling_words():
    text = admin_module._group_stats_text({"ok": 3, "failed": 0, "last_ok": "not a date"}, NOW)
    assert text == "Đã đăng 3 bài" and "gần nhất" not in text


def test_the_page_survives_an_unreadable_action_log(client, monkeypatch):
    save_groups(("Nhóm", "https://www.facebook.com/groups/1"))

    def boom(account_id):
        raise RuntimeError("database is locked")

    monkeypatch.setattr(db, "group_activity", boom)
    resp = client.get("/admin/groups?account_id=acc-a")
    assert resp.status_code == 200 and "chưa đăng lần nào" in resp.text and ">Nhóm</a>" in resp.text
    added = client.post("/admin/groups/add", data={"account_id": "acc-a", "name": "N2", "url": "https://www.facebook.com/groups/2"}, headers={"hx-request": "true"})
    assert added.status_code == 200


def test_search_text_is_folded_so_unaccented_typing_finds_accented_names(client):
    import unicodedata
    assert admin_module._fold_vi("Việc làm Đà Nẵng") == "viec lam da nang" and admin_module._fold_vi("KỸ SƯ") == "ky su"
    assert admin_module._fold_vi(unicodedata.normalize("NFD", "Việc làm")) == admin_module._fold_vi(unicodedata.normalize("NFC", "Việc làm")) == "viec lam"
    save_groups(*[(f"Việc làm {i}", f"https://www.facebook.com/groups/{i}") for i in range(9)])
    text = groups_page(client)
    assert 'data-search="viec lam 0 https://www.facebook.com/groups/0"' in text and "function foldVi" in text and 'normalize("NFD")' in text


def test_a_vanity_slug_matches_whatever_its_case(client):
    save_groups(("Nhóm", "https://www.facebook.com/groups/VietLam"))
    log("https://www.facebook.com/groups/vietlam")
    assert "Đã đăng 1 bài" in groups_page(client)
    assert admin_module._group_key("https://www.facebook.com/groups/VietLam") == admin_module._group_key("https://www.facebook.com/groups/vietlam")


def test_pressing_enter_in_the_rate_limit_dialog_saves_it_never_resets_it():
    """Enter submits with the FIRST submit button of the form: that must be Lưu, not "Khôi phục mặc định" (which drops the override)."""
    form = re.search(r'<form method="post" action="/admin/accounts/rate-limits".*?</form>', _modal(), re.S).group(0)
    submits = re.findall(r'<button type="submit"[^>]*>', form)
    assert submits[0] == '<button type="submit">' and 'name="reset"' in submits[1] and len(submits) == 2
    assert form.index(">Lưu</button>") < form.index('name="reset"')
    assert "flex-row-reverse" in admin_module._PAGE_STYLE.split(".rl-actions {")[1].split("}")[0]


def test_the_dialog_shows_exactly_the_fields_the_save_route_needs():
    assert sorted(re.findall(r'<input type="number"[^>]*? name="(\w+)"', _modal())) == sorted(runtime_config.EDITABLE_RATE_LIMITS_FIELDS)
    assert sorted(admin_module._RATE_LIMITS_LABELS) == sorted(runtime_config.EDITABLE_RATE_LIMITS_FIELDS)


def test_password_and_delay_boxes_have_accessible_names():
    box = admin_module._password_input_html("p", label="Mật khẩu mới")
    assert 'aria-label="Mật khẩu mới"' in box and 'aria-pressed="false"' in box and "'Ẩn mật khẩu' : 'Hiện mật khẩu'" in box
    modal = _modal()
    assert 'aria-label="Giữa 2 bài đăng: tối thiểu (giây)"' in modal and 'aria-label="Giữa 2 comment: tối đa (giây)"' in modal
    assert 'aria-label="Nhập lại mật khẩu"' in admin_module._mod_user_add_modal_html() and 'aria-label="Mật khẩu"' in admin_module._login_page_html("/admin", False)


def test_no_dead_attributes_or_classes_are_left(client):
    save_groups(*[(f"G{i}", f"https://www.facebook.com/groups/{i}") for i in range(9)])
    text = body(groups_page(client))
    assert "data-filter-list" not in text and "data-group-row" not in text and "data-filter-row" in text
    assert "login-card" not in admin_module._login_page_html("/admin", False)
