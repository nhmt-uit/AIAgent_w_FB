"""The /admin/schedule redesign (2026-11-02): compact rows grouped by day, the edit panel opened in
place, one loud button only when a post is due, a "⋯" menu for the rest — in the three tabs
(Đã lên lịch / Quá hạn / Chờ duyệt)."""
from __future__ import annotations

import re
from datetime import datetime, timedelta, timezone

import pytest

import human_bot.admin as admin_module
import human_bot.schedule_store as schedule_store
from human_bot.config import AccountConfig, GroupRef
from tests.test_admin_schedule import _add_review, client  # noqa: F401  (fixtures/helpers)

GROUP_URL = "https://www.facebook.com/groups/1383875949915495"


@pytest.fixture
def accounts(monkeypatch):
    registry = {"acc-a": AccountConfig(account_id="acc-a", display_name="Anna"), "acc-b": AccountConfig(account_id="acc-b", display_name="Bao")}
    monkeypatch.setattr(admin_module, "get_all_accounts", lambda: registry)
    groups = {"acc-a": [GroupRef(name="Việc làm Kỹ Sư <Nhật>", url=GROUP_URL)], "acc-b": []}
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: groups.get(aid, []))
    return registry


def _item(page: str, task_id: str) -> str:
    """The html of the schedule row that contains this task id."""
    parts = re.split(r'(?=<div class="sched-item)', page)
    return next(part for part in parts if task_id in part and part.startswith('<div class="sched-item'))


def _menu(item: str) -> str:
    return item.split('<div class="row-menu-pop">')[1].split("</details>")[0]


FUTURE = lambda: datetime.now(timezone.utc) + timedelta(hours=3)  # noqa: E731


def _add_task(when, account_id="acc-a", action="post_to_group", content="hello", target_url="https://facebook.com/groups/1", **kw):
    task = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(when.isoformat()), action=action, account_id=account_id,
        scheduled_at=when.isoformat(), content=content, target_url=target_url, **kw,
    )
    schedule_store.add(task)
    return task


def _add_missed(when, reason="quá hạn test", **kw):
    task = _add_task(when, **kw)
    schedule_store.mark_missed(task.task_id, reason)
    return task


# --- Đã lên lịch -------------------------------------------------------------------------------------------------

def test_a_pending_task_is_one_compact_row_with_the_group_name_not_its_url(client, accounts):
    t = _add_task(FUTURE(), account_id="acc-a", content="Tìm nhân sự ở Tokyo", target_url=GROUP_URL)
    page = client.get("/admin/schedule").text
    item = _item(page, t.task_id)
    assert 'data-sched-when="' in item and "data-local-time" in item                              # the day heading and the HH:MM come from the browser's own timezone
    assert "Việc làm Kỹ Sư &lt;Nhật&gt;" in item and "<Nhật>" not in item                          # the name, escaped
    assert f'href="{GROUP_URL}"' in item and f'title="{GROUP_URL}"' in item and f">{GROUP_URL}<" not in item   # the URL is the link, never the visible text
    assert "id: " not in item and "Ngày giờ thực hiện" not in item and "Url nhóm" not in item         # the old stacked metadata is gone
    assert "Tìm nhân sự ở Tokyo" in item and 'class="sched-list" data-sched-days' in page


def test_a_group_the_account_does_not_list_falls_back_to_the_url_tail_and_a_comment_names_its_post(client, accounts):
    other = _add_task(FUTURE(), account_id="acc-a", target_url="https://www.facebook.com/groups/777")
    comment = _add_task(FUTURE(), account_id="acc-a", action="comment_on_group_post", target_url="https://www.facebook.com/groups/1/posts/456")
    page = client.get("/admin/schedule").text
    assert ">777</a>" in _item(page, other.task_id)
    assert ">bài viết …456</a>" in _item(page, comment.task_id) and "Comment bài trong nhóm" in _item(page, comment.task_id)


def test_a_comment_names_the_group_its_post_is_in_when_the_account_lists_it(client, accounts):
    known = _add_task(FUTURE(), account_id="acc-a", action="comment_on_group_post", target_url=GROUP_URL + "/posts/987654321?comment_id=1")
    opaque = _add_task(FUTURE(), account_id="acc-b", action="comment_on_group_post", target_url="https://www.facebook.com/permalink.php?story_fbid=pfbid0abcdef123456&id=9")
    page = client.get("/admin/schedule").text
    assert ">bài trong Việc làm Kỹ Sư &lt;Nhật&gt;</a>" in _item(page, known.task_id)
    assert ">bài viết</a>" in _item(page, opaque.task_id)                                          # permalink.php?… has no id worth showing
    assert "story_fbid" not in re.sub(r'="[^"]*"', '=""', _item(page, opaque.task_id))                # the raw query never becomes visible text (only attribute values)


