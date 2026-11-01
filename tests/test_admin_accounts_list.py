"""The /admin/accounts list (2026-11-01 redesign): one row per account, a Page nested under its
owner, ONE contextual button plus a "⋯" menu, and none of the old noise (age / source columns,
repeated headings, per-Page chips)."""
from __future__ import annotations

import html as html_lib
import re

import pytest

from human_bot.config import AccountStatus, get_all_accounts
from human_bot.runtime_config import save_registered_account
from tests.test_page_account import ME, PAGE, _register, client  # noqa: F401  (fixtures/helpers)


def _rows(page_html: str) -> dict[str, str]:
    """data-account → that row's html."""
    parts = re.split(r'(?=<li class="acct-row)', page_html)
    return {m.group(1): part for part in parts if (m := re.search(r'data-account="([^"]+)"', part))}


def _menu(row: str) -> str:
    return row.split('<div class="row-menu-pop">')[1]


def _primary(row: str) -> str:
    return row.split('<div class="acct-actions">')[1].split('<details class="row-menu">')[0]


def test_the_list_drops_the_columns_headings_and_chips_that_only_added_noise(client):
    _register(client)
    content = client.get("/admin/accounts", headers={"hx-request": "true"}).text          # just the accounts panel (the Sync tab has its own table)
    for gone in ("Tuổi tài khoản", ">Nguồn<", "Tài khoản hiện có", "Các Page:", "chip-row", "<table", "<th>"):
        assert gone not in content
    page = client.get("/admin/accounts").text
    assert "bootstrap_login.py &lt;account_id&gt; trên máy này" not in page                  # the long intro lives only in the registration dialog
    assert page.count("Các tài khoản Facebook mà bot dùng để đăng bài và bình luận.") == 1


def test_the_header_counts_the_accounts_and_those_needing_attention(client):
    page = client.get("/admin/accounts").text
    assert '<span class="acct-count">1 tài khoản</span>' in page and "cần chú ý" in page         # tu_iizuki has no session file
    client.post("/admin/accounts/disable", data={"account_id": "tu_iizuki"})
    assert "cần chú ý" not in client.get("/admin/accounts").text                                  # switched off on purpose is not a problem
    client.post("/admin/accounts/pause", data={"account_id": "tu_iizuki"})
    assert "1 cần chú ý" in client.get("/admin/accounts").text                                    # paused is


def test_a_page_is_nested_under_its_owner_and_a_personal_account_is_not(client):
    _register(client)
    save_registered_account("other_personal", "Other")
    rows = _rows(client.get("/admin/accounts").text)
    assert 'acct-child' in rows["page_donkysu"] and "acct-child" not in rows["tu_iizuki"] and "acct-child" not in rows["other_personal"]
    page = client.get("/admin/accounts").text
    assert page.index('data-account="tu_iizuki"') < page.index('data-account="page_donkysu"') < page.index('data-account="other_personal"')


def test_a_page_without_a_usable_owner_is_listed_on_its_own_with_its_warning(isolated_runtime_config, isolated_accounts_dir, client):
    save_registered_account("page_orphan", "Orphan", PAGE, "", "", "auto")
    row = _rows(client.get("/admin/accounts").text)["page_orphan"]
    assert "acct-child" not in row and "chưa liên kết tài khoản cá nhân" in row and "chưa khai báo tên hồ sơ cá nhân" in row


def test_an_active_account_shows_one_button_only_when_something_needs_doing(client):
    row = _rows(client.get("/admin/accounts").text)["tu_iizuki"]
    assert "🌐 Đăng nhập</button>" in _primary(row) and "bootstrap-login-modal?account_id=tu_iizuki" in _primary(row)   # no session file yet
    account = get_all_accounts()["tu_iizuki"]
    account.storage_state_path.parent.mkdir(parents=True, exist_ok=True)
    account.storage_state_path.write_text("{}")
    row = _rows(client.get("/admin/accounts").text)["tu_iizuki"]
    assert _primary(row).strip() == ""                                                              # healthy: nothing to press
    assert "phiên đăng nhập OK" in row and "🌐 Đăng nhập lại" in _menu(row)                         # re-login stays one click away


def test_the_menu_of_an_active_account_holds_limits_off_pause_and_delete_with_consequences(client):
    menu = _menu(_rows(client.get("/admin/accounts").text)["tu_iizuki"])
    assert "rate-limits-modal?account_id=tu_iizuki" in menu and "⏱ Giới hạn tốc độ" in menu
    assert 'action="/admin/accounts/disable"' in menu and "⏻ Tắt" in menu and "bật lại là chạy ngay" in menu
    assert 'action="/admin/accounts/pause"' in menu and "⚠ Tạm dừng" in menu and "hạ nhiệt" in menu
    assert 'action="/admin/accounts/delete"' in menu and "menu-item danger" in menu and "hx-confirm" in menu
    assert "Mức giới hạn:" in menu and "human_bot/config.py" in menu                                # age tier + source moved here


