---
skill: Human-like Typing, Pacing & Mouse Movement
used_by: [human-bot-executor]
source: |
  https://github.com/Lax3n/HumanTyping
  https://roundproxies.com/blog/human-typing-playwright/
  https://browser-use.com/posts/bot-detection
  https://www.sciencedirect.com/science/article/pii/S2405844021025160
  https://cside.com/blog/catching-ai-agents-behavioral-signals
  https://cside.com/blog/catching-playwright-and-browserless-bots-by-the-cursor
  https://github.com/bn-l/ghost-cursor-play
  https://link.springer.com/chapter/10.1007/978-3-031-65175-5_30
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: Explains why and how human_bot simulates human typing rhythm/typos, contextual UI pauses, and mouse movement instead of instant field-fills and straight-line clicks — read this before adding a new action, or when tuning behavior via .env or the /admin UI.
> VI: Giải thích vì sao và cách human_bot mô phỏng nhịp gõ phím/lỗi gõ, các khoảng chờ theo ngữ cảnh, và di chuyển chuột thay vì điền chữ tức thì và click theo đường thẳng — đọc file này trước khi thêm một hành động mới, hoặc khi chỉnh hành vi qua .env hoặc giao diện /admin.

# Skill: Human-like Typing, Pacing & Mouse Movement

## Why this matters

