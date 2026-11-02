"""/admin/reports after the 2026-11-02 UI round: tabs (a new "Lỗi" tab), number tiles, the "Tổng quan" tab's bars
(causes, weeks, actions, groups), and one row look for every attempt (what, where, why it failed in words).

Rows are seeded straight into action_log (isolated_db); group names come from a patched saved-groups list."""
from __future__ import annotations

import html as html_lib
import json
import re
from urllib.parse import parse_qs, urlparse
from datetime import date, datetime, timedelta, timezone

import pytest
from fastapi.testclient import TestClient

import human_bot.admin as admin_module
from human_bot import db, failure_info
from human_bot.config import GroupRef
from tests.test_admin_post import _make_test_app

TIMEOUT = 'error:Locator.wait_for: Timeout 30000ms exceeded.\nCall log:\n  - waiting for get_by_role("button", name="Đăng")'
OFFLINE = "error:Page.goto: net::ERR_INTERNET_DISCONNECTED at https://www.facebook.com/groups/1"
NOT_CONFIRMED = "post_still_visible_after_click: composer still open"
GROUP_URL = "https://www.facebook.com/groups/1383875949915495"


@pytest.fixture
def client(isolated_runtime_config, isolated_schedule_dirs, isolated_db, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: [GroupRef(name="Việc làm Kỹ Sư <Nhật>", url=GROUP_URL)])
    return TestClient(_make_test_app(), follow_redirects=False)


def log(*, ok=True, action="post_to_group", account="acc-a", message="", url=GROUP_URL, name=None, content="Nội dung bài", at=None,
        source="schedule_auto", **extra):
    return db.log_action(
        account_id=account, action=action, success=ok, message=message, target_url=url, target_group_name=name, content=content,
        source=source, created_at=(at or datetime.now(timezone.utc)).isoformat(), **extra,
    )


def page(client, **params) -> str:
    qs = "&".join(f"{k}={v}" for k, v in params.items())
    resp = client.get(f"/admin/reports?{qs}")
    assert resp.status_code == 200
    return resp.text


def tiles(text: str) -> dict[str, str]:
    return {m.group(2): m.group(0) for m in re.finditer(r'<(a|div) class="stat[^"]*"[^>]*><span class="stat-label">([^<]+)</span>.*?</\1>', text, re.S)}


# --- tabs -----------------------------------------------------------------------------------------------------------------

def test_tabs_are_the_shared_tab_style_in_a_clear_order_with_the_failure_count(client):
    log(); log(ok=False, message=TIMEOUT); log(ok=False, message=OFFLINE)
    text = page(client)
    labels = re.findall(r'<a href="/admin/reports\?[^"]*" hx-get[^>]*class="sched-tab(?: active)?">(.*?)</a>', text)
    assert [l.split(" <span")[0] for l in labels] == ["📊 Tổng quan", "📮 Bài đăng", "💬 Bình luận", "🕒 Hoạt động", "⚠️ Lỗi", "⚙️ Thời hạn lưu"]
    assert '<span class="badge badge-bad">2</span>' in labels[4] and "badge" not in "".join(labels[:4] + labels[5:])
    assert text.count('class="sched-tab active"') == 1 and "border-bottom:2px solid #111827" not in text    # no hand-styled tab links any more


@pytest.mark.parametrize("asked, active", [("tables", "Tổng quan"), ("recent", "Hoạt động"), ("failures", "Lỗi"), ("settings", "Thời hạn lưu"), ("junk", "Tổng quan")])
def test_active_tab(client, asked, active):
    assert active in re.search(r'class="sched-tab active">(.*?)</a>', page(client, tab=asked)).group(1)


def test_filters_and_page_size_carry_the_failures_tab_through(client):
    text = page(client, tab="failures", account_id="acc-a", days="30")
    assert text.count('hx-vals=\'{"tab": "failures"}\'') == 3                      # account, days and page-size selects
    assert 'href="/admin/reports?account_id=acc-a&days=30&tab=tables"' in text    # the other tabs keep the filters


def test_settings_tab_still_skips_filters_and_numbers(client):
    text = page(client, tab="settings")
    assert 'class="stat' not in text and "reports-account-select" not in text and "Thời hạn lưu dữ liệu" in text


# --- number tiles ---------------------------------------------------------------------------------------------------------

def test_tiles_only_the_failure_one_is_a_link_and_it_goes_to_the_failures_tab_with_the_filters(client):
    log(); log(ok=False, message=TIMEOUT)
    t = tiles(page(client, account_id="acc-a", days="7"))
    assert t["Tổng số lần chạy"].startswith("<div") and t["Thành công"].startswith("<div") and t["Tài khoản có hoạt động"].startswith("<div")
    assert t["Thất bại"].startswith('<a class="stat stat-attn" href="/admin/reports?account_id=acc-a&days=7&tab=failures">')
    assert "xem các lần lỗi" in t["Thất bại"] and "7 ngày qua" in t["Tổng số lần chạy"]


