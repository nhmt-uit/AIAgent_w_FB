"""The home page "Hôm nay" (2026-11-02): five numbers that are links, the problems first, the next posts,
one line per account — and the shared numbers (human_bot/overview.py) Telegram's /report uses too."""
from __future__ import annotations

import os
import re
from datetime import datetime, timedelta, timezone

import pytest

import human_bot.admin as admin_module
import human_bot.schedule_store as schedule_store
from human_bot import daily_limits, db, failure_tickets, overview, telegram_commands, telegram_failures
from human_bot.config import AccountConfig, AccountStatus, GroupRef
from human_bot.runtime_config import save_registered_account, save_scheduling_overrides, set_account_disabled, set_account_paused
from tests.test_admin_home import client  # noqa: F401  (fixture)


def _task(when: datetime, account_id="tu_iizuki", action="post_to_group", url="https://www.facebook.com/groups/1", **kw):
    t = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(when.isoformat()), action=action, account_id=account_id,
        scheduled_at=when.isoformat(), content="x", target_url=url, **kw,
    )
    schedule_store.add(t)
    return t


def _tile(page: str, label: str) -> str:
    return re.search(rf'<a class="stat[^"]*" href="[^"]*"><span class="stat-label">{re.escape(label)}</span>.*?</a>', page, flags=re.S).group(0)


def _end_of_business_day() -> datetime:
    return daily_limits.business_day_start(datetime.now(timezone.utc)) + timedelta(days=1)


@pytest.fixture
def home(client, isolated_schedule_dirs):
    return lambda: client.get("/admin").text


# --- the page ------------------------------------------------------------------------------------------------------------------

def test_the_page_says_what_day_it_is_and_offers_the_two_things_you_do_most(home):
    page = home()
    assert "<h1>Hôm nay</h1>" in page and "ngày làm việc tính từ 02:00 đến 02:00 hôm sau, giờ Nhật" in page
    assert re.search(r"(Thứ hai|Thứ ba|Thứ tư|Thứ năm|Thứ sáu|Thứ bảy|Chủ nhật) \d\d/\d\d", page)
    assert 'href="/admin/post?tab=job">＋ Tin tuyển dụng</a>' in page and 'href="/admin/post?tab=group">＋ Đăng bài</a>' in page


def test_the_six_link_cards_that_repeated_the_menu_are_gone(home):
    page = home()
    for gone in ("home-link-card", "Đăng ký tài khoản mới sau khi chạy bootstrap_login.py", "Sức khoẻ tài khoản", "Bảng điều khiển"):
        assert gone not in page
    assert "Trang quản trị nội bộ — đừng đưa ra internet" in page                           # the one warning that matters stays, as a footnote


def test_five_numbers_each_a_link_to_where_you_deal_with_them(home):
    page = home()
    expected = {
        "Chờ đăng hôm nay": "/admin/schedule", "Kết quả hôm nay": "/admin/reports", "Quá hạn": "/admin/schedule?tab=missed",
        "Chờ duyệt": "/admin/schedule?tab=needs_review", "Lỗi chưa xử lý": "/admin/reports?tab=failures&days=7",     # the Báo cáo "Lỗi" tab (7 days: it lists every failure, not only the unhandled ones)
    }
    for label, href in expected.items():
        assert f'href="{href}"><span class="stat-label">{label}</span>' in page


