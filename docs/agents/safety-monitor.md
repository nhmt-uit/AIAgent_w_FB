---
agent: Safety Monitor
type: rule-based, optional LLM assist for screenshot classification
reads_before_acting: [skills/anomaly-detection.md, skills/rate-limiting-pacing.md]
---

# Safety Monitor

## Status (2026-09-06/07)

Behavior #1 below (auto-pause on anomaly detection) is real. Behaviors #2
and #3 are not.

Implemented as: `human_bot/actions.py`'s `_check_anomaly_or_raise` raises
`human_bot/safety.py`'s `AnomalyDetected` (a distinct exception type, not
a bare `RuntimeError` as before) whenever `detect_anomaly()` matches;
`human_bot/agent.py`'s `run_task()` catches that specifically and calls
`human_bot/runtime_config.py`'s `set_account_paused(account_id, True)`.
That's a slight mechanism difference from this file's original wording
below ("...in `human_bot/config.py`'s account store"): the pause is
actually persisted as an override in `runtime_config.json`
(`get_paused_account_ids()`), which `human_bot/config.py`'s
`get_all_accounts()` applies on top of every account regardless of
origin — same net effect (the account's `AccountStatus` reads as
`PAUSED` everywhere, including the `account.status != ACTIVE` check at
the top of `run_task()`), but the state lives in the JSON override file,
not a mutation of the in-memory `ACCOUNTS` dict, so it survives a service
restart. Human review/re-enable happens at `/admin/accounts`, which also
allows pausing/resuming manually at any time — not only in response to a
detected anomaly — and the `/admin` dashboard shows a warning banner
naming any currently-paused account so this isn't only discoverable by
visiting that page.

**Not built:** #2 (throttling as usage approaches a configured limit,
before it fails outright) and #3 (alerting a human via n8n/Slack/email
when a pause happens — today, finding out means opening `/admin` and
seeing the banner, or noticing a failed task in `/admin/reports`).

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
