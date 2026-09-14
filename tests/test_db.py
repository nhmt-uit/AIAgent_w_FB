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
