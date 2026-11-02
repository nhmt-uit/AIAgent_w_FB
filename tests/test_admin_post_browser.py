"""/admin/post's page script in a real browser: the tab that stays put and the typed text that survives an account
switch or a validation error, the "Sẽ tạo N bài" count, the salary hint that follows the period.

The server-rendered side is covered in test_admin_post_ui.py; this is the part only a browser can show. Skipped
when Playwright (or its Chromium) is not installed. Nothing here schedules a task: the only POSTs are ones the
server rejects before it writes anything, and every store path is a throwaway directory anyway."""
from __future__ import annotations

import re
import socket
import threading
import time

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
expect = sync_api.expect
uvicorn = pytest.importorskip("uvicorn")

pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")            # uvicorn's own websockets import

import human_bot.admin as admin_module
from human_bot import content_strategist, runtime_config, schedule_store
from human_bot.config import RateLimits
from tests.test_admin_post import _make_test_app
from tests.test_admin_post_ui import GROUPS, _FakeAccount


@pytest.fixture(scope="module")
def base_url(tmp_path_factory, request):
    tmp = tmp_path_factory.mktemp("post-browser")
    mp = pytest.MonkeyPatch()
    request.addfinalizer(mp.undo)                                                      # also when the setup below skips or raises
    mp.delenv("ADMIN_USERNAME", raising=False)
    mp.delenv("ADMIN_PASSWORD", raising=False)
    mp.setattr(runtime_config, "RUNTIME_CONFIG_PATH", tmp / "runtime_config.json")
    for name in ("PENDING_DIR", "POSTED_DIR", "FAILED_DIR", "CANCELLED_DIR", "MISSED_DIR", "NEEDS_REVIEW_DIR", "REJECTED_REVIEW_DIR"):
        mp.setattr(schedule_store, name, tmp / name.lower())
    accounts = {
        "acc-a": _FakeAccount("acc-a", RateLimits(posts_per_day=30, max_groups_per_post=2), tmp / "a.jsonl"),
        "acc-b": _FakeAccount("acc-b", RateLimits(posts_per_day=30, max_groups_per_post=3), tmp / "b.jsonl", display_name="Acc B"),
    }
    mp.setattr(admin_module, "get_all_accounts", lambda: accounts)
    mp.setattr(admin_module, "get_joined_groups", lambda aid: GROUPS)
    mp.setattr(content_strategist, "ai_provider_configured", lambda: True)

    with socket.socket() as sock:
        sock.bind(("127.0.0.1", 0))
        port = sock.getsockname()[1]
    server = uvicorn.Server(uvicorn.Config(_make_test_app(), host="127.0.0.1", port=port, log_level="warning"))
    thread = threading.Thread(target=server.run, daemon=True)
    thread.start()

    def stop():
        server.should_exit = True
        thread.join(5)

    request.addfinalizer(stop)
    for _ in range(100):
        if server.started:
            break
        time.sleep(0.05)
    else:
        pytest.skip("test server did not start")
    return f"http://127.0.0.1:{port}/admin/post"


@pytest.fixture(scope="module")
def browser():
    with sync_api.sync_playwright() as p:
        try:
            b = p.chromium.launch(headless=True)
        except Exception as exc:  # noqa: BLE001 - no browser binary installed
            pytest.skip(f"Chromium not available: {exc}")
        yield b
        b.close()


@pytest.fixture
def page(browser):
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.route(re.compile(r"^(?!http://127\.0\.0\.1)"), lambda route: route.abort())      # the CDN scripts: not needed, and not worth a 30 s hang offline
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    yield pg
    ctx.close()


def _active_tab(page) -> str:
    return page.locator(".tab-btn.active").inner_text()


def test_switching_account_keeps_the_tab_and_the_typed_text_and_a_plain_visit_starts_empty(page, base_url):
    page.goto(f"{base_url}?tab=job")
    page.fill("input[name=title]", "Thợ hàn Aichi")
    page.fill("input[name=company]", "ABC")
    page.fill("textarea[name=extra_info]", "Tăng ca 30h")
    page.fill("input[name=salary_min]", "22")
    page.select_option("select[name=salary_period]", "hour")
    page.select_option("#post-account-select", "acc-b")
    page.wait_for_url("**account_id=acc-b**")

    assert "Tin tuyển dụng" in _active_tab(page)
    assert [page.input_value("input[name=title]"), page.input_value("input[name=company]"), page.input_value("textarea[name=extra_info]"),
            page.input_value("input[name=salary_min]"), page.input_value("select[name=salary_period]")] == ["Thợ hàn Aichi", "ABC", "Tăng ca 30h", "22", "hour"]
    assert page.input_value("input[name=group_count]") == "3"                          # acc-b's own limit, not acc-a's 2
    assert "Nhập số yên" in page.locator("[data-salary-hint]").inner_text()           # the hint followed the restored period

    page.goto(f"{base_url}?tab=job")                                                  # a normal visit: nothing comes back
    assert page.input_value("input[name=title]") == ""
    assert page.errors == []


