"""
Human-like typing, pacing, and mouse-movement simulation for Playwright
actions.

Purpose: bot-detection systems (including Facebook's) look at behavioral
signals beyond raw activity volume — mouse movement, scroll patterns, and
TYPING CADENCE specifically are called out as signals modern systems check
(see docs/skills/human-like-interaction.md and
docs/research/human-behavior-simulation.md for citations). Every action
that types text should go through human_type() here instead of
page.fill()/locator.fill(), and every click on a meaningful UI control
should go through human_click() instead of Locator.click() directly.

All tunables are centralized in three config dataclasses below
(HumanTypingConfig, HumanPacingConfig, HumanMouseConfig) and overridable
via environment variables in .env, so behavior can be adjusted without
touching code — see docs/skills/human-like-interaction.md for what each
setting means, research-backed default ranges, and further reading. The
/admin web UI (human_bot/admin.py) can also override these at runtime via
human_bot/runtime_config.py, without touching .env at all.

Honesty about limits: this is a best-effort approximation of human
behavior, not a guarantee against detection.

GIỚI HẠN KHÔNG VÁ ĐƯỢC Ở TẦNG CODE NÀY (ghi lại 2026-09-08, sau khi so sánh
với một hệ thống automation iOS/Safari khác dùng JS injection —
`Runtime.evaluate` + tự dựng `new PointerEvent()/new KeyboardEvent()` rồi
`dispatchEvent()`): mọi hàm trong file này (`human_click`, `human_type`,
`human_scroll_to`) đều gọi `page.mouse.*`/`page.keyboard.*` của Playwright
— tức là lệnh CDP cấp thấp (`Input.dispatchMouseEvent`,
`Input.dispatchKeyEvent`), đi thẳng vào pipeline input THẬT của Chromium,
KHÔNG PHẢI tự dựng sự kiện DOM bằng JS. Vì vậy, khác với hệ thống
JS-injection nói trên (nơi mọi sự kiện tự dựng luôn có
`event.isTrusted === false`, không có cách nào sửa được ở tầng JS), các sự
kiện ở đây thực sự có `isTrusted: true` — Chromium tự sinh toàn bộ chuỗi
pointerdown/mousedown/pointerup/mouseup/click một cách tự nhiên từ chính
input đã nhận, không phải do mình tự ráp từng sự kiện một.

Tuy vậy, vẫn có những giới hạn KHÔNG vá được ở tầng module này, vì chúng
nằm sâu hơn — trong chính CDP hoặc trong việc Playwright/Puppeteer/
Selenium đều phải dùng CDP:
  1. `movementX`/`movementY` của mọi pointer event luôn = 0 khi dispatch
     qua CDP, dù toạ độ thực sự đổi — chuột thật luôn báo giá trị khác 0.
  2. CDP chỉ gửi 1 mẫu toạ độ cho mỗi lần gọi `mouse.move()`, trong khi
     chuột thật gửi nhiều mẫu dồn dập (coalesced events) ở tần số quét cao
     hơn nhiều — không thể giả lập bằng cách gọi `mouse.move()` nhiều lần
     hơn, vì đó vẫn là các sự kiện rời rạc, không phải luồng liên tục thật.
  3. Bản thân việc trình duyệt bị điều khiển qua CDP domain "Runtime" (lệnh
     `Runtime.enable` mà Playwright/Puppeteer/Selenium đều cần dùng để chạy
     JS trong trang) là một bề mặt bị dò riêng (Cloudflare/DataDome...) —
     KHÔNG liên quan gì tới việc mình dùng domain "Input" (mouse/keyboard)
     đúng cách ở đây; đây là giới hạn của chính việc dùng Playwright, không
     phải lỗi trong file này. Có bản vá cộng đồng (rebrowser-patches) cho
     việc này nhưng phải vá thẳng vào lõi Playwright — chưa áp dụng, xem
     README.md mục "Điểm yếu đã ghi nhận".
Nói ngắn gọn: code ở đây đã ở phía "khó bị phát hiện hơn" trên đúng trục mà
nhiều hệ thống automation khác (không dùng Chromium+CDP) buộc phải chấp
nhận thua — nhưng vẫn có trần giới hạn riêng của CDP mà không có cách nào
vượt qua nếu không đổi hẳn sang điều khiển chuột/bàn phím THẬT ở tầng hệ
điều hành (ngoài phạm vi Playwright — xem thảo luận trong README).

Vietnamese typo handling (word-level, not per-character): a word
containing at least one non-ASCII character (i.e. a Vietnamese diacritic)
is never given a per-character QWERTY-neighbor typo, because those
characters are not produced by a single physical key on a real keyboard —
they are composed by an input method (Unikey/EVKey, Telex/VNI), and a
naive substitution on the already-composed character would not reflect
how a real typo happens there, risking corrupted-looking text. Instead,
such a word can occasionally be typed correctly, "noticed" as wrong,
backspaced as a whole word, and retyped — a word-level correction that
never produces incorrect final text. See
docs/research/human-behavior-simulation.md for the two approaches
considered and why this one was implemented first.
"""
import asyncio
import os
import random
import re
from dataclasses import dataclass, field

