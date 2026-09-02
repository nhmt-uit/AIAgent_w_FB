"""
Smoke test: launch a real browser and open facebook.com.

Purpose: the very first sanity check before building anything else — prove
Playwright can launch a browser and reach facebook.com from THIS machine's
network. Run this directly in your own Terminal (not through any Claude
sandbox/bridge) since Claude's own execution environments are behind an
organization network proxy that blocks facebook.com.

Setup (run once):
    pip install playwright
    playwright install chromium

Run:
    python3 open_facebook.py
"""
import asyncio
from playwright.async_api import async_playwright


async def main() -> None:
    async with async_playwright() as p:
        browser = await p.chromium.launch(headless=False)  # headless=False so you can SEE it open
        page = await browser.new_page()
        await page.goto("https://www.facebook.com", wait_until="domcontentloaded", timeout=30000)
        print("Page title:", await page.title())
        print("Current URL:", page.url)
        input("Browser is open on facebook.com — press Enter here to close it...")
        await browser.close()


if __name__ == "__main__":
    asyncio.run(main())