def test_the_numbers_come_from_the_data_and_only_what_needs_you_turns_amber(home):
    page = home()
    for label in ("Chờ đăng hôm nay", "Quá hạn", "Chờ duyệt", "Lỗi chưa xử lý"):
        assert 'class="stat"' in _tile(page, label)                                          # all zero: calm
    now = datetime.now(timezone.utc)
    _task(now + timedelta(seconds=30))                                                      # today
    due = _task(now - timedelta(minutes=5))                                                 # today, already due
    _task(_end_of_business_day() + timedelta(hours=3))                                      # a later day
    missed = _task(now - timedelta(days=2)); schedule_store.mark_missed(missed.task_id, "x")
    db.log_action(account_id="tu_iizuki", action="post_to_group", success=True)
    db.log_action(account_id="tu_iizuki", action="post_to_group", success=True)
    db.log_action(account_id="tu_iizuki", action="post_to_group", success=False, message="boom")
    page = home()
    waiting = _tile(page, "Chờ đăng hôm nay")
    assert '<span class="stat-num">2</span>' in waiting and "⏰ 1 đã đến giờ" in waiting and "stat-attn" in waiting
    assert '<span class="ok">✅ 2</span> <span class="bad">❌ 1</span>' in _tile(page, "Kết quả hôm nay") and "stat-attn" not in _tile(page, "Kết quả hôm nay")
    assert '<span class="stat-num">1</span>' in _tile(page, "Quá hạn") and "stat-attn" in _tile(page, "Quá hạn") and "chờ bạn xếp lại" in _tile(page, "Quá hạn")
    assert due.task_id                                                                         # (kept for readability)


def test_the_failures_number_is_read_only_and_matches_what_telegram_would_list(home):
    when = datetime.now(timezone.utc) - timedelta(hours=1)
    t = _task(when)
    schedule_store.mark_failed(t.task_id, "error:Page.goto: Timeout 30000ms exceeded.")
    page = home()
    assert '<span class="stat-num">1</span>' in _tile(page, "Lỗi chưa xử lý") and "xem lỗi 7 ngày qua · xử lý: gõ /error" in _tile(page, "Lỗi chưa xử lý")
    assert failure_tickets.list_open(kind=None) == []                                         # viewing the page filed nothing
    assert telegram_failures.open_failure_count() == 1                                       # ...and Telegram's own count agrees (and DOES file the card)
    assert len(failure_tickets.list_open()) == 1


# --- problems ----------------------------------------------------------------------------------------------------------------------

def test_a_switched_off_auto_fire_is_the_first_problem_with_a_way_to_fix_it(home):
    page = home()
    assert 'class="card home-attn"' in page and "Tự động đăng đang <b>tắt</b>" in page and 'href="/admin/config">Bật ở Cấu hình</a>' in page
    save_scheduling_overrides({"auto_fire_enabled": True})
    assert "Tự động đăng đang <b>tắt</b>" not in home()


def test_a_paused_account_is_listed_first_among_the_problems_and_in_the_account_lines(home):
    save_registered_account("acc-healthy", "Healthy Account")
    save_registered_account("acc-paused", "Paused Account")
    set_account_paused("acc-paused", True, reason="checkpoint thật")
    page = home()
    attention = page.split('class="card home-attn"')[1].split("</ul>")[0]
    assert attention.index("Paused Account") < attention.index("Healthy Account")
    assert "Tạm dừng — checkpoint thật" in attention and 'href="/admin/accounts">Mở tài khoản</a>' in attention
    lines = page.split('class="health-list"')[1]
    assert lines.index("Paused Account") < lines.index("Healthy Account")                    # paused first, then worst health, then by name


def test_a_page_that_cannot_run_is_a_problem_even_though_the_five_signals_do_not_see_it(home):
    save_registered_account("page_orphan", "Orphan Page", "The Page", "Tu Nguyen", "", "auto")      # no owner
    assert "Page chưa cấu hình đủ hoặc chưa chạy được" in home().split('class="card home-attn"')[1].split("</ul>")[0]


def test_nothing_to_flag_means_no_problems_card_at_all(client, isolated_schedule_dirs, monkeypatch):
    monkeypatch.setattr(admin_module, "get_all_accounts", lambda: {})
    save_scheduling_overrides({"auto_fire_enabled": True})
    page = client.get("/admin").text
    assert 'class="card home-attn"' not in page and "Chưa có tài khoản nào" in page


def test_the_attention_reason_is_one_definition(isolated_runtime_config, isolated_accounts_dir):
    from human_bot.config import get_all_accounts
    save_registered_account("p1", "P1")
    save_registered_account("page_x", "X", "Page X", "Me", "", "auto")
    set_account_disabled("p1", True)
    accounts = get_all_accounts()
    assert admin_module._account_attention_reason(accounts["p1"], accounts) is None                 # off on purpose
    set_account_disabled("p1", False)
    assert admin_module._account_attention_reason(get_all_accounts()["p1"], get_all_accounts()) == "chưa đăng nhập"
    set_account_paused("p1", True)
    assert admin_module._account_attention_reason(get_all_accounts()["p1"], get_all_accounts()) == "đang tạm dừng"
    assert "Page chưa cấu hình đủ" in admin_module._account_attention_reason(accounts["page_x"], accounts)


