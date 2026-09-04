"""
One-time bootstrap: log into a Facebook account manually in a real browser
window, then save the session so human_bot can reuse it without logging in
again. See docs/skills/session-persistence.md for the reasoning.

Run directly in your own Terminal (not through any Claude sandbox/bridge):

    python3 human_bot/bootstrap_login.py <account_id>

Example:

    python3 human_bot/bootstrap_login.py my_page

This creates accounts/<account_id>/storage_state.json. That file contains
live login cookies — never commit it (already covered by .gitignore).

After running this once, register the account so the rest of the system
knows it exists: start the service (uvicorn human_bot.service:app) and
register it at /admin/accounts with this same account_id — no code edit
or restart needed. Alternatively, add it to human_bot/config.py's
ACCOUNTS dict by hand if you want it committed as a permanent default:

    "my_page": AccountConfig(account_id="my_page", display_name="My Page"),
"""
import asyncio
import sys
from pathlib import Path

from playwright.async_api import async_playwright

PROJECT_ROOT = Path(__file__).resolve().parent.parent
ACCOUNTS_DIR = PROJECT_ROOT / "accounts"


async def main(account_id: str) -> None:
    out_dir = ACCOUNTS_DIR / account_id
    out_dir.mkdir(parents=True, exist_ok=True)
    out_path = out_dir / "storage_state.json"

    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)
        context = await browser.new_context()
        page = await context.new_page()
        await page.goto("https://www.facebook.com/login", wait_until="domcontentloaded")

        print("\n" + "=" * 60)
        print(f"Log into the Facebook account for '{account_id}' in the")
        print("browser window that just opened. Complete any 2FA/checkpoint")
        print("steps until you land on your normal Facebook home feed.")
        print("=" * 60)
        input("\nPress Enter here once you are fully logged in... ")

        await context.storage_state(path=str(out_path))
        await browser.close()

        print(f"\nSaved session to: {out_path}")
        print(f"Next: register this account at /admin/accounts (account_id={account_id!r}),")
        print("or add it to human_bot/config.py's ACCOUNTS dict by hand, e.g.:")
        print(f'  "{account_id}": AccountConfig(account_id="{account_id}", display_name="..."),')


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("Usage: python3 human_bot/bootstrap_login.py <account_id>")
        sys.exit(1)
    asyncio.run(main(sys.argv[1]))
