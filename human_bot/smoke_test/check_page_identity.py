"""
Smoke test: does a Facebook "acting as a Page" identity SURVIVE being saved
to a storage_state file and reloaded? (2026-10-31, deciding whether the bot
can treat a Page as its own account.)

Why it matters: the bot only ever runs from a saved storage_state.json. If
the Page identity is kept in that file, a Page "account" is just another
state file. If it is NOT, the bot must click "Switch to <Page>" at the start
of every run and verify it worked before posting.

SAFE BY DESIGN: this script NEVER reads-then-overwrites the real
accounts/<id>/storage_state.json. It only READS it, and writes its probe
state to a separate file (accounts/<id>/_page_probe_state.json, git-ignored
like everything under accounts/). It does not post, comment, like or send
anything — it only opens the account menu and reads the "Switch to ..."
buttons. Cookie VALUES are never printed, only names.

How to read the result: the account menu lists the OTHER identities as
"Switch to <name>" buttons. If "Switch to <Page name>" is offered, you are
currently the personal profile; if the Page's name is NOT offered but another
"Switch to ..." is, you are currently the Page.

Run from the project root, in your own Terminal (a real browser window opens):

  # step 1 - from your personal session, switch to the Page and save the probe state
  python3 -m human_bot.smoke_test.check_page_identity switch --account tu_iizuki --page "Đơn Kỹ Sư Nhật"

  # step 2 - reopen with ONLY the saved probe state: which identity are we now?
  python3 -m human_bot.smoke_test.check_page_identity check --account tu_iizuki --page "Đơn Kỹ Sư Nhật"

  # optional - what does the real (untouched) session look like?
  python3 -m human_bot.smoke_test.check_page_identity check --account tu_iizuki --page "Đơn Kỹ Sư Nhật" --real
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import Page, sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
ACCOUNT_MENU = re.compile(r"^(Account|Tài khoản)", re.IGNORECASE)
SWITCH_TO = re.compile(r"^(Switch to|Chuyển sang)\s+(.+)$", re.IGNORECASE)


def _state_paths(account: str) -> tuple[Path, Path]:
    base = ROOT / "accounts" / account
    return base / "storage_state.json", base / "_page_probe_state.json"


def _open_account_menu(page: Page) -> None:
    page.get_by_role("button", name=ACCOUNT_MENU).first.click()
    page.wait_for_timeout(1500)


def _switch_buttons(page: Page) -> list[str]:
    """Names of every "Switch to ..." button currently visible in the menu
    (= the identities we are NOT currently using)."""
    names = []
    for button in page.get_by_role("button").all():
        try:
            name = (button.get_attribute("aria-label") or button.inner_text() or "").strip()
        except Exception:  # noqa: BLE001 - a detached node mid-render is fine to skip
            continue
        m = SWITCH_TO.match(name)
        if m:
            names.append(m.group(2).strip())
    return sorted(set(names))


def _report(page: Page, context, page_name: str) -> None:
    others = _switch_buttons(page)
    cookies = sorted({c["name"] for c in context.cookies() if "facebook" in c.get("domain", "")})
    print()
    print("Identities offered by 'Switch to ...':", others or "(none found — menu may not have opened)")
    print("Cookie names present:", cookies)
    print("i_user cookie present:", "i_user" in cookies)
    if not others:
        verdict = "UNKNOWN — no 'Switch to' button found; check the screenshot / the open window"
    elif any(page_name.lower() == o.lower() for o in others):
        verdict = f"PERSONAL profile (the Page '{page_name}' is offered as a switch target)"
    else:
        verdict = f"most likely the PAGE '{page_name}' (it is not offered; other identities are)"
    print("CURRENT IDENTITY:", verdict)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("mode", choices=["switch", "check"])
    parser.add_argument("--account", required=True)
    parser.add_argument("--page", required=True, help="exact Page name as shown in 'Switch to <name>'")
    parser.add_argument("--real", action="store_true", help="check mode: use the real storage_state.json instead of the probe file")
    args = parser.parse_args()

    real_state, probe_state = _state_paths(args.account)
    source = real_state if (args.mode == "switch" or args.real) else probe_state
    if not source.exists():
        print(f"State file not found: {source}" + ("  (run the 'switch' step first)" if source == probe_state else ""))
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="en-US", storage_state=str(source))
        page = context.new_page()
        page.goto("https://www.facebook.com/", wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(3000)
        _open_account_menu(page)
        print(f"[{args.mode}] state loaded from: {source.name}")
        print("BEFORE:")
        _report(page, context, args.page)

        if args.mode == "switch":
            button = page.get_by_role("button", name=re.compile(rf"^Switch to {re.escape(args.page)}$", re.IGNORECASE))
            if button.count() == 0:
                print(f"\nNo 'Switch to {args.page}' button — already the Page, or the name differs. Nothing was changed.")
            else:
                button.first.click()
                page.wait_for_timeout(6000)
                _open_account_menu(page)
                print("\nAFTER switching:")
                _report(page, context, args.page)
                context.storage_state(path=str(probe_state))
                print(f"\nProbe state saved to: {probe_state}  (the real storage_state.json was NOT touched)")

        shot = ROOT / "accounts" / args.account / f"_page_probe_{args.mode}.png"
        page.screenshot(path=str(shot))
        print(f"Screenshot (account menu): {shot}")
        input("\nPress Enter to close the browser (nothing else is saved)...")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
