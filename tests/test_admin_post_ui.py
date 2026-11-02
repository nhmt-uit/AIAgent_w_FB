"""The Đăng bài page after the 2026-11-02 UI round: tab order and the tab that stays put when the account changes,
compact compose forms (grid + hints), the account named once next to each submit button, the live "Sẽ tạo N bài"
count, links back to Lịch đăng, and one-<span> banners so they don't break into a column on a phone.

The typed-text-survives-a-reload behaviour is JavaScript (sessionStorage) and was checked in a real browser; here we
pin the server-rendered hooks it relies on."""
from __future__ import annotations

import re
from dataclasses import dataclass
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import human_bot.admin as admin_module
from human_bot import content_strategist
from human_bot.config import AccountStatus, GroupRef, RateLimits
from tests.test_admin_post import _make_test_app


@dataclass
class _FakeAccount:
    account_id: str
    rate_limits: RateLimits
    action_log_path: Path
    display_name: str = "Acc A"
    sponsored_only: bool = False
    status: object = AccountStatus.ACTIVE


GROUPS = [GroupRef(name=f"Group <{i}>", url=f"https://facebook.com/groups/{i}") for i in range(3)]


@pytest.fixture
def accounts(tmp_path):
    return {
        "acc-a": _FakeAccount("acc-a", RateLimits(posts_per_day=30, max_groups_per_post=2), tmp_path / "a.jsonl"),
        "acc-b": _FakeAccount("acc-b", RateLimits(posts_per_day=30, max_groups_per_post=3), tmp_path / "b.jsonl", display_name="Acc B"),
    }


@pytest.fixture
def client(isolated_runtime_config, isolated_schedule_dirs, monkeypatch, accounts):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(admin_module, "get_all_accounts", lambda: accounts)
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: GROUPS)
    monkeypatch.setattr(content_strategist, "ai_provider_configured", lambda: True)
    return TestClient(_make_test_app(), follow_redirects=False)


def _active_tab(html: str) -> str:
    return re.search(r'<button type="button" class="tab-btn active" data-tab-target="tab-(\w+)"', html).group(1)


def _panel(html: str, key: str) -> str:
    start = html.index(f'id="tab-{key}"')
    nxt = html.find('class="tab-panel"', start + 10)
    return html[start: nxt if nxt != -1 else len(html)]


# --- tabs -----------------------------------------------------------------------------------------------------------------

def test_job_posts_come_first_and_are_the_default_tab(client):
    page = client.get("/admin/post").text
    labels = re.findall(r'<button type="button" class="tab-btn(?: active)?" data-tab-target="tab-\w+">([^<]+)</button>', page)
    assert [l.split(" ", 1)[1] for l in labels] == ["Tin tuyển dụng", "Đăng vào nhóm", "Bình luận", "Tường cá nhân"]
    assert _active_tab(page) == "job"
    assert "hidden" not in re.search(r'<div class="tab-panel" id="tab-job"([^>]*)>', page).group(1)


@pytest.mark.parametrize("asked, shown", [
    ("job", "job"), ("group", "group"), ("comment", "comment"), ("profile", "profile"),
    ("tab-group", "group"),            # what the account switcher used to send: the button's target id
    ("tab-profile", "profile"), ("nonsense", "job"), ("", "job"),
])
def test_tab_param_picks_the_panel_and_accepts_the_button_id_form(client, asked, shown):
    assert _active_tab(client.get(f"/admin/post?tab={asked}").text) == shown


def test_switching_account_asks_for_the_tab_by_its_key_not_the_button_id(client):
    page = client.get("/admin/post").text
    assert 'replace(/^tab-/, "")' in page and "writePostDraft(true)" in page         # the JS sends tab=job, and stashes the draft first
    assert 'id="post-account-form"' in page and "data-preserve-post-form" in page


