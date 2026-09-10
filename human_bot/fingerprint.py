"""
Purpose of this file / Muc dich cua file nay:
EN: Per-account (not per-launch) browser context fingerprint
diversification. Requested 2026-09-09, after noting that human_bot/
browser_pool.py launches one Chromium PROCESS per account (real isolation
already, no shared browser between accounts) but every one of those
processes uses the exact same default viewport/DPI — so from Facebook's
side, every account still "looks like" it's coming from an identical
device. get_fingerprint() below derives a small, stable set of
context-launch values from account_id via hashing, so the same account
always gets the same profile across restarts — a value that changes on
every launch would itself be a STRONGER bot signal than no
diversification at all (see docs/skills/session-persistence.md, which
already calls out "fingerprint continuity" as something that makes a
session look like a returning human).

Deliberately narrow scope for now — only viewport size and
device_scale_factor vary per account. Two related things were considered
and deliberately NOT done here:
- user_agent: Playwright's `user_agent` context option only overrides
  navigator.userAgent and the UA request header — it does NOT change
  Chromium's own Client Hints (Sec-CH-UA-*, navigator.userAgentData),
  which still reflect the real installed Chromium build. Overriding one
  without the other creates a UA/Client-Hints MISMATCH, itself a stronger
  bot signal than using the real default UA everywhere. Randomizing this
  safely needs either disabling Client Hints entirely or a
  stealth-patching layer this project doesn't have.
- timezone_id / geolocation: these need to agree with the account's real
  (proxy) IP, or a timezone/IP mismatch becomes its own bot signal — worse
  than every account sharing one timezone. Only worth touching once each
  account has its own proxy/IP, which is a separate, not-yet-built
  improvement (per-account proxy was raised in the same conversation as
  this file and deferred).
VI: Da dang hoa fingerprint (theo tung tai khoan, khong phai theo tung
lan mo trinh duyet). Yeu cau 2026-09-09.
"""
from __future__ import annotations

import hashlib
from dataclasses import dataclass


@dataclass(frozen=True)
class AccountFingerprint:
    viewport: dict[str, int]
    device_scale_factor: float


# Common real desktop resolutions (laptop and external-monitor sizes
# actually seen in the wild), each paired with a device_scale_factor that
# realistically goes with it in practice (e.g. a 1440x900 MacBook is
# usually @2x, a 1920x1080 external monitor is usually @1x). Kept small
# and mundane on purpose — an exotic/rare size stands out MORE than
# blending into one of the most common few, which is the opposite of the
# goal here.
_PROFILES: list[AccountFingerprint] = [
    AccountFingerprint(viewport={"width": 1366, "height": 768}, device_scale_factor=1.0),
    AccountFingerprint(viewport={"width": 1440, "height": 900}, device_scale_factor=2.0),
    AccountFingerprint(viewport={"width": 1536, "height": 864}, device_scale_factor=1.25),
    AccountFingerprint(viewport={"width": 1920, "height": 1080}, device_scale_factor=1.0),
    AccountFingerprint(viewport={"width": 1280, "height": 800}, device_scale_factor=2.0),
]


def get_fingerprint(account_id: str) -> AccountFingerprint:
    """Deterministic pick from _PROFILES — the same account_id always maps
    to the same profile, stable across service restarts without needing
    any extra persisted state (see module docstring on why stability
    matters more than randomness here). Not cryptographic; sha256 is just
    a convenient, well-distributed hash to turn a string into a stable
    index."""
    digest = hashlib.sha256(account_id.encode("utf-8")).digest()
    index = digest[0] % len(_PROFILES)
    return _PROFILES[index]
