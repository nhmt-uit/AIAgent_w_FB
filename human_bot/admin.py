"""
Purpose of this file / Muc dich cua file nay:
EN: Local-only web admin UI, mounted into human_bot/service.py's FastAPI
app under /admin. Two things it replaces: (1) editing HUMAN_TYPING_* values
in .env and restarting the process — now a form that writes
runtime_config.json and takes effect on the very next post; (2) typing
post content as a terminal command-line argument — now a textarea. This page has real
Facebook-posting power (it calls the exact same run_task() as the /tasks
API n8n uses), so it is protected with HTTP Basic Auth when ADMIN_USERNAME
and ADMIN_PASSWORD are set in .env, and should never be exposed to the
public internet — see docs/architecture.md.
VI: Giao dien quan tri web, chi dung noi bo, duoc gan vao ung dung FastAPI
cua human_bot/service.py duoi duong dan /admin. No thay the hai viec:
(1) sua cac gia tri HUMAN_TYPING_* trong .env roi khoi dong lai tien
trinh — gio la mot form ghi vao runtime_config.json va co hieu luc ngay
tu lan dang bai tiep theo; (2) go noi dung bai dang truc tiep trong tham
so dong lenh terminal — gio la mot o textarea. Trang nay co quyen dang bai that len Facebook (no
goi dung ham run_task() giong het API /tasks ma n8n dung), nen duoc bao
ve bang HTTP Basic Auth khi ADMIN_USERNAME va ADMIN_PASSWORD duoc dat
trong .env, va khong duoc phep mo ra internet cong khai — xem
docs/architecture.md.

Ghi chu ve redesign (2026): giao dien duoc lam lai (CSS/HTML) de de nhin
va de dung hon, nhung TOAN BO logic route/form-field-name/POST handler
giu nguyen 100% — chi phan trinh bay (presentation) thay doi.

Ghi chu ve nang cap UI dot 2 (2026-09-04): chuyen sang Tailwind CDN
(https://cdn.tailwindcss.com, dung "Play CDN" — khong can build step,
khong can Node) cho toan bo phan nhin, va htmx
(https://unpkg.com/htmx.org) cho cac trang co bang/CRUD (Nhom da tham
gia, Lich dang, Bao cao) de sua/xoa/loc khong phai tai lai ca trang.
Van la Python/FastAPI render san HTML — khong tach React, khong co API
JSON rieng. Moi ten class CSS cu (card, field-row, data-table, ...) van
giu nguyen va duoc dinh nghia lai bang Tailwind @apply trong _PAGE_STYLE,
nen phan lon HTML sinh ra o duoi khong doi — chi doi cach cac class do
duoc ve.
"""
import asyncio
import dataclasses
import html
import json
import os
import random
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path

from human_bot import bootstrap_login_sessions, db, schedule_store, screenshots
from human_bot.agent import TaskRequest, run_task
from human_bot.config import (
    ACCOUNT_AGE_TIERS,
    AccountStatus,
    GroupRef,
    RateLimits,
    get_all_accounts,
    new_group_id,
)
from human_bot.data_sync import apply_quiet_hours, get_all_sync_statuses, _format_attr
from human_bot.data_sync_config import DataSyncConfig
from human_bot.scheduling_config import SchedulingConfig
from human_bot.media import MediaConfig
from human_bot.humanize import HumanMouseConfig, HumanPacingConfig, HumanScrollConfig, HumanTypingConfig
from human_bot.runtime_config import (
    EDITABLE_HUMAN_TYPING_FIELDS,
    EDITABLE_PACING_FIELDS,
    EDITABLE_MOUSE_FIELDS,
    EDITABLE_SCROLL_FIELDS,
    EDITABLE_DATA_SYNC_FIELDS,
    EDITABLE_SCHEDULING_FIELDS,
    EDITABLE_MEDIA_FIELDS,
    EDITABLE_SAFETY_COOLDOWN_FIELDS,
    get_data_sync_config,
    get_scheduling_config,
    get_human_typing_overrides,
    get_pacing_overrides,
    get_mouse_overrides,
    get_scroll_overrides,
    get_data_sync_overrides,
    get_scheduling_overrides,
    get_media_overrides,
    get_safety_cooldown_overrides,
    save_safety_cooldown_overrides,
    get_joined_groups,
    get_registered_accounts,
    save_human_typing_overrides,
    save_pacing_overrides,
    save_mouse_overrides,
    save_scroll_overrides,
    save_data_sync_overrides,
    save_scheduling_overrides,
    save_media_overrides,
    save_joined_groups,
    save_registered_account,
    delete_registered_account,
    set_account_paused,
    set_account_removed,
    resume_account,
    get_pause_info,
    get_resume_cooldown_info,
    clear_resume_cooldown,
    get_account_age_tier,
    set_account_age_tier,
    clear_account_age_tier,
    DEFAULT_ACCOUNT_AGE_TIER,
    get_rate_limits_overrides,
    save_rate_limits_overrides,
    EDITABLE_RATE_LIMITS_FIELDS,
    get_sync_disabled_account_ids,
    set_account_sync_enabled,
    get_secrets_config,
    save_secrets_overrides,
    get_active_ai_provider_config,
)
from human_bot.safety_cooldown_config import SafetyCooldownConfig

router = APIRouter(prefix="/admin", tags=["admin"])
_security = HTTPBasic(auto_error=False)

# Human-readable Vietnamese labels for internal snake_case keys shown
# anywhere in the admin UI (dropdowns, tables) — the raw key (e.g.
# "post_to_group") is still what gets submitted/stored, this only changes
# what a person reads on screen. Includes actions not implemented in
# human_bot/actions.py yet so the label is ready the moment they are.
_ACTION_LABELS: dict[str, str] = {
    "post_to_own_profile": "Đăng lên tường cá nhân",
    "post_to_group": "Đăng vào nhóm",
    "comment_on_friend_post": "Comment bài bạn bè",
    "comment_on_group_post": "Comment bài trong nhóm",
    "like_post": "Thích bài viết",
    "read_recent_comments": "Đọc comment gần đây",
}

# Icon + Tailwind color pair per action, so "Đăng vào nhóm" and "Comment
# bài trong nhóm" (easy to confuse at a glance, both group-related) read
# as visually distinct badges instead of same-weight plain text — added
# after a request to make /admin/schedule items easier to scan quickly.
_ACTION_BADGE_STYLE: dict[str, tuple[str, str]] = {
    "post_to_own_profile": ("🧑", "bg-blue-50 text-blue-600"),
    "post_to_group": ("👥", "bg-purple-50 text-purple-600"),
    "comment_on_group_post": ("💬", "bg-emerald-50 text-emerald-600"),
    "comment_on_friend_post": ("💬", "bg-teal-50 text-teal-600"),
    "like_post": ("👍", "bg-amber-50 text-amber-600"),
    "read_recent_comments": ("👀", "bg-gray-100 text-gray-600"),
}


def _action_badge_html(action: str) -> str:
    icon, color_classes = _ACTION_BADGE_STYLE.get(action, ("•", "bg-gray-100 text-gray-600"))
    label = html.escape(_ACTION_LABELS.get(action, action))
    return (
        f'<span class="inline-flex items-center gap-1 text-xs font-semibold '
        f'px-2.5 py-0.5 rounded-full {color_classes}">{icon} {label}</span>'
    )


def _account_label(account_id: str, accounts: dict | None = None) -> str:
    """"<Tên hiển thị> (<account_id>)" for a known account, or the bare
    id if it's somehow not registered — never crashes a page render over
    a dangling account_id in old data."""
    accounts = accounts if accounts is not None else get_all_accounts()
    account = accounts.get(account_id)
    return f"{account.display_name} ({account_id})" if account else account_id


def _auto_fire_status_html() -> str:
    """A visible, LIVE reminder of SchedulingConfig.auto_fire_enabled's
    current state, shown on both /admin/post and /admin/schedule — added
    2026-09-07 after a manually-scheduled post sat past its due time
    because this flag (then buried inside "Đồng bộ dữ liệu bên B" in
    /admin/config) was off and nothing on either page said so. Always
    reads the live config rather than being passed in, so it can never go
    stale relative to what /admin/config → "Lên lịch & tự động đăng"
    actually has saved."""
    if get_scheduling_config().auto_fire_enabled:
        return '<div class="flash">✅ Tự động đăng: <strong>Đang bật</strong> — bài đến giờ sẽ tự chạy.</div>'
    return (
        '<div class="error">⚠️ Tự động đăng: <strong>Đang tắt</strong> — bài đến giờ cần bấm "🚀 Đăng ngay" thủ công. '
        '<a href="/admin/config">Bật ở Cấu hình →</a></div>'
    )


_TYPING_LABELS: dict[str, str] = {
    "enabled": "Bật giả lập gõ phím kiểu người",
    "wpm": "Tốc độ gõ trung bình (WPM, quy ước 5 ký tự = 1 từ)",
    "char_delay_stdev_ratio": "Độ lệch ngẫu nhiên giữa các phím (0.35 = ±35%)",
    "min_char_delay_ms": "Khoảng cách tối thiểu giữa 2 phím (ms)",
    "word_pause_min_ms": "Ngừng thêm sau mỗi từ — tối thiểu (ms)",
    "word_pause_max_ms": "Ngừng thêm sau mỗi từ — tối đa (ms)",
    "punctuation_pause_min_ms": "Ngừng thêm sau dấu câu — tối thiểu (ms)",
    "punctuation_pause_max_ms": "Ngừng thêm sau dấu câu — tối đa (ms)",
    "typo_probability": "Xác suất gõ sai mỗi ký tự ASCII (0.03 = 3%)",
    "typo_notice_delay_min_ms": "Thời gian 'nhận ra lỗi' trước khi xoá — tối thiểu (ms)",
    "typo_notice_delay_max_ms": "Thời gian 'nhận ra lỗi' trước khi xoá — tối đa (ms)",
    "word_typo_probability": "Xác suất gõ sai cả từ có dấu rồi xoá gõ lại (0.04 = 4%)",
    "fatigue_factor_per_char": "Hệ số 'mỏi tay' — chậm dần theo mỗi ký tự đã gõ",
}

_PACING_LABELS: dict[str, str] = {
    "enabled": "Bật các khoảng chờ theo ngữ cảnh",
    "page_load_pause_min_ms": "Chờ sau khi vào trang — tối thiểu (ms)",
    "page_load_pause_max_ms": "Chờ sau khi vào trang — tối đa (ms)",
    "composer_open_pause_min_ms": "Chờ sau khi mở ô đăng bài — tối thiểu (ms)",
    "composer_open_pause_max_ms": "Chờ sau khi mở ô đăng bài — tối đa (ms)",
    "ui_step_pause_min_ms": "Chờ giữa mỗi bước chọn (VD: chọn đối tượng) — tối thiểu (ms)",
    "ui_step_pause_max_ms": "Chờ giữa mỗi bước chọn (VD: chọn đối tượng) — tối đa (ms)",
    "reading_wpm": "Tốc độ đọc thầm ước tính (từ/phút)",
    "reading_pause_min_ms": "Giới hạn thời gian đọc lại trước khi Đăng — tối thiểu (ms)",
    "reading_pause_max_ms": "Giới hạn thời gian đọc lại trước khi Đăng — tối đa (ms)",
    "reading_buffer_min_ms": "Đệm ngẫu nhiên cộng thêm vào thời gian đọc — tối thiểu (ms)",
    "reading_buffer_max_ms": "Đệm ngẫu nhiên cộng thêm vào thời gian đọc — tối đa (ms)",
}

_MOUSE_LABELS: dict[str, str] = {
    "enabled": "Bật di chuyển chuột kiểu đường cong trước khi click",
    "min_steps": "Số bước di chuyển chuột tối thiểu",
    "max_steps": "Số bước di chuyển chuột tối đa",
    "step_delay_min_ms": "Độ trễ giữa mỗi bước di chuyển — tối thiểu (ms)",
    "step_delay_max_ms": "Độ trễ giữa mỗi bước di chuyển — tối đa (ms)",
    "curve_offset_ratio": "Độ cong của đường di chuyển, tỉ lệ theo khoảng cách (0.18 = 18%)",
    "overshoot_probability": "Xác suất di chuyển vọt quá đích rồi kéo lại (0.15 = 15%)",
    "overshoot_ratio": "Mức vọt quá đích, tỉ lệ theo khoảng cách",
    "min_distance_for_curve_px": "Khoảng cách tối thiểu (px) mới áp dụng đường cong",
    "click_delay_min_ms": "Thời gian giữ chuột (nhấn xuống → nhả ra) — tối thiểu (ms)",
    "click_delay_max_ms": "Thời gian giữ chuột (nhấn xuống → nhả ra) — tối đa (ms)",
    "jitter_px": "Độ rung tay ngẫu nhiên trong lúc di chuyển (px, 0 = tắt)",
}

_SCROLL_LABELS: dict[str, str] = {
    "enabled": "Bật cuộn trang nhiều bước có giảm tốc (tắt = nhảy thẳng tới vị trí)",
    "step_delay_min_ms": "Độ trễ giữa mỗi lần cuộn — tối thiểu (ms)",
    "step_delay_max_ms": "Độ trễ giữa mỗi lần cuộn — tối đa (ms)",
    "max_step_px": "Khoảng cách tối đa mỗi lần cuộn (px)",
    "deceleration_ratio": "Tỉ lệ quãng đường còn lại được cuộn mỗi lần (0.5 = 50%, càng nhỏ càng giảm tốc rõ)",
    "max_iterations": "Số lần cuộn tối đa trước khi chốt vị trí chính xác",
}

_BOOL_FIELDS = {
    "enabled", "auto_fire_enabled", "attach_random_meme_default",
    "job_post_ai_enabled", "candidate_reply_ai_enabled",
}

# Pulled out of DataSyncConfig's usual card into their own "🤖 AI" tab in
# /admin/config, next to the API key card — same fields, same save path
# (save_data_sync_overrides()), just displayed somewhere more findable
# than buried in "Đồng bộ dữ liệu". See config_form()'s docstring-less
# but commented split logic.
_AI_TOGGLE_FIELDS = {"job_post_ai_enabled", "candidate_reply_ai_enabled"}

_SCHEDULING_LABELS: dict[str, str] = {
    "auto_fire_enabled": (
        "⚠️ Tự động đăng khi đến giờ — áp dụng cho MỌI bài trong lịch (tắt = chỉ đặt "
        "lịch, phải bấm 'Đăng ngay' thủ công ở /admin/schedule; áp dụng cả bài tự động "
        "từ bên B lẫn bài soạn tay ở /admin/post)"
    ),
}

_ICONS: dict[str, str] = {
    "scheduling": "🚀",
    "typing": "⌨️",
    "pacing": "⏱️",
    "mouse": "🖱️",
    "scroll": "↕️",
}

# Scheduling first — it's the highest-stakes/most-consulted setting (whether
# anything auto-posts to Facebook at all), so it shouldn't require scrolling
# past 3 other cards to find (moved to the top 2026-09-07, after a user
# looked for it under "Đồng bộ dữ liệu bên B" and didn't find it there).
_CONFIG_SECTIONS = [
    ("scheduling", "scheduling", "Lên lịch & tự động đăng", SchedulingConfig, EDITABLE_SCHEDULING_FIELDS, _SCHEDULING_LABELS,
     get_scheduling_overrides, save_scheduling_overrides),
    ("human_typing", "typing", "Gõ phím", HumanTypingConfig, EDITABLE_HUMAN_TYPING_FIELDS, _TYPING_LABELS,
     get_human_typing_overrides, save_human_typing_overrides),
    ("pacing", "pacing", "Khoảng chờ theo ngữ cảnh", HumanPacingConfig, EDITABLE_PACING_FIELDS, _PACING_LABELS,
     get_pacing_overrides, save_pacing_overrides),
    ("mouse", "mouse", "Di chuyển chuột", HumanMouseConfig, EDITABLE_MOUSE_FIELDS, _MOUSE_LABELS,
     get_mouse_overrides, save_mouse_overrides),
    ("scroll", "scroll", "Cuộn trang", HumanScrollConfig, EDITABLE_SCROLL_FIELDS, _SCROLL_LABELS,
     get_scroll_overrides, save_scroll_overrides),
]

_DATA_SYNC_LABELS: dict[str, str] = {
    "enabled": "Bật bộ đồng bộ dữ liệu từ bên B (lấy + chống trùng + đặt lịch)",
    "poll_interval_minutes": "Chu kỳ gọi API bên B để lấy dữ liệu mới (phút)",
    "due_check_interval_seconds": "Chu kỳ kiểm tra bài đã đến giờ đăng (giây)",
    "post_gap_min_minutes": "Khoảng cách giữa 2 bài đăng nhóm liên tiếp — tối thiểu (phút)",
    "post_gap_max_minutes": "Khoảng cách giữa 2 bài đăng nhóm liên tiếp — tối đa (phút)",
    "comment_gap_min_minutes": "Khoảng cách giữa 2 lượt reply ứng viên liên tiếp — tối thiểu (phút)",
    "comment_gap_max_minutes": "Khoảng cách giữa 2 lượt reply ứng viên liên tiếp — tối đa (phút)",
    "quiet_hour_start_local": "Giờ bắt đầu khung giờ yên tĩnh, không đặt lịch (giờ địa phương, 0-23)",
    "quiet_hour_end_local": "Giờ kết thúc khung giờ yên tĩnh (giờ địa phương, 0-23)",
    "candidate_min_confidence": "Độ tin cậy tối thiểu để nhắn ứng viên (0-1)",
    "candidate_max_age_days": "Chỉ nhắn ứng viên có bài đăng trong vòng bao nhiêu ngày",
    "cache_retention_days": "Số ngày giữ lại cache chống trùng trước khi dọn",
    "job_post_ai_enabled": "Dùng AI soạn lại bài tin tuyển dụng đăng nhóm",
    "candidate_reply_ai_enabled": "Dùng AI để soạn câu reply comment bài viết ứng viên",
}

# Overrides the default "mặc định: X · key: field_name" sub-line
# (render_rows() in config_form()) with a plain-language explanation
# instead — used for the 2 AI toggles above, where "mặc định: True" is
# far less useful to an operator than knowing what flipping it actually
# changes at posting time.
_FIELD_DESCRIPTIONS: dict[str, str] = {
    "job_post_ai_enabled": (
        "Bài viết sẽ được soạn lại ngay lúc đăng, nếu không sử dụng thì bài đăng sẽ được đăng theo "
        "template mẫu"
    ),
    "candidate_reply_ai_enabled": (
        "Comment sẽ được soạn ngay lúc đăng, hoặc nếu tắt sẽ sử dụng câu reply từ API GET /reply, "
        "hoặc từ template mẫu"
    ),
}

_ICONS["data_sync"] = "🔄"

_CONFIG_SECTIONS.append(
    ("data_sync", "data_sync", "Đồng bộ dữ liệu bên B", DataSyncConfig, EDITABLE_DATA_SYNC_FIELDS, _DATA_SYNC_LABELS,
     get_data_sync_overrides, save_data_sync_overrides)
)


def _mask_api_key(key: str) -> str:
    """`"sk-ant-api03-abc...xyz9"` -> `"sk-ant-a...yz9"` — enough to
    recognize/confirm which key is active without displaying anything a
    screenshot or shoulder-surf could actually reuse. Full dots for
    anything too short to safely reveal a prefix+suffix of."""
    if len(key) <= 10:
        return "•" * len(key)
    return f"{key[:7]}...{key[-4:]}"


# One entry per provider human_bot/ai_client.py knows how to call — the
# single place to add a 5th provider later (new SecretsConfig fields +
# one entry here + one _call_* function in ai_client.py). "env_var" is
# None for Gemini/custom since this project has no established env var
# name for them (admin-UI-only, unlike Anthropic/OpenAI which fall back
# to ANTHROPIC_API_KEY/OPENAI_API_KEY per get_active_ai_provider_config()).
# "suggested_models" — top 3 most-recognizable model ids for that provider,
# offered as a quick-pick dropdown next to the free-text model input (added
# 2026-09-10, admin feedback: picking from a short list beats having to
# already know/copy-paste the exact case-sensitive API identifier). Empty
# for "custom" — there's no sensible "top 3" for an arbitrary endpoint.
_AI_PROVIDERS: list[dict[str, Any]] = [
    {"key": "anthropic", "label": "Anthropic (Claude)", "key_field": "anthropic_api_key",
     "model_field": "anthropic_model", "model_placeholder": "claude-sonnet-4-5",
     "suggested_models": ["claude-opus-4-5", "claude-sonnet-4-5", "claude-haiku-4-5"],
     "key_placeholder": "sk-ant-...", "env_var": "ANTHROPIC_API_KEY", "base_url_field": None},
    {"key": "openai", "label": "OpenAI (GPT)", "key_field": "openai_api_key",
     "model_field": "openai_model", "model_placeholder": "gpt-4o-mini",
     "suggested_models": ["gpt-4o", "gpt-4o-mini", "gpt-4.1-mini"],
     "key_placeholder": "sk-...", "env_var": "OPENAI_API_KEY", "base_url_field": None},
    {"key": "gemini", "label": "Google Gemini", "key_field": "gemini_api_key",
     "model_field": "gemini_model", "model_placeholder": "gemini-2.5-flash",
     "suggested_models": ["gemini-2.5-pro", "gemini-2.5-flash", "gemini-2.5-flash-lite"],
     "key_placeholder": "AIza...", "env_var": None, "base_url_field": None},
    {"key": "custom", "label": "Tuỳ chỉnh (OpenAI-compatible)", "key_field": "custom_api_key",
     "suggested_models": [],
     "model_field": "custom_model", "model_placeholder": "vd: deepseek-chat",
     "key_placeholder": "API key của bên đó", "env_var": None, "base_url_field": "custom_base_url"},
]

# Toggles which provider's fieldset is visible when the dropdown below
# changes — plain vanilla JS (no htmx round-trip needed, all 4 providers'
# fields already sit in the DOM so one form submit saves everything).
_AI_PROVIDER_SWITCH_JS = (
    "document.querySelectorAll('[data-ai-provider-fields]').forEach(function(el){"
    "el.hidden = (el.getAttribute('data-ai-provider-fields') !== this.value);"
    "}, this);"
)


def _ai_provider_card_html(flash: str = "") -> str:
    """Standalone (not a `<form>`, deliberately — the whole /admin/config
    page is already one big `<form>`, and nested `<form>` elements are
    invalid HTML/silently misbehave) htmx-driven card for managing which AI
    provider is active plus its key/model (+ base URL for "custom") from
    the web instead of only via .env. Originally Anthropic-only (added
    2026-09-10 after live-testing content_strategist.py's AI drafting),
    generalized same day to Anthropic/OpenAI/Gemini/custom — see
    human_bot/secrets_config.py and human_bot/ai_client.py. Re-rendered
    wholesale (hx-swap="outerHTML") after every save/clear so the masked
    status line always reflects what's actually active."""
    cfg = get_secrets_config()
    provider_keys = [p["key"] for p in _AI_PROVIDERS]
    active = cfg.ai_provider if cfg.ai_provider in provider_keys else "anthropic"
    active_provider_info = next(p for p in _AI_PROVIDERS if p["key"] == active)
    active_cfg = get_active_ai_provider_config()

    if active_cfg.api_key:
        override_set = bool(getattr(cfg, active_provider_info["key_field"]).strip())
        source = "nhập trên admin" if override_set else "từ .env"
        status = (
            f'<span class="badge" style="background:#ecfdf5;color:#059669;">'
            f'Provider đang dùng: {html.escape(str(active_provider_info["label"]))} — key {source} '
            f'({html.escape(_mask_api_key(active_cfg.api_key))})</span>'
        )
    else:
        status = (
            f'<span class="badge" style="background:#fef2f2;color:#dc2626;">'
            f'Provider đang chọn ({html.escape(str(active_provider_info["label"]))}) chưa có key nào — '
            f'nhánh AI sẽ luôn rơi về mẫu (template)</span>'
        )

    options_html = "".join(
        f'<option value="{p["key"]}"{" selected" if p["key"] == active else ""}>{html.escape(str(p["label"]))}</option>'
        for p in _AI_PROVIDERS
    )

    fieldsets_html = []
    for p in _AI_PROVIDERS:
        key_val = str(getattr(cfg, p["key_field"]))
        model_val = str(getattr(cfg, p["model_field"]))
        hidden_attr = "" if p["key"] == active else " hidden"
        env_hint = f' · fallback <code>.env</code>: <code>{p["env_var"]}</code>' if p["env_var"] else ""

        base_url_html = ""
        if p["base_url_field"]:
            base_url_val = str(getattr(cfg, p["base_url_field"]))
            base_url_html = f"""
    <div class="field-stack">
      <div class="field-label">Base URL<div class="field-key">endpoint gốc của bên cung cấp, KHÔNG kèm "/chat/completions" — vd: https://api.deepseek.com/v1</div></div>
      <div class="field-input"><input type="text" name="{p['base_url_field']}" value="{html.escape(base_url_val)}" placeholder="https://.../v1"></div>
    </div>"""

        clear_btn_html = ""
        if key_val.strip():
            clear_btn_html = (
                f'<button type="button" class="btn-small btn-secondary" style="flex-shrink:0;" '
                f'hx-post="/admin/config/ai-provider/clear-key" '
                f'hx-vals=\'{{"provider": "{p["key"]}"}}\' '
                f'hx-target="#ai-provider-card" hx-swap="outerHTML" '
                f'hx-confirm="Xoá key đã lưu cho {html.escape(str(p["label"]))}? Sẽ dùng lại key trong .env nếu có (Anthropic/OpenAI), hoặc không dùng AI nếu không có.">Xoá key</button>'
            )

        # datalist: one native combo-box-like input — a dropdown arrow to
        # pick a suggested model AND free-typing in the same field, instead
        # of a separate <select> stacked above/below the text input (admin
        # feedback: two visible controls for one value looked cluttered).
        model_input_id = f"model-input-{p['key']}"
        datalist_html = ""
        list_attr = ""
        if p["suggested_models"]:
            datalist_id = f"model-suggestions-{p['key']}"
            list_attr = f' list="{datalist_id}"'
            datalist_options = "".join(
                f'<option value="{html.escape(m)}">' for m in p["suggested_models"]
            )
            datalist_html = f'<datalist id="{datalist_id}">{datalist_options}</datalist>'

        fieldsets_html.append(f"""
  <div data-ai-provider-fields="{p['key']}"{hidden_attr}>
    <div class="field-stack">
      <div class="field-label">API key ({html.escape(str(p["label"]))})<div class="field-key">để trống = giữ nguyên key hiện tại{env_hint}</div></div>
      <div class="field-input" style="display:flex;gap:8px;">
        <input type="password" name="{p['key_field']}" placeholder="{p['key_placeholder']}"
          style="flex:1 1 auto;min-width:0;font-family:monospace;">
        <button type="button" class="btn-small btn-secondary" style="flex-shrink:0;"
          onclick="var i=this.previousElementSibling; i.type = (i.type==='password' ? 'text' : 'password');">👁</button>
        {clear_btn_html}
      </div>
    </div>
    <div class="field-stack">
      <div class="field-label">Model<div class="field-key">để trống = dùng mặc định hệ thống — bấm vào ô để chọn nhanh model phổ biến, hoặc tự gõ tên khác (phải đúng chính xác, phân biệt hoa/thường)</div></div>
      <div class="field-input">
        <input type="text" id="{model_input_id}" name="{p['model_field']}" value="{html.escape(model_val)}" placeholder="{p['model_placeholder']}" style="font-family:monospace;"{list_attr}>
        {datalist_html}
      </div>
    </div>{base_url_html}
  </div>""")

    return f"""
<div class="card" id="ai-provider-card">
  <h2>🔑 Cấu hình AI</h2>
  <p class="page-desc">Chọn nhà cung cấp AI dùng cho 2 công tắc AI ở dưới (soạn bài tin tuyển dụng + viết lại reply ứng viên). Key/model nhập ở đây <b>ưu tiên hơn</b> biến môi trường trong <code>.env</code> — có hiệu lực ngay, không cần khởi động lại service.</p>
  {flash}
  <p>{status}</p>
  <div class="field-stack">
    <div class="field-label">Nhà cung cấp</div>
    <div class="field-input"><select name="ai_provider" onchange="{_AI_PROVIDER_SWITCH_JS}">{options_html}</select></div>
  </div>
  {"".join(fieldsets_html)}
  <div class="form-actions">
    <button type="button" hx-post="/admin/config/ai-provider" hx-include="#ai-provider-card"
      hx-target="#ai-provider-card" hx-swap="outerHTML">Lưu cấu hình AI</button>
  </div>
</div>"""


_MEDIA_LABELS: dict[str, str] = {
    "attach_random_meme_default": (
        "Tự động đính kèm ảnh ngẫu nhiên từ media/memes/ khi bài đăng chưa có ảnh riêng "
        "(ảnh do bên B cung cấp cho bài đó luôn được ưu tiên dùng trước)"
    ),
}

_ICONS["media"] = "🖼️"

_CONFIG_SECTIONS.append(
    ("media", "media", "Ảnh đính kèm", MediaConfig, EDITABLE_MEDIA_FIELDS, _MEDIA_LABELS,
     get_media_overrides, save_media_overrides)
)

_SAFETY_COOLDOWN_LABELS: dict[str, str] = {
    "enabled": "Bật hạ nhiệt sau khi 'Kích hoạt lại' một tài khoản từng bị tạm dừng",
    # "trong lúc hạ nhiệt" nói chung dễ gây hiểu lầm từ 2026-09-15 (đổi
    # sang 2 tuần có nấc) — các con số dưới đây CHỈ áp dụng tuần 1 (và
    # cả cooldown_days cho riêng tier "Dưới 1 tháng", vốn không có tier
    # thấp hơn để nhích lên); tuần 2 của các tier khác dùng preset của
    # tier thấp hơn liền kề (human_bot/config.py's
    # COOLDOWN_WEEK2_STEP_UP_TIER), không đọc các field này — chỉnh số
    # ở đây không ảnh hưởng gì tới mức tuần 2 của 1 tài khoản đã "trưởng
    # thành".
    "cooldown_days": "Tổng số ngày hạ nhiệt (chia đôi thành 2 tuần: tuần 1 = mức sàn dưới đây cho MỌI tier, tuần 2 = nhích lên 1 tier thấp hơn — xem COOLDOWN_WEEK2_STEP_UP_TIER), trước khi tự trở về giới hạn cũ",
    "posts_per_day": "Số bài đăng tối đa/ngày ở TUẦN 1 hạ nhiệt (mọi tier)",
    "comments_per_hour": "Số comment tối đa/giờ ở TUẦN 1 hạ nhiệt (mọi tier)",
    "comments_per_day": "Số comment tối đa/ngày ở TUẦN 1 hạ nhiệt (mọi tier)",
    "likes_per_hour": "Số lượt thích tối đa/giờ ở TUẦN 1 hạ nhiệt (mọi tier)",
    "min_delay_seconds": "Khoảng chờ giữa 2 hành động — tối thiểu (giây) ở TUẦN 1 hạ nhiệt (mọi tier)",
    "max_delay_seconds": "Khoảng chờ giữa 2 hành động — tối đa (giây) ở TUẦN 1 hạ nhiệt (mọi tier)",
}

_ICONS["safety_cooldown"] = "🧊"

_CONFIG_SECTIONS.append(
    ("safety_cooldown", "safety_cooldown", "Hạ nhiệt sau khi kích hoạt lại tài khoản",
     SafetyCooldownConfig, EDITABLE_SAFETY_COOLDOWN_FIELDS, _SAFETY_COOLDOWN_LABELS,
     get_safety_cooldown_overrides, save_safety_cooldown_overrides)
)