def test_a_clean_period_shows_a_calm_failure_tile(client):
    log()
    tile = tiles(page(client))["Thất bại"]
    assert "stat-attn" not in tile and "không có lỗi" in tile and ">0<" in tile


def test_a_rate_limited_deferral_is_not_a_failure_anywhere(client):
    log(ok=False, message="rate_limited: gap not reached")
    text = page(client)
    assert ">0<" in tiles(text)["Thất bại"] and 'badge badge-bad">' not in re.search(r'class="sched-tabs">.*?</div>', text, re.S).group(0)
    assert "Không có lần nào thất bại" in page(client, tab="failures")
    recent = page(client, tab="recent")
    assert "⏳ Chưa chạy" in recent and "bị giới hạn tốc độ" in recent and "hạn mức giờ/ngày" in recent


# --- db -------------------------------------------------------------------------------------------------------------------

def test_failed_filter_agrees_with_the_failed_number(isolated_db):
    log(); log(ok=False, message=TIMEOUT); log(ok=False, message=OFFLINE, account="acc-b"); log(ok=False, message="rate_limited: x"); log(ok=False, message="")
    stats = db.summary_stats()
    failed = db.recent_activity(only_failed=True)
    assert stats["failed"] == len(failed) == db.recent_activity_count(only_failed=True) == 3
    assert all(not r["success"] and not (r["message"] or "").startswith("rate_limited:") for r in failed)
    assert db.recent_activity_count(account_id="acc-b", only_failed=True) == 1 and db.recent_activity_count() == 5
    assert sorted(db.failure_message_counts()) == sorted([("", 1), (TIMEOUT, 1), (OFFLINE, 1)])
    assert db.failure_message_counts(account_id="acc-b") == [(OFFLINE, 1)]
    assert sum(n for _m, n in db.failure_message_counts()) == stats["failed"]               # the breakdown adds up to the tile


def test_failed_filter_respects_the_time_window(isolated_db):
    log(ok=False, message=TIMEOUT, at=datetime.now(timezone.utc) - timedelta(days=40)); log(ok=False, message=OFFLINE)
    since = (datetime.now(timezone.utc) - timedelta(days=7)).isoformat()
    assert db.recent_activity_count(since=since, only_failed=True) == 1 and db.failure_message_counts(since=since) == [(OFFLINE, 1)]


# --- the rows -------------------------------------------------------------------------------------------------------------

def test_a_success_is_a_tick_and_a_failure_says_why_in_words_with_the_raw_error_one_click_away(client):
    log(); log(ok=False, message=TIMEOUT)
    text = page(client, tab="recent")
    assert text.count('title="Thành công">✅</span>') == 1 and "badge-ok" not in text.split('class="sched-list"')[1]
    assert '<span class="badge badge-bad">⚠️ Thất bại</span>' in text
    assert "Không thấy ô/nút cần bấm (hết thời gian chờ)" in text and "bài chưa lên — thử lại được" in text
    rows = text.split('<div class="sched-list">')[1]
    assert '<details class="rep-tech"><summary>Chi tiết kỹ thuật</summary><pre>' in rows and "Locator.wait_for" in rows.split("<pre>")[1]


def test_the_note_names_what_is_unknown_and_what_cannot_be_retried(client):
    log(ok=False, message=NOT_CONFIRMED); log(ok=False, message="anomaly_detected: checkpoint")
    text = html_lib.unescape(page(client, tab="failures"))
    assert "Facebook không xác nhận sau khi bấm Đăng" in text and "nên xem trên Facebook trước khi đăng lại" in text
    assert "checkpoint" in text and "cần xử lý nguyên nhân trước khi thử lại" in text
    for info in (failure_info.classify(NOT_CONFIRMED), failure_info.classify("anomaly_detected: x")):
        assert info.safety in failure_info.SAFETY_HINT


def test_raw_errors_are_escaped(client):
    log(ok=False, message="error:<script>alert(1)</script>")
    text = page(client, tab="failures")
    assert "<script>alert(1)</script>" not in text and "&lt;script&gt;alert(1)&lt;/script&gt;" in text


