"""
get_session_expiry() (2026-10-02, added for /admin's "sức khoẻ tài khoản"
card) — the only piece of bootstrap_login_sessions.py testable without a
real Playwright browser. Everything else in this module drives a real
headed login flow and isn't unit-tested.
"""
from __future__ import annotations

import json

import pytest

from human_bot import bootstrap_login_sessions as bls


@pytest.fixture
def isolated_accounts_dir(tmp_path, monkeypatch):
    monkeypatch.setattr(bls, "ACCOUNTS_DIR", tmp_path)
    return tmp_path


def _write_storage_state(accounts_dir, account_id: str, cookies: list[dict]) -> None:
    acc_dir = accounts_dir / account_id
    acc_dir.mkdir(parents=True, exist_ok=True)
    (acc_dir / "storage_state.json").write_text(
        json.dumps({"cookies": cookies, "origins": []}), encoding="utf-8"
    )


def test_get_session_expiry_none_when_file_missing(isolated_accounts_dir):
    assert bls.get_session_expiry("never_logged_in") is None


def test_get_session_expiry_none_when_json_corrupt(isolated_accounts_dir):
    acc_dir = isolated_accounts_dir / "acc1"
    acc_dir.mkdir()
    (acc_dir / "storage_state.json").write_text("{not valid json", encoding="utf-8")
    assert bls.get_session_expiry("acc1") is None


def test_get_session_expiry_uses_min_of_real_auth_cookies_only(isolated_accounts_dir):
    """Regression test for the real finding (2026-10-02, read a live
    storage_state.json): a plain min() over EVERY cookie picks up "wd"
    (just the saved browser window size), which expires far sooner than
    the real Facebook auth cookies and would false-alarm constantly. Only
    c_user/xs/fr may ever decide this."""
    _write_storage_state(isolated_accounts_dir, "acc1", [
        {"name": "wd", "domain": ".facebook.com", "expires": 1000},  # soonest, must be ignored
        {"name": "c_user", "domain": "facebook.com", "expires": 3000},
        {"name": "xs", "domain": "facebook.com", "expires": 2000},
        {"name": "fr", "domain": "facebook.com", "expires": 5000},
        {"name": "unrelated_cookie", "domain": "google.com", "expires": 500},
    ])
    expiry = bls.get_session_expiry("acc1")
    assert expiry is not None
    assert expiry.timestamp() == 2000  # min(c_user=3000, xs=2000, fr=5000)


def test_get_session_expiry_none_when_no_auth_cookies_present(isolated_accounts_dir):
    _write_storage_state(isolated_accounts_dir, "acc1", [
        {"name": "wd", "domain": ".facebook.com", "expires": 1000},
        {"name": "datr", "domain": ".facebook.com", "expires": 9999999999},
    ])
    assert bls.get_session_expiry("acc1") is None


def test_get_session_expiry_ignores_session_only_cookies(isolated_accounts_dir):
    """A cookie with no `expires` (or -1, Playwright's session-cookie
    marker) must not crash or be treated as "already expired"."""
    _write_storage_state(isolated_accounts_dir, "acc1", [
        {"name": "xs", "domain": "facebook.com", "expires": -1},
        {"name": "fr", "domain": "facebook.com", "expires": 4000},
    ])
    expiry = bls.get_session_expiry("acc1")
    assert expiry is not None
    assert expiry.timestamp() == 4000