from playwright.async_api import Page


def _env_float(name: str, default: float) -> float:
    val = os.environ.get(name)
    return float(val) if val not in (None, "") else default


def _env_bool(name: str, default: bool) -> bool:
    val = os.environ.get(name)
    if val in (None, ""):
        return default
    return val.strip().lower() not in ("false", "0", "no")


# =============================================================================
# Typing
# =============================================================================

@dataclass
class HumanTypingConfig:
    """
    Every field is overridable via .env (see docs/skills/human-like-interaction.md
    for the full table). Defaults aim for an average, unremarkable typist —
    not the fastest or slowest plausible human — since consistently
    superhuman OR suspiciously uniform speed are both signals worth
    avoiding.
    """
    enabled: bool = field(default_factory=lambda: _env_bool("HUMAN_TYPING_ENABLED", True))

    # Words-per-minute, using the standard 5-characters-per-word convention
    # (so this is comparable to typing-test WPM figures). ~40 WPM is an
    # average adult typist; ~60-80 WPM is a fast one. Do NOT set this to a
    # "characters per second" value directly — see module docstring.
    wpm: float = field(default_factory=lambda: _env_float("HUMAN_TYPING_WPM", 40.0))

    # How much each keystroke's delay varies from the mean, as a fraction
    # of the mean (0.35 means a typical keystroke's delay is mean ± 35%).
    # This is what makes consecutive keystrokes feel uneven rather than a
    # metronome — every character gets its own randomly sampled delay.
    char_delay_stdev_ratio: float = field(default_factory=lambda: _env_float("HUMAN_TYPING_STDEV_RATIO", 0.35))
    min_char_delay_ms: float = field(default_factory=lambda: _env_float("HUMAN_TYPING_MIN_DELAY_MS", 25.0))

    # Extra pause added after a space (word boundary) and after sentence
    # punctuation, on top of the normal per-character delay — people pause
    # between words/thoughts more than between letters within a word.
    word_pause_min_ms: float = field(default_factory=lambda: _env_float("HUMAN_TYPING_WORD_PAUSE_MIN_MS", 150.0))
    word_pause_max_ms: float = field(default_factory=lambda: _env_float("HUMAN_TYPING_WORD_PAUSE_MAX_MS", 450.0))
    punctuation_pause_min_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_TYPING_PUNCT_PAUSE_MIN_MS", 250.0)
    )
    punctuation_pause_max_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_TYPING_PUNCT_PAUSE_MAX_MS", 700.0)
    )

    # Per-character typo simulation — ASCII letters only (QWERTY-neighbor
    # substitution). See HUMAN_TYPING_WORD_TYPO_PROB below for the separate,
    # word-level mechanism that covers Vietnamese diacritic words.
    typo_probability: float = field(default_factory=lambda: _env_float("HUMAN_TYPING_TYPO_PROB", 0.03))
    typo_notice_delay_min_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_TYPING_TYPO_NOTICE_MIN_MS", 150.0)
    )
    typo_notice_delay_max_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_TYPING_TYPO_NOTICE_MAX_MS", 450.0)
    )

    # Word-level "typed it, noticed a mistake, backspaced the whole word,
    # retyped it" correction — applied only to words containing at least
    # one non-ASCII character (Vietnamese diacritics). See module
    # docstring for why this is word-level rather than per-character.
    word_typo_probability: float = field(
        default_factory=lambda: _env_float("HUMAN_TYPING_WORD_TYPO_PROB", 0.04)
    )

    # Very mild slowdown as typing continues, approximating fatigue over a
    # long post (0.0005 = +0.05% delay per character already typed).
    fatigue_factor_per_char: float = field(default_factory=lambda: _env_float("HUMAN_TYPING_FATIGUE_PER_CHAR", 0.0005))

    @property
    def mean_char_delay_ms(self) -> float:
        chars_per_minute = self.wpm * 5  # standard "word" = 5 characters
        return 60000.0 / chars_per_minute


