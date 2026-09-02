---
skill: Rate Limiting & Human-like Pacing
used_by: [human-bot-executor, safety-monitor]
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: Action-speed limits and human-like pacing rules — read this to tune how fast/slow an account is allowed to act, or after an account gets flagged too often.
> VI: Giới hạn tốc độ hành động và quy tắc giãn cách giống người thật — đọc file này khi cần điều chỉnh tốc độ hành động của một tài khoản, hoặc sau khi tài khoản bị cảnh báo nhiều lần.

# Skill: Rate Limiting & Pacing

## Why

Facebook's Terms prohibit automated behavior that mimics or substitutes for
a real user, and its abuse systems key heavily on *pattern*: constant
speed, 24/7 activity, and perfectly even intervals are the clearest bot
signals — more than any single action. This skill exists to make human_bot's
behavior look paced like a person, not to guarantee undetectability.

## Default limits (per account, configurable in `human_bot/config.py`)

| Action | Default limit |
|---|---|
| Posts | 2–3 per day |
| Comments | 4–6 per hour, max ~20/day |
| Likes | up to 15/hour |
| Concurrent actions on the same account | 1 (never run two actions in parallel on one account) |

These are conservative starting points, not guarantees — tune down further
for new/low-trust accounts and up only gradually for old, established ones.

## Pacing rules

1. Delay between actions is **randomized**, not fixed — draw from a range
   (e.g. 90–400 seconds) rather than sleeping a constant duration.
2. Concentrate activity within plausible waking hours for the account's
   apparent timezone; avoid scheduling dense activity between roughly
   1am–6am local time.
3. Never schedule action batches that repeat at an exact fixed cadence
   (e.g. "every exactly 30 minutes") — jitter the schedule itself, not just
   the action delay.
4. Vary action order/mix where possible (a like, then later a comment)
   rather than always the same action type back-to-back.

## Enforcement point

The human_bot Executor Agent must check the account's rolling usage against
these limits **before** opening the browser for a new task (see
`docs/agents/human-bot-executor.md`, step 2) and refuse the task rather
than queue and wait.

## Relationship to Safety Monitor

The Safety Monitor (see `docs/agents/safety-monitor.md`) treats an account
that is *repeatedly* hitting its limit as a signal to tighten that
account's limits further, independent of whether an actual anomaly has
occurred yet.