def test_an_off_account_offers_turn_on_as_its_button_and_no_pause(client):
    client.post("/admin/accounts/disable", data={"account_id": "tu_iizuki"})
    row = _rows(client.get("/admin/accounts").text)["tu_iizuki"]
    assert 'action="/admin/accounts/enable"' in _primary(row) and "▶ Bật lại" in _primary(row)
    assert "⏻ Đã tắt" in row and "Tắt chủ động từ" in row
    assert 'action="/admin/accounts/pause"' not in row and 'action="/admin/accounts/disable"' not in row and "Kích hoạt lại" not in row


def test_a_paused_account_offers_the_cooldown_resume_and_says_why_it_was_paused(client):
    client.post("/admin/accounts/pause", data={"account_id": "tu_iizuki"})
    row = _rows(client.get("/admin/accounts").text)["tu_iizuki"]
    assert 'action="/admin/accounts/resume"' in _primary(row) and "▶ Kích hoạt lại" in _primary(row) and "hạ nhiệt" in _primary(row)
    assert "⏸ Tạm dừng" in row and "tạm dừng thủ công" in row and "⏻ Đã tắt" not in row
    assert 'action="/admin/accounts/disable"' not in row                                           # a paused account cannot be switched off


def test_a_page_has_no_login_item_anywhere_and_keeps_its_mode_picker_in_its_row(client):
    _register(client, mode="auto")
    row = _rows(client.get("/admin/accounts").text)["page_donkysu"]
    assert "bootstrap-login-modal" not in row and 'name="mode"' in row and "Cách chạy" in row
    assert "rate-limits-modal?account_id=page_donkysu" in _menu(row)


def test_the_account_name_links_to_its_report_and_every_name_is_escaped(client):
    save_registered_account("evil_acc", '<img src=x onerror=alert(1)> & "q"')
    page = client.get("/admin/accounts").text
    row = _rows(page)["evil_acc"]
    assert "<img src=x" not in row and "&lt;img src=x onerror=alert(1)&gt;" in row
    assert 'href="/admin/reports?account_id=evil_acc"' in row


def test_an_empty_list_invites_the_first_registration(isolated_runtime_config, isolated_accounts_dir, client, monkeypatch):
    from human_bot import admin
    monkeypatch.setattr(admin, "get_all_accounts", lambda: {})
    page = admin._accounts_content_html()
    assert "Chưa có tài khoản nào" in page and "acct-list" not in page and "acct-count" not in page


def test_the_menu_can_be_closed_by_clicking_elsewhere(client):
    page = client.get("/admin/accounts").text
    assert 'details.row-menu[open]' in page and 'document.addEventListener("click"' in page


def test_a_personal_account_without_a_session_can_log_in_even_while_it_is_off_or_paused(client):
    client.post("/admin/accounts/disable", data={"account_id": "tu_iizuki"})
    row = _rows(client.get("/admin/accounts").text)["tu_iizuki"]
    assert "▶ Bật lại" in _primary(row) and "bootstrap-login-modal?account_id=tu_iizuki" in _menu(row)     # one click away in the menu
    assert "🌐 Đăng nhập &amp; lưu phiên" in _menu(row) and "Chưa có phiên đăng nhập" in _menu(row)
    client.post("/admin/accounts/enable", data={"account_id": "tu_iizuki"})
    client.post("/admin/accounts/pause", data={"account_id": "tu_iizuki"})
    assert "bootstrap-login-modal?account_id=tu_iizuki" in _menu(_rows(client.get("/admin/accounts").text)["tu_iizuki"])


def test_the_menu_closing_script_is_registered_only_once(client):
    page = client.get("/admin/accounts").text
    assert "if (!window.__rowMenuCloser)" in page and page.count("window.__rowMenuCloser = true") == 1


# --- the Đồng bộ and Tài khoản Telegram tabs (same cleanup) ---------------------------------------------------------------

def _panel(client, tab: str) -> str:
    page = client.get(f"/admin/accounts?tab={tab}").text
    start = page.index(f'id="tab-{tab}"')
    return page[start:]


def test_the_sync_tab_is_a_compact_toggle_matrix_without_the_wall_of_explanation(client):
    _register(client)
    panel = _panel(client, "sync")
    assert "Đồng bộ dữ liệu bên B theo tài khoản" not in panel and "Cấu hình chu kỳ, khoảng cách" not in panel
    assert '<span class="acct-count">2 tài khoản</span>' in panel and 'href="/admin/config?tab=sync"' in panel
    assert "<th>Đồng bộ ⓘ</th>" not in panel and "Đồng bộ ⓘ" in panel and "Chỉ sponsored ⓘ" in panel
    assert "Hai công tắc này làm gì?" in panel and "sponsored_by" in panel                    # the explanation is one click away, not always on screen
    assert panel.count('class="switch"') == 4 and "sync-enable" in panel or "sync-disable" in panel


def test_a_page_sits_under_its_owner_in_the_sync_tab_too(client):
    _register(client)
    save_registered_account("other_personal", "Other")
    panel = _panel(client, "sync")
    assert panel.index("tu_iizuki") < panel.index("page_donkysu") < panel.index("other_personal")
    assert 'class="sync-child"' in panel and "📄 " in panel