def test_the_target_is_a_name_never_a_raw_url(client):
    log(url=GROUP_URL + "/", content="a")                                                    # no recorded name -> the saved group's
    log(url="https://www.facebook.com/groups/777", name="Tên đã ghi", content="b")
    log(url="https://www.facebook.com/groups/555", content="c")                              # unknown group -> its id
    log(action="comment_on_group_post", url=GROUP_URL + "/posts/998877", content="d")
    log(action="comment_on_friend_post", url="https://www.facebook.com/someone/posts/4242", content="e")
    log(action="post_to_own_profile", url=None, content="f")
    text = page(client, tab="recent")
    for label in ("Việc làm Kỹ Sư &lt;Nhật&gt;", "Tên đã ghi", ">555<", "bài trong Việc làm Kỹ Sư &lt;Nhật&gt;", "bài viết …424", "Tường cá nhân"):
        assert label in text, label
    assert not re.search(r">https?://[^<]+<", text)                                          # URLs live in href/title only


def test_source_labels_are_words_not_paths():
    assert all("/" not in label and "(" not in label.replace("(n8n)", "") for label in admin_module._SOURCE_LABELS.values())
    assert admin_module._SOURCE_LABELS["manual"] == "Đăng tay" and admin_module._SOURCE_LABELS["schedule_auto"] == "Tự động"


def test_the_failures_tab_lists_only_failures_and_keeps_the_retry_button(client):
    log(content="ok one"); log(ok=False, message=TIMEOUT, content="broken one")
    text = page(client, tab="failures")
    assert "broken one" in text and "ok one" not in text
    assert 'title="Đăng lại"' in text and "Các lần thất bại" in text and "1 mục" in text
    assert "hx-vals='{\"tab\": \"failures\"}'" in text


def test_the_failures_list_paginates_and_the_pager_stays_on_the_tab(client):
    for i in range(17):
        log(ok=False, message=TIMEOUT, content=f"fail {i}", at=datetime.now(timezone.utc) - timedelta(minutes=i))
    first = page(client, tab="failures")
    assert first.count('class="rep-line"') == 15 and "/ 2" in first and "17 mục" in first
    assert 'href="/admin/reports?tab=failures&page=2"' in first and '<input type="hidden" name="tab" value="failures">' in first
    assert page(client, tab="failures", page=2).count('class="rep-line"') == 2


def test_a_retried_failure_shows_its_state_instead_of_the_button(client):
    row = log(ok=False, message=TIMEOUT)
    log(ok=True, source="schedule_manual", retry_of_log_id=row)
    text = page(client, tab="failures")
    assert "✅ Đã đăng lại" in text and 'title="Đăng lại"' not in text


# --- Tổng quan ------------------------------------------------------------------------------------------------------------

def test_week_labels_are_date_ranges_and_fall_back_to_the_raw_label():
    assert admin_module._week_range_label("2026-10-26", date(2026, 10, 28)) == ("26/10 – 01/11", True)
    assert admin_module._week_range_label("2026-10-26", date(2026, 11, 1)) == ("26/10 – 01/11", True)       # the Sunday is still that week
    assert admin_module._week_range_label("2026-10-26", date(2026, 11, 2)) == ("26/10 – 01/11", False)
    assert admin_module._week_range_label("2025-12-29", date(2026, 1, 3)) == ("29/12 – 04/01", True)        # across New Year
    assert admin_module._week_range_label("garbage", date(2026, 6, 1)) == ("garbage", False)


def test_one_calendar_week_is_one_key_even_across_new_year(isolated_db):
    """The old strftime('%Y-W%W') split 29 Dec - 4 Jan into "2025-W52" and "2026-W00"."""
    for day in ((2025, 12, 29), (2025, 12, 31), (2026, 1, 1), (2026, 1, 4), (2026, 1, 5)):          # Mon, Wed, Thu, Sun, then the next Monday
        log(at=datetime(*day, 12, 0, tzinfo=timezone.utc))
    rows = {r["week"]: r["total"] for r in db.weekly_post_counts()}
    assert rows == {"2025-12-29": 4, "2026-01-05": 1}
    assert all(datetime.strptime(week, "%Y-%m-%d").weekday() == 0 for week in rows)                 # always a Monday
    assert {r["week"] for r in db.weekly_post_counts(since=datetime(2026, 1, 2, tzinfo=timezone.utc).isoformat())} == {"2025-12-29", "2026-01-05"}


def test_weekly_table_is_one_row_per_week_with_a_column_per_account_and_a_total_bar(client):
    now = datetime.now(timezone.utc)
    for i in range(3):
        log(account="acc-a", at=now); log(account="acc-b", at=now)
    log(account="acc-a", at=now - timedelta(days=8))
    text = page(client)
    weekly = text.split("Bài đăng thành công theo tuần")[1].split("</table>")[0]
    assert re.findall(r'<th class="num">([^<]+)</th>', weekly) == ["acc-a", "acc-b"]            # the busier account first
    rows = re.findall(r'<tr><td class="nowrap">.*?</tr>', weekly, re.S)
    assert len(rows) == 2 and "đang diễn ra" in rows[0] and "đang diễn ra" not in rows[1]
    assert re.findall(r'class="bar-val">(\d+)', rows[0]) == ["6"] and "--w:1.0000" in rows[0] and "--w:0.1667" in rows[1]
    assert "2026-W" not in weekly and "W4" not in weekly


