"""Tests for human_bot/db.py's "theo từng lần đăng" (per-job) report
queries — job_post_groups(), job_post_groups_count(), job_post_group_detail()
— and its "theo từng lần bình luận" (per-candidate-comment) counterpart —
candidate_comments(), candidate_comments_count(). Unlike the job report,
the candidate one is a FLAT one-row-per-action_log-row list (no grouping —
a candidate only ever gets one comment, no per-group fan-out like a job).
Isolated from the real human_bot.db via monkeypatching DB_PATH to a tmp_path
file (per project rule: never touch the live database in tests)."""
import json

import pytest

from human_bot import db


@pytest.fixture
def isolated_db(tmp_path, monkeypatch):
    monkeypatch.setattr(db, "DB_PATH", tmp_path / "test.db")
    db.ensure_schema()
    return db


def _log_job_row(d, source_id, account_id, group_name, success, content="nội dung"):
    d.log_action(
        account_id=account_id,
        action="post_to_group",
        success=success,
        message="" if success else "some failure",
        target_group_name=group_name,
        content=content,
        source="scheduled",
        source_kind="job",
        source_id=source_id,
        job_data={"title": "Kỹ sư cơ khí", "attributes": {"company": "ACME", "jlpt": "N2"}},
    )


def test_job_post_groups_groups_by_source_and_account(isolated_db):
    _log_job_row(isolated_db, "job-1", "acc-a", "group-1", True)
    _log_job_row(isolated_db, "job-1", "acc-a", "group-2", False)
    _log_job_row(isolated_db, "job-2", "acc-a", "group-1", True)

    rows = isolated_db.job_post_groups()
    by_source = {r["source_id"]: r for r in rows}
    assert set(by_source) == {"job-1", "job-2"}
    assert by_source["job-1"]["total_groups"] == 2
    assert by_source["job-1"]["succeeded_groups"] == 1
    assert by_source["job-2"]["total_groups"] == 1
    assert by_source["job-2"]["succeeded_groups"] == 1


def test_job_post_groups_separates_by_account(isolated_db):
    _log_job_row(isolated_db, "job-1", "acc-a", "group-1", True)
    _log_job_row(isolated_db, "job-1", "acc-b", "group-1", True)

    rows = isolated_db.job_post_groups()
    assert len(rows) == 2
    accounts = {r["account_id"] for r in rows}
    assert accounts == {"acc-a", "acc-b"}


def test_job_post_groups_only_includes_job_source_kind(isolated_db):
    _log_job_row(isolated_db, "job-1", "acc-a", "group-1", True)
    isolated_db.log_action(
        account_id="acc-a", action="post_to_own_profile", success=True,
        content="text", source="manual", source_kind=None, source_id=None,
    )

    rows = isolated_db.job_post_groups()
    assert len(rows) == 1
    assert rows[0]["source_id"] == "job-1"


def test_job_post_groups_filters_by_account_id(isolated_db):
    _log_job_row(isolated_db, "job-1", "acc-a", "group-1", True)
    _log_job_row(isolated_db, "job-2", "acc-b", "group-1", True)

    rows = isolated_db.job_post_groups(account_id="acc-a")
    assert len(rows) == 1
    assert rows[0]["account_id"] == "acc-a"