def test_the_group_list_is_read_once_per_account_however_many_tasks_there_are(client, accounts, monkeypatch):
    calls = []
    real = admin_module.get_joined_groups
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: (calls.append(aid), real(aid))[1])
    for _ in range(6):
        _add_task(FUTURE(), account_id="acc-a", target_url=GROUP_URL)
    client.get("/admin/schedule")
    assert calls.count("acc-a") == 1


def test_the_group_is_matched_by_id_not_by_exact_url(client, accounts):
    t = _add_task(FUTURE(), account_id="acc-a", target_url=GROUP_URL + "/")                           # a trailing slash must still find the saved name
    assert "Việc làm Kỹ Sư &lt;Nhật&gt;" in _item(client.get("/admin/schedule").text, t.task_id)


def test_only_a_due_post_gets_the_loud_button_and_the_amber_flag(client, accounts):
    due = _add_task(datetime.now(timezone.utc) - timedelta(minutes=20), account_id="acc-a")
    later = _add_task(FUTURE(), account_id="acc-a")
    page = client.get("/admin/schedule").text
    due_item, later_item = _item(page, due.task_id), _item(page, later.task_id)
    assert 'class="sched-item sched-due"' in due_item and "⏰ đến giờ" in due_item
    assert '<button type="submit" class="btn-small">🚀 Đăng ngay</button>' in due_item
    assert "sched-due" not in later_item and '<button type="submit" class="btn-small btn-secondary">🚀 Đăng ngay</button>' in later_item


def test_fire_now_keeps_its_confirmation_and_the_view_it_came_from(client, accounts):
    t = _add_task(FUTURE(), account_id="acc-a")
    page = client.get("/admin/schedule?account_id=acc-a&page_size=10").text
    form = _item(page, t.task_id).split('action="/admin/schedule/fire-now"')[1].split("</form>")[0]
    assert 'hx-confirm="Đăng bài này lên Facebook ngay bây giờ?"' in form
    assert 'name="account_id" value="acc-a"' in form and 'name="page_size" value="10"' in form and f'value="{t.task_id}"' in form


def test_editing_happens_in_a_panel_that_starts_closed_and_holds_the_full_text(client, accounts):
    long_text = "Dòng " + "rất dài " * 120 + "<script>alert(1)</script>"
    t = _add_task(FUTURE(), account_id="acc-a", content=long_text)
    item = _item(client.get("/admin/schedule").text, t.task_id)
    assert '<div class="sched-edit" hidden>' in item and 'action="/admin/schedule/update"' in item and "✎ Sửa" in item
    textarea = item.split('<textarea name="content"')[1].split("</textarea>")[0]
    assert "rất dài " * 120 in textarea and "…" not in textarea                                 # never truncated: Lưu must not chop a long post
    assert "<script>alert(1)</script>" not in item and "&lt;script&gt;alert(1)&lt;/script&gt;" in item
    assert 'name="scheduled_at"' in item and "data-schedule-preset" in item and ">Lưu</button>" in item and ">Đóng</button>" in item


def test_the_menu_holds_swap_copy_and_cancel_with_the_consequence_of_each(client, accounts):
    t = _add_task(FUTURE(), account_id="acc-a", target_url=GROUP_URL)
    menu = _menu(_item(client.get("/admin/schedule").text, t.task_id))
    assert 'action="/admin/schedule/swap-modal"' in menu and 'hx-target="#modal-root"' in menu and "removeAttribute(" in menu.split('action="/admin/schedule/swap-modal"')[1].split("</form>")[0]   # opens a modal: closes the menu behind it
    assert "removeAttribute(" not in menu.split('action="/admin/schedule/cancel"')[1].split("</form>")[0]   # the list is replaced anyway
    assert "📋 Copy URL" in menu and "copyText(" in menu
    assert 'action="/admin/schedule/cancel"' in menu and 'hx-confirm="Huỷ lịch đăng này?"' in menu and "menu-item danger" in menu
    assert f"Mã: {t.task_id}" in menu


