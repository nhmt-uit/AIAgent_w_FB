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


# --- "⇄ Đổi giờ" (swap scheduled_at between 2 pending tasks, 2026-09-29) ----

def test_swap_modal_lists_only_same_account_same_bucket_candidates(client):
    now = datetime.now(timezone.utc)
    post_a = _add_task(now, account_id="acc-a", action="post_to_group")
    post_b = _add_task(now + timedelta(hours=1), account_id="acc-a", action="post_to_own_profile")
    schedule_store.update(post_b.task_id, content="post B same bucket")
    other_account = _add_task(now + timedelta(hours=2), account_id="acc-b", action="post_to_group")
    schedule_store.update(other_account.task_id, content="other account")
    comment = _add_task(now + timedelta(hours=3), account_id="acc-a", action="comment_on_group_post")
    schedule_store.update(comment.task_id, content="different bucket")

    resp = client.post("/admin/schedule/swap-modal", data={"task_id": post_a.task_id})
    assert resp.status_code == 200
    assert "post B same bucket" in resp.text  # same account + "post" bucket, offered
    assert "other account" not in resp.text  # different account, excluded
    assert "different bucket" not in resp.text  # comment bucket, excluded
    assert post_b.task_id in resp.text


def test_swap_modal_shows_empty_state_with_no_eligible_candidates(client):
    task = _add_task(datetime.now(timezone.utc), account_id="acc-a", action="post_to_group")
    resp = client.post("/admin/schedule/swap-modal", data={"task_id": task.task_id})
    assert "Không có bài nào khác" in resp.text
    assert "disabled" in resp.text


def test_swap_modal_task_not_found(client):
    resp = client.post("/admin/schedule/swap-modal", data={"task_id": "nonexistent"})
    assert "Không tìm thấy" in resp.text


def test_swap_trades_scheduled_at_between_two_pending_tasks(client):
    now = datetime.now(timezone.utc)
    a = _add_task(now, account_id="acc-a", action="post_to_group")
    schedule_store.update(a.task_id, content="A")
    b = _add_task(now + timedelta(hours=3), account_id="acc-a", action="post_to_group")
    schedule_store.update(b.task_id, content="B")

    resp = client.post("/admin/schedule/swap", data={"task_id_a": a.task_id, "task_id_b": b.task_id})
    assert resp.status_code in (200, 303)

    new_a = schedule_store.get(a.task_id)
    new_b = schedule_store.get(b.task_id)
    assert new_a.scheduled_at == b.scheduled_at
    assert new_b.scheduled_at == a.scheduled_at
    assert new_a.content == "A" and new_b.content == "B"


def test_swap_rejects_different_accounts_even_via_direct_post(client):
    now = datetime.now(timezone.utc)
    a = _add_task(now, account_id="acc-a", action="post_to_group")
    b = _add_task(now + timedelta(hours=1), account_id="acc-b", action="post_to_group")

    resp = client.post("/admin/schedule/swap", data={"task_id_a": a.task_id, "task_id_b": b.task_id})
    assert resp.status_code in (200, 303)
    assert schedule_store.get(a.task_id).scheduled_at == a.scheduled_at  # unchanged
    assert schedule_store.get(b.task_id).scheduled_at == b.scheduled_at


def test_swap_rejects_different_buckets_even_via_direct_post(client):
    now = datetime.now(timezone.utc)
    a = _add_task(now, account_id="acc-a", action="post_to_group")
    b = _add_task(now + timedelta(hours=1), account_id="acc-a", action="comment_on_group_post")

    resp = client.post("/admin/schedule/swap", data={"task_id_a": a.task_id, "task_id_b": b.task_id})
    assert resp.status_code in (200, 303)
    assert schedule_store.get(a.task_id).scheduled_at == a.scheduled_at  # unchanged
    assert schedule_store.get(b.task_id).scheduled_at == b.scheduled_at


def test_swap_task_not_found(client):
    a = _add_task(datetime.now(timezone.utc), account_id="acc-a", action="post_to_group")
    resp = client.post("/admin/schedule/swap", data={"task_id_a": a.task_id, "task_id_b": "nonexistent"})
    assert resp.status_code in (200, 303)
    assert schedule_store.get(a.task_id).scheduled_at == a.scheduled_at  # unchanged


# --- "↩️ Mượn giờ" (missed task takes a pending task's slot, displaced ------
# pending task gets a freshly-suggested new slot, 2026-09-29) -------------

