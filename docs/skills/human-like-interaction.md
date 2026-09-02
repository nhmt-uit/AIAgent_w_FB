---
skill: Human-like Typing & Pacing
used_by: [human-bot-executor]
source: |
  https://github.com/Lax3n/HumanTyping
  https://roundproxies.com/blog/human-typing-playwright/
  https://browser-use.com/posts/bot-detection
  https://www.sciencedirect.com/science/article/pii/S2405844021025160
---

> **Purpose of this file / Mục đích của file này:**
>
> EN: Explains why and how human_bot simulates human typing rhythm and typos instead of instantly filling text fields — read this before adding a new action that types content, or when tuning typing speed/behavior via .env.
> VI: Giải thích vì sao và cách human_bot mô phỏng nhịp gõ phím và lỗi gõ giống người thay vì điền chữ tức thì — đọc file này trước khi thêm một hành động mới có gõ nội dung, hoặc khi chỉnh tốc độ/hành vi gõ qua .env.

# Skill: Human-like Typing & Pacing

## Why this matters

Bot-detection research and browser-use's own writeup on the topic both
name **typing cadence** explicitly, alongside mouse movement and scroll
patterns, as a behavioral signal detection systems check
(browser-use.com/posts/bot-detection: "Mouse movements, scroll patterns,
typing cadence"). `page.fill()` / `.fill()` sets a field's value instantly
with zero keystrokes sent — about as inhuman a signal as exists. Every
action that types content into Facebook must go through
`human_bot/humanize.py`'s `human_type()` instead.

## What real human typing actually looks like (research summary)

- Typing speed is conventionally measured in **WPM (words per minute)**,
  using 5 characters = 1 "word" as the standard conversion. An average
  adult types roughly 40 WPM; a fast typist 60-80 WPM; professional
  touch-typists can exceed 100 WPM. **This is much slower than it sounds
  in characters/second** — 40 WPM ≈ 3.3 chars/sec, 80 WPM ≈ 6.7 chars/sec.
  A naive "60 characters per second" target would be ~720 WPM, physically
  impossible for a human — a mistake worth flagging if it ever comes up
  again when tuning this.
- Inter-keystroke timing is **not constant** even for the same person
  typing the same text twice — published keystroke-dynamics research
  (e.g. the ScienceDirect paper above on free-text keystroke timing
  distributions) models per-keystroke latency as noisy around a mean, not
  fixed. `human_bot/humanize.py` samples each character's delay from a
  Gaussian distribution around a mean derived from the configured WPM,
  which is what makes consecutive keystrokes feel uneven instead of a
  metronome — this directly answers "can we control the pause between
  each character, since it differs per character for a real person": yes,
  every character gets its own independently sampled delay.
- People pause **longer between words than between letters within a
  word**, and longer still after sentence-ending punctuation (thinking
  about the next clause/sentence). `human_type()` adds extra randomized
  delay after spaces and after `.,!?;:`.
- People **mistype and self-correct** — an adjacent-key slip is the most
  common error type (e.g. typing "d" instead of "s"), usually noticed
  within a few hundred milliseconds and fixed with Backspace before
  continuing. `human_type()` simulates this at a configurable probability
  per ASCII letter: type a plausible wrong (QWERTY-adjacent) letter, pause
  (simulating the moment of noticing), Backspace, then type the correct
  letter and continue.
- Real typing also slows down gradually over a long stretch (fatigue) —
  approximated here as a very small per-character delay increase.

## What this does NOT do (be honest about the limits)

- No Vietnamese-specific typo model. Typo injection only applies to plain
  ASCII letters — Vietnamese diacritic characters (ăâêôơư and tone marks)
  are typed without simulated typos, because they aren't produced by a
  single physical keypress the way a QWERTY-neighbor-substitution model
  assumes (they come from an input method like Telex/VNI or direct
  Unicode input) — simulating a "typo" there risked producing invalid or
  garbled text instead of a plausible human mistake.
- No mouse-movement or click-timing simulation beyond the small
  `human_pause()` calls between UI steps (open composer → set privacy →
  type → submit) — see `human_bot/actions.py` for where these are placed.
- This is a best-effort behavioral approximation, not a guarantee against
  detection — see `docs/skills/rate-limiting-pacing.md` for the
  complementary macro-level pacing (how often an account acts at all),
  which matters at least as much as micro-level typing rhythm.

## Configuration (all in `.env`, all optional — sensible defaults apply)

| Variable | Default | Meaning |
|---|---|---|
| `HUMAN_TYPING_ENABLED` | `true` | Set `false` to fall back to instant text insertion (e.g. for fast local testing) |
| `HUMAN_TYPING_WPM` | `40` | Base typing speed — see the WPM note above; do not set this as a chars/sec value |
| `HUMAN_TYPING_STDEV_RATIO` | `0.35` | How much each keystroke's delay varies from the mean (as a fraction of the mean) |
| `HUMAN_TYPING_MIN_DELAY_MS` | `25` | Floor on any single keystroke delay |
| `HUMAN_TYPING_WORD_PAUSE_MIN_MS` / `_MAX_MS` | `150` / `450` | Extra pause range after a space |
| `HUMAN_TYPING_PUNCT_PAUSE_MIN_MS` / `_MAX_MS` | `250` / `700` | Extra pause range after `.,!?;:` |
| `HUMAN_TYPING_TYPO_PROB` | `0.03` | Probability of a simulated typo per ASCII letter (3%) |
| `HUMAN_TYPING_TYPO_NOTICE_MIN_MS` / `_MAX_MS` | `150` / `450` | How long "noticing" a typo takes before Backspace |
| `HUMAN_TYPING_FATIGUE_PER_CHAR` | `0.0005` | Per-character delay growth over a long post (mild fatigue) |

See `human_bot/humanize.py`'s `HumanTypingConfig` dataclass — this table
and that class must be kept in sync.

## Where it's used

`human_bot/actions.py`'s `post_to_own_profile` calls `human_type()` for
the post body and `human_pause()` between the composer/privacy/submit
steps. Every new action added later that types content (comments, group
posts) must do the same — see `docs/skills/facebook-custom-actions.md`.
