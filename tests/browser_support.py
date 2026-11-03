"""Shared fixtures for the real-browser tests (Playwright + Chromium) of the admin pages.

Import them into a test module with `from tests.browser_support import live_admin, browser, page  # noqa: F401` — the
module then skips itself when Playwright / uvicorn / Chromium is missing. `live_admin` serves the admin app on a
free local port with every store path (runtime config, schedule folders) in a throwaway directory and the accounts
and groups faked; `page` blocks every request that leaves 127.0.0.1 (the CDN scripts are not needed for what is
checked, and offline they would hang for 30 s)."""
from __future__ import annotations

import re
import socket
import threading
import time

import pytest

sync_api = pytest.importorskip("playwright.sync_api")
uvicorn = pytest.importorskip("uvicorn")

import human_bot.admin as admin_module
from human_bot import content_strategist, runtime_config, schedule_store
from human_bot.config import RateLimits
from tests.test_admin_post import _make_test_app
from tests.test_admin_post_ui import GROUPS, _FakeAccount


@pytest.fixture(scope="module")
def live_admin(tmp_path_factory, request):
    """The origin of a running admin app, e.g. "http://127.0.0.1:54321" (the pages are under /admin/...)."""
    tmp = tmp_path_factory.mktemp("browser-admin")
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
    return f"http://127.0.0.1:{port}"


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
    ctx.route(re.compile(r"^(?!http://127\.0\.0\.1)"), lambda route: route.abort())
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    yield pg
    ctx.close()


@pytest.fixture
def page_with_cdn(browser):
    """Like `page`, but the two CDN scripts the admin pages use may load: htmx (hx-post / hx-get need it) and Tailwind
    (the real stylesheet — without it a `hidden` attribute is only the browser's default, so a CSS rule that overrides
    it, like the one in admin.py's `.form-actions[hidden]` comment, could never be caught). Offline, the requests fail
    and the tests that need them skip themselves — see `require_cdn`."""
    ctx = browser.new_context(viewport={"width": 1280, "height": 900})
    ctx.route(re.compile(r"^(?!http://127\.0\.0\.1|https://unpkg\.com/htmx\.org|https://cdn\.tailwindcss\.com)"), lambda route: route.abort())
    pg = ctx.new_page()
    pg.errors = []
    pg.on("pageerror", lambda e: pg.errors.append(str(e)))
    yield pg
    ctx.close()


def require_cdn(pg) -> None:
    """Skip unless htmx and Tailwind both loaded (call after the page's first goto())."""
    pg.wait_for_timeout(300)                                                           # Tailwind's play CDN compiles after load
    if pg.evaluate("typeof htmx") != "object" or pg.evaluate("typeof tailwind") == "undefined":
        pytest.skip("htmx / Tailwind could not be loaded from their CDNs (offline?)")
