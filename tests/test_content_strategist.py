from __future__ import annotations

import json

import pytest

from human_bot import content_strategist as cs
from human_bot.config import GroupRef


@pytest.fixture(autouse=True)
def deterministic_random(monkeypatch):
    """Every pool in content_strategist.py is picked via random.choice() —
    pin it to "always pick the first option" so assertions can check exact
    content instead of "one of N possible strings"."""
    monkeypatch.setattr(cs.random, "choice", lambda seq: seq[0])


# --- _format_man --------------------------------------------------------

def test_format_man_whole_number():
    assert cs._format_man(250000) == "25"


def test_format_man_half_man_fraction():
    assert cs._format_man(15000) == "1.5"


# --- _salary_line ---------------------------------------------------------

def test_salary_line_jpy_month_converts_to_man():
    line = cs._salary_line({"min": 220000, "max": 280000, "currency": "JPY", "period": "month"})
    assert "22" in line and "28" in line
    assert "lá" in line or "man" in line or "tờ" in line or " m/" in line or "m/tháng" in line


def test_salary_line_jpy_hour_stays_raw_yen_no_man_conversion():
    line = cs._salary_line({"min": 1300, "max": 1500, "currency": "JPY", "period": "hour"})
    assert "1300" in line and "1500" in line
    assert "JPY" in line


def test_salary_line_non_jpy_currency_keeps_raw_amount():
    line = cs._salary_line({"min": 2000, "max": 3000, "currency": "USD", "period": "month"})
    assert "2000" in line and "3000" in line and "USD" in line


def test_salary_line_year_period_can_use_nenshuu_label(monkeypatch):
    monkeypatch.setattr(cs.random, "choice", lambda seq: seq[-1])
    line = cs._salary_line({"min": 7000000, "currency": "JPY", "period": "year"})
    assert line.startswith("Nenshuu:") or line.startswith("年収:")


def test_salary_line_non_year_period_never_uses_nenshuu_label(monkeypatch):
    monkeypatch.setattr(cs.random, "choice", lambda seq: seq[-1])
    line = cs._salary_line({"min": 250000, "currency": "JPY", "period": "month"})
    assert "Nenshuu" not in line and "年収" not in line


def test_salary_line_min_only():
    line = cs._salary_line({"min": 200000, "currency": "JPY", "period": "month"})
    assert line is not None
    assert "20" in line


def test_salary_line_missing_returns_none():
    assert cs._salary_line(None) is None
    assert cs._salary_line({}) is None
    assert cs._salary_line({"min": None, "max": None}) is None


# --- _visa_line -------------------------------------------------------------

def test_visa_line_known_code_maps_to_real_name():
    line = cs._visa_line("gijinkoku")
    assert "Gijinkoku" in line or "Kỹ Sư" in line or "技術" in line


def test_visa_line_unknown_code_capitalizes_as_is():
    line = cs._visa_line("some_unknown_code")
    assert "Some_unknown_code" in line


# --- _join_list_or_str -------------------------------------------------------

def test_join_list_or_str_list_input_no_python_repr_artifacts():
    result = cs._join_list_or_str(["Shizuoka"])
    assert result == "Shizuoka"
    assert "[" not in result and "]" not in result and "'" not in result


def test_join_list_or_str_multi_item_list():
    assert cs._join_list_or_str(["Tokyo", "Osaka"]) == "Tokyo, Osaka"


def test_join_list_or_str_plain_string_passthrough():
    assert cs._join_list_or_str("Osaka") == "Osaka"


def test_join_list_or_str_falsy_returns_empty_string():
    assert cs._join_list_or_str(None) == ""
    assert cs._join_list_or_str([]) == ""


# --- _draft_job_post_placeholder --------------------------------------------

def _job(**attrs) -> dict:
    return {"title": "Kỹ sư cơ khí", "attributes": attrs}