# QWERTY physical-neighbor map, used only to pick a plausible mistyped
# ASCII letter — not a general keyboard-layout model.
_QWERTY_NEIGHBORS = {
    "q": "wa", "w": "qes", "e": "wrd", "r": "etf", "t": "ryg", "y": "tuh", "u": "yij",
    "i": "uok", "o": "ipl", "p": "ol",
    "a": "qsz", "s": "awedx", "d": "serfcx", "f": "drtgv", "g": "ftyhb", "h": "gyujn",
    "j": "huikm", "k": "jiol", "l": "kop",
    "z": "asx", "x": "zsdc", "c": "xdfv", "v": "cfgb", "b": "vghn", "n": "bhjm", "m": "njk",
}


def _sample_char_delay_ms(config: HumanTypingConfig) -> float:
    mean = config.mean_char_delay_ms
    stdev = mean * config.char_delay_stdev_ratio
    return max(random.gauss(mean, stdev), config.min_char_delay_ms)


def _pick_typo_char(correct_char: str) -> str | None:
    neighbors = _QWERTY_NEIGHBORS.get(correct_char.lower())
    if not neighbors:
        return None
    typo = random.choice(neighbors)
    return typo.upper() if correct_char.isupper() else typo


async def _type_one_char(page: Page, char: str, cfg: HumanTypingConfig, chars_typed: int) -> int:
    """
    Types a single character with human-like pacing: possible ASCII
    per-char typo+correction, a randomly sampled delay, extra word/
    punctuation pause, and mild fatigue. Shared by human_type()'s
    word-by-word loop and its whitespace-handling loop so both use
    identical timing logic. Returns the updated `chars_typed` counter
    (fatigue accumulates across the whole call, retypes included).
    """
    if char.isascii() and char.isalpha() and random.random() < cfg.typo_probability:
        typo_char = _pick_typo_char(char)
        if typo_char:
            await page.keyboard.type(typo_char)
            await page.wait_for_timeout(
                random.uniform(cfg.typo_notice_delay_min_ms, cfg.typo_notice_delay_max_ms)
            )
            await page.keyboard.press("Backspace")
            await page.wait_for_timeout(_sample_char_delay_ms(cfg))

    await page.keyboard.type(char)
    chars_typed += 1

    fatigue_multiplier = 1.0 + (chars_typed * cfg.fatigue_factor_per_char)
    delay_ms = _sample_char_delay_ms(cfg) * fatigue_multiplier

    if char.isspace():
        delay_ms += random.uniform(cfg.word_pause_min_ms, cfg.word_pause_max_ms)
    elif char in ".,!?;:":
        delay_ms += random.uniform(cfg.punctuation_pause_min_ms, cfg.punctuation_pause_max_ms)

    await page.wait_for_timeout(delay_ms)
    return chars_typed


async def _type_word(page: Page, word: str, cfg: HumanTypingConfig, chars_typed: int) -> int:
    for char in word:
        chars_typed = await _type_one_char(page, char, cfg, chars_typed)
    return chars_typed


