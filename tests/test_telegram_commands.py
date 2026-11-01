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
    ("/schedule", "schedule"), ("/SCHEDULE", "schedule"), ("/schedule@my_bot", "schedule"), ("/report hôm qua", "report"),
    ("  /help ", "help"), ("schedule", None), ("", None), (None, None), ("/", None), ("hello /schedule", None),
])
def test_parse_command(text, expected):
    assert telegram_commands.parse_command(text) == expected


@pytest.mark.parametrize("old,new", [
    ("lich", "schedule"), ("quahan", "overdue"), ("loi", "error"), ("choduyet", "review"),
    ("baocao", "report"), ("suckhoe", "health"), ("tamdung", "pause"), ("tieptuc", "resume"),
])
def test_the_old_vietnamese_names_still_work_but_are_not_advertised(old, new):
    assert telegram_commands.parse_command(f"/{old}") == new and telegram_commands.parse_command(f"/{old.upper()}@my_bot now") == new
    assert telegram_commands.is_known_command(new) and not telegram_commands.is_known_command(old)
    assert old not in [c for c, _d in telegram_commands.COMMANDS] and f"/{old}" not in telegram_commands.help_text()


def test_every_command_name_is_english():
    assert [c for c, _d in telegram_commands.COMMANDS] == [
        "schedule", "report", "health", "error", "overdue", "review", "pause", "resume", "help",
    ]


def test_help_is_grouped_explains_the_tip_and_the_time_zone():
    text = telegram_commands.help_text()
    assert "XEM NHANH" in text and "XỬ LÝ" in text and "TỰ ĐỘNG ĐĂNG" in text and "trả lời (reply)" in text and "JST" in text
    assert telegram_commands.help_text("Xin chào").startswith("Xin chào\n\nCác lệnh bạn có thể dùng:")


def test_help_text_lists_every_command():
    text = telegram_commands.help_text()
    for command, _desc in telegram_commands.COMMANDS:
        assert f"/{command}" in text


def test_command_names_are_valid_for_telegram():
    import re
    for command, _desc in telegram_commands.COMMANDS:
        assert re.fullmatch(r"[a-z0-9_]{1,32}", command)


# --- /schedule, /overdue -------------------------------------------------------------

def _add(store, when, account_id="acc-a", action="post_to_group"):
    task = store.ScheduledTask(
        task_id=store.new_task_id(when.isoformat()), action=action, account_id=account_id,
        scheduled_at=when.isoformat(), content="x", target_url="https://www.facebook.com/groups/1383875949915495/",
    )
    store.add(task)
    return task


def test_schedule_text_when_empty(isolated_schedule_dirs, isolated_runtime_config):
    text = telegram_commands.schedule_text()
    assert "không còn bài nào chờ đăng" in text and "Các ngày sau: 0 bài" in text


def test_schedule_text_splits_today_from_later_days(isolated_schedule_dirs, isolated_runtime_config):
    now = datetime.now(timezone.utc)
    end_of_day = daily_limits.business_day_start(now) + timedelta(days=1)
    _add(isolated_schedule_dirs, end_of_day - timedelta(minutes=30))
    _add(isolated_schedule_dirs, end_of_day + timedelta(hours=5))
    text = telegram_commands.schedule_text(now)
    assert "Bài sắp đăng hôm nay: 1 bài (giờ JST)" in text and "Các ngày sau: 1 bài" in text


def test_schedule_text_reads_in_plain_words(isolated_schedule_dirs, isolated_runtime_config, monkeypatch):
    now = datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc)                               # 14:00 JST on the 1st
    _add(isolated_schedule_dirs, now + timedelta(hours=6))                               # 20:00 JST, same day
    _add(isolated_schedule_dirs, now + timedelta(hours=11, minutes=30), action="comment_on_group_post")   # 01:30 JST on the 2nd, still this business day
    monkeypatch.setattr(telegram_commands, "target_label", lambda t: "Nhóm Thợ Hàn")
    text = telegram_commands.schedule_text(now)
    assert "• 20:00 · Đăng bài · acc-a\n   ↳ Nhóm Thợ Hàn" in text                       # no raw "post_to_group", no date for today
    assert "• 02/11 01:30 · Bình luận · acc-a" in text                                  # another calendar date is spelled out
    assert "post_to_group" not in text and "comment_on_group_post" not in text


