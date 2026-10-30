"""Tests for /admin/post's "📋 Tin tuyển dụng" tab (2026-10-30): a job typed
by hand → one drafted post per auto-picked group, scheduled in one click."""
from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from pathlib import Path
from urllib.parse import parse_qs, urlparse

import pytest
from fastapi.testclient import TestClient

import human_bot.admin as admin_module
from human_bot import content_strategist, schedule_store
from human_bot.config import GroupRef, RateLimits
from tests.test_admin_post import _make_test_app


@dataclass
class _FakeAccount:
    account_id: str
    rate_limits: RateLimits
    action_log_path: Path
    display_name: str = "Acc A"
    sponsored_only: bool = False
    status: object = None


GROUPS = [GroupRef(name=f"Group {i}", url=f"https://facebook.com/groups/{i}") for i in range(4)]


@pytest.fixture
def client(isolated_runtime_config, isolated_schedule_dirs, tmp_path, monkeypatch):
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    acc = _FakeAccount("acc-a", RateLimits(posts_per_day=30, max_groups_per_post=3), tmp_path / "action_log.jsonl")
    acc.action_log_path.write_text("")
    monkeypatch.setattr(admin_module, "get_all_accounts", lambda: {"acc-a": acc})
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: GROUPS)
    monkeypatch.setattr(admin_module, "_last_scheduled_time_per_group", lambda aid: {})
    return TestClient(_make_test_app(), follow_redirects=False)


FORM = {
    "account_id": "acc-a", "title": "Vận hành máy", "company": "Công ty ABC", "location": "Ibaraki",
    "visa": "tokutei", "jlpt": "N4", "salary_min": "22", "salary_max": "28", "salary_period": "month",
    "benefits": "Trợ cấp vợ con 2m8, trợ cấp nhà, tăng ca 30h/tháng", "group_count": "3",
}


def _params(resp):
    return parse_qs(urlparse(resp.headers["location"]).query)


def test_job_tab_renders_with_both_buttons(client):
    resp = client.get("/admin/post?tab=job")
    assert resp.status_code == 200
    assert "Tạo bằng AI" in resp.text and "Tạo bằng template" in resp.text and "Phúc lợi" in resp.text


def test_template_mode_schedules_one_post_per_picked_group(client):
    resp = client.post("/admin/post/schedule-job", data={**FORM, "mode": "template"})
    assert resp.status_code == 303 and "posted" in _params(resp)
    tasks = schedule_store.list_pending()
    assert len(tasks) == 3
    assert len({t.target_url for t in tasks}) == 3  # three different groups
    assert all(t.action == "post_to_group" and t.account_id == "acc-a" for t in tasks)
    assert all(t.ai_redraft is False and t.source_kind == "job" for t in tasks)
    assert len({t.source_id for t in tasks}) == 1 and tasks[0].source_id.startswith("manual-")
    first = tasks[0].content
    assert "Vận hành máy" in first and "Ibaraki" in first and "Công ty ABC" in first
    assert "Trợ cấp vợ con 2m8" in first and "tăng ca 30h/tháng" in first  # the benefits survive verbatim
    assert "22" in first and "28" in first  # 22-28 man, converted from yên and back
    times = sorted(datetime.fromisoformat(t.scheduled_at) for t in tasks)
    assert times[0] < times[1] < times[2]  # spaced by the account's gap, not all at once


def test_salary_typed_in_man_is_stored_as_yen_and_hourly_is_not_scaled(client):
    client.post("/admin/post/schedule-job", data={**FORM, "mode": "template", "group_count": "1"})
    assert schedule_store.list_pending()[0].job_data["attributes"]["salary"]["min"] == 220000
    for t in schedule_store.list_pending():
        schedule_store.cancel(t.task_id)
    client.post("/admin/post/schedule-job", data={**FORM, "mode": "template", "group_count": "1",
                                                  "salary_min": "1400", "salary_max": "", "salary_period": "hour"})
    assert schedule_store.list_pending()[0].job_data["attributes"]["salary"]["min"] == 1400


def test_ai_mode_uses_the_ai_drafts_and_marks_them_as_ai(client, monkeypatch):
    monkeypatch.setattr(content_strategist, "ai_provider_configured", lambda: True)
    seen = {}

    async def fake_ai(job, groups):
        seen["job"], seen["n"] = job, len(groups)
        return [f"AI bài {i}" for i in range(len(groups))]

    monkeypatch.setattr(content_strategist, "_draft_via_ai", fake_ai)  # draft_ai_variants() delegates to it
    resp = client.post("/admin/post/schedule-job", data={**FORM, "mode": "ai"})
    assert "AI" in _params(resp)["posted"][0] and "template" not in _params(resp)["posted"][0]
    assert sorted(t.content for t in schedule_store.list_pending()) == ["AI bài 0", "AI bài 1", "AI bài 2"]
    assert seen["n"] == 3 and seen["job"]["attributes"]["benefits"].startswith("Trợ cấp")