async def human_type(page: Page, text: str, config: HumanTypingConfig | None = None) -> None:
    """
    Types `text` into whatever element on `page` currently has keyboard
    focus, word by word, with human-like timing, occasional ASCII
    per-character typos, and occasional whole-word backspace-retype for
    words containing Vietnamese diacritics (see module docstring). Click/
    focus the target field BEFORE calling this — this function only sends
    keystrokes, it does not locate elements.

    If config.enabled is False, falls back to instant text insertion
    (page.keyboard.insert_text) — useful to disable per-account or for
    quick testing without changing call sites.
    """
    cfg = config or HumanTypingConfig()

    if not cfg.enabled:
        await page.keyboard.insert_text(text)
        return

    chars_typed = 0
    # Alternating runs of non-whitespace ("words") and whitespace,
    # covering every character exactly once — concatenating the tokens
    # back together reproduces `text` exactly.
    tokens = re.findall(r"\S+|\s+", text)

    for token in tokens:
        if token.isspace():
            for ch in token:
                if ch == "\n":
                    # Confirmed live 2026-09-09 (real incident, account
                    # tu_iizuki, posting into a group): Facebook's group
                    # composer shows an inline member-tag suggestion
                    # dropdown while typing a word that matches a group
                    # member's name (e.g. typing "Tokyo" suggested a real
                    # member named "Tokyo Tran") — keyboard.type("\n")
                    # below sends an actual Enter keypress, and Facebook
                    # intercepts Enter while that dropdown is open to
                    # ACCEPT the highlighted suggestion instead of
                    # inserting a line break, silently corrupting the
                    # post (merged lines, injected mention text). A
                    # plain space closes the dropdown without accepting
                    # anything, so typing one right before Enter — with a
                    # short pause for Facebook's JS to actually dismiss
                    # it — reliably avoids this. The trailing space this
                    # leaves at the end of the previous line is invisible
                    # once rendered.
                    await page.keyboard.type(" ")
                    await page.wait_for_timeout(random.uniform(150, 350))
                chars_typed = await _type_one_char(page, ch, cfg, chars_typed)
            continue

        word = token
        chars_typed = await _type_word(page, word, cfg, chars_typed)

        has_diacritics = any(not ch.isascii() for ch in word)
        if has_diacritics and random.random() < cfg.word_typo_probability:
            # Whole-word "typed it, noticed, retyped" correction. Always
            # retypes the SAME correct word — this can never corrupt the
            # final text, only add a human-looking hesitation around it.
            await page.wait_for_timeout(
                random.uniform(cfg.typo_notice_delay_min_ms, cfg.typo_notice_delay_max_ms)
            )
            for _ in range(len(word)):
                await page.keyboard.press("Backspace")
                # Backspacing a word you already know is wrong tends to be
                # a bit brisker/more rhythmic than composing new text.
                await page.wait_for_timeout(_sample_char_delay_ms(cfg) * 0.6)
            await page.wait_for_timeout(random.uniform(cfg.word_pause_min_ms, cfg.word_pause_max_ms))
            chars_typed = await _type_word(page, word, cfg, chars_typed)


async def human_pause(min_ms: float = 300, max_ms: float = 900) -> None:
    """
    A short generic randomized pause between distinct UI steps. Prefer the
    named, independently-configurable HumanPacingConfig pauses below
    (pause_after_page_load, pause_after_composer_open,
    pause_between_ui_steps, reading_pause) for steps that have a specific
    real-world timing expectation — this generic one is for anywhere else
    a "don't click through instantly" pause is needed.
    """
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)


# =============================================================================
# Contextual pacing
# =============================================================================