def test_schedule_text_flags_tasks_whose_time_already_passed(isolated_schedule_dirs, isolated_runtime_config):
    now = datetime.now(timezone.utc)
    _add(isolated_schedule_dirs, now - timedelta(minutes=10))
    _add(isolated_schedule_dirs, now + timedelta(minutes=10))
    text = telegram_commands.schedule_text(now)
    assert "hôm nay: 2 bài" in text and "⏰ 1 bài đã đến giờ nhưng chưa chạy" in text and "/resume" in text   # says what to check
    assert text.count("• ⏰") == 1  # only the past-due line carries the marker


def test_schedule_text_caps_the_list(isolated_schedule_dirs, isolated_runtime_config):
    now = datetime.now(timezone.utc)
    start = daily_limits.business_day_start(now)
    for i in range(15):
        _add(isolated_schedule_dirs, start + timedelta(hours=2, minutes=i))
    text = telegram_commands.schedule_text(now)
    assert text.count("•") == telegram_commands._MAX_LINES
    assert "…và 5 bài khác" in text
    assert len(text) < 4096


def test_the_reason_a_task_was_parked_reads_in_plain_words(isolated_schedule_dirs):
    store = isolated_schedule_dirs
    reasons = {
        "Mất mạng: không kết nối được internet": "mất mạng",
        "Service đang tắt, bỏ qua khi khởi động": "service tắt",
        "Tài khoản a đang được tắt khi đến giờ đăng (x). Cần admin duyệt lại": "tài khoản bị tắt",
        "Tài khoản a đang tạm dừng khi đến giờ đăng (x). Cần admin duyệt lại": "tài khoản tạm dừng",
        "gì đó khác": "khác",
    }
    for reason, tag in reasons.items():
        task = _add(store, datetime.now(timezone.utc) - timedelta(days=2))
        store.mark_missed(task.task_id, reason)
        assert telegram_commands.missed_reason_tag(task.task_id) == tag


# --- /report and the daily summary ---------------------------------------------

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
    assert "Kết quả: ✅ 2 thành công · ❌ 1 thất bại" in report and "Đăng bài ✅2 ❌1" in report and "post_to_group" not in report
    assert "📊 Báo cáo hôm nay (từ 02:00 JST đến giờ)" in report and "Tình hình hiện tại:" in report
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
    assert telegram_commands.command_target("/schedule@other_bot") == "other_bot"
    assert telegram_commands.command_target("/schedule") is None
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


# --- readable replies (2026-11-01) ---------------------------------------------------------------------------------

class _Named:
    def __init__(self, name, page=""):
        self.display_name, self.page_name = name, page


def test_the_queue_footer_names_only_what_needs_attention_and_the_command_for_it(isolated_schedule_dirs, isolated_runtime_config, monkeypatch):
    from human_bot import telegram_failures
    monkeypatch.setattr(telegram_commands.schedule_store, "list_missed", lambda: [object(), object()])
    monkeypatch.setattr(telegram_commands.schedule_store, "list_needs_review", lambda: [object()])
    monkeypatch.setattr(telegram_failures, "open_failure_count", lambda: 3)
    footer = telegram_commands._queue_footer(datetime.now(timezone.utc))
    assert "Tình hình hiện tại:" in footer and "⚠️ Bài lỡ giờ: 2 → /overdue" in footer
    assert "❌ Lỗi chưa xử lý: 3 → /error" in footer and "🔍 Tin chờ duyệt: 1 → /review" in footer
    assert "Không có bài lỡ giờ" not in footer


def test_the_report_shows_idle_accounts_in_one_line_and_uses_display_names(isolated_schedule_dirs, isolated_runtime_config, monkeypatch):
    accounts = {"a1": _Named("Anna"), "a2": _Named("Bao"), "p1": _Named("Đơn Kỹ Sư", page="Đơn Kỹ Sư Nhật")}
    monkeypatch.setattr(telegram_commands, "get_all_accounts", lambda: accounts)
    monkeypatch.setattr(telegram_commands.db, "summary_stats", lambda aid, s, u: (
        {"total": 2, "succeeded": 1, "failed": 1} if aid == "a1" else {"total": 0, "succeeded": 0, "failed": 0}))
    monkeypatch.setattr(telegram_commands.db, "action_type_counts", lambda a, s, u: [
        {"action": "post_to_group", "success": 1, "total": 1}, {"action": "comment_on_group_post", "success": 0, "total": 1},
    ])
    text = telegram_commands.report_text(datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc))
    assert "• Anna: ✅ 1 · ❌ 1\n   ↳ Đăng bài ✅1 · Bình luận ❌1" in text
    assert "• Chưa có lượt nào: Bao, 📄 Đơn Kỹ Sư" in text and "a2" not in text
    monkeypatch.setattr(telegram_commands.db, "summary_stats", lambda aid, s, u: {"total": 0, "succeeded": 0, "failed": 0})
    assert telegram_commands._activity_block(datetime(2026, 11, 1, tzinfo=timezone.utc), None).startswith("Chưa có lượt đăng/bình luận nào.")


