"""Tests for human_bot/telegram_alerts.py (2026-10-13, Telegram Vòng 1):
the outage record that survives the outage it reports, the one-combined-
message flush, and the startup-sweep / needs-review notices."""
from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from human_bot import data_sync, network_check, telegram_alerts, telegram_notify
from human_bot.scheduling_config import SchedulingConfig


@pytest.fixture(autouse=True)
def _isolated_state(tmp_path, monkeypatch):
    monkeypatch.setattr(telegram_alerts, "STATE_PATH", tmp_path / "_telegram_state.json")


class _Task:
    def __init__(self, i=0, account_id="acc-a", action="comment_on_group_post"):
        self.account_id, self.action = account_id, action
        self.scheduled_at = (datetime.now(timezone.utc) - timedelta(minutes=i)).isoformat()


def _wire(monkeypatch, *, online=True, send_ok=True, configured=True):
    sent: list[str] = []

    async def is_online():
        return online

    async def send_checked(text, *, silent=False):
        sent.append(text)
        return send_ok

    monkeypatch.setattr(network_check, "is_online", is_online)
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: configured)
    monkeypatch.setattr(telegram_notify, "send_message_checked", send_checked)
    return sent


def test_record_outage_merges_into_one_outage_and_caps_stored_items():
    telegram_alerts.record_outage([_Task(1), _Task(2)])
    since = telegram_alerts.get_state()["outage"]["since"]
    telegram_alerts.record_outage([_Task(i) for i in range(30)])
    outage = telegram_alerts.get_state()["outage"]
    assert outage["count"] == 32
    assert outage["since"] == since
    assert len(outage["items"]) == telegram_alerts._MAX_STORED_ITEMS


def test_record_outage_with_no_tasks_records_nothing():
    telegram_alerts.record_outage([])
    assert "outage" not in telegram_alerts.get_state()


def test_format_outage_text_lists_a_few_and_counts_the_rest():
    telegram_alerts.record_outage([_Task(i) for i in range(8)])
    outage = telegram_alerts.get_state()["outage"]
    text = telegram_alerts.format_outage_text(outage, datetime.now(timezone.utc) + timedelta(minutes=45))
    assert "8 bài" in text and "…và 3 bài khác" in text and "có thể đã mất từ trước đó" in text
    assert text.count("•") == 5


async def test_flush_does_nothing_and_sends_nothing_when_idle(monkeypatch):
    sent = _wire(monkeypatch)
    assert await telegram_alerts.flush_pending() is False
    assert sent == []


async def test_flush_keeps_the_outage_while_still_offline(monkeypatch):
    sent = _wire(monkeypatch, online=False)
    telegram_alerts.record_outage([_Task()])
    assert await telegram_alerts.flush_pending() is False
    assert sent == [] and "outage" in telegram_alerts.get_state()


async def test_flush_sends_one_combined_message_once_online_then_clears(monkeypatch):
    sent = _wire(monkeypatch)
    telegram_alerts.record_outage([_Task(1), _Task(2), _Task(3)])
    assert await telegram_alerts.flush_pending() is True
    assert len(sent) == 1 and "3 bài" in sent[0]
    assert "outage" not in telegram_alerts.get_state()
    assert await telegram_alerts.flush_pending() is False
    assert len(sent) == 1


async def test_flush_keeps_the_outage_when_telegram_send_fails(monkeypatch):
    sent = _wire(monkeypatch, send_ok=False)
    telegram_alerts.record_outage([_Task()])
    assert await telegram_alerts.flush_pending() is False
    assert len(sent) == 1 and "outage" in telegram_alerts.get_state()


async def test_flush_drops_pending_when_telegram_is_muted_instead_of_retrying_forever(monkeypatch):
    sent = _wire(monkeypatch, configured=False)
    telegram_alerts.record_outage([_Task()])
    telegram_alerts.queue_notice("x")
    await telegram_alerts.flush_pending()
    state = telegram_alerts.get_state()
    assert sent == [] and "outage" not in state and state["notices"] == []


async def test_startup_sweep_notice_is_sent_or_queued_for_retry(monkeypatch):
    items = [{"account_id": "acc-a", "action": "post_to_group", "scheduled_at": datetime.now(timezone.utc).isoformat()}]
    sent = _wire(monkeypatch, send_ok=False)
    await telegram_alerts.notify_startup_sweep(items)
    assert len(sent) == 1 and len(telegram_alerts.get_state()["notices"]) == 1

    sent_ok = _wire(monkeypatch, send_ok=True)
    assert await telegram_alerts.flush_pending() is True  # the queued notice goes out later
    assert len(sent_ok) == 1 and telegram_alerts.get_state()["notices"] == []


async def test_startup_sweep_notice_skipped_when_nothing_swept(monkeypatch):
    sent = _wire(monkeypatch)
    await telegram_alerts.notify_startup_sweep([])
    assert sent == []


