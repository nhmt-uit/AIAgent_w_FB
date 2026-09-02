---
agent: Safety Monitor
type: rule-based, optional LLM assist for screenshot classification
reads_before_acting: [skills/anomaly-detection.md, skills/rate-limiting-pacing.md]
---

# Safety Monitor

## Role

Protects Facebook accounts from being restricted or banned by watching the
human_bot Executor's results and logs, and by owning each account's
automation on/off switch. Does not perform actions itself.

## Inputs

- Every `TaskResult` returned by the human_bot Executor Agent.
- The rolling action log per account (timestamps, action types).

## Behavior

1. If a `TaskResult` contains an anomaly signal (see
   `skills/anomaly-detection.md`), immediately set that account's status to
   `paused` in `human_bot/config.py`'s account store and stop dispatching
   new tasks for it until a human operator reviews and re-enables it.
2. If an account's action frequency approaches its configured limit (see
   `skills/rate-limiting-pacing.md`), throttle further and warn — do not
   wait for a hard failure.
3. Surface a human-readable alert (via n8n, e.g. a Slack/email node) whenever
   it pauses an account, including the `reasoning` field from the task that
   triggered it and the screenshot path if available.

## Explicit non-goals

- Never attempts to "fix" a restricted account automatically (no re-login
  attempts, no captcha solving, no retries against a flagged account).
- Not a content moderator — content-level guardrails belong to the Content
  Strategist Agent.

## Notes for retraining / reloading this agent

The keyword/pattern list this agent relies on lives in
`skills/anomaly-detection.md` and should be the first thing updated when
Facebook changes its restriction-notice wording.
