"""
Purpose of this file / Muc dich cua file nay:
EN: In-process manager for the "Đăng nhập & lưu phiên" button on
/admin/accounts — a web-triggered alternative to running
human_bot/bootstrap_login.py by hand in a terminal. Requested 2026-09-09.

Same idea as that script (open a real, headed Facebook login page, let a
human log in, then save Playwright's storage_state.json) but adapted to a
request/response web UI instead of a blocking terminal script: there is no
`input("Press Enter...")` to wait on here, so the flow is split into
start() (open the browser, return immediately) and confirm() (called from
a second click once the human is actually done logging in), with status()
polled in between so /admin/accounts can show live progress via htmx.

IMPORTANT: the browser window this opens is headed (headless=False) and
appears on the screen of the MACHINE RUNNING THE human_bot SERVICE
PROCESS — not on the screen of whoever is looking at /admin in their own
browser. This only makes sense for a local, single-operator deployment
(the same assumption human_bot/bootstrap_login.py and this project's
README already make), never a remote/headless server.

Sessions are tracked in a plain in-memory dict, keyed by account_id, alive
only for this process's lifetime — restarting the service loses any
in-flight (not yet confirmed) login session, same as Ctrl+C-ing a running
bootstrap_login.py would.
VI: Quan ly (trong tien trinh) cho luong "Dang nhap & luu phien" o nut tren
/admin/accounts — mot cach thay the qua web cho viec chay tay
human_bot/bootstrap_login.py trong terminal. Yeu cau 2026-09-09.
"""
from __future__ import annotations

import asyncio
from dataclasses import dataclass
from pathlib import Path

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from human_bot.fingerprint import get_fingerprint

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_DIR = PROJECT_ROOT / "accounts"


@dataclass
class _LoginSession:
    status: str  # "opening" | "waiting_confirm" | "saved" | "error"
    error: str | None = None
    playwright: Playwright | None = None
    browser: Browser | None = None
    context: BrowserContext | None = None
    page: Page | None = None


# Single-process, in-memory only — see module docstring. Not safe to share
# across multiple worker processes (same caveat human_bot/browser_pool.py
# already documents for its own _pool).
_sessions: dict[str, _LoginSession] = {}


async def _close(session: _LoginSession) -> None:
    """Best-effort teardown — mirrors browser_pool.AccountSession.close()'s
    exception-swallowing reasoning: a failure closing an already-dead
    browser must never block the admin action (saving, cancelling) that
    triggered this."""
    try:
        if session.browser is not None:
            await session.browser.close()
    except Exception:  # noqa: BLE001
        pass
    try:
        if session.playwright is not None:
            await session.playwright.stop()
    except Exception:  # noqa: BLE001
        pass


async def start(account_id: str) -> None:
    """Open a real (headed) browser window at the Facebook login page for
    `account_id`. Meant to be fired via asyncio.create_task() from the web
    request handler (POST /admin/accounts/bootstrap-login/start), which
    returns to the browser immediately rather than waiting on this — the
    admin UI polls status() instead. Replaces any previous in-flight
    session for the same account_id (e.g. the operator re-clicked "Mở
    trình duyệt" after closing the window by hand)."""
    old = _sessions.get(account_id)
    session = _LoginSession(status="opening")
    _sessions[account_id] = session
    if old is not None:
        await _close(old)

    try:
        session.playwright = await async_playwright().start()
        session.browser = await session.playwright.chromium.launch(headless=False)
        # locale="en-US" for the same reason browser_pool.py sets it on
        # every production session — every selector in human_bot/actions.py
        # is recorded against Facebook's English UI (see
        # docs/skills/facebook-custom-actions.md, "Facebook UI language").
        # The Facebook account's OWN language setting still has to be
        # English too; this only forces the browser side.
        # Same per-account viewport/DPI browser_pool.py's production
        # sessions use — see human_bot/fingerprint.py's docstring. Matters
        # here too so the fingerprint an account logs in under is the same
        # one it's actually used under afterward.
        fp = get_fingerprint(account_id)
        session.context = await session.browser.new_context(
            locale="en-US", viewport=fp.viewport, device_scale_factor=fp.device_scale_factor,
        )
        session.page = await session.context.new_page()
        await session.page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")
        session.status = "waiting_confirm"
    except Exception as exc:  # noqa: BLE001 — surfaced to the admin UI via status(), never raised into the background task
        session.status = "error"
        session.error = str(exc)


def status(account_id: str) -> tuple[str, str | None]:
    """("none", None) if nothing was ever started (or it was already
    confirmed/cancelled) for this account_id; otherwise the current
    (status, error) pair — see _LoginSession.status for the state names."""
    session = _sessions.get(account_id)
    if session is None:
        return "none", None
    return session.status, session.error


async def confirm(account_id: str) -> tuple[bool, str | None]:
    """Called once the human has finished logging in inside the window
    start() opened. Saves accounts/<account_id>/storage_state.json (same
    output path/format human_bot/bootstrap_login.py produces) and closes
    the browser. Returns (True, None) on success or (False, error message)
    otherwise — never raises, so the route handler can render either
    outcome directly."""
    session = _sessions.get(account_id)
    if session is None or session.status != "waiting_confirm":
        return False, "Không có phiên đăng nhập nào đang chờ xác nhận cho tài khoản này — bấm \"Mở trình duyệt đăng nhập\" lại."
    try:
        out_dir = ACCOUNTS_DIR / account_id
        out_dir.mkdir(parents=True, exist_ok=True)
        await session.context.storage_state(path=str(out_dir / "storage_state.json"))
    except Exception as exc:  # noqa: BLE001
        # The browser/context is closed either way (finally, below) — drop
        # the now-dead session instead of leaving it in _sessions still
        # claiming "waiting_confirm" (status() would keep reporting a
        # session the admin UI has no working button left to act on;
        # start() would still recover on the NEXT click by closing this
        # stale entry first, but there's no reason to leave that trap set).
        _sessions.pop(account_id, None)
        return False, str(exc)
    finally:
        await _close(session)
    _sessions.pop(account_id, None)
    return True, None


async def cancel(account_id: str) -> None:
    session = _sessions.pop(account_id, None)
    if session is not None:
        await _close(session)
