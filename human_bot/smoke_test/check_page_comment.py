"""
Smoke test: comment on a Facebook group post AS A PAGE and find out exactly
how the "send" step works (2026-10-31). The Page recording
(codegen_page_identity.py) stopped right after typing the comment, so the
submit step for the Page identity is still unconfirmed.

THIS SCRIPT POSTS ONE REAL COMMENT from the Page. Before sending it shows
which identity the comment box belongs to and the exact text, and waits for
you to type YES. Use a post where one extra comment is harmless (e.g. your
own test post), and a short text you don't mind seeing — you can delete the
comment by hand afterwards.

What it reports:
  - the comment box's accessible name (it should contain the Page's name,
    e.g. "Answer as Đơn Kỹ Sư Nhật" — if it does not, the script refuses)
  - which send mechanism worked: the "Post comment" button, or Enter
  - whether the comment text then appears on the page (= really posted)

It only READS the probe state saved by check_page_identity.py ("switch"
step) and never saves any state. Nothing but this one comment is sent.

Run from the project root, in your own Terminal (a real browser opens):

  python3 -m human_bot.smoke_test.check_page_comment --account tu_iizuki \\
      --page "Đơn Kỹ Sư Nhật" \\
      --url "https://www.facebook.com/groups/<id>/posts/<id>" \\
      --text "Test comment, xin bỏ qua"
"""
from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from playwright.sync_api import sync_playwright

ROOT = Path(__file__).resolve().parent.parent.parent
COMMENT_BOX = re.compile(r"comment|answer|bình luận|câu trả lời", re.IGNORECASE)
# Deliberately NOT a bare "Comment"/"Bình luận": a post's action bar has its own
# "Comment" button that only focuses the box and sends nothing.
SEND_BUTTON = re.compile(r"^(Post comment|Đăng bình luận)$", re.IGNORECASE)


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument("--account", required=True)
    parser.add_argument("--page", required=True, help="exact Page name, as in 'Switch to <name>'")
    parser.add_argument("--url", required=True, help="permalink of the post to comment on")
    parser.add_argument("--text", required=True, help="the comment text")
    parser.add_argument("--state", help="storage-state file (default: accounts/<account>/_page_probe_state.json)")
    args = parser.parse_args()

    state = Path(args.state) if args.state else ROOT / "accounts" / args.account / "_page_probe_state.json"
    if not state.exists():
        print(f"State file not found: {state}\nRun check_page_identity.py 'switch' first.")
        return 1

    with sync_playwright() as p:
        browser = p.chromium.launch(headless=False)
        context = browser.new_context(locale="en-US", storage_state=str(state))
        page = context.new_page()
        page.goto(args.url, wait_until="domcontentloaded", timeout=45000)
        page.wait_for_timeout(4000)

        box = page.get_by_role("textbox", name=COMMENT_BOX).first
        try:
            box.wait_for(state="visible", timeout=20000)
        except Exception:  # noqa: BLE001
            print("No comment box found on this page (wrong URL, no access, or comments are off). Nothing was sent.")
            browser.close()
            return 1

        label = box.get_attribute("aria-label") or ""
        print(f"\nComment box accessible name: {label!r}")
        if args.page.lower() not in label.lower():
            print(f"REFUSING: the comment box is not labelled with the Page name '{args.page}'.\n"
                  "The session may be acting as your personal profile. Nothing was sent.")
            page.screenshot(path=str(ROOT / "accounts" / args.account / "_page_comment_refused.png"))
            browser.close()
            return 2

        print(f"Identity looks right. Text to send: {args.text!r}")
        if input("Type YES to post this comment as the Page: ").strip() != "YES":
            print("Cancelled. Nothing was sent.")
            browser.close()
            return 0

        box.click()
        box.fill(args.text)
        page.wait_for_timeout(1200)

        mechanism = None
        button = page.get_by_role("button", name=SEND_BUTTON)
        if button.count() > 0:
            try:
                button.first.click(timeout=5000)
                mechanism = f"button {button.first.get_attribute('aria-label') or 'click'!r}"
            except Exception as exc:  # noqa: BLE001
                print(f"Send button was found but the click failed ({exc}); trying Enter.")
        if mechanism is None:
            box.press("Enter")
            mechanism = "Enter key"

        page.wait_for_timeout(5000)
        # The typed text is also visible INSIDE the box until it is sent, so
        # "text found on the page" alone proves nothing — require the box to
        # have emptied as well.
        text_on_page = page.get_by_text(args.text, exact=False).count() > 0
        remaining = (box.inner_text() or "").strip() if box.count() else ""
        box_emptied = remaining == ""
        posted = text_on_page and box_emptied
        print(f"\nSend mechanism used : {mechanism}")
        print(f"Text visible on page: {text_on_page}")
        print(f"Box emptied after send: {box_emptied}")
        print("RESULT:", "comment POSTED" if posted else "NOT confirmed — look at the window / screenshot")
        shot = ROOT / "accounts" / args.account / "_page_comment_result.png"
        page.screenshot(path=str(shot))
        print(f"Screenshot: {shot}")
        input("\nPress Enter to close the browser (delete the test comment by hand if you like)...")
        browser.close()
    return 0


if __name__ == "__main__":
    sys.exit(main())
