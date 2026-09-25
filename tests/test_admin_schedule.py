"""
HTTP-level tests for /admin/schedule (2026-09-25 test-coverage plan,
Phase 1) — this tab has the highest churn of any admin.py section and
already produced 2 real bugs this project shipped without catching
automatically:

1. The "Quá hạn" filter dropdown disappearing entirely once its filter
   matched zero tasks (`_missed_tasks_section_html()` used to `return`
   early with a lone empty-state div, wiping out the filter/bulk-action
   controls along with it — only an F5 escaped it).
2. Picking "— Tất cả —" in that same dropdown sent `missed_min_days=`
   (empty string) and 422'd, because `schedule_list()`'s GET route used
   to type that param as `int | None` (FastAPI/pydantic rejects `""`
   before the function body ever runs).

Both were fixed on 2026-09-24 but verified only via ad-hoc TestClient
scripts at the time, per that day's own tasks.md entry — this file
closes that gap with real regression tests.

Same "minimal FastAPI app, never the real service.app" pattern as
tests/test_admin_login.py (see that file's own docstring for why:
human_bot/service.py's lifespan() launches real Playwright browsers and
background polling loops on startup). Uses the isolated_schedule_dirs
fixture (tests/conftest.py) for all schedule_store state, and
no_real_run_task for the 2 fire-now routes so no real browser action is
ever dispatched.
"""
from __future__ import annotations

from datetime import datetime, timedelta, timezone
from urllib.parse import quote

import pytest
from fastapi import FastAPI
from fastapi.responses import RedirectResponse, Response
from fastapi.testclient import TestClient
from starlette.middleware.sessions import SessionMiddleware

import human_bot.schedule_store as schedule_store
from human_bot.admin import NotLoggedIn, router as admin_router
from human_bot.config import AccountConfig, RateLimits


def _make_test_app() -> FastAPI:
    app = FastAPI()
    app.add_middleware(
        SessionMiddleware,
        secret_key="test-only-secret-key",
        session_cookie="human_bot_admin_session",
        max_age=3600,
        same_site="lax",
        https_only=False,
    )

    @app.exception_handler(NotLoggedIn)
    async def _handle_not_logged_in(request, exc: NotLoggedIn) -> Response:
        login_url = "/admin/login"
        if exc.next_path:
            login_url += "?next=" + quote(exc.next_path, safe="")
        if request.headers.get("hx-request") == "true":
            return Response(status_code=200, headers={"HX-Redirect": login_url})
        return RedirectResponse(login_url, status_code=303)

    app.include_router(admin_router)
    return app


@pytest.fixture
def client(isolated_runtime_config, isolated_schedule_dirs, monkeypatch):
    """Login left off (no ADMIN_USERNAME/PASSWORD) so every request
    reaches the route directly — this file is about /admin/schedule's
    own logic, not auth (already covered by test_admin_login.py)."""
    monkeypatch.delenv("ADMIN_USERNAME", raising=False)
    monkeypatch.delenv("ADMIN_PASSWORD", raising=False)
    return TestClient(_make_test_app(), follow_redirects=False)


def _add_task(when: datetime, account_id="acc-a", action="post_to_group", **overrides) -> schedule_store.ScheduledTask:
    task = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(when.isoformat()),
        action=action, account_id=account_id, scheduled_at=when.isoformat(),
        content="hello", target_url="https://facebook.com/groups/1",
        **overrides,
    )
    schedule_store.add(task)
    return task


def _add_missed(when: datetime, reason="quá hạn test", **kwargs) -> schedule_store.ScheduledTask:
    task = _add_task(when, **kwargs)
    schedule_store.mark_missed(task.task_id, reason)
    return task


# --- Bug #1 regression: filter/bulk controls must survive a zero-match filter ---