def test_the_last_sync_reads_as_one_short_line(client, monkeypatch):
    from human_bot import admin
    monkeypatch.setattr(admin, "get_all_sync_statuses", lambda: {
        "tu_iizuki": {"status": "ok", "last_run_at": "2026-11-01T01:00:00+00:00", "jobs_fetched": 67, "candidates_fetched": 6, "scheduled_posts": 12, "scheduled_comments": 0},
        "nhtu00": {"status": "error", "last_run_at": "2026-11-01T01:00:00+00:00", "error": "side B timeout"},
    })
    save_registered_account("nhtu00", "Nguyen Tu")
    panel = _panel(client, "sync")
    assert "✅ OK" in panel and "67 job · 6 ứng viên lấy về · 12 bài + 0 bình luận mới lên lịch" in panel and "candidate" not in panel
    assert "⚠️ Lỗi" in panel and "side B timeout" in panel


def test_an_off_or_paused_account_has_a_note_instead_of_a_sync_switch(client):
    client.post("/admin/accounts/disable", data={"account_id": "tu_iizuki"})
    assert "đã tắt — không sync" in _panel(client, "sync")
    client.post("/admin/accounts/enable", data={"account_id": "tu_iizuki"})
    client.post("/admin/accounts/pause", data={"account_id": "tu_iizuki"})
    assert "tạm dừng — đã chặn sync" in _panel(client, "sync")


def test_the_telegram_tab_lists_people_with_a_menu_not_three_buttons_each(client):
    from human_bot.runtime_config import add_telegram_recipient
    add_telegram_recipient("931000937", "Tu")
    add_telegram_recipient("123456789", "Anh <b>Nam</b>")
    panel = _panel(client, "telegram")
    assert "<table" not in panel.split('id="tab-')[0] and '<span class="acct-count">2 người nhận tin từ bot</span>' in panel
    assert panel.count('class="tg-row"') == 2 and panel.count('<details class="row-menu">') == 2
    assert 'hx-get="/admin/accounts/telegram/931000937/edit-modal"' in panel and "✏️ Sửa tên" in panel
    assert 'action="/admin/accounts/telegram/931000937/test"' in panel and "🧪 Gửi tin thử" in panel
    assert 'action="/admin/accounts/telegram/931000937/delete"' in panel and "menu-item danger" in panel and "hx-confirm" in panel
    assert "<b>Nam</b>" not in panel and "Anh &lt;b&gt;Nam&lt;/b&gt;" in panel                 # names are escaped


def test_the_telegram_how_to_is_collapsed_and_the_pending_senders_are_a_highlighted_box(client):
    from human_bot import telegram_notify
    telegram_notify.record_pending_sender("555", "Bryan")
    panel = _panel(client, "telegram")
    assert '<details class="mini-help"' in panel and "Cách thêm người nhận" in panel and "bot Telegram của hệ thống" in panel
    assert 'class="tg-pending"' in panel and "🔔 1 người mới nhắn vào bot, chưa được thêm" in panel
    assert "phía trên" not in panel                                                          # the old sentence pointed at a list that is often not there
    empty = _panel(client, "telegram")
    assert "Bryan" in empty


def test_with_nobody_registered_the_telegram_tab_says_so(client):
    panel = _panel(client, "telegram")
    assert "Chưa có ai nhận báo động Telegram" in panel and "➕ Thêm thủ công" in panel


# --- review fixes (2026-11-01) --------------------------------------------------------------------------------------------

def test_the_login_entry_is_not_repeated_when_the_rows_own_button_is_already_login(client):
    row = _rows(client.get("/admin/accounts").text)["tu_iizuki"]
    assert "🌐 Đăng nhập</button>" in _primary(row) and "bootstrap-login-modal" not in _menu(row)
    client.post("/admin/accounts/disable", data={"account_id": "tu_iizuki"})                      # now the row's button is "Bật lại"
    assert "bootstrap-login-modal?account_id=tu_iizuki" in _menu(_rows(client.get("/admin/accounts").text)["tu_iizuki"])


def test_a_page_that_is_off_on_purpose_is_not_counted_as_needing_attention(client):
    _register(client, mode="owner_session", personal_name="")                                       # no personal name: would be a problem...
    save_registered_account("page_ok", "OK", "Other Page", ME, "tu_iizuki", "auto")
    assert "cần chú ý" in client.get("/admin/accounts").text
    client.post("/admin/accounts/disable", data={"account_id": "page_donkysu"})
    client.post("/admin/accounts/disable", data={"account_id": "tu_iizuki"})
    client.post("/admin/accounts/disable", data={"account_id": "page_ok"})
    assert "cần chú ý" not in client.get("/admin/accounts").text                                    # ...but everything is off on purpose


def test_the_menu_never_pokes_out_of_a_phone_screen():
    from human_bot import admin
    css = admin._PAGE_STYLE
    assert "width: min(18rem, calc(100vw - 2rem))" in css
    assert ".acct-actions details.row-menu { position: static; }" in css and ".acct-actions .row-menu-pop { left: 0; right: auto; }" in css   # anchored to the row, not to the button