_PAGE_STYLE = """
<script src="https://cdn.tailwindcss.com"></script>
<script src="https://unpkg.com/htmx.org@1.9.12"></script>
<style type="text/tailwindcss">
@layer base {
  body { @apply bg-gray-100 text-gray-900 leading-relaxed; }
  a { @apply text-indigo-600 no-underline; }
  a:hover { @apply underline; }
}
@layer components {
  .topbar { @apply bg-white border-b border-gray-200 sticky top-0 z-10 px-4 sm:px-6; }
  .topbar-inner { @apply max-w-6xl mx-auto flex items-center gap-4 sm:gap-7 h-14 flex-wrap; }
  .brand { @apply font-bold text-base tracking-tight flex items-center gap-2; }
  .brand-dot { @apply w-2.5 h-2.5 rounded-full bg-indigo-600 inline-block; }
  nav.topnav { @apply flex gap-1 flex-wrap; }
  nav.topnav a { @apply text-gray-500 text-sm font-medium px-3 py-1.5 rounded-md hover:bg-indigo-50 hover:text-indigo-600 hover:no-underline transition-colors; }
  nav.topnav a.active { @apply bg-indigo-50 text-indigo-600; }

  main { @apply max-w-6xl mx-auto px-4 sm:px-6 py-8 pb-16; }

  h1 { @apply text-2xl font-semibold tracking-tight mb-1.5 text-gray-900; }
  h2 { @apply text-base font-semibold mb-3.5 flex items-center gap-2 text-gray-900; }
  .page-desc { @apply text-gray-500 text-sm mb-6; }

  .card { @apply bg-white border border-gray-200 rounded-2xl shadow-sm p-5 sm:p-6 mb-5; }

  .field-grid { @apply grid grid-cols-1 gap-3.5; }
  .field-row { @apply flex items-center justify-between gap-5 py-2.5 border-b border-gray-100 flex-wrap sm:flex-nowrap; }
  .field-row:last-child { @apply border-b-0 pb-0; }
  .field-label { @apply flex-1 text-sm text-gray-800 min-w-[160px]; }
  .field-key { @apply text-gray-400 text-xs mt-0.5; }
  .field-input { @apply w-full sm:w-[220px] flex-shrink-0; }

  /* Stacked field layout — label above, full-width input below. Used for
     text-heavy fields (URLs, names, freeform account/action pickers)
     where the side-by-side field-row/field-input (fine for short numeric
     settings on /admin/config) leaves the input too narrow while the
     label column sits mostly empty. */
  .field-stack { @apply flex flex-col gap-1.5 py-2.5 border-b border-gray-100; }
  .field-stack:last-child { @apply border-b-0 pb-0; }
  .field-stack .field-label { @apply text-sm text-gray-800 font-medium flex-none min-w-0; }
  .field-stack .field-input { @apply w-full; }

  input[type=text], input[type=number], input[type=password], input[type=datetime-local], textarea, select {
    @apply w-full box-border px-2.5 py-2 text-sm border border-gray-200 rounded-lg bg-white text-gray-900 font-sans;
  }
  input[type=text]:focus, input[type=number]:focus, input[type=password]:focus, input[type=datetime-local]:focus, textarea:focus, select:focus {
    @apply outline-none border-indigo-600 ring-4 ring-indigo-50;
  }
  input[type=checkbox] { @apply w-[18px] h-[18px] accent-indigo-600 cursor-pointer; }
  textarea { @apply min-h-[160px] resize-y; }

  /* Toggle switch — same underlying <input type=checkbox name=... value="true">
     as the plain checkboxes above (so form submission/save path is
     unchanged), just visually hidden and styled via the sibling .switch-slider.
     Used for the AI tab's on/off toggles, where "bật/tắt" reads better as a
     switch than a checkbox. */
  .switch { @apply relative inline-block w-[42px] h-[24px] cursor-pointer flex-shrink-0; }
  .switch input { @apply absolute opacity-0 w-0 h-0 cursor-pointer; }
  .switch-slider { @apply absolute inset-0 bg-gray-300 rounded-full transition-colors; }
  .switch-slider::before { content: ""; @apply absolute w-[18px] h-[18px] left-[3px] top-[3px] bg-white rounded-full transition-transform shadow; }
  .switch input:checked + .switch-slider { @apply bg-indigo-600; }
  .switch input:checked + .switch-slider::before { @apply translate-x-[18px]; }
  .switch input:focus-visible + .switch-slider { @apply ring-4 ring-indigo-50; }

  button, .btn {
    @apply px-[18px] py-[9px] text-sm font-semibold border-0 rounded-lg bg-indigo-600 text-white cursor-pointer transition-colors inline-block text-center;
  }
  button:hover, .btn:hover { @apply bg-indigo-700 no-underline; }
  button.btn-secondary, a.btn-secondary { @apply bg-white text-gray-900 border border-gray-200; }
  button.btn-secondary:hover, a.btn-secondary:hover { @apply bg-gray-50 no-underline; }
  .btn-small { @apply px-3 py-1.5 text-[13px]; }
  button.btn-copy, a.btn-copy { @apply bg-teal-50 text-teal-700 border border-teal-200 px-2.5 py-1 text-xs rounded-full; }
  button.btn-copy:hover, a.btn-copy:hover { @apply bg-teal-100 no-underline; }

  .muted { @apply text-gray-500 text-sm; }

  .flash, .error, .warning { @apply rounded-2xl px-4 py-3 mb-5 text-sm flex items-center gap-2; }
  .flash { @apply bg-emerald-50 border border-emerald-200 text-emerald-700; }
  .error { @apply bg-red-50 border border-red-200 text-red-700; }
  .warning { @apply bg-amber-50 border border-amber-200 text-amber-800; }
  /* Same look as .warning above, but sized/margined for sitting INSIDE a
     .queue-item (per-task banner) rather than at page level. */
  .warning-inline { @apply bg-amber-50 border border-amber-200 text-amber-800 rounded-xl px-3 py-2 mt-2 mb-2 text-sm flex items-center gap-2; }

  .form-actions { @apply mt-2 flex justify-end; }

  .badge { @apply inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-600; }

  .account-list { @apply list-none p-0 m-0 flex flex-wrap gap-2; }
  .account-list li { @apply bg-indigo-50 text-indigo-600 text-sm font-semibold px-3 py-1.5 rounded-full; }

  .home-links { @apply grid grid-cols-1 sm:grid-cols-2 gap-4 mt-2; }
  .home-link-card { @apply block bg-white border border-gray-200 rounded-2xl px-5 py-[18px] shadow-sm hover:border-indigo-600 hover:no-underline transition-colors; }
  .home-link-card .title { @apply font-bold text-[15px] text-gray-900 mb-1; }
  .home-link-card .desc { @apply text-gray-500 text-[13px]; }

  .queue-item { @apply border border-gray-200 rounded-2xl px-4 py-[14px] mb-3 bg-white; }
  .queue-item .queue-filename { @apply text-xs text-gray-500 mb-1.5; }
  .queue-item .queue-preview { @apply text-sm mb-2.5 whitespace-pre-wrap; }
  .queue-item form { @apply flex gap-2 items-center flex-wrap; }
  .queue-item select { @apply w-auto min-w-[140px]; }

  .empty-state { @apply text-center text-gray-500 px-4 py-7 text-sm border border-dashed border-gray-300 rounded-2xl; }

  .section-divider { @apply mt-8 mb-[18px] text-xs uppercase tracking-wide text-gray-500 font-bold; }

  .tab-bar { @apply flex gap-1.5 border-b border-gray-200 mb-5 flex-wrap; }
  .tab-btn { @apply bg-transparent border-0 border-b-2 border-transparent px-3.5 py-2.5 text-sm font-semibold text-gray-500 cursor-pointer -mb-px; }
  .tab-btn:hover { @apply text-gray-900; }
  .tab-btn.active { @apply text-indigo-600 border-indigo-600; }
  .tab-panel[hidden] { @apply hidden; }

  /* Custom select — styled trigger + dropdown panel that opens below it,
     backed by a real <select> (kept in the DOM, visually hidden) so form
     submission and the existing name="..." fields need no changes. */
  .cselect { @apply relative; }
  .cselect select.cselect-native { @apply hidden; }
  .cselect-trigger { @apply w-full flex items-center justify-between gap-2 px-2.5 py-2 border border-gray-200 rounded-lg bg-white text-gray-900 text-sm cursor-pointer; }
  .cselect-trigger:hover { @apply border-indigo-600; }
  .cselect-trigger.open { @apply border-indigo-600 ring-4 ring-indigo-50; }
  .cselect-trigger .chevron { @apply text-gray-400 text-[11px] transition-transform flex-shrink-0; }
  .cselect-trigger.open .chevron { @apply rotate-180; }
  .cselect-panel { @apply absolute left-0 right-0 top-[calc(100%+6px)] bg-white border border-gray-200 rounded-xl shadow-lg p-1.5 max-h-60 overflow-y-auto z-50 hidden; }
  .cselect-panel.open { @apply block; }
  .cselect-option { @apply px-2.5 py-2 rounded-md text-sm cursor-pointer; }
  .cselect-option:hover { @apply bg-indigo-50 text-indigo-600; }
  .cselect-option.selected { @apply bg-indigo-50 text-indigo-600 font-semibold; }
  .queue-item .cselect { @apply min-w-[220px]; }

  /* Modal — used by /admin/groups' "Thêm nhóm mới"/"Sửa" so the form
     opens in an overlay instead of an always-visible inline card.
     #modal-root (see _layout()) is an empty container the whole app
     shares; htmx swaps a .modal-backdrop into it to open, and either the
     backdrop click / ✕ / Escape (plain JS, no server round-trip) or a
     successful form submit (server sends back an empty swap for
     #modal-root, see _group_modal_html() callers) empties it again to
     close. */
  .modal-backdrop { @apply fixed inset-0 bg-black/50 flex items-center justify-center z-[100] p-4; }
  .modal-box { @apply bg-white rounded-2xl shadow-xl max-w-md w-full p-6 max-h-[90vh] overflow-y-auto; }
  /* Wider variant for /admin/accounts' modals (account add, rate-limits —
     the latter got noticeably more crowded once the age-tier quick-apply
     buttons were added) — .modal-box's own max-w-md stays the default for
     every other modal (e.g. /admin/groups' edit modal). */
  .modal-box-wide { @apply max-w-2xl; }
  .modal-header { @apply flex items-center justify-between mb-4; }
  .modal-header h2 { @apply mb-0; }
  .modal-close { @apply bg-transparent text-gray-400 border-0 text-lg leading-none px-2 py-1 rounded-md; }
  .modal-close:hover { @apply bg-gray-100 text-gray-700; }

  .table-scroll { @apply w-full overflow-x-auto -mx-1 px-1; }
  .data-table { @apply w-full border-collapse min-w-[560px]; }
  .data-table th, .data-table td { @apply text-left px-3 py-2.5 border-b border-gray-100 text-sm align-middle; }
  .data-table th { @apply text-gray-500 font-semibold text-[11px] uppercase tracking-wide; }
  .data-table tr:last-child td { @apply border-b-0; }
  .data-table td.col-actions { @apply whitespace-nowrap w-px; }
  .data-table td.col-actions form { @apply inline-block ml-1.5; }
  .data-table .row-url { @apply text-gray-500 text-[13px] break-all; }
  .account-filter { @apply flex items-center gap-2.5 mb-5 flex-wrap; }
  .account-filter select { @apply w-auto min-w-[260px]; }
  .account-filter label { @apply text-sm text-gray-500 font-semibold; }

  /* _expandable_text()'s <details> — CSS-only truncate/expand (no JS,
     no separate short/full markup) so opening it swaps STRAIGHT from
     the ellipsis-clipped line to the full text in place, instead of
     showing the short teaser above a second copy of the full text
     (owner-reported 2026-09-12: the old <summary>+<div> version left
     the truncated line visible above the expanded one). */
  .expandable-text > summary { @apply cursor-pointer block whitespace-nowrap overflow-hidden text-ellipsis max-w-full; }
  .expandable-text[open] > summary { @apply whitespace-pre-wrap overflow-visible max-w-full; }

  /* htmx: fade the swapped-in fragment in, and dim the target briefly
     while a request is in flight — the only visual cue a click "did
     something" now that most actions no longer reload the page. */
  .htmx-added { @apply opacity-0; }
  .htmx-settling { @apply opacity-100 transition-opacity duration-150; }
  .htmx-request.htmx-target-dim { @apply opacity-60 transition-opacity duration-150; }
}
</style>

<script>
(function () {
  function closeAllCSelects() {
    document.querySelectorAll(".cselect-panel.open").forEach(function (p) { p.classList.remove("open"); });
    document.querySelectorAll(".cselect-trigger.open").forEach(function (t) { t.classList.remove("open"); });
  }

  function initCSelect(wrap) {
    if (wrap.dataset.cselectInit) return;
    wrap.dataset.cselectInit = "1";
    var select = wrap.querySelector("select.cselect-native");
    var trigger = wrap.querySelector(".cselect-trigger");
    var label = trigger.querySelector(".cselect-trigger-label");
    var panel = wrap.querySelector(".cselect-panel");
    if (!select || !trigger || !panel) return;

    function render() {
      panel.innerHTML = "";
      Array.prototype.forEach.call(select.options, function (opt) {
        var item = document.createElement("div");
        item.className = "cselect-option" + (opt.value === select.value ? " selected" : "");
        item.textContent = opt.textContent;
        item.addEventListener("click", function (e) {
          e.stopPropagation();
          select.value = opt.value;
          select.dispatchEvent(new Event("change"));
          label.textContent = opt.textContent;
          closeAllCSelects();
          render();
        });
        panel.appendChild(item);
      });
    }

    trigger.addEventListener("click", function (e) {
      e.stopPropagation();
      var wasOpen = panel.classList.contains("open");
      closeAllCSelects();
      if (!wasOpen) {
        panel.classList.add("open");
        trigger.classList.add("open");
      }
    });

    var current = select.options[select.selectedIndex];
    label.textContent = current ? current.textContent : "";
    render();
  }

  document.addEventListener("click", closeAllCSelects);

  // Modal: Escape closes whichever .modal-backdrop is currently open
  // (opening/closing the backdrop itself is plain DOM — see
  // .modal-backdrop's onclick and .modal-close's onclick inline in the
  // markup — this only adds the keyboard shortcut on top of those).
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var backdrop = document.querySelector(".modal-backdrop");
    if (backdrop) backdrop.remove();
  });

  // Repeatable content blocks for /admin/post's "Đăng vào nhóm" form
  // (human_bot/admin.py's post_form/post_schedule_groups): each block is
  // a content_<i>/groups_<i> field pair — see post_schedule_groups()'s
  // comment for why the server scans for whatever indices are present
  // instead of assuming 0..N. Cloning the first block (always literally
  // index "0" in the server-rendered markup) and bumping its field names
  // to a fresh, never-reused index is enough; removing a block never
  // needs to renumber anything else.
  function initRepeatableBlocks(container) {
    if (container.dataset.repeatableInit) return;
    container.dataset.repeatableInit = "1";
    var addBtn = container.querySelector("[data-add-block]");
    var list = container.querySelector("[data-block-list]");
    var template = list ? list.querySelector("[data-block]") : null;
    if (!addBtn || !list || !template) return;
    var nextIndex = 1;

    // With only 1 block left, its "Xoá khối này" button is HIDDEN rather
    // than left clickable-but-silently-doing-nothing — a form can't be
    // emptied down to zero blocks, but a button that just ignores clicks
    // with no feedback reads as broken, not as "not allowed".
    function updateRemoveVisibility() {
      var blocks = list.querySelectorAll("[data-block]");
      var onlyOne = blocks.length <= 1;
      blocks.forEach(function (block) {
        var btn = block.querySelector("[data-remove-block]");
        if (btn) btn.style.display = onlyOne ? "none" : "";
      });
    }

    function wireRemove(block) {
      var removeBtn = block.querySelector("[data-remove-block]");
      if (!removeBtn) return;
      removeBtn.addEventListener("click", function () {
        block.remove();
        updateRemoveVisibility();
      });
    }

    // "Chọn tất cả" toggles every group checkbox WITHIN this one block —
    // scoped per block (not global) since each content block targets its
    // own independent set of groups.
    function wireSelectAll(block) {
      var btn = block.querySelector("[data-select-all-groups]");
      if (!btn) return;
      btn.addEventListener("click", function () {
        var boxes = block.querySelectorAll('input[type="checkbox"]');
        var allChecked = Array.prototype.every.call(boxes, function (b) { return b.checked; });
        boxes.forEach(function (b) { b.checked = !allChecked; });
      });
    }

    addBtn.addEventListener("click", function () {
      var index = nextIndex++;
      var clone = template.cloneNode(true);
      clone.querySelectorAll("[name]").forEach(function (el) {
        el.name = el.name.replace(/_0$/, "_" + index);
        if (el.tagName === "TEXTAREA") el.value = "";
        if (el.type === "checkbox") el.checked = false;
      });
      wireRemove(clone);
      wireSelectAll(clone);
      list.appendChild(clone);
      updateRemoveVisibility();
    });

    wireRemove(template);
    wireSelectAll(template);
    updateRemoveVisibility();
  }

  // Datetime picker for any "when to post" field (/admin/post's compose
  // forms, /admin/schedule's edit form): the visible <input
  // type="datetime-local"> is never itself submitted — it only drives a
  // hidden UTC-ISO field (the one with a real `name`) that the backend
  // actually reads. This conversion MUST happen in the browser: only the
  // browser knows the viewer's local timezone, so doing it server-side
  // would silently assume UTC and shift every pick by the real offset.
  // Hoisted out of initScheduleField (2026-09-15 — see
  // refreshScheduleFieldDisplays() below for why): both need the exact
  // same UTC-ISO -> "YYYY-MM-DDTHH:MM" formatting.
  function schedulePad(n) { return String(n).padStart(2, "0"); }
  function toLocalInputValue(date) {
    return date.getFullYear() + "-" + schedulePad(date.getMonth() + 1) + "-" + schedulePad(date.getDate())
      + "T" + schedulePad(date.getHours()) + ":" + schedulePad(date.getMinutes());
  }

  function initScheduleField(wrap) {
    if (wrap.dataset.scheduleInit) return;
    wrap.dataset.scheduleInit = "1";
    var localInput = wrap.querySelector("[data-schedule-local]");
    var utcInput = wrap.querySelector("[data-schedule-utc]");
    if (!localInput || !utcInput) return;

    // Pre-fill the visible picker from whatever UTC value the page
    // already carries (editing an existing scheduled task).
    if (utcInput.value && !localInput.value) {
      var initial = new Date(utcInput.value);
      if (!isNaN(initial.getTime())) localInput.value = toLocalInputValue(initial);
    }

    localInput.addEventListener("input", function () {
      if (!localInput.value) { utcInput.value = ""; return; }
      var d = new Date(localInput.value);
      if (!isNaN(d.getTime())) utcInput.value = d.toISOString();
    });

    // Click anywhere in the field (not just its small calendar icon) to
    // open the native picker — showPicker() is Chrome/Edge-only as of
    // this writing, so this is a bonus on top of the icon, not a
    // replacement: browsers without it just keep working the old way.
    if (typeof localInput.showPicker === "function") {
      localInput.addEventListener("click", function () {
        try { localInput.showPicker(); } catch (e) { /* not user-activated, or already open */ }
      });
    }

    // Quick-pick buttons (see _datetime_picker_html) — set the picker
    // and fire the same "input" handling path as if the person had
    // typed it themselves, so the hidden UTC field stays in sync.
    wrap.querySelectorAll("[data-schedule-preset]").forEach(function (btn) {
      btn.addEventListener("click", function () {
        var base = new Date();
        var preset = btn.getAttribute("data-schedule-preset");
        if (preset === "+1h") base = new Date(base.getTime() + 60 * 60 * 1000);
        if (preset === "+1d") base = new Date(base.getTime() + 24 * 60 * 60 * 1000);
        localInput.value = toLocalInputValue(base);
        localInput.dispatchEvent(new Event("input"));
      });
    });
  }

  // /admin/post's account picker is a plain full-reload <form> (see
  // post_form()'s account_picker in human_bot/admin.py) — switching
  // account would otherwise silently wipe whatever was already typed
  // into the "Đăng lên tường cá nhân" card. Before that GET fires, copy
  // its current content + picked time into hidden fields on the SAME
  // form, so post_form() can read them back (profile_content /
  // profile_scheduled_at) and re-fill the card after the reload.
  function initPreservePostForm(form) {
    if (form.dataset.preserveInit) return;
    form.dataset.preserveInit = "1";
    var select = form.querySelector("select[name=account_id]");
    if (!select) return;
    select.addEventListener("change", function () {
      var contentEl = document.querySelector("[data-preserve-profile-content]");
      var scheduleWrap = document.querySelector("[data-preserve-profile-schedule]");
      var scheduleUtcEl = scheduleWrap ? scheduleWrap.querySelector("[data-schedule-utc]") : null;
      var activeTab = document.querySelector("[data-tabs] .tab-btn.active");
      setHidden(form, "profile_content", contentEl ? contentEl.value : "");
      setHidden(form, "profile_scheduled_at", scheduleUtcEl ? scheduleUtcEl.value : "");
      setHidden(form, "tab", activeTab ? activeTab.getAttribute("data-tab-target") : "");
      form.submit();
    });
  }

  // Plain tab switcher for /admin/post's Tường cá nhân / Đăng vào nhóm
  // sections — added because the page got long enough that having both
  // always visible at once was more scrolling than scanning. No
  // routing/state beyond which panel is showing; the
  // initial active tab is decided server-side (post_form()'s `tab` query
  // param — set on a validation-error redirect so the right panel is
  // already open when the page comes back).
  function initTabs(container) {
    if (container.dataset.tabsInit) return;
    container.dataset.tabsInit = "1";
    var buttons = container.querySelectorAll(".tab-btn");
    buttons.forEach(function (btn) {
      btn.addEventListener("click", function () {
        var target = btn.getAttribute("data-tab-target");
        buttons.forEach(function (b) { b.classList.toggle("active", b === btn); });
        container.querySelectorAll(".tab-panel").forEach(function (panel) {
          panel.hidden = panel.id !== target;
        });
      });
    });
  }

  // Rewrites a server-rendered "<span data-local-dt data-utc=...>" (see
  // admin.py's _local_dt_html()) from its fallback JST text to the
  // VIEWER's OWN browser-local time — plain Date getters (getHours(),
  // getDate(), ...) already read in whatever timezone the browser/OS is
  // set to, no library needed. Left as the server-rendered JST fallback
  // if this never runs (JS disabled) — still a correct absolute instant,
  // just a different, fixed label in that case.
  function initLocalDateTime(el) {
    if (el.dataset.localDtInit) return;
    el.dataset.localDtInit = "1";
    var iso = el.getAttribute("data-utc");
    var d = iso ? new Date(iso) : null;
    if (!d || isNaN(d.getTime())) return;
    function pad(n) { return String(n).padStart(2, "0"); }
    el.textContent = pad(d.getHours()) + ":" + pad(d.getMinutes()) + " " +
      pad(d.getDate()) + "-" + pad(d.getMonth() + 1) + "-" + d.getFullYear();
  }

  // Fills /admin/schedule's hidden "tz_offset" field (see admin.py's
  // _schedule_content_html()'s filter_html) from the VIEWER's own
  // browser timezone, same "what time is this for ME" instant
  // initLocalDateTime() above already renders per row — so the "Ngày
  // đăng" date filter buckets tasks by the exact date shown on screen,
  // not the server's own timezone. Sent as MINUTES TO ADD TO UTC TO GET
  // LOCAL (e.g. +540 for JST, UTC+9) — the negative of what
  // Date.getTimezoneOffset() itself returns (that one is "minutes to
  // ADD TO LOCAL to get UTC") — matched on the server by
  // admin.py's _task_local_date(), which does `utc + tz_offset_minutes`.
  // Re-run on every htmx outerHTML swap of #schedule-content (same as
  // initLocalDateTime), since the freshly-rendered hidden input
  // otherwise comes back with whatever default the server rendered (0)
  // until this overwrites it.
  function initTzOffsetField(el) {
    if (el.dataset.tzOffsetInit) return;
    el.dataset.tzOffsetInit = "1";
    el.value = String(-new Date().getTimezoneOffset());
  }

  // Fills the "Giới hạn tốc độ" modal's number inputs from a quick-apply
  // age-tier button's own data-* attributes (see admin.py's
  // _rate_limits_modal_body_html()) — CLIENT-SIDE ONLY, no request sent,
  // nothing persists until the modal's own "Lưu" button is pressed
  // (2026-09-11, owner request — clicking a tier used to save
  // immediately, surprising when a value changed with no explicit save).
  function initApplyTierButton(btn) {
    if (btn.dataset.applyTierInit) return;
    btn.dataset.applyTierInit = "1";
    btn.addEventListener("click", function () {
      var body = btn.closest("#rate-limits-body");
      var form = body && body.querySelector('form[action="/admin/accounts/rate-limits"]');
      if (!form) return;
      Object.keys(btn.dataset).forEach(function (key) {
        if (key === "applyTier" || key === "applyTierInit") return;
        var input = form.querySelector('[name="' + key + '"]');
        if (input) input.value = btn.dataset[key];
      });
    });
  }

  function setHidden(form, name, value) {
    var el = form.querySelector('input[type=hidden][name="' + name + '"]');
    if (!el) {
      el = document.createElement("input");
      el.type = "hidden";
      el.name = name;
      form.appendChild(el);
    }
    el.value = value;
  }

  function initDynamicScope(root) {
    root.querySelectorAll("[data-cselect]").forEach(initCSelect);
    root.querySelectorAll("[data-repeatable-blocks]").forEach(initRepeatableBlocks);
    root.querySelectorAll("[data-schedule-field]").forEach(initScheduleField);
    root.querySelectorAll("[data-local-dt]").forEach(initLocalDateTime);
    root.querySelectorAll("[data-tz-offset-field]").forEach(initTzOffsetField);
    root.querySelectorAll("[data-apply-tier]").forEach(initApplyTierButton);
    root.querySelectorAll("[data-preserve-post-form]").forEach(initPreservePostForm);
    root.querySelectorAll("[data-tabs]").forEach(initTabs);
  }

  // Owner-reported 2026-09-15: the datetime picker (data-schedule-field,
  // e.g. "Sửa" on /admin/schedule, /admin/post's "Đăng lên tường cá
  // nhân") visually goes BLANK after switching away to another browser
  // tab and back — not the in-page htmx tabs above (those already
  // re-sync via initDynamicScope() on htmx:afterSwap, see the comment
  // just below), and not lost data either: the hidden UTC field
  // (data-schedule-utc, the one actually submitted) still holds the
  // right value the whole time, only the VISIBLE <input
  // type="datetime-local"> (data-schedule-local)'s own rendered text
  // clears — a known Chromium quirk where a datetime-local input's
  // value was set via JS (initScheduleField's own prefill, or a
  // quick-pick button) rather than typed by the user, and the widget's
  // internal display cache doesn't survive the tab losing/regaining
  // visibility. Pressing F5 "fixes" it only because that re-runs
  // initScheduleField's prefill from scratch on a freshly-parsed page —
  // this does the exact same re-derivation without a reload, driven by
  // whichever value the hidden UTC field ALREADY has (so it can't ever
  // clobber an in-progress edit: every keystroke in the visible field
  // already re-synced the hidden one via its own "input" listener
  // first).
  function refreshScheduleFieldDisplays() {
    document.querySelectorAll("[data-schedule-field]").forEach(function (wrap) {
      var localInput = wrap.querySelector("[data-schedule-local]");
      var utcInput = wrap.querySelector("[data-schedule-utc]");
      if (!localInput || !utcInput || !utcInput.value) return;
      var d = new Date(utcInput.value);
      if (isNaN(d.getTime())) return;
      localInput.value = toLocalInputValue(d);
    });
  }
  document.addEventListener("visibilitychange", function () {
    if (!document.hidden) refreshScheduleFieldDisplays();
  });
  // Covers the same class of "came back to this tab/page" case for
  // bfcache restores (e.g. navigating back), which don't always fire
  // visibilitychange on every browser.
  window.addEventListener("pageshow", function () { refreshScheduleFieldDisplays(); });

  document.addEventListener("DOMContentLoaded", function () { initDynamicScope(document); });
  // /admin/schedule's account filter / update / fire-now / cancel all
  // htmx-swap a fresh #schedule-content in (outerHTML swap) —
  // DOMContentLoaded never fires again for that. Re-scanning the WHOLE
  // document (not just e.detail.target) is deliberate: for an outerHTML
  // swap, htmx's own event.detail.target can still reference the
  // now-detached old element rather than the new one it was replaced
  // with, so scoping to it silently skipped the freshly-inserted
  // datetime pickers — they never got their visible <input
  // type="datetime-local"> synced from the hidden UTC value, which
  // looked exactly like "the picker reset" after switching accounts
  // (the conversation that found this). Each init function above guards
  // against re-initializing an already-initialized element, so
  // rescanning the whole page on every swap is safe, not wasteful.
  //
  // Listener attached to `document`, NOT `document.body` (bug found
  // 2026-09-15, owner report: switching /admin/schedule's own
  // "Task đã lên lịch"/"Task quá hạn" tabs back and forth blanked the
  // datetime picker EVERY time, F5 was the only fix) — this whole
  // <script> block runs inside <head> (see _PAGE_STYLE/_layout()),
  // where `document.body` is still null; `document.body.
  // addEventListener(...)` therefore THREW immediately at parse time
  // and this listener never actually registered AT ALL, on ANY admin
  // page, since whenever this line was first written — every htmx swap
  // silently ran with NO re-init happening, only ever masked by
  // DOMContentLoaded's own one-time init succeeding on first load
  // (confirmed live with Playwright: a thrown pageerror at parse time,
  // stack pointing at this exact line; dataset.scheduleInit never set
  // on a post-swap element, proving initScheduleField() never ran for
  // it). Custom events htmx dispatches on the swapped element still
  // bubble all the way up to `document` regardless — `document` itself
  // exists even mid-<head>, unlike `document.body` — so this is the
  // full fix, not a workaround.
  document.addEventListener("htmx:afterSwap", function () { initDynamicScope(document); });
})();
</script>
"""


def _custom_select(
    name: str, options: list[str], selected: str | None = None, labels: dict[str, str] | None = None
) -> str:
    """Render a styled dropdown (trigger button + panel opening below it)
    backed by a real <select name="..."> so existing form handlers and
    field names keep working unchanged. `labels` maps a raw option value
    (e.g. "post_to_group", an account_id) to what a person should read
    instead (e.g. "Đăng vào nhóm", "Trang của tôi (my_page)") — the
    dropdown still submits/stores the raw value, only the displayed text
    changes. The custom-dropdown JS (initCSelect below) reads its panel
    text straight from each native <option>'s textContent, so labelling
    happens entirely here — no JS change needed."""
    if selected is None:
        selected = options[0] if options else ""
    labels = labels or {}
    native_opts = "".join(
        f'<option value="{html.escape(opt)}"{" selected" if opt == selected else ""}>{html.escape(labels.get(opt, opt))}</option>'
        for opt in options
    )
    return f"""<div class="cselect" data-cselect>
  <select name="{html.escape(name)}" class="cselect-native">{native_opts}</select>
  <button type="button" class="cselect-trigger"><span class="cselect-trigger-label">{html.escape(labels.get(selected, selected))}</span><span class="chevron">▾</span></button>
  <div class="cselect-panel"></div>
</div>"""