def test_the_account_picker_says_which_account_will_post(client):
    page = client.get("/admin/post?account_id=acc-b").text
    assert "Đăng bằng tài khoản" in page
    assert page.count('<span class="post-as">Đăng bằng <b>Acc B (acc-b)</b></span>') == 4       # next to every submit button
    assert "Soạn cho tài khoản" not in page


def test_card_titles_no_longer_repeat_the_account_name(client):
    page = client.get("/admin/post?account_id=acc-b").text
    for title in ("📋 Tin tuyển dụng</h2>", "👥 Đăng vào nhóm</h2>", "💬 Bình luận</h2>", "👤 Tường cá nhân</h2>"):
        assert f"<h2>{title}" in page
    assert not re.search(r"<h2>[^<]*acc-b", page)


# --- job form -------------------------------------------------------------------------------------------------------------

def test_job_form_keeps_every_field_name_the_server_reads(client):
    job = _panel(client.get("/admin/post?tab=job").text, "job")
    for name in ("account_id", "title", "company", "location", "visa", "jlpt", "salary_min", "salary_max", "salary_period", "extra_info", "group_count"):
        assert f'name="{name}"' in job
    assert 'name="mode" value="ai"' in job and 'name="mode" value="template"' in job
    assert re.findall(r'<option value="(\w+)">/ ', job) == ["month", "year", "hour"]


def test_job_form_is_a_grid_with_the_short_fields_side_by_side(client):
    job = _panel(client.get("/admin/post?tab=job").text, "job")
    assert job.count('class="form-grid"') == 1
    wide = re.findall(r'<(?:label|div) class="fg span-2"><span class="fg-label">([^<]+)', job)
    narrow = re.findall(r'<label class="fg"><span class="fg-label">([^<]+)', job)
    assert narrow == ["Công ty", "Địa điểm", "Visa", "JLPT"]
    assert wide == ["Tiêu đề / vị trí ", "Lương", "Thông tin thêm", "Số nhóm sẽ đăng"]       # (the required star is a span of its own)
    assert 'class="req">*</span>' in job


def test_the_salary_hint_matches_what_the_server_stores_and_every_variant_ships_for_the_script(client):
    job = _panel(client.get("/admin/post?tab=job").text, "job")
    shown = re.search(r'<span class="fg-hint" data-salary-hint>([^<]+)', job).group(1)
    assert shown == admin_module._SALARY_HINT_ANY and "man" in shown and "yên" in shown       # without JS: all three periods in one line
    attrs = dict(re.findall(r'data-hint-(\w+)="([^"]+)"', job))
    assert set(attrs) == {"month", "year", "hour"} and attrs["hour"] == "Nhập số yên: 1500 nghĩa là 1.500 yên mỗi giờ."
    # the month/year examples are the conversion _build_manual_job really applies (25 man a month = 250.000 yên)
    assert "25 nghĩa là 25万 = 250.000 yên mỗi tháng" in attrs["month"] and "300 nghĩa là 300万 = 3.000.000 yên mỗi năm" in attrs["year"]
    job_dict = admin_module._build_manual_job({"title": "T", "salary_min": "25", "salary_period": "month"})
    assert job_dict["attributes"]["salary"]["min"] == 250_000 == 25 * content_strategist.YEN_PER_MAN
    assert admin_module._build_manual_job({"title": "T", "salary_min": "1500", "salary_period": "hour"})["attributes"]["salary"]["min"] == 1500


def test_each_submit_button_says_what_it_does_and_a_missing_ai_key_is_said_before_the_click(client, monkeypatch):
    job = _panel(client.get("/admin/post?tab=job").text, "job")
    assert "mỗi nhóm một bài viết khác nhau" in job and "khung mẫu có sẵn, nhanh, không dùng AI" in job
    assert "chưa có khoá AI" not in job

    monkeypatch.setattr(content_strategist, "ai_provider_configured", lambda: False)
    job = _panel(client.get("/admin/post?tab=job").text, "job")
    assert 'chưa có khoá AI ở <a href="/admin/config?tab=ai">Cấu hình → AI</a> — nút này sẽ dùng template' in job
    assert 'name="mode" value="ai"' in job                                            # still clickable: it falls back, as before


