"""/admin/config's page script in a real browser: the unsaved-change count, "↺ đặt lại", a min above its max, dropping
changes, the save bar on each tab, and the AI switches that save the moment they are flipped.

Server-rendered side: test_admin_config_ui.py. Skipped when Playwright / Chromium is missing. The runtime config is a
throwaway file (browser_support.live_admin), and the only POSTs are the AI switch route's."""
from __future__ import annotations

import pytest

from tests.browser_support import browser, live_admin, page, page_with_cdn, require_cdn, sync_api  # noqa: F401 - fixtures, picked up by name
from human_bot import runtime_config
from human_bot.data_sync_config import DataSyncConfig
import human_bot.admin as admin_module



def default_of(field: str) -> str:
    """The default as the page prints it — read from the class at call time: some defaults come from the environment."""
    return admin_module._num_text(getattr(DataSyncConfig(), field))


expect = sync_api.expect
pytestmark = pytest.mark.filterwarnings("ignore::DeprecationWarning")            # uvicorn's own websockets import

POLL = "input[name=data_sync__poll_interval_minutes]"
GAP_MIN, GAP_MAX = "input[name=data_sync__post_gap_min_minutes]", "input[name=data_sync__post_gap_max_minutes]"


@pytest.fixture
def config_url(live_admin):
    runtime_config.save_data_sync_overrides({})
    runtime_config.save_human_typing_overrides({})
    return f"{live_admin}/admin/config"


def row(page, field: str):
    return page.locator(f"[data-field-row]:has(input[name={field}])")


def test_the_save_bar_counts_rows_changed_and_discard_puts_them_back(page, config_url):
    page.goto(f"{config_url}?tab=sync")
    note = page.locator("[data-dirty-note]")
    expect(note).to_have_text("Chưa có thay đổi")
    expect(page.locator("[data-discard]")).to_be_hidden()
    page.fill(POLL, "7")
    expect(note).to_have_text("1 thay đổi chưa lưu")
    page.fill(GAP_MAX, "120")                                                         # a pair is ONE row, however many of its boxes you touch
    page.fill(GAP_MIN, "25")
    expect(note).to_have_text("2 thay đổi chưa lưu")
    page.click("[data-discard]")
    expect(note).to_have_text("Chưa có thay đổi")
    assert page.input_value(POLL) == default_of("poll_interval_minutes") and page.input_value(GAP_MAX) == default_of("post_gap_max_minutes")
    assert page.errors == []


def test_a_changed_row_offers_its_default_and_reset_brings_it_back(page, config_url):
    page.goto(f"{config_url}?tab=sync")
    wrap = row(page, "data_sync__poll_interval_minutes").locator("[data-reset-wrap]")
    expect(wrap).to_be_hidden()
    page.fill(POLL, "7")
    expect(wrap).to_be_visible()
    assert f"mặc định {default_of('poll_interval_minutes')}" in wrap.inner_text()
    wrap.locator("[data-reset]").click()
    assert page.input_value(POLL) == default_of("poll_interval_minutes")
    expect(wrap).to_be_hidden()
    page.fill(POLL, default_of("poll_interval_minutes"))                                                             # typing the default by hand is "not changed" too
    expect(wrap).to_be_hidden()
    page.fill(POLL, "")                                                               # blank is saved as "the default" (config_save skips it): not shown as a change
    expect(wrap).to_be_hidden()


def test_a_min_above_its_max_turns_the_row_red_until_fixed(page, config_url):
    page.goto(f"{config_url}?tab=sync")
    page.fill(GAP_MIN, str(int(float(default_of("post_gap_max_minutes"))) + 100))                        # above the max
    assert "pair-bad" in row(page, "data_sync__post_gap_min_minutes").get_attribute("class")
    page.fill(GAP_MIN, "1")
    assert "pair-bad" not in row(page, "data_sync__post_gap_min_minutes").get_attribute("class")


def test_a_switch_off_its_default_resets_too(page, config_url):
    page.goto(f"{config_url}?tab=behavior")
    switch = page.locator("input[name=scheduling__auto_fire_enabled]")
    wrap = row(page, "scheduling__auto_fire_enabled").locator("[data-reset-wrap]")
    expect(wrap).to_be_hidden()
    page.locator("label.switch:has(input[name=scheduling__auto_fire_enabled])").click()
    assert switch.is_checked()
    expect(wrap).to_be_visible()
    wrap.locator("[data-reset]").click()
    assert not switch.is_checked()


def test_the_advanced_group_is_folded_until_opened_and_its_boxes_still_count(page, config_url):
    page.goto(f"{config_url}?tab=behavior")
    expect(page.locator("input[name=typing__wpm]")).to_be_hidden()
    page.click(".cfg-adv > summary")
    page.fill("input[name=typing__wpm]", "55")
    expect(page.locator("[data-dirty-note]")).to_have_text("1 thay đổi chưa lưu")


def test_the_page_save_bar_follows_the_tab_you_are_on(page_with_cdn, config_url):
    """With the real stylesheet: `.form-actions { display:flex }` once overrode the `hidden` attribute (see admin.py)."""
    page = page_with_cdn
    page.goto(f"{config_url}?tab=behavior")
    require_cdn(page)
    bar = page.locator("#config-generic-save-actions")
    expect(bar).to_be_visible()
    for target, visible in (("tab-ai", False), ("tab-sync", True), ("tab-content", False), ("tab-behavior", True)):
        page.click(f"[data-tab-target={target}]")
        assert bar.is_visible() == visible, target


def test_an_ai_switch_saves_the_moment_it_is_flipped_and_keeps_other_settings(page_with_cdn, config_url):
    page = page_with_cdn
    runtime_config.save_data_sync_overrides({"poll_interval_minutes": 30.0})
    page.goto(f"{config_url}?tab=ai")
    require_cdn(page)
    page.locator("#ai-toggle-card label.switch").first.click()
    expect(page.locator("#ai-toggle-card .flash")).to_have_text("✅ Đã lưu.")
    assert runtime_config.get_data_sync_overrides() == {"poll_interval_minutes": 30.0, "job_post_ai_enabled": False}
    page.locator("#ai-toggle-card label.switch").first.click()                        # the swapped-in card still works
    expect(page.locator("#ai-toggle-card .flash")).to_have_text("✅ Đã lưu.")
    assert runtime_config.get_data_sync_overrides()["job_post_ai_enabled"] is True
    assert page.errors == []
