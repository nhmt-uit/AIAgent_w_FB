"""
Purpose of this file / Muc dich cua file nay:
EN: Drafts the actual wording for job posts broadcast to Facebook groups —
the one place in this project's pipeline where the same source material
genuinely needs to read differently more than once, since posting
identical text into several groups an account belongs to is the clearest
spam signal there is (see docs/agents/content-strategist.md, Guardrail
2). Posting to one's own profile (/admin/post) is user-typed by hand and
only happens once, so it is NOT drafted here and needs no variation — see
the conversation that scoped this file down to just the group-broadcast
case.

Two entry points, used at two different points in the pipeline (changed
2026-09-10 — see draft_single_post()'s docstring for the full reasoning):
- `template_variants(job, groups)` — called from human_bot/data_sync.py's
  sync_all() at SCHEDULE time (when a job is first fetched from side B),
  unconditionally, no AI, no API key needed. Fills every group's
  ScheduledTask.content with something reasonable to show in
  /admin/schedule immediately, and doubles as the fallback content that
  stays in place if AI drafting is off or fails later.
- `draft_single_post(job, group_name, ai_enabled)` — called from
  data_sync.py's fire_due_tasks() at FIRE time (right before ONE specific
  ScheduledTask actually posts), one call per task.
- `rewrite_candidate_reply(base_text, candidate, ai_enabled)` — added
  2026-09-10, a THIRD stage in the separate candidate-reply pipeline (see
  its own docstring): rewrites whatever text data_sync.py already has
  (side B's own /reply draft, or the local template) into fresh wording,
  same fire-time timing as draft_single_post().
All three that actually call the API do so through human_bot/ai_client.py's
call_ai_text() (added 2026-09-10, multi-provider — Anthropic/OpenAI/Gemini/
a custom OpenAI-compatible endpoint, whichever is selected on /admin/config's
AI tab) over httpx (already a project dependency, see requirements.txt)
rather than going through human_bot/llm.py's get_llm(), which pulls in the
(optional, not installed by default) browser-use package just to construct
a chat model client — too heavy for a single plain-text drafting call.

Which provider/key/model is "active" is resolved by
human_bot.runtime_config.get_active_ai_provider_config() — an
/admin/config-saved override per provider (added 2026-09-10) if one is
set, else the ANTHROPIC_API_KEY/OPENAI_API_KEY env var for those two
providers.

Safe-by-default: if ai_enabled is False, no AI provider key is configured, or
the API call fails or returns something unusable (wrong variant count,
empty string, bad JSON, over length), draft_single_post() silently falls
back to the same plain-template drafting template_variants() already
uses. Every task drafted either way is still staged in /admin/schedule
for human review before it fires (DataSyncConfig.auto_fire_enabled
defaults False) — this file only changes what the drafted text says, not
the safety gate around actually posting it.
VI: Soan noi dung that cho tin tuyen dung duoc dang vao nhom Facebook —
noi duy nhat trong pipeline nay thuc su can noi dung khac nhau nhieu lan,
vi dang y het chu vao nhieu nhom cung tai khoan la dau hieu spam ro nhat
(xem docs/agents/content-strategist.md, Guardrail 2). Dang len tuong ca
nhan (/admin/post) la nguoi dung tu go tay va chi dang 1 lan, nen KHONG
can bien tau va khong xu ly o day.

2 diem vao, dung o 2 thoi diem khac nhau trong pipeline (doi 2026-09-10):
template_variants() chay luc len lich (khong AI), draft_single_post()
chay luc den gio dang thuc su (co AI neu duoc bat + co key), xem docstring
cua draft_single_post() de biet ly do doi.
"""
from __future__ import annotations

import json
import logging
import random
from typing import TYPE_CHECKING, Any

from human_bot.ai_client import call_ai_text
from human_bot.runtime_config import get_active_ai_provider_config

if TYPE_CHECKING:
    from human_bot.config import GroupRef

logger = logging.getLogger("human_bot.content_strategist")