@dataclass
class HumanPacingConfig:
    """
    Named pauses for specific points in a UI flow, each independently
    configurable — as opposed to human_pause()'s one-size-fits-all short
    pause. Default ranges follow
    docs/research/human-behavior-simulation.md's contextual delay table.
    """
    enabled: bool = field(default_factory=lambda: _env_bool("HUMAN_PACE_ENABLED", True))

    # After landing on a page, before doing anything at all.
    page_load_pause_min_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_PACE_PAGE_LOAD_MIN_MS", 7000.0)
    )
    page_load_pause_max_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_PACE_PAGE_LOAD_MAX_MS", 10000.0)
    )

    # After opening a composer/dialog, before interacting with it.
    composer_open_pause_min_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_PACE_COMPOSER_OPEN_MIN_MS", 3000.0)
    )
    composer_open_pause_max_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_PACE_COMPOSER_OPEN_MAX_MS", 5000.0)
    )

    # Between each click in a multi-step picker flow (e.g. the audience/
    # privacy selector: click -> wait -> click -> wait).
    ui_step_pause_min_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_PACE_UI_STEP_MIN_MS", 1500.0)
    )
    ui_step_pause_max_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_PACE_UI_STEP_MAX_MS", 3000.0)
    )

    # "Reading back" typed content before submitting — modeled on silent
    # reading speed (word count / reading_wpm) plus a random buffer,
    # rather than a flat random range, so a one-line status and a long
    # paragraph don't get the same review time. Clamped to
    # [reading_pause_min_ms, reading_pause_max_ms].
    reading_wpm: float = field(default_factory=lambda: _env_float("HUMAN_PACE_READING_WPM", 220.0))
    reading_pause_min_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_PACE_READING_MIN_MS", 5000.0)
    )
    reading_pause_max_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_PACE_READING_MAX_MS", 20000.0)
    )
    reading_buffer_min_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_PACE_READING_BUFFER_MIN_MS", 500.0)
    )
    reading_buffer_max_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_PACE_READING_BUFFER_MAX_MS", 2000.0)
    )


async def pause_after_page_load(config: HumanPacingConfig | None = None) -> None:
    cfg = config or HumanPacingConfig()
    if not cfg.enabled:
        return
    await asyncio.sleep(random.uniform(cfg.page_load_pause_min_ms, cfg.page_load_pause_max_ms) / 1000)


async def pause_after_composer_open(config: HumanPacingConfig | None = None) -> None:
    cfg = config or HumanPacingConfig()
    if not cfg.enabled:
        return
    await asyncio.sleep(
        random.uniform(cfg.composer_open_pause_min_ms, cfg.composer_open_pause_max_ms) / 1000
    )


async def pause_between_ui_steps(config: HumanPacingConfig | None = None) -> None:
    cfg = config or HumanPacingConfig()
    if not cfg.enabled:
        return
    await asyncio.sleep(random.uniform(cfg.ui_step_pause_min_ms, cfg.ui_step_pause_max_ms) / 1000)


async def reading_pause(content: str, config: HumanPacingConfig | None = None) -> None:
    """Pause as if reading `content` back before submitting it."""
    cfg = config or HumanPacingConfig()
    if not cfg.enabled:
        return
    word_count = max(len(content.split()), 1)
    estimated_ms = (word_count / cfg.reading_wpm) * 60000.0
    buffer_ms = random.uniform(cfg.reading_buffer_min_ms, cfg.reading_buffer_max_ms)
    total_ms = min(max(estimated_ms + buffer_ms, cfg.reading_pause_min_ms), cfg.reading_pause_max_ms)
    await asyncio.sleep(total_ms / 1000)


# =============================================================================
# Mouse movement
# =============================================================================