def test_a_task_warning_is_shown_under_the_text(client, accounts):
    t = _add_task(FUTURE(), account_id="acc-a", last_warning="Còn 1 bài trong giờ này")
    assert '<div class="sched-why">Còn 1 bài trong giờ này</div>' in _item(client.get("/admin/schedule").text, t.task_id)


def test_the_toolbar_is_one_row_keeping_every_filter_control(client, accounts):
    _add_task(FUTURE(), account_id="acc-a")
    page = client.get("/admin/schedule").text
    assert page.count('class="sched-toolbar"') == 1 and "1 bài đang chờ</span>" in page
    for control in ('id="schedule-account-select"', 'id="schedule-action-select"', 'id="schedule-date-input"', 'id="schedule-pagesize-select"', 'id="schedule-tz-offset"'):
        assert control in page
    assert 'class="account-filter"' not in page


def test_the_tabs_say_bai_not_task_and_mark_the_active_one(client, accounts):
    _add_task(FUTURE(), account_id="acc-a")
    _add_missed(datetime.now(timezone.utc) - timedelta(days=1), account_id="acc-a")
    page = client.get("/admin/schedule").text
    assert "📋 Đã lên lịch (1)" in page and "⚠️ Quá hạn (1)" in page and "🔍 Chờ duyệt (0)" in page and "Task đã lên lịch (" not in page and "Task quá hạn (" not in page
    assert re.search(r'class="sched-tab active">📋 Đã lên lịch', page)
    assert re.search(r'class="sched-tab active">⚠️ Quá hạn', client.get("/admin/schedule?tab=missed").text)


def test_an_empty_schedule_points_at_the_compose_page(client, accounts):
    page = client.get("/admin/schedule").text
    assert "Chưa có bài nào đang chờ lịch" in page and 'href="/admin/post">Đăng bài</a>' in page


# --- Quá hạn --------------------------------------------------------------------------------------------------------------

def test_a_missed_row_leads_with_reschedule_and_says_how_late_and_why(client, accounts):
    t = _add_missed(datetime.now(timezone.utc) - timedelta(days=2), reason="Mất mạng: không kết nối được internet", account_id="acc-a")
    page = client.get("/admin/schedule?tab=missed").text
    item = _item(page, t.task_id)
    assert "quá 2 ngày" in item and "Mất mạng: không kết nối được internet" in item and 'class="sched-item sched-missed"' in item
    assert f"/admin/schedule/missed/suggest?task_id={t.task_id}" in item and "🔄 Lên lịch lại</button>" in item
    assert 'action="/admin/schedule/missed/fire-now"' in item and "🚀 Đăng ngay" in item
    assert f'name="task_ids" value="{t.task_id}" form="missed-bulk-form"' in item                       # still selectable for the bulk delete


def test_a_missed_row_reschedules_from_its_own_panel_and_the_menu_has_borrow_and_delete(client, accounts):
    t = _add_missed(datetime.now(timezone.utc) - timedelta(days=1), account_id="acc-a", content="nội dung quá hạn")
    item = _item(client.get("/admin/schedule?tab=missed").text, t.task_id)
    assert '<div class="sched-edit" hidden>' in item and 'action="/admin/schedule/missed/reschedule"' in item and "📅 Đặt lịch</button>" in item and "nội dung quá hạn" in item
    menu = _menu(item)
    assert f"/admin/schedule/missed/borrow?task_id={t.task_id}" in menu and "↩️ Mượn giờ của bài khác" in menu and "bài đó dời sang sau" in menu
    assert 'action="/admin/schedule/missed/cancel"' in menu and 'hx-confirm="Xoá mục quá hạn này?"' in menu


def test_the_missed_tab_explains_itself_in_plain_words_and_folds_away_the_button_guide(client, accounts):
    _add_missed(datetime.now(timezone.utc) - timedelta(days=1), account_id="acc-a")
    page = client.get("/admin/schedule?tab=missed").text
    assert "mất mạng, service tắt, tài khoản tắt hoặc tạm dừng" in page and f"hơn {schedule_store.STALE_MISSED_MAX_AGE_DAYS} ngày" in page
    assert "<summary>Các nút làm gì?</summary>" in page and "Mượn giờ" in page
    assert 'id="missed-bulk-form"' in page and "Xoá đã chọn" in page and 'id="schedule-missed-mindays-select"' in page


# --- Chờ duyệt ------------------------------------------------------------------------------------------------------------