# Rewritten 2026-09-10 to fold in the same business rules the fallback
# template (_draft_job_post_placeholder) already enforces mechanically —
# no link, man/lá/tờ/m for JPY month/year salary, visa named instead of
# a raw code, unclear visa/salary invites a DM instead of silence — but
# stated as guidance for the model to write FREELY around, not a literal
# line-by-line structure to fill in. The point of paying for an AI call
# here at all is natural, varied prose; forcing it back into the
# template's exact line shape would defeat that. `url` is deliberately
# not even included in _job_summary() below — rule 5 alone was judged
# not reliable enough on its own to guarantee no link ever appears.
_SYSTEM_PROMPT = """Bạn là Content Strategist Agent cho một trang Facebook tuyển dụng kỹ sư Nhật Bản.
Nhiệm vụ: viết bài đăng tuyển dụng bằng tiếng Việt để đăng vào nhiều nhóm Facebook khác nhau.

Quy tắc bắt buộc:
1. Mỗi bài PHẢI khác nhau thật sự — khác câu mở đầu, khác cách diễn đạt, không phải chỉ đổi vài từ. Đăng y hệt nhau vào nhiều nhóm là dấu hiệu spam rõ nhất, tuyệt đối tránh.
2. Không bịa thêm thông tin ngoài dữ liệu tin tuyển dụng được cung cấp.
3. Không viết nội dung chung chung, sáo rỗng kiểu quảng cáo — bài phải có thông tin cụ thể (vị trí, công ty, địa điểm... nếu có).
4. Giọng văn tự nhiên, thân thiện, như một người thật đang chia sẻ tin tuyển dụng, không phải giọng quảng cáo máy móc.
5. TUYỆT ĐỐI KHÔNG chèn link/URL vào bài đăng. Nếu muốn mời người đọc tìm hiểu thêm, hãy viết một câu mời nhắn tin/inbox trực tiếp, không bao giờ dán link.
6. Lương (nếu có trong dữ liệu) và tính theo THÁNG hoặc NĂM bằng yên (JPY): đổi sang đơn vị "man" (chia số tiền cho 10.000) rồi gọi bằng một trong các từ "man", "m", "lá", hoặc "tờ" — tự chọn linh hoạt, không cần cố định một từ (ví dụ 250000 JPY/tháng có thể viết "25 lá/tháng", "25 man/tháng"...). Lương theo GIỜ hoặc NGÀY thì giữ nguyên số yên gốc, không đổi qua man.
7. Visa (nếu có trong dữ liệu): đừng in nguyên mã kỹ thuật khó hiểu (ví dụ "gijinkoku") một cách máy móc — có thể gọi bằng chính mã đó (viết hoa chữ đầu, mã gốc vẫn là một lựa chọn hợp lệ, không phải luôn luôn phải đổi), một tên tiếng Việt thông dụng, hoặc tên tiếng Nhật (kanji) nếu biết — ví dụ mã "gijinkoku" (đầy đủ là 技術・人文知識・国際業務) có thể gọi "Gijinkoku", "Visa Kỹ Sư", hoặc dùng nguyên kanji. Nếu là mã khác không chắc, cứ viết hoa chữ đầu mã gốc.
8. Nếu dữ liệu KHÔNG có visa hoặc KHÔNG có lương: đừng bỏ trống im lặng không nhắc gì — viết một câu ngắn mời nhắn tin/inbox để trao đổi thêm về đúng phần đang thiếu đó.
9. Mỗi bài dài tối đa khoảng 500 ký tự — đủ thông tin cụ thể nhưng không lan man, dài dòng.
10. Câu MỞ ĐẦU và câu KẾT của mỗi bài là phần người đọc chú ý nhất khi lướt Facebook — phải thu hút, có sức gợi, tránh mở đầu/kết câu sáo rỗng rập khuôn.

Bạn chỉ trả lời bằng JSON hợp lệ, không thêm bất kỳ chữ nào khác ngoài JSON."""

# Hard safety cap enforced in code (not just the soft ~500-char guidance
# in the prompt above) — an AI response wildly over this is treated as a
# bad result and falls back to the template, same as an empty string or
# wrong variant count already do below.
_MAX_AI_POST_LENGTH = 800


# --- Fallback template ---------------------------------------------------
# Rewritten 2026-09-10 per explicit rules from the project owner, replacing
# the original 3-opener/link-in-post version. Kept deterministic-by-group
# (variant_seed = the group's index, see _fallback_variants below) for the
# opener only — every other piece of variation (the "info còn thiếu" line,
# the closing CTA) uses real random.choice(), since those don't need the
# same-job-different-groups distinctness guarantee the opener rotation
# exists for.