def test_the_weekly_table_folds_its_account_columns_into_the_total_cell_for_a_phone(client):
    now = datetime.now(timezone.utc)
    for _ in range(2):
        log(account="acc-a", at=now)
    log(account="acc-b", at=now)
    weekly = page(client).split("Bài đăng thành công theo tuần")[1].split("</table>")[0]
    assert '<div class="wk-split">acc-a 2 · acc-b 1</div>' in weekly and 'class="data-table rep-weekly"' in weekly
    css = admin_module._PAGE_STYLE
    assert ".data-table.rep-weekly { min-width: 0; }" in css and ".rep-weekly .num { display: none; }" in css and ".wk-split { display: block;" in css


def test_a_single_account_gets_no_account_columns(client):
    log(account="acc-a")
    weekly = page(client, account_id="acc-a").split("Bài đăng thành công theo tuần")[1].split("</table>")[0]
    assert '<th class="num">' not in weekly and "<th>Tuần</th><th>Tổng số bài</th>" in weekly


def test_the_causes_card_counts_by_cause_and_only_exists_with_failures(client):
    log()
    assert "Lỗi theo nguyên nhân" not in page(client)
    for message in (TIMEOUT, TIMEOUT, OFFLINE, NOT_CONFIRMED, TIMEOUT):
        log(ok=False, message=message)
    card = page(client).split("Lỗi theo nguyên nhân")[1].split("Thành công / thất bại theo hành động")[0]
    rows = re.findall(r'<div class="bar-label">([^<]+)<span class="bar-sub">([^<]+)</span></div>.*?class="bar-val">(\d+)', card, re.S)
    assert rows[0] == ("Không thấy ô/nút cần bấm (hết thời gian chờ)", "bài chưa lên — thử lại được, nhưng lỗi kiểu này hay lặp lại", "3")
    assert {r[0] for r in rows[1:]} == {"Máy mất mạng khi vào Facebook", "Facebook không xác nhận sau khi bấm Đăng"} and sum(int(r[2]) for r in rows) == 5
    assert "tab=failures" in card and "Xem từng lần lỗi" in card


def test_actions_card_is_a_split_bar_with_the_rate_and_a_legend(client):
    for _ in range(3):
        log()
    log(ok=False, message=TIMEOUT)
    card = page(client).split("Thành công / thất bại theo hành động")[1].split("Bài đăng theo nhóm")[0]
    assert "Thành công</span>" in card and "Thất bại</span>" in card                           # the legend: the two dots are named
    assert '<span class="split-ok" style="flex:3"></span><span class="split-bad" style="flex:1"></span>' in card
    assert "3 <span class=\"dot dot-bad\"></span>1 · 75%" in card


def test_groups_card_shows_names_ranked_with_the_top_ten_and_the_rest_folded(client):
    for i in range(12):
        for _ in range(12 - i):
            log(url=f"https://www.facebook.com/groups/{100 + i}", name=f"Nhóm số {i}")
    log(url=GROUP_URL)                                                                         # no recorded name: the saved one
    card = page(client).split("Bài đăng theo nhóm")[1]
    top = card.split('<details class="rep-more">')[0]
    assert top.count('class="bar-row"') == 10 and "Nhóm số 0" in top and "Nhóm số 9" in top and "Nhóm số 10" not in top
    assert '<details class="rep-more"><summary>Xem thêm 3 nhóm</summary>' in card and "Nhóm số 11" in card and "Việc làm Kỹ Sư &lt;Nhật&gt;" in card
    assert "(chưa rõ tên)" not in card and "--w:1.0000" in card


def test_groups_name_the_account_only_when_there_are_several(client):
    log(account="acc-a", name="G")
    assert 'sched-acct">· acc-a' not in page(client).split("Bài đăng theo nhóm")[1]
    log(account="acc-b", name="G")
    assert 'sched-acct">· acc-a' in page(client).split("Bài đăng theo nhóm")[1]


def test_empty_database_overview_still_renders(client):
    text = page(client)
    assert "Chưa có bài đăng thành công nào được ghi nhận." in text and "Chưa có dữ liệu." in text and "Lỗi theo nguyên nhân" not in text


# --- Bài đăng / Bình luận -------------------------------------------------------------------------------------------------

JOB = {"title": "Thợ hàn <Aichi>", "attributes": {"company": "ABC", "salary": {"min": 220000, "max": 280000, "currency": "JPY", "period": "month"}}}