def test_missed_filter_controls_survive_a_filter_with_zero_matches(client):
    """2026-09-24 real bug: filtering to zero matches used to wipe out
    the "Quá hạn" <select> and "Chọn tất cả"/"Xoá đã chọn" controls along
    with the (rightfully empty) task list, leaving no way to change the
    filter back without an F5."""
    now = datetime.now(timezone.utc)
    _add_missed(now - timedelta(days=1))  # only 1 day overdue

    resp = client.get("/admin/schedule?tab=missed&missed_min_days=30")
    assert resp.status_code == 200
    assert 'id="schedule-missed-mindays-select"' in resp.text
    assert "Chọn tất cả" in resp.text
    assert "Không có task nào quá hạn" in resp.text


def test_missed_filter_shows_matching_tasks_and_hides_fresher_ones(client):
    now = datetime.now(timezone.utc)
    old = _add_missed(now - timedelta(days=10))
    fresh = _add_missed(now - timedelta(days=1))

    resp = client.get("/admin/schedule?tab=missed&missed_min_days=7")
    assert old.task_id in resp.text
    assert fresh.task_id not in resp.text


# --- Bug #2 regression: "— Tất cả —" (empty string) must not 422 ---

def test_missed_min_days_empty_string_does_not_422(client):
    """2026-09-24 real bug: schedule_list()'s missed_min_days used to be
    typed int | None, so FastAPI 422'd on the "— Tất cả —" option's
    empty-string value before the route body ever ran."""
    now = datetime.now(timezone.utc)
    _add_missed(now - timedelta(days=1))

    resp = client.get("/admin/schedule?tab=missed&missed_min_days=")
    assert resp.status_code == 200


def test_missed_min_days_garbage_string_falls_back_to_unfiltered(client):
    now = datetime.now(timezone.utc)
    task = _add_missed(now - timedelta(days=1))
    resp = client.get("/admin/schedule?tab=missed&missed_min_days=not-a-number")
    assert resp.status_code == 200
    assert task.task_id in resp.text


# --- Pending-tab filters ---

def test_pending_tab_account_filter_shows_only_matching_account(client, monkeypatch):
    """account_id must be a KNOWN account (get_all_accounts()) or
    _schedule_content_html() resets the filter to "show all" — see that
    function's own "unknown/stale filter falls back to all" comment —
    so both fake accounts must be registered for this filter to bite."""
    import human_bot.admin as admin_module
    accounts = {
        "acc-a": AccountConfig(account_id="acc-a", display_name="A"),
        "acc-b": AccountConfig(account_id="acc-b", display_name="B"),
    }
    monkeypatch.setattr(admin_module, "get_all_accounts", lambda: accounts)

    now = datetime.now(timezone.utc)
    a = _add_task(now + timedelta(hours=1), account_id="acc-a")
    b = _add_task(now + timedelta(hours=1), account_id="acc-b")

    resp = client.get("/admin/schedule?account_id=acc-a")
    assert a.task_id in resp.text
    assert b.task_id not in resp.text


def test_pending_tab_action_filter(client):
    now = datetime.now(timezone.utc)
    post = _add_task(now + timedelta(hours=1), action="post_to_group")
    comment = _add_task(now + timedelta(hours=1), action="comment_on_group_post")

    resp = client.get("/admin/schedule?action=post_to_group")
    assert post.task_id in resp.text
    assert comment.task_id not in resp.text


# --- Bulk-cancel only touches the ids actually submitted ---

def test_missed_bulk_cancel_only_removes_selected_ids(client):
    now = datetime.now(timezone.utc)
    keep = _add_missed(now - timedelta(days=1))
    remove = _add_missed(now - timedelta(days=2))

    resp = client.post("/admin/schedule/missed/bulk-cancel", data={"task_ids": [remove.task_id]})
    assert resp.status_code in (200, 303)
    assert schedule_store.get_missed(remove.task_id) is None
    assert schedule_store.get_missed(keep.task_id) is not None


def test_missed_bulk_cancel_with_no_ids_selected_is_a_no_op(client):
    now = datetime.now(timezone.utc)
    keep = _add_missed(now - timedelta(days=1))
    resp = client.post("/admin/schedule/missed/bulk-cancel", data={})
    assert resp.status_code in (200, 303)
    assert schedule_store.get_missed(keep.task_id) is not None