def _datetime_picker_html(name: str, current_value: str = "", required: bool = False, blank_hint: bool = True) -> str:
    """A real <input type="datetime-local"> for any "when to post" field —
    /admin/post's compose forms and /admin/schedule's edit form. The
    visible picker is NEVER itself submitted; it only drives a hidden
    `name`-named field (the initScheduleField JS, in this module's page
    script) that always carries a UTC ISO 8601 string, which is what
    _parse_scheduled_at()/schedule_store actually read. This conversion
    is deliberately done in the browser, not here — only the browser
    knows the viewer's local timezone, so converting server-side would
    silently assume UTC and shift every pick by the real offset.

    The picker interprets whatever is typed using the OPERATOR's own
    device timezone (standard <input type="datetime-local"> behavior) —
    correct automatically for someone in Japan picking a Japan-time slot;
    no separate timezone-conversion display (dropped per project owner
    feedback — the raw picker is enough).

    Clicking anywhere in the field opens the native picker (not just its
    small calendar icon) via the input's own `.showPicker()` — wired up
    in initScheduleField, guarded for browsers that don't have it yet."""
    hint = ' <span class="muted" style="font-size:12px;">(để trống = ngay bây giờ)</span>' if blank_hint else ""
    presets = (
        '<button type="button" class="btn-secondary btn-small" data-schedule-preset="now">Ngay bây giờ</button>'
        '<button type="button" class="btn-secondary btn-small" data-schedule-preset="+1h">+1 giờ</button>'
        '<button type="button" class="btn-secondary btn-small" data-schedule-preset="+1d">Ngày mai, giờ này</button>'
    )
    return (
        f'<div data-schedule-field style="display:flex; align-items:center; gap:8px; flex-wrap:wrap;">'
        f'<input type="datetime-local"{" required" if required else ""} data-schedule-local>'
        f'<input type="hidden" name="{html.escape(name)}" data-schedule-utc value="{html.escape(current_value)}">'
        f"{presets}"
        f"{hint}"
        f"</div>"
    )


def _is_htmx(request: Request) -> bool:
    """True when this request came from an htmx-driven interaction (a
    hx-get/hx-post triggered by the browser JS), not a normal navigation
    or a plain form submit with no JS. Routes that support both use this
    to decide: return just the refreshed fragment for htmx (so it can
    swap it in without a full reload), or the full page / a redirect
    otherwise — the plain <form method="post" action="..."> on every
    mutating form still works with JS disabled, just with a full page
    reload, so nothing breaks if htmx fails to load."""
    return request.headers.get("hx-request") == "true"


def _require_auth(credentials: HTTPBasicCredentials | None = Depends(_security)) -> None:
    expected_user = os.environ.get("ADMIN_USERNAME")
    expected_pass = os.environ.get("ADMIN_PASSWORD")
    if not expected_user or not expected_pass:
        return
    valid = (credentials is not None
             and secrets.compare_digest(credentials.username, expected_user)
             and secrets.compare_digest(credentials.password, expected_pass))
    if not valid:
        raise HTTPException(status_code=status.HTTP_401_UNAUTHORIZED, detail="Unauthorized",
                             headers={"WWW-Authenticate": "Basic"})


def _layout(body: str, active: str = "") -> str:
    def nav_class(key: str) -> str:
        return "active" if key == active else ""

    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>human_bot admin</title>{_PAGE_STYLE}</head>
<body>
<div id="modal-root"></div>
<div class="topbar">
  <div class="topbar-inner">
    <div class="brand"><span class="brand-dot"></span> human_bot</div>
    <nav class="topnav">
      <a href="/admin" class="{nav_class('home')}">Trang chủ</a>
      <a href="/admin/accounts" class="{nav_class('accounts')}">Tài khoản</a>
      <a href="/admin/config" class="{nav_class('config')}">Cấu hình</a>
      <a href="/admin/post" class="{nav_class('post')}">Đăng bài</a>
      <a href="/admin/groups" class="{nav_class('groups')}">Nhóm đã tham gia</a>
      <a href="/admin/schedule" class="{nav_class('schedule')}">Lịch đăng</a>
      <a href="/admin/reports" class="{nav_class('reports')}">Báo cáo</a>
    </nav>
  </div>
</div>
<main>
{body}
</main>
</body></html>"""


@router.get("", response_class=HTMLResponse)
async def admin_home(_: None = Depends(_require_auth)) -> str:
    accounts = get_all_accounts()
    accounts_html = "".join(f"<li>{html.escape(a.display_name)} ({html.escape(aid)})</li>" for aid, a in accounts.items()) or '<span class="muted">Chưa có tài khoản nào</span>'

    # Surfaced here, not just at /admin/accounts, because the whole point
    # of auto-pause (human_bot/agent.py's run_task(), on
    # human_bot/safety.py's AnomalyDetected) is that a human notices
    # promptly — burying it one click deep defeats that (raised in the
    # admin UI review that asked for this).
    paused = [a for a in accounts.values() if a.status == AccountStatus.PAUSED]
    if paused:
        names = ", ".join(html.escape(a.display_name) for a in paused)
        pause_warning = f"""
<div class="error" style="margin-bottom:20px;">
  ⚠️ {len(paused)} tài khoản đang <strong>Tạm dừng</strong>: {names} — human_bot sẽ không đăng/comment/like gì cho các tài khoản này.
  <a href="/admin/accounts" style="margin-left:6px;">Xem / kích hoạt lại →</a>
</div>"""
    else:
        pause_warning = ""

    return _layout(f"""
<h1>Bảng điều khiển</h1>
<p class="page-desc">Trang quản trị nội bộ. Không public trang này ra internet — nó có quyền đăng bài thật lên Facebook.</p>
{pause_warning}
<div class="card">
  <h2>👤 Tài khoản đã đăng ký <span class="badge">{len(accounts)}</span></h2>
  <ul class="account-list">{accounts_html}</ul>
</div>

<div class="home-links">
  <a class="home-link-card" href="/admin/accounts">
    <div class="title">👤 Tài khoản</div>
    <div class="desc">Đăng ký tài khoản mới sau khi chạy bootstrap_login.py, tạm dừng/kích hoạt lại, xoá — không cần sửa code.</div>
  </a>
  <a class="home-link-card" href="/admin/config">
    <div class="title">⚙️ Cấu hình</div>
    <div class="desc">Tốc độ gõ, khoảng chờ, di chuyển chuột (tab "Cấu hình hành vi") và chu kỳ/ngưỡng lọc của bộ đồng bộ bên B (tab "Đồng bộ dữ liệu") — áp dụng ngay, không cần khởi động lại.</div>
  </a>
  <a class="home-link-card" href="/admin/post">
    <div class="title">📝 Đăng bài</div>
    <div class="desc">Soạn nội dung, lên lịch đăng tường cá nhân hoặc nhiều nhóm cùng lúc, quản lý hàng đợi nội dung.</div>
  </a>
  <a class="home-link-card" href="/admin/groups">
    <div class="title">👥 Nhóm đã tham gia</div>
    <div class="desc">Danh sách URL nhóm Facebook mỗi tài khoản đã tham gia — bộ đồng bộ bên B dùng để broadcast bài đăng nhóm.</div>
  </a>
  <a class="home-link-card" href="/admin/schedule">
    <div class="title">🔄 Lịch đăng</div>
    <div class="desc">Xem, sửa, huỷ mọi bài đang chờ đăng — dù lên lịch thủ công ở /admin/post hay tự động từ bộ đồng bộ bên B.</div>
  </a>
  <a class="home-link-card" href="/admin/reports">
    <div class="title">📊 Báo cáo</div>
    <div class="desc">Tài khoản nào đăng bao nhiêu bài mỗi tuần, đăng vào nhóm nào, tỉ lệ thành công/thất bại.</div>
  </a>
</div>
""", active="home")


@router.get("/config", response_class=HTMLResponse)
async def config_form(saved: bool = False, tab: str = "behavior", _: None = Depends(_require_auth)) -> str:
    def render_rows(config_cls, editable_fields, labels, current, prefix, field_subset=None):
        """`field_subset` narrows which of `editable_fields` actually get
        rendered here — used to split DataSyncConfig's 2 AI-toggle fields
        out into their own tab (see below) without needing a whole
        separate _CONFIG_SECTIONS entry/save path for them; they still
        save through the same save_data_sync_overrides() as every other
        DataSyncConfig field, just rendered in a different card/tab."""
        defaults = config_cls()
        names = field_subset if field_subset is not None else editable_fields
        rows = []
        for field_name in names:
            label = labels.get(field_name, field_name)
            default_val = getattr(defaults, field_name)
            value = current.get(field_name, default_val)
            form_name = f"{prefix}__{field_name}"
            if field_name in _BOOL_FIELDS:
                checked = "checked" if value else ""
                input_html = (
                    f'<label class="switch"><input type="checkbox" name="{form_name}" value="true" {checked}>'
                    f'<span class="switch-slider"></span></label>'
                )
            else:
                input_html = f'<input type="number" step="any" name="{form_name}" value="{html.escape(str(value))}">'
            sub_line = (
                html.escape(_FIELD_DESCRIPTIONS[field_name]) if field_name in _FIELD_DESCRIPTIONS
                else f"mặc định: {html.escape(str(default_val))} · key: {field_name}"
            )
            rows.append(f"""
<div class="field-row">
  <div class="field-label">{html.escape(label)}<div class="field-key">{sub_line}</div></div>
  <div class="field-input">{input_html}</div>
</div>""")
        return "".join(rows)

    def render_card(icon: str, title: str, rows_html: str) -> str:
        return f"""
<div class="card">
  <h2>{icon} {html.escape(title)}</h2>
  <div class="field-grid">{rows_html}</div>
</div>"""

    sections_html = []
    for section_key, prefix, title, config_cls, editable_fields, labels, get_overrides, _save_fn in _CONFIG_SECTIONS:
        current = get_overrides()
        if section_key == "data_sync":
            # Pulled out into the "ai" tab below, alongside the API key
            # card — everything else from DataSyncConfig stays here.
            fields_here = [f for f in editable_fields if f not in _AI_TOGGLE_FIELDS]
        else:
            fields_here = editable_fields
        rows_html = render_rows(config_cls, editable_fields, labels, current, prefix, fields_here)
        icon = _ICONS.get(prefix, "")
        sections_html.append((section_key, render_card(icon, title, rows_html)))

    data_sync_current = get_data_sync_overrides()
    ai_toggle_rows = render_rows(
        DataSyncConfig, EDITABLE_DATA_SYNC_FIELDS, _DATA_SYNC_LABELS, data_sync_current, "data_sync",
        [f for f in EDITABLE_DATA_SYNC_FIELDS if f in _AI_TOGGLE_FIELDS],
    )
    ai_toggle_card = render_card("🤖", "Bật/tắt AI", ai_toggle_rows)

    flash = '<p class="flash">✅ Đã lưu cấu hình. Áp dụng ngay từ lần đăng bài tiếp theo.</p>' if saved else ""

    behavior_cards = "".join(card for key, card in sections_html if key != "data_sync")
    sync_cards = "".join(card for key, card in sections_html if key == "data_sync")

    active_tab = tab if tab in ("behavior", "sync", "ai") else "behavior"

    def tab_btn(key: str, label: str) -> str:
        cls = "tab-btn active" if key == active_tab else "tab-btn"
        return f'<button type="button" class="{cls}" data-tab-target="tab-{key}">{label}</button>'

    def panel_attrs(key: str) -> str:
        return "" if key == active_tab else " hidden"

    return _layout(f"""
<h1>Cấu hình</h1>
<p class="page-desc">Ghi vào runtime_config.json (không đụng tới .env), có hiệu lực ngay, không cần khởi động lại service.</p>
{flash}
<form method="post" action="/admin/config">
<div data-tabs>
  <div class="tab-bar">
    {tab_btn("behavior", "🧑 Cấu hình hành vi")}
    {tab_btn("sync", "🔄 Đồng bộ dữ liệu")}
    {tab_btn("ai", "🤖 AI")}
  </div>

  <div class="tab-panel" id="tab-behavior"{panel_attrs("behavior")}>
    {behavior_cards}
  </div>

  <div class="tab-panel" id="tab-sync"{panel_attrs("sync")}>
    <p class="page-desc">Cấu hình cho bộ đồng bộ dữ liệu bên B (human_bot/data_sync.py). Lần sync gần nhất theo từng tài khoản: xem <a href="/admin/accounts?tab=sync">Tài khoản → Đồng bộ</a>.</p>
    {sync_cards}
  </div>

  <div class="tab-panel" id="tab-ai"{panel_attrs("ai")}>
    <p class="page-desc">Chọn nhà cung cấp AI + key/model và công tắc bật/tắt cho AI soạn bài tin tuyển dụng đăng nhóm + viết lại reply ứng viên (human_bot/content_strategist.py, human_bot/ai_client.py). Cả 2 công tắc dưới đây vẫn là field của bộ đồng bộ bên B (DataSyncConfig) — chỉ tách ra hiển thị riêng ở đây cho gọn.</p>
    {_ai_provider_card_html()}
    {ai_toggle_card}
  </div>
