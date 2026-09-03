"""
Keeps one persistent, already-logged-in Playwright browser open per
Facebook account for the entire lifetime of the human_bot service process,
instead of launching a fresh browser for every single task.

Why: the operator runs this service continuously (24/7) and wants the
browser sitting there already logged in, ready to act the moment n8n sends
a task — no launch latency, and the account's browsing looks like one
continuous session rather than restarting for every action (itself closer
to normal human behavior). See docs/architecture.md and
docs/skills/session-persistence.md.

This is plain Playwright (not browser-use) — see human_bot/actions.py for
why. This module is a simple in-memory pool keyed by account_id, fine for
a single-process deployment. If human_bot is ever run with multiple worker
processes, this needs to move to a model where exactly one process owns
each account's browser (a browser can't safely be driven by two processes
at once).
"""
import os

from playwright.async_api import Browser, BrowserContext, Page, Playwright, async_playwright

from human_bot.config import AccountConfig

_pool: dict[str, "AccountSession"] = {}


def _headless_default() -> bool:
    # Set HEADLESS=false in .env while testing to watch the browser act.
    return os.environ.get("HEADLESS", "true").strip().lower() != "false"


class AccountSession:
    """One persistent browser + page for a single Facebook account."""

    def __init__(self, account: AccountConfig, headless: bool | None = None):
        self.account = account
        self.headless = _headless_default() if headless is None else headless
        self._playwright: Playwright | None = None
        self.browser: Browser | None = None
        self.context: BrowserContext | None = None
        self.page: Page | None = None

    async def ensure_started(self) -> None:
        if self.page is not None:
            return
        self._playwright = await async_playwright().start()
        self.browser = await self._playwright.chromium.launch(headless=self.headless)
        self.context = await self.browser.new_context(
            storage_state=str(self.account.storage_state_path),
            # All recorded selectors in human_bot/actions.py are written
            # against Facebook's ENGLISH UI (decided 2026-09-03 — see
            # docs/skills/facebook-custom-actions.md, "Facebook UI
            # language"). Forcing it here means the bot doesn't depend on
            # the machine's own locale or Facebook's guess from IP/device
            # — but the FACEBOOK ACCOUNT ITSELF must also have its display
            # language set to English in its own settings, since an
            # account-level language preference can still override this.
            locale="en-US",
        )
        self.page = await self.context.new_page()

    async def restart_session(self) -> None:
        """
        Close and re-open this account's browser. Use this if a session
        seems to be in a bad state, without restarting the whole service
        process. (Unlike the earlier browser-use-based design, there is no
        agent system prompt to reload here — see docs/agents/
        human-bot-executor.md for what "reload a skill" now means.)
        """
        await self.close()
        await self.ensure_started()

    async def save_state(self) -> None:
        """
        Persist cookies/localStorage to disk right now, without closing the
        browser. Called after every completed task (see human_bot/agent.py)
        so the login session survives even if the process is killed
        ungracefully — e.g. Ctrl+C delivers SIGINT to Playwright's own
        Node.js driver subprocess too, which can die before an orderly
        shutdown finishes saving state (see close() below). Best-effort: a
        failed save here must never crash the caller.
        """
        if self.context is None:
            return
        try:
            await self.context.storage_state(path=str(self.account.storage_state_path))
        except Exception as e:
            print(
                f"[browser_pool] warning: failed to save session state for "
                f"'{self.account.account_id}': {e}"
            )

    async def close(self) -> None:
        # NOTE on the Ctrl+C traceback some operators see here: SIGINT goes
        # to the whole process group, including Playwright's driver
        # subprocess, which can already be dead by the time this runs. Each
        # step below is wrapped so a broken pipe during shutdown never
        # blocks the others or crashes uvicorn's shutdown sequence — this
        # is a best-effort "clean up if we still can", not a guarantee.
        await self.save_state()
        if self.browser is not None:
            try:
                await self.browser.close()
            except Exception as e:
                print(f"[browser_pool] warning: browser.close() failed: {e}")
        if self._playwright is not None:
            try:
                await self._playwright.stop()
            except Exception as e:
                print(f"[browser_pool] warning: playwright.stop() failed: {e}")
        self.page = None
        self.context = None
        self.browser = None
        self._playwright = None


def get_session(account: AccountConfig) -> AccountSession:
    if account.account_id not in _pool:
        _pool[account.account_id] = AccountSession(account)
    return _pool[account.account_id]


async def warm_up(accounts: list[AccountConfig]) -> None:
    """Pre-launch browsers for the given accounts (call at service startup)."""
    for account in accounts:
        await get_session(account).ensure_started()


async def close_all() -> None:
    for session in _pool.values():
        await session.close()
    _pool.clear()