# 5-10 recruitment-style openers to rotate through — replaces the old
# fixed "[Tin tuyển dụng]" bracket-and-colon style entirely.
_JOB_POST_OPENERS = [
    "TÌM ĐỒNG ĐỘI",
    "TÌM NHÂN SỰ",
    "TÌM NHÂN TÀI",
    "TÌM ỨNG VIÊN",
    "TUYỂN GẤP",
    "TIN TUYỂN DỤNG",
    "CƠ HỘI VIỆC LÀM",
    "CẦN TUYỂN",
]

# "<opener> - <title>" fits on one line up to this many characters; past
# it, splits into "<opener>" then "<title>" on their own lines instead
# (still no "-" once split — the dash only makes sense joining a single
# line, not separating two).
_HEADER_MAX_LEN = 65

# NEVER include the job's URL in the post body (owner's explicit rule,
# 2026-09-10) — a bare Facebook link inside a group post reads as spam/
# scraped content; these invite a DM instead, picked at random so 10
# broadcasts of different jobs don't all end identically.
_CONTACT_CTA = [
    "Nhắn tin mình để biết thêm chi tiết nha",
    "Inbox mình để được tư vấn kỹ hơn",
    "Ai quan tâm nhắn tin mình nhé",
    "Cần thêm thông tin thì ib mình nha",
    "Liên hệ mình qua inbox để rõ hơn",
    "Ai cần thì nhắn tin mình trao đổi thêm nha",
    "Muốn ứng tuyển thì ib mình nha",
    "Nhắn tin mình để mình gửi thêm thông tin",
    "Quan tâm thì để lại tin nhắn nha",
    "Ib mình để nhận thông tin chi tiết",
]

# When visa and/or lương is missing from side B's attributes, both get
# folded into ONE line naming what's unclear plus a short "trao đổi
# thêm" nudge — instead of just silently omitting each missing field
# with nothing said about it. jlpt is deliberately NOT part of this
# (owner's explicit call, 2026-09-10): a missing jlpt value still just
# omits its own line, same as before.
_MISSING_INFO_LABELS = {"visa": "visa", "salary": "lương"}
_MISSING_INFO_SUFFIXES = [
    "nhắn tin thêm nha",
    "trao đổi thêm nhé",
    "ib để biết thêm",
    "để lại tin nhắn mình gửi thêm nha",
    "nhắn mình để rõ hơn",
]

_SALARY_PERIOD_LABELS = {"month": "tháng", "hour": "giờ", "day": "ngày", "year": "năm"}

# Random label for the "địa điểm" line, picked fresh per post so a batch
# of jobs doesn't all read with the exact same word (2026-09-10, owner's
# request).
_LOCATION_LABELS = ["Địa điểm", "Địa điểm làm việc", "Địa chỉ", "Vị trí", "Nơi làm việc", "Khu vực làm việc"]

# side B's visaType is a bare code (e.g. "gijinkoku") — not something a
# Vietnamese jobseeker audience recognizes on sight. Each code maps to a
# few interchangeable ways people actually refer to it: the code itself
# capitalized, a common Vietnamese nickname, and the official Japanese
# term — one is picked at random per post. Extend this dict as new
# visaType codes show up in real side-B data; an unknown code just prints
# as-is (capitalized), same as before this feature existed.
_VISA_TYPE_NAMES: dict[str, list[str]] = {
    "gijinkoku": ["Gijinkoku", "Kỹ Sư", "技術・人文知識・国際業務"],
    "tokutei": ["Tokutei", "Kỹ Năng Đặc Định", "特定技能"],
    "ginou": ["Ginou", "Kỹ Năng", "技能"],
    "jisshu": ["Thực Tập Sinh", "TITP", "技能実習"],
    "kenshu": ["Thực Tập Sinh", "TITP", "技能実習"],
    "eijuu": ["Vĩnh Trú", "永住者"],
    "teijuu": ["Định Trú", "定住者"],
    "koudo_jinzai": ["Nhân Lực Chất Lượng Cao", "高度専門職"],
}

