---
skill: Session Persistence (login state)
used_by: [human-bot-executor]
source: https://playwright.dev/python/docs/auth
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: How login sessions are saved and reused per account — read this when a task unexpectedly lands on a login page, or when setting up a new Facebook account.
> VI: Cách lưu và tái sử dụng phiên đăng nhập cho từng tài khoản — đọc file này khi một tác vụ bất ngờ bị đưa về trang đăng nhập, hoặc khi thiết lập một tài khoản Facebook mới.

# Skill: Session Persistence

## Why

Logging in fresh on every run is slow, triggers Facebook's login-anomaly
checks, and throws away the browser fingerprint continuity that makes
automated sessions look more like a returning human. Every account must
have a **persisted session** the Executor reuses.

## Storage convention

```
accounts/<account_id>/storage_state.json
```

This directory is **gitignored** — it contains live session cookies and
must never be committed or shared.

## One-time bootstrap (manual, human does the actual login)

`human_bot/bootstrap_login.py` implements this with plain Playwright:

```python
from playwright.async_api import async_playwright

async with async_playwright() as p:
    browser = await p.chromium.launch(headless=False)
    context = await browser.new_context()
    page = await context.new_page()
    await page.goto("https://www.facebook.com/login")
    # --- human logs in manually in the opened window, solves any 2FA ---
    await context.storage_state(path="accounts/<account_id>/storage_state.json")
    await browser.close()
```

This step must be done by a human, once per account, on a stable
network/IP if possible (see `skills/rate-limiting-pacing.md` for why IP
stability matters).

## Runtime usage

`human_bot/browser_pool.py` implements this — one persistent browser
context per account, kept open for the life of the service process (see
`docs/architecture.md` section 3b):

```python
from playwright.async_api import async_playwright

playwright = await async_playwright().start()
browser = await playwright.chromium.launch(headless=True)
context = await browser.new_context(storage_state=f"accounts/{account_id}/storage_state.json")
page = await context.new_page()
```

Playwright loads cookies/localStorage from the file at context creation.
Updates made during the session are only persisted back to disk when
explicitly saved — `browser_pool.py`'s `AccountSession.close()` calls
`context.storage_state(path=...)` before closing, so sessions stay valid
across restarts without re-login, as long as Facebook doesn't force a
re-auth.

## Fallback: automated credential login

`human_bot/fallback_auto_login.py` exists as a manually-triggered backup
for re-establishing a session when the normal bootstrap flow above isn't
practical. It is explicitly NOT part of the automated pipeline — it must
only be run directly by a human who watches the browser window and can
intervene for 2FA/checkpoint steps. See that file's own docstring for full
reasoning and usage. Credentials live in `.env`, never in code.

## Failure mode to detect

If a run finds itself on a Facebook login page instead of the expected
target, that means the session expired or was invalidated — this is itself
an anomaly signal (see `skills/anomaly-detection.md`) and must not trigger
an automatic re-login attempt with stored credentials; flag it for a human
to re-bootstrap the session instead.