def test_salary_reads_in_words_whatever_its_shape():
    text = admin_module._salary_text
    assert text(JOB["attributes"]["salary"]) == "22–28 man / tháng"
    assert text({"min": 3000000, "max": 3000000, "currency": "JPY", "period": "year"}) == "300 man / năm"
    assert text({"min": 1500, "currency": "JPY", "period": "hour"}) == "1.500 yên / giờ"
    assert text({"max": 250000, "period": "month"}) == "25 man / tháng" and text({"min": 215000, "period": "month"}) == "21.5 man / tháng"
    assert text({"min": 100, "currency": "USD", "period": "hour"}) == "100 USD / giờ" and text({"min": None, "max": None}) == ""
    assert text("tùy năng lực") == "tùy năng lực"


def test_attrs_summary_never_prints_a_python_dict():
    out = admin_module._attrs_summary_html("T", {"company": "ABC", "salary": JOB["attributes"]["salary"], "extra": {"a": 1, "b": None}, "tags": ["x", "y"], "confidence": 0.5, "empty": ""})
    assert "Lương:</b> 22–28 man / tháng" in out and "{" not in out and "None" not in out
    assert "extra:</b> a: 1" in out and "tags:</b> x, y" in out and "Độ tin cậy:</b> 50%" in out and "empty" not in out


def test_job_card_leads_with_the_job_title_and_the_rows_inside_skip_what_the_card_already_says(client):
    for i, ok in enumerate((True, False)):
        log(ok=ok, message="" if ok else TIMEOUT, source_kind="job", source_id="j1", job_data=JOB, url=f"https://www.facebook.com/groups/{i}", content=f"nội dung {i}")
    text = page(client, tab="jobs")
    summary = re.search(r'<details class="rep-job">\s*<summary>(.*?)</summary>', text, re.S).group(1)
    assert "Thợ hàn &lt;Aichi&gt;" in summary and "acc-a · 2 nhóm" in summary and "1 thành công" in summary and "1 thất bại" in summary
    assert "Lương:</b> 22–28 man / tháng" in text and "{'min'" not in text
    inner = text.split('class="sched-list rep-job-rows"')[1]
    assert "acc-a" not in inner.split("</details>")[0] and "Đăng vào nhóm" not in inner.split("</details>")[0]   # one account, one action: said once
    assert "Không thấy ô/nút cần bấm" in inner and 'title="Đăng lại"' in inner


def test_job_without_data_says_so(client):
    log(source_kind="job", source_id="j2", job_data=None)
    text = page(client, tab="jobs")
    assert "(không có tiêu đề)" in text and "(không có dữ liệu gốc)" in text


def test_comments_tab_shows_the_candidates_own_data_above_the_comment(client):
    cand = {"attributes": {"desiredJobField": ["Cơ khí", "Điện"], "preferredRegion": "Kanto"}}
    log(action="comment_on_group_post", url=GROUP_URL + "/posts/5551212", source_kind="candidate", source_id="c1", job_data=cand, content="Ib mình nha")
    text = page(client, tab="candidates")
    assert "Muốn làm:</b> Cơ khí, Điện" in text and "Khu vực mong muốn:</b> Kanto" in text
    assert text.index("Muốn làm") < text.index("Ib mình nha") and "bài trong Việc làm" in text
    assert "Comment bài trong nhóm" not in text.split('class="sched-list"')[1]                 # every row is a comment: not repeated on each


# --- home -----------------------------------------------------------------------------------------------------------------

def test_home_failure_tile_leads_to_the_failures_tab(client):
    assert 'href="/admin/reports?tab=failures&days=7"><span class="stat-label">Lỗi chưa xử lý' in client.get("/admin").text


# --- styles -----------------------------------------------------------------------------------------------------------------

def test_chart_and_row_css_is_there():
    css = admin_module._PAGE_STYLE
    for rule in ("a.stat, div.stat {", ".bar-fill { display: block;", "width: calc((100% - 3rem) * var(--w, 0))", "border-radius: 0 4px 4px 0",
                 ".split-bar { display: flex; gap: 2px;", ".rep-bad { box-shadow", ".rep-line { @apply grid", ".rep-time { @apply text-sm text-gray-700 whitespace-nowrap",
                 ".rep-grid { @apply grid grid-cols-1 items-start"):
        assert rule in css, rule


# --- review fixes ---------------------------------------------------------------------------------------------------------

def test_causes_card_survives_an_empty_sample_and_says_when_it_is_a_partial_one(client, monkeypatch):
    log(ok=False, message=TIMEOUT); log(ok=False, message=OFFLINE); log(ok=False, message=OFFLINE)
    monkeypatch.setattr(db, "failure_message_counts", lambda **kw: [])                # e.g. cleaned up between the two reads
    assert client.get("/admin/reports").status_code == 200
    monkeypatch.setattr(db, "failure_message_counts", lambda **kw: [(OFFLINE, 1)])
    card = page(client).split("Lỗi theo nguyên nhân")[1].split("Thành công / thất bại theo hành động")[0]
    assert "Chỉ phân loại được 1 trong tổng số 3 lần lỗi." in card