# "{name}" is filled with one of the names above — some templates put
# "Visa"/a prefix before it with a colon, others write it inline with no
# colon at all (owner's explicit example: "Visa Gijinkoku"), so the mix
# doesn't read as one rigid rule every single time.
_VISA_LINE_TEMPLATES = [
    "Visa: {name}",
    "Loại visa: {name}",
    "Hỗ trợ Visa: {name}",
    "Visa {name}",
]


def _visa_line(visa_code: str) -> str:
    names = _VISA_TYPE_NAMES.get(str(visa_code).strip().lower())
    name = random.choice(names) if names else str(visa_code).strip().capitalize()
    return random.choice(_VISA_LINE_TEMPLATES).format(name=name)


# Random label for the "lương" line — "Về tay" reads like colloquial
# take-home-pay phrasing, so it's paired with the "khoảng"/"~" template
# pools below rather than the full general pool ("từ X đến Y", "trên X"
# don't read naturally after "Về tay").
_SALARY_LABELS = ["Lương", "Mức lương", "Thu nhập", "Đãi ngộ", "Về tay"]
_SALARY_ABOUT_ONLY_LABEL = "Về tay"

# "Nenshuu"/"年収" (Japanese for annual income) — added 2026-09-10 per
# owner request, common loanwords in Vietnamese-for-Japan-jobs communities
# (same spirit as the visa kanji in _VISA_TYPE_NAMES below). ONLY valid
# for period == "year" — unlike the general pool above, calling a monthly
# or hourly wage "Nenshuu" would be factually wrong, not just a style
# choice, so this extends (not replaces) _SALARY_LABELS only when the
# salary is actually annual.
_SALARY_LABELS_YEAR_EXTRA = ["Nenshuu", "年収"]

# Vietnamese slang for 万 (10,000 yên) — used instead of the bare number
# whenever the amount is actually in yên and the pay period is month/year
# (an hourly/daily wage like "1400 yên/giờ" stays as a plain number; only
# a monthly/yearly figure is large enough that man/lá/tờ reads naturally
# — see _MAN_PERIOD_KEYS).
_MAN_WORDS = ["lá", "tờ", "man", "m"]
_MAN_PERIOD_KEYS = {"month", "year"}

_SALARY_RANGE_TEMPLATES = [
    "từ {lo} đến {hi}", "{lo}-{hi}", "khoảng {lo}-{hi}", "{lo}~{hi}", "dao động {lo}-{hi}", "tầm {lo}-{hi}",
]
_SALARY_RANGE_TEMPLATES_ABOUT = ["khoảng {lo}-{hi}", "{lo}~{hi}"]
_SALARY_MIN_TEMPLATES = ["từ {lo}", "trên {lo}", "khoảng {lo}"]
_SALARY_MIN_TEMPLATES_ABOUT = ["khoảng {lo}", "~{lo}"]
_SALARY_MAX_TEMPLATES = ["tới {hi}", "dưới {hi}", "khoảng {hi}"]
_SALARY_MAX_TEMPLATES_ABOUT = ["khoảng {hi}", "~{hi}"]


def _format_man(amount: float) -> str:
    """`250000` yên -> `"25"` (man/lá/tờ) — `1.5` for a half-man amount
    like `15000`, never a trailing `.0` for a whole number."""
    man = amount / 10000
    if man == int(man):
        return str(int(man))
    return f"{man:.1f}"