Bot-detection research and browser-use's own writeup on the topic name
**typing cadence, mouse movement, and scroll patterns** together as
behavioral signals detection systems check
(browser-use.com/posts/bot-detection: "Mouse movements, scroll patterns,
typing cadence"). cside's writeups go further: real mouse paths show
"curved paths, micro-corrections near a target, physiological tremor"
while automation shows "straight lines... identical velocity, same
origin", and keystroke timing shows "uneven intervals... backspaces and
corrections" versus scripted input's "near-zero variance... or an instant
paste". `page.fill()` and a straight `Locator.click()` are both about as
inhuman a signal as exists. Every action that types content must go
through `human_bot/humanize.py`'s `human_type()`, and every click on a
meaningful control should go through `human_click()`.

## Typing: rhythm and typos

- Typing speed is conventionally measured in **WPM (words per minute)**,
  using 5 characters = 1 "word" as the standard conversion. An average
  adult types roughly 40 WPM; a fast typist 60-80 WPM. **This is much
  slower than it sounds in characters/second** — 40 WPM ≈ 3.3 chars/sec.
  A naive "60 characters per second" target would be ~720 WPM, physically
  impossible — a mistake worth flagging if it ever comes up again.
- Inter-keystroke timing is **not constant** even for the same person
  typing the same text twice — published keystroke-dynamics research
  models per-keystroke latency as noisy around a mean. `human_type()`
  samples each character's delay from a Gaussian distribution around a
  mean derived from the configured WPM.
- People pause **longer between words than between letters within a
  word**, and longer still after sentence-ending punctuation.
- People **mistype and self-correct**. Two separate mechanisms cover this:
  - **ASCII per-character typos** (`typo_probability`): a QWERTY-adjacent
    letter substitution (e.g. "d" instead of "s"), noticed after a short
    delay, then Backspace + retype.
  - **Word-level typos for Vietnamese diacritic words** (`word_typo_probability`,
    added 2026-09-02): a word containing at least one non-ASCII character
    is occasionally typed correctly, "noticed" as wrong, backspaced as a
    *whole word*, and retyped — never a per-character substitution. This
    exists because Vietnamese diacritics aren't produced by a single
    physical keypress (they come from an input method — Unikey/EVKey,
    Telex/VNI — composing several keystrokes into one character), so a
    QWERTY-neighbor substitution on the already-composed character
    wouldn't reflect how a real typo happens there, and risked producing
    garbled-looking text. Word-level backspace-retype always ends on the
    correct word, so it can only add a human-looking hesitation, never
    corrupt the post. See `docs/research/human-behavior-simulation.md`
    for the more elaborate Telex-key-order-slip approach that was
    considered and deferred.
- Real typing also slows down gradually over a long stretch (fatigue) —
  approximated as a very small per-character delay increase.

## Contextual pacing (not just typing)

Beyond typing itself, specific points in a UI flow get their own
independently-configurable pause, via `HumanPacingConfig` and its
`pause_after_page_load()` / `pause_after_composer_open()` /
`pause_between_ui_steps()` / `reading_pause()` functions:

- After landing on a page, before touching anything (default 7-10s).
- After opening a composer/dialog, before interacting with it (3-5s).
- Between each click in a multi-step picker flow, e.g. the audience/
  privacy selector (1.5-3s per step).
- After finishing typing, before submitting — `reading_pause()` estimates
  a "reading it back" delay from the content's word count and a
  configured silent-reading WPM (default 220), plus a random buffer,
  clamped to a min/max — so a one-line status and a long paragraph don't
  get the same review time, unlike a flat random range.

## Mouse movement

`human_mouse_move()` / `human_click()` move the mouse along a slightly
curved path — a quadratic Bézier curve with one random control point
offset to a single side of the straight line (never zig-zagging both
ways), step count and per-step delay scaled to distance (a rough Fitts's
law approximation: farther/smaller target ⇒ more, slower steps), and an
occasional overshoot-then-correct for longer moves — instead of jumping
straight to a target and clicking. This is a simplified Python
reimplementation of the approach used by the `ghost-cursor` library
(Puppeteer/Playwright-JS; no official Python port exists). `human_click()`
also picks a random point *within* the target's bounding box rather than
always the exact center, waits for visibility, and scrolls the element
into view first (replacing the safety checks a bypassed `Locator.click()`
would normally have done).

## What this does NOT do (be honest about the limits)

- No Telex-key-order-slip typo model for Vietnamese (see above) — only
  whole-word backspace-retype, which is simpler and can't corrupt text,
  but is less textured than a real mid-word Telex mistake would be.
- Mouse movement is a geometric approximation (one Bézier curve), not a
  biomechanical model — it does not simulate tremor, acceleration curves
  from real pointing-device studies, or a live occlusion/interception
  check beyond what `human_click()`'s pre-move waits provide.
- This is a best-effort behavioral approximation, not a guarantee against
  detection — see `docs/skills/rate-limiting-pacing.md` for the
  complementary macro-level pacing (how often an account acts at all),
  which matters at least as much as micro-level rhythm.

## Configuration

All three config dataclasses live in `human_bot/humanize.py`, are
overridable via `.env`, and can also be edited live (no restart needed)
from the `/admin` web UI (`human_bot/admin.py`), which layers
`runtime_config.json` overrides on top via `human_bot/runtime_config.py`.
Keep this table, the dataclasses, and `runtime_config.py`'s
`EDITABLE_*_FIELDS` lists in sync when adding a field.

### Typing (`HumanTypingConfig`)

| Variable | Default | Meaning |
|---|---|---|
| `HUMAN_TYPING_ENABLED` | `true` | Set `false` to fall back to instant text insertion |
| `HUMAN_TYPING_WPM` | `40` | Base typing speed — see the WPM note above; not a chars/sec value |
| `HUMAN_TYPING_STDEV_RATIO` | `0.35` | How much each keystroke's delay varies from the mean |
| `HUMAN_TYPING_MIN_DELAY_MS` | `25` | Floor on any single keystroke delay |
| `HUMAN_TYPING_WORD_PAUSE_MIN_MS` / `_MAX_MS` | `150` / `450` | Extra pause range after a space |
| `HUMAN_TYPING_PUNCT_PAUSE_MIN_MS` / `_MAX_MS` | `250` / `700` | Extra pause range after `.,!?;:` |
| `HUMAN_TYPING_TYPO_PROB` | `0.03` | Probability of an ASCII per-character typo (3%) |
| `HUMAN_TYPING_TYPO_NOTICE_MIN_MS` / `_MAX_MS` | `150` / `450` | How long "noticing" a typo takes before Backspace |
| `HUMAN_TYPING_WORD_TYPO_PROB` | `0.04` | Probability of a whole-word backspace-retype for a word with Vietnamese diacritics (4%) |
| `HUMAN_TYPING_FATIGUE_PER_CHAR` | `0.0005` | Per-character delay growth over a long post |

### Pacing (`HumanPacingConfig`)

| Variable | Default | Meaning |
|---|---|---|
| `HUMAN_PACE_ENABLED` | `true` | Set `false` to skip all contextual pauses below |
| `HUMAN_PACE_PAGE_LOAD_MIN_MS` / `_MAX_MS` | `7000` / `10000` | Pause after landing on a page |
| `HUMAN_PACE_COMPOSER_OPEN_MIN_MS` / `_MAX_MS` | `3000` / `5000` | Pause after opening a composer/dialog |
| `HUMAN_PACE_UI_STEP_MIN_MS` / `_MAX_MS` | `1500` / `3000` | Pause between steps in a multi-click picker flow |
| `HUMAN_PACE_READING_WPM` | `220` | Silent reading speed used to estimate the "read it back" pause |
| `HUMAN_PACE_READING_MIN_MS` / `_MAX_MS` | `5000` / `20000` | Clamp range for the reading-back pause |
| `HUMAN_PACE_READING_BUFFER_MIN_MS` / `_MAX_MS` | `500` / `2000` | Random buffer added on top of the estimated reading time |

### Mouse movement (`HumanMouseConfig`)

| Variable | Default | Meaning |
|---|---|---|
| `HUMAN_MOUSE_ENABLED` | `true` | Set `false` to fall back to an instant straight-line move |
| `HUMAN_MOUSE_MIN_STEPS` / `_MAX_STEPS` | `8` / `20` | Intermediate move steps, scaled by distance within this range |
| `HUMAN_MOUSE_STEP_DELAY_MIN_MS` / `_MAX_MS` | `8` / `20` | Delay between each intermediate move step |
| `HUMAN_MOUSE_CURVE_OFFSET_RATIO` | `0.18` | Perpendicular control-point offset, as a fraction of the move distance |
| `HUMAN_MOUSE_OVERSHOOT_PROB` | `0.15` | Probability of overshooting the target then correcting back |
| `HUMAN_MOUSE_OVERSHOOT_RATIO` | `0.08` | How far past the target an overshoot goes, as a fraction of distance |
| `HUMAN_MOUSE_MIN_DISTANCE_PX` | `12` | Below this distance, just snap directly — no point animating a curve |

## Where it's used

`human_bot/actions.py`'s `post_to_own_profile` calls `pause_after_page_load()`
right after `page.goto()`, `human_click()` for every button/locator click,
`pause_after_composer_open()` / `pause_between_ui_steps()` between the
composer/privacy-picker steps, `human_type()` for the post body, and
`reading_pause()` right before clicking "Đăng". Every new action added
later that types content or clicks through a multi-step flow (comments,
group posts) must do the same — see
`docs/skills/facebook-custom-actions.md`.