</div>
<div class="form-actions"><button type="submit">Lưu cấu hình</button></div>
</form>
""", active="config")


@router.post("/config")
async def config_save(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    """Blindly casting every numeric field to `float` here used to corrupt
    any field whose dataclass actually declares `int` (found 2026-09-07:
    HumanMouseConfig.min_steps/max_steps went 8 -> 8.0 the very first time
    this route was ever used to save ANY section, since one submit here
    covers every section's fields at once — then silently crashed
    human_mouse_move()'s `range(1, steps + 1)` months later, only on the
    rare click distance that clamps to exactly one of those bounds, with
    'float' object cannot be interpreted as an integer). Now casts to
    whatever type each dataclass field actually declares, via
    dataclasses.fields(), so an int-typed field survives a round trip
    through this form as a real int."""
    form = await request.form()
    for section_key, prefix, _title, config_cls, editable_fields, _labels, _get_fn, save_fn in _CONFIG_SECTIONS:
        field_types = {f.name: f.type for f in dataclasses.fields(config_cls)}
        values: dict = {}
        for field_name in editable_fields:
            form_name = f"{prefix}__{field_name}"
            if field_name in _BOOL_FIELDS:
                values[field_name] = form_name in form
                continue
            raw = form.get(form_name)
            if raw in (None, ""):
                continue
            caster = int if field_types.get(field_name) is int else float
            try:
                values[field_name] = caster(float(raw))
            except (TypeError, ValueError):
                continue
        save_fn(values)
    return RedirectResponse(url="/admin/config?saved=1", status_code=303)


@router.post("/config/ai-provider", response_class=HTMLResponse)
async def config_ai_provider_save(request: Request, _: None = Depends(_require_auth)) -> str:
    form = await request.form()
    provider_keys = [p["key"] for p in _AI_PROVIDERS]
    provider = str(form.get("ai_provider", "anthropic")).strip().lower()
    if provider not in provider_keys:
        provider = "anthropic"

    updates: dict[str, Any] = {"ai_provider": provider}
    for p in _AI_PROVIDERS:
        for field in (p["key_field"], p["model_field"], p["base_url_field"]):
            if not field:
                continue
            # Blank means "leave unchanged" (see the card's own field-key
            # hint) — same semantics the single-provider version of this
            # route always had; the separate "Xoá key" button is what
            # actually clears a field.
            raw = str(form.get(field, "")).strip()
            if raw:
                updates[field] = raw
    save_secrets_overrides(updates)
    return _ai_provider_card_html(flash='<p class="flash">✅ Đã lưu cấu hình AI.</p>')


@router.post("/config/ai-provider/clear-key", response_class=HTMLResponse)
async def config_ai_provider_clear_key(request: Request, _: None = Depends(_require_auth)) -> str:
    form = await request.form()
    provider = str(form.get("provider", "")).strip().lower()
    provider_info = next((p for p in _AI_PROVIDERS if p["key"] == provider), None)
    if provider_info:
        save_secrets_overrides({provider_info["key_field"]: ""})
    return _ai_provider_card_html(flash='<p class="flash">✅ Đã xoá key — quay lại dùng key trong .env (nếu có) hoặc không dùng AI.</p>')


def _account_id_error(account_id: str, existing: dict) -> str | None:
    if not account_id:
        return "account_id không được để trống"
    if not re.fullmatch(r"[a-z0-9_]+", account_id):
        return "account_id chỉ được dùng chữ thường, số và dấu gạch dưới (không dấu cách, không hoa)"
    if account_id in existing:
        return f"account_id '{account_id}' đã tồn tại"
    return None


def _account_modal_html(account_id: str = "", display_name: str = "", error: str | None = None) -> str:
    """Renders the whole #modal-root swap for the "Đăng ký tài khoản mới"
    form — same pattern as _group_modal_html(): opened via GET (button
    below), redisplayed with a validation error on a bad POST without
    losing what was typed, and a successful POST returns something else
    entirely (_accounts_content_html's oob update) which is what actually
    closes it."""
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    tier_options = "".join(
        f'<option value="{tier_key}"{" selected" if tier_key == DEFAULT_ACCOUNT_AGE_TIER else ""}>'
        f'{html.escape(label)} ({rl.posts_per_day} bài/ngày)</option>'
        for tier_key, (label, rl) in ACCOUNT_AGE_TIERS.items()
    )
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box modal-box-wide">
    <div class="modal-header">
      <h2>➕ Đăng ký tài khoản mới</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    <p class="page-desc">Chỉ đăng ký sau khi đã chạy <code>python3 human_bot/bootstrap_login.py &lt;account_id&gt;</code> trên máy này để lưu phiên đăng nhập.</p>
    {err_html}
    <form method="post" action="/admin/accounts/add" hx-post="/admin/accounts/add" hx-target="#modal-root" hx-swap="innerHTML">
      <div class="field-grid">
        <div class="field-stack"><div class="field-label">account_id (khớp với tên đã dùng ở bootstrap_login.py)</div><div class="field-input"><input type="text" name="account_id" value="{html.escape(account_id)}" placeholder="vd: my_page" required pattern="[a-z0-9_]+"></div></div>
        <div class="field-stack"><div class="field-label">Tên hiển thị</div><div class="field-input"><input type="text" name="display_name" value="{html.escape(display_name)}" placeholder="vd: Trang của tôi"></div></div>
        <div class="field-stack"><div class="field-label">Tuổi tài khoản Facebook (đặt giới hạn tốc độ ban đầu tương ứng)</div><div class="field-input"><select name="age_tier">{tier_options}</select></div></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        <button type="submit">Đăng ký</button>
      </div>
    </form>
  </div>
</div>"""


def _bootstrap_login_status_html(account_id: str) -> str:
    """The part of the "Đăng nhập & lưu phiên" modal that changes as the
    background login session (human_bot/bootstrap_login_sessions.py)
    progresses — polled by htmx every 2s while "opening"/"waiting_confirm"
    so an operator watching /admin sees the real state (in particular:
    when it's finally safe to click "Đã đăng nhập xong") without needing
    to guess or refresh."""
    state, error = bootstrap_login_sessions.status(account_id)
    aid_html = html.escape(account_id)
    if state in ("none", "opening"):
        return f"""
<div id="bootstrap-login-status" hx-get="/admin/accounts/bootstrap-login/status?account_id={aid_html}"
     hx-trigger="load delay:2s" hx-target="this" hx-swap="outerHTML">
  <p class="page-desc">⏳ Đang mở trình duyệt cho <code>{aid_html}</code>... Cửa sổ Chrome sẽ hiện trên MÁY ĐANG CHẠY human_bot (không phải máy bạn đang xem trang này).</p>
</div>"""
    if state == "waiting_confirm":
        return f"""
<div id="bootstrap-login-status">
  <p class="page-desc">🌐 Cửa sổ trình duyệt đã mở tới trang đăng nhập Facebook. Đăng nhập thủ công (kể cả 2FA nếu có) tới khi vào được trang chủ Facebook bình thường, rồi bấm nút bên dưới.</p>
  <div class="form-actions">
    <button type="button" class="btn-secondary" style="margin-right:8px;"
      hx-post="/admin/accounts/bootstrap-login/cancel" hx-vals='{{"account_id": "{aid_html}"}}'
      hx-target="#bootstrap-login-status" hx-swap="outerHTML">✕ Huỷ, đóng trình duyệt</button>
    <button type="button"
      hx-post="/admin/accounts/bootstrap-login/confirm" hx-vals='{{"account_id": "{aid_html}"}}'
      hx-target="#bootstrap-login-status" hx-swap="outerHTML">✅ Đã đăng nhập xong, lưu phiên</button>
  </div>
</div>"""
    if state == "saved":
        # Not actually reachable via polling — accounts_bootstrap_login_
        # confirm() (the only path that reaches "saved") pops the session
        # right after, so the next status() call sees "none" again. Kept
        # as a defensive fallback rendering, not dead-code cleanup bait.
        return f"""
<div id="bootstrap-login-status">
  <p class="flash">✅ Đã lưu phiên đăng nhập cho <code>{aid_html}</code>. Có thể đóng cửa sổ này.</p>
</div>"""
    # "error"
    err_html = html.escape(error or "lỗi không rõ")
    return f"""
<div id="bootstrap-login-status">
  <p class="error">⚠️ Không mở được trình duyệt cho <code>{aid_html}</code>: {err_html}</p>
  <div class="form-actions">
    <button type="button"
      hx-post="/admin/accounts/bootstrap-login/start" hx-vals='{{"account_id": "{aid_html}"}}'
      hx-target="#bootstrap-login-status" hx-swap="outerHTML">🔁 Thử lại</button>
  </div>
</div>"""


def _bootstrap_login_modal_html(account_id: str) -> str:
    aid_html = html.escape(account_id)
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>🌐 Đăng nhập &amp; lưu phiên — {aid_html}</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    <p class="page-desc">Thay cho việc tự chạy <code>python3 human_bot/bootstrap_login.py {aid_html}</code> trong terminal — chỉ dùng được khi human_bot đang chạy trên máy có màn hình (không phải server từ xa/không màn hình), vì trình duyệt mở ra nằm trên máy đó, không phải máy bạn đang xem trang admin này.</p>
    <div class="form-actions">
      <button type="button"
        hx-post="/admin/accounts/bootstrap-login/start" hx-vals='{{"account_id": "{aid_html}"}}'
        hx-target="#bootstrap-login-status" hx-swap="outerHTML">🌐 Mở trình duyệt đăng nhập</button>
    </div>
    <div id="bootstrap-login-status"></div>
  </div>
</div>"""


@router.get("/accounts/bootstrap-login-modal", response_class=HTMLResponse)
async def accounts_bootstrap_login_modal(account_id: str, _: None = Depends(_require_auth)) -> str:
    return _bootstrap_login_modal_html(account_id)


@router.post("/accounts/bootstrap-login/start", response_class=HTMLResponse)
async def accounts_bootstrap_login_start(request: Request, _: None = Depends(_require_auth)) -> str:
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    if not re.fullmatch(r"[a-z0-9_]+", account_id or ""):
        return '<div id="bootstrap-login-status"><p class="error">⚠️ account_id không hợp lệ</p></div>'
    # Fire-and-forget: bootstrap_login_sessions.start() opens the (headed)
    # browser and awaits page.goto() itself, which can take a couple
    # seconds — the request handler returns immediately with a polling
    # panel instead of making the operator's browser tab hang waiting on
    # it. See that module's docstring for the full state machine.
    asyncio.create_task(bootstrap_login_sessions.start(account_id))
    return _bootstrap_login_status_html(account_id)


@router.get("/accounts/bootstrap-login/status", response_class=HTMLResponse)
async def accounts_bootstrap_login_status(account_id: str, _: None = Depends(_require_auth)) -> str:
    return _bootstrap_login_status_html(account_id)


@router.post("/accounts/bootstrap-login/confirm", response_class=HTMLResponse)
async def accounts_bootstrap_login_confirm(request: Request, _: None = Depends(_require_auth)) -> str:
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    ok, error = await bootstrap_login_sessions.confirm(account_id)
    aid_html = html.escape(account_id)
    if not ok:
        # bootstrap_login_sessions.confirm() already dropped the dead
        # session on failure (browser/context closed either way) — offer
        # a way back in instead of a dead-end message with no button.
        err_html = html.escape(error or "lỗi không rõ")
        return f"""
<div id="bootstrap-login-status">
  <p class="error">⚠️ {err_html}</p>
  <div class="form-actions">
    <button type="button"
      hx-post="/admin/accounts/bootstrap-login/start" hx-vals='{{"account_id": "{aid_html}"}}'
      hx-target="#bootstrap-login-status" hx-swap="outerHTML">🔁 Mở lại trình duyệt</button>
  </div>
</div>"""
    # confirm() already popped the in-memory session on success, so
    # _bootstrap_login_status_html(account_id) would now read back "none"
    # (nothing in flight) and render the wrong ("still opening") panel —
    # build the success message directly instead of going through it.
    # Also refresh the accounts table out-of-band so the "chưa có
    # storage_state.json" badge/button for this row flips to "phiên OK"
    # without the operator needing to close the modal and reload.
    return f"""
<div id="bootstrap-login-status">
  <p class="flash">✅ Đã lưu phiên đăng nhập cho <code>{aid_html}</code>. Có thể đóng cửa sổ này.</p>
</div>{_accounts_content_html(oob=True)}"""


@router.post("/accounts/bootstrap-login/cancel", response_class=HTMLResponse)
async def accounts_bootstrap_login_cancel(request: Request, _: None = Depends(_require_auth)) -> str:
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    await bootstrap_login_sessions.cancel(account_id)
    return '<div id="bootstrap-login-status"><p class="page-desc">Đã đóng trình duyệt, chưa lưu phiên đăng nhập.</p></div>'


_RATE_LIMITS_LABELS: dict[str, str] = {
    "posts_per_day": "Số bài đăng tối đa / ngày",
    "comments_per_hour": "Số comment tối đa / giờ",
    "comments_per_day": "Số comment tối đa / ngày",
    "likes_per_hour": "Số like tối đa / giờ",
    "post_min_delay_seconds": "Khoảng chờ tối thiểu giữa 2 BÀI ĐĂNG (giây)",
    "post_max_delay_seconds": "Khoảng chờ tối đa giữa 2 BÀI ĐĂNG (giây)",
    "comment_min_delay_seconds": "Khoảng chờ tối thiểu giữa 2 COMMENT (giây)",
    "comment_max_delay_seconds": "Khoảng chờ tối đa giữa 2 COMMENT (giây)",
    "max_groups_per_post": "Số nhóm tối đa mỗi tin tuyển dụng được phát vào",
}


def _rate_limits_modal_body_html(account_id: str, limits: RateLimits, is_override: bool, error: str | None = None) -> str:
    """Just the part of the "Giới hạn tốc độ" modal that actually changes
    when a quick-apply age-tier button is clicked — the backdrop/box/header
    shell around this (_rate_limits_modal_html, below) stays untouched
    across those clicks. Split out 2026-09-07 after the tier buttons were
    found to make the WHOLE modal visibly jump/flash on every click, when
    they swapped #modal-root's entire innerHTML (backdrop included) each
    time — swapping only this inner, id-tagged div instead means the
    backdrop/box never unmounts, so there's nothing left to jump."""
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    rows = "".join(
        f'''<div class="field-row">
  <div class="field-label">{html.escape(label)}<div class="field-key">key: {field}</div></div>
  <div class="field-input"><input type="number" step="1" min="0" name="{field}" value="{getattr(limits, field)}" required></div>
</div>'''
        for field, label in _RATE_LIMITS_LABELS.items()
    )
    reset_note = (
        '<p class="page-desc">Tài khoản này đang dùng giá trị tuỳ chỉnh riêng — bấm "Khôi phục mặc định" để quay lại giá trị chuẩn trong code.</p>'
        if is_override
        else '<p class="page-desc">Tài khoản này đang dùng giá trị mặc định chung (chưa tuỳ chỉnh riêng).</p>'
    )
    # Quick-apply buttons per age tier — for when an account ages into the
    # next tier (e.g. crosses 1 month old) and its limits should loosen a
    # bit, without typing 6 numbers by hand each time. CLIENT-SIDE ONLY
    # (2026-09-11, owner request: clicking a tier used to save immediately
    # via a round-trip to /admin/accounts/rate-limits/apply-tier — surprised
    # the owner mid-investigation when a value changed without an explicit
    # "Lưu" click) — each button just fills the form's number inputs via
    # initRateLimitTierButtons() below, nothing persists until "Lưu" is
    # pressed. The exact values still come from ACCOUNT_AGE_TIERS (server-
    # rendered into data-* attributes, one per editable field except
    # max_groups_per_post — tier presets don't cover that field at all, so
    # a tier click must leave whatever the account currently has there
    # untouched, same as the save route already does), so JS never
    # hardcodes or risks drifting from the real preset numbers.
    #
    # ALSO fills the form's hidden `tier_key` field (2026-09-15, added
    # alongside human_bot/runtime_config.py's get_account_age_tier()) via
    # the exact same generic initApplyTierButton() loop — `data-tier_key`
    # uses an underscore, not a hyphen, so it lands in btn.dataset as
    # `tier_key` (unchanged) rather than being camelCased to `tierKey`,
    # matching the hidden field's `name="tier_key"` with no JS change
    # needed. accounts_rate_limits_save() reads it to persist WHICH tier
    # this save came from — separate from the raw numbers, since the
    # numbers alone can't tell a tier-button click apart from someone
    # typing coincidentally-matching values by hand.
    tier_buttons = "".join(
        f'''<button type="button" class="btn-small btn-secondary" style="margin:2px;" data-apply-tier
        data-tier_key="{tier_key}"
        {" ".join(f'data-{field}="{getattr(rl, field)}"' for field in _RATE_LIMITS_LABELS if field != "max_groups_per_post")}
        >{html.escape(label)} ({rl.posts_per_day} bài/ngày)</button>'''
        for tier_key, (label, rl) in ACCOUNT_AGE_TIERS.items()
    )
    return f"""<div id="rate-limits-body">
    {reset_note}
    {err_html}
    <p class="page-desc">Áp nhanh theo tuổi tài khoản Facebook:</p>
    <div>{tier_buttons}</div>
    <form method="post" action="/admin/accounts/rate-limits" hx-post="/admin/accounts/rate-limits" hx-target="#modal-root" hx-swap="innerHTML">
      <input type="hidden" name="account_id" value="{html.escape(account_id)}">
      <!-- Filled by initApplyTierButton() (this module's page script) when
           a quick-apply tier button above is clicked — tells
           accounts_rate_limits_save() which age tier (if any) to persist
           via set_account_age_tier() alongside the raw numbers below.
           Stays empty if the admin only ever typed numbers by hand,
           which correctly leaves the account's existing age tier
           untouched (see human_bot/runtime_config.py's
           get_account_age_tier()'s docstring for why that field is kept
           separate from these raw numbers in the first place). -->
      <input type="hidden" name="tier_key" value="">
      <div class="field-grid">{rows}</div>
      <div class="form-actions">
        <button type="submit" name="reset" value="1" class="btn-secondary" style="margin-right:8px;">Khôi phục mặc định</button>
        <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        <button type="submit">Lưu</button>
      </div>
    </form>
</div>"""


def _rate_limits_modal_html(account_id: str, limits: RateLimits, is_override: bool, error: str | None = None) -> str:
    """Renders the whole #modal-root swap for the "Giới hạn tốc độ" form —
    same open/redisplay-with-error/close-via-oob-update pattern as
    _account_modal_html() and _group_modal_html(). `limits` is always the
    EFFECTIVE values (override applied if one exists, else the account's
    code-level default) — the form always shows/edits what's actually in
    force, never a stale default alongside an active override. Used for
    the initial open and for any full-page (non-htmx) fallback; the
    quick-apply tier buttons instead swap _rate_limits_modal_body_html()'s
    output directly, see that function's docstring."""
    body = _rate_limits_modal_body_html(account_id, limits, is_override, error)
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box modal-box-wide">
    <div class="modal-header">
      <h2>⏱️ Giới hạn tốc độ — {html.escape(account_id)}</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    {body}
  </div>
</div>"""


def _sync_content_html(saved: bool = False, oob: bool = False) -> str:
    """Everything about the side-B sync that's per-account: the Bật/Tắt
    toggle (human_bot/runtime_config.py's get_sync_disabled_account_ids()/
    set_account_sync_enabled()) AND the last sync_all() outcome
    (human_bot/data_sync.py's get_all_sync_statuses()) — both moved here
    from the "Tài khoản" tab/the old /admin/config page respectively
    (2026-09-08) so everything sync-related lives under one "Đồng bộ" tab
    instead of being split by coincidence of which table it started in.
    Self-contained with its own #sync-content id so its own toggle actions
    can htmx-swap just this block, independent of #accounts-content."""
    accounts = get_all_accounts()
    statuses = get_all_sync_statuses()
    sync_disabled_ids = get_sync_disabled_account_ids()
    flash = '<p class="flash">✅ Đã lưu.</p>' if saved else ""

    rows = []
    for aid, account in accounts.items():
        is_paused = account.status == AccountStatus.PAUSED
        # Paused blocks EVERY action (agent.py's run_task() rejects any
        # status != ACTIVE), sync included — so it already can't run
        # regardless of this override, and the toggle is replaced with a
        # plain note instead of an actionable button.
        if is_paused:
            status_cell = '<span class="row-url">tạm dừng — đã chặn sync</span>'
            action_cell = ""
        elif aid in sync_disabled_ids:
            status_cell = '<span class="badge" style="background:#fef2f2;color:#dc2626;">⏸ Tắt</span>'
            action_cell = f"""<form method="post" action="/admin/accounts/sync-enable" style="display:inline;"
        hx-post="/admin/accounts/sync-enable" hx-target="#sync-content" hx-swap="outerHTML">
  <input type="hidden" name="account_id" value="{html.escape(aid)}">
  <button type="submit" class="btn-small">Bật lại</button>
</form>"""
        else:
            status_cell = '<span class="badge" style="background:#ecfdf5;color:#059669;">● Bật</span>'
            action_cell = f"""<form method="post" action="/admin/accounts/sync-disable" style="display:inline;"
        hx-post="/admin/accounts/sync-disable" hx-target="#sync-content" hx-swap="outerHTML"
        hx-confirm="Tắt đồng bộ dữ liệu bên B cho tài khoản {html.escape(aid)}? Tài khoản vẫn hoạt động bình thường (đăng tay, comment...) — chỉ riêng việc tự lấy job/candidate mới từ bên B bị bỏ qua.">
  <input type="hidden" name="account_id" value="{html.escape(aid)}">
  <button type="submit" class="btn-small btn-secondary">Tắt</button>
</form>"""

        entry = statuses.get(aid)
        if entry is None:
            last_run_cell = '<span class="row-url">chưa chạy lần nào</span>'
        elif entry.get("status") == "ok":
            last_run_cell = (
                f'<span class="badge" style="background:#ecfdf5;color:#059669;">✅ OK</span> '
                f'{_local_dt_html(entry.get("last_run_at"))} — '
                f'{entry.get("jobs_fetched", 0)} job, {entry.get("candidates_fetched", 0)} candidate lấy về, '
                f'{entry.get("scheduled_posts", 0)} bài + {entry.get("scheduled_comments", 0)} comment mới lên lịch'
            )
        else:
            last_run_cell = (
                f'<span class="badge" style="background:#fef2f2;color:#dc2626;">⚠️ Lỗi</span> '
                f'{_local_dt_html(entry.get("last_run_at"))} — {html.escape(str(entry.get("error", "")))}'
            )

        rows.append(f"""
<tr>
  <td>{html.escape(account.display_name)}<div class="row-url">{html.escape(aid)}</div></td>
  <td>{status_cell}</td>
  <td class="col-actions">{action_cell}</td>
  <td>{last_run_cell}</td>
</tr>""")

    table = f"""
<div class="table-scroll">
  <table class="data-table">
    <thead><tr><th>Tài khoản</th><th>Trạng thái</th><th>Hành động</th><th>Lần sync gần nhất</th></tr></thead>
    <tbody>{"".join(rows) or '<tr><td colspan="4" class="empty-state">Chưa có tài khoản nào</td></tr>'}</tbody>
  </table>
</div>"""

    oob_attr = ' hx-swap-oob="true"' if oob else ""
    return f"""<div id="sync-content"{oob_attr}>
{flash}
<div class="card">
  <h2>🔄 Đồng bộ dữ liệu bên B theo tài khoản</h2>
  <p class="page-desc">Bật/tắt riêng cho từng tài khoản — một tài khoản ACTIVE bị tắt ở đây vẫn đăng/comment bình thường qua /admin/post, chỉ riêng việc tự lấy job/candidate mới từ bên B bị bỏ qua. Cấu hình chu kỳ, khoảng cách, ngưỡng lọc... ở <a href="/admin/config?tab=sync">Cấu hình → Đồng bộ dữ liệu</a>.</p>
  {table}
</div>
</div>"""


def _account_age_tier_label(rl: RateLimits) -> str:
    """Which ACCOUNT_AGE_TIERS preset (if any) this account's current
    posts_per_day/comments_per_day matches — shown in the accounts list
    (2026-09-11, owner request: "hiển thị tuổi tài khoản cho dễ biết")
    so the current tier is visible without opening the "⏱️ Giới hạn"
    modal. Matched on posts_per_day + comments_per_day only, the same 2
    fields the modal's own tier buttons show next to their label
    ("{label} (N bài/ngày)") — comments_per_hour/likes_per_hour/the gap
    fields are all DERIVED from those two in every preset (see
    ACCOUNT_AGE_TIERS's own comment in config.py), so matching on just
    these two is equivalent to matching the whole preset in practice.
    Falls back to "Tuỳ chỉnh" (custom) when nothing matches — a manually
    edited value, or max_groups_per_post alone was changed (that field
    isn't part of any tier preset at all, so it never affects this
    match) — not an error, just means the account isn't sitting exactly
    on one of the 5 standard tiers."""
    for label, preset in ACCOUNT_AGE_TIERS.values():
        if rl.posts_per_day == preset.posts_per_day and rl.comments_per_day == preset.comments_per_day:
            return label
    return "Tuỳ chỉnh"


def _accounts_content_html(saved: bool = False, error: str | None = None, oob: bool = False) -> str:
    accounts = get_all_accounts()
    registered_ids = {a["account_id"] for a in get_registered_accounts()}
    flash = '<p class="flash">✅ Đã lưu.</p>' if saved else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""

    rows = []
    for aid, a in accounts.items():
        has_session = a.storage_state_path.exists()
        session_badge = (
            '<span class="badge" style="background:#ecfdf5;color:#059669;">phiên OK</span>'
            if has_session
            else (
                '<span class="badge" style="background:#fef2f2;color:#dc2626;">chưa có storage_state.json</span> '
                f'<button type="button" class="btn-small btn-secondary" '
                f'hx-get="/admin/accounts/bootstrap-login-modal?account_id={html.escape(aid)}" '
                f'hx-target="#modal-root" hx-swap="innerHTML">🌐 Đăng nhập &amp; lưu phiên</button>'
            )
        )
        is_paused = a.status == AccountStatus.PAUSED
        status_badge = (
            '<span class="badge" style="background:#fef2f2;color:#dc2626;">⏸ Tạm dừng</span>'
            if is_paused
            else '<span class="badge" style="background:#ecfdf5;color:#059669;">● Hoạt động</span>'
        )
        # Reason + timestamp of the pause, and (once resumed) the reduced-
        # limit cooldown window — shown right under the badge so a human
        # deciding whether it's actually safe to "Kích hoạt lại" has real
        # context instead of a bare status dot. See
        # docs/skills/anomaly-detection.md and
        # human_bot/safety_cooldown_config.py for the reasoning (a real
        # external report of accounts getting re-flagged after resuming
        # full-speed too soon post-restriction).
        status_detail = ""
        if is_paused:
            info = get_pause_info(aid)
            if info:
                reason_txt = html.escape(info["reason"] or "không rõ (tạm dừng thủ công)")
                when_txt = _local_dt_html(info["paused_at"])
                status_detail = f'<div class="row-url">từ {when_txt} — {reason_txt}</div>'
        else:
            cooldown = get_resume_cooldown_info(aid)
            if cooldown:
                until_txt = _local_dt_html(cooldown.get("until"))
                reason_txt = html.escape(cooldown.get("reason") or "không rõ")
                week = cooldown.get("week")
                base_tier_key = cooldown.get("base_tier")
                base_tier_label = ACCOUNT_AGE_TIERS.get(base_tier_key, (base_tier_key or "?", None))[0]
                week_txt = (
                    f"tuần {week}/2 — mức sàn thấp nhất"
                    if week == 1
                    else f"tuần {week}/2 — đã nhích lên 1 bậc"
                )
                status_detail = (
                    f'<div class="row-url">🧊 Đang hạ nhiệt ({html.escape(str(week_txt))}), '
                    f'xong vào {until_txt}, sẽ quay về mức "{html.escape(base_tier_label)}" '
                    f'— lần trước bị dừng vì: {reason_txt}</div>'
                )
        # Pausing is a runtime override that applies to ANY account
        # (code-level or registered here) — see human_bot/config.py's
        # get_all_accounts() and human_bot/runtime_config.py's
        # set_account_paused(). Also set automatically the moment
        # human_bot/safety.py's AnomalyDetected fires on a real post — see
        # human_bot/agent.py's run_task(). Resuming goes through
        # resume_account() (not set_account_paused directly) so the
        # post-resume cooldown above gets applied.
        status_action = (
            f"""<form method="post" action="/admin/accounts/resume" style="display:inline;"
        hx-post="/admin/accounts/resume" hx-target="#accounts-content" hx-swap="outerHTML">
  <input type="hidden" name="account_id" value="{html.escape(aid)}">
  <button type="submit" class="btn-small">▶ Kích hoạt lại</button>
</form>"""
            if is_paused
            else f"""<form method="post" action="/admin/accounts/pause" style="display:inline;"
        hx-post="/admin/accounts/pause" hx-target="#accounts-content" hx-swap="outerHTML"
        hx-confirm="Tạm dừng tài khoản {html.escape(aid)}? human_bot sẽ không đăng/comment/like gì cho tài khoản này cho tới khi bạn kích hoạt lại.">
  <input type="hidden" name="account_id" value="{html.escape(aid)}">
  <button type="submit" class="btn-small btn-secondary">⏸ Tạm dừng</button>
</form>"""
        )
        is_runtime = aid in registered_ids
        source = "/admin/accounts" if is_runtime else "human_bot/config.py"
        # "Xoá" works on EVERY account now, code-level ones included (see
        # human_bot/runtime_config.py's set_account_removed) — a
        # code-level entry can't actually be deleted from a running
        # process, but this hides it from every list/lookup the same way,
        # undoable by registering the same account_id again here.
        delete_confirm = (
            f"Xoá tài khoản {html.escape(aid)} khỏi danh sách? Sẽ huỷ mọi bài đang chờ lịch của tài khoản này "
            "và xoá danh sách nhóm đã lưu. File storage_state.json (phiên đăng nhập) sẽ KHÔNG bị xoá."
            if is_runtime
            else f"Ẩn tài khoản {html.escape(aid)} (khai báo trong human_bot/config.py) khỏi human_bot? "
            "Sẽ huỷ mọi bài đang chờ lịch và xoá danh sách nhóm đã lưu. Muốn dùng lại: đăng ký lại đúng "
            "account_id này ở đây. File storage_state.json sẽ KHÔNG bị xoá."
        )
        delete_btn = f"""<form method="post" action="/admin/accounts/delete" style="display:inline;"
        hx-post="/admin/accounts/delete" hx-target="#accounts-content" hx-swap="outerHTML"
        hx-confirm="{delete_confirm}">
  <input type="hidden" name="account_id" value="{html.escape(aid)}">
  <button type="submit" class="btn-secondary btn-small">Xoá</button>
</form>"""
        rate_limits_btn = (
            f'<button type="button" class="btn-small btn-secondary" '
            f'hx-get="/admin/accounts/rate-limits-modal?account_id={html.escape(aid)}" '
            f'hx-target="#modal-root" hx-swap="innerHTML">⏱️ Giới hạn</button>'
        )
        age_tier_label = html.escape(_account_age_tier_label(a.rate_limits))
        rows.append(f"""
<tr>
  <td>{html.escape(a.display_name)}<div class="row-url">{html.escape(aid)}</div></td>
  <td>{status_badge}{status_detail}</td>
  <td>{session_badge}</td>
  <td><span class="badge">{age_tier_label}</span></td>
  <td class="row-url">{html.escape(source)}</td>
  <td class="col-actions">{status_action} {rate_limits_btn} {delete_btn}</td>
</tr>""")

    table = f"""
<div class="table-scroll">
  <table class="data-table">
    <thead><tr><th>Tài khoản</th><th>Trạng thái</th><th>Phiên đăng nhập</th><th>Tuổi tài khoản</th><th>Nguồn</th><th></th></tr></thead>
    <tbody>{"".join(rows) or '<tr><td colspan="6" class="empty-state">Chưa có tài khoản nào</td></tr>'}</tbody>
  </table>
</div>"""

    oob_attr = ' hx-swap-oob="true"' if oob else ""
    return f"""<div id="accounts-content"{oob_attr}>
{flash}{err}

<div class="card">
  <h2>👤 Tài khoản hiện có <span class="badge">{len(accounts)}</span>
    <button type="button" class="btn-small" style="margin-left:auto;"
            hx-get="/admin/accounts/add-modal" hx-target="#modal-root" hx-swap="innerHTML">➕ Đăng ký tài khoản mới</button>
  </h2>
  {table}
</div>
</div>"""


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(
    request: Request, saved: bool = False, error: str | None = None, tab: str = "accounts",
    _: None = Depends(_require_auth),
) -> str:
    content = _accounts_content_html(saved, error)
    if _is_htmx(request):
        return content

    active_tab = tab if tab in ("accounts", "sync") else "accounts"

    def tab_btn(key: str, label: str) -> str:
        cls = "tab-btn active" if key == active_tab else "tab-btn"
        return f'<button type="button" class="{cls}" data-tab-target="tab-{key}">{label}</button>'

    def panel_attrs(key: str) -> str:
        return "" if key == active_tab else " hidden"

    return _layout(f"""
<h1>Tài khoản</h1>
<p class="page-desc">Đăng ký tài khoản mới sau khi đã chạy <code>python3 human_bot/bootstrap_login.py &lt;account_id&gt;</code> trên máy này để lưu phiên đăng nhập — không cần sửa human_bot/config.py hay khởi động lại service. Tài khoản đăng ký ở đây dùng rate limit / nhóm mặc định, chỉnh thêm ở /admin/config và /admin/groups nếu cần.</p>

<div data-tabs>
  <div class="tab-bar">
    {tab_btn("accounts", "👤 Tài khoản")}
    {tab_btn("sync", "🔄 Đồng bộ")}
  </div>

  <div class="tab-panel" id="tab-accounts"{panel_attrs("accounts")}>
    {content}
  </div>

  <div class="tab-panel" id="tab-sync"{panel_attrs("sync")}>
    {_sync_content_html(saved=(saved and active_tab == "sync"))}
  </div>
</div>
""", active="accounts")


@router.get("/accounts/add-modal", response_class=HTMLResponse)
async def accounts_add_modal(_: None = Depends(_require_auth)) -> str:
    return _account_modal_html()


@router.post("/accounts/add")
async def accounts_add(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip().lower()
    display_name = str(form.get("display_name", "")).strip()
    error = _account_id_error(account_id, get_all_accounts())
    if error:
        if _is_htmx(request):
            return HTMLResponse(_account_modal_html(account_id=account_id, display_name=display_name, error=error))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': error})}", status_code=303)
    save_registered_account(account_id, display_name or account_id)
    set_account_removed(account_id, False)  # undo a previous "Xoá", if any
    # Falls back to "under_1_month" (owner decision 2026-09-15) rather
    # than silently applying no override at all (the code-level RateLimits
    # default is actually "over_12_months", 30 posts/day — the opposite of
    # the safe assumption a brand-new registration should start from) —
    # the <select> itself already defaults to "under_1_month" too (see
    # _account_modal_html()), so this only ever matters for a direct API
    # call that skips the field entirely.
    age_tier = str(form.get("age_tier", "")).strip()
    if age_tier not in ACCOUNT_AGE_TIERS:
        age_tier = DEFAULT_ACCOUNT_AGE_TIER
    _, preset = ACCOUNT_AGE_TIERS[age_tier]
    save_rate_limits_overrides(account_id, dataclasses.asdict(preset))
    set_account_age_tier(account_id, age_tier)
    if _is_htmx(request):
        # No primary content for #modal-root (the form's own hx-target) —
        # htmx empties it, closing the modal — plus an out-of-band refresh
        # of #accounts-content so the new account shows up immediately.
        return HTMLResponse(_accounts_content_html(saved=True, oob=True))
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.post("/accounts/pause")
async def accounts_pause(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    set_account_paused(account_id, True)
    if _is_htmx(request):
        return HTMLResponse(_accounts_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.post("/accounts/resume")
async def accounts_resume(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    resume_account(account_id)  # clears the pause AND starts the reduced-limit cooldown
    if _is_htmx(request):
        return HTMLResponse(_accounts_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.post("/accounts/sync-disable")
async def accounts_sync_disable(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    set_account_sync_enabled(account_id, False)
    if _is_htmx(request):
        return HTMLResponse(_sync_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?tab=sync&saved=1", status_code=303)


@router.post("/accounts/sync-enable")
async def accounts_sync_enable(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    set_account_sync_enabled(account_id, True)
    if _is_htmx(request):
        return HTMLResponse(_sync_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?tab=sync&saved=1", status_code=303)


@router.post("/accounts/delete")
async def accounts_delete(request: Request, _: None = Depends(_require_auth)):
    """Removes the account from human_bot entirely, whatever its origin:
    delete_registered_account() drops it from /admin/accounts' registry
    (no-op if it's a code-level ACCOUNTS entry instead), and
    set_account_removed() hides it from get_all_accounts() either way —
    that second part is what makes "Xoá" actually work on a code-level
    account too (see human_bot/runtime_config.py's docstring for the undo
    path: register the same account_id again here).

    Also cleans up everything else that would otherwise dangle and
    reference a now-unknown account_id, OR silently reappear if the same
    account_id is registered again later:
    - pending schedule tasks (would error the next time something tries
      to fire them — get_account() raises for an unknown id)
    - the saved joined-groups list
    - any pause status
    - any per-account data-sync opt-out (set_account_sync_enabled)
    - the rate-limits override (human_bot/runtime_config.py's
      save_rate_limits_overrides({})) — without this, re-registering the
      same account_id later and picking a fresh age tier would be
      silently overridden by whatever limits it had before deletion
    - any still-running post-resume cooldown record
      (clear_resume_cooldown()) — found 2026-09-07: left alone, a
      cooldown active at delete time would keep ticking in
      runtime_config.json and its "🧊 Đang hạ nhiệt" banner could
      confusingly reappear for a freshly re-registered account_id later
    - the saved age tier (clear_account_age_tier()) — same "don't
      silently inherit stale state from before the delete" reasoning;
      without this, re-registering the same account_id and picking a
      DIFFERENT age tier would still cooldown-phase using the old,
      never-cleared tier if it's ever paused/resumed

    Deliberately does NOT touch accounts/<id>/storage_state.json (the
    real Facebook login session), action_log.jsonl / the action_log DB
    table, or screenshots/<id>/ — same "never silently delete real login
    data / historical records" reasoning as everywhere else in this
    project; delete those by hand if truly no longer needed."""
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    delete_registered_account(account_id)
    set_account_removed(account_id, True)
    set_account_paused(account_id, False)  # drop any stale pause override too
    set_account_sync_enabled(account_id, True)  # drop any stale sync opt-out too
    save_joined_groups(account_id, [])
    save_rate_limits_overrides(account_id, {})
    clear_resume_cooldown(account_id)
    clear_account_age_tier(account_id)
    for task in schedule_store.list_pending():
        if task.account_id == account_id:
            schedule_store.cancel(task.task_id)
    if _is_htmx(request):
        return HTMLResponse(_accounts_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.get("/accounts/rate-limits-modal", response_class=HTMLResponse)
async def accounts_rate_limits_modal(account_id: str, _: None = Depends(_require_auth)) -> str:
    accounts = get_all_accounts()
    if account_id not in accounts:
        return _rate_limits_modal_html(account_id, RateLimits(), is_override=False, error="Không tìm thấy tài khoản này")
    is_override = bool(get_rate_limits_overrides(account_id))
    return _rate_limits_modal_html(account_id, accounts[account_id].rate_limits, is_override=is_override)


@router.post("/accounts/rate-limits")
async def accounts_rate_limits_save(request: Request, _: None = Depends(_require_auth)):
    """Saves a per-account RateLimits override (human_bot/runtime_config.py's
    save_rate_limits_overrides) — or, on the "Khôi phục mặc định" button
    (form field `reset`), clears it back to the account's code-level
    default. Validated here rather than trusting the <input
    type="number">/min="0"> HTML attributes, which a bad/absent client
    never actually enforces server-side."""
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    accounts = get_all_accounts()
    if account_id not in accounts:
        err = "Không tìm thấy tài khoản này"
        if _is_htmx(request):
            return HTMLResponse(_rate_limits_modal_html(account_id, RateLimits(), is_override=False, error=err))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': err})}", status_code=303)

    if form.get("reset"):
        save_rate_limits_overrides(account_id, {})
        if _is_htmx(request):
            return HTMLResponse(_accounts_content_html(saved=True, oob=True))
        return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)

    def _fail(err: str, attempted: RateLimits):
        if _is_htmx(request):
            return HTMLResponse(_rate_limits_modal_html(account_id, attempted, is_override=True, error=err))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': err})}", status_code=303)

    values: dict[str, int] = {}
    current = accounts[account_id].rate_limits
    for field in EDITABLE_RATE_LIMITS_FIELDS:
        raw = form.get(field)
        try:
            n = int(raw)
        except (TypeError, ValueError):
            return _fail(f"Giá trị '{field}' không hợp lệ", current)
        if n < 0:
            return _fail(f"Giá trị '{field}' phải >= 0", current)
        values[field] = n
    if values["post_min_delay_seconds"] > values["post_max_delay_seconds"]:
        return _fail("Khoảng chờ tối thiểu giữa 2 bài đăng phải nhỏ hơn hoặc bằng khoảng chờ tối đa", RateLimits(**values))
    if values["comment_min_delay_seconds"] > values["comment_max_delay_seconds"]:
        return _fail("Khoảng chờ tối thiểu giữa 2 comment phải nhỏ hơn hoặc bằng khoảng chờ tối đa", RateLimits(**values))

    save_rate_limits_overrides(account_id, values)
    # Only set when a quick-apply tier button was actually clicked (see
    # _rate_limits_modal_body_html()'s tier_buttons comment) — typing
    # numbers by hand leaves this blank, which correctly leaves the
    # account's existing age tier (used only for post-resume cooldown
    # phasing, human_bot/runtime_config.py's get_active_cooldown_rate_
    # limits()) untouched.
    tier_key = str(form.get("tier_key", "")).strip()
    if tier_key:
        set_account_age_tier(account_id, tier_key)
    if _is_htmx(request):
        return HTMLResponse(_accounts_content_html(saved=True, oob=True))
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


def _parse_scheduled_at(raw: str) -> datetime | None:
    """Empty string means "as soon as possible" — `datetime.now(UTC)`, so
    the resulting ScheduledTask is immediately due and can be fired right
    away from /admin/schedule's "🚀 Đăng ngay" button, same as any other
    task. Anything non-empty must be a valid ISO 8601 timestamp; returns
    None on a bad string so the caller can reject the form instead of
    silently scheduling for the wrong time.

    Clamped forward to "now" if it parses to a moment already in the
    past — a picked time can go stale between when it was chosen in the
    browser (e.g. the "Ngay bây giờ" preset snapshots the click-time
    instant) and when the form actually gets submitted. Without this, a
    slow submit on post_schedule_groups() could land every group's
    computed time in the past AT ONCE, and they'd all fire back-to-back
    the moment something checks for due tasks — exactly the "never a
    burst" pacing principle (docs/skills/rate-limiting-pacing.md) this
    project is built around. This never rejects a past pick as an error;
    it just means "as soon as possible", same as leaving the field blank."""
    raw = raw.strip()
    now = datetime.now(timezone.utc)
    if not raw:
        return now
    try:
        dt = datetime.fromisoformat(raw.replace("Z", "+00:00"))
    except ValueError:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    dt = dt.astimezone(timezone.utc)
    return dt if dt > now else now


@router.get("/post", response_class=HTMLResponse)
async def post_form(
    account_id: str | None = None,
    scheduled: int | None = None,
    posted: str | None = None,
    error: str | None = None,
    profile_content: str | None = None,
    profile_scheduled_at: str | None = None,
    tab: str | None = None,
    # From /admin/reports' "📅 Đặt lịch" (owner request 2026-09-12) — a
    # failed group-post or comment's original content/target, so the
    # admin doesn't have to retype it here, just pick a date/time.
    prefill_content: str | None = None,
    prefill_target_url: str | None = None,
    prefill_retry_of_log_id: int | None = None,
    _: None = Depends(_require_auth),
) -> str:
    accounts = get_all_accounts()
    account_ids = list(accounts)
    if not account_ids:
        return _layout(
            '<h1>Đăng bài</h1><div class="empty-state">Chưa có tài khoản nào — '
            'đăng ký ở <a href="/admin/accounts">/admin/accounts</a> trước.</div>',
            active="post",
        )
    if account_id not in accounts:
        account_id = account_ids[0]
    account_labels = {aid: _account_label(aid, accounts) for aid in account_ids}

    if scheduled:
        flash = '<p class="flash">✅ Đã lên lịch — xem/sửa/đăng ngay ở /admin/schedule.</p>'
    elif posted:
        flash = f'<p class="flash">✅ {html.escape(posted)}</p>'
    else:
        flash = ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""

    # Doesn't block composing/scheduling for a paused account — a task
    # created now is still safely staged behind /admin/schedule's own
    # review step — just warns up front instead of letting it silently
    # fail with "account_paused" whenever something later tries to fire
    # it (found in the admin UI review that asked for this).
    pause_warning = ""
    if accounts[account_id].status == AccountStatus.PAUSED:
        pause_warning = (
            '<div class="error">⚠️ Tài khoản này đang <strong>Tạm dừng</strong> — bài lên lịch ở đây sẽ '
            'không tự đăng cho tới khi bạn <a href="/admin/accounts">kích hoạt lại</a>.</div>'
        )

    auto_fire_notice = _auto_fire_status_html()

    # Choosing the account fully reloads this page (plain GET form) rather
    # than trying to keep an account-scoped group checkbox list in sync
    # via JS/htmx — same "still-full-reload page" simplicity already used
    # elsewhere on this page. To stop that reload from silently wiping
    # whatever was already typed into the "Đăng lên tường cá nhân" card
    # (reported in the conversation that raised this — content + the
    # picked time both reset), preservePostFormOnAccountSwitch (this
    # module's page script) copies that card's current content/time into
    # hidden fields on THIS form before it submits, and post_form() below
    # reads them back (profile_content/profile_scheduled_at) to re-fill
    # the card after the reload. Scoped to the profile card only — the
    # "Đăng vào nhóm" card's content blocks are dynamically added by JS
    # and not worth the extra complexity to preserve the same way.
    account_picker = f"""
<form method="get" action="/admin/post" class="account-filter" id="post-account-form" data-preserve-post-form>
  <label for="post-account-select">Soạn cho tài khoản</label>
  <select name="account_id" id="post-account-select">
    {"".join(f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(account_labels[aid])}</option>' for aid in account_ids)}
  </select>
</form>"""

    groups = get_joined_groups(account_id)
    if groups:
        group_checkboxes = "".join(
            f'''<label style="display:flex; align-items:center; gap:6px; font-size:13px; background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:6px 10px;">
  <input type="checkbox" name="groups_0" value="{html.escape(g.url)}"{" checked" if prefill_target_url and g.url == prefill_target_url else ""}> {html.escape(g.name or g.url)}
</label>'''
            for g in groups
        )
        group_post_card = f"""
<div class="card">
  <h2>👥 Đăng vào nhóm — {html.escape(account_labels[account_id])}</h2>
  <p class="page-desc">Có thể tạo nhiều khối nội dung khác nhau, mỗi khối đăng vào một tập nhóm riêng — ví dụ nội dung A cho 3 nhóm đầu, nội dung B cho nhóm còn lại. Hệ thống tự rải giờ đăng giữa TẤT CẢ các bài (kể cả giữa các khối khác nhau) theo khoảng cách đang cấu hình ở <a href="/admin/config?tab=sync">Cấu hình → Đồng bộ dữ liệu</a> — không đăng dồn một lúc dù chọn nhiều nhóm.</p>
  <form method="post" action="/admin/post/schedule-groups">
    <input type="hidden" name="account_id" value="{html.escape(account_id)}">
    <input type="hidden" name="retry_of_log_id" value="{prefill_retry_of_log_id or ""}">
    <div data-repeatable-blocks>
      <div data-block-list>
        <div class="content-block" data-block style="border:1px solid #e5e7eb; border-radius:12px; padding:14px; margin-bottom:10px;">
          <textarea name="content_0" placeholder="Nội dung cho các nhóm được chọn bên dưới..." required>{html.escape(prefill_content or "")}</textarea>
          <div class="field-key" style="margin:8px 0 6px; display:flex; align-items:center; justify-content:space-between;">
            <span>Đăng vào nhóm:</span>
            <button type="button" class="btn-secondary btn-small" data-select-all-groups>Chọn tất cả</button>
          </div>
          <div style="display:flex; flex-wrap:wrap; gap:8px;">{group_checkboxes}</div>
          <button type="button" class="btn-secondary btn-small" data-remove-block style="margin-top:10px;">Xoá khối này</button>
        </div>
      </div>
      <button type="button" class="btn-secondary btn-small" data-add-block>+ Thêm nội dung khác</button>
    </div>
    <div class="field-stack" style="margin-top:14px;">
      <div class="field-label">Bắt đầu đăng lúc</div>
      <div class="field-input">{_datetime_picker_html("start_at")}</div>
    </div>
    <div class="form-actions"><button type="submit">Lên lịch tất cả</button></div>
  </form>
</div>"""
    else:
        group_post_card = f"""
<div class="card">
  <h2>👥 Đăng vào nhóm — {html.escape(account_labels[account_id])}</h2>
  <div class="empty-state">Tài khoản này chưa có nhóm nào — thêm ở <a href="/admin/groups?account_id={html.escape(account_id)}">/admin/groups</a> trước.</div>
</div>"""

    # "💬 Bình luận" tab (2026-09-12) — added specifically so /admin/reports'
    # "📅 Đặt lịch" has somewhere to land for a candidate comment
    # (comment_on_group_post/comment_on_friend_post); no group-membership
    # list to pick from like the post card above, since a comment always
    # targets one specific existing FB post/profile URL, not a joined
    # group — so target_url is a plain editable text field instead of
    # checkboxes. Action (group vs friend) is inferred from the URL at
    # submit time, same rule data_sync.py's sync_all() already uses
    # ("/groups/" in url).
    comment_post_card = f"""
<div class="card">
  <h2>💬 Đặt lịch bình luận — {html.escape(account_labels[account_id])}</h2>
  <p class="page-desc">Bình luận vào MỘT bài đăng/hồ sơ Facebook cụ thể (dán URL bài đó bên dưới) — khác với "Đăng vào nhóm" ở trên vốn đăng bài mới, không phải bình luận vào bài có sẵn.</p>
  <form method="post" action="/admin/post/schedule-comment">
    <input type="hidden" name="account_id" value="{html.escape(account_id)}">
    <input type="hidden" name="retry_of_log_id" value="{prefill_retry_of_log_id or ""}">
    <div class="field-stack">
      <div class="field-label">URL bài đăng/hồ sơ cần bình luận</div>
      <div class="field-input">
        <input type="url" name="target_url" placeholder="https://facebook.com/groups/.../posts/..." required
               style="width:100%; box-sizing:border-box;"
               value="{html.escape(prefill_target_url or "")}">
      </div>
    </div>
    <textarea name="content" placeholder="Nội dung bình luận..." required style="margin-top:14px;">{html.escape(prefill_content or "")}</textarea>
    <div class="field-stack" style="margin-top:14px;">
      <div class="field-label">Đăng lúc</div>
      <div class="field-input">{_datetime_picker_html("scheduled_at")}</div>
    </div>
    <div class="form-actions"><button type="submit">Lên lịch</button></div>
  </form>
</div>"""

    active_tab = tab if tab in ("profile", "group", "comment") else "profile"

    def tab_btn(key: str, label: str) -> str:
        cls = "tab-btn active" if key == active_tab else "tab-btn"
        return f'<button type="button" class="{cls}" data-tab-target="tab-{key}">{label}</button>'

    def panel_attrs(key: str) -> str:
        return "" if key == active_tab else " hidden"

    return _layout(f"""
<h1>Đăng bài</h1>
<p class="page-desc">Soạn nội dung và chọn thời điểm đăng — bài nào cũng qua lịch (<a href="/admin/schedule">/admin/schedule</a>) trước khi thật sự chạy, kể cả muốn đăng ngay (để trống giờ đăng, rồi bấm "🚀 Đăng ngay" bên đó).</p>
{flash}{err}
{account_picker}
{pause_warning}
{auto_fire_notice}

<div data-tabs>
  <div class="tab-bar">
    {tab_btn("profile", "👤 Tường cá nhân")}
    {tab_btn("group", "👥 Đăng vào nhóm")}
    {tab_btn("comment", "💬 Bình luận")}
  </div>

  <div class="tab-panel" id="tab-profile"{panel_attrs("profile")}>
    <div class="card">
      <h2>👤 Đăng lên tường cá nhân — {html.escape(account_labels[account_id])}</h2>
      <form method="post" action="/admin/post/schedule-profile">
        <input type="hidden" name="account_id" value="{html.escape(account_id)}">
        <input type="hidden" name="retry_of_log_id" value="{prefill_retry_of_log_id or ""}">
        <textarea name="content" placeholder="Nội dung bài đăng..." required data-preserve-profile-content>{html.escape(profile_content or "")}</textarea>
        <div class="field-stack" style="margin-top:14px;">
          <div class="field-label">Đối tượng xem</div>
          <div class="field-input">
            <select name="audience">
              <option value="public" selected>🌍 Công khai (Public)</option>
              <option value="friends">👥 Bạn bè (Friends)</option>
              <option value="only_me">🔒 Chỉ mình tôi (Only me)</option>
            </select>
          </div>
        </div>
        <div class="field-stack" style="margin-top:14px;">
          <div class="field-label">Đăng lúc</div>
          <div class="field-input" data-preserve-profile-schedule>{_datetime_picker_html("scheduled_at", current_value=profile_scheduled_at or "")}</div>
        </div>
        <div class="form-actions"><button type="submit">Lên lịch</button></div>
      </form>
    </div>
  </div>

  <div class="tab-panel" id="tab-group"{panel_attrs("group")}>
    {group_post_card}
  </div>

  <div class="tab-panel" id="tab-comment"{panel_attrs("comment")}>
    {comment_post_card}
  </div>
</div>
""", active="post")


def _parse_retry_of_log_id(form) -> int | None:
    """`retry_of_log_id` hidden field threaded through /admin/post's 3
    compose forms (2026-09-12) — set only when the admin got here via
    /admin/reports' "📅 Đặt lịch" (see _repost_choice_modal_html()'s
    prefill_qs), so the task this creates still traces back to the
    original failed report row once it fires (agent.py's TaskRequest.
    retry_of_log_id → db.log_action()). Empty/missing means a task
    composed fresh, not from a report row."""
    raw = str(form.get("retry_of_log_id", "")).strip()
    if not raw:
        return None
    try:
        return int(raw)
    except ValueError:
        return None


@router.post("/post/schedule-profile")
async def post_schedule_profile(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    content = str(form.get("content", "")).strip()
    if not content:
        return RedirectResponse(url=f"/admin/post?account_id={account_id}&tab=profile&error=Nội+dung+trống", status_code=303)
    scheduled_at = _parse_scheduled_at(str(form.get("scheduled_at", "")))
    if scheduled_at is None:
        return RedirectResponse(url=f"/admin/post?account_id={account_id}&tab=profile&error=Giờ+đăng+không+hợp+lệ", status_code=303)
    audience = str(form.get("audience", "public")).strip()
    if audience not in ("public", "friends", "only_me"):
        audience = "public"
    task = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
        action="post_to_own_profile",
        account_id=account_id,
        scheduled_at=scheduled_at.isoformat(),
        content=content,
        audience=audience,
        reasoning="manual: composed at /admin/post",
        retry_of_log_id=_parse_retry_of_log_id(form),
    )
    schedule_store.add(task)
    return RedirectResponse(url=f"/admin/post?account_id={account_id}&tab=profile&scheduled=1", status_code=303)


@router.post("/post/schedule-groups")
async def post_schedule_groups(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()

    # Content blocks were submitted as content_<i> / groups_<i> pairs — see
    # post_form()'s data-repeatable-blocks template and its cloning JS
    # (initRepeatableBlocks). Scanning for whatever indices are actually
    # present (rather than assuming 0..N contiguous) means removing a
    # block in the browser can never desync from what the server expects.
    indices = sorted(
        {key.split("_", 1)[1] for key in form.keys() if key.startswith("content_")},
        key=lambda s: int(s) if s.isdigit() else 0,
    )
    blocks: list[tuple[str, list[str]]] = []
    for idx in indices:
        content = str(form.get(f"content_{idx}", "")).strip()
        group_urls = [str(u) for u in form.getlist(f"groups_{idx}") if str(u).strip()]
        if content and group_urls:
            blocks.append((content, group_urls))

    if not blocks:
        return RedirectResponse(
            url=f"/admin/post?account_id={account_id}&tab=group&error=Cần ít nhất 1 khối nội dung có chọn nhóm",
            status_code=303,
        )

    start_at = _parse_scheduled_at(str(form.get("start_at", "")))
    if start_at is None:
        return RedirectResponse(url=f"/admin/post?account_id={account_id}&tab=group&error=Giờ+bắt+đầu+không+hợp+lệ", status_code=303)

    retry_of_log_id = _parse_retry_of_log_id(form)
    cfg = get_data_sync_config()
    next_time = start_at
    scheduled_count = 0
    for content, group_urls in blocks:
        for group_url in group_urls:
            # Clamp the CHAIN variable itself (not a throwaway copy) — see
            # human_bot/data_sync.py's apply_quiet_hours() docstring for why.
            next_time = apply_quiet_hours(next_time, cfg)
            scheduled_at = next_time
            task = schedule_store.ScheduledTask(
                task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
                action="post_to_group",
                account_id=account_id,
                scheduled_at=scheduled_at.isoformat(),
                content=content,
                target_url=group_url,
                reasoning="manual: composed at /admin/post",
                retry_of_log_id=retry_of_log_id,
            )
            schedule_store.add(task)
            scheduled_count += 1
            next_time = next_time + timedelta(
                minutes=random.uniform(cfg.post_gap_min_minutes, cfg.post_gap_max_minutes)
            )

    return RedirectResponse(url=f"/admin/post?account_id={account_id}&tab=group&scheduled={scheduled_count}", status_code=303)


@router.post("/post/schedule-comment")
async def post_schedule_comment(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    """Schedules a comment onto a specific existing FB post/profile (not a
    new post like schedule-groups above) — added 2026-09-12 so /admin/
    reports' "📅 Đặt lịch" has a landing page for a candidate comment.
    Action (group vs friend comment) is inferred from the URL, same rule
    data_sync.py's sync_all() already uses for candidate replies."""
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    target_url = str(form.get("target_url", "")).strip()
    content = str(form.get("content", "")).strip()
    if not target_url or not content:
        return RedirectResponse(
            url=f"/admin/post?account_id={account_id}&tab=comment&error=Cần+URL+và+nội+dung+bình+luận",
            status_code=303,
        )
    scheduled_at = _parse_scheduled_at(str(form.get("scheduled_at", "")))
    if scheduled_at is None:
        return RedirectResponse(url=f"/admin/post?account_id={account_id}&tab=comment&error=Giờ+đăng+không+hợp+lệ", status_code=303)
    action = "comment_on_group_post" if "/groups/" in target_url else "comment_on_friend_post"
    task = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
        action=action,
        account_id=account_id,
        scheduled_at=scheduled_at.isoformat(),
        content=content,
        target_url=target_url,
        reasoning="manual: composed at /admin/post",
        retry_of_log_id=_parse_retry_of_log_id(form),
    )
    schedule_store.add(task)
    return RedirectResponse(url=f"/admin/post?account_id={account_id}&tab=comment&scheduled=1", status_code=303)


# --- Schedule (side-B data-sync poller output) ------------------------------

def _fmt_jst(iso: str | None) -> str:
    """Same instant as `iso`, in Japan Standard Time (JST, UTC+9) —
    HH:MM DD-MM-YYYY, no UTC shown alongside. Used by /admin/schedule's
    per-task line: this project's audience/groups are Japan-focused (see
    docs/architecture.md), so JST is the timezone that actually matters
    when reading "when does this post go out" — not UTC, and (per the
    conversation that requested this, replacing an earlier UTC+Vietnam
    version) not Vietnam time either. Fixed +9h offset, not zoneinfo:
    Japan has had no DST since 1951, so this is exact, not an
    approximation."""
    if not iso:
        return "—"
    try:
        from datetime import datetime, timedelta
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        jst_dt = dt + timedelta(hours=9)
        return jst_dt.strftime("%H:%M %d-%m-%Y")
    except (ValueError, AttributeError):
        return iso


def _local_dt_html(iso: str | None) -> str:
    """Same instant as `iso`, rendered in the VIEWER's OWN browser
    timezone — via initLocalDateTime() in this module's page script,
    which overwrites the element's text using JS `Date` (its getHours()/
    getDate()/etc. read in the browser's local timezone automatically).
    Unlike _fmt_jst() (fixed JST, meant for "when does this reach the
    Japan-based audience"), this is for a value a live admin is looking
    at right now on /admin/schedule — "what time is this for ME" — which
    should track wherever THEY happen to have their browser open (added
    2026-09-10 after a request to stop hard-coding JST for this one).
    Server-renders the JST text as a fallback (same as _fmt_jst()) for
    when JS never runs — always a correct absolute instant either way,
    just labeled differently once JS replaces it."""
    if not iso:
        return "—"
    fallback = f"{_fmt_jst(iso)} (giờ Nhật Bản)"
    return f'<span data-local-dt data-utc="{html.escape(iso)}">{fallback}</span>'


_ISO_DT_RE = re.compile(r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(?:\.\d+)?(?:[+-]\d{2}:\d{2}|Z)?")


def _localize_iso_timestamps_html(text: str) -> str:
    """Renders free-form `text` with any embedded ISO 8601 UTC timestamp
    swapped for a _local_dt_html() span (browser-local time, same as
    every other time display in this admin UI) instead of showing the
    raw "2026-09-13T07:58:00+00:00" string as-is — owner-reported
    2026-09-14: schedule_store.get_missed_reason()'s text (built by
    data_sync.sweep_overdue_on_startup()) has 2 such timestamps baked
    into it as plain text. The stored .result.txt itself keeps the raw
    ISO (it's a plain-text audit file, not HTML), only the ADMIN UI
    rendering here substitutes — every other part of the string is still
    html.escape()'d individually so this can't introduce injection via
    the surrounding text."""
    parts = []
    last = 0
    for m in _ISO_DT_RE.finditer(text):
        parts.append(html.escape(text[last:m.start()]))
        parts.append(_local_dt_html(m.group(0)))
        last = m.end()
    parts.append(html.escape(text[last:]))
    return "".join(parts)


_SCHEDULE_PAGE_SIZE = 20
# Choices offered by the "items per page" <select> — added 2026-09-11,
# owner request. Bounded/allowlisted rather than a free-typed number so a
# stray huge value (or someone hand-editing the URL) can't render
# thousands of items at once; _clamp_schedule_page_size() below falls back
# to _SCHEDULE_PAGE_SIZE for anything outside this list.
_SCHEDULE_PAGE_SIZE_CHOICES = (10, 20, 50, 100)


def _clamp_schedule_page_size(raw: int) -> int:
    return raw if raw in _SCHEDULE_PAGE_SIZE_CHOICES else _SCHEDULE_PAGE_SIZE


def _schedule_page_link(
    account_id: str | None, target_page: int, label: str, enabled: bool, page_size: int = _SCHEDULE_PAGE_SIZE,
    action_filter: str | None = None, date_filter: str | None = None, tz_offset: int = 0,
) -> str:
    if not enabled:
        return f'<span class="btn-secondary btn-small" style="opacity:.45; pointer-events:none;">{label}</span>'
    from urllib.parse import urlencode
    qs = urlencode({k: v for k, v in {
        "account_id": account_id, "page": target_page,
        "page_size": page_size if page_size != _SCHEDULE_PAGE_SIZE else None,
        "action": action_filter, "date": date_filter,
        "tz_offset": tz_offset if tz_offset else None,
    }.items() if v})
    return (
        f'<a class="btn-secondary btn-small" href="/admin/schedule?{qs}" '
        f'hx-get="/admin/schedule?{qs}" hx-target="#schedule-content" hx-swap="outerHTML" hx-push-url="true">{label}</a>'
    )


def _missed_page_link(account_id: str | None, target_page: int, label: str, enabled: bool, page_size: int) -> str:
    if not enabled:
        return f'<span class="btn-secondary btn-small" style="opacity:.45; pointer-events:none;">{label}</span>'
    from urllib.parse import urlencode
    qs = urlencode({k: v for k, v in {
        "account_id": account_id, "tab": "missed", "missed_page": target_page,
        "page_size": page_size if page_size != _SCHEDULE_PAGE_SIZE else None,
    }.items() if v})
    return (
        f'<a class="btn-secondary btn-small" href="/admin/schedule?{qs}" '
        f'hx-get="/admin/schedule?{qs}" hx-target="#schedule-content" hx-swap="outerHTML" hx-push-url="true">{label}</a>'
    )


def _missed_tasks_section_html(account_id: str | None, page: int, page_size: int, accounts: dict, missed_page: int = 1) -> str:
    """"⚠️ Task quá hạn" tab content (2026-09-14, split into its own tab
    per owner request — was a conditionally-shown callout card before;
    pagination added same day, same owner request). schedule_store.
    MISSED_DIR holds tasks the one-time startup sweep pulled out of
    pending/ because their scheduled_at was already in the past the
    moment the service came back up (see data_sync.
    sweep_overdue_on_startup()'s docstring). Every action here re-renders
    the WHOLE #schedule-content (same as pending-task actions already
    do), so both tabs always stay in sync with each other.

    `missed_page` is a SEPARATE page counter from the pending tab's own
    `page` — the two tabs have unrelated item counts, so sharing one
    "page" query param would desync whichever tab isn't currently active
    (same "job_page"/"candidate_page" reasoning as /admin/reports' own
    multi-tab pagination)."""
    all_missed = schedule_store.list_missed()
    if not all_missed:
        return '<div class="empty-state">Không có task nào quá hạn — mọi thứ đúng lịch.</div>'

    total = len(all_missed)
    total_pages = max(1, -(-total // page_size))
    missed_page = min(max(missed_page, 1), total_pages)
    start = (missed_page - 1) * page_size
    missed = all_missed[start:start + page_size]

    filter_fields = (
        f'<input type="hidden" name="account_id" value="{html.escape(account_id or "")}">'
        f'<input type="hidden" name="page" value="{page}">'
        f'<input type="hidden" name="page_size" value="{page_size}">'
        f'<input type="hidden" name="tab" value="missed">'
        f'<input type="hidden" name="missed_page" value="{missed_page}">'
    )
    items_html = []
    for t in missed:
        content_full = html.escape(t.content or "")
        reason = schedule_store.get_missed_reason(t.task_id)
        reason_html = f'<div class="warning-inline">{_localize_iso_timestamps_html(reason)}</div>' if reason else ""
        url_row_html = ""
        if t.target_url:
            url_label = "Url nhóm" if t.action == "post_to_group" else "Url bài viết"
            url_display = html.escape(t.target_url)
            url_row_html = f'<div class="field-key">{url_label}: <a class="row-url" href="{url_display}" target="_blank" rel="noopener">{url_display}</a></div>'
        reschedule_qs = (
            f"task_id={html.escape(t.task_id, quote=True)}&account_id={html.escape(account_id or '', quote=True)}"
            f"&page={page}&page_size={page_size}&missed_page={missed_page}"
        )
        items_html.append(f"""
<div class="queue-item" style="border-left:3px solid #f59e0b;">
  <label style="display:flex; align-items:center; gap:8px; cursor:pointer;">
    <input type="checkbox" name="task_ids" value="{html.escape(t.task_id)}" form="missed-bulk-form">
    <span class="queue-filename">{_action_badge_html(t.action)} · {html.escape(_account_label(t.account_id, accounts))}</span>
  </label>
  <div class="field-key">id: {html.escape(t.task_id)}</div>
  <div class="field-key">Giờ dự kiến ban đầu: {_local_dt_html(t.scheduled_at)}</div>
  {url_row_html}
  {reason_html}
  <form method="post" action="/admin/schedule/missed/reschedule"
        hx-post="/admin/schedule/missed/reschedule" hx-target="#schedule-content" hx-swap="outerHTML"
        style="margin-top:8px; display:flex; gap:8px; align-items:flex-start; flex-wrap:wrap;">
    <input type="hidden" name="task_id" value="{html.escape(t.task_id)}">
    {filter_fields}
    <textarea name="content" style="flex:1; min-width:240px; min-height:60px;">{content_full}</textarea>
    {_datetime_picker_html("scheduled_at", current_value=t.scheduled_at, required=True, blank_hint=False)}
    <button type="submit" class="btn-small">📅 Đặt lịch</button>
  </form>
  <div style="margin-top:8px; display:flex; gap:8px;">
    <button type="button" class="btn-small"
            hx-get="/admin/schedule/missed/suggest?{reschedule_qs}" hx-target="#modal-root" hx-swap="innerHTML">🔄 Lên lịch lại</button>
    <form method="post" action="/admin/schedule/missed/cancel"
          hx-post="/admin/schedule/missed/cancel" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-confirm="Xoá mục quá hạn này?">
      <input type="hidden" name="task_id" value="{html.escape(t.task_id)}">
      {filter_fields}
      <button type="submit" class="btn-secondary btn-small">🗑️ Xoá</button>
    </form>
  </div>
</div>""")

    return f"""
<form id="missed-bulk-form" method="post" action="/admin/schedule/missed/bulk-cancel"
      hx-post="/admin/schedule/missed/bulk-cancel" hx-target="#schedule-content" hx-swap="outerHTML"
      hx-confirm="Xoá tất cả mục đã chọn?">
  {filter_fields}
</form>
<div class="card">
  <div style="display:flex; justify-content:space-between; align-items:center; flex-wrap:wrap; gap:8px;">
    <p class="page-desc" style="margin:0;">Những bài lẽ ra đã đến giờ đăng nhưng service đang tắt lúc đó — giữ lại đây thay vì tự động đăng khi khởi động lại, chờ bạn duyệt: "📅 Đặt lịch" (tự chọn giờ mới), "🔄 Lên lịch lại" (hệ thống gợi ý giờ trống gần nhất), hoặc xoá nếu không cần nữa.</p>
    <div style="display:flex; align-items:center; gap:12px; flex-shrink:0;">
      <label style="font-size:13px; display:flex; align-items:center; gap:4px; cursor:pointer; white-space:nowrap;">
        <input type="checkbox" onclick="document.querySelectorAll('input[name=task_ids]').forEach(function(cb){{cb.checked=this.checked}}.bind(this))">
        Chọn tất cả
      </label>
      <button type="submit" form="missed-bulk-form" class="btn-secondary btn-small">🗑️ Xoá đã chọn</button>
    </div>
  </div>
  {"".join(items_html)}
  {_missed_pagination_html(account_id, missed_page, total_pages, total, page_size)}
</div>"""


def _missed_pagination_html(account_id: str | None, missed_page: int, total_pages: int, total: int, page_size: int) -> str:
    if total_pages <= 1:
        return ""
    jump_hidden_fields = (
        (f'<input type="hidden" name="account_id" value="{html.escape(account_id)}">' if account_id else "")
        + '<input type="hidden" name="tab" value="missed">'
        + f'<input type="hidden" name="page_size" value="{page_size}">'
    )
    return f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-top:14px; flex-wrap:wrap; gap:8px;">
  <div style="display:flex; gap:8px; align-items:center;">
    {_missed_page_link(account_id, 1, "«« Đầu", missed_page > 1, page_size)}
    {_missed_page_link(account_id, missed_page - 1, "← Trang trước", missed_page > 1, page_size)}
  </div>
  <form hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML" hx-push-url="true"
        style="display:flex; gap:6px; align-items:center; background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:5px 10px;">
    {jump_hidden_fields}
    <span class="muted">Trang</span>
    <input type="number" name="missed_page" min="1" max="{total_pages}" value="{missed_page}"
           style="width:64px; text-align:center;" aria-label="Đi đến trang">
    <span class="muted">/ {total_pages} — {total} mục</span>
    <button type="submit" class="btn-secondary btn-small">Đi</button>
  </form>
  <div style="display:flex; gap:8px; align-items:center;">
    {_missed_page_link(account_id, missed_page + 1, "Trang sau →", missed_page < total_pages, page_size)}
    {_missed_page_link(account_id, total_pages, "Cuối »»", missed_page < total_pages, page_size)}
  </div>
</div>"""


_SCHEDULE_TABS = ("pending", "missed")

# The two action filter choices offered on /admin/schedule's pending tab
# (owner request 2026-09-15) — deliberately just these two, not every
# _ACTION_LABELS key: post_to_own_profile/comment_on_friend_post/like_post/
# read_recent_comments are either manual-only or paused (see
# project_deprioritized_fb_actions memory) and would just clutter a filter
# meant to split "Đăng vào nhóm" vs "Comment bài trong nhóm" — the two
# actions data_sync.py's sync_all() actually produces onto this schedule.
_SCHEDULE_FILTERABLE_ACTIONS = ("post_to_group", "comment_on_group_post")


def _clamp_schedule_tab(raw: str | None) -> str:
    return raw if raw in _SCHEDULE_TABS else "pending"


def _clamp_schedule_action(raw: str | None) -> str | None:
    return raw if raw in _SCHEDULE_FILTERABLE_ACTIONS else None


def _task_local_date(iso: str | None, tz_offset_minutes: int) -> str | None:
    """`iso` (a ScheduledTask.scheduled_at, always UTC) as a YYYY-MM-DD
    date in the VIEWER's OWN browser timezone — `tz_offset_minutes` is
    minutes to ADD to UTC to get local (e.g. +540 for JST, UTC+9; the
    NEGATIVE of what JS's `Date.getTimezoneOffset()` itself returns),
    sent up from the page itself (see initTzOffsetField() in this
    module's page script) so the date filter below buckets by the exact
    same "what date is this for ME" instant /admin/schedule already
    displays via _local_dt_html() — never the server's own timezone,
    which may not match the viewer's at all."""
    if not iso:
        return None
    try:
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return None
    local = dt + timedelta(minutes=tz_offset_minutes)
    return local.strftime("%Y-%m-%d")


def _schedule_content_html(
    account_id: str | None = None, page: int = 1, page_size: int = _SCHEDULE_PAGE_SIZE,
    saved: bool = False, error: str | None = None, tab: str | None = None, missed_page: int = 1,
    action_filter: str | None = None, date_filter: str | None = None, tz_offset: int = 0,
) -> str:
    page_size = _clamp_schedule_page_size(page_size)
    tab = _clamp_schedule_tab(tab)
    action_filter = _clamp_schedule_action(action_filter)
    date_filter = date_filter.strip() if date_filter else None
    accounts = get_all_accounts()
    if account_id and account_id not in accounts:
        account_id = None  # unknown/stale filter falls back to "all", never a hard error
    all_tasks = schedule_store.list_pending()
    missed_count = len(schedule_store.list_missed())
    tasks = [t for t in all_tasks if not account_id or t.account_id == account_id]
    if action_filter:
        tasks = [t for t in tasks if t.action == action_filter]
    if date_filter:
        tasks = [t for t in tasks if _task_local_date(t.scheduled_at, tz_offset) == date_filter]

    total = len(tasks)
    total_pages = max(1, -(-total // page_size))  # ceil division
    page = min(max(page, 1), total_pages)
    start = (page - 1) * page_size
    page_tasks = tasks[start:start + page_size]

    flash = '<p class="flash">✅ Đã cập nhật.</p>' if saved else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""

    # Filtering by account is what keeps this page workable once the
    # schedule gets busy (many accounts/groups) — switching accounts
    # always jumps back to page 1 (neither <select> below ever sends a
    # `page` param), so a filter change never lands on a now-out-of-range
    # page. The two selects include each other's current value via
    # hx-include (by id) so switching one doesn't silently reset the
    # other back to its default — added 2026-09-11 alongside the
    # page-size select itself (owner request: no way to see/change how
    # many items render per page).
    account_options = '<option value="">— Tất cả tài khoản —</option>' + "".join(
        f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(a.display_name)} ({html.escape(aid)})</option>'
        for aid, a in accounts.items()
    )
    page_size_options = "".join(
        f'<option value="{size}"{" selected" if size == page_size else ""}>{size}/trang</option>'
        for size in _SCHEDULE_PAGE_SIZE_CHOICES
    )
    action_options = '<option value="">— Tất cả hành động —</option>' + "".join(
        f'<option value="{action}"{" selected" if action == action_filter else ""}>{html.escape(_ACTION_LABELS.get(action, action))}</option>'
        for action in _SCHEDULE_FILTERABLE_ACTIONS
    )
    # tab != "pending" (missed) never renders this form at all — its own
    # filter is _missed_tasks_section_html()'s, unrelated to
    # action_filter/date_filter/tz_offset below — so these two new
    # filters only ever apply here, on the pending list.
    #
    # All 5 fields include EACH OTHER via hx-include (by id) — same
    # pattern as the account/page-size pair above — so changing any one
    # never silently drops what the other four currently hold. tz_offset
    # is never edited by the viewer directly; initTzOffsetField() (this
    # module's page script) fills it from the browser's own
    # Date.getTimezoneOffset() on load/swap, so the date filter below
    # buckets by "what date is this for ME", the same instant
    # _local_dt_html() already shows per row — not the server's own
    # timezone, which may not match the viewer's at all.
    _sched_filter_ids = "#schedule-account-select,#schedule-pagesize-select,#schedule-action-select,#schedule-date-input,#schedule-tz-offset"
    # "Xoá bộ lọc" (owner request 2026-09-15) — only clears action/date
    # (account_id/page_size are the ORIGINAL filter row, left alone);
    # only shown when one of the two is actually set, same "don't offer
    # a button that does nothing" pattern as elsewhere in this file.
    # tz_offset deliberately dropped too (harmless either way — nothing
    # is left for it to scope once date is gone — but cleaner not to
    # carry a now-pointless param into the URL).
    from urllib.parse import urlencode as _urlencode_clear
    _clear_qs = _urlencode_clear({k: v for k, v in {
        "account_id": account_id, "page_size": page_size if page_size != _SCHEDULE_PAGE_SIZE else None,
    }.items() if v})
    clear_filter_html = ""
    if action_filter or date_filter:
        clear_filter_html = (
            f'<a class="btn-secondary btn-small" href="/admin/schedule?{_clear_qs}" '
            f'hx-get="/admin/schedule?{_clear_qs}" hx-target="#schedule-content" hx-swap="outerHTML" '
            f'hx-push-url="true">✕ Xoá bộ lọc</a>'
        )
    filter_html = f"""
<div class="account-filter">
  <label for="schedule-account-select">Tài khoản</label>
  <select name="account_id" id="schedule-account-select" hx-include="{_sched_filter_ids}"
          hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-trigger="change" hx-push-url="true">{account_options}</select>
  <label for="schedule-pagesize-select">Hiển thị</label>
  <select name="page_size" id="schedule-pagesize-select" hx-include="{_sched_filter_ids}"
          hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-trigger="change" hx-push-url="true">{page_size_options}</select>
  <span class="badge">{total} bài đang chờ</span>
</div>
<div class="account-filter">
  <label for="schedule-action-select">Hành động</label>
  <select name="action" id="schedule-action-select" hx-include="{_sched_filter_ids}"
          hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-trigger="change" hx-push-url="true">{action_options}</select>
  <label for="schedule-date-input">Ngày đăng</label>
  <input type="date" name="date" id="schedule-date-input" value="{html.escape(date_filter or "")}"
         hx-include="{_sched_filter_ids}"
         hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML"
         hx-trigger="change" hx-push-url="true">
  <input type="hidden" name="tz_offset" id="schedule-tz-offset" data-tz-offset-field value="{tz_offset}">
  {clear_filter_html}
</div>"""

    if page_tasks:
        items_html = []
        for t in page_tasks:
            # NOT truncated — this exact string is also the editable
            # <textarea>'s value below. Truncating it here used to mean
            # opening "Sửa" and clicking "Lưu" on any post longer than a
            # cutoff silently chopped off everything past it, even
            # without touching the text (found in the admin UI review
            # that raised this).
            content_full = html.escape(t.content or "")
            # Every mutating form below carries the current filter/page
            # back so update/fire-now/cancel re-render the SAME view
            # instead of silently resetting to "all accounts, page 1".
            filter_fields = (
                f'<input type="hidden" name="account_id" value="{html.escape(account_id or "")}">'
                f'<input type="hidden" name="page" value="{page}">'
                f'<input type="hidden" name="page_size" value="{page_size}">'
                f'<input type="hidden" name="action" value="{html.escape(action_filter or "")}">'
                f'<input type="hidden" name="date" value="{html.escape(date_filter or "")}">'
                f'<input type="hidden" name="tz_offset" value="{tz_offset}">'
            )
            url_row_html = ""
            if t.target_url:
                url_label = "Url nhóm" if t.action == "post_to_group" else "Url bài viết"
                url_display = html.escape(t.target_url)
                url_js = html.escape(json.dumps(t.target_url), quote=True)
                url_row_html = f"""
  <div class="field-key">{url_label}: <a class="row-url" href="{url_display}" target="_blank" rel="noopener">{url_display}</a>
    <button type="button" class="btn-copy" style="margin-left:6px;"
            onclick="navigator.clipboard.writeText({url_js}); var b=this; var t0=b.textContent; b.textContent='✅ Đã copy'; setTimeout(function(){{b.textContent=t0;}}, 1500);">📋 Copy</button>
  </div>"""
            warning_html = ""
            if t.last_warning:
                warning_html = f'<div class="warning-inline">{html.escape(t.last_warning)}</div>'
            items_html.append(f"""
<div class="queue-item">
  <div class="queue-filename">{_action_badge_html(t.action)} · {html.escape(_account_label(t.account_id, accounts))}</div>
  <div class="field-key">id: {html.escape(t.task_id)}</div>
  <div class="field-key">Ngày giờ thực hiện: {_local_dt_html(t.scheduled_at)}</div>
  {url_row_html}
  {warning_html}
  <form method="post" action="/admin/schedule/update"
        hx-post="/admin/schedule/update" hx-target="#schedule-content" hx-swap="outerHTML"
        style="margin-top:8px; display:flex; gap:8px; align-items:flex-start; flex-wrap:wrap;">
    <input type="hidden" name="task_id" value="{html.escape(t.task_id)}">
    {filter_fields}
    <textarea name="content" style="flex:1; min-width:240px; min-height:60px;">{content_full}</textarea>
    {_datetime_picker_html("scheduled_at", current_value=t.scheduled_at, required=True, blank_hint=False)}
    <button type="submit" class="btn-small">Lưu</button>
  </form>
  <div style="margin-top:8px; display:flex; gap:8px;">
    <form method="post" action="/admin/schedule/fire-now"
          hx-post="/admin/schedule/fire-now" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-confirm="Đăng bài này lên Facebook ngay bây giờ?">
      <input type="hidden" name="task_id" value="{html.escape(t.task_id)}">
      {filter_fields}
      <button type="submit" class="btn-small">🚀 Đăng ngay</button>
    </form>
    <form method="post" action="/admin/schedule/cancel"
          hx-post="/admin/schedule/cancel" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-confirm="Huỷ lịch đăng này?">
      <input type="hidden" name="task_id" value="{html.escape(t.task_id)}">
      {filter_fields}
      <button type="submit" class="btn-secondary btn-small">Huỷ</button>
    </form>
  </div>
</div>""")
        list_html = "".join(items_html)
    elif total == 0:
        list_html = '<div class="empty-state">Chưa có bài nào đang chờ lịch. Bộ đồng bộ bên B sẽ tự điền vào đây khi có dữ liệu mới, hoặc soạn thủ công ở /admin/post.</div>'
    else:
        list_html = '<div class="empty-state">Không có bài nào ở trang này.</div>'

    pagination_html = ""
    if total_pages > 1:
        # First/last jump buttons (added 2026-09-11, owner request: from
        # page 1 there was no fast way to reach page 10 or the last page,
        # only one-page-at-a-time prev/next) + a "go to page N" input for
        # anything in between, styled as one pill ("Trang [_]/12 [Đi]")
        # instead of a bare number box — first version looked out of
        # place next to the button-styled prev/next links, same visual
        # language as the switch/config boxes elsewhere in this file
        # (background + border + rounded corners). All reuse the same GET
        # /admin/schedule?... route _schedule_page_link already uses, so
        # htmx swap/push-url behavior stays identical; page_size threads
        # through everywhere page already does so changing page never
        # silently resets it back to the default.
        jump_hidden_fields = (
            (f'<input type="hidden" name="account_id" value="{html.escape(account_id)}">' if account_id else "")
            + f'<input type="hidden" name="page_size" value="{page_size}">'
            + (f'<input type="hidden" name="action" value="{html.escape(action_filter)}">' if action_filter else "")
            + (f'<input type="hidden" name="date" value="{html.escape(date_filter)}">' if date_filter else "")
            + (f'<input type="hidden" name="tz_offset" value="{tz_offset}">' if tz_offset else "")
        )
        pagination_html = f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-top:14px; flex-wrap:wrap; gap:8px;">
  <div style="display:flex; gap:8px; align-items:center;">
    {_schedule_page_link(account_id, 1, "«« Đầu", page > 1, page_size, action_filter, date_filter, tz_offset)}
    {_schedule_page_link(account_id, page - 1, "← Trang trước", page > 1, page_size, action_filter, date_filter, tz_offset)}
  </div>
  <form hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML" hx-push-url="true"
        style="display:flex; gap:6px; align-items:center; background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:5px 10px;">
    {jump_hidden_fields}
    <span class="muted">Trang</span>
    <input type="number" name="page" min="1" max="{total_pages}" value="{page}"
           style="width:64px; text-align:center;" aria-label="Đi đến trang">
    <span class="muted">/ {total_pages}</span>
    <button type="submit" class="btn-secondary btn-small">Đi</button>
  </form>
  <div style="display:flex; gap:8px; align-items:center;">
    {_schedule_page_link(account_id, page + 1, "Trang sau →", page < total_pages, page_size, action_filter, date_filter, tz_offset)}
    {_schedule_page_link(account_id, total_pages, "Cuối »»", page < total_pages, page_size, action_filter, date_filter, tz_offset)}
  </div>
</div>"""

    def _schedule_tab_link(tab_key: str, label: str) -> str:
        from urllib.parse import urlencode as _urlencode_tab
        active = tab_key == tab
        qs = _urlencode_tab({k: v for k, v in {
            "account_id": account_id, "tab": tab_key,
            "page_size": page_size if page_size != _SCHEDULE_PAGE_SIZE else None,
        }.items() if v})
        style = (
            "border-bottom:2px solid #111827; font-weight:600; color:#111827;" if active
            else "border-bottom:2px solid transparent; color:#6b7280;"
        )
        return (
            f'<a href="/admin/schedule?{qs}" hx-get="/admin/schedule?{qs}" '
            f'hx-target="#schedule-content" hx-swap="outerHTML" hx-push-url="true" '
            f'style="padding:8px 4px; text-decoration:none; {style}">{label}</a>'
        )

    tab_nav_html = f"""
<div style="display:flex; gap:20px; margin-bottom:18px; border-bottom:1px solid #e5e7eb;">
  {_schedule_tab_link("pending", f"📋 Task đã lên lịch ({total})")}
  {_schedule_tab_link("missed", f"⚠️ Task quá hạn ({missed_count})")}
</div>"""

    if tab == "missed":
        tab_body_html = _missed_tasks_section_html(account_id, page, page_size, accounts, missed_page)
    else:
        tab_body_html = f"""
{filter_html}
{list_html}
{pagination_html}"""

    return f"""<div id="schedule-content">
{tab_nav_html}
{flash}{err}
{tab_body_html}
</div>"""


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_list(
    request: Request,
    account_id: str | None = None,
    page: int = 1,
    page_size: int = _SCHEDULE_PAGE_SIZE,
    saved: bool = False,
    error: str | None = None,
    tab: str | None = None,
    missed_page: int = 1,
    action: str | None = None,
    date: str | None = None,
    tz_offset: int = 0,
    _: None = Depends(_require_auth),
) -> str:
    content = _schedule_content_html(account_id=account_id, page=page, page_size=page_size, saved=saved, error=error, tab=tab, missed_page=missed_page, action_filter=action, date_filter=date, tz_offset=tz_offset)
    if _is_htmx(request):
        return content
    return _layout(f"""
<h1>Lịch đăng</h1>
<p class="page-desc">Mọi bài chờ đăng — tự động từ bộ đồng bộ bên B (human_bot/data_sync.py) hoặc soạn thủ công ở /admin/post — đều nằm ở đây trước khi thật sự chạy.</p>
{_auto_fire_status_html()}
{content}
""", active="schedule")


def _schedule_redirect(account_id: str | None, page: int, **params) -> RedirectResponse:
    from urllib.parse import urlencode
    query = {"account_id": account_id, "page": page, **params}
    query = {k: v for k, v in query.items() if v not in (None, "", 0)}
    return RedirectResponse(url=f"/admin/schedule?{urlencode(query)}", status_code=303)


def _schedule_form_filter(form) -> tuple[str | None, int, int, int, str | None, str | None, int]:
    account_id = str(form.get("account_id", "")).strip() or None
    try:
        page = int(str(form.get("page", "1")))
    except ValueError:
        page = 1
    try:
        page_size = _clamp_schedule_page_size(int(str(form.get("page_size", _SCHEDULE_PAGE_SIZE))))
    except ValueError:
        page_size = _SCHEDULE_PAGE_SIZE
    try:
        missed_page = int(str(form.get("missed_page", "1")))
    except ValueError:
        missed_page = 1
    # action/date/tz_offset (2026-09-15, owner request): only meaningful
    # for the pending tab's own filter (see _schedule_content_html) —
    # the missed-tab handlers below still unpack them (tuple shape is
    # shared) but never pass them on, since /admin/schedule's "missed"
    # tab has no such filter of its own.
    action_filter = _clamp_schedule_action(str(form.get("action", "")).strip() or None)
    date_filter = str(form.get("date", "")).strip() or None
    try:
        tz_offset = int(str(form.get("tz_offset", "0")))
    except ValueError:
        tz_offset = 0
    return account_id, page, page_size, missed_page, action_filter, date_filter, tz_offset


@router.post("/schedule/update")
async def schedule_update(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id, page, page_size, missed_page, action_filter, date_filter, tz_offset = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    content = str(form.get("content", ""))
    scheduled_at = str(form.get("scheduled_at", ""))
    # Clearing last_warning here: editing the schedule (most likely the
    # time, per the rate-limit banner's own suggestion) is the admin
    # acting on the warning — an unresolved warning should not linger
    # after they've already adjusted it.
    updated = schedule_store.update(task_id, content=content, scheduled_at=scheduled_at, last_warning=None)
    if updated is None:
        err = "Không tìm thấy mục này (có thể đã được đăng hoặc huỷ)"
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset, error=err))
        return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, error=err)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset, saved=True))
    return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, saved=1)


@router.post("/schedule/cancel")
async def schedule_cancel(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id, page, page_size, missed_page, action_filter, date_filter, tz_offset = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    schedule_store.cancel(task_id)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset, saved=True))
    return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, saved=1)


# --- "⚠️ Task quá hạn" review (2026-09-14) — see schedule_store.MISSED_DIR
# and data_sync.sweep_overdue_on_startup()'s docstrings for the full
# picture: these 5 routes are the admin-review resolution for whatever
# the one-time startup sweep pulled out of pending/.

@router.post("/schedule/missed/reschedule")
async def schedule_missed_reschedule(request: Request, _: None = Depends(_require_auth)):
    """"📅 Đặt lịch" on a missed task — admin picks the content/time by
    hand, same edit form shape as schedule_update() above, but the SOURCE
    is missed/ instead of pending/ (schedule_store.restore_to_pending())."""
    form = await request.form()
    account_id, page, page_size, missed_page, _action_filter, _date_filter, _tz_offset = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    content = str(form.get("content", ""))
    scheduled_at = str(form.get("scheduled_at", ""))
    restored = schedule_store.restore_to_pending(task_id, content=content, scheduled_at=scheduled_at)
    if restored is None:
        err = "Không tìm thấy mục này (có thể đã được xử lý ở tab khác)"
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, error=err))
        return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, error=err)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, saved=True))
    return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, saved=1)


@router.get("/schedule/missed/suggest", response_class=HTMLResponse)
async def schedule_missed_suggest(
    task_id: str, account_id: str | None = None, page: int = 1, page_size: int = _SCHEDULE_PAGE_SIZE,
    missed_page: int = 1,
    _: None = Depends(_require_auth),
) -> str:
    """"🔄 Lên lịch lại" step 1 on a missed task — same suggestion engine
    as /admin/reports' retry flow (_suggest_reschedule_at()), just fed a
    ScheduledTask's account/action instead of an action_log row's."""
    task = schedule_store.get_missed(task_id)
    if task is None:
        return ""
    account = get_all_accounts().get(task.account_id)
    if account is None:
        return (
            '<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">'
            '<div class="modal-box"><p class="error">⚠️ Không tìm thấy tài khoản này.</p></div></div>'
        )
    suggested = _suggest_reschedule_at(account, task.action)
    page_size = _clamp_schedule_page_size(page_size)
    filter_fields = (
        f'<input type="hidden" name="account_id" value="{html.escape(account_id or "")}">'
        f'<input type="hidden" name="page" value="{page}">'
        f'<input type="hidden" name="page_size" value="{page_size}">'
        f'<input type="hidden" name="missed_page" value="{missed_page}">'
        f'<input type="hidden" name="task_id" value="{html.escape(task_id)}">'
        f'<input type="hidden" name="scheduled_at" value="{suggested.isoformat()}">'
    )
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>🔄 Lên lịch lại</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    <p>Giờ đăng gợi ý: <b>{_local_dt_html(suggested.isoformat())}</b></p>
    <p class="muted">Đã tính theo giới hạn số lượng/ngày, khoảng cách tối thiểu với lần đăng gần nhất, và giờ yên tĩnh đang cấu hình. Bấm Xác nhận để đưa lại vào lịch chờ (xem/sửa lại ở /admin/schedule), hoặc Huỷ để tự chọn giờ khác qua "📅 Đặt lịch".</p>
    <div class="form-actions">
      <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
      <form method="post" action="/admin/schedule/missed/reschedule-confirm"
            hx-post="/admin/schedule/missed/reschedule-confirm" hx-target="#schedule-content" hx-swap="outerHTML" style="display:inline;">
        {filter_fields}
        <button type="submit">✅ Xác nhận</button>
      </form>
    </div>
  </div>
</div>"""


@router.post("/schedule/missed/reschedule-confirm")
async def schedule_missed_reschedule_confirm(request: Request, _: None = Depends(_require_auth)):
    """"🔄 Lên lịch lại" step 2 — admin confirmed the suggested slot."""
    form = await request.form()
    account_id, page, page_size, missed_page, _action_filter, _date_filter, _tz_offset = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    scheduled_at_raw = str(form.get("scheduled_at", "")).strip()
    try:
        scheduled_at = datetime.fromisoformat(scheduled_at_raw.replace("Z", "+00:00"))
    except ValueError:
        scheduled_at = datetime.now(timezone.utc)
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)
    restored = schedule_store.restore_to_pending(task_id, scheduled_at=scheduled_at.isoformat())
    if restored is None:
        err = "Không tìm thấy mục này (có thể đã được xử lý ở tab khác)"
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, error=err) + _MODAL_CLOSE_OOB)
    return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, saved=True) + _MODAL_CLOSE_OOB)


@router.post("/schedule/missed/cancel")
async def schedule_missed_cancel(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id, page, page_size, missed_page, _action_filter, _date_filter, _tz_offset = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    schedule_store.cancel_missed(task_id)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, saved=True))
    return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, saved=1)


@router.post("/schedule/missed/bulk-cancel")
async def schedule_missed_bulk_cancel(request: Request, _: None = Depends(_require_auth)):
    """"🗑️ Xoá đã chọn" — the "chọn nhiều/chọn tất cả rồi xoá một lúc"
    owner asked for. `task_ids` arrives as a repeated form field (each
    checked checkbox); every id gets cancel_missed()'d independently —
    an id that's already gone (someone else resolved it, or a double
    submit) is simply a no-op, never an error for the whole batch."""
    form = await request.form()
    account_id, page, page_size, missed_page, _action_filter, _date_filter, _tz_offset = _schedule_form_filter(form)
    task_ids = [str(v) for v in form.getlist("task_ids") if str(v).strip()]
    for task_id in task_ids:
        schedule_store.cancel_missed(task_id)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, saved=True))
    return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, saved=1)


# Closes the "Vẫn đăng ngay?" rate-limit modal (see
# _fire_now_confirm_modal_html()) via an out-of-band swap tacked onto
# every htmx response from schedule_fire_now() — harmless when no modal
# is open (an empty #modal-root swapped for an empty #modal-root).
_MODAL_CLOSE_OOB = '<div id="modal-root" hx-swap-oob="true"></div>'


def _fire_now_confirm_modal_html(
    task_id: str, account_id: str | None, page: int, page_size: int, warning: str,
    action_filter: str | None = None, date_filter: str | None = None, tz_offset: int = 0,
) -> str:
    """Renders the #modal-root swap for schedule_fire_now()'s rate-limit
    confirmation prompt — shown ONLY when the sole thing blocking the
    post is the soft min-gap pacing check (human_bot/safety.py's
    is_gap_reason()), never for a hard per-day/per-hour count cap (those
    stay a flat refusal — see can_proceed(ignore_gap=...)'s docstring for
    why). "Vẫn đăng ngay" resubmits the same fire-now form with
    force=1, which schedule_fire_now() passes through as
    TaskRequest.force_ignore_gap."""
    filter_fields = (
        f'<input type="hidden" name="account_id" value="{html.escape(account_id or "")}">'
        f'<input type="hidden" name="page" value="{page}">'
        f'<input type="hidden" name="page_size" value="{page_size}">'
        f'<input type="hidden" name="action" value="{html.escape(action_filter or "")}">'
        f'<input type="hidden" name="date" value="{html.escape(date_filter or "")}">'
        f'<input type="hidden" name="tz_offset" value="{tz_offset}">'
    )
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>⚠️ Đang bị rate-limit</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    <p>{html.escape(warning)}</p>
    <p class="muted">Bạn có thể đợi đến thời gian gợi ý ở trên, hoặc đăng ngay bây giờ — chỉ bỏ qua khoảng nghỉ tối thiểu giữa 2 hành động, các giới hạn số lượng/ngày và /giờ vẫn được giữ nguyên.</p>
    <div class="form-actions">
      <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Đợi đến giờ gợi ý</button>
      <form method="post" action="/admin/schedule/fire-now"
            hx-post="/admin/schedule/fire-now" hx-target="#schedule-content" hx-swap="outerHTML"
            style="display:inline;">
        <input type="hidden" name="task_id" value="{html.escape(task_id)}">
        {filter_fields}
        <input type="hidden" name="force" value="1">
        <button type="submit">🚀 Vẫn đăng ngay</button>
      </form>
    </div>
  </div>
</div>"""


@router.post("/schedule/fire-now")
async def schedule_fire_now(request: Request, _: None = Depends(_require_auth)):
    """Post a scheduled task immediately, bypassing auto_fire_enabled — this
    button is the manual override for when that safety gate is (correctly)
    left off. See docs/architecture.md section 3c.

    Still goes through RateLimiter — "Đăng ngay" only skips
    auto_fire_enabled, not rate-limiting. If the sole reason it's blocked
    is the soft min-gap pacing check, the admin gets a confirmation modal
    (_fire_now_confirm_modal_html()) offering to override just that gap;
    a hard per-day/per-hour count cap is never offered an override — see
    human_bot/safety.py's can_proceed(ignore_gap=...) docstring for why
    the two are treated differently. Requested 2026-09-09."""
    form = await request.form()
    account_id, page, page_size, missed_page, action_filter, date_filter, tz_offset = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    force = str(form.get("force", "")) == "1"
    task = schedule_store.get(task_id)
    if task is None:
        err = "Không tìm thấy mục này"
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset, error=err) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, error=err)

    from human_bot import daily_limits
    from human_bot.agent import rate_limit_bucket_for
    from human_bot.safety import is_gap_reason, rate_limit_wait_message
    account = get_all_accounts().get(task.account_id)
    bucket = rate_limit_bucket_for(task.action)
    if account and bucket and not force:
        # daily_limits.can_proceed() (2026-09-11), not RateLimiter.can_proceed()
        # directly — see human_bot/daily_limits.py's module docstring.
        allowed, reason = daily_limits.can_proceed(account, bucket)
        if not allowed and is_gap_reason(reason):
            # Soft pacing gap only — offer the override modal instead of
            # failing outright. Doesn't record an attempt (can_proceed()
            # is read-only).
            warning = rate_limit_wait_message(account, bucket) or reason
            if _is_htmx(request):
                # The triggering "🚀 Đăng ngay" form's hx-target is
                # #schedule-content (outerHTML) — returning ONLY the modal
                # here would swap the modal itself into #schedule-content,
                # deleting that id from the DOM and leaving the modal's
                # own "Vẫn đăng ngay" form (hx-target="#schedule-content")
                # with nothing to swap into (silently does nothing on
                # click — the bug reported 2026-09-09). #schedule-content
                # must stay present as the primary swap; the modal goes in
                # separately via an OOB swap into #modal-root.
                modal_oob = f'<div id="modal-root" hx-swap-oob="true">{_fire_now_confirm_modal_html(task_id, account_id, page, page_size, warning, action_filter, date_filter, tz_offset)}</div>'
                return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset) + modal_oob)
            return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, error=warning)
        if not allowed:
            # A hard count cap (posts_per_day/comments_per_hour/
            # comments_per_day/likes_per_hour) — never overridable, not
            # even by `force` (see can_proceed()'s docstring), so there's
            # no modal to offer here, just skip the doomed-to-fail
            # run_task() call and show the reschedule suggestion directly
            # (2026-09-11 — same investigation as fire_due_tasks()'s
            # matching pre-check).
            warning = daily_limits.hard_cap_message(account, bucket) or reason
            if _is_htmx(request):
                return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset, error=warning) + _MODAL_CLOSE_OOB)
            return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, error=warning)

    result = await run_task(TaskRequest(
        action=task.action,
        account_id=task.account_id,
        target_url=task.target_url,
        content=task.content,
        media_path=task.media_path,
        audience=task.audience,
        reasoning=task.reasoning,
        source="schedule_manual",
        source_kind=task.source_kind,
        source_id=task.source_id,
        # See data_sync.py's fire_due_tasks() for why: candidate tasks
        # carry their origin data in task.candidate_data instead, never
        # task.job_data — exactly one of the two is ever set.
        job_data=task.job_data or task.candidate_data,
        retry_of_log_id=task.retry_of_log_id,
        force_ignore_gap=force,
    ))
    if result.success:
        schedule_store.mark_posted(task_id, result.message)
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset, saved=True) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, saved=1)
    if result.message.startswith("rate_limited:"):
        # Same reasoning as data_sync.py's fire_due_tasks(): this isn't a
        # real failure of the post, it just fired too soon after the
        # account's last action (or hit a hard count cap — never
        # overridable) — keep it in pending/ with a warning instead of
        # failed/.
        warning = None
        if account and bucket:
            warning = rate_limit_wait_message(account, bucket) or daily_limits.hard_cap_message(account, bucket)
        schedule_store.update(task_id, last_warning=warning or result.message)
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset, error=warning or result.message) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, error=warning or result.message)
    schedule_store.mark_failed(task_id, result.message)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset, error=f"Đăng thất bại: {result.message}") + _MODAL_CLOSE_OOB)
    return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, error=f"Đăng thất bại: {result.message}")


# --- Joined group URLs (per-account, used by the data-sync poller) ---------
#
# Fully htmx-driven CRUD: the account filter and every add/edit/delete
# form target #groups-content and swap it in place, so switching accounts
# or editing a group never reloads the whole page. _groups_content_html()
# is the one function that builds that fragment — used both by the plain
# GET (first load / no-JS fallback / any link a user pastes directly) and
# by every mutating POST when called via htmx (see _is_htmx()).

def _groups_redirect(account_id: str, **params) -> RedirectResponse:
    from urllib.parse import urlencode
    query = {"account_id": account_id, **params}
    query = {k: v for k, v in query.items() if v not in (None, "")}
    return RedirectResponse(url=f"/admin/groups?{urlencode(query)}", status_code=303)


def _groups_content_html(
    account_id: str | None, saved: bool = False, error: str | None = None, oob: bool = False
) -> str:
    accounts = get_all_accounts()
    account_ids = list(accounts)
    if not account_ids:
        return '<div id="groups-content"><div class="empty-state">Chưa có tài khoản nào — đăng ký ở /admin/accounts trước.</div></div>'
    if account_id not in accounts:
        account_id = account_ids[0]
    account = accounts[account_id]
    groups = get_joined_groups(account_id)

    flash = '<p class="flash">✅ Đã lưu.</p>' if saved else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""

    account_options = "".join(
        f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(a.display_name)} ({html.escape(aid)})</option>'
        for aid, a in accounts.items()
    )
    filter_html = f"""
<div class="account-filter">
  <label for="groups-account-select">Tài khoản</label>
  <select name="account_id" id="groups-account-select"
          hx-get="/admin/groups" hx-target="#groups-content" hx-swap="outerHTML"
          hx-trigger="change" hx-push-url="true">{account_options}</select>
  <span class="badge">{len(groups)} nhóm</span>
  <button type="button" class="btn-small" style="margin-left:auto;"
          hx-get="/admin/groups/add-modal?account_id={html.escape(account_id)}"
          hx-target="#modal-root" hx-swap="innerHTML">➕ Thêm nhóm mới</button>
</div>"""

    if groups:
        rows = []
        for g in groups:
            name_display = html.escape(g.name) if g.name else '<span class="muted">(chưa đặt tên)</span>'
            url_display = html.escape(g.url)
            rows.append(f"""
<tr>
  <td>{name_display}</td>
  <td class="row-url"><a href="{url_display}" target="_blank" rel="noopener">{url_display}</a></td>
  <td class="col-actions">
    <button type="button" class="btn-small btn-secondary"
            hx-get="/admin/groups/edit-modal?account_id={html.escape(account_id)}&group_id={html.escape(g.id)}"
            hx-target="#modal-root" hx-swap="innerHTML">Sửa</button>
    <form method="post" action="/admin/groups/delete"
          hx-post="/admin/groups/delete" hx-target="#groups-content" hx-swap="outerHTML"
          hx-confirm="Xoá nhóm này khỏi danh sách?">
      <input type="hidden" name="account_id" value="{html.escape(account_id)}">
      <input type="hidden" name="group_id" value="{html.escape(g.id)}">
      <button type="submit" class="btn-small btn-secondary">Xoá</button>
    </form>
  </td>
</tr>""")
        table_html = f"""
<div class="card">
  <h2>👥 Danh sách nhóm — {html.escape(account.display_name)}</h2>
  <div class="table-scroll">
  <table class="data-table">
    <thead><tr><th>Tên nhóm</th><th>URL nhóm</th><th></th></tr></thead>
    <tbody>{''.join(rows)}</tbody>
  </table>
  </div>
</div>"""
    else:
        table_html = '<div class="empty-state">Tài khoản này chưa có nhóm nào. Bấm "➕ Thêm nhóm mới" ở trên để thêm nhóm đầu tiên.</div>'

    oob_attr = ' hx-swap-oob="true"' if oob else ""
    return f"""<div id="groups-content"{oob_attr}>
{filter_html}
{flash}{err}
{table_html}
</div>"""


def _group_modal_html(
    mode: str,  # "add" | "edit"
    account_id: str,
    group_id: str | None = None,
    name: str = "",
    url: str = "",
    error: str | None = None,
) -> str:
    """Renders the whole #modal-root swap for the add/edit group form —
    used both to open the modal (GET /groups/add-modal, /groups/edit-modal)
    and to redisplay it with a validation error without closing it (the
    POST handlers below). A successful POST returns something else
    entirely (an out-of-band #groups-content update with no primary
    content), which is what actually closes the modal — see
    _groups_content_html()'s `oob` param.

    Identifies the group being edited by its stable GroupRef.id, not by
    position in the list — a list index baked into this form at render
    time could point at the wrong group by the time it's submitted, if
    the list changed in between (another tab, a concurrent edit)."""
    is_edit = mode == "edit"
    title = "✏️ Sửa nhóm" if is_edit else "➕ Thêm nhóm mới"
    action_url = "/admin/groups/update" if is_edit else "/admin/groups/add"
    submit_label = "Lưu thay đổi" if is_edit else "Thêm vào danh sách"
    id_field = f'<input type="hidden" name="group_id" value="{html.escape(group_id)}">' if is_edit and group_id else ""
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>{title}</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    {err_html}
    <form method="post" action="{action_url}" hx-post="{action_url}" hx-target="#modal-root" hx-swap="innerHTML">
      <input type="hidden" name="account_id" value="{html.escape(account_id)}">
      {id_field}
      <div class="field-grid">
        <div class="field-stack"><div class="field-label">Tên nhóm</div><div class="field-input"><input type="text" name="name" value="{html.escape(name)}" placeholder="Nhóm IT Nhật Bản"></div></div>
        <div class="field-stack"><div class="field-label">URL nhóm</div><div class="field-input"><input type="text" name="url" value="{html.escape(url)}" placeholder="https://www.facebook.com/groups/123456789012345" required></div></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        <button type="submit">{submit_label}</button>
      </div>
    </form>
  </div>
</div>"""


@router.get("/groups", response_class=HTMLResponse)
async def groups_form(
    request: Request,
    account_id: str | None = None,
    saved: bool = False,
    error: str | None = None,
    _: None = Depends(_require_auth),
) -> str:
    content = _groups_content_html(account_id, saved, error)
    if _is_htmx(request):
        return content
    return _layout(f"""
<h1>Nhóm đã tham gia</h1>
<p class="page-desc">Danh sách nhóm Facebook mỗi tài khoản đã tham gia. Bộ đồng bộ dữ liệu bên B (human_bot/data_sync.py) dùng danh sách này để broadcast mỗi bài tuyển dụng mới vào tất cả các nhóm của tài khoản tương ứng. Lưu ở đây có hiệu lực ngay, không cần sửa code hay khởi động lại. Ưu tiên URL dạng ID số thay vì tên tuỳ chỉnh — xem docs/skills/group-targeting.md, mục "Numeric ID vs. custom (vanity) group URL".</p>
{content}
""", active="groups")


@router.get("/groups/add-modal", response_class=HTMLResponse)
async def groups_add_modal(account_id: str | None = None, _: None = Depends(_require_auth)) -> str:
    accounts = get_all_accounts()
    account_ids = list(accounts)
    if account_id not in accounts:
        account_id = account_ids[0] if account_ids else ""
    return _group_modal_html("add", account_id)


def _find_group(groups: list[GroupRef], group_id: str) -> GroupRef | None:
    return next((g for g in groups if g.id == group_id), None)


@router.get("/groups/edit-modal", response_class=HTMLResponse)
async def groups_edit_modal(account_id: str, group_id: str, _: None = Depends(_require_auth)) -> str:
    g = _find_group(get_joined_groups(account_id), group_id)
    if g is None:
        return _group_modal_html("edit", account_id, group_id=group_id, error="Mục không còn tồn tại — có thể đã bị xoá.")
    return _group_modal_html("edit", account_id, group_id=group_id, name=g.name, url=g.url)


@router.post("/groups/add")
async def groups_add(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id = str(form.get("account_id", ""))
    name = str(form.get("name", "")).strip()
    url = str(form.get("url", "")).strip()
    if not url:
        if _is_htmx(request):
            return HTMLResponse(_group_modal_html("add", account_id, name=name, url=url, error="URL nhóm không được để trống"))
        return _groups_redirect(account_id, error="URL nhóm không được để trống")
    groups = get_joined_groups(account_id)
    new_id = new_group_id({g.id for g in groups})
    groups.append(GroupRef(id=new_id, name=name, url=url))
    save_joined_groups(account_id, groups)
    if _is_htmx(request):
        # No primary content for #modal-root (the form's own hx-target) —
        # htmx empties it, closing the modal — plus an out-of-band refresh
        # of #groups-content so the new group shows up immediately.
        return HTMLResponse(_groups_content_html(account_id, saved=True, oob=True))
    return _groups_redirect(account_id, saved=1)


@router.post("/groups/update")
async def groups_update(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id = str(form.get("account_id", ""))
    group_id = str(form.get("group_id", "")).strip()
    if not group_id:
        if _is_htmx(request):
            return HTMLResponse(_groups_content_html(account_id, error="Mục không hợp lệ", oob=True))
        return _groups_redirect(account_id, error="Mục không hợp lệ")
    name = str(form.get("name", "")).strip()
    url = str(form.get("url", "")).strip()
    if not url:
        if _is_htmx(request):
            return HTMLResponse(_group_modal_html("edit", account_id, group_id=group_id, name=name, url=url, error="URL nhóm không được để trống"))
        return _groups_redirect(account_id, error="URL nhóm không được để trống")
    groups = get_joined_groups(account_id)
    existing = _find_group(groups, group_id)
    if existing is None:
        if _is_htmx(request):
            return HTMLResponse(_groups_content_html(account_id, error="Mục không còn tồn tại", oob=True))
        return _groups_redirect(account_id, error="Mục không còn tồn tại")
    # Keep the same id — this is an edit, not a replace; a new random id
    # here would break any in-flight reference to the old one (e.g. a
    # second tab with this group's edit modal still open).
    groups = [GroupRef(id=g.id, name=name, url=url) if g.id == group_id else g for g in groups]
    save_joined_groups(account_id, groups)
    if _is_htmx(request):
        return HTMLResponse(_groups_content_html(account_id, saved=True, oob=True))
    return _groups_redirect(account_id, saved=1)


@router.post("/groups/delete")
async def groups_delete(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id = str(form.get("account_id", ""))
    group_id = str(form.get("group_id", "")).strip()
    groups = get_joined_groups(account_id)
    remaining = [g for g in groups if g.id != group_id]
    if len(remaining) != len(groups):
        save_joined_groups(account_id, remaining)
    if _is_htmx(request):
        return HTMLResponse(_groups_content_html(account_id, saved=True))
    return _groups_redirect(account_id, saved=1)


# --- Reports (from human_bot/db.py's action_log) ----------------------------

_SOURCE_LABELS: dict[str, str] = {
    "manual": "Đăng trực tiếp (/admin/post)",
    "queue": "Từ hàng đợi (content_queue)",
    "schedule_manual": "Đăng ngay (/admin/schedule)",
    "schedule_auto": "Tự động (bộ đồng bộ bên B)",
    "api": "Gọi API /tasks trực tiếp (VD: n8n)",
}


def _expandable_text(text: str | None, limit: int = 80) -> str:
    """Show `text` clipped to one line with a CSS ellipsis, with a native
    <details> disclosure (no JS needed) to expand and read the full thing
    — for /admin/reports' "Ghi chú"/"Nội dung đã đăng" columns, where a
    Playwright error message or a full post can run well past a single
    line. The FULL text is the only copy of the markup — always lives
    inside <summary> — clipped via the `.expandable-text > summary` CSS
    rule while closed, shown in full (no more clipping) once <details>
    opens, so expanding swaps straight to the full text in place instead
    of showing a short teaser stacked above a second, separate copy of
    the same text (owner-reported 2026-09-12). Only wraps in <details>
    when actually longer than `limit`; a short message renders as plain
    text, no disclosure triangle for nothing."""
    text = text or ""
    if not text:
        return '<span class="muted">—</span>'
    full = html.escape(text)
    if len(text) <= limit:
        return full
    return f'<details class="expandable-text"><summary>{full}</summary></details>'


def _screenshot_link_html(path: str | None) -> str:
    """A "📷 Xem" link to /admin/screenshot for one action_log row's
    evidence screenshot (human_bot/screenshots.py, added 2026-09-07) — or
    a muted dash if this row has none (older rows from before this
    feature, or the screenshot itself failed to capture / was already
    pruned by screenshots.cleanup_old())."""
    if not path:
        return '<span class="muted">—</span>'
    from urllib.parse import quote
    return f'<a href="/admin/screenshot?path={quote(path, safe="")}" target="_blank" rel="noopener">📷 Xem</a>'


_REPORTS_DAYS_LABELS: dict[str, str] = {
    "": "Tất cả thời gian",
    "7": "7 ngày qua",
    "30": "30 ngày qua",
    "90": "90 ngày qua",
}
_REPORTS_RECENT_PAGE_SIZE = 15
# Choices offered by the "Hoạt động gần đây" items-per-page <select> —
# added 2026-09-11, same pattern (and same owner request) as
# /admin/schedule's _SCHEDULE_PAGE_SIZE_CHOICES above; default (15) kept
# as-is rather than switched to match schedule's default, so a bare
# /admin/reports (no page_size in the URL) renders exactly as before.
_REPORTS_PAGE_SIZE_CHOICES = (10, 15, 30, 50, 100)
# "Theo từng lần đăng" job-report page size (2026-09-12) — fixed rather
# than a selectable choice like recent activity's: each row here expands
# into a whole per-group sub-table, so even 10 jobs/page can already be a
# tall card. No owner request yet for a selector, so kept simple.
_JOB_REPORT_PAGE_SIZE = 10
# "Theo từng lần bình luận" candidate-report page size (2026-09-12) — same
# fixed-not-selectable reasoning as _JOB_REPORT_PAGE_SIZE above.
_CANDIDATE_REPORT_PAGE_SIZE = 10

# /admin/reports tab keys (2026-09-12, owner request — page had grown to 6
# stacked cards, some with their own pagination, "quá nhiều nội dung").
# "tables" (KPI + theo tuần/nhóm/hành động) is the default so a bare
# /admin/reports with no `tab` in the URL renders exactly what it always
# has, same "don't change behavior for old bookmarks/links" reasoning as
# _REPORTS_RECENT_PAGE_SIZE's default above.
_REPORTS_TABS = ("tables", "jobs", "candidates", "recent")
_REPORTS_TAB_LABELS = {
    "tables": "📊 Thống kê chi tiết",
    "jobs": "📮 Bài đăng",
    "candidates": "💬 Bình luận",
    "recent": "🕒 Hoạt động gần đây",
}


def _clamp_reports_tab(raw: str | None) -> str:
    return raw if raw in _REPORTS_TABS else "tables"


def _clamp_reports_page_size(raw: int) -> int:
    return raw if raw in _REPORTS_PAGE_SIZE_CHOICES else _REPORTS_RECENT_PAGE_SIZE

# Actions "Đăng lại" (repost) can resubmit from a past action_log row —
# the ones that post free-form `content` somewhere (own profile / a group)
# plus group comments (added on request — comment_on_friend_post stays out
# since that action is intentionally deprioritized/paused, see
# docs/architecture.md or ask before re-enabling it). Like/read actions
# have no standalone "content" to repost, and media_path is never stored in
# action_log (see docstring on the "Đăng lại" button below), so a repost is
# always text-only regardless of whether the original post had an image
# attached. Only offered for FAILED rows — a successful attempt doesn't
# need retrying, and resubmitting a successful comment/post would just be
# posting a duplicate (per-project decision, 2026-09-09).
_REPOSTABLE_ACTIONS = {"post_to_own_profile", "post_to_group", "comment_on_group_post"}

# Human-readable labels for known side-B `attributes` keys — used by
# _attrs_summary_html() below for BOTH "Bài đăng" (job) and "Bình luận"
# (candidate) "Dữ liệu gốc" — job_data/candidate_data are the RAW,
# UNFILTERED dict side B sent (see db.log_action()'s docstring), so any
# key not listed here still renders (falls back to its own raw key name)
# instead of silently disappearing — owner request 2026-09-12: "Phần nội
# dung gốc nên đầy đủ hơn" (the old version only showed a hand-picked
# subset — company/location/visaType/jlpt/salary for jobs,
# desiredJobField/preferredRegion for candidates — dropping anything side
# B sent outside that fixed list, `confidence`/`contact` included, even
# though the full dict was already sitting in the DB the whole time).
_ATTR_LABELS = {
    "jobField": "Ngành nghề",
    "company": "Công ty",
    "location": "Địa điểm",
    "visaType": "Loại visa",
    "jlpt": "JLPT",
    "salary": "Lương",
    "confidence": "Độ tin cậy",
    "desiredJobField": "Muốn làm",
    "preferredRegion": "Khu vực mong muốn",
    "contact": "Liên hệ",
}


def _attrs_summary_html(title, attrs: dict) -> str:
    """Renders EVERY non-empty key in `attrs` (plus `title` if given) as
    "Nhãn: giá trị" pairs — dynamic, not a fixed allowlist, so a field
    side B adds later (or one this project just hasn't named yet) still
    shows up, using its own key name as the label until _ATTR_LABELS
    above is taught a nicer one. `confidence` (a 0-1 ML score) is
    formatted as a percentage since the raw decimal reads oddly next to
    everything else here."""
    parts = []
    if title:
        parts.append(f"<b>{html.escape('Tiêu đề')}:</b> {html.escape(_format_attr(title))}")
    for key, value in (attrs or {}).items():
        if not value and value != 0:
            continue
        if key == "confidence":
            try:
                value = f"{float(value) * 100:.0f}%"
            except (TypeError, ValueError):
                pass
        label = _ATTR_LABELS.get(key, key)
        parts.append(f"<b>{html.escape(label)}:</b> {html.escape(_format_attr(value))}")
    return " &nbsp;·&nbsp; ".join(parts) if parts else '<span class="muted">—</span>'


_RESCHEDULE_SEARCH_DAYS = 30


def _suggest_reschedule_at(account, action: str) -> datetime:
    """The "🔄 Lên lịch lại" suggestion (owner request 2026-09-12): the
    earliest time this account could actually post/comment `action` again
    without breaking posts_per_day/comments_per_day, its own min-gap
    pacing, or quiet hours. Deliberately reuses the SAME primitives the
    real auto-scheduler (data_sync.py) and enforcement (daily_limits.py/
    safety.py) already use, rather than a separate ad-hoc rule.

    MUST also count already-PENDING scheduled tasks (schedule_store), not
    just past real attempts (daily_limits/RateLimiter only ever read
    action_log, which a pending task hasn't reached yet) — owner-reported
    bug 2026-09-12: suggesting "Lên lịch lại" twice in the same sitting
    (nothing had actually fired yet in between) kept returning the exact
    same slot both times, since neither daily_limits' business-day count
    nor RateLimiter's next_allowed_at() had any way to see the first
    suggestion the admin had just confirmed. Fixed by folding pending
    tasks of the same account+bucket into both checks below:
      1. Cap check — a business day's effective usage is REAL count
         (daily_limits.count_since_business_day_start(), today only) +
         however many pending tasks already land in that same business-
         day window.
      2. Gap check — same "kẹp sàn" as before via
         RateLimiter.next_allowed_at() (last REAL action), but also
         floored against the LATEST pending task's own scheduled_at +
         this account's min_delay_seconds for this bucket — otherwise 2
         reschedules in a row could still land back-to-back with no gap
         at all between them.

    These 3 checks (gap floor, quiet hours, day cap) are applied in a
    CONVERGING LOOP, not a single pass — owner-reported bug 2026-09-14:
    a single pass (floor → quiet hours → done) let the gap floor push
    the candidate BACK INTO quiet hours with nothing to catch it, and
    let it land on a day whose capacity was never re-checked (the
    day-cap loop only ran ONCE, before the floors were ever applied).
    Looping until nothing moves anymore means each fix-up gets
    re-validated against the other two.

    Search depth: business days start at 2 AM JST, exactly the start of
    the default quiet-hours window — so pushing to a fully-capped day's
    start (cap check) never itself ends the loop; the NEXT iteration
    still has to quiet-hours-clamp that 2 AM landing forward before the
    cap can be usefully re-checked. Skipping one fully-capped day this
    way costs 2 iterations (one to push to the next day, one to clamp
    it out of quiet hours — which may itself push straight past ANOTHER
    full day, so it's not always exactly 2, but never fewer), not 1 —
    see `_RESCHEDULE_SEARCH_DAYS` below.

    Only a SUGGESTION — reports_reschedule_confirm() still re-checks
    everything for real via schedule_store's normal fire-time path, this
    is just what the admin sees before clicking "Xác nhận"."""
    from human_bot import daily_limits, schedule_store
    from human_bot.agent import rate_limit_bucket_for
    from human_bot.safety import RateLimiter

    bucket = rate_limit_bucket_for(action)
    now = datetime.now(timezone.utc)

    if bucket == "post":
        sibling_actions = {"post_to_own_profile", "post_to_group"}
        cap = account.rate_limits.posts_per_day
        gap_seconds = account.rate_limits.post_min_delay_seconds
    elif bucket == "comment":
        sibling_actions = {"comment_on_group_post", "comment_on_friend_post"}
        cap = account.rate_limits.comments_per_day
        gap_seconds = account.rate_limits.comment_min_delay_seconds
    else:
        sibling_actions, cap, gap_seconds = set(), None, 0

    def _parse_aware(iso: str) -> datetime | None:
        try:
            dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        except ValueError:
            return None
        return dt if dt.tzinfo else dt.replace(tzinfo=timezone.utc)

    pending_times = sorted(
        t for t in (
            _parse_aware(p.scheduled_at) for p in schedule_store.list_pending()
            if p.account_id == account.account_id and p.action in sibling_actions
        ) if t is not None
    )

    def _pending_count_on(day_start: datetime) -> int:
        day_end = day_start + timedelta(days=1)
        return sum(1 for t in pending_times if day_start <= t < day_end)

    today_start = daily_limits.business_day_start(now)

    floors = []
    if bucket:
        real_floor = RateLimiter(account).next_allowed_at(bucket)
        if real_floor is not None:
            if real_floor.tzinfo is None:
                real_floor = real_floor.replace(tzinfo=timezone.utc)
            floors.append(real_floor)
    if pending_times:
        floors.append(pending_times[-1] + timedelta(seconds=gap_seconds))

    cfg = get_data_sync_config()
    candidate = now
    # 30 real days of search depth (project owner's call 2026-09-15 —
    # 30 consecutive fully-capped business days is already a config
    # problem worth surfacing, not something to keep searching past),
    # at up to 3 iterations/day per this function's own docstring above.
    for _ in range(_RESCHEDULE_SEARCH_DAYS * 3):
        moved = False

        if floors:
            raised = max(candidate, *floors)
            if raised != candidate:
                candidate, moved = raised, True

        clamped = apply_quiet_hours(candidate, cfg)
        if clamped != candidate:
            candidate, moved = clamped, True

        if cap is not None:
            day_start = daily_limits.business_day_start(candidate)
            real_used = (
                daily_limits.count_since_business_day_start(account, bucket)
                if bucket and day_start == today_start else 0
            )
            used = real_used + _pending_count_on(day_start)
            if used >= cap:
                candidate = day_start + timedelta(days=1)
                moved = True

        if not moved:
            break
    return candidate


def _repost_choice_button_html(
    r: sqlite3.Row, *, account_id: str | None, days: str | None, page: int, page_size: int,
    job_page: int, candidate_page: int, tab: str,
) -> str:
    """The "↻" trigger button — opens _repost_choice_modal_html() instead
    of resubmitting directly (owner request 2026-09-12: offer "Đăng ngay"/
    "Đặt lịch"/"Lên lịch lại" instead of only ever firing immediately).
    Same eligibility rule as before (see _REPOSTABLE_ACTIONS above)."""
    if r['action'] not in _REPOSTABLE_ACTIONS or r['success'] or not (r['content'] or '').strip():
        return ""
    from urllib.parse import urlencode
    qs = urlencode({
        "log_id": r["id"], "account_id": account_id or "", "days": days or "",
        "page": page, "page_size": page_size, "job_page": job_page,
        "candidate_page": candidate_page, "tab": tab,
    })
    return (
        f'<button type="button" class="btn-secondary btn-small" title="Đăng lại" '
        f'hx-get="/admin/reports/repost-choice?{qs}" hx-target="#modal-root" hx-swap="innerHTML">↻</button>'
    )


def _repost_choice_modal_html(
    row: sqlite3.Row, *, account_id: str | None, days: str | None, page: int, page_size: int,
    job_page: int, candidate_page: int, tab: str,
) -> str:
    """3-way choice modal for a FAILED repostable row (owner request
    2026-09-12): "Đăng ngay" (unchanged immediate-fire via
    /admin/reports/repost), "Đặt lịch" (opens /admin/post pre-filled,
    admin picks the date/time by hand), "Lên lịch lại" (server suggests
    the next slot that wouldn't break posts_per_day/comments_per_day —
    see _suggest_reschedule_at() — admin confirms before it's actually
    added to the schedule)."""
    from urllib.parse import urlencode
    filter_fields = (
        f'<input type="hidden" name="account_id" value="{html.escape(account_id or "")}">'
        f'<input type="hidden" name="days" value="{html.escape(days or "")}">'
        f'<input type="hidden" name="page" value="{page}">'
        f'<input type="hidden" name="page_size" value="{page_size}">'
        f'<input type="hidden" name="job_page" value="{job_page}">'
        f'<input type="hidden" name="candidate_page" value="{candidate_page}">'
        f'<input type="hidden" name="tab" value="{html.escape(tab)}">'
        f'<input type="hidden" name="log_id" value="{row["id"]}">'
    )
    is_comment = row["action"] in ("comment_on_group_post", "comment_on_friend_post")
    label = "bình luận" if is_comment else "bài viết"
    # post_to_own_profile has its OWN tab/prefill params on /admin/post
    # (profile_content/profile_scheduled_at, predating this feature) —
    # route it there instead of "group" (which is post_to_group only) or
    # "comment" (comment_on_*_post only).
    if row["action"] == "post_to_own_profile":
        prefill_qs = urlencode({
            "account_id": row["account_id"], "tab": "profile",
            "profile_content": row["content"] or "",
            "prefill_retry_of_log_id": row["id"],
        })
    else:
        prefill_qs = urlencode({
            "account_id": row["account_id"],
            "tab": "comment" if is_comment else "group",
            "prefill_content": row["content"] or "",
            "prefill_target_url": row["target_url"] or "",
            "prefill_retry_of_log_id": row["id"],
        })
    reschedule_qs = urlencode({
        "log_id": row["id"], "account_id": account_id or "", "days": days or "",
        "page": page, "page_size": page_size, "job_page": job_page,
        "candidate_page": candidate_page, "tab": tab,
    })
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>↻ Đăng lại {label}</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    <p class="muted">Bản ghi này đã thất bại — chọn cách xử lý:</p>
    <ul style="font-size:13px; color:#6b7280; margin:0 0 16px; padding-left:18px; line-height:1.7;">
      <li><b>Đăng ngay</b> — thử lại ngay bây giờ, vẫn kiểm tra đủ giới hạn số lượng/ngày và /giờ như bình thường.</li>
      <li><b>Đặt lịch</b> — mở trang soạn bài với nội dung điền sẵn, bạn tự chọn ngày giờ.</li>
      <li><b>Lên lịch lại</b> — hệ thống tự tìm giờ trống gần nhất còn đủ hạn mức, bạn xác nhận trước khi thêm vào lịch.</li>
    </ul>
    <div style="display:flex; flex-direction:column; gap:8px;">
      <form method="post" action="/admin/reports/repost" hx-post="/admin/reports/repost" hx-target="#reports-content" hx-swap="outerHTML">
        {filter_fields}
        <button type="submit" style="width:100%;">🚀 Đăng ngay</button>
      </form>
      <a class="btn-secondary" style="width:100%; text-align:center; box-sizing:border-box;" href="/admin/post?{prefill_qs}">📅 Đặt lịch</a>
      <button type="button" class="btn-secondary" style="width:100%;"
              hx-get="/admin/reports/reschedule-suggest?{reschedule_qs}" hx-target="#modal-root" hx-swap="innerHTML">🔄 Lên lịch lại</button>
    </div>
  </div>
</div>"""


def _reports_since(days: str | None) -> str | None:
    """`days` (from the "Khoảng thời gian" filter, e.g. "30") to an ISO
    UTC cutoff `created_at >= this` — None/"" means no cutoff (all time)."""
    if not days:
        return None
    try:
        n = int(days)
    except ValueError:
        return None
    from datetime import datetime, timedelta, timezone
    return (datetime.now(timezone.utc) - timedelta(days=n)).isoformat()


def _reports_content_html(
    account_id: str | None = None, days: str | None = None, page: int = 1,
    page_size: int = _REPORTS_RECENT_PAGE_SIZE, job_page: int = 1, candidate_page: int = 1,
    tab: str | None = None,
    posted: str | None = None, error: str | None = None, warning: str | None = None,
) -> str:
    page_size = _clamp_reports_page_size(page_size)
    tab = _clamp_reports_tab(tab)
    accounts = get_all_accounts()
    since = _reports_since(days)
    flash = f'<p class="flash">✅ {html.escape(posted)}</p>' if posted else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    # Separate from `error` (2026-09-11, owner request): "Đăng lại" hitting
    # the account's own rate-limit gap isn't a real failure — the repost
    # just fired too soon, exactly like /admin/schedule's "Đăng ngay" hitting
    # the same gap (see reports_repost() below) — so it gets the neutral
    # `.warning` style (amber) instead of `.error` (red), same distinction
    # schedule_fire_now() already makes with rate_limit_wait_message().
    warn = f'<p class="warning">⏳ {html.escape(warning)}</p>' if warning else ""

    account_options = '<option value="">— Tất cả tài khoản —</option>' + "".join(
        f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(a.display_name)} ({html.escape(aid)})</option>'
        for aid, a in accounts.items()
    )
    days_options = "".join(
        f'<option value="{html.escape(key)}"{" selected" if (days or "") == key else ""}>{html.escape(label)}</option>'
        for key, label in _REPORTS_DAYS_LABELS.items()
    )
    page_size_options = "".join(
        f'<option value="{size}"{" selected" if size == page_size else ""}>{size}/trang</option>'
        for size in _REPORTS_PAGE_SIZE_CHOICES
    )
    # The page-size <select> itself renders inside the "Hoạt động gần
    # đây" card's own header row, next to that card's title (owner
    # request 2026-09-11, twice: first moved out of the page-wide
    # account/days filter row since it only affects this one card, then
    # out of the card's footer too — "xấu quá" — up next to the title
    # instead) — but its markup and hx-include wiring live together right
    # here since both selects need each other's id, and this is where
    # account_options/days_options are already in scope.
    # #reports-pagesize-select still gets found by hx-include regardless
    # of where in the DOM it ends up.
    page_size_select_html = f"""<label for="reports-pagesize-select" class="muted">Hiển thị</label>
  <select name="page_size" id="reports-pagesize-select"
          hx-get="/admin/reports" hx-target="#reports-content" hx-swap="outerHTML"
          hx-trigger="change" hx-include="#reports-account-select, #reports-days-select"
          hx-vals='{{"tab": "recent"}}' hx-push-url="true">{page_size_options}</select>"""
    # The 2 page-wide selects include the page-size one via hx-include so
    # switching account/days never silently resets it back to default.
    # hx-vals carries the currently active tab through (2026-09-12) — these
    # selects render above every tab, so without it, changing the account/
    # days filter would silently snap back to the default "tables" tab.
    filter_html = f"""
<div class="account-filter">
  <label for="reports-account-select">Tài khoản</label>
  <select name="account_id" id="reports-account-select"
          hx-get="/admin/reports" hx-target="#reports-content" hx-swap="outerHTML"
          hx-trigger="change" hx-include="#reports-days-select, #reports-pagesize-select"
          hx-vals='{{"tab": "{tab}"}}' hx-push-url="true">{account_options}</select>
  <label for="reports-days-select">Khoảng thời gian</label>
  <select name="days" id="reports-days-select"
          hx-get="/admin/reports" hx-target="#reports-content" hx-swap="outerHTML"
          hx-trigger="change" hx-include="#reports-account-select, #reports-pagesize-select"
          hx-vals='{{"tab": "{tab}"}}' hx-push-url="true">{days_options}</select>
</div>"""

    def _reports_tab_link(tab_key: str) -> str:
        from urllib.parse import urlencode as _urlencode_tab
        active = tab_key == tab
        qs = _urlencode_tab({k: v for k, v in {
            "account_id": account_id, "days": days, "tab": tab_key,
            "page_size": page_size if page_size != _REPORTS_RECENT_PAGE_SIZE else None,
        }.items() if v})
        style = (
            "border-bottom:2px solid #111827; font-weight:600; color:#111827;" if active
            else "border-bottom:2px solid transparent; color:#6b7280;"
        )
        return (
            f'<a href="/admin/reports?{qs}" hx-get="/admin/reports?{qs}" '
            f'hx-target="#reports-content" hx-swap="outerHTML" hx-push-url="true" '
            f'style="padding:8px 4px; text-decoration:none; {style}">{_REPORTS_TAB_LABELS[tab_key]}</a>'
        )

    tab_nav_html = f"""
<div style="display:flex; gap:20px; margin-bottom:18px; border-bottom:1px solid #e5e7eb;">
  {"".join(_reports_tab_link(k) for k in _REPORTS_TABS)}
</div>"""

    # --- KPI summary — glance-and-go health check before the detail tables ---
    stats = db.summary_stats(account_id=account_id, since=since)
    rate_display = f"{stats['success_rate']}%" if stats["success_rate"] is not None else "—"
    # Equal-width 5-column grid (owner request 2026-09-11 — the previous
    # flex/gap layout let each tile take only as much width as its own
    # content needed, so the 5 tiles ended up visibly uneven). auto-fit +
    # minmax still divides evenly on narrow screens (fewer, wider columns)
    # instead of overflowing.
    summary_html = f"""
<div class="card">
  <div style="display:grid; grid-template-columns:repeat(auto-fit, minmax(150px, 1fr)); gap:24px;">
    <div><div class="muted" style="font-size:12px;">Tổng số hành động</div><div style="font-size:22px; font-weight:700;">{stats['total']}</div></div>
    <div><div class="muted" style="font-size:12px;">Thành công</div><div style="font-size:22px; font-weight:700; color:#059669;">{stats['succeeded']}</div></div>
    <div><div class="muted" style="font-size:12px;">Thất bại</div><div style="font-size:22px; font-weight:700; color:#dc2626;">{stats['failed']}</div></div>
    <div><div class="muted" style="font-size:12px;">Tỉ lệ thành công</div><div style="font-size:22px; font-weight:700;">{rate_display}</div></div>
    <div><div class="muted" style="font-size:12px;">Tài khoản có hoạt động</div><div style="font-size:22px; font-weight:700;">{stats['active_accounts']}</div></div>
  </div>
</div>"""

    # Which failed rows already have a pending (not-yet-fired) retry task
    # queued via "📅 Đặt lịch"/"🔄 Lên lịch lại" (2026-09-12) — one cheap
    # directory scan, reused by whichever tab actually renders below, so
    # those rows show "⏳ Đã lên lịch lại" instead of the "↻" button
    # again. Pairs with db.successful_retry_log_ids() (per-tab, batched
    # over just the rows that tab is about to render) for the "✅ Đã đăng
    # lại" case — see _repost_action_cell_html() below.
    pending_retry_ids = {
        t.retry_of_log_id for t in schedule_store.list_pending() if t.retry_of_log_id
    }

    # Tab "tables" only (2026-09-12) — skip these 3 queries entirely on the
    # other 2 tabs, same reasoning as the job/recent sections below: no
    # point querying data a tab switch won't even render.
    if tab == "tables":
        weekly_rows = db.weekly_post_counts(account_id=account_id, since=since)
        if weekly_rows:
            weekly_html = "".join(
                f"<tr><td>{html.escape(r['week'])}</td><td>{html.escape(_account_label(r['account_id'], accounts))}</td><td>{r['total']}</td></tr>"
                for r in weekly_rows
            )
            weekly_table = f"""
<div class="table-scroll"><table class="data-table">
  <thead><tr><th>Tuần</th><th>Tài khoản</th><th>Số bài đăng thành công</th></tr></thead>
  <tbody>{weekly_html}</tbody>
</table></div>"""
        else:
            weekly_table = '<div class="empty-state">Chưa có bài đăng thành công nào được ghi nhận.</div>'

        group_rows = db.group_post_counts(account_id=account_id, since=since)
        if group_rows:
            group_html = "".join(
                f"""<tr>
  <td>{html.escape(_account_label(r['account_id'], accounts))}</td>
  <td>{html.escape(r['target_group_name']) if r['target_group_name'] else '<span class="muted">(chưa rõ tên)</span>'}</td>
  <td class="row-url"><a href="{html.escape(r['target_url'] or '')}" target="_blank" rel="noopener">{html.escape(r['target_url'] or '')}</a></td>
  <td>{r['total']}</td>
</tr>""" for r in group_rows
            )
            group_table = f"""
<div class="table-scroll"><table class="data-table">
  <thead><tr><th>Tài khoản</th><th>Tên nhóm</th><th>URL nhóm</th><th>Số bài đăng thành công</th></tr></thead>
  <tbody>{group_html}</tbody>
</table></div>"""
        else:
            group_table = '<div class="empty-state">Chưa có bài đăng nhóm nào được ghi nhận.</div>'

        action_rows = db.action_type_counts(account_id=account_id, since=since)
        if action_rows:
            # Pivot db.action_type_counts()'s (action, success, total) rows —
            # one row per (action, success/fail) combo — into one row per
            # action with separate Thành công/Thất bại columns (owner request
            # 2026-09-11: easier to scan than a repeated "Kết quả" column).
            # dict preserves first-seen order, which matches the query's own
            # `ORDER BY action, success DESC`.
            pivoted: dict[str, dict[str, int]] = {}
            for r in action_rows:
                entry = pivoted.setdefault(r["action"], {"succeeded": 0, "failed": 0})
                entry["succeeded" if r["success"] else "failed"] = r["total"]
            action_html = "".join(
                f"""<tr>
  <td>{html.escape(_ACTION_LABELS.get(action, action))}</td>
  <td style="color:#059669;">{counts['succeeded']}</td>
  <td style="color:#dc2626;">{counts['failed']}</td>
</tr>""" for action, counts in pivoted.items()
            )
            action_table = f"""
<div class="table-scroll"><table class="data-table">
  <thead><tr><th>Hành động</th><th>Thành công</th><th>Thất bại</th></tr></thead>
  <tbody>{action_html}</tbody>
</table></div>"""
        else:
            action_table = '<div class="empty-state">Chưa có dữ liệu.</div>'

    # --- "Theo từng lần đăng" (2026-09-12): one job = one card of its own —
    # target groups, per-group content actually posted, per-group time and
    # result, and the raw side-B job data it came from. Grouped server-side
    # by db.job_post_groups() (source_kind='job' rows only — candidates
    # have no per-group fan-out to gather), rendered as one <details> per
    # job so the (potentially long) per-group table only takes space once
    # opened.
    def _recent_result_icon(r: sqlite3.Row) -> str:
        # Distinct from a real failure (2026-09-11, same reasoning as
        # summary_stats()/action_type_counts() in db.py) — a rate_limited
        # row was never actually attempted, so lumping it in with ⚠️ next
        # to genuine broken-selector/timeout failures made the "KQ" column
        # misleading at a glance. Used by both "Hoạt động gần đây" and
        # "Theo từng lần đăng" (2026-09-12) — same action_log rows, same
        # icon rules.
        if r["success"]:
            return "✅"
        if (r["message"] or "").startswith("rate_limited:"):
            return "⏳"
        return "⚠️"

    def _group_link_html(row: sqlite3.Row) -> str:
        # Same link-the-name pattern as the "Bài đăng theo nhóm" table
        # above — bấm tên nhóm/bài mở thẳng ra đó (owner request
        # 2026-09-12). Used by both "Theo từng lần đăng" (nhóm) and
        # "Theo từng lần bình luận" (bài/nhóm chứa comment).
        name = row["target_group_name"] or row["target_url"] or "—"
        if row["target_url"]:
            return f'<a href="{html.escape(row["target_url"])}" target="_blank" rel="noopener">{html.escape(name)}</a>'
        return html.escape(name)

    def _repost_action_cell_html(r: sqlite3.Row, done_retry_ids: set[int]) -> str:
        # Replaces the "↻" button with a plain status text once this row
        # has already been handled (owner request 2026-09-12: "Bài Đăng/
        # Bình luận nào đã được lên lịch lại (tự động hay ADMIN thêm lại,
        # hoặc đã ĐĂNG NGAY) — thay nút ĐĂNG LẠI bằng text"). Checked in
        # this order: a still-PENDING retry task (schedule_store) wins
        # over a past completed one, since that's the more current state.
        if r['action'] not in _REPOSTABLE_ACTIONS or r['success'] or not (r['content'] or '').strip():
            return ""
        if r["id"] in pending_retry_ids:
            return '<span class="muted" style="font-size:12px; white-space:nowrap;">⏳ Đã lên lịch lại</span>'
        if r["id"] in done_retry_ids:
            return '<span class="muted" style="font-size:12px; white-space:nowrap;">✅ Đã đăng lại</span>'
        return _repost_choice_button_html(
            r, account_id=account_id, days=days, page=page, page_size=page_size,
            job_page=job_page, candidate_page=candidate_page, tab=tab,
        )

    job_cards_html = job_nav_html = ""
    if tab == "jobs":
        job_total = db.job_post_groups_count(account_id=account_id, since=since)
        job_total_pages = max(1, -(-job_total // _JOB_REPORT_PAGE_SIZE))
        job_page = min(max(job_page, 1), job_total_pages)
        job_rows = db.job_post_groups(
            account_id=account_id, since=since,
            limit=_JOB_REPORT_PAGE_SIZE, offset=(job_page - 1) * _JOB_REPORT_PAGE_SIZE,
        )

        def _job_data_summary_html(raw: str | None) -> str:
            if not raw:
                return '<span class="muted">(không có dữ liệu gốc)</span>'
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                return '<span class="muted">(dữ liệu gốc không đọc được)</span>'
            attrs = data.get("attributes") or {}
            # title falls back to nothing here (not jobField) — jobField
            # already renders on its own via the attrs loop below (as
            # "Ngành nghề"), showing it twice under 2 different labels
            # would be redundant.
            return _attrs_summary_html(data.get("title"), attrs)

        if job_rows:
            job_cards_html = ""
            # Fetch every job's detail rows FIRST (before building any
            # HTML) so successful_retry_log_ids() can run as ONE batched
            # query over every failed row on this page, instead of one
            # query per row (2026-09-12).
            job_detail_by_source = {
                (jr["source_id"], jr["account_id"]): db.job_post_group_detail(jr["source_id"], jr["account_id"])
                for jr in job_rows
            }
            eligible_ids = [
                d["id"] for rows in job_detail_by_source.values() for d in rows
                if d["action"] in _REPOSTABLE_ACTIONS and not d["success"] and (d["content"] or "").strip()
            ]
            done_retry_ids = db.successful_retry_log_ids(eligible_ids)
            for jr in job_rows:
                detail_rows = job_detail_by_source[(jr["source_id"], jr["account_id"])]
                detail_html = "".join(
                    f"""<tr>
  <td>{_local_dt_html(d['created_at'])}</td>
  <td class="row-url">{_group_link_html(d)}</td>
  <td class="muted">{_expandable_text(d['content'])}</td>
  <td style="text-align:center;">{_recent_result_icon(d)}</td>
  <td>{_screenshot_link_html(d['screenshot_path'] if 'screenshot_path' in d.keys() else None)}</td>
  <td class="muted">{_expandable_text(d['message'])}</td>
  <td>{_repost_action_cell_html(d, done_retry_ids)}</td>
</tr>""" for d in detail_rows
                )
                succeeded = jr["succeeded_groups"] or 0
                failed = jr["total_groups"] - succeeded
                result_summary = f'<span style="color:#059669;">{succeeded} thành công</span>'
                if failed:
                    result_summary += f', <span style="color:#dc2626;">{failed} thất bại</span>'
                job_cards_html += f"""
<details style="border:1px solid #e5e7eb; border-radius:8px; padding:10px 14px; margin-bottom:10px;">
  <summary style="cursor:pointer; font-weight:600;">
    {html.escape(_account_label(jr['account_id'], accounts))} — {jr['total_groups']} nhóm ({result_summary})
    <span class="muted" style="font-weight:400;"> · {_local_dt_html(jr['first_posted_at'])} → {_local_dt_html(jr['last_posted_at'])}</span>
  </summary>
  <div class="page-desc" style="margin-top:8px;">{_job_data_summary_html(jr['job_data'])}</div>
  <div class="table-scroll" style="margin-top:8px;"><table class="data-table" style="table-layout:fixed; width:100%;">
    <thead><tr>
      <th style="width:12%;">Thời gian</th>
      <th style="width:14%;">Nhóm</th>
      <th style="width:26%;">Nội dung đã đăng</th>
      <th style="width:5%; text-align:center;">KQ</th>
      <th style="width:7%;">Ảnh</th>
      <th style="width:26%;">Ghi chú</th>
      <th style="width:10%;">Thao tác</th>
    </tr></thead>
    <tbody>{detail_html}</tbody>
  </table></div>
</details>"""
        else:
            job_cards_html = '<div class="empty-state">Chưa có bài đăng job nào được ghi nhận.</div>'

        if job_total_pages > 1:
            from urllib.parse import urlencode as _urlencode_job

            def _job_page_link(target_page: int, label: str, enabled: bool) -> str:
                if not enabled:
                    return f'<span class="btn-secondary btn-small" style="opacity:.45; pointer-events:none;">{label}</span>'
                qs = _urlencode_job({k: v for k, v in {
                    "account_id": account_id, "days": days, "tab": "jobs",
                    "page_size": page_size if page_size != _REPORTS_RECENT_PAGE_SIZE else None,
                    "job_page": target_page if target_page != 1 else None,
                }.items() if v})
                return (
                    f'<a class="btn-secondary btn-small" href="/admin/reports?{qs}" '
                    f'hx-get="/admin/reports?{qs}" hx-target="#reports-content" hx-swap="outerHTML" hx-push-url="true">{label}</a>'
                )

            job_nav_html = f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px; flex-wrap:wrap; gap:8px;">
  <div style="display:flex; gap:8px; align-items:center;">
    {_job_page_link(job_page - 1, "← Trang trước", job_page > 1)}
  </div>
  <span class="muted">Trang {job_page} / {job_total_pages} — {job_total} job</span>
  <div style="display:flex; gap:8px; align-items:center;">
    {_job_page_link(job_page + 1, "Trang sau →", job_page < job_total_pages)}
  </div>
</div>"""

    # --- "Theo từng lần bình luận" (2026-09-12, flattened same day per
    # owner request) — for candidate replies (source_kind='candidate'):
    # which post/friend a comment went to, the candidate's own raw
    # attributes (desiredJobField/preferredRegion — see content_strategist.
    # rewrite_candidate_reply()'s docstring), and the actual comment text
    # posted. FLAT table, one row per action_log row — unlike "theo từng
    # lần đăng"'s grouped <details> cards, a candidate only ever gets ONE
    # comment (no per-group fan-out like a job), so grouping just added a
    # pointless extra click per row ("chỉ có 1 bình luận cho từng bài viết
    # nên không cần gom nhóm lại đâu, thể hiện rõ ra luôn cũng được").
    candidate_cards_html = candidate_nav_html = ""
    if tab == "candidates":
        candidate_total = db.candidate_comments_count(account_id=account_id, since=since)
        candidate_total_pages = max(1, -(-candidate_total // _CANDIDATE_REPORT_PAGE_SIZE))
        candidate_page = min(max(candidate_page, 1), candidate_total_pages)
        candidate_rows = db.candidate_comments(
            account_id=account_id, since=since,
            limit=_CANDIDATE_REPORT_PAGE_SIZE, offset=(candidate_page - 1) * _CANDIDATE_REPORT_PAGE_SIZE,
        )

        def _candidate_data_summary_html(raw: str | None) -> str:
            if not raw:
                return '<span class="muted">—</span>'
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                return '<span class="muted">(không đọc được)</span>'
            return _attrs_summary_html(None, data.get("attributes") or {})

        if candidate_rows:
            eligible_ids = [
                r["id"] for r in candidate_rows
                if r["action"] in _REPOSTABLE_ACTIONS and not r["success"] and (r["content"] or "").strip()
            ]
            done_retry_ids = db.successful_retry_log_ids(eligible_ids)
            candidate_html = "".join(
                f"""<tr>
  <td>{_local_dt_html(r['created_at'])}</td>
  <td class="row-url">{_group_link_html(r)}</td>
  <td class="muted">{_candidate_data_summary_html(r['job_data'])}</td>
  <td class="muted">{_expandable_text(r['content'])}</td>
  <td style="text-align:center;">{_recent_result_icon(r)}</td>
  <td>{_screenshot_link_html(r['screenshot_path'] if 'screenshot_path' in r.keys() else None)}</td>
  <td class="muted">{_expandable_text(r['message'])}</td>
  <td>{_repost_action_cell_html(r, done_retry_ids)}</td>
</tr>""" for r in candidate_rows
            )
            candidate_cards_html = f"""
<div class="table-scroll"><table class="data-table" style="table-layout:fixed; width:100%;">
  <thead><tr>
    <th style="width:11%;">Thời gian</th>
    <th style="width:13%;">Bài/Nhóm</th>
    <th style="width:18%;">Dữ liệu gốc</th>
    <th style="width:21%;">Nội dung đã đăng</th>
    <th style="width:5%; text-align:center;">KQ</th>
    <th style="width:6%;">Ảnh</th>
    <th style="width:16%;">Ghi chú</th>
    <th style="width:10%;">Thao tác</th>
  </tr></thead>
  <tbody>{candidate_html}</tbody>
</table></div>"""
        else:
            candidate_cards_html = '<div class="empty-state">Chưa có bình luận nào được ghi nhận.</div>'

        if candidate_total_pages > 1:
            from urllib.parse import urlencode as _urlencode_candidate

            def _candidate_page_link(target_page: int, label: str, enabled: bool) -> str:
                if not enabled:
                    return f'<span class="btn-secondary btn-small" style="opacity:.45; pointer-events:none;">{label}</span>'
                qs = _urlencode_candidate({k: v for k, v in {
                    "account_id": account_id, "days": days, "tab": "candidates",
                    "page_size": page_size if page_size != _REPORTS_RECENT_PAGE_SIZE else None,
                    "candidate_page": target_page if target_page != 1 else None,
                }.items() if v})
                return (
                    f'<a class="btn-secondary btn-small" href="/admin/reports?{qs}" '
                    f'hx-get="/admin/reports?{qs}" hx-target="#reports-content" hx-swap="outerHTML" hx-push-url="true">{label}</a>'
                )

            candidate_nav_html = f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px; flex-wrap:wrap; gap:8px;">
  <div style="display:flex; gap:8px; align-items:center;">
    {_candidate_page_link(candidate_page - 1, "← Trang trước", candidate_page > 1)}
  </div>
  <span class="muted">Trang {candidate_page} / {candidate_total_pages} — {candidate_total} bình luận</span>
  <div style="display:flex; gap:8px; align-items:center;">
    {_candidate_page_link(candidate_page + 1, "Trang sau →", candidate_page < candidate_total_pages)}
  </div>
</div>"""

    # --- Recent activity: paginated + height-capped, so this block (by far
    # the longest one) never dominates the page regardless of how much
    # history exists — see the conversation that raised "4 khối khá dài,
    # nhất là Hoạt động gần đây". Tab "recent" only (2026-09-12).
    recent_total = 0
    recent_table = recent_pagination_html = ""
    if tab == "recent":
        recent_total = db.recent_activity_count(account_id=account_id, since=since)
        recent_total_pages = max(1, -(-recent_total // page_size))
        page = min(max(page, 1), recent_total_pages)
        recent_rows = db.recent_activity(
            limit=page_size,
            offset=(page - 1) * page_size,
            account_id=account_id,
            since=since,
        )
        if recent_rows:
            eligible_ids = [
                r["id"] for r in recent_rows
                if r["action"] in _REPOSTABLE_ACTIONS and not r["success"] and (r["content"] or "").strip()
            ]
            done_retry_ids = db.successful_retry_log_ids(eligible_ids)
            recent_html = "".join(
                f"""<tr>
  <td>{_local_dt_html(r['created_at'])}</td>
  <td>{html.escape(_account_label(r['account_id'], accounts))}</td>
  <td>{html.escape(_ACTION_LABELS.get(r['action'], r['action']))}</td>
  <td class="row-url">{html.escape((r['target_group_name'] or r['target_url'] or '—'))}</td>
  <td style="text-align:center;">{_recent_result_icon(r)}</td>
  <td>{html.escape(_SOURCE_LABELS.get(r['source'], r['source']))}</td>
  <td>{_screenshot_link_html(r['screenshot_path'] if 'screenshot_path' in r.keys() else None)}</td>
  <td class="muted">{_expandable_text(r['message'])}</td>
  <td>{_repost_action_cell_html(r, done_retry_ids)}</td>
</tr>""" for r in recent_rows
            )
            recent_table = f"""
<div class="table-scroll" style="max-height:420px; overflow-y:auto;"><table class="data-table" style="table-layout:fixed; width:100%;">
  <thead><tr>
    <th style="width:12%;">Thời gian</th>
    <th style="width:12%;">Tài khoản</th>
    <th style="width:12%;">Hành động</th>
    <th style="width:16%;">Đích</th>
    <th style="width:5%; text-align:center;">KQ</th>
    <th style="width:8%;">Nguồn</th>
    <th style="width:6%;">Ảnh</th>
    <th style="width:20%;">Ghi chú</th>
    <th style="width:9%;">Thao tác</th>
  </tr></thead>
  <tbody>{recent_html}</tbody>
</table></div>"""
        else:
            recent_table = '<div class="empty-state">Chưa có hoạt động nào được ghi nhận.</div>'

        # Footer row for the "Hoạt động gần đây" card (item count + nav) — the
        # page-size select itself now renders up in this card's own header
        # row, next to the "🕒 Hoạt động gần đây" title (2026-09-11: an
        # earlier version put it down here in the footer, owner found that
        # placement "xấu" — moved up so it reads as "controls for this card"
        # rather than buried at the bottom). The Đầu/Trước/jump/Sau/Cuối nav
        # below only renders once there's more than 1 page.
        nav_html = ""
        if recent_total_pages > 1:
            from urllib.parse import urlencode

            # First/last buttons + a pretty single-pill "go to page" jump —
            # same pattern (and same owner request) as /admin/schedule's
            # pagination; page_size threads through so navigating never
            # silently resets it back to the default.
            def _recent_page_link(target_page: int, label: str, enabled: bool) -> str:
                if not enabled:
                    return f'<span class="btn-secondary btn-small" style="opacity:.45; pointer-events:none;">{label}</span>'
                qs = urlencode({k: v for k, v in {
                    "account_id": account_id, "days": days, "page": target_page, "tab": "recent",
                    "page_size": page_size if page_size != _REPORTS_RECENT_PAGE_SIZE else None,
                }.items() if v})
                return (
                    f'<a class="btn-secondary btn-small" href="/admin/reports?{qs}" '
                    f'hx-get="/admin/reports?{qs}" hx-target="#reports-content" hx-swap="outerHTML" hx-push-url="true">{label}</a>'
                )

            jump_hidden_fields = (
                (f'<input type="hidden" name="account_id" value="{html.escape(account_id)}">' if account_id else "")
                + (f'<input type="hidden" name="days" value="{html.escape(days)}">' if days else "")
                + f'<input type="hidden" name="page_size" value="{page_size}">'
                + '<input type="hidden" name="tab" value="recent">'
            )
            nav_html = f"""
  <div style="display:flex; gap:8px; align-items:center;">
    {_recent_page_link(1, "«« Đầu", page > 1)}
    {_recent_page_link(page - 1, "← Trang trước", page > 1)}
  </div>
  <form hx-get="/admin/reports" hx-target="#reports-content" hx-swap="outerHTML" hx-push-url="true"
        style="display:flex; gap:6px; align-items:center; background:#f9fafb; border:1px solid #e5e7eb; border-radius:8px; padding:5px 10px;">
    {jump_hidden_fields}
    <span class="muted">Trang</span>
    <input type="number" name="page" min="1" max="{recent_total_pages}" value="{page}"
           style="width:64px; text-align:center;" aria-label="Đi đến trang">
    <span class="muted">/ {recent_total_pages}</span>
    <button type="submit" class="btn-secondary btn-small">Đi</button>
  </form>
  <div style="display:flex; gap:8px; align-items:center;">
    {_recent_page_link(page + 1, "Trang sau →", page < recent_total_pages)}
    {_recent_page_link(recent_total_pages, "Cuối »»", page < recent_total_pages)}
  </div>"""

        # Item count ("N mục") moved up to the card header next to "Hiển thị"
        # (2026-09-11) — this footer only needs to render at all once there's
        # actual nav (>1 page) to show.
        recent_pagination_html = f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px; flex-wrap:wrap; gap:8px;">
  {nav_html}
</div>""" if nav_html else ""

    # --- Assemble: only the active tab's card(s) render (2026-09-12, owner
    # request — page had grown to 6 stacked cards, "quá nhiều nội dung").
    if tab == "tables":
        tab_content_html = f"""
<div class="card">
  <h2>📅 Bài đăng thành công theo tuần</h2>
  {weekly_table}
</div>

<div class="card">
  <h2>👥 Bài đăng theo nhóm</h2>
  {group_table}
</div>

<div class="card">
  <h2>📈 Tỉ lệ thành công/thất bại theo hành động</h2>
  {action_table}
</div>"""
    elif tab == "jobs":
        tab_content_html = f"""
<div class="card">
  <h2>📮 Bài đăng</h2>
  {job_cards_html}
  {job_nav_html}
</div>"""
    elif tab == "candidates":
        tab_content_html = f"""
<div class="card">
  <h2>💬 Bình luận</h2>
  {candidate_cards_html}
  {candidate_nav_html}
</div>"""
    else:  # "recent"
        tab_content_html = f"""
<div class="card">
  <div style="display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap;">
    <h2 style="margin:0; white-space:nowrap;">🕒 Hoạt động gần đây</h2>
    <div style="display:flex; gap:10px; align-items:center; white-space:nowrap; flex-shrink:0;">
      {page_size_select_html}
      <span class="muted">{recent_total} mục</span>
    </div>
  </div>
  {recent_table}
  {recent_pagination_html}
</div>"""

    return f"""<div id="reports-content">
{flash}
{err}
{warn}
{filter_html}
{tab_nav_html}
{summary_html}
{tab_content_html}
</div>"""


@router.get("/screenshot")
async def admin_screenshot(path: str, _: None = Depends(_require_auth)):
    """Serves one evidence screenshot (human_bot/screenshots.py) from
    /admin/reports' "Ảnh" column. `path` is the absolute path stored in
    action_log.screenshot_path — resolved and checked against
    SCREENSHOTS_ROOT before ever touching the filesystem, so this can
    never be used to read an arbitrary file elsewhere on disk via a
    crafted `path` query param."""
    target = Path(path).resolve()
    root = screenshots.SCREENSHOTS_ROOT.resolve()
    if target != root and root not in target.parents:
        raise HTTPException(status_code=404, detail="Not found")
    if not target.is_file():
        raise HTTPException(status_code=404, detail="Not found")
    return FileResponse(str(target))


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(
    request: Request,
    account_id: str | None = None,
    days: str | None = None,
    page: int = 1,
    page_size: int = _REPORTS_RECENT_PAGE_SIZE,
    job_page: int = 1,
    candidate_page: int = 1,
    tab: str | None = None,
    posted: str | None = None,
    error: str | None = None,
    warning: str | None = None,
    _: None = Depends(_require_auth),
) -> str:
    content = _reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, posted=posted, error=error, warning=warning)
    if _is_htmx(request):
        return content
    return _layout(f"""
<h1>Báo cáo</h1>
<p class="page-desc">Thống kê từ toàn bộ hành động human_bot đã thử thực hiện (thành công lẫn thất bại) — ghi tự động mỗi lần qua human_bot/agent.py's run_task(), không phân biệt đăng thủ công, từ hàng đợi, đặt lịch, hay tự động từ bộ đồng bộ bên B.</p>
{content}
""", active="reports")


def _reports_redirect(account_id: str | None, days: str | None, page: int, **params) -> RedirectResponse:
    from urllib.parse import urlencode
    query = {"account_id": account_id, "days": days, "page": page, **params}
    query = {k: v for k, v in query.items() if v not in (None, "", 0)}
    return RedirectResponse(url=f"/admin/reports?{urlencode(query)}", status_code=303)


@router.post("/reports/repost")
async def reports_repost(request: Request, _: None = Depends(_require_auth)):
    """"Đăng lại" — resubmit a past action_log row as a brand-new task via
    run_task(), fired immediately (same as /admin/schedule's "Đăng ngay").
    Only ever text-only: media_path is never captured in action_log (see
    _repost_button_html's docstring in _reports_content_html), so an
    original post that had an image attached reposts without it."""
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip() or None
    days = str(form.get("days", "")).strip() or None
    try:
        page = int(str(form.get("page", "1")))
    except ValueError:
        page = 1
    try:
        page_size = _clamp_reports_page_size(int(str(form.get("page_size", _REPORTS_RECENT_PAGE_SIZE))))
    except ValueError:
        page_size = _REPORTS_RECENT_PAGE_SIZE
    try:
        job_page = int(str(form.get("job_page", "1")))
    except ValueError:
        job_page = 1
    try:
        candidate_page = int(str(form.get("candidate_page", "1")))
    except ValueError:
        candidate_page = 1
    # Repost buttons only ever render on the "recent" tab (see
    # _repost_button_html) — default there if the field is somehow missing.
    tab = str(form.get("tab", "recent")).strip() or "recent"
    try:
        log_id = int(str(form.get("log_id", "")))
    except ValueError:
        return _reports_redirect(account_id, days, page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error="Thiếu id bản ghi")

    row = db.get_action_log(log_id)
    if row is None:
        err = "Không tìm thấy bản ghi này"
        if _is_htmx(request):
            return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error=err) + _MODAL_CLOSE_OOB)
        return _reports_redirect(account_id, days, page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error=err)
    if row["action"] not in _REPOSTABLE_ACTIONS or row["success"] or not (row["content"] or "").strip():
        err = "Hành động này không thể đăng lại"
        if _is_htmx(request):
            return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error=err) + _MODAL_CLOSE_OOB)
        return _reports_redirect(account_id, days, page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error=err)

    try:
        result = await run_task(TaskRequest(
            action=row["action"],
            account_id=row["account_id"],
            target_url=row["target_url"],
            content=row["content"],
            reasoning=f"repost: từ báo cáo (bản ghi #{log_id})",
            source="manual",
            retry_of_log_id=log_id,
        ))
    except ValueError as exc:
        err = str(exc)
        if _is_htmx(request):
            return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error=err) + _MODAL_CLOSE_OOB)
        return _reports_redirect(account_id, days, page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error=err)

    if result.success:
        msg = "Đã đăng lại."
        if _is_htmx(request):
            return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, posted=msg) + _MODAL_CLOSE_OOB)
        return _reports_redirect(account_id, days, page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, posted=msg)
    if result.message.startswith("rate_limited:"):
        # Same reasoning as /admin/schedule's schedule_fire_now(): firing
        # too soon (or hitting a hard per-day/per-hour count cap) after
        # this account's last action of the same type isn't a real
        # failure of the repost — it's the rate-limiter doing its job.
        # Owner asked (2026-09-11) that this stop being shown as a red
        # "Đăng lại thất bại" error; rate_limit_wait_message()/
        # daily_limits.hard_cap_message() give a human-readable explanation
        # (with a reschedule suggestion for the hard-cap case) when
        # possible, falling back to the raw reason otherwise.
        from human_bot import daily_limits
        from human_bot.agent import rate_limit_bucket_for
        from human_bot.safety import rate_limit_wait_message
        account = get_all_accounts().get(row["account_id"])
        bucket = rate_limit_bucket_for(row["action"])
        warning = None
        if account and bucket:
            warning = rate_limit_wait_message(account, bucket) or daily_limits.hard_cap_message(account, bucket)
        warning = warning or result.message
        if _is_htmx(request):
            return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, warning=warning) + _MODAL_CLOSE_OOB)
        return _reports_redirect(account_id, days, page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, warning=warning)
    err = f"Đăng lại thất bại: {result.message}"
    if _is_htmx(request):
        return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error=err) + _MODAL_CLOSE_OOB)
    return _reports_redirect(account_id, days, page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error=err)