def test_candidate_data_with_the_word_muted_in_it_is_still_shown(client):
    log(action="comment_on_group_post", url=GROUP_URL + "/posts/1", source_kind="candidate", source_id="c9", job_data={"attributes": {"company": "Muted Co"}})
    assert "Muted Co" in page(client, tab="candidates") and 'class="rep-extra"' in page(client, tab="candidates")


@pytest.mark.parametrize("attributes", [["x"], "text", 5, None])
def test_malformed_attributes_never_break_a_tab(client, attributes):
    log(source_kind="job", source_id="jx", job_data={"title": "T", "attributes": attributes})
    log(action="comment_on_group_post", url=GROUP_URL + "/posts/1", source_kind="candidate", source_id="cx", job_data={"attributes": attributes})
    for tab in ("jobs", "candidates"):
        assert client.get(f"/admin/reports?tab={tab}").status_code == 200


def test_salary_follows_the_same_rules_as_the_posts():
    text = admin_module._salary_text
    assert text({"min": 250000, "currency": "jpy", "period": "month"}) == "25 man / tháng"          # a lower-case currency is still yên
    assert text({"min": 250000, "currency": "", "period": "month"}) == "25 man / tháng" and text({"min": 250000, "currency": None}) == "250.000 yên"
    assert text({"min": 0, "max": 250000, "period": "month"}) == "25 man / tháng"                    # 0 is "missing", like _salary_line
    assert text({"min": 0, "max": 0}) == "" and text({"min": 100, "currency": "usd", "period": "hour"}) == "100 USD / giờ"


def test_lich_dang_and_bao_cao_name_a_target_the_same_way():
    from types import SimpleNamespace
    lookup = lambda account, url: "Tên nhóm" if "/groups/1" in url else None
    row = lambda action, url: {"action": action, "target_url": url, "account_id": "a", "target_group_name": None}
    for action, url in (("post_to_group", "https://www.facebook.com/groups/1"), ("post_to_group", "https://www.facebook.com/groups/9"),
                        ("comment_on_group_post", "https://www.facebook.com/groups/1/posts/123456789"), ("comment_on_friend_post", "https://www.facebook.com/x/posts/42"),
                        ("comment_on_group_post", "https://www.facebook.com/photo.php")):
        task = SimpleNamespace(action=action, account_id="a", target_url=url)
        assert admin_module._sched_target_html(task, lookup) == admin_module._log_target_html(row(action, url), lookup)


def test_a_job_card_counts_a_deferral_as_waiting_not_failed(client):
    log(source_kind="job", source_id="j3", job_data=JOB, url="https://www.facebook.com/groups/1")
    log(ok=False, message="rate_limited: gap", source_kind="job", source_id="j3", job_data=JOB, url="https://www.facebook.com/groups/2")
    summary = re.search(r'<details class="rep-job">\s*<summary>(.*?)</summary>', page(client, tab="jobs"), re.S).group(1)
    assert "1 thành công" in summary and "1 chưa chạy" in summary and "thất bại" not in summary


def test_the_job_card_has_a_visible_open_marker():
    css = admin_module._PAGE_STYLE
    assert '.rep-job > summary::before { content: "▸";' in css and '.rep-job[open] > summary::before { content: "▾"; }' in css


def test_non_link_tiles_get_the_amber_and_orphan_rules_too():
    css = admin_module._PAGE_STYLE
    assert ".stat.stat-attn { @apply bg-amber-50" in css and ".stat-row > .stat:last-child:nth-child(odd)" in css
    assert admin_module._stat_tile("x", "1", None, attention=True).startswith('<div class="stat stat-attn">')


def test_the_rate_limited_prefix_is_one_definition():
    """agent.py writes it, db.py's SQL and is_rate_limited() read it."""
    import inspect
    from human_bot import agent
    assert db.RATE_LIMITED_PREFIX == "rate_limited:" and db.is_rate_limited("rate_limited: x") and not db.is_rate_limited("error:x") and not db.is_rate_limited(None)
    assert "db.RATE_LIMITED_PREFIX" in inspect.getsource(agent)


# --- the retry dialog -----------------------------------------------------------------------------------------------------

def _dialog(client, message, **kw) -> str:
    row = log(ok=False, message=message, **kw)
    resp = client.get(f"/admin/reports/repost-choice?log_id={row}&tab=failures")
    assert resp.status_code == 200
    return resp.text


