---
agent: human_bot Executor Agent
type: plain Playwright dispatcher (no LLM in the normal path — see docs/architecture.md)
reads_before_acting:
  - skills/facebook-custom-actions.md
  - skills/session-persistence.md
  - skills/rate-limiting-pacing.md
  - skills/anomaly-detection.md
  - skills/vision-fallback.md
  - skills/human-like-interaction.md
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: Describes what the Executor does and how it dispatches Task JSON to real Facebook actions — read this to understand the request/response contract or when adding a new action type.
> VI: Mô tả Executor làm gì và cách nó thực thi Task JSON thành hành động thật trên Facebook — đọc file này để hiểu hợp đồng request/response, hoặc khi thêm một loại hành động mới.

# human_bot Executor Agent

## Role

Executes exactly one pre-decided Task JSON (produced by the Content
Strategist Agent, see `docs/agents/content-strategist.md`). Does **not**
decide what to post or judge relevance, and — as of the current design —
does **not** use an LLM to figure out *how* to carry out the steps either:
`human_bot/agent.py` dispatches the Task JSON's `action` field directly to
a matching Python function in `human_bot/actions.py`, which runs a fixed,
pre-recorded sequence of Playwright steps. See `docs/architecture.md`
section 1 for why this is deterministic rather than LLM-driven.

## Inputs

A Task JSON (see content-strategist.md for the schema) plus `account_id`.

## Persistent browser (24/7)

This Executor runs behind a long-lived service (`human_bot/service.py`)
that keeps **one already-logged-in Playwright browser context open per
account for the life of the process** (see `human_bot/browser_pool.py`).
Each incoming task reuses that same browser page instead of paying
browser-launch cost and instead of the account's session restarting for
every single action.

Practical effect: run `uvicorn human_bot.service:app` as a long-running
process (systemd/pm2/Docker), and it opens each active account's browser
once at startup and keeps it ready. n8n only ever calls `POST /tasks` — it
does not manage the browser's lifecycle at all.

Because there is no LLM system prompt to reload, a code change to
`human_bot/actions.py` takes effect on the next process restart (a plain
Python file, not a per-run-loaded doc) — see `docs/architecture.md`
section 3b.

## Behavior contract

1. Load the account's persisted session — never log in interactively during
   a normal task run (see `skills/session-persistence.md`).
2. Check the account's rate-limit budget before acting; if exhausted, return
   immediately without opening the browser (see
   `skills/rate-limiting-pacing.md`).
3. Dispatch to the matching function in `human_bot/actions.py` — one
   function per real-world context, not a generic post/comment (see
   `skills/facebook-custom-actions.md` for why):
   - `post_to_own_profile` → `actions.post_to_own_profile()`
   - `post_to_group` → `actions.post_to_group()`
   - `comment_on_friend_post` → `actions.comment_on_friend_post()`
   - `comment_on_group_post` → `actions.comment_on_group_post()`
   - `like_post` → `actions.like_post()`
   (full contracts in `skills/facebook-custom-actions.md`)
4. On every page load, scan for anomaly signals (captcha, checkpoint,
   restriction notice) before proceeding — see `skills/anomaly-detection.md`.
   If detected: stop immediately, do not retry, capture a screenshot, and
   return `success: false` with the anomaly reason. Never attempt to solve
   a captcha.
5. If a recorded Playwright selector can't find its element, this is where
   the reserved LLM fallback in `skills/vision-fallback.md` would be
   invoked — not implemented in the default path yet; today a broken
   selector is a hard failure that needs a human to re-record it with
   Codegen.

## Output contract (TaskResult)

```json
{
  "success": true,
  "message": "string",
  "screenshot_path": "string | null",
  "timestamp": "ISO-8601 string"
}
```

## Explicit non-goals

- Does not draft or rewrite content — content comes verbatim from the Task
  JSON.
- Does not decide whether an action is a good idea — that already happened
  upstream.
- Does not retry indefinitely — a small, bounded retry count only.
- Does not use an LLM to decide what to click — see `docs/architecture.md`.

## Notes for retraining / reloading this agent

There is no prompt to "retrain" in the normal path anymore — behavior
lives in plain Python code. If Facebook's UI changes and actions start
failing, re-record the affected step(s) with Playwright Codegen and update
the matching function in `human_bot/actions.py` directly — see
`skills/facebook-custom-actions.md`, "When Facebook's UI changes".