def _salary_line(salary: Any) -> str | None:
    """Full "<label>: <value phrase>" line, or None if salary is missing/
    unusable (caller then treats "lương" as one of the missing-info
    fields — see _MISSING_INFO_LABELS). Never emits a literal "None" the
    way the original f-string version did when only one of min/max was
    set."""
    if not isinstance(salary, dict):
        return None
    lo, hi = salary.get("min"), salary.get("max")
    if not lo and not hi:
        return None

    currency = (salary.get("currency") or "JPY").upper()
    period = salary.get("period") or ""

    label_pool = _SALARY_LABELS + _SALARY_LABELS_YEAR_EXTRA if period == "year" else _SALARY_LABELS
    label = random.choice(label_pool)
    about_only = label == _SALARY_ABOUT_ONLY_LABEL

    if currency == "JPY" and period in _MAN_PERIOD_KEYS:
        # Real yên amounts convert to man/lá/tờ — this is what side B's
        # min/max are actually denominated in (plain yên, e.g. 250000),
        # not already-in-man numbers, so the /10000 conversion here is
        # required, not cosmetic.
        man_word = random.choice(_MAN_WORDS)
        lo_s = _format_man(lo) if lo else None
        hi_s = _format_man(hi) if hi else None
        unit = f" {man_word}/{_SALARY_PERIOD_LABELS.get(period, period)}"
    else:
        # Hourly/daily wages (too small for man/lá/tờ to read naturally)
        # or a non-JPY currency — keep the plain amount + unit as before.
        lo_s = str(lo) if lo else None
        hi_s = str(hi) if hi else None
        period_label = _SALARY_PERIOD_LABELS.get(period, period)
        unit = f" {currency}/{period_label}".rstrip("/")

    if lo_s and hi_s:
        templates = _SALARY_RANGE_TEMPLATES_ABOUT if about_only else _SALARY_RANGE_TEMPLATES
        value = random.choice(templates).format(lo=lo_s, hi=hi_s)
    elif lo_s:
        templates = _SALARY_MIN_TEMPLATES_ABOUT if about_only else _SALARY_MIN_TEMPLATES
        value = random.choice(templates).format(lo=lo_s)
    else:
        templates = _SALARY_MAX_TEMPLATES_ABOUT if about_only else _SALARY_MAX_TEMPLATES
        value = random.choice(templates).format(hi=hi_s)

    return f"{label}: {value}{unit}"


def _join_list_or_str(value: Any) -> str:
    """Side B's own attributes (jobField, location...) come back as a
    list some of the time (e.g. `["Shizuoka"]`) and a bare string other
    times — joining defensively here is what stops a value like that
    landing in the actual post text as literal Python repr
    (`['Shizuoka']`, brackets/quotes and all), which is exactly what the
    unguarded f-string interpolation used to do before this rewrite."""
    if isinstance(value, list):
        return ", ".join(str(v) for v in value if v)
    return str(value) if value else ""


def _draft_job_post_placeholder(job: dict, variant_seed: int = 0) -> str:
    attrs = job.get("attributes") or {}
    opener = _JOB_POST_OPENERS[variant_seed % len(_JOB_POST_OPENERS)]
    title = _join_list_or_str(job.get("title") or attrs.get("jobField")) or "vị trí đang tuyển"

    header = f"{opener} - {title}"
    lines = [header] if len(header) <= _HEADER_MAX_LEN else [opener, title]

    company = _join_list_or_str(attrs.get("company"))
    if company:
        lines.append(f"Công ty: {company}")
    location = _join_list_or_str(attrs.get("location"))
    if location:
        lines.append(f"{random.choice(_LOCATION_LABELS)}: {location}")

    visa = attrs.get("visaType")
    if visa:
        lines.append(_visa_line(visa))
    jlpt = attrs.get("jlpt")
    if jlpt:
        lines.append(f"Yêu cầu JLPT: {jlpt}")
    salary_text = _salary_line(attrs.get("salary"))
    if salary_text:
        lines.append(salary_text)

    missing = [
        label for key, label in _MISSING_INFO_LABELS.items()
        if not (visa if key == "visa" else salary_text)
    ]
    if missing:
        lines.append(f"Thông tin {'/'.join(missing)} — {random.choice(_MISSING_INFO_SUFFIXES)}")

    lines.append(random.choice(_CONTACT_CTA))
    return "\n".join(lines)