def test_action_and_account_names_fall_back_to_what_they_were_given(monkeypatch):
    assert telegram_commands.action_label("post_to_group") == "Đăng bài" and telegram_commands.action_label("brand_new") == "brand_new"
    assert telegram_commands.action_label(None) == "?"
    monkeypatch.setattr(telegram_commands, "get_all_accounts", lambda: {"p": _Named("Trang", page="Trang X"), "n": _Named("")})
    assert telegram_commands.account_name("p") == "📄 Trang" and telegram_commands.account_name("n") == "n" and telegram_commands.account_name("zz") == "zz"


def test_short_when_leaves_out_the_date_for_today_only():
    now = datetime(2026, 11, 1, 5, 0, tzinfo=timezone.utc)                          # 14:00 JST on the 1st
    assert telegram_commands.short_when("2026-11-01T11:00:00+00:00", now) == "20:00"
    assert telegram_commands.short_when("2026-11-01T16:30:00+00:00", now) == "02/11 01:30"   # 01:30 JST on the 2nd
    assert telegram_commands.short_when(None, now) == "?" and telegram_commands.short_when("garbage", now) == "?"


async def test_a_message_the_bot_does_not_understand_and_start_get_a_friendly_first_line(monkeypatch):
    import human_bot.service as svc
    assert svc._telegram_reply_for(None).startswith("🤔 Mình chưa hiểu tin nhắn này.\n\nCác lệnh bạn có thể dùng:")
    assert svc._telegram_reply_for("whatever").startswith("🤔 Mình chưa hiểu")
    assert svc._telegram_reply_for("start").startswith("👋 Xin chào!") and "/schedule" in svc._telegram_reply_for("start")
    assert svc._telegram_reply_for("help").startswith("Các lệnh bạn có thể dùng:")


def test_the_health_reply_has_a_heading_and_marks_pages(isolated_runtime_config, isolated_accounts_dir, isolated_db):
    import human_bot.service as svc
    text = svc._telegram_reply_for("health")
    assert text.startswith("🩺 Tình trạng các tài khoản\n\n") and "👤 " in text


def test_help_and_the_bot_menu_come_from_one_list():
    text = telegram_commands.help_text()
    for name, short, long, _group in telegram_commands._SPEC:
        assert f"/{name} — {long}" in text and (name, short) in telegram_commands.COMMANDS
    assert len(telegram_commands.COMMANDS) == len(telegram_commands._SPEC)
    assert "tính từ 02:00 đến 02:00 hôm sau" in text                                # read from the daily-cap definition, not typed twice
    assert telegram_commands._boundary_hhmm() == "02:00"


def test_static_replies(monkeypatch):
    assert telegram_commands.static_reply("help").startswith("Các lệnh bạn có thể dùng:")
    assert telegram_commands.static_reply("start").startswith("👋 Xin chào!")
    assert telegram_commands.static_reply(None).startswith("🤔") and telegram_commands.static_reply("nope").startswith("🤔")
    assert telegram_commands.static_reply("schedule") is None                          # live data — built elsewhere


def test_a_quiet_day_says_so_once(isolated_schedule_dirs, isolated_runtime_config, monkeypatch):
    monkeypatch.setattr(telegram_commands, "get_all_accounts", lambda: {"a1": _Named("Anna"), "a2": _Named("Bao")})
    monkeypatch.setattr(telegram_commands.db, "summary_stats", lambda aid, s, u: {"total": 0, "succeeded": 0, "failed": 0})
    block = telegram_commands._activity_block(datetime(2026, 11, 1, tzinfo=timezone.utc), None)
    assert block == "Chưa có lượt đăng/bình luận nào."                                  # no second line repeating the same fact


def test_naming_many_accounts_reads_the_registry_once(isolated_schedule_dirs, isolated_runtime_config, monkeypatch):
    calls = []

    def registry():
        calls.append(1)
        return {"acc-a": _Named("Anna")}

    monkeypatch.setattr(telegram_commands, "get_all_accounts", registry)
    now = datetime.now(timezone.utc)
    for i in range(4):
        _add(isolated_schedule_dirs, now + timedelta(minutes=10 + i))
    telegram_commands.schedule_text(now)
    assert len(calls) == 1