def test_draft_job_post_placeholder_full_fields():
    job = _job(
        company="ABC Corp", location=["Shizuoka"], visaType="gijinkoku", jlpt="N3",
        salary={"min": 220000, "max": 280000, "currency": "JPY", "period": "month"},
    )
    text = cs._draft_job_post_placeholder(job, variant_seed=0)
    assert "ABC Corp" in text
    assert "Shizuoka" in text
    assert "N3" in text
    assert "Kỹ sư cơ khí" in text
    # No missing-info line should appear when both visa and salary are present.
    assert "Thông tin" not in text


def test_draft_job_post_placeholder_missing_visa_and_salary_combined_line():
    job = _job(company="X Co", location="Tokyo")
    text = cs._draft_job_post_placeholder(job, variant_seed=0)
    assert "Thông tin visa/lương" in text


def test_draft_job_post_placeholder_header_splits_past_max_len():
    long_title = "A" * (cs._HEADER_MAX_LEN + 10)
    job = {"title": long_title, "attributes": {}}
    text = cs._draft_job_post_placeholder(job, variant_seed=0)
    lines = text.split("\n")
    header_line = lines[0]
    assert " - " not in header_line
    assert long_title in lines


def test_draft_job_post_placeholder_opener_keyed_by_variant_seed():
    job = _job()
    text0 = cs._draft_job_post_placeholder(job, variant_seed=0)
    text1 = cs._draft_job_post_placeholder(job, variant_seed=1)
    opener0 = text0.split("\n")[0].split(" - ")[0]
    opener1 = text1.split("\n")[0].split(" - ")[0]
    assert opener0 == cs._JOB_POST_OPENERS[0]
    assert opener1 == cs._JOB_POST_OPENERS[1]


# --- template_variants -------------------------------------------------------

def test_template_variants_one_per_group_keyed_by_group_index_not_job_index():
    job = _job()
    groups = [GroupRef(name="G1", url=""), GroupRef(name="G2", url=""), GroupRef(name="G3", url="")]
    variants = cs.template_variants(job, groups)
    assert len(variants) == 3
    for idx, text in enumerate(variants):
        opener = text.split("\n")[0].split(" - ")[0]
        assert opener == cs._JOB_POST_OPENERS[idx % len(cs._JOB_POST_OPENERS)]


# --- _extract_json ------------------------------------------------------

def test_extract_json_plain():
    assert cs._extract_json('{"posts": ["a", "b"]}') == {"posts": ["a", "b"]}


def test_extract_json_fenced_with_json_tag():
    text = '```json\n{"posts": ["a"]}\n```'
    assert cs._extract_json(text) == {"posts": ["a"]}


def test_extract_json_fenced_bare():
    text = '```\n{"posts": ["a"]}\n```'
    assert cs._extract_json(text) == {"posts": ["a"]}


# --- _job_summary -------------------------------------------------------

def test_job_summary_only_allowed_fields_and_no_url():
    job = {
        "title": "Kỹ sư",
        "url": "https://example.com/job/123",
        "attributes": {
            "company": "X", "location": "Tokyo", "visaType": "gijinkoku",
            "jlpt": "N2", "salary": {"min": 1}, "internalId": "should-not-leak",
        },
    }
    summary = cs._job_summary(job)
    assert "url" not in summary
    assert "internalId" not in summary
    assert set(summary.keys()) == {"title", "company", "location", "visa_type", "jlpt", "salary"}


# --- Async fallback paths -------------------------------------------------

@pytest.mark.asyncio
async def test_draft_single_post_falls_back_when_no_api_key(monkeypatch):
    monkeypatch.setattr(
        cs, "get_active_ai_provider_config",
        lambda: type("C", (), {"api_key": ""})(),
    )

    async def _should_not_be_called(*a, **kw):
        raise AssertionError("call_ai_text must not be called when no API key is configured")

    monkeypatch.setattr(cs, "call_ai_text", _should_not_be_called)
    job = _job(company="X")
    result = await cs.draft_single_post(job, "bản nháp đã lên lịch", group_name="G1", ai_enabled=True)
    assert result == "bản nháp đã lên lịch"  # existing schedule content untouched


