"""
FALLBACK ONLY — automated email/password login for Facebook.

Purpose: a manually-triggered backup for when the normal bootstrap flow
(human_bot/bootstrap_login.py, where a person logs in by hand) is not an
option and you need to re-establish a session quickly. This is NOT part of
the automated pipeline and must never be called by human_bot/agent.py,
human_bot/service.py, or the Safety Monitor — see
docs/skills/anomaly-detection.md and docs/skills/session-persistence.md,
which both explicitly say the system must never auto-relogin on its own.

Why this is a fallback and not the normal path (see chat/README for the
full reasoning): a fresh automated login is one of the clearest bot signals
Facebook's abuse detection looks for, 2FA/checkpoint challenges usually
can't be solved by a script at all, and it requires storing a real
password. Prefer human_bot/bootstrap_login.py whenever possible. Use this
script only when you are the one running it, watching the browser window,
and ready to intervene by hand.

Setup: put credentials in a local .env file (never commit it — see
.gitignore) as:
    FB_EMAIL__<account_id>=you@example.com
    FB_PASSWORD__<account_id>=your-password

Run directly in your own Terminal (not through any Claude sandbox/bridge):

    python3 human_bot/fallback_auto_login.py <account_id>
"""
import asyncio
import os
import sys
from pathlib import Path

from dotenv import load_dotenv
from playwright.async_api import async_playwright

from human_bot.safety import detect_anomaly

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_DIR = PROJECT_ROOT / "accounts"


async def main(account_id: str) -> None:
    load_dotenv(PROJECT_ROOT / ".env")

    email = os.environ.get(f"FB_EMAIL__{account_id}")
    password = os.environ.get(f"FB_PASSWORD__{account_id}")
    if not email or not password:
        print(
            f"Missing credentials. Add these to .env:\n"
            f"  FB_EMAIL__{account_id}=...\n"
            f"  FB_PASSWORD__{account_id}=...\n"
        )
        sys.exit(1)

    out_dir = ACCOUNTS_DIR / account_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "storage_state.json"

    async with async_playwright() as p:
        # headless=False on purpose — you are expected to watch this run and
        # step in manually for any 2FA/checkpoint screen.
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()

        await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")

        # NOTE: these selectors are Facebook's standard login form field
        # names at the time this was written and may need updating — see
        # docs/skills/vision-fallback.md if the form isn't found.
        try:
            await page.fill('input[name="email"]', email, timeout=15000)
            await page.fill('input[name="pass"]', password, timeout=15000)
            await page.click('button[name="login"]', timeout=15000)
        except Exception as e:
            print(f"Could not fill/submit the login form automatically: {e}")
            print("The browser window is still open — you can log in by hand instead.")

        print("\n" + "=" * 60)
        print("If Facebook is asking for a verification code, identity check,")
        print("or anything else automation can't handle, resolve it by hand")
        print("in the browser window now.")
        print("=" * 60)
        input("\nPress Enter here once you are fully logged in and on your feed... ")

        page_text = await page.inner_text("body")
        signal = detect_anomaly(page_text, page.url)
        if signal:
            print(f"\nWARNING: possible restriction/checkpoint signal detected: {signal!r}")
            print("Do NOT save this as a trusted session — resolve the issue first,")
            print("then re-run this script.")
            await browser.close()
            sys.exit(1)

        await context.storage_state(path=str(out_path))
        await browser.close()

        print(f"\nSaved session to: {out_path}")
        print("Next: make sure this account_id is registered in human_bot/config.py.")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 human_bot/fallback_auto_login.py <account_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
