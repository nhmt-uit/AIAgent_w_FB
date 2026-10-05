"""
Tests for agent.py's run_task() Telegram hooks (2026-10-05, owner's 3-part
alert request — see tasks.md): a silent per-attempt report for every
GENUINE attempt (never for the 3 early-exit paths, which never touched
Facebook at all), plus the "N lần fail liên tiếp" loud alert firing
exactly once right when the streak reaches the threshold.

Mocks human_bot.agent.telegram_notify.send_message/send_photo directly
(rather than exercising the real HTTP layer, already covered by
tests/test_telegram_notify.py) and human_bot.agent._ACTION_DISPATCH's
per-action function (rather than driving a real Playwright browser) —
same "mock the one seam that matters" approach
tests/conftest.py's no_real_run_task fixture uses for admin.py's routes.
"""
from __future__ import annotations

import pytest

from human_bot import agent, daily_limits
from human_bot.actions import ActionResult
from human_bot.agent import TaskRequest
from human_bot.runtime_config import set_account_paused
from human_bot.safety import AnomalyDetected

ACCOUNT_ID = "tu_iizuki"  # code-level default account, always ACTIVE unless paused via runtime_config


class _FakeSession:
    def __init__(self, is_alive: bool = True):
        self.page = None
        self._is_alive = is_alive

    async def ensure_started(self) -> None:
        pass

    def is_alive(self) -> bool:
        return self._is_alive

    async def save_state(self) -> None:
        pass


@pytest.fixture
def telegram_calls(monkeypatch):
    """Replaces agent.telegram_notify.send_message/send_photo with fakes
    that record every call instead of touching the network — returns a
    single list shared by both, in call order, as (kind, text, silent)."""
    calls: list[tuple[str, str, bool]] = []

    async def fake_send_message(text, *, silent=False):
        calls.append(("message", text, silent))

    async def fake_send_photo(path, caption="", *, silent=False):
        calls.append(("photo", caption, silent))

    monkeypatch.setattr(agent.telegram_notify, "send_message", fake_send_message)
    monkeypatch.setattr(agent.telegram_notify, "send_photo", fake_send_photo)
    return calls


@pytest.fixture
def genuine_attempt_setup(monkeypatch):
    """Clears the 2 obstacles run_task() would otherwise hit before
    reaching the real action dispatch — the rate-limit gap check and the
    real Playwright session — so a test can drive run_task() all the way
    through to _notify_telegram_for_attempt() without a real browser."""
    monkeypatch.setattr(daily_limits, "can_proceed", lambda account, bucket, ignore_gap=False: (True, ""))
    monkeypatch.setattr(agent, "get_session", lambda account: _FakeSession())


def _set_action_result(monkeypatch, success: bool, message: str = "") -> None:
    async def fake_fn(page, req):
        return ActionResult(success=success, message=message)

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", fake_fn))


async def test_paused_account_sends_no_attempt_report(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, telegram_calls,
):
    set_account_paused(ACCOUNT_ID, True, reason="test")
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id=ACCOUNT_ID, target_url="x", content="c"))

    assert result.success is False
    assert "account_paused" in result.message
    assert telegram_calls == []


async def test_unsupported_action_sends_no_attempt_report(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, telegram_calls,
):
    result = await agent.run_task(TaskRequest(action="not_a_real_action", account_id=ACCOUNT_ID))

    assert result.success is False
    assert "unsupported_action" in result.message
    assert telegram_calls == []


async def test_rate_limited_sends_no_attempt_report(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, telegram_calls, monkeypatch,
):
    monkeypatch.setattr(daily_limits, "can_proceed", lambda account, bucket, ignore_gap=False: (False, "too_many_today"))
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id=ACCOUNT_ID, target_url="x", content="c"))

    assert result.success is False
    assert "rate_limited" in result.message
    assert telegram_calls == []


async def test_genuine_success_sends_exactly_one_silent_report(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, telegram_calls, genuine_attempt_setup, monkeypatch,
):
    _set_action_result(monkeypatch, success=True, message="posted ok")
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id=ACCOUNT_ID, target_url="https://x", content="c"))

    assert result.success is True
    assert len(telegram_calls) == 1
    kind, text, silent = telegram_calls[0]
    assert kind == "message"  # no screenshot_path in this fake session
    assert silent is True
    assert "✅" in text
    assert ACCOUNT_ID in text
    assert "post_to_group" in text


async def test_genuine_failure_sends_exactly_one_silent_report(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, telegram_calls, genuine_attempt_setup, monkeypatch,
):
    _set_action_result(monkeypatch, success=False, message="selector not found")
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id=ACCOUNT_ID, target_url="https://x", content="c"))

    assert result.success is False
    assert len(telegram_calls) == 1
    kind, text, silent = telegram_calls[0]
    assert silent is True
    assert "❌" in text
    assert "selector not found" in text


async def test_consecutive_failure_alert_fires_exactly_once_at_threshold(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, telegram_calls, genuine_attempt_setup, monkeypatch,
):
    _set_action_result(monkeypatch, success=False, message="boom")
    req = TaskRequest(action="post_to_group", account_id=ACCOUNT_ID, target_url="https://x", content="c")

    for _ in range(agent._CONSECUTIVE_FAILURE_ALERT_THRESHOLD - 1):
        await agent.run_task(req)
    loud_alerts_before = [c for c in telegram_calls if c[2] is False]
    assert loud_alerts_before == []

    await agent.run_task(req)  # this one hits the threshold exactly
    loud_alerts_at_threshold = [c for c in telegram_calls if c[2] is False]
    assert len(loud_alerts_at_threshold) == 1
    assert "LIÊN TIẾP" in loud_alerts_at_threshold[0][1]

    await agent.run_task(req)  # one failure past the threshold — must NOT re-fire
    loud_alerts_after = [c for c in telegram_calls if c[2] is False]
    assert len(loud_alerts_after) == 1


async def test_anomaly_detected_sends_only_the_pause_alert_not_a_redundant_attempt_report(
    isolated_runtime_config, isolated_accounts_dir, isolated_db, telegram_calls, genuine_attempt_setup, monkeypatch,
):
    """Regression test (2026-10-05 self-review): run_task()'s
    `except AnomalyDetected` branch used to fall through to the shared
    tail and ALSO send the normal per-attempt report (silent) — on top
    of its own loud "TẠM DỪNG" alert — for the exact same incident. Must
    send exactly 1 Telegram message total: the loud pause alert."""
    async def fake_fn(page, req):
        raise AnomalyDetected("checkpoint")

    monkeypatch.setitem(agent._ACTION_DISPATCH, "post_to_group", ("post", fake_fn))
    result = await agent.run_task(TaskRequest(action="post_to_group", account_id=ACCOUNT_ID, target_url="https://x", content="c"))

    assert result.success is False
    assert len(telegram_calls) == 1
    kind, text, silent = telegram_calls[0]
    assert kind == "message"
    assert silent is False
    assert "TẠM DỪNG" in text