def test_job_post_groups_pagination(isolated_db):
    for i in range(5):
        _log_job_row(isolated_db, f"job-{i}", "acc-a", "group-1", True)

    assert isolated_db.job_post_groups_count() == 5
    page1 = isolated_db.job_post_groups(limit=2, offset=0)
    page2 = isolated_db.job_post_groups(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {r["source_id"] for r in page1}.isdisjoint({r["source_id"] for r in page2})


def test_job_post_groups_carries_job_data(isolated_db):
    _log_job_row(isolated_db, "job-1", "acc-a", "group-1", True)

    rows = isolated_db.job_post_groups()
    parsed = json.loads(rows[0]["job_data"])
    assert parsed["title"] == "Kỹ sư cơ khí"
    assert parsed["attributes"]["company"] == "ACME"


def test_job_post_group_detail_returns_every_group_row_oldest_first(isolated_db):
    _log_job_row(isolated_db, "job-1", "acc-a", "group-1", True, content="bài cho group 1")
    _log_job_row(isolated_db, "job-1", "acc-a", "group-2", False, content="bài cho group 2")

    detail = isolated_db.job_post_group_detail("job-1", "acc-a")
    assert len(detail) == 2
    assert detail[0]["target_group_name"] == "group-1"
    assert detail[0]["content"] == "bài cho group 1"
    assert detail[1]["target_group_name"] == "group-2"
    assert detail[1]["success"] == 0


def test_job_post_group_detail_scoped_to_source_and_account(isolated_db):
    _log_job_row(isolated_db, "job-1", "acc-a", "group-1", True)
    _log_job_row(isolated_db, "job-2", "acc-a", "group-1", True)
    _log_job_row(isolated_db, "job-1", "acc-b", "group-1", True)

    detail = isolated_db.job_post_group_detail("job-1", "acc-a")
    assert len(detail) == 1


def _log_candidate_row(d, source_id, account_id, success, content="bình luận"):
    d.log_action(
        account_id=account_id,
        action="comment_on_group_post",
        success=success,
        message="" if success else "some failure",
        target_group_name="group-1",
        content=content,
        source="scheduled",
        source_kind="candidate",
        source_id=source_id,
        job_data={"attributes": {"desiredJobField": "cơ khí", "preferredRegion": "Osaka"}},
    )


def test_candidate_comments_is_flat_one_row_per_attempt(isolated_db):
    # No grouping (2026-09-12, owner request) — a candidate normally gets
    # exactly 1 comment (unlike a job's per-group fan-out), so each
    # action_log row shows up as its own row, newest first.
    _log_candidate_row(isolated_db, "cand-1", "acc-a", True, content="lần 1")
    _log_candidate_row(isolated_db, "cand-2", "acc-a", False, content="lần 2")

    rows = isolated_db.candidate_comments()
    assert len(rows) == 2
    assert rows[0]["content"] == "lần 2"  # newest first
    assert rows[0]["success"] == 0
    assert rows[1]["content"] == "lần 1"
    assert rows[1]["success"] == 1


def test_candidate_comments_shows_retry_as_its_own_row(isolated_db):
    # A retried (via "Đăng lại") candidate just shows up as an extra row —
    # no collapsing, unlike the old grouped version.
    _log_candidate_row(isolated_db, "cand-1", "acc-a", False)
    _log_candidate_row(isolated_db, "cand-1", "acc-a", True)

    rows = isolated_db.candidate_comments()
    assert len(rows) == 2
    assert {r["source_id"] for r in rows} == {"cand-1"}


def test_candidate_comments_only_includes_candidate_source_kind(isolated_db):
    _log_candidate_row(isolated_db, "cand-1", "acc-a", True)
    _log_job_row(isolated_db, "job-1", "acc-a", "group-1", True)

    rows = isolated_db.candidate_comments()
    assert len(rows) == 1
    assert rows[0]["source_id"] == "cand-1"


def test_candidate_comments_filters_by_account_id(isolated_db):
    _log_candidate_row(isolated_db, "cand-1", "acc-a", True)
    _log_candidate_row(isolated_db, "cand-2", "acc-b", True)

    rows = isolated_db.candidate_comments(account_id="acc-a")
    assert len(rows) == 1
    assert rows[0]["account_id"] == "acc-a"


def test_candidate_comments_pagination(isolated_db):
    for i in range(5):
        _log_candidate_row(isolated_db, f"cand-{i}", "acc-a", True)

    assert isolated_db.candidate_comments_count() == 5
    page1 = isolated_db.candidate_comments(limit=2, offset=0)
    page2 = isolated_db.candidate_comments(limit=2, offset=2)
    assert len(page1) == 2
    assert len(page2) == 2
    assert {r["source_id"] for r in page1}.isdisjoint({r["source_id"] for r in page2})


def test_candidate_comments_carries_job_data(isolated_db):
    _log_candidate_row(isolated_db, "cand-1", "acc-a", True)

    rows = isolated_db.candidate_comments()
    parsed = json.loads(rows[0]["job_data"])
    assert parsed["attributes"]["desiredJobField"] == "cơ khí"
    assert parsed["attributes"]["preferredRegion"] == "Osaka"


# --- cleanup_old(): 6-month retention of action_log (2026-09-28) ---

def _log_at(db_mod, days_ago: float, message: str):
    from datetime import datetime, timedelta, timezone
    db_mod.log_action(
        account_id="acc-a", action="post_to_group", success=True, message=message,
        created_at=(datetime.now(timezone.utc) - timedelta(days=days_ago)).isoformat(),
    )


def _messages(db_mod) -> set[str]:
    return {r["message"] for r in db_mod.recent_activity(limit=100)}


def _set_retention(**kwargs):
    from human_bot.runtime_config import save_retention_overrides
    values = {"screenshot_days": 60, "schedule_days": 180, "action_log_days": 180}
    values.update(kwargs)
    save_retention_overrides(values)


def test_cleanup_old_default_keeps_six_months_and_drops_older(isolated_db, isolated_runtime_config):
    from human_bot.retention_config import RetentionConfig
    assert RetentionConfig().action_log_days == 180
    _log_at(isolated_db, 5, "recent")
    _log_at(isolated_db, 170, "just-inside")
    _log_at(isolated_db, 190, "just-outside")
    _log_at(isolated_db, 400, "very-old")
    assert isolated_db.cleanup_old() == 2
    assert _messages(isolated_db) == {"recent", "just-inside"}


def test_cleanup_old_uses_the_admin_configured_window(isolated_db, isolated_runtime_config):
    _set_retention(action_log_days=10)
    _log_at(isolated_db, 5, "keep")
    _log_at(isolated_db, 20, "drop")
    assert isolated_db.cleanup_old() == 1
    assert _messages(isolated_db) == {"keep"}


def test_cleanup_old_on_empty_table_is_a_noop(isolated_db, isolated_runtime_config):
    assert isolated_db.cleanup_old() == 0


def test_cleanup_old_non_positive_retention_disables_instead_of_wiping(isolated_db, isolated_runtime_config):
    """Found in a pre-commit review: a retention of 0 used to delete EVERY
    row (cutoff = now), even one written seconds ago. Zero or negative must
    mean "keep everything" — as an explicit argument and as the saved
    admin setting."""
    _log_at(isolated_db, 0, "brand-new")
    _log_at(isolated_db, 400, "ancient")
    assert isolated_db.cleanup_old(0) == 0
    assert isolated_db.cleanup_old(-5) == 0
    _set_retention(action_log_days=0)
    assert isolated_db.cleanup_old() == 0
    assert _messages(isolated_db) == {"brand-new", "ancient"}


# --- log_skipped_job (2026-09-29/30: jobs filtered out for incomplete
# content are logged here since _mark_seen() itself only stores
# {kind, seen_at} — this table is the only place the raw record survives) --

def test_log_skipped_job_round_trip(isolated_db):
    isolated_db.log_skipped_job(
        "703",
        reason="incomplete_data",
        missing_fields=["title", "details"],
        job={"title": None, "attributes": {"confidence": 0.88}},
    )
    conn = isolated_db._connect()
    try:
        row = conn.execute("SELECT * FROM skipped_jobs WHERE job_id = ?", ("703",)).fetchone()
    finally:
        conn.close()
    assert row is not None
    assert row["reason"] == "incomplete_data"
    assert json.loads(row["missing_fields"]) == ["title", "details"]
    assert row["title"] is None
    assert json.loads(row["attributes"]) == {"confidence": 0.88}
    assert row["created_at"]


# --- last_successful_action_per_account (2026-10-02, "sức khoẻ tài khoản") --

def test_last_successful_action_per_account_picks_the_latest_per_account(isolated_db):
    isolated_db.log_action(account_id="acc-a", action="post_to_group", success=True, created_at="2026-10-01T01:00:00+00:00")
    isolated_db.log_action(account_id="acc-a", action="post_to_group", success=True, created_at="2026-10-02T03:00:00+00:00")
    isolated_db.log_action(account_id="acc-b", action="comment_on_group_post", success=True, created_at="2026-09-30T00:00:00+00:00")

    result = isolated_db.last_successful_action_per_account()
    assert result == {
        "acc-a": "2026-10-02T03:00:00+00:00",
        "acc-b": "2026-09-30T00:00:00+00:00",
    }


def test_last_successful_action_per_account_ignores_failed_rows(isolated_db):
    isolated_db.log_action(account_id="acc-a", action="post_to_group", success=False, created_at="2026-10-02T03:00:00+00:00")
    isolated_db.log_action(account_id="acc-a", action="post_to_group", success=True, created_at="2026-10-01T01:00:00+00:00")

    result = isolated_db.last_successful_action_per_account()
    assert result == {"acc-a": "2026-10-01T01:00:00+00:00"}


def test_last_successful_action_per_account_omits_accounts_with_no_success(isolated_db):
    isolated_db.log_action(account_id="acc-a", action="post_to_group", success=False, created_at="2026-10-02T03:00:00+00:00")

    result = isolated_db.last_successful_action_per_account()
    assert "acc-a" not in result


def test_last_successful_action_per_account_empty_when_no_rows(isolated_db):
    assert isolated_db.last_successful_action_per_account() == {}