def template_variants(job: dict, groups: list["GroupRef"]) -> list[str]:
    """One template-drafted variant per group, cycling through the opener
    list by GROUP index — not job index, which is the pre-AI version of
    this bug: with variant_seed keyed to the job's position in the
    fetched batch instead of the group's position, every group broadcast
    of the same job got the exact same opener (and the rest of the text
    is identical either way, since the template has no other source of
    variation).

    Public (not `_fallback_variants`, its name until 2026-09-10) — this
    is now called directly and unconditionally from data_sync.py's
    sync_all() at SCHEDULE time (see that function's docstring for why AI
    no longer runs there at all), not just as an AI-failure fallback."""
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
    into the drafted text. `url` is deliberately excluded (2026-09-10,
    not an oversight) — rule 5 in _SYSTEM_PROMPT already says never to
    link it, but not giving the model the URL at all is a stronger
    guarantee than an instruction alone: it can't paste what it was
    never handed."""
    attrs = job.get("attributes") or {}
    return {
        "title": job.get("title") or attrs.get("jobField"),
        "company": attrs.get("company"),
        "location": attrs.get("location"),
        "visa_type": attrs.get("visaType"),
        "jlpt": attrs.get("jlpt"),
        "salary": attrs.get("salary"),
    }


async def _draft_via_ai(job: dict, groups: list["GroupRef"]) -> list[str]:
    group_names = [g.name or g.url for g in groups]
    user_prompt = (
        f"Tin tuyển dụng (JSON): {json.dumps(_job_summary(job), ensure_ascii=False)}\n\n"
        f"Viết {len(groups)} bài đăng KHÁC NHAU cho cùng tin tuyển dụng này, "
        f"mỗi bài dành cho một nhóm Facebook theo đúng thứ tự sau: "
        f"{json.dumps(group_names, ensure_ascii=False)}.\n\n"
        f'Trả lời DUY NHẤT bằng JSON dạng {{"posts": ["bài cho nhóm 1", "bài cho nhóm 2", ...]}} '
        f"— đúng {len(groups)} phần tử, đúng thứ tự nhóm ở trên, không thêm chữ nào khác."
    )

    text = await call_ai_text(_SYSTEM_PROMPT, user_prompt, max_tokens=2048)
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
    if any(len(p) > _MAX_AI_POST_LENGTH for p in cleaned):
        # The ~500-char target in _SYSTEM_PROMPT is a soft ask the model
        # can ignore — this is the hard backstop, same "never trust the
        # AI output blindly" stance as the empty-string/wrong-count
        # checks above. Falls back to the template rather than posting
        # something that ran far past what was asked for.
        raise ValueError(
            f"content_strategist: AI returned a post over {_MAX_AI_POST_LENGTH} chars "
            f"(longest: {max(len(p) for p in cleaned)})"
        )
    return cleaned


async def draft_single_post(
    job: dict, existing_content: str, group_name: str | None = None, ai_enabled: bool = True,
) -> str:
    """AI-drafted text for exactly ONE post to ONE group — the fire-time
    counterpart of the removed `draft_group_post_variants` (batch, one
    call across every group of a job at once). 2026-09-10: AI drafting
    moved from SCHEDULE time (data_sync.py's sync_all(), when a job is
    first fetched from side B) to FIRE time (data_sync.py's
    fire_due_tasks(), right before this one ScheduledTask actually
    posts) per the project owner's explicit request — mirroring how
    _fetch_candidate_reply() already works for candidate replies (side B
    only runs ITS Claude call when that endpoint is hit, at fire time,
    for the same "don't pay for a draft that might get cancelled/
    rescheduled before it ever posts" reason).

    Trade-off the owner explicitly accepted: the old batch call's
    guarantee that N groups broadcasting the same job get GENUINELY
    different wording (all N drafted together in one prompt, so the
    model could see and avoid repeating itself) is gone — each group's
    post is now drafted independently, at its own randomly-spaced fire
    time, with no visibility into what any sibling group's post says.
    Live-tested 2026-09-10 against two real separate calls for the same
    job and still read naturally different call to call, but this is no
    longer an enforced guarantee, just an observed tendency.

    `existing_content` is whatever is ALREADY on the ScheduledTask —
    the template drafted at schedule time, or an admin's own hand-edit
    made on /admin/schedule before this task fired. Returned UNCHANGED
    whenever AI isn't used at all (2026-09-10, fixing a real gotcha
    reported by the project owner: this function used to fall back to a
    freshly-random `_draft_job_post_placeholder()` call on AI failure,
    silently discarding whatever an admin had manually edited into the
    schedule — same "never lose what's already there" stance
    rewrite_candidate_reply() already takes with `base_text`).

    `ai_enabled` is DataSyncConfig.job_post_ai_enabled, the /admin/config
    toggle — kept as a plain parameter (not read from runtime_config
    directly) so this module stays testable/callable without that whole
    config layer. `group_name` is best-effort display text only (e.g.
    human_bot.agent.resolve_group_name()'s result) — a None/empty value
    just means the model gets no group name to personalize around."""
    if not ai_enabled:
        return existing_content

    if not get_active_ai_provider_config().api_key:
        return existing_content

    from human_bot.config import GroupRef  # runtime import — module-level is TYPE_CHECKING-only above

    try:
        posts = await _draft_via_ai(job, [GroupRef(name=group_name or "", url="")])
        return posts[0]
    except Exception:  # noqa: BLE001 - any AI failure must fall back, never block scheduling
        logger.exception("content_strategist: AI draft failed, keeping existing schedule content")
        return existing_content


# NOT CALLED ANYWHERE as of 2026-09-10 — superseded by draft_single_post()
# above when AI drafting moved from schedule-time to fire-time (see that
# function's docstring for the full reasoning/trade-off). Kept, not
# deleted, per the project owner's explicit request (2026-09-10) — this
# is the one call that guarantees N groups broadcasting the same job get
# GENUINELY different wording (all drafted together in one prompt), which
# draft_single_post()'s independent per-group calls no longer guarantee.
# If that guarantee ever needs to come back (e.g. AI re-enabled at
# schedule time instead of fire time), this is a working, tested
# starting point — not a reconstruction from scratch.
async def draft_group_post_variants(
    job: dict, groups: list["GroupRef"], ai_enabled: bool = True,
) -> list[str]:
    """One drafted post per group in `groups`, same order — genuinely
    different wording per group when the active AI provider has a key
    configured, `ai_enabled` is True, and the call succeeds; else the
    pre-AI placeholder template (see module docstring for why this
    fallback is safe/silent by design).

    `ai_enabled` is DataSyncConfig.job_post_ai_enabled, the /admin/config
    toggle — kept as a plain parameter here rather than reading
    runtime_config itself, so this module stays testable/callable without
    needing that whole config layer. Checked BEFORE the API key so
    flipping it off skips even looking at the key."""
    if not groups:
        return []
    if not ai_enabled:
        return template_variants(job, groups)

    if not get_active_ai_provider_config().api_key:
        return template_variants(job, groups)

    try:
        return await _draft_via_ai(job, groups)
    except Exception:  # noqa: BLE001 - any AI failure must fall back, never block scheduling
        logger.exception("content_strategist: AI draft failed, falling back to placeholder template")
        return template_variants(job, groups)


# --- Candidate reply rewriting -------------------------------------------
# Third stage of the candidate-reply pipeline, run at FIRE time in
# data_sync.py's fire_due_tasks(). Stage 2 and stage 3 are MUTUALLY
# EXCLUSIVE (changed 2026-09-10, same day this stage was added) — never
# both called for the same candidate, so a candidate never gets billed
# against both side B's Claude call AND our own AI-provider call for one
# reply:
#   1. The local template (data_sync._draft_candidate_reply_placeholder)
#      — drafted at SCHEDULE time, stashed as ScheduledTask.content.
#      Starting baseline every candidate gets; also the final fallback if
#      whichever of stage 2/3 actually runs produces nothing.
#   2. data_sync._fetch_candidate_reply() — side B's own GET
#      /api/candidates/{id}/reply. Called ONLY when stage 3 will NOT run
#      (DataSyncConfig.candidate_reply_ai_enabled is False, OR it's True
#      but content_strategist.ai_provider_configured() is False — no
#      point calling side B's paid drafting call AND skipping our own
#      cheaper rewrite for lack of a key; call side B instead in that
#      case). Replaces stage 1's text if it returns one.
#   3. rewrite_candidate_reply() below — OUR OWN AI-provider call (whichever
#      provider is active on /admin/config's AI tab), run ONLY when
#      candidate_reply_ai_enabled is True AND that provider actually has a
#      key configured; rewrites stage 1's template (stage 2 is skipped
#      entirely in this case, so there is no side-B text to rewrite) into
#      fresh wording. Exists because stage 1 only ever recycles the same
#      10 fixed templates — this stage is what actually guarantees each
#      posted comment reads uniquely, the same anti-spam motivation
#      draft_single_post() serves for job posts.

_CANDIDATE_REPLY_SYSTEM_PROMPT = """Bạn là một người thật đang bình luận dưới bài đăng tìm việc của một ứng viên trong nhóm Facebook.
Nhiệm vụ: viết LẠI một bản nháp bình luận có sẵn, mời ứng viên đó nhắn tin/inbox để trao đổi thêm về cơ hội việc làm.

Quy tắc bắt buộc:
1. Giữ đúng Ý CHÍNH của bản nháp (mời nhắn tin/inbox trao đổi thêm) — không đổi ý nghĩa, không bịa thêm thông tin cụ thể (tên công ty, mức lương, địa chỉ, số điện thoại...) ngoài dữ liệu được cung cấp.
2. Cách diễn đạt PHẢI khác bản nháp — không chỉ đổi vài từ. Đăng lại gần như y nguyên một mẫu câu cố định nhiều lần cho nhiều người là dấu hiệu spam rõ nhất, tuyệt đối tránh.
3. Giọng văn tự nhiên, thân thiện, ngắn gọn như một bình luận thật của một người — không phải giọng quảng cáo.
4. TUYỆT ĐỐI KHÔNG chèn link/URL.
5. Tối đa khoảng 200 ký tự.

Bạn chỉ trả lời bằng JSON hợp lệ dạng {"reply": "..."} không thêm bất kỳ chữ nào khác ngoài JSON."""

# Hard safety cap (same "never trust the AI output blindly" stance as
# _MAX_AI_POST_LENGTH above) — the ~200-char target in the prompt is soft.
_MAX_CANDIDATE_REPLY_LENGTH = 400


def ai_provider_configured() -> bool:
    """True if the currently active AI provider (/admin/config's AI tab —
    human_bot.runtime_config.get_active_ai_provider_config(), generalized
    2026-09-10 from the original Anthropic-only anthropic_key_configured())
    has an API key available. The single source of truth for that check,
    used by both draft_single_post()/rewrite_candidate_reply() themselves
    AND by data_sync.py's fire_due_tasks(), which needs to know this
    BEFORE deciding whether to even call side B's own /reply endpoint for
    a candidate (see rewrite_candidate_reply()'s docstring, "stage 2 vs.
    stage 3 are now mutually exclusive")."""
    return bool(get_active_ai_provider_config().api_key)


async def rewrite_candidate_reply(
    base_text: str, candidate: dict | None = None, ai_enabled: bool = True,
) -> str:
    """Rewrites `base_text` (whatever data_sync.py already has for this
    candidate — side B's own reply draft, or the local template) into
    fresh wording via the active AI provider, grounded on `candidate`'s
    attributes (desiredJobField/preferredRegion — see schedule_store.
    ScheduledTask.candidate_data's docstring for its shape) so the rewrite
    still makes sense for this specific person, not a generic paraphrase.

    Returns `base_text` UNCHANGED (never raises, never returns empty) if
    `ai_enabled` is False, no AI provider key is configured, `base_text`
    itself is falsy, or the API call fails/returns something unusable —
    same safe-by-default stance as draft_single_post()."""
    if not ai_enabled or not base_text:
        return base_text

    if not get_active_ai_provider_config().api_key:
        return base_text

    attrs = (candidate or {}).get("attributes") or {}
    context = {
        "ban_nhap_hien_tai": base_text,
        "ung_vien_muon_lam": attrs.get("desiredJobField"),
        "khu_vuc_mong_muon": attrs.get("preferredRegion"),
    }
    user_prompt = (
        f"Dữ liệu (JSON): {json.dumps(context, ensure_ascii=False)}\n\n"
        f'Viết lại "ban_nhap_hien_tai" theo đúng quy tắc đã nêu. '
        f'Trả lời DUY NHẤT bằng JSON dạng {{"reply": "..."}}, không thêm chữ nào khác.'
    )

    try:
        text = await call_ai_text(_CANDIDATE_REPLY_SYSTEM_PROMPT, user_prompt, max_tokens=512)
        parsed = _extract_json(text)
        reply = parsed.get("reply") if isinstance(parsed, dict) else None
        reply = str(reply).strip() if reply else ""
        if not reply:
            raise ValueError("content_strategist: candidate reply rewrite returned empty")
        if len(reply) > _MAX_CANDIDATE_REPLY_LENGTH:
            raise ValueError(
                f"content_strategist: candidate reply rewrite over {_MAX_CANDIDATE_REPLY_LENGTH} "
                f"chars (got {len(reply)})"
            )
        return reply
    except Exception:  # noqa: BLE001 - any AI failure must fall back, never block posting
        logger.exception("content_strategist: candidate reply AI rewrite failed, keeping existing draft")
        return base_text