def test_ai_mode_without_a_key_falls_back_to_template_and_says_so(client, monkeypatch):
    monkeypatch.setattr(content_strategist, "ai_provider_configured", lambda: False)
    resp = client.post("/admin/post/schedule-job", data={**FORM, "mode": "ai"})
    assert "AI chưa có key" in _params(resp)["posted"][0]
    assert len(schedule_store.list_pending()) == 3


def test_ai_failure_falls_back_to_template_and_says_so(client, monkeypatch):
    monkeypatch.setattr(content_strategist, "ai_provider_configured", lambda: True)

    async def boom(job, groups):
        raise RuntimeError("down")

    monkeypatch.setattr(content_strategist, "_draft_via_ai", boom)
    resp = client.post("/admin/post/schedule-job", data={**FORM, "mode": "ai"})
    assert "AI soạn lỗi" in _params(resp)["posted"][0]
    assert len(schedule_store.list_pending()) == 3


@pytest.mark.parametrize("override,expected", [
    ({"title": "  "}, "Tiêu đề"),
    ({"mode": ""}, "AI hay template"),
    ({"visa": "bogus"}, "visa"),
    ({"jlpt": "N9"}, "JLPT"),
    ({"salary_min": "30", "salary_max": "20"}, "không được lớn hơn"),
    ({"salary_min": "abc"}, "Số không hợp lệ"),
    ({"salary_min": "-5"}, "Số không hợp lệ"),
    ({"account_id": "nope"}, "tài khoản"),
])
def test_invalid_input_schedules_nothing_and_explains(client, override, expected):
    data = {**FORM, "mode": "template", **override}
    resp = client.post("/admin/post/schedule-job", data=data)
    assert resp.status_code == 303
    assert expected.lower() in _params(resp)["error"][0].lower()
    assert schedule_store.list_pending() == []


def test_only_the_title_is_required_and_sentinel_text_is_cleaned(client):
    resp = client.post("/admin/post/schedule-job", data={
        "account_id": "acc-a", "title": "Thợ hàn", "company": "unknown", "mode": "template", "group_count": "1",
    })
    assert "posted" in _params(resp)
    [task] = schedule_store.list_pending()
    assert "unknown" not in task.content.lower() and "Thợ hàn" in task.content
    assert "Thông tin visa/lương" in task.content  # missing visa + salary → says so and invites a message


def test_group_count_is_capped_by_the_accounts_max_groups_per_post(client):
    """The account allows 3 groups per job (it has 4): a form/POST asking
    for more cannot lift the same limit the side-B pipeline enforces."""
    client.post("/admin/post/schedule-job", data={**FORM, "mode": "template", "group_count": "99"})
    assert len(schedule_store.list_pending()) == 3


def test_hourly_salary_prints_as_a_whole_number_not_a_float(client):
    """Code review 2026-10-30: 1400 used to be stored as 1400.0 and posted as "1400.0 JPY/giờ"."""
    client.post("/admin/post/schedule-job", data={**FORM, "mode": "template", "group_count": "1",
                                                  "salary_min": "1400", "salary_max": "", "salary_period": "hour"})
    [task] = schedule_store.list_pending()
    assert "1400 " in task.content and "1400.0" not in task.content
    assert isinstance(task.job_data["attributes"]["salary"]["min"], int)


def test_comma_is_thousands_for_hourly_yen_but_decimal_for_man(client):
    client.post("/admin/post/schedule-job", data={**FORM, "mode": "template", "group_count": "1",
                                                  "salary_min": "1,400", "salary_max": "", "salary_period": "hour"})
    assert schedule_store.list_pending()[0].job_data["attributes"]["salary"]["min"] == 1400
    for t in schedule_store.list_pending():
        schedule_store.cancel(t.task_id)
    client.post("/admin/post/schedule-job", data={**FORM, "mode": "template", "group_count": "1",
                                                  "salary_min": "22,5", "salary_max": "", "salary_period": "month"})
    assert schedule_store.list_pending()[0].job_data["attributes"]["salary"]["min"] == 225000


def test_submitting_the_same_job_twice_does_not_double_schedule(client):
    first = client.post("/admin/post/schedule-job", data={**FORM, "mode": "template"})
    assert "posted" in _params(first)
    second = client.post("/admin/post/schedule-job", data={**FORM, "mode": "ai"})
    assert "đã được lên lịch rồi" in _params(second)["error"][0]
    assert len(schedule_store.list_pending()) == 3  # still just the first batch
    different = client.post("/admin/post/schedule-job", data={**FORM, "title": "Thợ hàn", "mode": "template"})
    assert "posted" in _params(different)