def test_dialog_for_a_safe_failure_has_no_warning_and_no_confirmation(client):
    text = _dialog(client, TIMEOUT)
    assert "🚀 Đăng ngay" in text and 'class="warning"' not in text and 'class="error"' not in text and "hx-confirm" not in text


def test_dialog_for_an_uncertain_failure_warns_and_asks_before_posting_again(client):
    text = _dialog(client, NOT_CONFIRMED)
    assert "chưa rõ bài đã lên Facebook chưa" in text and "bài trùng" in text
    assert 'hx-confirm="Bài này có thể đã lên Facebook rồi. Vẫn tiếp tục?"' in text


def test_dialog_for_an_unfixable_failure_says_what_to_fix_first_and_asks(client):
    text = html_lib.unescape(_dialog(client, "target_content_unavailable: gone"))
    assert "⛔" in text and "Bài đích không còn xem được" in text and "Lỗi này cần xử lý nguyên nhân trước. Vẫn tiếp tục?" in text


def test_dialog_for_a_deferral_is_calm(client):
    text = _dialog(client, "rate_limited: gap not reached")
    assert 'class="warning"' not in text and "hx-confirm" not in text


def test_a_failure_that_something_else_already_posted_offers_no_retry(client):
    failed_at = datetime.now(timezone.utc) - timedelta(hours=2)
    log(ok=False, message=TIMEOUT, content="same text", at=failed_at)
    assert 'title="Đăng lại"' in page(client, tab="failures")
    log(ok=True, content="same text", at=failed_at + timedelta(hours=1))                      # posted later by something else
    text = page(client, tab="failures")
    assert 'title="Đăng lại"' not in text and "✅ Đã đăng thành công sau đó" in text


# --- second review ---------------------------------------------------------------------------------------------------------

def test_rate_limited_is_an_exact_prefix_not_a_like_pattern(isolated_db):
    """The SQL used LIKE 'rate_limited:%' where "_" is a wildcard and case is ignored; the page's Python check was exact."""
    log(ok=False, message="rate limited: not the real prefix")                             # a space, not "_"
    log(ok=False, message="RATE_LIMITED: shouting")
    log(ok=False, message="rate_limited:posts_per_day limit reached")
    assert db.summary_stats()["failed"] == 2 == db.recent_activity_count(only_failed=True)
    assert not db.is_rate_limited("rate limited: x") and not db.is_rate_limited("RATE_LIMITED: x") and db.is_rate_limited("rate_limited:x")


def test_the_server_refuses_a_repost_of_something_already_posted(client, monkeypatch):
    ran = []

    async def no_run(request):
        ran.append(request)

    monkeypatch.setattr(admin_module, "run_task", no_run)
    failed_at = datetime.now(timezone.utc) - timedelta(hours=2)
    row = log(ok=False, message=TIMEOUT, content="same text", at=failed_at)
    log(ok=True, content="same text", at=failed_at + timedelta(hours=1))                      # a stale page still shows the button; the server knows better
    resp = client.post("/admin/reports/repost", data={"log_id": row, "tab": "failures"})
    assert resp.status_code == 303 and ran == []
    assert "không đăng lại để khỏi trùng" in parse_qs(urlparse(resp.headers["location"]).query)["error"][0]
    htmx = client.post("/admin/reports/repost", data={"log_id": row, "tab": "failures"}, headers={"hx-request": "true"})
    assert "đã được đăng thành công lúc" in htmx.text and ran == []


def test_the_server_refuses_to_reschedule_what_is_already_posted(client):
    failed_at = datetime.now(timezone.utc) - timedelta(hours=2)
    row = log(ok=False, message=TIMEOUT, content="same text", at=failed_at)
    log(ok=True, content="same text", at=failed_at + timedelta(hours=1))
    resp = client.post("/admin/reports/reschedule-confirm", data={"log_id": row, "tab": "failures"}, headers={"hx-request": "true"})
    assert "không đăng lại để khỏi trùng" in resp.text
    from human_bot import schedule_store
    assert schedule_store.list_pending() == []
    dialog = client.get(f"/admin/reports/reschedule-suggest?log_id={row}&tab=failures").text
    assert "không đăng lại để khỏi trùng" in dialog and "Xác nhận" not in dialog


def test_the_reschedule_dialog_also_warns_and_asks_for_an_uncertain_failure(client, monkeypatch):
    from types import SimpleNamespace
    monkeypatch.setattr(admin_module, "get_all_accounts", lambda: {"acc-a": SimpleNamespace(account_id="acc-a")})
    monkeypatch.setattr(admin_module, "_suggest_reschedule_at", lambda account, action: datetime.now(timezone.utc) + timedelta(hours=3))
    row = log(ok=False, message=NOT_CONFIRMED)
    text = client.get(f"/admin/reports/reschedule-suggest?log_id={row}&tab=failures").text
    assert "chưa rõ bài đã lên Facebook chưa" in text and 'hx-confirm="Bài này có thể đã lên Facebook rồi. Vẫn tiếp tục?"' in text
    safe = log(ok=False, message=TIMEOUT)
    assert "hx-confirm" not in client.get(f"/admin/reports/reschedule-suggest?log_id={safe}&tab=failures").text


