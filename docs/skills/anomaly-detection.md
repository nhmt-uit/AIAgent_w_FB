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
- "certain actions have been restricted"
- "checkpoint" (in URL path, e.g. `facebook.com/checkpoint/`)

**Confirmed live 2026-09-07** (real incident, account `tu_iizuki`, during a
manual Codegen recording session — see README.md's dated incident note for
the full story): Facebook's exact modal read *"Open Facebook on your
mobile device to confirm your identity — Certain actions have been
restricted due to unusual activity."* Already matched by BOTH "confirm
your identity" and "unusual activity" above — this is the first time any
signal in this list has been confirmed against a real screenshot rather
than assumed wording. "certain actions have been restricted" added as a
third, independent match on the same real text, so a future wording
change that drops one of the other two still gets caught.

Structural:
- A captcha iframe/element present on the page.
- The page unexpectedly redirects to a login page for an account with a
  valid `storage_state` (see `skills/session-persistence.md`).

## Required behavior on detection

1. Stop the current task immediately — do not attempt the intended action.
2. Do **not** retry, and do not attempt to solve a captcha or "confirm
   identity" flow programmatically.
3. Capture a `screenshot` action for evidence — **not implemented yet**
   (`TaskResult.screenshot_path` is always `None` today, see README.md's
   TODO list); tracked as a known gap, not a design decision.
4. Return `TaskResult { success: false, message: "anomaly_detected:<signal>" }`
   (`human_bot/safety.py`'s `AnomalyDetected` exception message — implemented).
5. **Implemented (2026-09-06/07):** the account is set to `paused`
   persistently (`human_bot/runtime_config.py`'s `set_account_paused()`,
   applied by `human_bot/config.py`'s `get_all_accounts()` — see
   `docs/agents/safety-monitor.md`'s "Status" section for the exact
   mechanism), along with the detected `reason` and a `paused_at`
   timestamp, shown at `/admin/accounts` right under the account's status
   badge — resuming needs a human to click "Kích hoạt lại" there (only
   re-bootstrapping the session (`skills/session-persistence.md`) is
   needed if the anomaly turned out to be an actual logged-out/invalidated
   session, not every pause).
6. **Implemented (2026-09-07), post-resume cooldown:** clicking "Kích
   hoạt lại" does not restore full-speed activity immediately — it starts
   a reduced-rate-limit cooldown window (`human_bot/safety_cooldown_config.py`'s
   `SafetyCooldownConfig`, editable at `/admin/config` → "🧊 Hạ nhiệt sau
   khi kích hoạt lại tài khoản"; mechanism in
   `human_bot/runtime_config.py`'s `resume_account()` /
   `_expire_resume_cooldown_if_due()`), after which the account's rate
   limits automatically return to whatever was in effect before the
   pause. Added after a real external report (Facebook group post shared
   2026-09-07) of accounts getting re-flagged shortly after resuming
   pre-restriction behavior at full speed — one operator who deliberately
   stayed quiet an extra week past their lifted restriction reported 3
   clean months afterward, versus another who cross-posted once right
   after a restriction lifted and was banned again immediately. The admin
   still decides *when* to click "Kích hoạt lại" — this only changes what
   happens *after* that click, not how soon it's safe to click it. See
   `/admin/accounts`'s "🧊 Đang hạ nhiệt..." badge for an account currently
   in this window.

## Known gap — anomaly re-check only happens right after page navigation

Every `_check_anomaly_or_raise()` call site in `human_bot/actions.py` runs
immediately after a `page.goto(...)`, never again later in the same
function. `post_to_own_profile`, `post_to_group`, and (recorded
2026-09-07/08) `comment_on_group_post` additionally re-check right when
their post-submit verification (`*_button.wait_for(state="hidden", ...)`)
times out, since a checkpoint modal popping up mid-submit can leave the
button attached to the DOM (only visually covered) rather than actually
removing it — that timeout branch would otherwise report a generic
`*_button_still_visible_after_click` failure instead of
`anomaly_detected:<signal>`, and the account would NOT get auto-paused
despite being flagged. The three still-unrecorded actions
(`comment_on_friend_post`, `like_post`, `read_recent_comments`) still
only check once, right after their initial `goto(post_url)` — add the
same post-submit re-check pattern when filling in their real
Codegen-recorded steps.

## Maintenance

Facebook changes restriction-notice wording periodically. When a new
wording is observed in the wild (via screenshots saved on `success: false`
results), add it to the text-based signal list above.
