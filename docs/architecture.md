---
title: System Architecture
audience: AI agents + engineers
language: English (technical file — see /README.md for project rules)
---

# System Architecture — human_bot (Facebook Automation)

## 1. Purpose

`human_bot` is the execution layer that performs real actions on Facebook
(post, comment, reply, like) on behalf of a multi-agent system orchestrated
by n8n. It is built on **plain [Playwright](https://playwright.dev/python/)**,
not an LLM-driven agent — every action's exact click-by-click steps are
recorded once by a human operator with Playwright Codegen (see
`docs/skills/facebook-custom-actions.md`), then implemented as deterministic
async functions. There is nothing for an AI to decide once the steps are
known, so running one for every action would only add cost, latency, and a
chance of misclicking.

[browser-use](https://github.com/browser-use/browser-use) (LLM-driven
browser automation) was the original design and is kept as a **reserved
fallback** (`human_bot/llm.py`) for when a recorded selector breaks and no
one has re-recorded it yet — see `docs/skills/vision-fallback.md`. It is
not used in the normal path. See `/docs/research/browser-use.md`
(Vietnamese, descriptive research notes) for the original technology
evaluation that led here.

## 2. Components

| Component | Role | Has browser? | Has independent judgment? |
|---|---|---|---|
| n8n | Orchestration: scheduling, triggers, queueing, retries, logging | No | No (rule-based workflow) |
| Content Strategist Agent | Decides *what* to post/comment and drafts the text | No | Yes (LLM) |
| human_bot Executor Agent | Executes one concrete, pre-decided action | Yes (plain Playwright) | No — intentionally deterministic, no LLM in the normal path |
| Safety Monitor | Watches results/logs for ban/restriction signals, pauses accounts | No | Partial (rule-based + optional LLM on screenshots) |

Full agent specs: `docs/agents/content-strategist.md`,
`docs/agents/human-bot-executor.md`, `docs/agents/safety-monitor.md`.

## 3. Data flow

```
n8n (schedule/trigger)
   │
   ▼
Content Strategist Agent (LLM only)
   │  produces a structured Task JSON:
   │  { action, account_id, target_url, content, media?, reasoning }
   ▼
n8n → HTTP POST /tasks → human_bot FastAPI service (long-running process)
   │
   ▼
human_bot Executor Agent (plain Playwright, no LLM)
   │  reuses the account's ALREADY-OPEN persistent browser (see section 3b)
   │  dispatches directly to the matching function in human_bot/actions.py
   │  (see skills/facebook-custom-actions.md) by action name — no AI
   │  decides which tool to call, agent.py's dispatch table does
   │  applies pacing rules (see skills/rate-limiting-pacing.md)
   │  watches for anomalies (see skills/anomaly-detection.md)
   ▼
TaskResult JSON { success, message, screenshot_path, timestamp }
   │
   ▼
n8n logs result → Safety Monitor inspects → may pause account
```

n8n never talks to a browser or to browser-use directly — it only ever
calls the one HTTP endpoint (`POST /tasks`) on the human_bot service.
Everything about "when to act" (the cron schedule, the trigger condition)
lives in n8n; everything about "how to act on Facebook" lives behind that
one endpoint.

## 3b. Persistent browser (runs 24/7, not launched per task)

`human_bot/service.py` is meant to run continuously (e.g. under systemd,
pm2, or a long-running Docker container) rather than being started fresh
for each task. On startup it pre-launches one already-logged-in Playwright
browser context per active account (see `human_bot/browser_pool.py`) and
keeps each one open for the life of the process. Each incoming
`POST /tasks` call reuses that same browser page instead of paying
browser-launch cost or restarting the account's session on every action.

This is a deliberate choice, not just a performance optimization: a
browser that opens and closes for every single action looks less like a
continuously-present human than one that stays open and simply acts from
time to time — see `docs/skills/rate-limiting-pacing.md`.

Trade-off: unlike an LLM agent's system prompt, there is no "reload" step
needed for a plain function — editing `human_bot/actions.py` takes effect
on the very next call automatically (Python re-imports are not needed
since the process reads the current code, but a running process DOES need
a restart to pick up an edited `.py` file — restart the whole service, or
call an account's `AccountSession.restart_session()` for a fresh browser
without restarting the process, e.g. if a page seems stuck).

## 4. Why the Executor has no independent judgment

The human_bot Executor Agent is deliberately kept "dumb": it receives an
already-decided action and executes it with a standardized, pre-recorded
Playwright function, instead of reasoning freely about Facebook's UI and
content each time. This:
- makes behavior fully deterministic and predictable (same action → exact
  same steps, every time)
- costs nothing per action beyond the browser itself — no LLM call, no API
  key, in the normal path
- eliminates the chance of an agent improvising something that looks
  bot-like (e.g. rewording content live, clicking unexpected UI)

All "thinking" (what to post, when it's relevant, how to phrase it) lives in
the Content Strategist Agent, which never touches the browser.

## 5. Directory layout

```
AIAgent_w_FB/
  README.md                     # Vietnamese — project overview & how to continue
  docs/
    research/                   # Vietnamese — human-facing research notes
    architecture.md             # English — this file
    agents/                     # English — one spec per agent
    skills/                     # English — reusable skill definitions agents reload
  human_bot/                    # Python package — the Executor Agent implementation
    config.py
    actions.py                  # Playwright action functions (the normal path)
    browser_pool.py              # persistent per-account Playwright sessions
    agent.py                     # dispatches Task JSON -> actions.py function
    safety.py
    service.py
    llm.py                       # reserved fallback (browser-use), not used by default
    prompt_loader.py              # reserved for the fallback path (see docs/skills/vision-fallback.md)
  accounts/                     # gitignored — per-account storage_state.json (secrets)
  requirements.txt
  .env.example
```

## 6. Language convention (why docs are split EN/VN)

- `README.md` and anything under `docs/research/` (descriptions, expectations,
  business context): **Vietnamese**, for the human team to read.
- Everything under `docs/agents/`, `docs/skills/`, `docs/architecture.md`,
  and all code/comments: **English**, because these files are the
  "knowledge base" an AI agent re-reads to (re)learn its role and skills —
  English keeps them precise and consistent for LLM consumption.
