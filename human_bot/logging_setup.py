"""
Purpose of this file / Muc dich cua file nay:
EN: Persist logger.exception() calls (human_bot/service.py's background
loops in particular — _data_sync_poll_loop, _data_sync_fire_loop, the
cleanup loops) to a file, not just the process's stdout/stderr. Before
this, an error in the side-B sync loop was only visible in the terminal
running `uvicorn` — invisible if that process runs detached/backgrounded
without output redirection, and lost on restart either way. Rotates so
this can't grow unbounded over a long-running 24/7 process.
VI: Ghi lai moi logger.exception() (dac biet la cac vong lap nen trong
human_bot/service.py — _data_sync_poll_loop, _data_sync_fire_loop, cac
vong lap don dep) ra file, khong chi dung lai o stdout/stderr cua tien
trinh. Truoc day, loi trong vong lap dong bo ben B chi thay duoc tren
terminal dang chay `uvicorn` — mat luon neu tien trinh chay ngam khong
redirect output, va mat khi restart du sao di nua. Co xoay vong (rotate)
de khong phinh to vo han qua mot tien trinh chay 24/7 lau dai.
"""
from __future__ import annotations

import logging
from logging.handlers import RotatingFileHandler
from pathlib import Path

LOG_DIR = Path(__file__).resolve().parent.parent / "logs"
LOG_PATH = LOG_DIR / "human_bot.log"

_configured = False


def configure_logging() -> None:
    global _configured
    if _configured:
        return
    _configured = True

    LOG_DIR.mkdir(parents=True, exist_ok=True)
    handler = RotatingFileHandler(LOG_PATH, maxBytes=5 * 1024 * 1024, backupCount=5, encoding="utf-8")
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(name)s: %(message)s"))
    handler.setLevel(logging.INFO)

    root = logging.getLogger()
    root.addHandler(handler)
    if root.level > logging.INFO or root.level == logging.NOTSET:
        root.setLevel(logging.INFO)