def test_a_sentinel_title_is_rejected_after_cleaning(client):
    resp = client.post("/admin/post/schedule-job", data={**FORM, "title": "unknown", "mode": "template"})
    assert "Tiêu đề" in _params(resp)["error"][0]
    assert schedule_store.list_pending() == []


def test_a_failure_midway_undoes_the_partial_batch(client, monkeypatch):
    real = admin_module._suggest_reschedule_at
    calls = {"n": 0}

    def flaky(account, action, exclude_task_id=None):
        calls["n"] += 1
        if calls["n"] == 2:
            raise RuntimeError("boom")
        return real(account, action, exclude_task_id)

    monkeypatch.setattr(admin_module, "_suggest_reschedule_at", flaky)
    resp = client.post("/admin/post/schedule-job", data={**FORM, "mode": "template"})
    assert "hoàn tác" in _params(resp)["error"][0]
    assert schedule_store.list_pending() == []  # nothing left behind to be double-posted by a retry


def test_retrying_a_manual_job_from_reports_keeps_the_admins_text(isolated_db, client):
    from human_bot import db
    db.log_action(account_id="acc-a", action="post_to_group", success=False, content="my text",
                  target_url="https://facebook.com/groups/1", source_kind="job", source_id="manual-ab12cd34",
                  job_data={"title": "t", "attributes": {}})
    db.log_action(account_id="acc-a", action="post_to_group", success=False, content="side b text",
                  target_url="https://facebook.com/groups/2", source_kind="job", source_id="777",
                  job_data={"title": "t", "attributes": {}})
    ids = {}
    import sqlite3
    conn = sqlite3.connect(db.DB_PATH)
    for log_id, source_id in conn.execute("SELECT id, source_id FROM action_log"):
        ids[source_id] = log_id
    conn.close()
    for source_id in ("manual-ab12cd34", "777"):
        client.post("/admin/reports/reschedule-confirm", data={"log_id": str(ids[source_id]), "scheduled_at": "2026-12-01T00:00:00+00:00"})
    by_source = {t.source_id: t for t in schedule_store.list_pending()}
    assert by_source["manual-ab12cd34"].ai_redraft is False
    assert by_source["777"].ai_redraft is True


def test_account_with_no_groups_gets_an_error(client, monkeypatch):
    monkeypatch.setattr(admin_module, "get_joined_groups", lambda aid: [])
    resp = client.post("/admin/post/schedule-job", data={**FORM, "mode": "template"})
    assert "chưa tham gia nhóm" in _params(resp)["error"][0]


async def test_fire_time_does_not_redraft_a_manual_job_with_ai(isolated_schedule_dirs, isolated_runtime_config, monkeypatch):
    """ai_redraft=False must keep fire_due_tasks() from replacing the text
    the admin chose; an ordinary side-B job task (default True) still gets re-drafted."""
    from human_bot import data_sync
    from human_bot.runtime_config import save_data_sync_overrides
    from human_bot.scheduling_config import SchedulingConfig

    save_data_sync_overrides({"job_post_ai_enabled": True})
    redrafted = []

    async def fake_draft(job_data, content, group_name, ai_enabled=True):
        redrafted.append(content)
        return "AI REDRAFT"

    sent = []

    async def fake_run_task(request):
        sent.append(request.content)
        from human_bot.agent import TaskResult
        return TaskResult(success=True, message="ok", screenshot_path=None, timestamp="t")

    async def online(*a, **k):
        return True

    from human_bot import network_check
    monkeypatch.setattr(network_check, "wait_for_internet", online)
    monkeypatch.setattr(data_sync.content_strategist, "draft_single_post", fake_draft)
    monkeypatch.setattr("human_bot.agent.run_task", fake_run_task)
    monkeypatch.setattr(data_sync, "get_account", lambda aid: None)
    when = datetime.now(timezone.utc) - timedelta(minutes=1)
    for name, redraft in (("manual text", False), ("side-b text", True)):
        schedule_store.add(schedule_store.ScheduledTask(
            task_id=schedule_store.new_task_id(when.isoformat()), action="post_to_group", account_id="acc-a",
            scheduled_at=when.isoformat(), content=name, target_url="https://facebook.com/groups/1",
            source_kind="job", source_id="x", job_data={"title": "t", "attributes": {}}, ai_redraft=redraft,
        ))
    await data_sync.fire_due_tasks(SchedulingConfig(auto_fire_enabled=True))
    assert sorted(sent) == ["AI REDRAFT", "manual text"]
    assert redrafted == ["side-b text"]