def test_borrow_modal_lists_pending_candidates_with_preview_time(client, account_with_rate_limits):
    account_with_rate_limits(posts_per_day=30)
    now = datetime.now(timezone.utc)
    missed = _add_missed(now - timedelta(hours=5), account_id="acc-a", action="post_to_group")
    pending = _add_task(now + timedelta(hours=1), account_id="acc-a", action="post_to_own_profile")
    schedule_store.update(pending.task_id, content="candidate B")

    resp = client.get(f"/admin/schedule/missed/borrow?task_id={missed.task_id}")
    assert resp.status_code == 200
    assert "candidate B" in resp.text
    assert pending.task_id in resp.text
    assert "dời sang" in resp.text


def test_borrow_modal_empty_state_with_no_eligible_candidates(client, account_with_rate_limits):
    account_with_rate_limits(posts_per_day=30)
    missed = _add_missed(datetime.now(timezone.utc) - timedelta(hours=5), account_id="acc-a", action="post_to_group")
    resp = client.get(f"/admin/schedule/missed/borrow?task_id={missed.task_id}")
    assert "Không có bài nào đang chờ đăng" in resp.text
    assert "disabled" in resp.text


def test_borrow_modal_missed_task_not_found(client):
    resp = client.get("/admin/schedule/missed/borrow?task_id=nonexistent")
    assert resp.text == ""


def test_borrow_modal_account_not_found(client):
    missed = _add_missed(datetime.now(timezone.utc) - timedelta(hours=5), account_id="acc-unregistered")
    resp = client.get(f"/admin/schedule/missed/borrow?task_id={missed.task_id}")
    assert "Không tìm thấy tài khoản" in resp.text


def test_borrow_confirm_moves_missed_task_into_pendings_old_slot_and_reschedules_pending(client, account_with_rate_limits):
    account_with_rate_limits(posts_per_day=30)
    now = datetime.now(timezone.utc)
    missed = _add_missed(now - timedelta(hours=5), account_id="acc-a", action="post_to_group")
    pending = _add_task(now + timedelta(hours=1), account_id="acc-a", action="post_to_own_profile")
    old_pending_time = pending.scheduled_at

    resp = client.post("/admin/schedule/missed/borrow-confirm", data={"task_id_a": missed.task_id, "task_id_b": pending.task_id})
    assert resp.status_code in (200, 303)

    moved = schedule_store.get(missed.task_id)
    assert moved is not None
    assert moved.scheduled_at == old_pending_time  # missed task took the pending task's exact old slot
    assert schedule_store.get_missed(missed.task_id) is None  # no longer in missed/

    displaced = schedule_store.get(pending.task_id)
    assert displaced is not None
    assert displaced.scheduled_at != old_pending_time  # displaced task got a new slot, not the same one


def test_borrow_confirm_does_not_overfill_the_displaced_days_cap(client, account_with_rate_limits):
    """Owner-caught bug (2026-09-29, before this ever shipped): computing
    the displaced task's new slot BEFORE inserting the missed task into
    pending/ let the day-cap check miss the missed task's own arrival —
    5 other same-day tasks read as "4 once excluding itself, room for 1
    more" and the displaced task landed right back on the now-6-tasks
    day. The missed task must be inserted FIRST so its arrival is
    already counted when the displaced task's new day is searched."""
    from human_bot import daily_limits
    account_with_rate_limits(posts_per_day=5, post_min_delay_seconds=0, post_max_delay_seconds=0)
    day = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)  # well clear of the 2 AM JST quiet-hours boundary
    assert daily_limits.business_day_key(day) == daily_limits.business_day_key(day + timedelta(hours=5))
    others = [_add_task(day + timedelta(hours=i), account_id="acc-a", action="post_to_group") for i in range(4)]
    borrowed_from = _add_task(day + timedelta(hours=5), account_id="acc-a", action="post_to_group")
    missed = _add_missed(datetime.now(timezone.utc) - timedelta(hours=5), account_id="acc-a", action="post_to_group")
    target_day = daily_limits.business_day_key(day)

    resp = client.post("/admin/schedule/missed/borrow-confirm", data={"task_id_a": missed.task_id, "task_id_b": borrowed_from.task_id})
    assert resp.status_code in (200, 303)

    all_tasks = [schedule_store.get(t.task_id) for t in ([missed, borrowed_from] + others)]
    same_day_count = sum(
        1 for t in all_tasks
        if daily_limits.business_day_key(datetime.fromisoformat(t.scheduled_at)) == target_day
    )
    assert same_day_count <= 5  # never more than the account's own daily cap