async def test_needs_review_notice_only_when_there_is_something(monkeypatch):
    sent = []

    async def send_message(text, *, silent=False):
        sent.append(text)

    monkeypatch.setattr(telegram_notify, "send_message", send_message)
    await telegram_alerts.notify_needs_review(0)
    await telegram_alerts.notify_needs_review(3)
    assert len(sent) == 1 and "3 job" in sent[0]


async def test_fire_due_tasks_offline_records_an_outage_for_the_later_telegram_message(isolated_schedule_dirs, monkeypatch):
    from human_bot.data_sync import fire_due_tasks

    async def offline(*a, **k):
        return False

    monkeypatch.setattr(network_check, "wait_for_internet", offline)
    store = isolated_schedule_dirs
    when = datetime.now(timezone.utc) - timedelta(minutes=3)
    store.add(store.ScheduledTask(
        task_id=store.new_task_id(when.isoformat()), action="comment_on_group_post", account_id="acc-a",
        scheduled_at=when.isoformat(), content="x", target_url="https://facebook.com/groups/1",
    ))
    await fire_due_tasks(SchedulingConfig(auto_fire_enabled=True))
    outage = telegram_alerts.get_state()["outage"]
    assert outage["count"] == 1 and outage["items"][0]["account_id"] == "acc-a"


def test_sweep_overdue_on_startup_returns_the_swept_items(isolated_schedule_dirs):
    store = isolated_schedule_dirs
    when = datetime.now(timezone.utc) - timedelta(hours=1)
    store.add(store.ScheduledTask(
        task_id=store.new_task_id(when.isoformat()), action="post_to_group", account_id="acc-a",
        scheduled_at=when.isoformat(), content="x", target_url="https://facebook.com/groups/1",
    ))
    result = data_sync.sweep_overdue_on_startup()
    assert result["swept"] == 1 and result["items"][0]["action"] == "post_to_group"


async def test_flush_does_not_overwrite_state_written_while_it_was_awaiting(monkeypatch):
    """Code review 2026-10-13: flush_pending() awaits network/Telegram calls;
    a marker written meanwhile (daily summary) or a notice queued meanwhile
    must survive its save."""
    telegram_alerts.record_outage([_Task()])

    async def is_online():
        return True

    async def send_checked(text, *, silent=False):
        telegram_alerts.update_state(last_summary_date="2026-10-13")  # another loop writes mid-send
        telegram_alerts.queue_notice("queued meanwhile")
        return True

    monkeypatch.setattr(network_check, "is_online", is_online)
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(telegram_notify, "send_message_checked", send_checked)
    await telegram_alerts.flush_pending()
    state = telegram_alerts.get_state()
    assert state.get("last_summary_date") == "2026-10-13"
    assert "outage" not in state


async def test_spawn_keeps_a_strong_reference_and_swallows_errors():
    ran = []

    async def ok():
        ran.append(1)

    async def boom():
        raise RuntimeError("boom")

    t1 = telegram_alerts.spawn(ok())
    assert t1 in telegram_alerts._background
    await t1
    await telegram_alerts.spawn(boom())  # must not raise
    assert ran == [1] and not telegram_alerts._background


async def test_flush_keeps_tasks_recorded_while_the_send_was_in_flight(monkeypatch):
    """Code review round 2: record_outage() merging into the record during
    the send must not be deleted unsent by the post-send cleanup."""
    telegram_alerts.record_outage([_Task(1), _Task(2)])

    async def is_online():
        return True

    async def send_checked(text, *, silent=False):
        telegram_alerts.record_outage([_Task(3)])  # another blip while sending
        return True

    monkeypatch.setattr(network_check, "is_online", is_online)
    monkeypatch.setattr(telegram_notify, "is_configured", lambda: True)
    monkeypatch.setattr(telegram_notify, "send_message_checked", send_checked)
    await telegram_alerts.flush_pending()
    outage = telegram_alerts.get_state()["outage"]
    assert outage["count"] == 1 and len(outage["items"]) == 1


def test_state_save_failure_never_raises_into_the_scheduler(tmp_path, monkeypatch):
    """Audit 2026-10-13: record_outage() runs inside fire_due_tasks(); an
    unwritable state location must not take that down."""
    blocker = tmp_path / "not_a_dir"
    blocker.write_text("x")
    monkeypatch.setattr(telegram_alerts, "STATE_PATH", blocker / "_telegram_state.json")
    telegram_alerts.record_outage([_Task()])  # must not raise


def test_tests_never_touch_the_real_state_file():
    """Audit 2026-10-13: a test once wrote a FAKE outage into the real
    data_sync_cache/_telegram_state.json (the real service would have
    announced it to real recipients). conftest now redirects it per test."""
    real = telegram_alerts.Path(telegram_alerts.__file__).resolve().parent.parent / "data_sync_cache" / "_telegram_state.json"
    assert telegram_alerts.STATE_PATH != real
