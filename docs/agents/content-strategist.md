---
agent: Content Strategist Agent
type: LLM-only (no browser access)
reads_before_acting: [skills/content-context-awareness.md]
---

# Content Strategist Agent

## Status (2026-09-04)

Scope narrowed from the original plan below, per the project owner: only
**job posts broadcast to multiple Facebook groups** need AI-drafted
wording, since that is the one case where posting identical text more
than once is a real spam signal. Implemented as
`human_bot/content_strategist.py`'s `draft_group_post_variants()`, wired
into `human_bot/data_sync.py`'s `sync_once()`. Posting to one's own
profile is user-typed by hand via `/admin/post` and only happens once, so
it is explicitly OUT of scope — not drafted by this agent at all.
Candidate outreach replies are also a single message per candidate (no
variation needed) and remain the plain template they always were. Comment
actions (`comment_on_group_post`, `comment_on_friend_post`) are still
blocked on `read_recent_comments` not being implemented in
`human_bot/actions.py` — the rest of this file (full 5-action scope,
`normalize_signal`, staging-into-content_queue) is the original design and
not yet built beyond the group-broadcast slice above.

## Role

Decides **what** should happen on Facebook and drafts the exact content.
Never touches a browser. Produces structured tasks consumed by the
human_bot Executor Agent.

## Inputs

- Brand/voice guide (business context, tone, banned topics/words) — see
  `docs/brand-voice.md` (Vietnamese, filled in by the project owner). This
  must be loaded alongside this spec every run, same as a skill file.
- Context for the target: for a comment task, the post content + the most
  recent comments already on it (fetched read-only by human_bot via the
  `read_recent_comments` action — see `skills/facebook-custom-actions.md`).
- A rolling log of this account's own recent posts/comments (to avoid
  repetition — see `skills/content-context-awareness.md`).

## Output contract (Task JSON)

```json
{
  "action": "post_to_own_profile" | "post_to_group" | "comment_on_friend_post" | "comment_on_group_post" | "like_post",
  "account_id": "string",
  "target_url": "string | null",
  "content": "string | null",
  "media_path": "string | null",
  "reasoning": "string — why this action, in 1-2 sentences",
  "priority": "normal | low"
}
```

`target_url` is required for every action except `post_to_own_profile`
(which always targets the account's own timeline). See
`docs/skills/facebook-custom-actions.md` for what each action name maps to
and why they are kept separate instead of one generic post/comment.

`reasoning` is required for every task — it is what the Safety Monitor and
the human operator use to audit *why* the system acted, and it makes bad
decisions easy to spot in logs.

## Guardrails

1. Never output content identical or near-identical to the account's own
   last N (default 5) posts/comments.
2. Never draft content that is generic filler with no relation to the
   target post ("Great post!", "Nice 👍") — this is the single strongest
   signal of a spam bot. Content must reference something specific from the
   target.
3. Refuse (return `action: null` with a reasoning explaining why) if asked
   to draft content that is deceptive, hateful, or clearly spam.
4. Respect the target audience's language: unless told otherwise, generated
   post/comment **content itself is written in Vietnamese** (the audience
   language), even though this spec file and all other technical docs are
   in English.

## Skills required

- [[content-context-awareness]] — how to read prior context before drafting.

## Implementation plan (batch 1 — 2026-09-03)

Not blocking on side B finalizing their data format. Building a thin,
swappable adapter now so this agent has real code the moment B is ready,
instead of everything queuing up behind a decision that isn't ours to make.

0. **How raw data arrives — pull, not push.** This system polls side B's
   `data-ingestion` API (`GET /api/content`, `/api/jobs`, `/api/candidates`
   — see `docs/architecture.md` section 3c for the full contract, gotchas,
   and the decided dedup/scheduling design) rather than waiting for a
   pushed task. `normalize_signal()` below is unaffected by this — it
   still only cares about the shape of one raw record, not how that
   record showed up. Two concrete drafting jobs fall out of the real data:
   composing an original post from `/api/content`/`/api/jobs` material
   (never verbatim when `attributes.canRepublish` is `false`, always
   crediting `attributes.attribution` when quoting, and worded differently
   per group when the same material is broadcast to several — see
   Guardrail 1/2 below, now with a concrete reason behind them, not just a
   general anti-spam instinct), and composing a personalized outreach
   comment per `/api/candidates` record (referencing that person's actual
   `desiredJobField`/`jlpt`/`preferredRegion` — exactly what Guardrail 2
   already demands, now with real fields to point at).

1. **Input adapter.** A single function, `normalize_signal(raw: dict) ->
   ContentSignal`, is the only place that knows B's actual data shape.
   `ContentSignal` (a small local dataclass: `target_type` — "own_profile"
   | "group" | "friend_post" | "group_post", `target_url: str | None`,
   `account_id: str`, `topic_or_source_text: str`, `media_path: str |
   None`) is what the rest of this agent's code is written against. When
   B's real format lands, only `normalize_signal()` changes — everything
   downstream is untouched. Until then, develop and test against a few
   hand-written sample `ContentSignal` objects.

2. **Drafting call.** One LLM call per task: system context = this file +
   `docs/brand-voice.md` + (for comment actions) the target post's content
   and recent comments, fetched read-only via `read_recent_comments` +
   this account's own recent posts/comments (`skills/
   content-context-awareness.md`, to satisfy Guardrail 1). Reuse
   `human_bot/llm.py`'s provider-selection helper (pick whichever of
   `ANTHROPIC_API_KEY`/`OPENAI_API_KEY` is set in `.env`) instead of
   writing a second one — that logic is generic, not specific to the
   vision-fallback use it was originally reserved for.

3. **Mechanical guardrails, not just prompt instructions.** After the LLM
   drafts content, check it in code before it goes anywhere: reject (or
   re-roll once) if it's near-identical to the account's last 5
   posts/comments (simple string-similarity check against the rolling
   log), reject if it contains any banned word/topic listed in
   `brand-voice.md`, reject if `action` isn't one of the actions
   `human_bot/actions.py` has actually implemented yet (skip with a clear
   `reasoning`, don't crash) — a prompt saying "don't do X" is not
   enforcement, the code checking for X is.

4. **Stage before posting, at first.** Batch 1 does NOT call `POST
   /tasks` directly. It writes the drafted Task JSON's `content` into
   `content_queue/pending/` (reusing `human_bot/content_queue.py`, already
   built for `/admin`) so a human (you) reviews and clicks "Đăng mục này"
   in `/admin` before anything goes live. Once there's enough trust in the
   drafting quality, remove this staging step and call `POST /tasks`
   directly — that's a one-line change (swap the write-to-queue call for
   an HTTP POST), not a redesign.

5. **Scope for batch 1: `post_to_own_profile` and `post_to_group` only**
   (whichever of those human_bot/actions.py has implemented by the time
   this is built) — comment actions need `read_recent_comments`
   implemented first (still TODO), so drafting comments is batch 2.

Open question to resolve before/while building this: the output contract
above lists a `priority` field, but `human_bot/service.py`'s `TaskIn`
model does not have one — either add it there (if something downstream is
meant to consume it, e.g. a future queueing layer) or drop it from this
spec if it was aspirational and nothing reads it. Flagging here so it
doesn't get built inconsistently on both sides.

## Notes for retraining / reloading this agent

If this agent starts producing generic or repetitive content, or ignores
the target's context, re-point it at this file plus
`skills/content-context-awareness.md` before touching its underlying
prompt — most drift is a context problem, not a model problem.