# --- next posts ---------------------------------------------------------------------------------------------------------------------

def test_the_next_four_posts_are_listed_with_group_names_and_a_link_to_the_rest(home, monkeypatch):
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: [GroupRef(name="Nhóm Thợ <Hàn>", url="https://www.facebook.com/groups/1")])
    now = datetime.now(timezone.utc)
    for i in range(6):
        _task(now + timedelta(hours=i + 1))
    page = home()
    block = page.split("📅 Sắp đăng")[1].split("home-more")[0]
    assert block.count('class="upnext-row"') == 4 and "Nhóm Thợ &lt;Hàn&gt;" in block and "Nhóm Thợ <Hàn>" not in block
    assert 'href="/admin/schedule">Xem tất cả (6) →</a>' in page


def test_with_no_posts_waiting_it_points_at_the_two_ways_to_make_some(home):
    page = home()
    assert "Chưa có bài nào chờ đăng" in page and "＋ Tin tuyển dụng" in page.split("Chưa có bài nào chờ đăng")[1][:200] or "Chưa có bài nào chờ đăng — bấm" in page


# --- one line per account -------------------------------------------------------------------------------------------------------------

def test_a_healthy_account_is_one_line_a_troubled_one_shows_only_what_is_wrong_and_all_five_signals_are_one_click_away(home, isolated_accounts_dir):
    save_registered_account("acc-paused", "Paused Account")
    set_account_paused("acc-paused", True, reason="checkpoint thật")
    row = home().split('<span class="health-name">Paused Account')[1].split("</details>")[0]
    assert 'health-red' in home().split('<span class="health-name">Paused Account')[0][-300:]
    summary = row.split('class="health-sum">')[1].split("</summary>")[0]
    assert "Tạm dừng — checkpoint thật" in summary and "Chưa mở phiên" not in summary           # only the lines that need a person
    assert '<div class="health-rows">' in row and "Chưa mở phiên trình duyệt nào" in row.split('class="health-rows"')[1]


def test_the_summary_text_is_state_plus_last_success_when_all_is_well_and_the_problems_otherwise():
    well = [("🟢", "Hoạt động"), ("⚪", "Chưa mở phiên trình duyệt nào"), ("🟢", "Thành công gần nhất: 14:08"), ("🟢", "Phiên đăng nhập còn 89 ngày")]
    assert admin_module._health_summary_text(2, well) == "Hoạt động · Thành công gần nhất: 14:08"
    bad = [("🟢", "Hoạt động"), ("🟡", "Im lặng 60 giờ"), ("🔴", "Phiên trình duyệt đã đóng")]
    assert admin_module._health_summary_text(0, bad) == "Phiên trình duyệt đã đóng · Im lặng 60 giờ"      # red before amber
    assert admin_module._health_summary_text(2, [("⚪", "Đã tắt (chủ động) — không chạy tác vụ nào")]) == "Đã tắt (chủ động) — không chạy tác vụ nào"


def test_an_account_switched_off_gets_a_grey_dot_not_a_green_one(home):
    save_registered_account("acc-off", "Off Account")
    set_account_disabled("acc-off", True)
    before = home().split('<span class="health-name">Off Account')[0]
    assert 'class="health-row health-gray"' in before[-200:]


# --- the shared numbers ----------------------------------------------------------------------------------------------------------------

def test_queue_counts_split_today_from_later_and_flag_what_is_due(isolated_schedule_dirs):
    now = datetime.now(timezone.utc)
    _task(now + timedelta(seconds=20)); _task(now - timedelta(minutes=3)); _task(_end_of_business_day() + timedelta(minutes=5))
    counts = overview.queue_counts(now)
    assert (counts.left_today, counts.due, counts.later) == (2, 1, 1)


