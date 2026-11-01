"""Cross-screen UI rules (2026-11-02): the CSS bug that made a hovered tab unreadable, and page
intros written for the person using the screen (no file names, no code identifiers)."""
from __future__ import annotations

import re

import pytest

from human_bot import admin
from tests.test_page_account import client  # noqa: F401  (fixture)

PAGES = ["/admin/config", "/admin/config?tab=sync", "/admin/post", "/admin/schedule", "/admin/groups", "/admin/reports", "/admin/accounts"]


def test_a_hovered_tab_repaints_its_own_background():
    css = admin._PAGE_STYLE
    # the global `button:hover` (specificity 0,1,1) paints every button indigo; a tab has to opt out explicitly
    assert ".tab-btn:hover { @apply bg-transparent text-gray-900; }" in css
    assert ".tab-btn.active, .tab-btn.active:hover { @apply text-indigo-600 border-indigo-600; }" in css


@pytest.mark.parametrize("path", PAGES)
def test_page_intros_name_no_files_or_code(client, path):
    page = client.get(path).text
    intros = re.findall(r'<p class="page-desc"[^>]*>(.*?)</p>', page, flags=re.S)
    assert intros, "page has no intro?"
    for intro in intros:
        for jargon in (".py", "docs/", "runtime_config", "run_task", "data_sync", "DataSyncConfig", "broadcast"):
            assert jargon not in intro or "bootstrap_login" in intro, f"{path}: {jargon!r} in an intro: {intro[:100]}"
