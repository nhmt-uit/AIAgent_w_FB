"""
Purpose of this file / Muc dich cua file nay:
EN: Drafts the actual wording for a job post broadcast to MULTIPLE Facebook
groups (human_bot/data_sync.py's sync_once()) — the one place in this
project's pipeline where the same source material genuinely needs to read
differently more than once, since posting identical text into several
groups an account belongs to is the clearest spam signal there is (see
docs/agents/content-strategist.md, Guardrail 2). Posting to one's own
profile (/admin/post) is user-typed by hand and only happens once, so it
is NOT drafted here and needs no variation — see the conversation that
scoped this file down to just the group-broadcast case.

Calls Anthropic's Messages API directly over httpx (already a project
dependency, see requirements.txt) rather than going through
human_bot/llm.py's get_llm(), which pulls in the (optional, not installed
by default) browser-use package just to construct a ChatAnthropic — too
heavy for a single plain-text drafting call.

Safe-by-default: if ANTHROPIC_API_KEY is unset, or the API call fails or
returns something unusable (wrong variant count, empty string, bad JSON),
this silently falls back to the same plain-template drafting that existed
before this file — human_bot/data_sync.py's behavior is UNCHANGED until a
real key is added to .env (and the service restarted — env vars are only
read at process startup, same convention as ADMIN_USERNAME/TASKS_API_KEY).
Every task drafted either way is still staged in /admin/schedule for human
review before it fires (DataSyncConfig.auto_fire_enabled defaults False) —
this file only changes what the drafted text says, not the safety gate
around actually posting it.
VI: Soan noi dung that cho tin tuyen dung duoc dang vao NHIEU nhom Facebook
cung luc (sync_once() trong human_bot/data_sync.py) — noi duy nhat trong
pipeline nay thuc su can noi dung khac nhau nhieu lan, vi dang y het chu
vao nhieu nhom cung tai khoan la dau hieu spam ro nhat (xem
docs/agents/content-strategist.md, Guardrail 2). Dang len tuong ca nhan
(/admin/post) la nguoi dung tu go tay va chi dang 1 lan, nen KHONG can bien
tau va khong xu ly o day.

Goi thang Anthropic Messages API qua httpx (da co san trong requirements.txt)
thay vi qua human_bot/llm.py's get_llm() — ham do keo theo goi browser-use
(optional, khong cai san) chi de tao ChatAnthropic, qua nang cho mot lan
goi soan van ban don gian.

An toan mac dinh: khong co ANTHROPIC_API_KEY, hoac goi API loi/tra ve thu
khong dung dang (sai so luong bien the, chuoi rong, JSON hong) thi tu dong
roi ve dung kieu soan mau (template) da co tu truoc — hanh vi cua
human_bot/data_sync.py KHONG doi cho toi khi co key that trong .env (va
restart service). Du soan bang cach nao, moi muc van duoc luu vao
/admin/schedule de nguoi xem lai truoc khi dang that.
"""
from __future__ import annotations

import json
import logging
import os
from typing import TYPE_CHECKING, Any

import httpx

if TYPE_CHECKING:
    from human_bot.config import GroupRef

logger = logging.getLogger("human_bot.content_strategist")

ANTHROPIC_API_URL = "https://api.anthropic.com/v1/messages"
# Overridable via .env (CONTENT_STRATEGIST_MODEL) in case this id ever
# needs to change without a code edit — see .env.example.
DEFAULT_MODEL = "claude-sonnet-4-5"

_SYSTEM_PROMPT = """Bạn là Content Strategist Agent cho một trang Facebook tuyển dụng kỹ sư Nhật Bản.
Nhiệm vụ: viết bài đăng tuyển dụng bằng tiếng Việt để đăng vào nhiều nhóm Facebook khác nhau.

Quy tắc bắt buộc:
1. Mỗi bài PHẢI khác nhau thật sự — khác câu mở đầu, khác cách diễn đạt, không phải chỉ đổi vài từ. Đăng y hệt nhau vào nhiều nhóm là dấu hiệu spam rõ nhất, tuyệt đối tránh.
2. Không bịa thêm thông tin ngoài dữ liệu tin tuyển dụng được cung cấp.
3. Không viết nội dung chung chung, sáo rỗng kiểu quảng cáo — bài phải có thông tin cụ thể (vị trí, công ty, địa điểm... nếu có).
4. Giọng văn tự nhiên, thân thiện, như một người thật đang chia sẻ tin tuyển dụng, không phải giọng quảng cáo máy móc.

Bạn chỉ trả lời bằng JSON hợp lệ, không thêm bất kỳ chữ nào khác ngoài JSON."""


# --- Fallback template (unchanged from the pre-AI placeholder) --------------

_JOB_POST_OPENERS = [
    "[Tin tuyển dụng]",
    "Cơ hội việc làm mới:",
    "Thông tin tuyển dụng:",
]