def test_a_time_without_an_offset_is_read_as_utc_like_the_store_does(isolated_schedule_dirs):
    now = datetime.now(timezone.utc)
    naive_past = (now - timedelta(minutes=10)).replace(tzinfo=None)
    t = schedule_store.ScheduledTask(task_id=schedule_store.new_task_id(naive_past.isoformat()), action="post_to_group", account_id="a",
                                     scheduled_at=naive_past.isoformat(), content="x", target_url="u")
    schedule_store.add(t)
    assert overview.queue_counts(now).due == 1


def test_telegrams_report_footer_and_the_home_page_read_the_same_numbers(home, isolated_schedule_dirs):
    now = datetime.now(timezone.utc)
    _task(now + timedelta(seconds=20)); _task(now - timedelta(minutes=3))
    footer = telegram_commands._queue_footer(now)
    assert "Chờ đăng hôm nay: 2 (⏰ 1 đã quá giờ chưa chạy)" in footer
    assert '<span class="stat-num">2</span>' in _tile(home(), "Chờ đăng hôm nay")


def test_todays_attempts_count_from_the_start_of_the_business_day_across_accounts(isolated_db, isolated_runtime_config):
    save_registered_account("acc-b", "B")
    now = datetime.now(timezone.utc)
    db.log_action(account_id="tu_iizuki", action="post_to_group", success=True)
    db.log_action(account_id="acc-b", action="post_to_group", success=False, message="boom")
    db.log_action(account_id="acc-b", action="post_to_group", success=True, created_at=(now - timedelta(days=3)).isoformat())      # not today
    t = overview.today(now)
    assert (t.ok, t.failed) == (1, 1) and t.day_start == daily_limits.business_day_start(now)
    assert overview.today(now, ["acc-b"]).failed == 1 and overview.today(now, ["tu_iizuki"]).failed == 0


def test_a_read_only_failure_listing_neither_files_tickets_nor_dismisses_stale_ones(isolated_schedule_dirs):
    t = _task(datetime.now(timezone.utc) - timedelta(hours=1))
    schedule_store.mark_failed(t.task_id, "boom")
    assert len(telegram_failures._failure_candidates(None, create=False)) == 1 and failure_tickets.list_open(kind=None) == []
    stale = failure_tickets.create(kind="failure", account_id="a", task_id="gone", message="x", failed_at=datetime.now(timezone.utc).isoformat())
    store = failure_tickets._load(); store[stale["id"]]["created_at"] = (datetime.now(timezone.utc) - timedelta(minutes=10)).isoformat(); failure_tickets._save(store)
    telegram_failures._failure_candidates(None, create=False)
    assert failure_tickets.get(stale["id"])["status"] == failure_tickets.OPEN                 # untouched by a read-only look
    telegram_failures.open_failures()
    assert failure_tickets.get(stale["id"])["status"] == failure_tickets.DISMISSED            # the normal listing still tidies up


# --- review fixes (2026-11-02) -----------------------------------------------------------------------------------------------------------

def test_a_page_running_on_its_owners_session_still_shows_up_when_it_is_paused(home):
    save_registered_account("page_o", "Owner Page", "The Page", "Tu Nguyen", "tu_iizuki", "owner_session")
    set_account_paused("page_o", True, reason="x")
    page = home()
    attention = page.split('class="card home-attn"')[1].split("</ul>")[0]
    assert "Owner Page" in attention and "đang tạm dừng" in attention                         # the old pause banner covered it; the new list must too
    assert "Owner Page" not in page.split('class="health-list"')[1]                          # (no health row of its own: the owner's covers the login)


def test_a_paused_page_with_its_own_session_is_listed_once_not_twice_in_one_line(home):
    save_registered_account("page_p", "Paused Page", "The Page", "Tu Nguyen", "tu_iizuki", "own_session")
    set_account_paused("page_p", True, reason="checkpoint")
    item = home().split('class="card home-attn"')[1].split("</ul>")[0].split("Paused Page</b>:")[1].split("</li>")[0]
    assert "Tạm dừng — checkpoint" in item and "đang tạm dừng" not in item