def test_group_count_is_capped_by_the_accounts_limit(client):
    job = _panel(client.get("/admin/post?account_id=acc-a&tab=job").text, "job")
    assert 'name="group_count" min="1" max="2" value="2"' in job and "Tối đa 2 (giới hạn của tài khoản; đã tham gia 3 nhóm)" in job


def test_the_job_description_has_no_doubled_word(client):
    assert "thông tin tin tuyển dụng" not in client.get("/admin/post?tab=job").text


# --- group form -----------------------------------------------------------------------------------------------------------

def test_group_form_lists_escaped_pills_and_the_live_count_hook(client):
    group = _panel(client.get("/admin/post?tab=group").text, "group")
    assert group.count('class="group-pill"') == 3 and "Group &lt;0&gt;" in group and "Group <0>" not in group
    assert "data-post-count-form" in group and 'data-post-count aria-live="polite"' in group
    assert 'name="groups_0"' in group and "data-select-all-groups" in group and "data-add-block" in group


def test_group_form_prefill_from_a_report_still_ticks_the_group_and_fills_the_text(client):
    group = _panel(client.get("/admin/post?tab=group&prefill_content=Xin+chao&prefill_target_url=https://facebook.com/groups/1").text, "group")
    assert ">Xin chao</textarea>" in group
    assert re.search(r'name="groups_0" value="https://facebook.com/groups/1" checked', group)
    assert group.count(" checked") == 1


def test_group_empty_state_points_at_the_groups_page_in_plain_words(client, monkeypatch):
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: [])
    group = _panel(client.get("/admin/post?account_id=acc-a&tab=group").text, "group")
    assert 'href="/admin/groups?account_id=acc-a">thêm ở “Nhóm đã tham gia”</a>' in group and "form" not in group.replace("form-grid", "")


# --- other tabs -----------------------------------------------------------------------------------------------------------

def test_comment_form_is_labelled_and_the_url_field_is_styled_like_the_others(client):
    comment = _panel(client.get("/admin/post?tab=comment").text, "comment")
    assert "URL bài đăng/hồ sơ cần bình luận" in comment and "Nội dung bình luận" in comment and 'type="url" name="target_url"' in comment
    assert 'style=' not in re.search(r'<input type="url"[^>]*>', comment).group(0)      # no per-field inline sizing any more
    assert "input[type=url]" in admin_module._PAGE_STYLE


def test_profile_form_keeps_the_hooks_that_carry_its_text_and_time_across_an_account_switch(client):
    page = client.get("/admin/post?tab=profile&profile_content=Hi&profile_scheduled_at=2026-11-05T01:00:00Z").text
    profile = _panel(page, "profile")
    assert ">Hi</textarea>" in profile and "data-preserve-profile-content" in profile and "data-preserve-profile-schedule" in profile
    assert 'value="2026-11-05T01:00:00Z"' in profile


# --- messages -------------------------------------------------------------------------------------------------------------

def test_success_messages_link_to_the_schedule(client):
    scheduled = client.get("/admin/post?scheduled=3").text
    assert '<div class="flash">✅ Đã lên lịch. <a href="/admin/schedule">Mở Lịch đăng →</a> để xem, sửa hoặc đăng ngay.</div>' in scheduled
    posted = client.get("/admin/post?tab=job&posted=Đã+tạo+2+bài+<b>").text
    assert "Đã tạo 2 bài &lt;b&gt;. " in posted and '<a href="/admin/schedule">Mở Lịch đăng →</a></div>' in posted


def test_errors_are_escaped(client):
    page = client.get("/admin/post?error=<script>x</script>").text
    assert "<script>x</script>" not in page and '<div class="error">⚠️ &lt;script&gt;x&lt;/script&gt;</div>' in page


