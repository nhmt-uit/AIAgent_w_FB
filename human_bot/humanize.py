"""
Human-like typing and pacing simulation for Playwright actions.

Purpose: bot-detection systems (including Facebook's) look at behavioral
signals beyond raw activity volume — mouse movement, scroll patterns, and
TYPING CADENCE specifically are called out as signals modern systems check
(see docs/skills/human-like-interaction.md for citations). Every action
that types text should go through human_type() here instead of
page.fill()/locator.fill(), which sets a field's value instantly with no
per-character timing at all — one of the most obviously non-human signals
possible.

All tunables are centralized in HumanTypingConfig below and overridable
via environment variables in .env, so behavior can be adjusted without
touching code — see docs/skills/human-like-interaction.md for what each
setting means, research-backed default ranges, and further reading.

Honesty about limits: this is a best-effort approximation of human typing
rhythm and error patterns, not a guarantee against detection. It does not
touch mouse movement, scroll behavior, or click timing beyond the small
pauses human_pause() adds. Typo injection only applies to plain ASCII
letters — Vietnamese diacritic characters are typed without simulated
typos, because a naive QWERTY-neighbor substitution does not reflect how
those characters are actually produced (via an input method, not a single
physical key), and getting this wrong risks corrupting otherwise-correct
text.
"""
import asyncio
import os
import random
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

    # Typo simulation (ASCII letters only — see module docstring).
    typo_probability: float = field(default_factory=lambda: _env_float("HUMAN_TYPING_TYPO_PROB", 0.03))
    typo_notice_delay_min_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_TYPING_TYPO_NOTICE_MIN_MS", 150.0)
    )
    typo_notice_delay_max_ms: float = field(
        default_factory=lambda: _env_float("HUMAN_TYPING_TYPO_NOTICE_MAX_MS", 450.0)
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


async def human_type(page: Page, text: str, config: HumanTypingConfig | None = None) -> None:
    """
    Types `text` into whatever element on `page` currently has keyboard
    focus, character by character, with human-like timing and occasional
    typo+correction. Click/focus the target field BEFORE calling this —
    this function only sends keystrokes, it does not locate elements.

    If config.enabled is False, falls back to instant text insertion
    (page.keyboard.insert_text) — useful to disable per-account or for
    quick testing without changing call sites.
    """
    cfg = config or HumanTypingConfig()

    if not cfg.enabled:
        await page.keyboard.insert_text(text)
        return

    chars_typed = 0
    for char in text:
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

        if char == " ":
            delay_ms += random.uniform(cfg.word_pause_min_ms, cfg.word_pause_max_ms)
        elif char in ".,!?;:":
            delay_ms += random.uniform(cfg.punctuation_pause_min_ms, cfg.punctuation_pause_max_ms)

        await page.wait_for_timeout(delay_ms)


async def human_pause(min_ms: float = 300, max_ms: float = 900) -> None:
    """
    A short randomized pause between distinct UI steps that are NOT typing
    (e.g. after opening the composer, before clicking the next button) —
    real people don't click through a multi-step flow instantly either.
    """
    await asyncio.sleep(random.uniform(min_ms, max_ms) / 1000)
