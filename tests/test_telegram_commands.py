"""Tests for human_bot/telegram_commands.py, the daily-summary sender in
human_bot/service.py, and db's new `until` bound (2026-10-13, Telegram
Vòng 1)."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

import human_bot.service as svc
from human_bot import daily_limits, db, telegram_alerts, telegram_commands, telegram_notify
from human_bot.runtime_config import save_telegram_overrides


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(telegram_alerts, "STATE_PATH", tmp_path / "_telegram_state.json")


# --- parse_command -------------------------------------------------------------

@pytest.mark.parametrize("text,expected", [
    ("/lich", "lich"), ("/LICH", "lich"), ("/lich@my_bot", "lich"), ("/baocao hôm qua", "baocao"),
    ("  /help ", "help"), ("lich", None), ("", None), (None, None), ("/", None), ("hello /lich", None),
])
def test_parse_command(text, expected):
    assert telegram_commands.parse_command(text) == expected


def test_help_text_lists_every_command():
    text = telegram_commands.help_text()
    for command, _desc in telegram_commands.COMMANDS:
        assert f"/{command}" in text


def test_command_names_are_valid_for_telegram():
    import re
    for command, _desc in telegram_commands.COMMANDS:
        assert re.fullmatch(r"[a-z0-9_]{1,32}", command)


# --- /lich, /quahan -------------------------------------------------------------

def _add(store, when, account_id="acc-a", action="post_to_group"):
    task = store.ScheduledTask(
        task_id=store.new_task_id(when.isoformat()), action=action, account_id=account_id,
        scheduled_at=when.isoformat(), content="x", target_url="https://www.facebook.com/groups/1383875949915495/",
    )
    store.add(task)
    return task


def test_schedule_text_when_empty(isolated_schedule_dirs, isolated_runtime_config):
    assert "không còn task" in telegram_commands.schedule_text()


def test_schedule_text_splits_today_from_later_days(isolated_schedule_dirs, isolated_runtime_config):
    now = datetime.now(timezone.utc)
    end_of_day = daily_limits.business_day_start(now) + timedelta(days=1)
    _add(isolated_schedule_dirs, end_of_day - timedelta(minutes=30))
    _add(isolated_schedule_dirs, end_of_day + timedelta(hours=5))
    text = telegram_commands.schedule_text(now)
    assert "hôm nay (1)" in text and "Các ngày sau: 1 task" in text


def test_schedule_text_flags_tasks_whose_time_already_passed(isolated_schedule_dirs, isolated_runtime_config):
    now = datetime.now(timezone.utc)
    _add(isolated_schedule_dirs, now - timedelta(minutes=10))
    _add(isolated_schedule_dirs, now + timedelta(minutes=10))
    text = telegram_commands.schedule_text(now)
    assert "hôm nay (2)" in text and "⏰ 1 task đã đến giờ nhưng chưa chạy" in text
    assert text.count("• ⏰") == 1  # only the past-due line carries the marker


def test_schedule_text_caps_the_list(isolated_schedule_dirs, isolated_runtime_config):
    now = datetime.now(timezone.utc)
    start = daily_limits.business_day_start(now)
    for i in range(15):
        _add(isolated_schedule_dirs, start + timedelta(hours=2, minutes=i))
    text = telegram_commands.schedule_text(now)
    assert text.count("•") == telegram_commands._MAX_LINES
    assert "…và 5 task khác" in text
    assert len(text) < 4096


def test_missed_text_when_empty(isolated_schedule_dirs):
    assert "Không có task nào quá hạn" in telegram_commands.missed_text()


def test_missed_text_shows_reason_tag_and_days(isolated_schedule_dirs):
    store = isolated_schedule_dirs
    task = _add(store, datetime.now(timezone.utc) - timedelta(days=2))
    store.mark_missed(task.task_id, "Mất mạng: không kết nối được internet")
    text = telegram_commands.missed_text()
    assert "1 task quá hạn" in text and "mất mạng" in text and "quá 2 ngày" in text


# --- /baocao and the daily summary ---------------------------------------------

class _Acc:
    pass


def test_report_and_summary_use_the_right_windows(isolated_schedule_dirs, isolated_runtime_config, monkeypatch):
    calls = []

    def fake_stats(account_id, since, until):
        calls.append((since, until))
        return {"total": 3, "succeeded": 2, "failed": 1, "success_rate": 66.7, "active_accounts": 1}

    monkeypatch.setattr(telegram_commands, "get_all_accounts", lambda: {"acc-a": _Acc()})
    monkeypatch.setattr(telegram_commands.db, "summary_stats", fake_stats)
    monkeypatch.setattr(telegram_commands.db, "action_type_counts", lambda a, s, u: [
        {"action": "post_to_group", "success": 1, "total": 2}, {"action": "post_to_group", "success": 0, "total": 1},
    ])
    now = datetime(2026, 10, 14, 21, 0, tzinfo=timezone.utc)  # 06:00 JST on the 15th
    today_start = daily_limits.business_day_start(now)

    report = telegram_commands.report_text(now)
    assert "✅ 2 · ❌ 1" in report and "post_to_group 2✅/1❌" in report
    assert calls[-1] == (today_start.isoformat(), None)

    summary = telegram_commands.daily_summary_text(now)
    assert "Tóm tắt ngày 14/10" in summary
    assert calls[-1] == ((today_start - timedelta(days=1)).isoformat(), today_start.isoformat())


def test_db_until_is_an_exclusive_upper_bound(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.ensure_schema()
    base = datetime(2026, 10, 14, 0, 0, tzinfo=timezone.utc)
    for i, hours in enumerate((1, 2, 3)):
        db.log_action(account_id="acc-a", action="post_to_group", success=True, created_at=(base + timedelta(hours=hours)).isoformat())
    stats = db.summary_stats("acc-a", since=base.isoformat(), until=(base + timedelta(hours=3)).isoformat())
    assert stats["total"] == 2  # the row exactly at `until` is excluded
    assert db.summary_stats("acc-a", since=base.isoformat())["total"] == 3  # no `until` = unchanged behavior


# --- daily summary sender -------------------------------------------------------

def _wire_summary(monkeypatch, *, send_ok=True):
    sent = []

    async def send_checked(text, *, silent=False):
        sent.append(text)
        return send_ok

    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(telegram_notify, "send_message_checked", send_checked)
    monkeypatch.setattr(svc.telegram_commands, "daily_summary_text", lambda now, anchor=None: "SUMMARY")
    return sent


def _jst(hour, minute=0, day=15):
    return datetime(2026, 10, day, hour, minute, tzinfo=timezone.utc) - timedelta(hours=9)


async def test_summary_sent_once_inside_the_window(monkeypatch, isolated_runtime_config):
    sent = _wire_summary(monkeypatch)
    assert await svc._maybe_send_daily_summary(_jst(6, 5)) is True
    assert await svc._maybe_send_daily_summary(_jst(6, 40)) is False  # same day, already sent
    assert sent == ["SUMMARY"]
    assert await svc._maybe_send_daily_summary(_jst(6, 5, day=16)) is True  # next day sends again


async def test_summary_not_sent_before_the_hour_or_after_the_catchup_window(monkeypatch, isolated_runtime_config):
    sent = _wire_summary(monkeypatch)
    assert await svc._maybe_send_daily_summary(_jst(5, 59)) is False
    assert await svc._maybe_send_daily_summary(_jst(8, 0)) is False  # 2h catch-up window is over
    assert await svc._maybe_send_daily_summary(_jst(7, 59)) is True  # service back late, still within
    assert len(sent) == 1


async def test_summary_failed_send_is_retried_and_not_marked_sent(monkeypatch, isolated_runtime_config):
    sent = _wire_summary(monkeypatch, send_ok=False)
    assert await svc._maybe_send_daily_summary(_jst(6, 5)) is False
    assert "last_summary_date" not in telegram_alerts.get_state()
    sent = _wire_summary(monkeypatch, send_ok=True)
    assert await svc._maybe_send_daily_summary(_jst(6, 10)) is True


async def test_summary_respects_the_toggle_and_configured_hour(monkeypatch, isolated_runtime_config):
    sent = _wire_summary(monkeypatch)
    save_telegram_overrides({"enabled": True, "daily_summary_enabled": False, "daily_summary_hour_jst": 6})
    assert await svc._maybe_send_daily_summary(_jst(6, 5)) is False
    save_telegram_overrides({"enabled": True, "daily_summary_enabled": True, "daily_summary_hour_jst": 7.0})  # float, like the 2026-10-06 bug
    assert await svc._maybe_send_daily_summary(_jst(6, 5)) is False
    assert await svc._maybe_send_daily_summary(_jst(7, 5)) is True
    assert len(sent) == 1


async def test_summary_hours_below_2_are_clamped_so_it_never_summarizes_an_unfinished_day(monkeypatch, isolated_runtime_config):
    sent = _wire_summary(monkeypatch)
    save_telegram_overrides({"enabled": True, "daily_summary_enabled": True, "daily_summary_hour_jst": 0})
    assert await svc._maybe_send_daily_summary(_jst(0, 30)) is False  # 00:30 — not the slot any more
    assert await svc._maybe_send_daily_summary(_jst(2, 10)) is True  # clamped to 02:00
    assert len(sent) == 1


async def test_summary_catchup_after_midnight_for_a_late_evening_hour(monkeypatch, isolated_runtime_config):
    """hour=23 with a 2h catch-up window: a service back at 00:30 must still
    send yesterday's 23:00 slot (and only once)."""
    captured = []
    sent = _wire_summary(monkeypatch)
    monkeypatch.setattr(svc.telegram_commands, "daily_summary_text", lambda now, anchor=None: captured.append(anchor) or "SUMMARY")
    save_telegram_overrides({"enabled": True, "daily_summary_enabled": True, "daily_summary_hour_jst": 23})
    assert await svc._maybe_send_daily_summary(_jst(0, 30, day=16)) is True
    assert await svc._maybe_send_daily_summary(_jst(0, 40, day=16)) is False
    assert captured == [_jst(23, 0, day=15)]  # anchored on the 23:00 slot, not on "now"
    assert len(sent) == 1