def test_banners_are_blocks_so_a_sentence_with_bold_and_links_stays_one_line_of_text():
    """.flash/.error/.warning used to be flex rows: <strong> and <a> inside a sentence each became their own column
    (ragged on a phone). Nothing in the admin puts a button or a form inside one, so a plain block is right."""
    css = admin_module._PAGE_STYLE
    rule = re.search(r"\.flash, \.error, \.warning \{ ([^}]*)\}", css).group(1)
    assert "flex" not in rule and "gap-" not in rule
    banners = re.findall(r'<(div|p)\s+class="(?:flash|error|warning)"[^>]*>(.*?)</\1>', Path(admin_module.__file__).read_text(encoding="utf-8"), re.S)
    assert banners and not [inner for _tag, inner in banners if re.search(r"<(button|form|input|select)\b", inner)]


def test_banners_for_a_stopped_account(client, accounts):
    for status, css, word in ((AccountStatus.DISABLED, "warning", "tắt"), (AccountStatus.PAUSED, "error", "Tạm dừng")):
        accounts["acc-a"].status = status
        page = client.get("/admin/post?account_id=acc-a").text
        assert re.search(rf'<div class="{css}">[^<]*<strong>{word}</strong>', page)


def test_auto_fire_notice_in_both_states(monkeypatch):
    for on, css, word in ((True, "flash", "Đang bật"), (False, "error", "Đang tắt")):
        monkeypatch.setattr(admin_module, "get_scheduling_config", lambda on=on: type("C", (), {"auto_fire_enabled": on})())
        html = admin_module._auto_fire_status_html()
        assert html.startswith(f'<div class="{css}">') and f"<strong>{word}</strong>" in html
    assert 'href="/admin/config"' in html


def test_server_errors_name_pages_not_url_paths(client, monkeypatch):
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: [])
    resp = client.post("/admin/post/schedule-job", data={"account_id": "acc-a", "title": "T", "mode": "template"})
    error = parse_qs(urlparse(resp.headers["location"]).query)["error"][0]
    assert error == "Tài khoản này chưa tham gia nhóm nào — thêm ở “Nhóm đã tham gia” trước"


def test_the_duplicate_job_error_names_the_schedule_page_not_its_url(client):
    form = {"account_id": "acc-a", "title": "Vận hành máy", "group_count": "1", "mode": "template"}
    assert "posted" in parse_qs(urlparse(client.post("/admin/post/schedule-job", data=form).headers["location"]).query)
    error = parse_qs(urlparse(client.post("/admin/post/schedule-job", data=form).headers["location"]).query)["error"][0]
    assert error == "Tin này đã được lên lịch rồi và còn bài đang chờ đăng — xem ở Lịch đăng"


# --- shared CSS ------------------------------------------------------------------------------------------------------------

def test_compose_form_css_is_there():
    css = admin_module._PAGE_STYLE
    for rule in (".form-grid { @apply grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-2; }", ".form-grid > .span-2 { @apply sm:col-span-2; }",
                 ".group-pill:has(input:checked)", ".post-actions {", ".mode-opt {", ".post-count.post-count-empty"):
        assert rule in css


def test_the_man_to_yen_rule_has_one_home():
    """The form's hint, the conversion that stores the salary and the post text all read content_strategist's constant."""
    assert content_strategist.YEN_PER_MAN == 10000 and content_strategist.MAN_PERIOD_KEYS == {"month", "year"}
    assert content_strategist._format_man(250_000) == "25" and content_strategist._format_man(15_000) == "1.5"
    assert f"{content_strategist.YEN_PER_MAN:,}".replace(",", ".") in admin_module._SALARY_HINTS["month"]


def test_admin_source_has_no_invalid_escape_sequences():
    """The page script lives in ordinary (non-raw) Python strings: a regex written \\d must be spelled \\\\d there, or Python 3.12+ warns
    (and a later release refuses to import the module)."""
    import warnings
    src = Path(admin_module.__file__).read_text(encoding="utf-8")
    with warnings.catch_warnings():
        warnings.simplefilter("error")
        compile(src, "admin.py", "exec")