@dataclass
class HumanMouseConfig:
    """
    Bezier-curve-style mouse movement before a click, instead of jumping
    straight there. Inspired by the ghost-cursor library's algorithm (see
    docs/research/human-behavior-simulation.md): one random control point
    offset to a single side of the straight line, step count/speed scaled
    to distance (a rough Fitts's-law approximation), and an occasional
    overshoot-then-correct for longer moves.
    """
    enabled: bool = field(default_factory=lambda: _env_bool("HUMAN_MOUSE_ENABLED", True))
    min_steps: int = field(default_factory=lambda: int(_env_float("HUMAN_MOUSE_MIN_STEPS", 8)))
    max_steps: int = field(default_factory=lambda: int(_env_float("HUMAN_MOUSE_MAX_STEPS", 20)))
    step_delay_min_ms: float = field(default_factory=lambda: _env_float("HUMAN_MOUSE_STEP_DELAY_MIN_MS", 8.0))
    step_delay_max_ms: float = field(default_factory=lambda: _env_float("HUMAN_MOUSE_STEP_DELAY_MAX_MS", 20.0))
    # Perpendicular control-point offset, as a fraction of the straight-line
    # distance between start and target.
    curve_offset_ratio: float = field(
        default_factory=lambda: _env_float("HUMAN_MOUSE_CURVE_OFFSET_RATIO", 0.18)
    )
    overshoot_probability: float = field(
        default_factory=lambda: _env_float("HUMAN_MOUSE_OVERSHOOT_PROB", 0.15)
    )
    # How far past the target an overshoot goes, as a fraction of distance.
    overshoot_ratio: float = field(default_factory=lambda: _env_float("HUMAN_MOUSE_OVERSHOOT_RATIO", 0.08))
    # Below this distance, just snap directly — animating a curve over a
    # few pixels looks (and is) pointless.
    min_distance_for_curve_px: float = field(
        default_factory=lambda: _env_float("HUMAN_MOUSE_MIN_DISTANCE_PX", 12.0)
    )
    # Time between mousedown and mouseup (page.mouse.click's own `delay`
    # param defaults to 0 — an instant down-up that's an easy behavioral
    # tell; real clicks always have some dwell time). Added 2026-09-08
    # after researching mouse-dynamics bot detection — see
    # docs/research/human-behavior-simulation.md.
    click_delay_min_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_MOUSE_CLICK_DELAY_MIN_MS", 40.0)
    )
    click_delay_max_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_MOUSE_CLICK_DELAY_MAX_MS", 120.0)
    )
    # Small random offset applied to each INTERMEDIATE point along the
    # curve (never the final landing point) — a real hand has sub-pixel
    # tremor a pure mathematical Bezier curve doesn't; that "too smooth"
    # quality is itself a signal mouse-dynamics classifiers look for.
    # Added 2026-09-08, same research pass as click_delay_* above.
    jitter_px: float = field(default_factory=lambda: _env_float("HUMAN_MOUSE_JITTER_PX", 1.5))


# Last known mouse position per page, keyed by id(page) — Playwright has no
# getter for current mouse position, so we track it ourselves. A stale
# entry after a page is replaced (e.g. AccountSession.restart_session()) is
# harmless: the next move just starts its curve from an outdated point.
_last_mouse_pos: dict[int, tuple[float, float]] = {}


def _quadratic_bezier(
    p0: tuple[float, float], p1: tuple[float, float], p2: tuple[float, float], t: float
) -> tuple[float, float]:
    x = (1 - t) ** 2 * p0[0] + 2 * (1 - t) * t * p1[0] + t ** 2 * p2[0]
    y = (1 - t) ** 2 * p0[1] + 2 * (1 - t) * t * p1[1] + t ** 2 * p2[1]
    return x, y


def _ease_in_out(t: float) -> float:
    """Smoothstep easing (slow-fast-slow spatial progression) applied to
    an otherwise-linear, roughly-constant-time step sequence — this is
    what produces the bell-shaped velocity profile real human mouse
    movement has (Fitts's law: accelerate, peak speed mid-movement,
    decelerate into the target), instead of the constant-speed traversal
    a naive curve-following bot produces. Added 2026-09-08 after
    researching mouse-dynamics bot detection (constant velocity along an
    otherwise-plausible curve is itself a classifier signal) — see
    docs/research/human-behavior-simulation.md."""
    return t * t * (3 - 2 * t)