def test_a_row_posted_later_does_not_also_claim_it_can_be_retried(client):
    failed_at = datetime.now(timezone.utc) - timedelta(hours=2)
    log(ok=False, message=TIMEOUT, content="same text", at=failed_at)
    log(ok=True, content="same text", at=failed_at + timedelta(hours=1))
    note = page(client, tab="failures").split('class="rep-note">')[1].split("</div>")[0]
    assert "Không thấy ô/nút cần bấm" in note and "thử lại được" not in note


def test_a_repeating_safe_failure_says_it_tends_to_repeat(client):
    log(ok=False, message=TIMEOUT)
    assert "thử lại được, nhưng lỗi kiểu này hay lặp lại" in page(client, tab="failures")
    assert failure_info.hint(failure_info.classify(OFFLINE)) == "bài chưa lên — thử lại được"        # a one-off (the network) is just "safe"


def test_the_posted_later_check_is_one_connection_for_the_page(isolated_db, monkeypatch):
    base = datetime.now(timezone.utc) - timedelta(hours=5)
    rows = [db.get_action_log(log(ok=False, message=TIMEOUT, content=f"c{i}", at=base)) for i in range(3)]
    log(ok=True, content="c1", at=base + timedelta(hours=1))
    log(ok=True, content="c2", at=base - timedelta(hours=1))                                       # BEFORE the failure: not "later"
    opened = []
    real = db._connect
    monkeypatch.setattr(db, "_connect", lambda: (opened.append(1), real())[1])
    assert db.failed_rows_posted_later(rows) == {rows[1]["id"]} and len(opened) == 1


def test_a_job_card_counts_what_it_shows_even_when_the_window_cuts_the_job(client):
    now = datetime.now(timezone.utc)
    for i, age in enumerate((20, 1, 1)):                                                            # one group before the 7-day window, two inside
        log(source_kind="job", source_id="jw", job_data=JOB, url=f"https://www.facebook.com/groups/{i}", at=now - timedelta(days=age))
    summary = re.search(r'<details class="rep-job">\s*<summary>(.*?)</summary>', page(client, tab="jobs", days=7), re.S).group(1)
    assert "· 3 nhóm" in summary and "3 thành công" in summary                                       # the label and the badges agree


@pytest.mark.parametrize("salary", [
    {"min": 1, "period": ["month"]}, {"min": 1, "currency": 5, "period": "hour"}, {"min": "1e999", "period": "month"},
    {"min": "abc", "period": "month"}, {"min": float("nan")}, {"min": None, "max": None, "note": "thương lượng"}, [1, 2], "tùy năng lực",
])
def test_a_malformed_salary_never_breaks_the_tab_and_never_vanishes(client, salary):
    log(source_kind="job", source_id="js", job_data={"title": "T", "attributes": {"salary": salary}})
    assert client.get("/admin/reports?tab=jobs").status_code == 200
    out = admin_module._attr_text("salary", salary)
    assert "{'" not in out and "['" not in out                                                      # never Python's repr of a dict / list


def test_a_salary_with_only_a_note_shows_the_note():
    assert admin_module._salary_text({"min": None, "max": None, "note": "thương lượng"}) == "note: thương lượng"
    assert "Lương:</b> note: thương lượng" in admin_module._attrs_summary_html(None, {"salary": {"min": 0, "note": "thương lượng"}})


def test_the_failure_badge_stays_on_the_settings_tab(client):
    log(ok=False, message=TIMEOUT)
    assert '<span class="badge badge-bad">1</span>' in page(client, tab="settings")


def test_weeks_run_monday_to_sunday_in_japan_time(isolated_db):
    """08:00 JST on Monday 2 Nov is Sunday 23:00 UTC: it belongs to the week that STARTS on the 2nd."""
    log(at=datetime(2026, 11, 1, 23, 0, tzinfo=timezone.utc))                                      # Mon 08:00 JST
    log(at=datetime(2026, 11, 1, 14, 0, tzinfo=timezone.utc))                                      # Sun 23:00 JST: still last week
    assert {r["week"]: r["total"] for r in db.weekly_post_counts()} == {"2026-11-02": 1, "2026-10-26": 1}


def test_the_weekly_card_says_which_weeks_these_are(client):
    log()
    assert "Tuần tính từ thứ Hai đến Chủ nhật, theo giờ Nhật." in page(client)
