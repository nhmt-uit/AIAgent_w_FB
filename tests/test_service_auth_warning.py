from __future__ import annotations

import pytest

import human_bot.service as svc


def _clear_auth_env(monkeypatch):
    for name in ("ADMIN_USERNAME", "ADMIN_PASSWORD", "TASKS_API_KEY"):
        monkeypatch.delenv(name, raising=False)


def test_warns_when_all_three_missing(monkeypatch, caplog):
    _clear_auth_env(monkeypatch)
    with caplog.at_level("WARNING", logger=svc.logger.name):
        svc._warn_if_auth_unconfigured()
    assert len(caplog.records) == 1
    msg = caplog.records[0].getMessage()
    assert "ADMIN_USERNAME" in msg and "ADMIN_PASSWORD" in msg and "TASKS_API_KEY" in msg


def test_warns_listing_only_the_missing_ones(monkeypatch, caplog):
    _clear_auth_env(monkeypatch)
    monkeypatch.setenv("ADMIN_USERNAME", "u")
    monkeypatch.setenv("ADMIN_PASSWORD", "p")
    with caplog.at_level("WARNING", logger=svc.logger.name):
        svc._warn_if_auth_unconfigured()
    assert len(caplog.records) == 1
    msg = caplog.records[0].getMessage()
    assert "TASKS_API_KEY" in msg
    assert "ADMIN_USERNAME" not in msg
    assert "ADMIN_PASSWORD" not in msg


def test_no_warning_when_all_three_set(monkeypatch, caplog):
    monkeypatch.setenv("ADMIN_USERNAME", "u")
    monkeypatch.setenv("ADMIN_PASSWORD", "p")
    monkeypatch.setenv("TASKS_API_KEY", "k")
    with caplog.at_level("WARNING", logger=svc.logger.name):
        svc._warn_if_auth_unconfigured()
    assert len(caplog.records) == 0


def test_blank_string_env_var_counts_as_missing(monkeypatch, caplog):
    monkeypatch.setenv("ADMIN_USERNAME", "   ")
    monkeypatch.setenv("ADMIN_PASSWORD", "p")
    monkeypatch.setenv("TASKS_API_KEY", "k")
    with caplog.at_level("WARNING", logger=svc.logger.name):
        svc._warn_if_auth_unconfigured()
    assert len(caplog.records) == 1
    assert "ADMIN_USERNAME" in caplog.records[0].getMessage()


def test_warn_returns_the_missing_list(monkeypatch):
    _clear_auth_env(monkeypatch)
    assert svc._warn_if_auth_unconfigured() == ["ADMIN_USERNAME", "ADMIN_PASSWORD", "TASKS_API_KEY"]


# --- _confirm_startup_or_abort ----------------------------------------------

def test_confirm_startup_noop_when_nothing_missing(monkeypatch):
    # Must not touch stdin/input at all when there's nothing to confirm.
    monkeypatch.setattr(svc.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("must not prompt")))
    svc._confirm_startup_or_abort([])  # no raise


def test_confirm_startup_skips_prompt_when_not_a_tty(monkeypatch):
    # A detached/backgrounded deployment (systemd, Docker, CI) has no one
    # to answer — must continue unattended (log-only warning), not hang.
    monkeypatch.setattr(svc.sys.stdin, "isatty", lambda: False)
    monkeypatch.setattr("builtins.input", lambda prompt="": (_ for _ in ()).throw(AssertionError("must not prompt")))
    svc._confirm_startup_or_abort(["ADMIN_USERNAME"])  # no raise


def test_confirm_startup_continues_on_explicit_y(monkeypatch):
    monkeypatch.setattr(svc.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "y")
    svc._confirm_startup_or_abort(["ADMIN_USERNAME"])  # no raise


def test_confirm_startup_aborts_on_anything_other_than_y(monkeypatch):
    monkeypatch.setattr(svc.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", lambda prompt="": "")
    with pytest.raises(RuntimeError):
        svc._confirm_startup_or_abort(["ADMIN_USERNAME"])


def test_confirm_startup_aborts_on_eof(monkeypatch):
    def _raise_eof(prompt=""):
        raise EOFError

    monkeypatch.setattr(svc.sys.stdin, "isatty", lambda: True)
    monkeypatch.setattr("builtins.input", _raise_eof)
    with pytest.raises(RuntimeError):
        svc._confirm_startup_or_abort(["ADMIN_USERNAME"])