async def human_mouse_move(
    page: Page, target_x: float, target_y: float, config: HumanMouseConfig | None = None
) -> None:
    """
    Move the mouse from wherever it was last put (per this module's own
    tracking — see _last_mouse_pos) to (target_x, target_y) along a
    slightly curved path with several intermediate steps, instead of
    jumping straight there. Falls back to a single instant move if
    disabled or the distance is negligible. Does NOT click — see
    human_click() for the full move-then-click helper.
    """
    cfg = config or HumanMouseConfig()
    start_x, start_y = _last_mouse_pos.get(id(page), (target_x, target_y))

    if not cfg.enabled:
        await page.mouse.move(target_x, target_y)
        _last_mouse_pos[id(page)] = (target_x, target_y)
        return

    distance = ((target_x - start_x) ** 2 + (target_y - start_y) ** 2) ** 0.5
    if distance < cfg.min_distance_for_curve_px:
        await page.mouse.move(target_x, target_y)
        _last_mouse_pos[id(page)] = (target_x, target_y)
        return

    mid_x = (start_x + target_x) / 2
    mid_y = (start_y + target_y) / 2
    # Perpendicular direction to the start->target line.
    perp_x, perp_y = -(target_y - start_y), (target_x - start_x)
    perp_len = max((perp_x ** 2 + perp_y ** 2) ** 0.5, 1e-6)
    side = random.choice([-1, 1])  # one side only, per ghost-cursor's approach
    offset = distance * cfg.curve_offset_ratio * side
    control_x = mid_x + (perp_x / perp_len) * offset
    control_y = mid_y + (perp_y / perp_len) * offset

    end_x, end_y = target_x, target_y
    will_overshoot = random.random() < cfg.overshoot_probability
    if will_overshoot:
        end_x = target_x + (target_x - start_x) * cfg.overshoot_ratio
        end_y = target_y + (target_y - start_y) * cfg.overshoot_ratio

    # int(...) matters here, not just cosmetic: cfg.min_steps/max_steps are
    # floats (admin-editable via /admin/config), so whenever the clamp
    # picks one of those bounds instead of round(distance / 25), max()/min()
    # hand back that float as-is — range() below then raises "'float'
    # object cannot be interpreted as an integer" (hit in production
    # 2026-09-07, only on distances short/long enough to actually clamp).
    steps = int(max(cfg.min_steps, min(cfg.max_steps, round(distance / 25))))
    for i in range(1, steps + 1):
        t = _ease_in_out(i / steps)
        x, y = _quadratic_bezier((start_x, start_y), (control_x, control_y), (end_x, end_y), t)
        if i < steps and cfg.jitter_px > 0:
            # Never jitter the final point of this leg — the curve still
            # has to actually land where it's supposed to (on the target,
            # or on the overshoot point before correction).
            x += random.uniform(-cfg.jitter_px, cfg.jitter_px)
            y += random.uniform(-cfg.jitter_px, cfg.jitter_px)
        await page.mouse.move(x, y)
        await page.wait_for_timeout(random.uniform(cfg.step_delay_min_ms, cfg.step_delay_max_ms))

    if will_overshoot:
        # Correct back from the overshoot in a few small steps.
        for i in range(1, 4):
            t = _ease_in_out(i / 3)
            x = end_x + (target_x - end_x) * t
            y = end_y + (target_y - end_y) * t
            if i < 3 and cfg.jitter_px > 0:
                x += random.uniform(-cfg.jitter_px, cfg.jitter_px)
                y += random.uniform(-cfg.jitter_px, cfg.jitter_px)
            await page.mouse.move(x, y)
            await page.wait_for_timeout(random.uniform(cfg.step_delay_min_ms, cfg.step_delay_max_ms))

    _last_mouse_pos[id(page)] = (target_x, target_y)


# =============================================================================
# Scrolling
# =============================================================================

@dataclass
class HumanScrollConfig:
    """
    Eased, multi-step scroll toward an element using real wheel-scroll
    events (page.mouse.wheel — a CDP Input-domain call, same trust level
    as mouse clicks, see this module's top-of-file note on isTrusted)
    instead of Playwright's own scroll_into_view_if_needed(), which jumps
    straight to position in a single instant call — an obvious tell,
    since real scrolling always takes multiple wheel ticks with the step
    size shrinking as the target gets closer (physical scroll-wheel
    inertia). Added 2026-09-08 after comparing notes with another
    automation codebase's smoothScrollTo() — see this module's top-of-file
    note and README.md's "Điểm yếu đã ghi nhận" for the full comparison.
    """
    enabled: bool = field(default_factory=lambda: _env_bool("HUMAN_SCROLL_ENABLED", True))
    step_delay_min_ms: float = field(default_factory=lambda: _env_float("HUMAN_SCROLL_STEP_DELAY_MIN_MS", 40.0))
    step_delay_max_ms: float = field(default_factory=lambda: _env_float("HUMAN_SCROLL_STEP_DELAY_MAX_MS", 90.0))
    # Cap on any single wheel tick, however far the target still is.
    max_step_px: float = field(default_factory=lambda: _env_float("HUMAN_SCROLL_MAX_STEP_PX", 400.0))
    # Fraction of the remaining distance covered per tick — this alone is
    # what produces the deceleration curve (each tick closes part of the
    # gap, so the gap — and therefore the next tick — keeps shrinking).
    deceleration_ratio: float = field(
        default_factory=lambda: _env_float("HUMAN_SCROLL_DECELERATION_RATIO", 0.5)
    )
    # Safety cap so a target that never reports as "in view" (a detached
    # element, an unexpected layout) can't loop forever — the trailing
    # scroll_into_view_if_needed() below still guarantees correctness.
    max_iterations: int = field(default_factory=lambda: int(_env_float("HUMAN_SCROLL_MAX_ITERATIONS", 10)))


