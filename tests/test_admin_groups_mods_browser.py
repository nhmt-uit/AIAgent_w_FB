"""The small scripts of the groups list, the rate-limit dialog and the password boxes, in a real browser: the search box,
the delays said in words as you type (and after a quick-apply age preset), the show / hide button.

The dialog is a fragment normally fetched with htmx; here it is fetched by hand and dropped into the page, then the page's own
init runs (it listens for htmx:afterSwap) — so no CDN is needed. Skipped when Playwright / Chromium is missing."""
from __future__ import annotations

import pytest

import human_bot.admin as admin_module
from human_bot.config import GroupRef
from tests.browser_support import browser, live_admin, page, sync_api  # noqa: F401 - fixtures, picked up by name

expect = sync_api.expect
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")            # uvicorn's own websockets import

MANY = [GroupRef(name=n, url=f"https://www.facebook.com/groups/{i}") for i, n in enumerate(
    ["Việc làm Nhật", "Kỹ sư Osaka", "Người Việt Tokyo", "Tuyển dụng Aichi", "Thực tập sinh", "Hội kỹ sư", "IT Nhật Bản", "Cơ khí Nagoya", "Xây dựng Kanto", "Điều dưỡng"])]


def test_the_group_search_hides_what_does_not_match_and_counts(page, live_admin, monkeypatch):
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: MANY)
    page.goto(f"{live_admin}/admin/groups?account_id=acc-a")
    rows = page.locator("[data-filter-row]")
    assert rows.count() == 10
    box, count, empty = page.locator("[data-list-filter]"), page.locator("[data-list-filter-count]"), page.locator("[data-list-filter-empty]")
    box.fill("kỹ sư")                                                                 # case-insensitive, by name
    expect(count).to_have_text("2 / 10")
    assert page.locator("[data-filter-row]:visible").count() == 2
    box.fill("ky su")                                                                 # ... and without the tone marks
    expect(count).to_have_text("2 / 10")
    box.fill("dieu duong")                                                            # đ and the marks of "Điều dưỡng"
    expect(count).to_have_text("1 / 10")
    box.fill("GROUPS/3")                                                              # ... or by URL
    expect(count).to_have_text("1 / 10")
    box.fill("không có nhóm này")
    expect(empty).to_be_visible()
    assert page.locator("[data-filter-row]:visible").count() == 0
    box.fill("")
    expect(empty).to_be_hidden()
    expect(count).to_have_text("")
    assert page.locator("[data-filter-row]:visible").count() == 10 and page.errors == []


def _open_dialog(page, live_admin) -> None:
    page.goto(f"{live_admin}/admin/groups?account_id=acc-a")                         # any admin page: it carries the script
    fragment = page.evaluate("url => fetch(url).then(r => r.text())", f"{live_admin}/admin/accounts/rate-limits-modal?account_id=acc-a")
    page.evaluate("html => { document.getElementById('modal-root').innerHTML = html; document.dispatchEvent(new Event('htmx:afterSwap')); }", fragment)


def test_the_delays_are_said_in_words_and_follow_what_you_type(page, live_admin):
    _open_dialog(page, live_admin)
    hint = page.locator("[data-duration-hint]").first
    initial = hint.inner_text()
    assert initial.startswith("≈ ") and "–" in initial
    page.fill("input[name=post_min_delay_seconds]", "3900")
    page.fill("input[name=post_max_delay_seconds]", "45")
    expect(hint).to_have_text("≈ 1 giờ 5 phút – 45 giây")
    page.fill("input[name=post_max_delay_seconds]", "7200")
    expect(hint).to_have_text("≈ 1 giờ 5 phút – 2 giờ")
    page.fill("input[name=post_min_delay_seconds]", "")                               # a blank box reads as 0, not "NaN"
    expect(hint).to_have_text("≈ 0 giây – 2 giờ")
    assert page.errors == []


def test_an_age_preset_fills_the_boxes_and_the_words_follow(page, live_admin):
    _open_dialog(page, live_admin)
    hint = page.locator("[data-duration-hint]").first
    page.fill("input[name=post_min_delay_seconds]", "1")
    expect(hint).to_contain_text("≈ 1 giây")
    page.locator("[data-apply-tier]").first.click()
    min_box = page.input_value("input[name=post_min_delay_seconds]")
    assert min_box != "1"
    expect(hint).to_contain_text(admin_module._duration_vi(int(min_box)))
    first_tier = next(iter(admin_module.ACCOUNT_AGE_TIERS.values()))[1]
    assert page.input_value("input[name=posts_per_day]") == str(first_tier.posts_per_day) and page.errors == []


def test_the_password_button_shows_and_hides_what_was_typed(page, live_admin):
    page.goto(f"{live_admin}/admin/groups?account_id=acc-a")
    html = admin_module._password_input_html("password")
    page.evaluate("html => { const d = document.createElement('div'); d.id = 'pw-test'; d.innerHTML = html; document.body.appendChild(d); }", html)
    box, toggle = page.locator("#pw-test input"), page.locator("#pw-test .pw-toggle")
    box.fill("abc123")
    assert box.get_attribute("type") == "password"
    toggle.click()
    assert box.get_attribute("type") == "text" and toggle.get_attribute("aria-pressed") == "true" and toggle.get_attribute("aria-label") == "Ẩn mật khẩu"
    toggle.click()
    assert box.get_attribute("type") == "password" and toggle.get_attribute("aria-pressed") == "false" and toggle.get_attribute("aria-label") == "Hiện mật khẩu"


def test_enter_in_a_number_box_saves_and_does_not_reset(page, live_admin):
    """The real hazard: Enter submits with the form's first submit button, which used to be "Khôi phục mặc định"."""
    _open_dialog(page, live_admin)
    posted = []

    def capture(route):
        posted.append(route.request.post_data or "")
        route.fulfill(status=200, content_type="text/html", body="<html><body>saved</body></html>")

    page.route("**/admin/accounts/rate-limits", capture)
    page.fill("input[name=posts_per_day]", "7")
    page.press("input[name=posts_per_day]", "Enter")
    page.wait_for_timeout(500)
    assert len(posted) == 1 and "posts_per_day=7" in posted[0] and "reset=" not in posted[0]


def test_a_search_box_that_came_back_with_text_filters_at_once(page, live_admin, monkeypatch):
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: MANY)
    page.goto(f"{live_admin}/admin/groups?account_id=acc-a")
    page.evaluate("""() => { const b = document.querySelector('[data-list-filter]'); b.dataset.filterInit = ''; b.value = 'osaka'; }""")
    page.evaluate("() => document.dispatchEvent(new Event('htmx:afterSwap'))")      # what a re-init after a restore looks like
    expect(page.locator("[data-list-filter-count]")).to_have_text("1 / 10")
