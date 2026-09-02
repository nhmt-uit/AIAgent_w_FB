---
skill: Anomaly / Restriction Detection
used_by: [human-bot-executor, safety-monitor]
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: The list of signals meaning "Facebook has restricted/challenged this account" and what to do — read this whenever a run fails unexpectedly, or after Facebook shows a new warning message you don't recognize.
> VI: Danh sách dấu hiệu cho biết "tài khoản đang bị Facebook hạn chế/thử thách" và cách xử lý — đọc file này khi một lượt chạy thất bại bất thường, hoặc khi Facebook hiện một thông báo cảnh báo mới lạ.

# Skill: Anomaly Detection

## Why

The single worst outcome is the Executor Agent repeatedly retrying against
an account Facebook has already flagged — this all but guarantees a full
ban. Detecting restriction signals early and stopping immediately is more
important than completing any individual task.

## Signals to check on every page load, before proceeding with an action

Text-based (case-insensitive substring match against extracted page text):
- "We restricted your account"
- "confirm your identity"
- "unusual activity"
- "you're temporarily blocked"
- "please verify"
- "checkpoint" (in URL path, e.g. `facebook.com/checkpoint/`)

Structural:
- A captcha iframe/element present on the page.
- The page unexpectedly redirects to a login page for an account with a
  valid `storage_state` (see `skills/session-persistence.md`).

## Required behavior on detection

1. Stop the current task immediately — do not attempt the intended action.
2. Do **not** retry, and do not attempt to solve a captcha or "confirm
   identity" flow programmatically.
3. Capture a `screenshot` action for evidence.
4. Return `TaskResult { success: false, message: "anomaly:<signal>" }`.
5. The Safety Monitor sets the account to `paused` (see
   `docs/agents/safety-monitor.md`) — resuming requires a human to log in
   manually and re-bootstrap the session
   (`skills/session-persistence.md`).

## Maintenance

Facebook changes restriction-notice wording periodically. When a new
wording is observed in the wild (via screenshots saved on `success: false`
results), add it to the text-based signal list above.