# --- Missed reschedule / reschedule-confirm / cancel ---

def test_missed_reschedule_moves_task_back_to_pending(client):
    now = datetime.now(timezone.utc)
    task = _add_missed(now - timedelta(hours=1))
    new_time = (now + timedelta(days=1)).isoformat()

    resp = client.post("/admin/schedule/missed/reschedule", data={
        "task_id": task.task_id, "content": "updated content", "scheduled_at": new_time,
    })
    assert resp.status_code in (200, 303)
    assert schedule_store.get_missed(task.task_id) is None
    restored = schedule_store.get(task.task_id)
    assert restored is not None
    assert restored.content == "updated content"


def test_missed_cancel_moves_task_to_cancelled(client):
    now = datetime.now(timezone.utc)
    task = _add_missed(now - timedelta(hours=1))
    resp = client.post("/admin/schedule/missed/cancel", data={"task_id": task.task_id})
    assert resp.status_code in (200, 303)
    assert schedule_store.get_missed(task.task_id) is None
    cancelled_files = list(schedule_store.CANCELLED_DIR.glob("*.json"))
    assert len(cancelled_files) == 1


def test_missed_action_on_already_resolved_task_is_a_graceful_no_op(client):
    resp = client.post("/admin/schedule/missed/cancel", data={"task_id": "nonexistent"})
    assert resp.status_code in (200, 303)


# --- Fire-now: pending tab (schedule_fire_now) and missed tab (schedule_missed_fire_now) ---

@pytest.fixture
def account_with_rate_limits(monkeypatch, tmp_path):
    """Registers a fake account via human_bot.admin.get_all_accounts()
    (monkeypatched directly, same as the manual live-verification script
    used during development) — avoids needing a real accounts/ directory
    on disk just to exercise the rate-limit branches.

    2026-09-25 fix (found during a post-Phase-1 audit, not caught when
    this was first written): action_log_path MUST be patched via
    `monkeypatch.setattr(AccountConfig, ...)`, never a raw
    `acc.__class__.action_log_path = ...` assignment — the raw form
    replaces the property on the AccountConfig CLASS itself with no
    teardown, so it silently leaked into every OTHER AccountConfig
    instance (including real ones) constructed anywhere in the test
    session afterward, for as long as the process stayed up. Confirmed
    live: a second, unrelated test creating its own AccountConfig after
    this fixture ran still got THIS fixture's tmp_path action_log back.
    monkeypatch.setattr on a class attribute restores the original
    property automatically at test teardown, closing that leak."""
    import human_bot.admin as admin_module

    def _make(**rate_limit_kwargs):
        action_log = tmp_path / "action_log.jsonl"
        action_log.write_text("")
        acc = AccountConfig(account_id="acc-a", display_name="Acc A", rate_limits=RateLimits(**rate_limit_kwargs))
        monkeypatch.setattr(AccountConfig, "action_log_path", property(lambda self: action_log))
        monkeypatch.setattr(admin_module, "get_all_accounts", lambda: {"acc-a": acc})
        return acc, action_log

    return _make


@pytest.mark.parametrize("route", ["/admin/schedule/fire-now", "/admin/schedule/missed/fire-now"])
def test_fire_now_posts_when_slot_and_gap_are_both_fine(client, account_with_rate_limits, no_real_run_task, route):
    account_with_rate_limits(posts_per_day=30)
    calls, _results = no_real_run_task
    now = datetime.now(timezone.utc)
    if "missed" in route:
        task = _add_missed(now - timedelta(hours=1))
    else:
        task = _add_task(now - timedelta(hours=1))

    resp = client.post(route, data={"task_id": task.task_id})
    assert resp.status_code in (200, 303)
    assert len(calls) == 1
    assert len(list(schedule_store.POSTED_DIR.glob("*.json"))) == 1