async def human_scroll_to(page: Page, locator, config: HumanScrollConfig | None = None) -> None:
    """
    Scroll the page toward `locator` in several real wheel-scroll steps
    (page.mouse.wheel) with a shrinking step size, instead of an instant
    jump. Always finishes with Playwright's own scroll_into_view_if_needed()
    as a precise correction — the eased loop above only needs to get
    close; exact positioning still has to be guaranteed for the click that
    follows.
    """
    cfg = config or HumanScrollConfig()
    if not cfg.enabled:
        await locator.scroll_into_view_if_needed()
        return
    viewport = page.viewport_size
    if viewport is None:
        await locator.scroll_into_view_if_needed()
        return
    for _ in range(cfg.max_iterations):
        box = await locator.bounding_box()
        if box is None:
            break
        target_center_y = box["y"] + box["height"] / 2
        remaining = target_center_y - viewport["height"] / 2
        if abs(remaining) < 20:
            break
        step = max(-cfg.max_step_px, min(cfg.max_step_px, remaining * cfg.deceleration_ratio))
        await page.mouse.wheel(0, step)
        await page.wait_for_timeout(random.uniform(cfg.step_delay_min_ms, cfg.step_delay_max_ms))
    await locator.scroll_into_view_if_needed()


async def human_click(
    page: Page,
    locator,
    mouse_config: HumanMouseConfig | None = None,
    scroll_config: HumanScrollConfig | None = None,
) -> None:
    """
    Click `locator` (a Playwright Locator) by curving the mouse to a
    random point inside its bounding box (human_mouse_move) instead of
    jumping straight there, then clicking at that exact point. Waits for
    the element to be visible and scrolls it into view first (via
    human_scroll_to's eased wheel-scroll, not an instant jump), mirroring
    the checks Locator.click() would normally do for us — since we bypass
    its own move+click, we take on that responsibility here.

    scroll_config isn't threaded through actions.py's ~25 call sites the
    way mouse_config is (there's no case where a caller would want a
    different scroll behavior than the account's current admin setting,
    unlike mouse_config which a couple of call sites do override) — when
    not given, it's fetched live from human_bot/runtime_config.py via a
    local import here, the same "avoid an import cycle at module load"
    pattern already used elsewhere in this codebase (e.g.
    human_bot/data_sync.py's fire_due_tasks()).
    """
    if scroll_config is None:
        from human_bot.runtime_config import get_scroll_config  # local import — avoid import cycle at module load
        scroll_config = get_scroll_config()
    mouse_cfg = mouse_config or HumanMouseConfig()
    await locator.wait_for(state="visible")
    await human_scroll_to(page, locator, scroll_config)
    box = await locator.bounding_box()
    if box is None:
        # Couldn't read a bounding box (e.g. element became detached) —
        # fall back to Playwright's own click rather than hard-failing.
        await locator.click()
        return
    target_x = box["x"] + random.uniform(0.3, 0.7) * box["width"]
    target_y = box["y"] + random.uniform(0.3, 0.7) * box["height"]
    await human_mouse_move(page, target_x, target_y, mouse_cfg)
    await page.mouse.click(
        target_x, target_y, delay=random.uniform(mouse_cfg.click_delay_min_ms, mouse_cfg.click_delay_max_ms)
    )
