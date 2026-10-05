"""
peek_session() (2026-10-02, added for /admin's "sức khoẻ tài khoản" card)
— the only piece of browser_pool.py testable without a real Playwright
browser. Everything else in this module launches real browsers and isn't
unit-tested.
"""
from __future__ import annotations

import pytest

from human_bot import browser_pool
from human_bot.config import AccountConfig


@pytest.fixture(autouse=True)
def _isolated_pool(monkeypatch):
    """The module-level `_pool` dict is shared/global — never let a test
    leak an entry into another test or (worse) the real running pool."""
    monkeypatch.setattr(browser_pool, "_pool", {})


def test_peek_session_returns_none_when_never_created():
    assert browser_pool.peek_session("no_such_account") is None


def test_peek_session_never_creates_an_entry_as_a_side_effect():
    """The whole point of peek_session() over get_session() — a dashboard
    view must not itself cause an account to gain a pool entry."""
    browser_pool.peek_session("acc1")
    assert "acc1" not in browser_pool._pool


def test_peek_session_returns_the_real_session_created_via_get_session():
    account = AccountConfig(account_id="acc1", display_name="Acc One")
    created = browser_pool.get_session(account)
    assert browser_pool.peek_session("acc1") is created


def test_fresh_session_peeked_is_not_alive():
    account = AccountConfig(account_id="acc1", display_name="Acc One")
    browser_pool.get_session(account)
    session = browser_pool.peek_session("acc1")
    assert session.is_alive() is False
