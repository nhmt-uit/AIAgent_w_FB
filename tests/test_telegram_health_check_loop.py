"""
Tests for human_bot/service.py's _telegram_health_check_loop() — the
background loop that fires Telegram alert types 4/5 and 5/5 ("im lặng
quá 48 giờ" / "phiên sắp hết hạn"), added 2026-10-05. Drives exactly 1
iteration per test via a fake asyncio.sleep that raises to stop the
`while True` loop right after the per-account scan completes.

2026-10-05 self-review, round 5: the loop now calls human_bot/admin.py's
_account_warning_status() directly for its actual combination logic
(rather than re-deriving it), so the dependencies to monkeypatch
(bootstrap_login_sessions.get_session_expiry, get_resume_cooldown_info)
live on the `admin` module now, not on `svc` — _account_warning_status
is the exact same function object under both names, so patching admin's
module globals affects it however it's called.
"""
from __future__ import annotations

import asyncio

import pytest

import human_bot.service as svc
from human_bot import admin
from human_bot.config import AccountConfig


def _account(aid="acc-a", name="Account A") -> AccountConfig:
    return AccountConfig(account_id=aid, display_name=name)


async def _run_one_iteration(monkeypatch, accounts: dict, last_success_map: dict, expiry_map: dict):
    sent = []

    async def fake_send_message(text, *, silent=False):
        sent.append((text, silent))

    async def fake_sleep(seconds):
        raise asyncio.CancelledError  # stop after exactly 1 scan

    monkeypatch.setattr(svc, "get_all_accounts", lambda: accounts)
    monkeypatch.setattr(svc.db, "last_successful_action_per_account", lambda: last_success_map)
    monkeypatch.setattr(
        admin.bootstrap_login_sessions, "get_session_expiry", lambda aid: expiry_map.get(aid),
    )
    monkeypatch.setattr(admin, "get_resume_cooldown_info", lambda aid: None)
    monkeypatch.setattr(svc.telegram_notify, "send_message", fake_send_message)
    monkeypatch.setattr(svc.asyncio, "sleep", fake_sleep)

    with pytest.raises(asyncio.CancelledError):
        await svc._telegram_health_check_loop()
    return sent


async def test_session_unreadable_sends_a_loud_alert(monkeypatch):
    """expiry=None means "chưa đăng nhập/file hỏng" — admin.py's
    _account_health_signals() treats this as its WORST (red) case for
    the session signal, and the Telegram loop must alert on it too."""
    sent = await _run_one_iteration(
        monkeypatch,
        accounts={"acc-a": _account()},
        last_success_map={},
        expiry_map={},  # acc-a has no readable session at all
    )
    assert len(sent) == 1
    text, silent = sent[0]
    assert silent is False
    assert "không đọc được phiên đăng nhập" in text.lower()


async def test_session_expired_sends_the_expired_wording_not_expiring_soon(monkeypatch):
    """Regression test (2026-10-05 self-review, round 5): a prior
    version only had 2 warning buckets (session_unreadable /
    session_expiry) and treated an ALREADY-expired session
    (days_left < 0) the same as one merely expiring soon, sending the
    milder "sắp hết hạn" (about to expire) wording — while /admin's
    dashboard correctly shows red "đã hết hạn" (already expired) for
    the same account. Must send the distinct, more urgent wording."""
    from datetime import datetime, timedelta, timezone

    already_expired = datetime.now(timezone.utc) - timedelta(days=3)
    sent = await _run_one_iteration(
        monkeypatch,
        accounts={"acc-a": _account()},
        last_success_map={},
        expiry_map={"acc-a": already_expired},
    )
    assert len(sent) == 1
    text, silent = sent[0]
    assert silent is False
    assert "đã hết hạn" in text.lower()
    assert "sắp hết hạn" not in text.lower()


async def test_session_expiring_soon_sends_the_softer_wording(monkeypatch):
    from datetime import datetime, timedelta, timezone

    expiring_soon = datetime.now(timezone.utc) + timedelta(days=5)
    sent = await _run_one_iteration(
        monkeypatch,
        accounts={"acc-a": _account()},
        last_success_map={},
        expiry_map={"acc-a": expiring_soon},
    )
    assert len(sent) == 1
    text, silent = sent[0]
    assert silent is False
    assert "sắp hết hạn" in text.lower()


async def test_one_accounts_bad_timestamp_does_not_skip_its_own_session_check_or_another_account(monkeypatch):
    """Regression test (2026-10-05 self-review, rounds 4 and 5): round 4
    isolated the scan PER ACCOUNT so one account's failure didn't skip
    every OTHER account's check. Round 5 went a level deeper —
    _account_warning_status() isolates its 2 independent sub-checks
    (silence; session) from EACH OTHER too, so acc-bad's unparsable
    last_success timestamp (which breaks only the silence check) must
    not also suppress acc-bad's OWN session_unreadable alert, in
    addition to not suppressing acc-good's alert."""
    sent = await _run_one_iteration(
        monkeypatch,
        accounts={"acc-bad": _account("acc-bad", "Bad"), "acc-good": _account("acc-good", "Good")},
        last_success_map={"acc-bad": "not-a-valid-timestamp"},  # datetime.fromisoformat() raises
        expiry_map={"acc-bad": None, "acc-good": None},  # both also trip "session_unreadable"
    )
    assert any("acc-bad" in text for text, _silent in sent)
    assert any("acc-good" in text for text, _silent in sent)