@router.get("/reports/repost-choice", response_class=HTMLResponse)
async def reports_repost_choice(
    log_id: int,
    account_id: str | None = None,
    days: str | None = None,
    page: int = 1,
    page_size: int = _REPORTS_RECENT_PAGE_SIZE,
    job_page: int = 1,
    candidate_page: int = 1,
    tab: str = "recent",
    _: None = Depends(_require_auth),
) -> str:
    """Opens the 3-way "Đăng lại" choice modal (owner request 2026-09-12)
    — hx-target="#modal-root" from _repost_choice_button_html()."""
    row = db.get_action_log(log_id)
    if row is None or row["action"] not in _REPOSTABLE_ACTIONS or row["success"] or not (row["content"] or "").strip():
        return ""
    return _repost_choice_modal_html(
        row, account_id=account_id, days=days, page=page, page_size=_clamp_reports_page_size(page_size),
        job_page=job_page, candidate_page=candidate_page, tab=_clamp_reports_tab(tab),
    )


@router.get("/reports/reschedule-suggest", response_class=HTMLResponse)
async def reports_reschedule_suggest(
    log_id: int,
    account_id: str | None = None,
    days: str | None = None,
    page: int = 1,
    page_size: int = _REPORTS_RECENT_PAGE_SIZE,
    job_page: int = 1,
    candidate_page: int = 1,
    tab: str = "recent",
    _: None = Depends(_require_auth),
) -> str:
    """Step 1 of "Lên lịch lại" — computes and shows the suggested slot
    (_suggest_reschedule_at()); admin confirms via
    reports_reschedule_confirm() below before anything is actually added
    to the schedule."""
    row = db.get_action_log(log_id)
    if row is None or row["action"] not in _REPOSTABLE_ACTIONS or row["success"] or not (row["content"] or "").strip():
        return ""
    account = get_all_accounts().get(row["account_id"])
    if account is None:
        return (
            '<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">'
            '<div class="modal-box"><p class="error">⚠️ Không tìm thấy tài khoản này.</p></div></div>'
        )
    suggested = _suggest_reschedule_at(account, row["action"])
    page_size = _clamp_reports_page_size(page_size)
    tab = _clamp_reports_tab(tab)
    filter_fields = (
        f'<input type="hidden" name="account_id" value="{html.escape(account_id or "")}">'
        f'<input type="hidden" name="days" value="{html.escape(days or "")}">'
        f'<input type="hidden" name="page" value="{page}">'
        f'<input type="hidden" name="page_size" value="{page_size}">'
        f'<input type="hidden" name="job_page" value="{job_page}">'
        f'<input type="hidden" name="candidate_page" value="{candidate_page}">'
        f'<input type="hidden" name="tab" value="{html.escape(tab)}">'
        f'<input type="hidden" name="log_id" value="{row["id"]}">'
        f'<input type="hidden" name="scheduled_at" value="{suggested.isoformat()}">'
    )
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>🔄 Lên lịch lại</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    <p>Giờ đăng gợi ý: <b>{_local_dt_html(suggested.isoformat())}</b></p>
    <p class="muted">Đã tính theo giới hạn số lượng/ngày, khoảng cách tối thiểu với lần đăng gần nhất, và giờ yên tĩnh đang cấu hình. Bấm Xác nhận để thêm vào lịch (xem/sửa lại ở /admin/schedule), hoặc Huỷ để tự chọn giờ khác qua "Đặt lịch".</p>
    <div class="form-actions">
      <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
      <form method="post" action="/admin/reports/reschedule-confirm"
            hx-post="/admin/reports/reschedule-confirm" hx-target="#reports-content" hx-swap="outerHTML" style="display:inline;">
        {filter_fields}
        <button type="submit">✅ Xác nhận</button>
      </form>
    </div>
  </div>