def test_command_target_extracts_the_bot_suffix():
    assert telegram_commands.command_target("/lich@other_bot") == "other_bot"
    assert telegram_commands.command_target("/lich") is None
    assert telegram_commands.command_target("hello") is None


def test_register_commands_only_calls_telegram_until_it_succeeds(monkeypatch):
    calls = []

    async def fake_set(commands):
        calls.append(1)
        return len(calls) >= 2  # first attempt fails

    monkeypatch.setattr(svc, "_telegram_commands_registered", False)
    monkeypatch.setattr(telegram_notify, "set_my_commands", fake_set)
    import asyncio
    for _ in range(4):
        asyncio.run(svc._register_telegram_commands())
    assert len(calls) == 2  # retried once after the failure, then never again


async def test_spawn_flush_is_background_and_single_in_flight(monkeypatch):
    """Code review 2026-10-13: the fire loop must not wait on Telegram."""
    import asyncio
    started = []
    release = asyncio.Event()

    async def slow_flush():
        started.append(1)
        await release.wait()

    monkeypatch.setattr(svc.telegram_alerts, "flush_pending", slow_flush)
    monkeypatch.setattr(svc, "_telegram_flush_task", None)
    svc._spawn_telegram_flush()   # returns immediately although the flush is still waiting
    await asyncio.sleep(0)
    svc._spawn_telegram_flush()   # one already in flight -> no second one
    await asyncio.sleep(0)
    assert started == [1]
    release.set()
    await svc._telegram_flush_task


def test_notify_config_changed_is_safe_from_a_worker_thread(monkeypatch):
    """Code review 2026-10-16: asyncio.Event.set() is not thread-safe; the
    Telegram pause/resume button saves config from asyncio.to_thread()."""
    import asyncio
    import threading
    from human_bot import runtime_config

    async def scenario():
        loop = asyncio.get_running_loop()
        runtime_config.set_notify_loop(loop)
        # A private Event: the module-level one binds to the first loop that
        # awaits it, which must not be this throwaway loop.
        event = asyncio.Event()
        monkeypatch.setattr(runtime_config, "_config_changed_event", event)
        waiter = asyncio.create_task(event.wait())
        await asyncio.sleep(0)
        t = threading.Thread(target=runtime_config.notify_config_changed)
        t.start()
        await asyncio.wait_for(waiter, timeout=2)  # woken via call_soon_threadsafe
        t.join()

    try:
        asyncio.run(scenario())
    finally:
        runtime_config.set_notify_loop(None)