@pytest.mark.asyncio
async def test_draft_single_post_skips_ai_entirely_when_disabled(monkeypatch):
    async def _should_not_be_called(*a, **kw):
        raise AssertionError("call_ai_text must not be called when ai_enabled=False")

    monkeypatch.setattr(cs, "call_ai_text", _should_not_be_called)
    job = _job(company="X")
    result = await cs.draft_single_post(job, "bản nháp đã lên lịch", group_name="G1", ai_enabled=False)
    assert result == "bản nháp đã lên lịch"


@pytest.mark.asyncio
async def test_draft_single_post_falls_back_on_ai_failure(monkeypatch):
    monkeypatch.setattr(
        cs, "get_active_ai_provider_config",
        lambda: type("C", (), {"api_key": "some-key"})(),
    )

    async def _raise(*a, **kw):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(cs, "call_ai_text", _raise)
    job = _job(company="X")
    result = await cs.draft_single_post(job, "bản nháp admin đã tự sửa", group_name="G1", ai_enabled=True)
    # Must keep the existing (possibly admin-edited) schedule content, NOT
    # regenerate a fresh random template — see draft_single_post()'s docstring.
    assert result == "bản nháp admin đã tự sửa"


@pytest.mark.asyncio
async def test_draft_single_post_uses_ai_result_when_call_succeeds(monkeypatch):
    monkeypatch.setattr(
        cs, "get_active_ai_provider_config",
        lambda: type("C", (), {"api_key": "some-key"})(),
    )

    async def _fake_call(system_prompt, user_prompt, max_tokens):
        return json.dumps({"posts": ["bài viết mới từ AI"]})

    monkeypatch.setattr(cs, "call_ai_text", _fake_call)
    job = _job(company="X")
    result = await cs.draft_single_post(job, "bản nháp cũ", group_name="G1", ai_enabled=True)
    assert result == "bài viết mới từ AI"


@pytest.mark.asyncio
async def test_rewrite_candidate_reply_returns_unchanged_when_disabled():
    result = await cs.rewrite_candidate_reply("bản nháp gốc", candidate=None, ai_enabled=False)
    assert result == "bản nháp gốc"


@pytest.mark.asyncio
async def test_rewrite_candidate_reply_returns_unchanged_on_empty_base_text():
    result = await cs.rewrite_candidate_reply("", candidate=None, ai_enabled=True)
    assert result == ""


@pytest.mark.asyncio
async def test_rewrite_candidate_reply_falls_back_on_ai_failure(monkeypatch):
    monkeypatch.setattr(
        cs, "get_active_ai_provider_config",
        lambda: type("C", (), {"api_key": "some-key"})(),
    )

    async def _raise(*a, **kw):
        raise RuntimeError("simulated API failure")

    monkeypatch.setattr(cs, "call_ai_text", _raise)
    result = await cs.rewrite_candidate_reply("bản nháp gốc", candidate=None, ai_enabled=True)
    assert result == "bản nháp gốc"


@pytest.mark.asyncio
async def test_rewrite_candidate_reply_uses_ai_result_when_call_succeeds(monkeypatch):
    monkeypatch.setattr(
        cs, "get_active_ai_provider_config",
        lambda: type("C", (), {"api_key": "some-key"})(),
    )

    async def _fake_call(system_prompt, user_prompt, max_tokens):
        return json.dumps({"reply": "câu trả lời mới từ AI"})

    monkeypatch.setattr(cs, "call_ai_text", _fake_call)
    result = await cs.rewrite_candidate_reply("bản nháp gốc", candidate=None, ai_enabled=True)
    assert result == "câu trả lời mới từ AI"


def test_ai_provider_configured_reflects_active_key(monkeypatch):
    monkeypatch.setattr(
        cs, "get_active_ai_provider_config",
        lambda: type("C", (), {"api_key": ""})(),
    )
    assert cs.ai_provider_configured() is False

    monkeypatch.setattr(
        cs, "get_active_ai_provider_config",
        lambda: type("C", (), {"api_key": "sk-real"})(),
    )
    assert cs.ai_provider_configured() is True