</div>"""


@router.post("/reports/reschedule-confirm")
async def reports_reschedule_confirm(request: Request, _: None = Depends(_require_auth)):
    """"Lên lịch lại" step 2 — creates the actual ScheduledTask at the
    admin-confirmed slot (schedule_store, same as any other pending task —
    reviewable/editable/cancellable at /admin/schedule before it fires).
    Unlike reports_repost()'s "Đăng ngay" (which deliberately drops job/
    candidate provenance — existing design, not changed here), this DOES
    carry source_kind/source_id/job_data-or-candidate_data forward, since
    the new task is a legitimate continuation of the same job/candidate —
    so it shows up correctly grouped in "Bài đăng"/"Bình luận" once it
    fires."""
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip() or None
    days = str(form.get("days", "")).strip() or None
    try:
        page = int(str(form.get("page", "1")))
    except ValueError:
        page = 1
    try:
        page_size = _clamp_reports_page_size(int(str(form.get("page_size", _REPORTS_RECENT_PAGE_SIZE))))
    except ValueError:
        page_size = _REPORTS_RECENT_PAGE_SIZE
    try:
        job_page = int(str(form.get("job_page", "1")))
    except ValueError:
        job_page = 1
    try:
        candidate_page = int(str(form.get("candidate_page", "1")))
    except ValueError:
        candidate_page = 1
    tab = str(form.get("tab", "recent")).strip() or "recent"
    try:
        log_id = int(str(form.get("log_id", "")))
    except ValueError:
        return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error="Thiếu id bản ghi") + _MODAL_CLOSE_OOB)

    row = db.get_action_log(log_id)
    if row is None or row["action"] not in _REPOSTABLE_ACTIONS or row["success"] or not (row["content"] or "").strip():
        err = "Bản ghi này không thể lên lịch lại"
        return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, error=err) + _MODAL_CLOSE_OOB)

    scheduled_at_raw = str(form.get("scheduled_at", "")).strip()
    try:
        scheduled_at = datetime.fromisoformat(scheduled_at_raw.replace("Z", "+00:00"))
    except ValueError:
        scheduled_at = datetime.now(timezone.utc)
    if scheduled_at.tzinfo is None:
        scheduled_at = scheduled_at.replace(tzinfo=timezone.utc)

    source_kind = row["source_kind"] if "source_kind" in row.keys() and row["source_kind"] else ""
    source_id = row["source_id"] if "source_id" in row.keys() and row["source_id"] else ""
    raw_job_data = row["job_data"] if "job_data" in row.keys() else None
    parsed_data = None
    if raw_job_data:
        try:
            parsed_data = json.loads(raw_job_data)
        except (TypeError, ValueError):
            parsed_data = None

    task = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
        action=row["action"],
        account_id=row["account_id"],
        scheduled_at=scheduled_at.isoformat(),
        content=row["content"],
        target_url=row["target_url"],
        reasoning=f"reschedule: từ báo cáo (bản ghi #{log_id})",
        source_kind=source_kind,
        source_id=source_id,
        job_data=parsed_data if source_kind == "job" else None,
        candidate_data=parsed_data if source_kind == "candidate" else None,
        retry_of_log_id=log_id,
    )
    schedule_store.add(task)
    msg = "Đã thêm vào lịch — xem/sửa ở /admin/schedule."
    return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, posted=msg) + _MODAL_CLOSE_OOB)
