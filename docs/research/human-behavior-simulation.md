# Research Notes: Human Behavior Simulation (Typing, Mouse, Pacing)

Purpose of this file / Muc dich cua file nay:
EN: Research findings and design decisions for making human_bot's browser
interactions look human (Vietnamese typo model, mouse movement, contextual
pacing, config/content delivery). Read this before changing human_bot/humanize.py.
VI: Ghi chu nghien cuu va cac quyet dinh thiet ke de human_bot thao tac
giong con nguoi hon (mo hinh go sai tieng Viet, di chuyen chuot, cac
khoang cho theo ngu canh, giao dien cau hinh/nguon noi dung). Doc file
nay truoc khi sua human_bot/humanize.py.

Date: 2026-09-02

## 1. Vietnamese typo + backspace-retype behavior

Current `human_type()` only simulates typos for ASCII letters via a
QWERTY-neighbor substitution model. This does NOT extend to Vietnamese
diacritics, because:

- Diacritic characters (a with breve/circumflex, d with stroke, tone marks)
  are not produced by a single physical key on a real keyboard — they are
  composed by an input method (Unikey, EVKey, etc.) using Telex or VNI key
  sequences (e.g. Telex "duwowngf" -> "duong" with breve/circumflex/tone
  applied -> "đường").
- Playwright's `page.keyboard.type()` sends fully-composed Unicode
  characters directly (via CDP), it does not go through a real OS-level
  IME. So we cannot simulate "wrong Telex keystrokes" at the IME level —
  only the resulting human behavior (typing a wrong word, noticing,
  correcting) can be modeled realistically.

Two possible approaches, in order of recommended implementation:

1. **Word-level typo + full-word backspace-retype (recommended first).**
   Occasionally, after finishing a Vietnamese word (a run of non-space
   characters), pause briefly, backspace the whole word, retype it
   correctly. Safe (never produces wrong final text), simple, and keystroke
   dynamics research indicates the mere PRESENCE of backspace events with
   uneven timing is what mainly distinguishes human typing from scripted
   input — exact fidelity to a specific typo type matters less.

2. **Telex key-order slip simulation (optional, more work later).**
   Simulate a plausible wrong intermediate syllable by e.g. typing the tone
   mark key out of order relative to Telex modifier keys, then correcting.
   Requires a per-syllable mapping table and carries higher risk of bugs
   corrupting the final text if not carefully validated. Defer until (1) is
   in place and tested.

## 2. Mouse movement + contextual pacing

Sources reviewed: cside.com blog on behavioral bot detection, browser-use.com
bot-detection post, ghost-cursor (Puppeteer/Playwright mouse-movement
library) documentation.

Key findings:
- Bot detection increasingly looks at *behavioral* signals together, not
  just one: mouse path curvature + micro-corrections near target, scroll
  velocity profile (burst-glide-stop vs. flat/step), keystroke interval
  variance + presence of backspace, and (for LLM-driven agents specifically)
  a distinct "AI reasoning latency" pause pattern between actions that
  differs from human read/think pauses. Our pipeline has no LLM in the
  normal path, so this last signal does not apply to us directly, but it
  means our own delays must vary randomly rather than being fixed.
- ghost-cursor's mouse-movement algorithm: generate a Bezier curve between
  start and end point, with a few random control points placed on ONE side
  of the straight line (not both, to avoid unnatural zig-zag); movement
  speed follows Fitts's law (further distance / smaller target => slower,
  more careful movement); "overshoot" for long-distance moves (cursor moves
  slightly past the target then corrects back); final click point is a
  random coordinate WITHIN the target element's bounding box, not always
  its center. No official Python port found — recommend a small custom
  `human_mouse_move()` in `human_bot/humanize.py` implementing the same
  Bezier-interpolation idea with `page.mouse.move()` in several steps
  before `page.mouse.click()`, instead of Playwright's direct click.

Recommended contextual delay table (all configurable, see section 3):

| Step | Suggested delay | Content-length dependent? |
|---|---|---|
| After landing on facebook.com, before any action | 7-10s | No |
| After clicking the composer trigger | 3-5s | No |
| Each step in the audience-picker flow (click -> wait -> click) | 1.5-3s per step | No |
| After finishing typing, before clicking "Đăng" | modeled on ~200-250 wpm silent reading speed + random buffer, clamped to a configurable min/max (default 5-20s) | Yes |
| Mouse move to a target before click | Bezier/Fitts's-law based, typically 0.3-1.2s depending on on-screen distance | Indirectly (screen distance) |

## 3. Config UI + content source (not .env, not CLI args)

Recommendation: extend the already-running 24/7 FastAPI service
(`human_bot/service.py`) with a local-only `/admin` page (bind to
localhost, not exposed publicly — it has real posting power):

- **Config page**: HTML form to edit humanize/rate-limit parameters
  (typing speed, typo probability, all the delay ranges above). Saves to a
  JSON file (e.g. `runtime_config.json`), NOT `.env`. Service reads this
  file at request time, so changes apply without restarting the process.
- **Post-content page**: textarea + account picker + action-type picker,
  calling the same `run_task()` used by the CLI test script — replaces
  typing content directly into a terminal command (which is what caused
  the earlier `dquote>` shell-quoting incident).
- Longer-term, once n8n is wired up for real, content should come FROM n8n
  (pulling from a sheet / the Content Strategist Agent) calling
  `POST /tasks` directly — the admin page's post-content form is for manual
  testing only, not the production content path.

## Sources consulted

- https://cside.com/blog/catching-ai-agents-behavioral-signals
- https://cside.com/blog/catching-playwright-and-browserless-bots-by-the-cursor
- https://browser-use.com/posts/bot-detection
- https://github.com/browser-use/browser-use/issues/947
- https://github.com/bn-l/ghost-cursor-play
- https://www.npmjs.com/package/ghost-cursor-playwright
- https://pypi.org/project/humanization-playwright/
- https://link.springer.com/chapter/10.1007/978-3-031-65175-5_30 (Detecting Web Bots via Keystroke Dynamics)
- https://wraitor.io/learn/keystroke-dynamics
- https://vietionary.net/learn/vietnamese-typing-tutorial
- https://en.wikipedia.org/wiki/Vietnamese_language_and_computers

## Open questions for the user

- Which content-source option for the admin page: simple textarea form
  only, or also a file/folder queue (e.g. drop a .txt file to post)?
- Priority: implement Vietnamese word-level typo model first, or the mouse
  movement humanization first, or the admin UI first? (All three were
  requested; suggest sequencing them.)
