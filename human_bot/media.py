"""
Purpose of this file / Muc dich cua file nay:
EN: Picks a random image from the local meme pool (media/memes/) to
attach when a post's caller didn't supply its own media_path. This is
the Python-side half of "always attach a picture unless there's a
reason not to" — see media/memes/README.md for the full policy
(side-B-supplied images always take priority; a per-account/global
toggle at /admin/config can turn the whole thing off). The actual
Playwright step that attaches a file to Facebook's composer is a
SEPARATE, still-pending piece — see the `if media_path:` TODO blocks in
human_bot/actions.py's post_to_own_profile/post_to_group. This module
only decides WHICH file path to use, never touches a browser.
VI: Chon ngau nhien mot anh trong kho meme cuc bo (media/memes/) de dinh
kem khi noi goi dang bai khong tu dua media_path rieng. Day la nua
"Python side" cua chinh sach "mac dinh luon kem anh, tru khi co ly do
khong kem" — xem media/memes/README.md de biet day du chinh sach (anh
tu ben B luon duoc uu tien; co cong tac bat/tat toan cuc o /admin/config).
Buoc Playwright thuc su dinh kem file vao khung dang bai Facebook la mot
phan RIENG, van con dang cho ghi — xem cac khoi TODO `if media_path:`
trong post_to_own_profile/post_to_group cua human_bot/actions.py. Module
nay chi quyet dinh CHON file nao, khong dong vao trinh duyet.
"""
from __future__ import annotations

import os
import random
from dataclasses import dataclass, field
from pathlib import Path

MEMES_DIR = Path(__file__).resolve().parent.parent / "media" / "memes"


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class MediaConfig:
    """Same env-override + /admin-editable pattern as
    human_bot/data_sync_config.py's DataSyncConfig — see
    human_bot/runtime_config.py for how /admin's saved overrides layer on
    top of this .env/code default. One field for now (more can be added
    here later, e.g. a per-category meme subfolder), which is exactly why
    this is a dataclass + EDITABLE_MEDIA_FIELDS section like every other
    /admin-editable config, rather than a bare standalone bool."""
    attach_random_meme_default: bool = field(
        default_factory=lambda: _env_bool("ATTACH_RANDOM_MEME_DEFAULT", True)
    )

_IMAGE_EXTENSIONS = {".jpg", ".jpeg", ".png", ".gif", ".webp"}


def list_memes() -> list[Path]:
    """All image files currently in the meme pool. Best-effort — an
    unreadable/missing directory just means an empty pool, never an
    exception (this must never break a post over a filesystem hiccup)."""
    if not MEMES_DIR.is_dir():
        return []
    try:
        return sorted(
            p for p in MEMES_DIR.iterdir()
            if p.is_file() and p.suffix.lower() in _IMAGE_EXTENSIONS
        )
    except OSError:
        return []


def pick_random_meme() -> str | None:
    """A random meme's absolute path as a string (ready to hand straight
    to TaskRequest.media_path / Playwright's file chooser), or None if the
    pool is empty. Never raises."""
    memes = list_memes()
    if not memes:
        return None
    return str(random.choice(memes))