def test_a_review_row_shows_title_confidence_and_a_preview_with_the_texts_one_click_away(client, accounts):
    r = _add_review(confidence=0.42, title="Thợ hàn <b>chuyên nghiệp</b>", account_id="acc-a")
    page = client.get("/admin/schedule?tab=needs_review").text
    assert 'class="sched-item sched-review"' in page and "Thợ hàn &lt;b&gt;chuyên nghiệp&lt;/b&gt;" in page and "<b>chuyên" not in page
    assert "Độ tin cậy: 0.42" in page and "✎ Xem / sửa nội dung" in page
    assert f'form="needs-review-approve-{r.review_id}"' in page and f'form="needs-review-reject-{r.review_id}"' in page
    panel = page.split('<div class="sched-edit" hidden>')[1]
    assert f'id="needs-review-approve-{r.review_id}"' in panel and 'name="content_0"' in panel         # the texts are still submitted with the approval
    assert 'hx-confirm="Bỏ qua tin này? Nó sẽ không được đăng."' in panel


def test_the_review_intro_links_to_the_sync_settings_and_names_no_file(client, accounts):
    _add_review(account_id="acc-a")
    page = client.get("/admin/schedule?tab=needs_review").text
    intro = page.split('class="sched-help"')[1].split("</p>")[0]
    assert 'href="/admin/config?tab=sync">Cấu hình → Đồng bộ dữ liệu</a>' in intro and ".py" not in intro and "/admin/config\"" not in intro


def test_a_naive_scheduled_time_is_read_as_utc_and_never_breaks_the_page(client, accounts):
    naive = datetime.now(timezone.utc).replace(tzinfo=None) - timedelta(minutes=30)                 # no offset, like a hand-edited / legacy file
    t = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(naive.isoformat()), action="post_to_group", account_id="acc-a",
        scheduled_at=naive.isoformat(), content="x", target_url=GROUP_URL,
    )
    schedule_store.add(t)
    resp = client.get("/admin/schedule")
    assert resp.status_code == 200 and "sched-due" in _item(resp.text, t.task_id)                      # 30 minutes ago in UTC: due


def test_the_page_script_parses_a_time_without_an_offset_as_utc():
    js = admin_module._PAGE_STYLE
    assert "function parseUtc(iso)" in js and 'iso + "Z"' in js
    assert js.count("parseUtc(") >= 4                                                                 # the day headings, HH:MM and the older date-time cell all use it


def test_missed_rows_sit_in_the_same_card_as_the_other_tabs_and_share_one_set_of_hidden_fields(client, accounts):
    a = _add_missed(datetime.now(timezone.utc) - timedelta(days=4), account_id="acc-a")
    b = _add_missed(datetime.now(timezone.utc) - timedelta(days=5), account_id="acc-a")
    page = client.get("/admin/schedule?tab=missed&missed_min_days=3&page_size=10").text
    assert page.count('<div class="sched-list">') == 1
    assert page.index('<div class="sched-list">') < page.index(f'value="{a.task_id}"') and page.index('<div class="sched-list">') < page.index(f'value="{b.task_id}"')
    bulk = page.split('id="missed-bulk-form"')[1].split("</form>")[0]
    row = _item(page, a.task_id).split('action="/admin/schedule/missed/fire-now"')[1].split("</form>")[0]
    for field in ('name="tab" value="missed"', 'name="missed_min_days" value="3"', 'name="page_size" value="10"'):
        assert field in bulk and field in row                                                         # the bulk form and a row form re-render the same view


def test_copying_works_without_the_clipboard_api_and_says_when_it_did_not():
    js = admin_module._PAGE_STYLE
    assert "function copyText(text, btn)" in js and "window.isSecureContext" in js and 'document.execCommand("copy")' in js
    assert "Không copy được" in js and "window.copyText = copyText" in js


def test_a_menu_item_can_be_told_explicitly_to_close_its_menu():
    on = admin_module._menu_form("/x", {}, "A", "b", target="#schedule-content", close_menu=True)
    off = admin_module._menu_form("/x", {}, "A", "b", target="#modal-root", close_menu=False)
    default_modal = admin_module._menu_form("/x", {}, "A", "b", target="#modal-root")
    default_list = admin_module._menu_form("/x", {}, "A", "b", target="#schedule-content")
    assert "removeAttribute" in on and "removeAttribute" not in off and "removeAttribute" in default_modal and "removeAttribute" not in default_list