def test_the_date_is_the_business_day_the_numbers_describe_not_the_calendar_date(home, monkeypatch):
    real = overview.today

    def at_one_am_jst_on_the_third(now, account_ids=None, pending=None):
        t = real(now, account_ids, pending)
        start = datetime(2026, 11, 1, 17, 0, tzinfo=timezone.utc)                              # 02:00 JST on 2 Nov: still the business day of the 2nd at 01:00 JST on the 3rd
        return overview.Today(queue=t.queue, missed=t.missed, reviews=t.reviews, ok=t.ok, failed=t.failed, day_start=start)

    monkeypatch.setattr(overview, "today", at_one_am_jst_on_the_third)
    assert "Thứ hai 02/11 · ngày làm việc" in home()


def test_the_results_tile_says_it_counts_attempts_of_every_kind(home):
    tile = _tile(home(), "Kết quả hôm nay")
    assert "lượt thành công · thất bại" in tile and "Đã đăng hôm nay" not in home()


def test_the_page_reads_the_queue_once_and_each_accounts_health_once(home, monkeypatch):
    save_registered_account("acc-1", "One"); save_registered_account("acc-2", "Two")
    calls = {"pending": 0, "signals": 0}
    real_pending, real_signals = schedule_store.list_pending, admin_module._account_health_signals
    monkeypatch.setattr(schedule_store, "list_pending", lambda: (calls.__setitem__("pending", calls["pending"] + 1), real_pending())[1])
    monkeypatch.setattr(admin_module, "_account_health_signals", lambda *a, **k: (calls.__setitem__("signals", calls["signals"] + 1), real_signals(*a, **k))[1])
    page = home()
    shown = len(re.findall(r'<details class="health-row', page))
    assert calls["pending"] == 1 and calls["signals"] == shown >= 3


def test_a_failure_scan_that_breaks_shows_a_question_mark_not_a_calm_zero(home, monkeypatch):
    def boom(now, *, create):
        raise RuntimeError("corrupt ticket store")

    monkeypatch.setattr(telegram_failures, "_failure_candidates", boom)
    tile = _tile(home(), "Lỗi chưa xử lý")
    assert '<span class="stat-num">?</span>' in tile and "không đọc được" in tile and "stat-attn" in tile
    assert telegram_failures.open_failure_count() == 0 and telegram_failures.open_failure_count(default=None) is None      # Telegram's footer keeps its calm default


def test_the_public_failure_listing_still_files_real_tickets_so_the_buttons_have_something_to_point_at(isolated_schedule_dirs):
    t = _task(datetime.now(timezone.utc) - timedelta(hours=1))
    schedule_store.mark_failed(t.task_id, "boom")
    listed = telegram_failures.open_failures()
    assert listed and all(x["id"] for x in listed)                                              # (the read-only scan hands out id "" stand-ins; this one must not)


def test_telegram_uses_the_same_definition_of_today_and_the_same_split_of_the_queue(isolated_schedule_dirs):
    assert telegram_commands._day_bounds is overview.day_bounds
    assert telegram_commands._parse("2026-11-03T09:00:00") == overview.parse_iso("2026-11-03T09:00:00") == datetime(2026, 11, 3, 9, 0, tzinfo=timezone.utc)
    now = datetime.now(timezone.utc)
    _task(now + timedelta(seconds=20)); _task(now - timedelta(minutes=3)); _task(_end_of_business_day() + timedelta(minutes=5))
    text = telegram_commands.schedule_text(now)
    counts = overview.queue_counts(now)
    assert f"Bài sắp đăng hôm nay: {counts.left_today} bài" in text and f"{counts.due} bài đã đến giờ nhưng chưa chạy" in text and f"Các ngày sau: {counts.later} bài" in text


def test_hovering_an_amber_tile_still_shows_it_is_clickable():
    css = admin_module._PAGE_STYLE
    assert "a.stat:hover, a.stat.stat-attn:hover { @apply border-indigo-400; }" in css and css.index(".stat.stat-attn {") < css.index("a.stat:hover, a.stat.stat-attn:hover")
    assert ".upnext-list > :first-child" in css
    assert ".stat-row > .stat:last-child:nth-child(odd) { grid-column: 1 / -1; }" in css                                    # five tiles on a phone: the last one spans, no orphan