def test_borrow_modal_preview_matches_what_confirm_will_actually_do(client, account_with_rate_limits):
    """Owner-caught bug 2026-09-29 (2nd half — the preview modal, not just
    the confirm route, had the same missing-A-in-the-count flaw): with a
    day already at its 5/5 cap, the preview used to say the displaced task
    would land back on that SAME (already full) day — a lie, since
    confirm's own (fixed) computation always pushes it to the NEXT
    business day once A is really counted there. The preview must show
    that same next-day answer, not the stale same-day one, so the owner
    isn't shown one outcome and given another."""
    import re
    from human_bot import daily_limits
    account_with_rate_limits(posts_per_day=5, post_min_delay_seconds=0, post_max_delay_seconds=0)
    day = datetime(2026, 10, 1, 10, tzinfo=timezone.utc)
    others = [_add_task(day + timedelta(hours=i), account_id="acc-a", action="post_to_group") for i in range(4)]
    borrowed_from = _add_task(day + timedelta(hours=5), account_id="acc-a", action="post_to_group")
    missed = _add_missed(datetime.now(timezone.utc) - timedelta(hours=5), account_id="acc-a", action="post_to_group")
    full_day = daily_limits.business_day_key(day)

    resp = client.get(f"/admin/schedule/missed/borrow?task_id={missed.task_id}")
    utcs = re.findall(r'data-utc="([^"]+)"', resp.text)
    # utcs[0] is the modal's own "Task quá hạn: ..." header line (task A's
    # past time). After that, rows are sorted by scheduled_at ascending
    # (5 candidates: others[0..3] then borrowed_from, the LAST row) — each
    # row has 2 data-utc values (its own current time, then its preview).
    preview_iso = utcs[1 + 2 * len(others) + 1]
    preview_day = daily_limits.business_day_key(datetime.fromisoformat(preview_iso.replace("Z", "+00:00")))
    assert preview_day != full_day  # must NOT claim it'll land back on the already-full day

    confirm_resp = client.post("/admin/schedule/missed/borrow-confirm", data={"task_id_a": missed.task_id, "task_id_b": borrowed_from.task_id})
    assert confirm_resp.status_code in (200, 303)
    actual_day = daily_limits.business_day_key(datetime.fromisoformat(schedule_store.get(borrowed_from.task_id).scheduled_at))
    assert preview_day == actual_day  # preview must agree with what confirm actually did


def test_borrow_confirm_rejects_different_accounts_even_via_direct_post(client, account_with_rate_limits):
    account_with_rate_limits(posts_per_day=30)
    now = datetime.now(timezone.utc)
    missed = _add_missed(now - timedelta(hours=5), account_id="acc-a", action="post_to_group")
    pending = _add_task(now + timedelta(hours=1), account_id="acc-b", action="post_to_group")

    resp = client.post("/admin/schedule/missed/borrow-confirm", data={"task_id_a": missed.task_id, "task_id_b": pending.task_id})
    assert resp.status_code in (200, 303)
    assert schedule_store.get_missed(missed.task_id) is not None  # untouched, still missed
    assert schedule_store.get(pending.task_id).scheduled_at == pending.scheduled_at  # unchanged


def test_borrow_confirm_rejects_different_buckets_even_via_direct_post(client, account_with_rate_limits):
    account_with_rate_limits(posts_per_day=30)
    now = datetime.now(timezone.utc)
    missed = _add_missed(now - timedelta(hours=5), account_id="acc-a", action="post_to_group")
    pending = _add_task(now + timedelta(hours=1), account_id="acc-a", action="comment_on_group_post")

    resp = client.post("/admin/schedule/missed/borrow-confirm", data={"task_id_a": missed.task_id, "task_id_b": pending.task_id})
    assert resp.status_code in (200, 303)
    assert schedule_store.get_missed(missed.task_id) is not None
    assert schedule_store.get(pending.task_id).scheduled_at == pending.scheduled_at


def test_borrow_confirm_task_not_found(client, account_with_rate_limits):
    account_with_rate_limits(posts_per_day=30)
    pending = _add_task(datetime.now(timezone.utc), account_id="acc-a", action="post_to_group")
    resp = client.post("/admin/schedule/missed/borrow-confirm", data={"task_id_a": "nonexistent", "task_id_b": pending.task_id})
    assert resp.status_code in (200, 303)
    assert schedule_store.get(pending.task_id).scheduled_at == pending.scheduled_at