def _draft_job_post_placeholder(job: dict, variant_seed: int = 0) -> str:
    attrs = job.get("attributes") or {}
    opener = _JOB_POST_OPENERS[variant_seed % len(_JOB_POST_OPENERS)]
    title = job.get("title") or attrs.get("jobField") or "vị trí đang tuyển"
    lines = [f"{opener} {title}"]
    if attrs.get("company"):
        lines.append(f"Công ty: {attrs['company']}")
    if attrs.get("location"):
        lines.append(f"Địa điểm: {attrs['location']}")
    if attrs.get("visaType"):
        lines.append(f"Visa: {attrs['visaType']}")
    if attrs.get("jlpt"):
        lines.append(f"Yêu cầu JLPT: {attrs['jlpt']}")
    salary = attrs.get("salary")
    if isinstance(salary, dict) and salary.get("min"):
        lines.append(
            f"Lương: {salary.get('min')}-{salary.get('max')} "
            f"{salary.get('currency', '')}/{salary.get('period', '')}"
        )
    if job.get("url"):
        lines.append(f"Chi tiết: {job['url']}")
    return "\n".join(lines)


def _fallback_variants(job: dict, groups: list["GroupRef"]) -> list[str]:
    """One variant per group, cycling through the opener list by GROUP
    index — not job index, which is the pre-AI version of this bug: with
    variant_seed keyed to the job's position in the fetched batch instead
    of the group's position, every group broadcast of the same job got
    the exact same opener (and the rest of the text is identical either
    way, since the template has no other source of variation)."""
    return [_draft_job_post_placeholder(job, variant_seed=idx) for idx in range(len(groups))]


# --- AI drafting --------------------------------------------------------

def _extract_json(text: str) -> Any:
    """Anthropic is asked to return raw JSON, but strip a ```json ... ```
    fence defensively in case the model wraps it anyway."""
    text = text.strip()
    if text.startswith("```"):
        text = text.split("\n", 1)[1] if "\n" in text else text
        if text.endswith("```"):
            text = text.rsplit("```", 1)[0]
        if text.startswith("json"):
            text = text[4:]
    return json.loads(text.strip())


def _job_summary(job: dict) -> dict:
    """Only the fields the model actually needs — keeps the prompt small
    and avoids leaking any side-B-internal fields (ids, timestamps...)
    into the drafted text."""
    attrs = job.get("attributes") or {}
    return {
        "title": job.get("title") or attrs.get("jobField"),
        "company": attrs.get("company"),
        "location": attrs.get("location"),
        "visa_type": attrs.get("visaType"),
        "jlpt": attrs.get("jlpt"),
        "salary": attrs.get("salary"),
        "url": job.get("url"),
    }


async def _draft_via_anthropic(job: dict, groups: list["GroupRef"], api_key: str) -> list[str]:
    group_names = [g.name or g.url for g in groups]
    user_prompt = (
        f"Tin tuyển dụng (JSON): {json.dumps(_job_summary(job), ensure_ascii=False)}\n\n"
        f"Viết {len(groups)} bài đăng KHÁC NHAU cho cùng tin tuyển dụng này, "
        f"mỗi bài dành cho một nhóm Facebook theo đúng thứ tự sau: "
        f"{json.dumps(group_names, ensure_ascii=False)}.\n\n"
        f'Trả lời DUY NHẤT bằng JSON dạng {{"posts": ["bài cho nhóm 1", "bài cho nhóm 2", ...]}} '
        f"— đúng {len(groups)} phần tử, đúng thứ tự nhóm ở trên, không thêm chữ nào khác."
    )

    model = os.environ.get("CONTENT_STRATEGIST_MODEL", "").strip() or DEFAULT_MODEL
    async with httpx.AsyncClient(timeout=60) as client:
        response = await client.post(
            ANTHROPIC_API_URL,
            headers={
                "x-api-key": api_key,
                "anthropic-version": "2023-06-01",
                "content-type": "application/json",
            },
            json={
                "model": model,
                "max_tokens": 2048,
                "system": _SYSTEM_PROMPT,
                "messages": [{"role": "user", "content": user_prompt}],
            },
        )
        response.raise_for_status()
        data = response.json()

    text = "".join(
        block.get("text", "") for block in data.get("content", []) if block.get("type") == "text"
    )
    parsed = _extract_json(text)
    posts = parsed["posts"] if isinstance(parsed, dict) else parsed
    if not isinstance(posts, list) or len(posts) != len(groups):
        raise ValueError(
            f"content_strategist: AI returned {len(posts) if isinstance(posts, list) else 'non-list'} "
            f"post(s), expected {len(groups)}"
        )
    cleaned = [str(p).strip() for p in posts]
    if any(not p for p in cleaned):
        raise ValueError("content_strategist: AI returned an empty post variant")
    return cleaned


async def draft_group_post_variants(job: dict, groups: list["GroupRef"]) -> list[str]:
    """One drafted post per group in `groups`, same order — genuinely
    different wording per group when an ANTHROPIC_API_KEY is configured
    and the call succeeds, else the pre-AI placeholder template (see
    module docstring for why this fallback is safe/silent by design)."""
    if not groups:
        return []

    api_key = os.environ.get("ANTHROPIC_API_KEY", "").strip()
    if not api_key:
        return _fallback_variants(job, groups)

    try:
        return await _draft_via_anthropic(job, groups, api_key)
    except Exception:  # noqa: BLE001 - any AI failure must fall back, never block scheduling
        logger.exception("content_strategist: AI draft failed, falling back to placeholder template")
        return _fallback_variants(job, groups)