@pytest.mark.parametrize("route", ["/admin/schedule/fire-now", "/admin/schedule/missed/fire-now"])
def test_fire_now_blocks_when_daily_slot_is_full_even_with_force(client, account_with_rate_limits, no_real_run_task, route):
    """The hard per-day count cap ("đủ slot hôm nay không") must never be
    bypassed, not even by force=1. Fixed 2026-09-25 in both routes:
    schedule_missed_fire_now() first, then schedule_fire_now() (the
    PENDING-tab route it was copied from) once the same gap was found
    here while writing this very test — both used to skip the hard-cap
    check entirely whenever force was set, not just the soft gap check."""
    account_with_rate_limits(posts_per_day=0)
    calls, _results = no_real_run_task
    now = datetime.now(timezone.utc)
    if "missed" in route:
        task = _add_missed(now - timedelta(hours=1))
    else:
        task = _add_task(now - timedelta(hours=1))

    resp = client.post(route, data={"task_id": task.task_id, "force": "1"})
    assert resp.status_code in (200, 303)
    assert len(calls) == 0
    if "missed" in route:
        assert schedule_store.get_missed(task.task_id) is not None
    else:
        assert schedule_store.get(task.task_id) is not None


@pytest.mark.parametrize("route", ["/admin/schedule/fire-now", "/admin/schedule/missed/fire-now"])
def test_fire_now_gap_block_shows_warning_without_firing(client, account_with_rate_limits, no_real_run_task, route):
    import json as json_mod
    account, action_log = account_with_rate_limits(
        posts_per_day=30, post_min_delay_seconds=99999, post_max_delay_seconds=99999,
    )
    now_naive = datetime.utcnow()
    action_log.write_text(json_mod.dumps({
        "action": "post", "success": True, "timestamp": now_naive.isoformat(),
        "next_allowed_at": (now_naive + timedelta(seconds=99999)).isoformat(),
    }) + "\n")
    calls, _results = no_real_run_task
    now = datetime.now(timezone.utc)
    if "missed" in route:
        task = _add_missed(now - timedelta(hours=1))
    else:
        task = _add_task(now - timedelta(hours=1))

    resp = client.post(route, data={"task_id": task.task_id}, headers={"hx-request": "true"})
    assert len(calls) == 0
    assert "Vẫn đăng ngay" in resp.text


@pytest.mark.parametrize("route", ["/admin/schedule/fire-now", "/admin/schedule/missed/fire-now"])
def test_fire_now_gap_block_with_force_fires_and_sets_force_ignore_gap(client, account_with_rate_limits, no_real_run_task, route):
    import json as json_mod
    account, action_log = account_with_rate_limits(
        posts_per_day=30, post_min_delay_seconds=99999, post_max_delay_seconds=99999,
    )
    now_naive = datetime.utcnow()
    action_log.write_text(json_mod.dumps({
        "action": "post", "success": True, "timestamp": now_naive.isoformat(),
        "next_allowed_at": (now_naive + timedelta(seconds=99999)).isoformat(),
    }) + "\n")
    calls, _results = no_real_run_task
    now = datetime.now(timezone.utc)
    if "missed" in route:
        task = _add_missed(now - timedelta(hours=1))
    else:
        task = _add_task(now - timedelta(hours=1))

    resp = client.post(route, data={"task_id": task.task_id, "force": "1"})
    assert resp.status_code in (200, 303)
    assert len(calls) == 1
    assert calls[0].force_ignore_gap is True


def test_fire_now_task_not_found(client, no_real_run_task):
    calls, _results = no_real_run_task
    resp = client.post("/admin/schedule/fire-now", data={"task_id": "nonexistent"})
    assert resp.status_code in (200, 303)
    assert len(calls) == 0


def test_missed_fire_now_task_not_found(client, no_real_run_task):
    calls, _results = no_real_run_task
    resp = client.post("/admin/schedule/missed/fire-now", data={"task_id": "nonexistent"})
    assert resp.status_code in (200, 303)
    assert len(calls) == 0
