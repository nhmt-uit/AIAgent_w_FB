"""
Purpose of this file / Muc dich cua file nay:
EN: Raw Playwright Codegen recording (unedited) for posting to a personal
profile, captured against account "troy" on 2026-09-02. This is a
reference/source artifact, NOT part of the human_bot pipeline — the real,
generalized implementation lives in human_bot/actions.py's
post_to_own_profile(), translated from this to the async API and adapted
to work for any account (not just "troy"). Keep this file when re-recording
a broken selector with Codegen: overwrite it with the new recording so
there is always a matching raw reference for the current actions.py code.
See docs/skills/facebook-custom-actions.md.
VI: Ban ghi Codegen goc (chua chinh sua) cho hanh dong dang bai len trang
ca nhan, ghi lai voi tai khoan "troy" ngay 2026-09-02. Day la file tham
chieu/nguon, KHONG nam trong pipeline chinh cua human_bot — phan trien
khai thuc te, tong quat hoa, nam trong post_to_own_profile() cua
human_bot/actions.py, duoc dich lai tu file nay sang async API va chinh
de dung duoc cho moi tai khoan (khong chi rieng "troy"). Giu lai file
nay khi ghi lai Codegen cho mot selector bi hong: ghi de bang ban ghi
moi de luon co mot ban tham chieu goc khop voi code actions.py hien tai.
Xem docs/skills/facebook-custom-actions.md.
"""
import re
from playwright.sync_api import Playwright, sync_playwright, expect


def run(playwright: Playwright) -> None:
    browser = playwright.chromium.launch(headless=False)
    context = browser.new_context(storage_state="accounts/troy/storage_state.json")
    page = context.new_page()
    page.goto("https://www.facebook.com/")
    page.get_by_role("button", name="Troy ơi, bạn đang nghĩ gì thế?").click()
    page.get_by_role("paragraph").click()
    page.get_by_role("button", name="Chỉnh sửa quyền riêng tư. Đ").click()
    page.locator("label:nth-child(6) > div > .x9f619.x1n2onr6.x1ja2u2z.x78zum5.xdt5ytf.x1iyjqo2.x2lwn1j > .x9f619.x1n2onr6.x1ja2u2z.x78zum5.xdt5ytf.x2lah0s.x193iq5w.xmzvs34 > .x1i10hfl.x1qjc9v5 > .html-div > .x9f619.x1ja2u2z.x78zum5.x2lah0s.x1n2onr6.x1qughib > .x9f619.x1ja2u2z.x78zum5.x1n2onr6.x1iyjqo2.xs83m0k > .x9f619").click()
    page.get_by_role("button", name="Đã lựa chọn xong đối tượng").click()
    page.locator(".x1ejq31n.x18oe1m7.x1sy0etr.xstzfhl.x9f619.xzsf02u").click()
    page.get_by_role("textbox").fill("Ở nhà một mình, nó cô đơn thật sự!​")
    page.get_by_role("button", name="Đăng").click()

    # ---------------------
    context.storage_state(path="accounts/troy/storage_state.json")
    context.close()
    browser.close()


with sync_playwright() as playwright:
    run(playwright)