def test_switching_account_stays_on_a_tab_that_is_not_the_default(page, base_url):
    page.goto(f"{base_url}?tab=comment")
    page.select_option("#post-account-select", "acc-b")
    page.wait_for_url("**account_id=acc-b**")
    assert "Bình luận" in _active_tab(page) and page.locator("#tab-comment").is_visible()
    assert "tab=comment" in page.url and "tab-comment" not in page.url                 # the key, not the button's id


def test_a_validation_error_brings_back_every_block_and_keeps_the_retry_link(page, base_url):
    page.goto(f"{base_url}?tab=group&prefill_content=Noi+dung+A&prefill_target_url=https://facebook.com/groups/1&prefill_retry_of_log_id=7")
    page.click("[data-add-block]")
    page.locator("[data-block]").nth(1).locator("textarea").fill("Noi dung B")
    page.locator("[data-block]").nth(0).locator(".group-pill").nth(1).click()          # un-tick block 0's prefilled group: nothing ticked anywhere
    assert page.locator("[data-post-count]").inner_text() == "Chưa chọn nhóm nào"
    page.click("button:has-text('Lên lịch tất cả')")
    page.wait_for_url("**error=**")
    assert "Cần ít nhất 1 khối" in page.locator(".error").first.inner_text()

    blocks = page.locator("[data-block]")
    assert blocks.count() == 2
    assert [blocks.nth(0).locator("textarea").input_value(), blocks.nth(1).locator("textarea").input_value()] == ["Noi dung A", "Noi dung B"]
    assert page.eval_on_selector("form[action='/admin/post/schedule-groups'] input[name=retry_of_log_id]", "e => e.value") == "7"
    assert page.errors == []


def test_the_chosen_time_comes_back_too_because_blank_means_now(page, base_url):
    page.goto(f"{base_url}?tab=group")
    page.fill("textarea[name=content_0]", "Noi dung")
    page.click("[data-schedule-preset='+1d']")
    picked = page.eval_on_selector("input[name=start_at]", "e => e.value")
    assert picked
    page.click("button:has-text('Lên lịch tất cả')")                                   # no group ticked: the server rejects it
    page.wait_for_url("**error=**")
    assert page.eval_on_selector("input[name=start_at]", "e => e.value") == picked
    assert page.eval_on_selector("[data-schedule-local]", "e => e.value") != ""        # the visible picker shows it again too


def test_the_count_follows_ticks_blocks_and_select_all(page, base_url):
    page.goto(f"{base_url}?tab=group")
    count = page.locator("[data-post-count]")                                          # (re-counted on the next tick, hence expect())
    expect(count).to_have_text("Chưa chọn nhóm nào")
    page.locator(".group-pill").nth(0).click()
    page.locator(".group-pill").nth(1).click()
    expect(count).to_have_text("Sẽ tạo 2 bài")
    page.click("[data-select-all-groups]")
    expect(count).to_have_text("Sẽ tạo 3 bài")
    page.click("[data-add-block]")
    page.locator("[data-block]").nth(1).locator("[data-select-all-groups]").click()
    expect(count).to_have_text("Sẽ tạo 6 bài")
    page.locator("[data-block]").nth(1).locator("[data-remove-block]").click()
    expect(count).to_have_text("Sẽ tạo 3 bài")


def test_the_salary_hint_follows_the_period(page, base_url):
    page.goto(f"{base_url}?tab=job")
    hint = page.locator("[data-salary-hint]")
    assert "250.000 yên mỗi tháng" in hint.inner_text()
    page.select_option("select[name=salary_period]", "year")
    assert "mỗi năm" in hint.inner_text()
    page.select_option("select[name=salary_period]", "hour")
    assert hint.inner_text() == "Nhập số yên: 1500 nghĩa là 1.500 yên mỗi giờ."


@pytest.mark.parametrize("draft", [
    {"switched": True},                                                                # no fields at all
    {"switched": True, "fields": {}, "checks": {}, "blocks": {"/admin/post/schedule-groups": "many"}},
    {"switched": True, "fields": {"/admin/post/schedule-job|visa|-1": "no-such-visa"}, "checks": {}},
    "not an object",
])
def test_a_draft_the_page_cannot_use_never_breaks_it(page, base_url, draft):
    page.goto(f"{base_url}?tab=job")
    page.evaluate("d => sessionStorage.setItem('human_bot.postDraft', JSON.stringify(d))", draft)
    page.goto(f"{base_url}?tab=job")
    page.click("[data-tab-target='tab-group']")                                        # the tab script (initialised after the draft) still runs
    assert page.locator("#tab-group").is_visible() and page.locator("#tab-job").is_hidden()
    assert page.locator("[data-post-count]").inner_text() == "Chưa chọn nhóm nào"
    assert page.input_value("select[name=visa]") == ""                                 # a value the select doesn't offer is not applied
    assert page.evaluate("sessionStorage.getItem('human_bot.postDraft')") is None      # and it is consumed, not kept for the next visit
    assert page.errors == []


def test_ticked_groups_and_the_group_count_stay_with_the_account_they_were_made_for(page, base_url):
    page.goto(f"{base_url}?tab=group")
    page.locator(".group-pill").nth(0).click()
    page.select_option("#post-account-select", "acc-b")
    page.wait_for_url("**account_id=acc-b**")
    assert page.locator(".group-pill input:checked").count() == 0
    assert page.locator("[data-post-count]").inner_text() == "Chưa chọn nhóm nào"
