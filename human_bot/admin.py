"""
Purpose of this file / Muc dich cua file nay:
EN: Local-only web admin UI, mounted into human_bot/service.py's FastAPI
app under /admin. Two things it replaces: (1) editing HUMAN_TYPING_* values
in .env and restarting the process — now a form that writes
runtime_config.json and takes effect on the very next post; (2) typing
post content as a terminal command-line argument — now a textarea. This page has real
Facebook-posting power (it calls the exact same run_task() as the /tasks
API n8n uses), so it is protected by a real session-based login (added
2026-09-24, see _require_login()/_require_admin_role() below) whenever
ADMIN_USERNAME and ADMIN_PASSWORD are set in .env — a single ADMIN account
plus up to 4 MOD accounts (managed at /admin/mod-users, ADMIN-only; MOD has
full access everywhere else) — and should never be exposed to the
public internet — see docs/architecture.md.
VI: Giao dien quan tri web, chi dung noi bo, duoc gan vao ung dung FastAPI
cua human_bot/service.py duoi duong dan /admin. No thay the hai viec:
(1) sua cac gia tri HUMAN_TYPING_* trong .env roi khoi dong lai tien
trinh — gio la mot form ghi vao runtime_config.json va co hieu luc ngay
tu lan dang bai tiep theo; (2) go noi dung bai dang truc tiep trong tham
so dong lenh terminal — gio la mot o textarea. Trang nay co quyen dang bai that len Facebook (no
goi dung ham run_task() giong het API /tasks ma n8n dung), nen duoc bao
ve bang dang nhap that (session that, tu 2026-09-24) khi ADMIN_USERNAME
va ADMIN_PASSWORD duoc dat trong .env — 1 tai khoan ADMIN duy nhat cong
toi da 4 tai khoan MOD (quan ly o /admin/mod-users, chi ADMIN vao duoc;
MOD co toan quyen o moi trang khac) — va khong duoc phep mo ra internet
cong khai — xem docs/architecture.md.

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
import logging
import os
import random
import re
import secrets
import shlex
import sqlite3
from datetime import datetime, timedelta, timezone
from typing import Any, get_type_hints

from fastapi import APIRouter, Depends, HTTPException, Request, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from pathlib import Path

from human_bot import bootstrap_login_sessions, browser_pool, content_strategist, db, failure_info, schedule_store, screenshots
from human_bot.agent import TaskRequest, run_task
from human_bot.config import (
    ACCOUNT_AGE_TIERS,
    AccountConfig,
    AccountStatus,
    GroupRef,
    RateLimits,
    PAGE_MODE_AUTO,
    PAGE_MODE_OWN_SESSION,
    PAGE_MODE_OWNER_SESSION,
    PAGE_SESSION_MODES,
    get_all_accounts,
    normalize_name,
    new_group_id,
    pages_of,
)
from human_bot.data_sync import (
    apply_quiet_hours,
    get_all_sync_statuses,
    _format_attr,
    _pick_groups_for_job,
    _last_scheduled_time_per_group,
    _CANDIDATE_REPLY_TEMPLATES_DEFAULT,
)
from human_bot.content_strategist import (
    _JOB_POST_OPENERS_DEFAULT,
    _CONTACT_CTA_DEFAULT,
    _MISSING_INFO_SUFFIXES_DEFAULT,
    _VISA_TYPE_NAMES_DEFAULT,
    _join_list_or_str,
)
from human_bot.data_sync_config import DataSyncConfig
from human_bot.scheduling_config import SchedulingConfig
from human_bot.media import MediaConfig
from human_bot import telegram_notify
from human_bot.telegram_config import TelegramConfig
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
    EDITABLE_TELEGRAM_FIELDS,
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
    get_telegram_overrides,
    save_telegram_overrides,
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
    set_page_session_mode,
    delete_registered_account,
    set_account_disabled,
    set_account_paused,
    set_account_removed,
    resume_account,
    get_disabled_info,
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
    get_sponsored_only_account_ids,
    set_account_sponsored_only,
    get_retention_config,
    save_retention_overrides,
    get_secrets_config,
    save_secrets_overrides,
    get_active_ai_provider_config,
    get_job_post_openers,
    save_job_post_openers,
    reset_job_post_openers,
    get_contact_cta,
    save_contact_cta,
    reset_contact_cta,
    get_missing_info_suffixes,
    save_missing_info_suffixes,
    reset_missing_info_suffixes,
    get_candidate_reply_templates,
    save_candidate_reply_templates,
    reset_candidate_reply_templates,
    get_visa_type_names,
    save_visa_type_names,
    reset_visa_type_names,
    add_mod_user,
    delete_mod_user,
    get_mod_user,
    get_mod_users,
    resolve_login,
    update_mod_user_password,
    add_telegram_recipient,
    delete_telegram_recipient,
    get_telegram_recipient,
    get_telegram_recipients,
    update_telegram_recipient_label,
)
from human_bot.safety_cooldown_config import SafetyCooldownConfig

router = APIRouter(prefix="/admin", tags=["admin"])
logger = logging.getLogger("human_bot.admin")

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


def _sponsor_badge_html(task) -> str:
    """Extra tag next to _action_badge_html() for a job-sourced task whose
    job carried a sponsored_by value — data_sync.py stashes it in
    task.job_data (see that field's own docstring: "stashed purely for
    /admin/schedule + reports traceability... not read by any scheduling
    logic itself"). Owner request 2026-09-25: make a sponsored (paid) post
    visually distinguishable at a glance from an ordinary one, right next
    to the action badge, in both "Chờ đăng" and "Task quá hạn". Empty
    string for anything else (candidate-sourced comment tasks only ever
    carry candidate_data, never job_data)."""
    if not (task.job_data and task.job_data.get("sponsored_by")):
        return ""
    return (
        ' <span class="inline-flex items-center gap-1 text-xs font-semibold '
        'px-2.5 py-0.5 rounded-full bg-amber-100 text-amber-700">💰 Sponsor</span>'
    )


def _account_label(account_id: str, accounts: dict | None = None) -> str:
    """"<Tên hiển thị> (<account_id>)" for a known account, or the bare
    id if it's somehow not registered — never crashes a page render over
    a dangling account_id in old data."""
    accounts = accounts if accounts is not None else get_all_accounts()
    account = accounts.get(account_id)
    if not account:
        return account_id
    # 📄 marks an account that runs as a Facebook Page, so it is not mistaken
    # for a personal account in pickers and headings (2026-10-31).
    return f"{'📄 ' if getattr(account, 'page_name', '') else ''}{account.display_name} ({account_id})"


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
    "daily_summary_enabled",
}

# Pulled out of DataSyncConfig's usual card into their own "🤖 AI" tab in
# /admin/config, next to the API key card. They are still DataSyncConfig fields, but they SAVE on their own, the
# moment they are flipped (config_ai_toggle(), a read-merge-write of the data_sync section) — and the page-wide
# "Lưu cấu hình" (config_save) carries their stored values over instead of reading them from the page.
_AI_TOGGLE_FIELDS = {"job_post_ai_enabled", "candidate_reply_ai_enabled"}

_SCHEDULING_LABELS: dict[str, str] = {
    "auto_fire_enabled": "Tự động đăng khi đến giờ",
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
    "job_min_confidence": "Độ tin cậy tối thiểu để tự lên lịch đăng tin tuyển dụng (0–1)",
    "max_overflow_business_days": "Số ngày nghiệp vụ được phép tràn khi hết hạn mức hôm nay",
    "max_cursor_holdback_days": "Số ngày tối đa giữ lại một tin/ứng viên bị hoãn mãi",
    "cache_retention_days": "Số ngày giữ lại cache chống trùng trước khi dọn",
    "job_post_ai_enabled": "Dùng AI soạn lại bài tin tuyển dụng đăng nhóm",
    "candidate_reply_ai_enabled": "Dùng AI để soạn câu reply comment bài viết ứng viên",
}

# The help line under the 2 AI toggles above (_config_rows_html() shows it as the row's explanation): what flipping
# one actually changes at posting time.
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

# One plain-language line under a setting: what flipping / changing it does. Keyed "<section prefix>__<field>" (the
# bare field names repeat across sections: every section has an "enabled"). Shown instead of the technical
# "mặc định · key" line the rows used to carry (the key is now the label's tooltip).
_FIELD_HELP: dict[str, str] = {
    "scheduling__auto_fire_enabled": (
        "Tắt = chỉ đặt lịch: bài đến giờ phải bấm “🚀 Đăng ngay” ở Lịch đăng. "
        "Áp dụng cho mọi bài — tự động từ bên B lẫn soạn tay ở Đăng bài."
    ),
    "data_sync__job_min_confidence": (
        "Tin thấp hơn mức này vẫn được soạn sẵn bằng template nhưng chờ bạn duyệt ở Lịch đăng → Chờ duyệt, không tự lên lịch."
    ),
    "data_sync__max_overflow_business_days": (
        "Tin sponsored cần chỗ trống gần — xem thêm tuỳ chọn “Chỉ đăng sponsored” của từng tài khoản ở Tài khoản."
    ),
    "data_sync__max_cursor_holdback_days": (
        "Mốc đồng bộ bị giữ lùi vì một tin hoặc ứng viên cứ bị hoãn; quá số ngày này thì bỏ qua nó thay vì quét lại toàn bộ lịch sử."
    ),
    "media__attach_random_meme_default": (
        "Lấy ngẫu nhiên từ thư mục media/memes/. Ảnh do bên B cung cấp cho bài luôn được dùng trước."
    ),
    "safety_cooldown__cooldown_days": (
        "Chia đôi thành 2 tuần: tuần 1 chạy ở mức sàn bên dưới cho mọi tier, tuần 2 nhích lên một tier thấp hơn; hết hạn thì tự trở về giới hạn cũ."
    ),
    "telegram__enabled": (
        "Cần có token của bot Telegram trong .env và người nhận ở Tài khoản → Tài khoản Telegram. "
        "Tắt ở đây để im lặng ngay, không cần sửa .env hay khởi động lại."
    ),
    "telegram__daily_summary_hour_jst": (
        "Ngày nghiệp vụ kết thúc lúc 2h sáng nên không đặt sớm hơn; mặc định 6 = 6h sáng, sau khung giờ yên lặng."
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
      <div class="field-label">API key ({html.escape(str(p["label"]))})<div class="field-key">bắt buộc phải nhập khi lưu cho nhà cung cấp đang chọn — muốn xoá hẳn, dùng nút "Xoá key" bên cạnh{env_hint}</div></div>
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
  <p class="page-desc">Key và model nhập ở đây được <b>ưu tiên hơn</b> file <code>.env</code>.</p>
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


# --- Content library tab ("Kho nội dung", 2026-10-01) -----------------------
#
# Lets an admin edit, from the web UI, the wording pools
# content_strategist.py/data_sync.py used to only read from hardcoded
# constants (owner incident that prompted this: 2 small wording tweaks in
# one session both required a code change + test run + commit + deploy).
# Standalone htmx card (not a nested `<form>`, same reason as
# _ai_provider_card_html above — /admin/config is already one big `<form>`).
# Repeatable rows reuse initRepeatableBlocks (generalized above to handle
# N pre-rendered rows, not just /admin/post's always-1-blank-row case).

def _repeatable_rows_html(blocks_html: str, add_label: str) -> str:
    return f"""
<div data-repeatable-blocks style="margin-top:8px;">
  <div data-block-list>{blocks_html}</div>
  <button type="button" class="btn-secondary btn-small" data-add-block style="margin-top:8px;">{html.escape(add_label)}</button>
</div>"""


def _text_row_block_html(field_name: str, idx: int, value: str, placeholder: str = "") -> str:
    return f"""
<div class="content-block" data-block style="display:flex; flex-wrap:wrap; gap:8px; align-items:center; margin-bottom:8px;">
  <input type="text" name="{field_name}_{idx}" value="{html.escape(value)}" placeholder="{html.escape(placeholder)}" style="flex:1 1 240px; min-width:160px;">
  <button type="button" class="btn-secondary btn-small" data-remove-block style="flex-shrink:0;">Xoá</button>
</div>"""


def _textarea_row_block_html(field_name: str, idx: int, value: str, placeholder: str = "") -> str:
    return f"""
<div class="content-block" data-block style="display:flex; flex-wrap:wrap; gap:8px; align-items:flex-start; margin-bottom:8px;">
  <textarea name="{field_name}_{idx}" rows="2" placeholder="{html.escape(placeholder)}" style="flex:1 1 240px; min-width:160px; min-height:64px; font-family:inherit;">{html.escape(value)}</textarea>
  <button type="button" class="btn-secondary btn-small" data-remove-block style="flex-shrink:0;">Xoá</button>
</div>"""


def _opener_row_block_html(idx: int, text: str, visa_restrictions: list[str], visa_names: dict[str, list[str]]) -> str:
    # Multi-select (2026-10-01, owner's request): no "Không giới hạn"
    # option — selecting NOTHING means unrestricted, same as an empty
    # `visa_restrictions` list; selecting 1+ codes means "any ONE of
    # these". If a restriction references a code no longer in "Tên gọi
    # visa" (deleted after being selected), keep it as an extra option
    # instead of letting it silently drop off the rendered <select> — a
    # native <select> can only submit a value that's actually one of its
    # own <option>s, so losing this would silently un-restrict the opener
    # from that code the next time this form is saved.
    all_codes = list(visa_names.keys())
    for code in visa_restrictions:
        if code not in all_codes:
            all_codes.append(code)
    options = []
    for code in all_codes:
        selected = " selected" if code in visa_restrictions else ""
        # First configured display name (if any) alongside the raw code —
        # a bare lowercase code list ("gijinkoku", "tokutei"...) reads a
        # lot less friendly than "Kỹ Sư (gijinkoku)".
        names = visa_names.get(code)
        label = f"{names[0]} ({code})" if names else code
        options.append(f'<option value="{html.escape(code)}"{selected}>{html.escape(label)}</option>')
    # Owner-reported 2026-10-01: a plain <select multiple> listbox "nhìn
    # xấu" (looks dated/ugly) and silently required knowing to hold Ctrl/
    # Cmd to pick more than one. Rendered instead as this app's existing
    # single-line "cselect" dropdown look (same CSS classes every other
    # dropdown here uses), generalized to a multi-select variant
    # (initCSelectMulti in the page script below) — a real <select
    # multiple name="opener_visa_{idx}"> still backs it for the form
    # submit, just visually hidden; clicking an option in the panel
    # toggles it and keeps the panel open, no modifier key needed.
    trigger_label = ", ".join(
        (visa_names.get(c) or [c])[0] for c in visa_restrictions
    ) if visa_restrictions else "Không giới hạn"
    cselect_html = f"""<div class="cselect" data-cselect-multi data-cselect-empty-label="Không giới hạn" style="min-width:160px; max-width:200px;">
  <select name="opener_visa_{idx}" multiple class="cselect-native">{"".join(options)}</select>
  <button type="button" class="cselect-trigger"><span class="cselect-trigger-label">{html.escape(trigger_label)}</span><span class="chevron">▾</span></button>
  <div class="cselect-panel"></div>
</div>"""
    return f"""
<div class="content-block" data-block style="display:flex; flex-wrap:wrap; gap:8px; align-items:flex-start; margin-bottom:8px;">
  <input type="text" name="opener_text_{idx}" value="{html.escape(text)}" placeholder="VD: TÌM NHÂN SỰ" style="flex:1 1 240px; min-width:160px;">
  <div style="flex:0 1 200px; max-width:200px;">
    {cselect_html}
    <div class="field-key" style="margin-top:2px;">Giới hạn visa (tuỳ chọn) — không chọn gì = mọi visa.</div>
  </div>
  <button type="button" class="btn-secondary btn-small" data-remove-block style="flex-shrink:0;">Xoá</button>
</div>"""


def _visa_name_row_block_html(idx: int, code: str, names: list[str]) -> str:
    return f"""
<div class="content-block" data-block style="display:flex; flex-wrap:wrap; gap:8px; align-items:flex-start; margin-bottom:8px;">
  <input type="text" name="visa_code_{idx}" value="{html.escape(code)}" placeholder="VD: gijinkoku" style="flex:0 0 160px; font-family:monospace;">
  <textarea name="visa_names_{idx}" rows="2" placeholder="Mỗi dòng 1 cách gọi" style="flex:1 1 240px; min-width:160px;">{html.escape(chr(10).join(names))}</textarea>
  <button type="button" class="btn-secondary btn-small" data-remove-block style="flex-shrink:0;">Xoá</button>
</div>"""


def _content_library_reset_btn_html(list_name: str, label: str) -> str:
    confirm = html.escape(f'Khôi phục "{label}" về mặc định gốc trong code? Mất mọi chỉnh sửa đã lưu cho riêng danh sách này.')
    return (
        f'<button type="button" class="btn-secondary btn-small" '
        f'hx-post="/admin/config/content-library/reset" hx-vals=\'{{"list_name": "{list_name}"}}\' '
        f'hx-target="#content-library-card" hx-swap="outerHTML" '
        f'hx-confirm="{confirm}">Khôi phục mặc định</button>'
    )


def _content_library_section_html(
    title: str, count: int, desc_html: str, body_html: str, reset_btn_html: str, *, open_by_default: bool,
) -> str:
    """One collapsible <details> block per list — 5 sections (up to ~40
    rows total between them) is a lot to scroll past at once if every row
    renders expanded; <details> is the same no-JS disclosure pattern
    already used elsewhere in this file (e.g. job-report cards), so
    collapsed sections still work with 0 extra JS."""
    open_attr = " open" if open_by_default else ""
    return f"""
<details{open_attr} style="border:1px solid #e5e7eb; border-radius:8px; padding:10px 14px; margin-bottom:14px;">
  <summary style="cursor:pointer; font-weight:600;">{html.escape(title)} <span class="badge">{count}</span></summary>
  <div style="margin-top:10px;">
    {desc_html}
    {body_html}
    {reset_btn_html}
  </div>
</details>"""


def _content_library_card_html(
    openers: list[dict], cta: list[str], suffixes: list[str],
    reply_templates: list[str], visa_names: dict[str, list[str]], flash: str = "", *, expand_all: bool = False,
) -> str:
    opener_blocks = "".join(
        _opener_row_block_html(i, o.get("text", ""), o.get("visa_restrictions") or [], visa_names)
        for i, o in enumerate(openers)
    ) or _opener_row_block_html(0, "", [], visa_names)
    cta_blocks = "".join(_text_row_block_html("cta", i, v) for i, v in enumerate(cta)) \
        or _text_row_block_html("cta", 0, "")
    suffix_blocks = "".join(_text_row_block_html("suffix", i, v) for i, v in enumerate(suffixes)) \
        or _text_row_block_html("suffix", 0, "")
    reply_blocks = "".join(_textarea_row_block_html("reply_template", i, v) for i, v in enumerate(reply_templates)) \
        or _textarea_row_block_html("reply_template", 0, "")
    visa_blocks = "".join(_visa_name_row_block_html(i, code, names) for i, (code, names) in enumerate(visa_names.items())) \
        or _visa_name_row_block_html(0, "", [])

    visa_section = _content_library_section_html(
        "Tên gọi các loại visa", len(visa_names),
        '<p class="page-desc">Mỗi mã visa (ví dụ gijinkoku, tokutei — viết đúng như bên B gửi sang) có thể có nhiều cách gọi; bot chọn ngẫu nhiên một cách mỗi lần đăng. Mã chưa có trong danh sách vẫn đăng được. <b>Vừa thêm mã mới thì bấm “Lưu Kho nội dung” một lần</b> để mã đó hiện ra ở “Giới hạn visa” của mục “Câu mở đầu” bên dưới.</p>',
        _repeatable_rows_html(visa_blocks, "+ Thêm mã visa"),
        _content_library_reset_btn_html("visa_names", "Tên gọi các loại visa"),
        open_by_default=expand_all,  # bulkiest/least-often-touched section — tucked away by default
    )
    opener_section = _content_library_section_html(
        "Câu mở đầu bài đăng nhóm", len(openers),
        '<p class="page-desc">Mỗi bài chọn một câu, xoay vòng theo nhóm. Chọn “Giới hạn visa” để chỉ dùng câu đó cho tin thuộc loại visa đã chọn; không chọn gì nghĩa là dùng cho mọi tin. Cần có ít nhất một câu không giới hạn.</p>',
        _repeatable_rows_html(opener_blocks, "+ Thêm câu mở đầu"),
        _content_library_reset_btn_html("openers", "Câu mở đầu bài đăng nhóm"),
        open_by_default=True,
    )
    cta_section = _content_library_section_html(
        "Câu mời nhắn tin (CTA)", len(cta), "",
        _repeatable_rows_html(cta_blocks, "+ Thêm câu mời nhắn tin"),
        _content_library_reset_btn_html("cta", "Câu mời nhắn tin"),
        open_by_default=True,
    )
    suffix_section = _content_library_section_html(
        "Câu khi thiếu visa/lương", len(suffixes), "",
        _repeatable_rows_html(suffix_blocks, "+ Thêm câu"),
        _content_library_reset_btn_html("suffixes", "Câu khi thiếu visa/lương"),
        open_by_default=True,
    )
    reply_section = _content_library_section_html(
        "Mẫu bình luận trả lời ứng viên", len(reply_templates),
        '<p class="page-desc">Dùng được {field} (ngành ứng viên muốn làm) và {region_clause} (khu vực, có thể rỗng) — không dùng dấu {} nào khác, hệ thống sẽ từ chối lưu nếu sai cú pháp.</p>',
        _repeatable_rows_html(reply_blocks, "+ Thêm mẫu bình luận"),
        _content_library_reset_btn_html("reply_templates", "Mẫu bình luận trả lời ứng viên"),
        open_by_default=True,
    )

    return f"""
<div class="card" id="content-library-card">
  <h2>📝 Kho nội dung</h2>
  <p class="page-desc">Câu chữ bot dùng khi tự soạn bài đăng nhóm và trả lời ứng viên. Lưu xong là dùng ngay cho lần đăng sau.</p>
  {flash}
  {visa_section}
  {opener_section}
  {cta_section}
  {suffix_section}
  {reply_section}
  <div class="form-actions" style="margin-top:20px;">
    <button type="button" hx-post="/admin/config/content-library" hx-include="#content-library-card"
      hx-target="#content-library-card" hx-swap="outerHTML">Lưu Kho nội dung</button>
  </div>
</div>"""


def _indices_for_prefix(form, prefix: str) -> list[str]:
    """Scans submitted form keys like "<prefix>_<i>" (initRepeatableBlocks'
    naming — see post_schedule_groups()'s identical pattern) for whatever
    indices are actually present, sorted numerically — removing a row in
    the browser never desyncs this from what the server expects."""
    return sorted(
        {key[len(prefix) + 1:] for key in form.keys() if key.startswith(prefix + "_")},
        key=lambda s: int(s) if s.isdigit() else 0,
    )


def _parse_content_library_form(form) -> tuple[list[dict], list[str], list[str], list[str], dict[str, list[str]], list[str]]:
    """Parses the raw submitted fields into the 5 lists this tab edits,
    dropping blank rows. Returns (openers, cta, suffixes, reply_templates,
    visa_names, extra_errors) — extra_errors covers the one row-level
    validation that doesn't fit the "just drop it" pattern (a visa code
    typed with no names given at all, see _visa_name_row_block_html)."""
    openers = []
    for idx in _indices_for_prefix(form, "opener_text"):
        text = str(form.get(f"opener_text_{idx}", "")).strip()
        if not text:
            continue
        # Multi-select (2026-10-01) — a native <select multiple> submits
        # one value per selected <option> under the SAME field name.
        visa_codes = [str(v).strip().lower() for v in form.getlist(f"opener_visa_{idx}") if str(v).strip()]
        openers.append({"text": text, "visa_restrictions": visa_codes})

    cta = [v for idx in _indices_for_prefix(form, "cta")
           if (v := str(form.get(f"cta_{idx}", "")).strip())]
    suffixes = [v for idx in _indices_for_prefix(form, "suffix")
                if (v := str(form.get(f"suffix_{idx}", "")).strip())]
    reply_templates = [v for idx in _indices_for_prefix(form, "reply_template")
                        if (v := str(form.get(f"reply_template_{idx}", "")).strip())]

    visa_names: dict[str, list[str]] = {}
    extra_errors: list[str] = []
    for idx in _indices_for_prefix(form, "visa_code"):
        code = str(form.get(f"visa_code_{idx}", "")).strip().lower()
        if not code:
            continue
        names = [n.strip() for n in str(form.get(f"visa_names_{idx}", "")).splitlines() if n.strip()]
        if not names:
            extra_errors.append(f'Mã visa "{code}" chưa có cách gọi nào — xoá dòng này hoặc thêm ít nhất 1 cách gọi.')
            continue
        if code in visa_names:
            # Silently letting the later row win would lose the earlier
            # row's names with no indication why — reject instead so the
            # admin notices and merges/renames by hand.
            extra_errors.append(f'Mã visa "{code}" bị lặp lại ở nhiều dòng — gộp lại thành 1 dòng hoặc đổi tên.')
            continue
        visa_names[code] = names

    return openers, cta, suffixes, reply_templates, visa_names, extra_errors


def _validate_content_library(
    openers: list[dict], cta: list[str], suffixes: list[str], reply_templates: list[str],
    visa_names: dict[str, list[str]], extra_errors: list[str],
) -> list[str]:
    errors = list(extra_errors)
    if not openers:
        errors.append("Câu mở đầu bài đăng nhóm: cần ít nhất 1 dòng.")
    elif not any(not o["visa_restrictions"] for o in openers):
        errors.append(
            "Câu mở đầu bài đăng nhóm: cần ít nhất 1 dòng KHÔNG giới hạn visa — "
            "nếu không, 1 tin thiếu/khác visa sẽ không còn câu mở đầu nào dùng được."
        )
    if not cta:
        errors.append("Câu mời nhắn tin: cần ít nhất 1 dòng.")
    if not suffixes:
        errors.append("Câu khi thiếu visa/lương: cần ít nhất 1 dòng.")
    if not reply_templates:
        errors.append("Mẫu bình luận trả lời ứng viên: cần ít nhất 1 dòng.")
    else:
        for t in reply_templates:
            try:
                t.format(field="x", region_clause="")
            except (KeyError, IndexError, ValueError) as exc:
                errors.append(
                    f'Mẫu bình luận "{t}" dùng sai placeholder ({exc}) — chỉ được dùng {{field}}/{{region_clause}}.'
                )
    if not visa_names:
        # Not a crash risk on its own (_visa_line() falls back to the raw
        # code capitalized when the dict is empty) — required anyway so
        # "xoá hết rồi lưu" gives a clear error instead of silently
        # reverting to the code default next render (an empty dict isn't
        # a usable override, same rule as the other 4 lists) with no
        # indication why the admin's edit appeared to do nothing.
        errors.append("Tên gọi các loại visa: cần ít nhất 1 mã.")
    return errors


_MEDIA_LABELS: dict[str, str] = {
    "attach_random_meme_default": "Tự động đính kèm ảnh ngẫu nhiên khi bài chưa có ảnh riêng",
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
    "cooldown_days": "Tổng số ngày hạ nhiệt",
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

_TELEGRAM_LABELS: dict[str, str] = {
    "enabled": "Bật báo cáo / báo động qua Telegram",
    "daily_summary_enabled": "Gửi tóm tắt mỗi ngày về những gì đã làm hôm qua (ngày nghiệp vụ 02:00 → 02:00 JST)",
    "daily_summary_hour_jst": "Giờ gửi tóm tắt (giờ Nhật, 2–23)",
}

_ICONS["telegram"] = "📨"

_CONFIG_SECTIONS.append(
    ("telegram", "telegram", "Báo động Telegram", TelegramConfig, EDITABLE_TELEGRAM_FIELDS,
     _TELEGRAM_LABELS, get_telegram_overrides, save_telegram_overrides)
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
  /* 2026-09-24 fix (real bug, found via screenshot at ~800-1024px width):
     this used a FIXED h-14 (56px) together with flex-wrap. Once the nav +
     user chip no longer fit on one row (happened once "Quản lý MOD" and
     the ADMIN/MOD user chip + logout button were added), the wrapped
     rows were squeezed into that fixed 56px box and overflowed OUTSIDE
     it — and because .topbar has z-10 (its own stacking context) while
     <main> below has no z-index, that overflow visually painted on TOP
     of the page's H1/content instead of pushing it down. min-h instead
     of h lets the sticky bar grow to fit however many rows it wraps to. */
  .topbar-inner { @apply max-w-6xl mx-auto flex items-center gap-4 sm:gap-7 min-h-[56px] py-2 flex-wrap; }
  .brand { @apply font-bold text-base tracking-tight flex items-center gap-2 text-gray-900 no-underline; }
  .brand:hover { @apply no-underline; }
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
  .field-stack .field-label, .fg-label { @apply text-sm text-gray-800 font-medium flex-none min-w-0; }
  .field-stack .field-input { @apply w-full; }

  input[type=text], input[type=url], input[type=search], input[type=number], input[type=password], input[type=datetime-local], textarea, select {
    @apply w-full box-border px-2.5 py-2 text-sm border border-gray-200 rounded-lg bg-white text-gray-900 font-sans;
  }
  input[type=text]:focus, input[type=url]:focus, input[type=search]:focus, input[type=number]:focus, input[type=password]:focus, input[type=datetime-local]:focus, textarea:focus, select:focus {
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

  /* A plain block: these hold a sentence with <strong>/<a>/<code> in it, and as a flex row every inline piece
     became its own column (ragged on a phone). None of them contains a button or form. */
  .flash, .error, .warning { @apply rounded-2xl px-4 py-3 mb-5 text-sm; }
  .flash { @apply bg-emerald-50 border border-emerald-200 text-emerald-700; }
  .error { @apply bg-red-50 border border-red-200 text-red-700; }
  .warning { @apply bg-amber-50 border border-amber-200 text-amber-800; }
  /* Same look as .warning above, but sized/margined for sitting INSIDE a
     .queue-item (per-task banner) rather than at page level. */
  .warning-inline { @apply bg-amber-50 border border-amber-200 text-amber-800 rounded-xl px-3 py-2 mt-2 mb-2 text-sm flex items-center gap-2; }

  .form-actions { @apply mt-2 flex justify-end; }
  /* Owner-reported 2026-10-01 — found the real cause after a server
     restart didn't fix it: `.form-actions`'s own `display:flex` (an
     AUTHOR stylesheet rule) silently overrides the `hidden` attribute's
     implicit `display:none` (just a UA-stylesheet default — author rules
     always win, tie-specificity or not), so `hidden` alone never actually
     hides a `.form-actions` element despite the attribute being correctly
     present in the HTML. Same bug class `.tab-panel[hidden]` below was
     already added for — content-library's `#config-generic-save-actions`
     is the first `.form-actions` that also needs `hidden` to work. */
  .form-actions[hidden] { @apply hidden; }

  .badge { @apply inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full bg-indigo-50 text-indigo-600; }
  .badge-ok { @apply bg-emerald-50 text-emerald-700; }
  .badge-warn { @apply bg-amber-50 text-amber-800; }
  .badge-bad { @apply bg-red-50 text-red-700; }

  /* /admin/accounts list (2026-11-01 redesign): one row per account, a Page nested under its
     owner, one contextual button and a "⋯" menu for the rest. */
  .acct-head { @apply flex flex-wrap items-center justify-between gap-3 mb-3; }
  .acct-count { @apply text-sm font-semibold text-gray-900; }
  .acct-attn { @apply text-sm font-semibold text-amber-700; }
  .acct-list { @apply list-none p-0 m-0; }
  .acct-row { @apply grid items-start gap-x-4 gap-y-2 py-3.5 border-t border-gray-100; grid-template-columns: minmax(0, 1.2fr) minmax(0, 1.3fr) 180px; }
  .acct-row:first-child { @apply border-t-0; }
  .acct-child .acct-who { @apply ml-4 pl-4 border-l-2 border-gray-100; }
  .acct-title { @apply flex flex-wrap items-baseline gap-x-2; }
  .acct-name { @apply font-semibold text-gray-900 no-underline; }
  a.acct-name:hover { @apply text-indigo-600; }
  .acct-aid { @apply text-xs text-gray-400; }
  .acct-meta { @apply mt-1 text-xs text-gray-500; }
  .acct-meta.warn { @apply text-amber-700; }
  .acct-mode { @apply inline-flex items-center gap-1.5 m-0; }
  .acct-note { @apply mt-1 text-xs text-gray-500; word-break: normal; }
  .acct-sess { @apply font-medium; }
  .acct-sess-ok { @apply text-emerald-700; }
  .acct-sess-warn { @apply text-amber-700; }
  .acct-sess-bad { @apply text-red-700; }
  .acct-actions { @apply flex items-center justify-end gap-1.5; }
  .st { @apply inline-block text-xs font-semibold px-2.5 py-0.5 rounded-full; }
  .st-ok { @apply bg-emerald-50 text-emerald-700; }
  .st-off { @apply bg-gray-100 text-gray-600; }
  .st-paused { @apply bg-red-50 text-red-700; }
  details.row-menu { @apply relative; }
  details.row-menu > summary { @apply list-none cursor-pointer select-none w-8 h-8 inline-flex items-center justify-center rounded-lg border border-gray-200 bg-white text-gray-600 text-lg leading-none; }
  details.row-menu > summary::-webkit-details-marker { display: none; }
  details.row-menu > summary:hover, details.row-menu[open] > summary { @apply bg-gray-50 text-gray-900; }
  .row-menu-pop { @apply absolute right-0 top-full mt-1 z-30 bg-white border border-gray-200 rounded-xl shadow-lg p-1.5; width: min(18rem, calc(100vw - 2rem)); }
  .row-menu-pop form { @apply m-0; }
  button.menu-item { @apply block w-full text-left bg-transparent text-gray-900 border-0 rounded-lg px-3 py-2 text-[13px] font-semibold; }
  button.menu-item:hover { @apply bg-gray-50 text-gray-900; }
  button.menu-item small { @apply block text-[11px] font-normal text-gray-500 mt-0.5; }
  button.menu-item.danger { @apply text-red-700; }
  button.menu-item.danger:hover { @apply bg-red-50 text-red-700; }
  .row-menu-sep { @apply border-0 border-t border-gray-100 my-1; }
  .row-menu-info { @apply px-3 pt-1.5 pb-1 text-[11px] text-gray-400; }
  .sync-table tr.sync-child td:first-child { @apply pl-9; }
  .sync-table td { @apply align-top; }
  /* /admin/schedule (2026-11-02): compact rows grouped by day, edit panel opened in place, "⋯" for the rest. */
  .sched-toolbar { @apply flex flex-wrap items-center gap-x-3 gap-y-2 mb-4; }
  .sched-toolbar label { @apply text-xs font-semibold text-gray-500; }
  .sched-toolbar select, .sched-toolbar input[type=date] { @apply w-auto text-sm py-1.5; min-width: 0; }
  .sched-count { @apply ml-auto text-sm font-semibold text-gray-700; }
  .sched-tabs { @apply flex flex-wrap gap-1.5 border-b border-gray-200 mb-5; }
  a.sched-tab { @apply px-3.5 py-2.5 text-sm font-semibold text-gray-500 no-underline border-b-2 border-transparent -mb-px; }
  a.sched-tab:hover { @apply text-gray-900; }
  a.sched-tab.active { @apply text-indigo-600 border-indigo-600; }
  .sched-list { @apply bg-white border border-gray-200 rounded-2xl shadow-sm; }
  .sched-list > :first-child { @apply rounded-t-2xl; }
  .sched-list > :last-child { @apply rounded-b-2xl; }
  .sched-dayhead { @apply px-4 py-2 bg-gray-50 border-b border-gray-100 text-xs font-bold uppercase tracking-wide text-gray-500; }
  .sched-item { @apply border-b border-gray-100 relative; }
  .sched-item:last-child { @apply border-b-0; }
  .sched-line { @apply grid items-center gap-x-3 gap-y-2 px-4 py-3; grid-template-columns: 66px minmax(0, 1fr) auto; }
  .sched-missed .sched-line { grid-template-columns: 22px 76px minmax(0, 1fr) auto; }
  .sched-review .sched-line { grid-template-columns: minmax(0, 1fr) auto; }
  .sched-due, .sched-missed { box-shadow: inset 3px 0 0 #f59e0b; }
  .sched-review { box-shadow: inset 3px 0 0 #8b5cf6; }
  .sched-time { @apply text-sm font-semibold text-gray-900; font-variant-numeric: tabular-nums; }
  .sched-time small { @apply block text-[11px] font-normal text-amber-700 whitespace-nowrap; }
  .sched-title { @apply flex flex-wrap items-center gap-x-2 gap-y-1 text-sm; }
  .sched-target { @apply font-semibold text-gray-900 no-underline; }
  a.sched-target:hover { @apply text-indigo-600; }
  .sched-acct { @apply text-xs text-gray-400; }
  .sched-preview { @apply mt-0.5 text-[13px] text-gray-500; display: -webkit-box; -webkit-line-clamp: 2; -webkit-box-orient: vertical; overflow: hidden; word-break: break-word; }
  .sched-why { @apply mt-1 text-xs text-amber-800 bg-amber-50 border border-amber-200 rounded-lg px-2 py-1; }
  .sched-actions { @apply flex flex-wrap items-center justify-end gap-1.5; }
  .sched-actions form { @apply m-0; }
  .sched-edit { @apply px-4 pb-4; padding-left: 82px; }
  .sched-edit textarea { @apply w-full; min-height: 90px; }
  .sched-edit-row { @apply flex flex-wrap items-center gap-2 mt-2; }
  .sched-check { @apply flex items-center; }
  .sched-help { @apply text-xs text-gray-500 mb-3; }
  .sched-groups { @apply flex flex-wrap gap-3; }
  .sched-group { flex: 1 1 260px; min-width: 0; }
  .sched-group textarea { @apply w-full; min-height: 90px; }
  @media (max-width: 720px) {
    .sched-line, .sched-missed .sched-line { grid-template-columns: minmax(0, 1fr); }
    .sched-actions { justify-content: flex-start; position: relative; }
    .sched-actions details.row-menu { position: static; }
    .sched-actions .row-menu-pop { left: 0; right: auto; }
    .sched-edit { padding-left: 16px; }
  }
  /* Rate-limit modal (2026-11-02): grouped, delays as a pair, the age presets as small chips. */
  .rl-tiers { @apply mb-3; }
  .rl-tier-buttons { @apply flex flex-wrap gap-1.5 mt-1.5; }
  .rl-actions { @apply justify-between items-center gap-2 mt-5 flex-wrap flex-row-reverse; }
  .rl-actions-main { @apply flex gap-2 flex-row-reverse; }
  #rate-limits-body .field-grid > .cfg-group-title:first-child { @apply mt-1; }
  /* Password box with a show / hide button; a single column of labelled fields (login, MOD forms). */
  .pw-field { @apply flex items-stretch gap-2; }
  .pw-field input { @apply flex-1 min-w-0; }
  .pw-toggle { @apply flex-none bg-white text-gray-600 border border-gray-200 px-3 text-base; }
  .pw-toggle:hover { @apply bg-gray-50 text-gray-900; }
  .pw-toggle[aria-pressed="true"] { @apply bg-indigo-50 text-indigo-700 border-indigo-200; }
  .form-col { @apply flex flex-col gap-4; }
  .modal-box .form-col + .form-actions { @apply mt-5; }
  /* /admin/groups (2026-11-02): one row per group — the name, its URL, what it got so far. */
  .grp-line { @apply grid items-center gap-x-3 gap-y-2 px-4 py-3; grid-template-columns: minmax(0, 1fr) auto; }
  .grp-main { @apply min-w-0; }
  .grp-url { @apply text-xs text-gray-400 break-all mt-0.5; }
  .grp-stats { @apply text-xs text-gray-500 mt-0.5; }
  .grp-flag { @apply text-[11px] font-normal text-gray-500 bg-gray-100 rounded-full px-2 py-0.5 cursor-help; }
  .grp-search { @apply flex items-center gap-3 mb-3; }
  .grp-search input { @apply max-w-sm; }
  .sched-target.muted { @apply text-gray-400 font-normal; }
  .sched-item[hidden] { @apply hidden; }
  @media (max-width: 720px) { .grp-line { grid-template-columns: minmax(0, 1fr); } }
  /* /admin/config (2026-11-02): rows that differ from the default, min/max pairs, folded "advanced" groups, sticky save bar. */
  .field-help { @apply text-xs text-gray-500 mt-0.5 leading-relaxed; }
  .field-row.is-changed { box-shadow: inset 3px 0 0 #818cf8; margin-inline: -.625rem; padding-inline: .625rem; }      /* the stripe sits outside; the text stays aligned */
  .reset-wrap { @apply text-xs text-indigo-600; }
  .reset-wrap b { @apply font-semibold; }
  .reset-link { @apply bg-transparent border-0 p-0 ml-1 text-xs font-semibold text-indigo-600 cursor-pointer underline; }
  .reset-link:hover { @apply bg-transparent text-indigo-800; }
  .pair-input { @apply flex items-center gap-2 sm:w-[300px]; }
  .pair-input input { @apply min-w-0; }
  .pair-sep, .pair-unit { @apply text-sm text-gray-500 flex-none; }
  .field-row.pair-bad .pair-input input { @apply border-red-400 bg-red-50; }
  .cfg-group-title { @apply text-xs font-bold uppercase tracking-wide text-gray-500 mt-5 mb-1; }
  .cfg-adv { @apply bg-white border border-gray-200 rounded-2xl shadow-sm mb-5; }
  .cfg-adv > summary { @apply flex flex-wrap items-center gap-x-3 gap-y-1 px-5 py-3.5 cursor-pointer text-base font-semibold text-gray-900; list-style: none; }
  .cfg-adv > summary::-webkit-details-marker { display: none; }
  .cfg-adv > summary::before { content: "▸"; @apply text-gray-400 text-xs; }
  .cfg-adv[open] > summary::before { content: "▾"; }
  .cfg-adv-note { @apply text-xs font-normal text-gray-500 ml-auto; }
  .cfg-adv-body { @apply px-5 pb-2; }
  .cfg-adv-body .card { @apply shadow-none; }
  .cfg-adv-inline { @apply shadow-none border-gray-100 bg-gray-50 mt-5 mb-0; }
  .cfg-adv-inline > summary { @apply text-sm py-2.5; }
  .cfg-adv-inline > .field-grid { @apply px-5 pb-3; }
  .form-actions.savebar { @apply sticky bottom-0 z-[5] items-center justify-between gap-3 mt-4 px-4 py-3 bg-white border border-gray-200 rounded-2xl shadow-md; }
  .form-actions.savebar[hidden] { @apply hidden; }
  .savebar-note { @apply text-sm text-gray-500; }
  .savebar-note.is-dirty { @apply text-amber-700 font-semibold; }
  .savebar-buttons { @apply flex items-center gap-2; }
  @media (max-width: 639px) { .pair-input { @apply w-full; } .cfg-adv-note { @apply ml-0 basis-full; } }
  /* /admin/reports (2026-11-02): bars (one accent colour, value at the tip), the same row look as Lịch đăng for every attempt. */
  .rep-grid { @apply grid grid-cols-1 items-start gap-5 mb-5 lg:grid-cols-2; }
  .rep-grid > .card { @apply mb-0; }
  .rep-grid > .card:only-child { @apply lg:col-span-2; }
  .bars { @apply flex flex-col; }
  .bar-row { display: grid; grid-template-columns: minmax(8rem, 17rem) minmax(0, 1fr); align-items: center; column-gap: .75rem; padding: .35rem 0; }
  .bar-label { @apply text-sm text-gray-800 min-w-0; overflow-wrap: anywhere; }
  .bar-sub { @apply block text-[11px] text-gray-500; }
  .bar-track { @apply flex items-center gap-2 h-5 min-w-0; }
  .bar-fill { display: block; flex: none; height: 14px; min-width: 2px; width: calc((100% - 3rem) * var(--w, 0)); border-radius: 0 4px 4px 0; background: #6366f1; }
  .bar-val { @apply text-sm font-semibold text-gray-900; font-variant-numeric: tabular-nums; }
  .bar-cell { min-width: 12rem; }
  .data-table.rep-weekly { min-width: 0; }                               /* (.data-table's own min-width comes later in this sheet) */
  .wk-split { display: none; }
  .data-table td.num, .data-table th.num { @apply text-right; font-variant-numeric: tabular-nums; }
  .data-table td.nowrap { @apply whitespace-nowrap; }
  .act-row { display: grid; grid-template-columns: minmax(6rem, 11rem) minmax(0, 1fr) auto; align-items: center; gap: .75rem; padding: .4rem 0; }
  .split-bar { display: flex; gap: 2px; height: 14px; min-width: 0; }
  .split-ok, .split-bad { display: block; min-width: 2px; }
  .split-ok { background: #10b981; border-radius: 4px 0 0 4px; }
  .split-bad { background: #ef4444; border-radius: 0 4px 4px 0; }
  .split-bar > :only-child { border-radius: 4px; }
  .act-num { @apply text-sm text-gray-700 whitespace-nowrap; font-variant-numeric: tabular-nums; }
  .dot { display: inline-block; width: 8px; height: 8px; border-radius: 50%; margin-right: 4px; }
  .dot-ok { background: #10b981; }
  .dot-bad { background: #ef4444; }
  .bar-legend { @apply flex gap-4 text-xs text-gray-500 mb-1; }
  .rep-tick { @apply text-sm; }
  .rep-more { @apply mt-2; }
  .rep-more > summary { @apply cursor-pointer text-sm text-indigo-600 py-1; }
  .rep-line { @apply grid items-start gap-x-3 gap-y-2 px-4 py-3; grid-template-columns: 8.75rem minmax(0, 1fr) auto; }
  .rep-time { @apply text-sm text-gray-700 whitespace-nowrap; font-variant-numeric: tabular-nums; }
  .rep-main { @apply min-w-0; }
  .rep-bad { box-shadow: inset 3px 0 0 #ef4444; }
  .rep-wait { box-shadow: inset 3px 0 0 #f59e0b; }
  .rep-content { @apply mt-1 text-[13px] text-gray-600; }
  .rep-extra { @apply mt-1 text-xs text-gray-500; }
  .rep-note { @apply mt-1 text-xs text-red-700; }
  .rep-note-ok { @apply text-gray-500; }
  .rep-hint { @apply text-gray-500; }
  .rep-tech { @apply mt-1; }
  .rep-tech > summary { @apply cursor-pointer text-gray-400 text-[11px]; }
  .rep-tech pre { @apply mt-1 p-2 bg-gray-50 border border-gray-200 rounded-lg text-[11px] text-gray-600 whitespace-pre-wrap break-all; font-family: ui-monospace, SFMono-Regular, Menlo, monospace; }
  .rep-job { @apply border border-gray-200 rounded-xl mb-2.5 bg-white; }
  .rep-job > summary { @apply flex flex-wrap items-center gap-x-3 gap-y-1 px-4 py-3 cursor-pointer; list-style: none; }
  .rep-job > summary::-webkit-details-marker { display: none; }
  .rep-job > summary::before { content: "▸"; @apply text-gray-400 text-xs; }
  .rep-job[open] > summary::before { content: "▾"; }
  .rep-job[open] > summary { @apply border-b border-gray-100; }
  .rep-job-title { @apply font-semibold text-sm text-gray-900; }
  .rep-job-when { @apply text-xs ml-auto; }
  .rep-job-data { @apply px-4 py-2 text-xs text-gray-500 border-b border-gray-100; }
  .rep-job-rows { @apply border-0 rounded-none shadow-none; }
  .rep-pager { @apply flex justify-between items-center flex-wrap gap-2 mt-3; }
  @media (max-width: 720px) {
    .rep-line { grid-template-columns: minmax(0, 1fr); }
    .rep-line .sched-actions { justify-content: flex-start; }
    .bar-row { grid-template-columns: minmax(0, 1fr); }
    .act-row { grid-template-columns: minmax(0, 1fr) auto; }
    .act-row .split-bar { grid-column: 1 / -1; grid-row: 2; }
    .rep-job-when { margin-left: 0; }
    .data-table.rep-weekly { table-layout: fixed; }
    .rep-weekly th:first-child { width: 7.5rem; }
    .rep-weekly .num { display: none; }
    .rep-weekly .bar-cell { min-width: 0; }
    .wk-split { display: block; @apply text-[11px] text-gray-500 mt-0.5; }
  }
  /* Home "Hôm nay" (2026-11-02) */
  .home-head { @apply flex flex-wrap items-start justify-between gap-3; }
  .home-quick { @apply flex flex-wrap gap-2 pt-1; }
  .stat-row { @apply grid gap-3 mb-5; grid-template-columns: repeat(auto-fit, minmax(170px, 1fr)); }
  @media (max-width: 599px) {
    .home-head { margin-bottom: 1rem; }                                   /* the quick links wrap under the title; keep them off the tiles */
    .stat-row > .stat:last-child:nth-child(odd) { grid-column: 1 / -1; } /* no orphan tile in a 2-column grid */
  }
  a.stat, div.stat { @apply flex flex-col gap-1 bg-white border border-gray-200 rounded-2xl px-4 py-3.5 shadow-sm no-underline text-gray-900; }
  .stat.stat-attn { @apply bg-amber-50 border-amber-300; }
  a.stat:hover, a.stat.stat-attn:hover { @apply border-indigo-400; }
  .stat-label { @apply text-xs font-semibold text-gray-500; }
  .stat-num { @apply text-2xl font-bold leading-tight; }
  .stat-num .ok { @apply text-emerald-600; }
  .stat-num .bad { @apply text-red-600; }
  .stat-sub { @apply text-[11px] text-gray-500; }
  .home-attn { @apply border-amber-200 bg-amber-50/50; }
  .attn-list { @apply list-none p-0 m-0; }
  .attn-list li { @apply flex flex-wrap items-center justify-between gap-2 py-2 border-t border-amber-100 text-sm; }
  .attn-list li:first-child { @apply border-t-0; }
  .attn-text { @apply min-w-0; }
  .upnext-row { @apply flex flex-wrap items-center gap-x-3 gap-y-1 py-2 border-t border-gray-100 text-sm; }
  .upnext-list > :first-child { @apply border-t-0; }
  .upnext-time { @apply text-xs font-semibold text-gray-600 w-40 shrink-0; }
  .home-more { @apply mt-2 text-sm; }
  .home-manage { @apply ml-auto text-sm font-medium; }
  .health-list { @apply flex flex-col; }
  details.health-row { @apply border-t border-gray-100 first:border-t-0; }
  details.health-row > summary { @apply flex flex-wrap items-center gap-x-3 gap-y-1 py-2.5 cursor-pointer list-none text-sm; }
  details.health-row > summary::-webkit-details-marker { display: none; }
  .health-dot { @apply w-2.5 h-2.5 rounded-full shrink-0 bg-gray-300; }
  .health-green .health-dot { @apply bg-emerald-500; }
  .health-amber .health-dot { @apply bg-amber-500; }
  .health-red .health-dot { @apply bg-red-500; }
  .health-name { @apply font-semibold text-gray-900; }
  .health-sum { @apply text-gray-500 text-[13px] min-w-0; }
  .health-rows { @apply pb-3 pl-6 flex flex-col gap-1 text-[13px]; }
  .home-foot { @apply mt-6 text-xs; }
  .tg-list { @apply mt-1; }
  .tg-row { @apply flex items-center justify-between gap-3 py-3 border-t border-gray-100; }
  .tg-list > .tg-row:first-child { @apply border-t-0; }
  .tg-pending { @apply bg-amber-50 border border-amber-200 rounded-xl px-4 py-3 mb-3; }
  .tg-pending .tg-row { @apply border-amber-100 py-2; }
  .tg-pending .acct-count + .tg-row { @apply border-t-0; }
  @media (max-width: 720px) {
    .acct-row { grid-template-columns: minmax(0, 1fr); }
    .acct-actions { justify-content: flex-start; }
    .acct-actions { position: relative; }
    .acct-actions details.row-menu { position: static; }
    .acct-actions .row-menu-pop { left: 0; right: auto; }
    .acct-child .acct-who { @apply ml-2 pl-3; }
  }
  select.mode-select { @apply w-auto max-w-full text-xs py-1 px-2; }
  .mini-help { @apply mt-1.5 text-xs text-gray-500; }
  .mini-help summary { @apply cursor-pointer text-indigo-600 font-medium; }
  .mini-help code { @apply block bg-gray-50 border border-gray-200 rounded-md px-2 py-1 mt-1 text-[11px] text-gray-700 break-all whitespace-pre-wrap; }
  .hint, .fg-hint { @apply text-gray-500 text-xs mt-1 leading-relaxed; }
  details.page-section { @apply border border-gray-200 rounded-xl px-4 py-3 mt-3 bg-gray-50/60; }
  details.page-section > summary { @apply cursor-pointer text-sm font-semibold text-gray-800; }
  details.page-section[open] > summary { @apply mb-2; }
  .mode-card { @apply flex gap-2.5 items-start border border-gray-200 rounded-xl px-3 py-2.5 cursor-pointer bg-white mb-2; }
  .mode-card:has(input:checked) { @apply border-indigo-600 bg-indigo-50; }
  .mode-card input { @apply mt-1 flex-shrink-0; }
  .mode-card .mode-title { @apply text-sm font-semibold text-gray-900; }
  .mode-card .mode-desc { @apply text-xs text-gray-500 mt-0.5; }

  .account-list { @apply list-none p-0 m-0 flex flex-wrap gap-2; }
  .account-list li { @apply bg-indigo-50 text-indigo-600 text-sm font-semibold px-3 py-1.5 rounded-full; }

  .queue-item { @apply border border-gray-200 rounded-2xl px-4 py-[14px] mb-3 bg-white; }
  .queue-item .queue-filename { @apply text-xs text-gray-500 mb-1.5; }
  .queue-item .queue-preview { @apply text-sm mb-2.5 whitespace-pre-wrap; }
  .queue-item form { @apply flex gap-2 items-center flex-wrap; }
  .queue-item select { @apply w-auto min-w-[140px]; }

  .empty-state { @apply text-center text-gray-500 px-4 py-7 text-sm border border-dashed border-gray-300 rounded-2xl; }

  .section-divider { @apply mt-8 mb-[18px] text-xs uppercase tracking-wide text-gray-500 font-bold; }

  .tab-bar { @apply flex gap-1.5 border-b border-gray-200 mb-5 flex-wrap; }
  .tab-btn { @apply bg-transparent border-0 border-b-2 border-transparent px-3.5 py-2.5 text-sm font-semibold text-gray-500 cursor-pointer -mb-px; }
  .tab-btn:hover { @apply bg-transparent text-gray-900; }
  .tab-btn.active, .tab-btn.active:hover { @apply text-indigo-600 border-indigo-600; }
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
  /* Compose forms on /admin/post: a two-column grid on a wide screen (short fields side by side,
     long ones span both), a single column on a phone. */
  .form-grid { @apply grid grid-cols-1 gap-x-4 gap-y-4 sm:grid-cols-2; }
  .form-grid > .span-2 { @apply sm:col-span-2; }
  .fg { @apply flex flex-col gap-1.5 min-w-0; }
  .fg-label .req { @apply text-red-600; }
  .fg input.narrow { @apply w-28; }
  .fg textarea.compact { @apply min-h-[96px]; }
  .salary-row { @apply flex items-center gap-2 flex-wrap; }
  .salary-row input { @apply w-28 flex-none; }
  .salary-row select { @apply w-auto; }
  .post-block { @apply border border-gray-200 rounded-xl p-3.5 mb-2.5; }
  .block-groups-head { @apply flex items-center justify-between mt-3 mb-2; }
  .group-pills { @apply flex flex-wrap gap-2; }
  .group-pill { @apply flex items-center gap-1.5 text-[13px] bg-gray-50 border border-gray-200 rounded-lg px-2.5 py-1.5 cursor-pointer; }
  .group-pill:has(input:checked) { @apply bg-indigo-50 border-indigo-300; }
  .block-remove { @apply mt-3; }
  .post-actions { @apply mt-5 pt-4 border-t border-gray-100 flex flex-wrap items-start justify-between gap-x-4 gap-y-3; }
  .post-as { @apply text-sm text-gray-500 pt-2; }
  .post-as b { @apply text-gray-800 font-semibold; }
  .post-btns { @apply flex flex-wrap items-start justify-end gap-3 ml-auto; }
  .mode-opt { @apply flex flex-col gap-1 max-w-[260px]; }
  .post-count { @apply text-sm text-gray-600 self-center; }
  .post-count.post-count-empty { @apply text-amber-700; }
  @media (max-width: 639px) {
    .post-btns { @apply w-full; }
    .mode-opt { @apply flex-1 max-w-none; flex-basis: 100%; }
    .post-btns button { @apply w-full; }
  }
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

  // Multi-select variant of the cselect dropdown above (2026-10-01, owner
  // feedback: the plain <select multiple> listbox "nhìn xấu" and required
  // knowing to hold Ctrl/Cmd to pick more than one — this keeps the same
  // single-line trigger + dropdown-panel LOOK as every other dropdown in
  // this app, backed by a real <select multiple name="...">, but clicking
  // an option just TOGGLES it and leaves the panel open instead of
  // replacing the value and closing — needed because picking several
  // options one at a time with a normal click only works if the panel
  // stays put between clicks. `emptyLabel` is shown when nothing is
  // selected (e.g. "Không giới hạn") instead of a blank trigger.
  function initCSelectMulti(wrap) {
    if (wrap.dataset.cselectInit) return;
    wrap.dataset.cselectInit = "1";
    var select = wrap.querySelector("select.cselect-native");
    var trigger = wrap.querySelector(".cselect-trigger");
    var label = trigger.querySelector(".cselect-trigger-label");
    var panel = wrap.querySelector(".cselect-panel");
    if (!select || !trigger || !panel) return;
    // Read from a data attribute, not a 2nd function argument — this runs
    // via `querySelectorAll(...).forEach(initCSelectMulti)` in 2 places
    // (initDynamicScope below, and initRepeatableBlocks' clone handler),
    // and Array.forEach's own 2nd callback argument is the array INDEX,
    // which would silently clobber a real 2nd parameter here.
    var emptyLabel = wrap.dataset.cselectEmptyLabel || "";

    function selectedOptions() {
      return Array.prototype.filter.call(select.options, function (o) { return o.selected; });
    }

    function updateLabel() {
      var chosen = selectedOptions();
      label.textContent = chosen.length
        ? chosen.map(function (o) { return o.textContent; }).join(", ")
        : (emptyLabel || "");
    }

    function render() {
      panel.innerHTML = "";
      Array.prototype.forEach.call(select.options, function (opt) {
        var item = document.createElement("div");
        item.className = "cselect-option" + (opt.selected ? " selected" : "");
        item.textContent = (opt.selected ? "✓ " : "") + opt.textContent;
        item.addEventListener("click", function (e) {
          e.stopPropagation();
          opt.selected = !opt.selected;
          select.dispatchEvent(new Event("change"));
          updateLabel();
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

    updateLabel();
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

  // Custom confirm modal replacing the browser's native window.confirm()
  // popup for every hx-confirm="..." button in the app (2026-09-24, owner
  // request — same .modal-backdrop/.modal-box the rest of the app already
  // uses, instead of the unstylable native dialog). htmx fires
  // "htmx:confirm" before EVERY request, not just ones with hx-confirm —
  // evt.detail.question is null for those, so this lets them straight
  // through untouched. preventDefault() + later calling
  // evt.detail.issueRequest(true) is htmx's own documented way to swap in
  // a custom confirm UI; the `true` skips "htmx:confirm" firing again for
  // the same request. Built via DOM methods (not string-concatenated
  // innerHTML) for the question text specifically, since a few
  // hx-confirm values embed admin-entered text (e.g. an account id) —
  // textContent needs no manual escaping either way.
  document.addEventListener("htmx:confirm", function (e) {
    if (!e.detail.question) return;
    e.preventDefault();
    var root = document.getElementById("modal-root");
    if (!root) { e.detail.issueRequest(true); return; } // no modal slot available — fail open rather than silently block the action
    root.innerHTML = "";
    var backdrop = document.createElement("div");
    backdrop.className = "modal-backdrop";
    var box = document.createElement("div");
    box.className = "modal-box";
    box.setAttribute("role", "alertdialog");
    box.setAttribute("aria-modal", "true");
    var question = document.createElement("p");
    question.style.margin = "0 0 20px";
    question.textContent = e.detail.question;
    var actions = document.createElement("div");
    actions.className = "form-actions";
    var cancelBtn = document.createElement("button");
    cancelBtn.type = "button";
    cancelBtn.className = "btn-secondary";
    cancelBtn.style.marginRight = "8px";
    cancelBtn.textContent = "Huỷ";
    var okBtn = document.createElement("button");
    okBtn.type = "button";
    okBtn.textContent = "Xác nhận";
    function close() { backdrop.remove(); }
    cancelBtn.addEventListener("click", close);
    okBtn.addEventListener("click", function () {
      close();
      e.detail.issueRequest(true);
    });
    actions.appendChild(cancelBtn);
    actions.appendChild(okBtn);
    box.appendChild(question);
    box.appendChild(actions);
    backdrop.appendChild(box);
    backdrop.addEventListener("click", function (ev) { if (ev.target === backdrop) close(); });
    root.appendChild(backdrop);
  });

  // Repeatable content blocks — originally /admin/post's "Đăng vào nhóm"
  // form only (human_bot/admin.py's post_form/post_schedule_groups): each
  // block there is a content_<i>/groups_<i> field pair — see
  // post_schedule_groups()'s comment for why the server scans for
  // whatever indices are present instead of assuming 0..N. Cloning
  // block[0] (always literally index "0" in the server-rendered markup)
  // and bumping its field names to a fresh, never-reused index is enough;
  // removing a block never needs to renumber anything else.
  //
  // Generalized 2026-10-01 for /admin/config's "Kho nội dung" tab, which
  // (unlike /admin/post's always-blank compose form) pre-renders however
  // many rows are already saved — N blocks at page load, not just 1 — so
  // this now wires EVERY pre-rendered block's remove button (not just
  // block[0]) and seeds `nextIndex` from the highest index actually
  // present, instead of assuming the template is the only block and the
  // next free index is always 1.
  function initRepeatableBlocks(container) {
    if (container.dataset.repeatableInit) return;
    container.dataset.repeatableInit = "1";
    var addBtn = container.querySelector("[data-add-block]");
    var list = container.querySelector("[data-block-list]");
    var existingBlocks = list ? list.querySelectorAll("[data-block]") : [];
    var template = existingBlocks.length ? existingBlocks[0] : null;
    if (!addBtn || !list || !template) return;
    var nextIndex = 1;
    existingBlocks.forEach(function (block) {
      block.querySelectorAll("[name]").forEach(function (el) {
        var m = el.name.match(/_(\\d+)$/);
        if (m) nextIndex = Math.max(nextIndex, parseInt(m[1], 10) + 1);
      });
    });

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
        if (el.tagName === "INPUT" && el.type !== "checkbox") el.value = "";
        if (el.type === "checkbox") el.checked = false;
        // Plain <select> (none left on this page as of 2026-10-01, kept
        // for any future one): reset to its first option. A <select
        // multiple> (opener's "Giới hạn visa") has no such "blank/
        // default" option any more — selectedIndex=0 would leave it
        // cloned with option[0] silently selected (restricting the new
        // row to a random visa code instead of leaving it unrestricted),
        // so every option is explicitly deselected instead.
        if (el.tagName === "SELECT") {
          if (el.multiple) {
            Array.prototype.forEach.call(el.options, function (o) { o.selected = false; });
          } else {
            el.selectedIndex = 0;
          }
        }
      });
      // cloneNode() also copies any cselect/cselect-multi dropdown's
      // ALREADY-rendered trigger label + option panel, plus the "already
      // initialized" dataset flag that's meant to stop a 2nd init — left
      // alone, the cloned row's dropdown would show the ORIGINAL row's
      // label frozen in place and never respond to clicks. The native
      // <select> options were just reset above, so re-initializing from
      // scratch here picks that up correctly (empty selection -> empty
      // label).
      clone.querySelectorAll("[data-cselect]").forEach(function (w) { delete w.dataset.cselectInit; initCSelect(w); });
      clone.querySelectorAll("[data-cselect-multi]").forEach(function (w) { delete w.dataset.cselectInit; initCSelectMulti(w); });
      wireRemove(clone);
      wireSelectAll(clone);
      list.appendChild(clone);
      updateRemoveVisibility();
    });

    existingBlocks.forEach(function (block) {
      wireRemove(block);
      wireSelectAll(block);
    });
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
      setHidden(form, "tab", activeTab ? activeTab.getAttribute("data-tab-target").replace(/^tab-/, "") : "");
      writePostDraft(true);
      form.submit();
    });
  }

  // /admin/post keeps what was typed across the two ways the page reloads
  // under the admin: switching account (plain GET form, above) and a
  // server-side validation error (redirect back with ?error=). Every
  // compose form's plain fields — text, textarea, number, select, the ticked
  // group checkboxes and the extra "+ Thêm nội dung khác" blocks — are
  // stashed in sessionStorage right before either one, and put back on the
  // next load ONLY if that load was one of those two (`switched`, or ?error=
  // present); a normal visit, or the success redirect (?scheduled= /
  // ?posted=), just clears it so an old draft never resurfaces. A blank
  // time means "now", so the date pickers travel too (their hidden UTC value;
  // the visible picker is rebuilt from it). Storage can be blocked and a
  // stored draft can be from another build — every access is guarded, and
  // the page works the same without a draft.
  //
  // Fields are keyed by form action + name + POSITION of their content block
  // (content_0 / content_3 are "the block at position p": the number in the
  // name is only an id), so blocks come back in order whatever their ids.
  // Account-specific things are not carried to another account: the ticked
  // groups and the group count (each account has its own limit), nor the
  // "retry of report row N" link, which belongs to the account that failed.
  var POST_DRAFT_KEY = "human_bot.postDraft";

  function postForms() {
    return document.querySelectorAll("[data-tabs] form[action^='/admin/post/']");
  }

  function eachDraftField(callback) {
    postForms().forEach(function (f) {
      var action = f.getAttribute("action");
      var blocks = f.querySelectorAll("[data-block]");
      f.querySelectorAll("textarea[name], input[name], select[name]").forEach(function (el) {
        if (el.name === "account_id") return;
        if (el.type === "hidden" && el.name !== "retry_of_log_id" && !el.hasAttribute("data-schedule-utc")) return;
        var block = el.closest("[data-block]");
        var position = block ? Array.prototype.indexOf.call(blocks, block) : -1;
        callback(el, action + "|" + el.name.replace(/_\\d+$/, "_") + "|" + position);
      });
    });
  }

  function writePostDraft(switched) {
    try {
      var fields = {}, checks = {}, blocks = {};
      eachDraftField(function (el, key) {
        if (el.type === "checkbox") {
          if (el.checked) (checks[key] = checks[key] || []).push(el.value);
        } else {
          fields[key] = el.value;
        }
      });
      postForms().forEach(function (f) { blocks[f.getAttribute("action")] = f.querySelectorAll("[data-block]").length; });
      sessionStorage.setItem(POST_DRAFT_KEY, JSON.stringify({ switched: !!switched, fields: fields, checks: checks, blocks: blocks }));
    } catch (e) { /* storage blocked: the form just starts empty */ }
  }

  function applyPostDraft(draft) {
    // The extra content blocks only exist after a click on "+ Thêm nội dung
    // khác": add as many as the draft had (bounded, in case the click does nothing).
    postForms().forEach(function (f) {
      var want = (draft.blocks || {})[f.getAttribute("action")] || 0;
      var add = f.querySelector("[data-add-block]");
      for (var guard = 0; add && guard < 50 && f.querySelectorAll("[data-block]").length < want; guard++) add.click();
    });
    eachDraftField(function (el, key) {
      if (el.type === "hidden") {
        // hidden: the date pickers' UTC value (the visible picker is rebuilt from it) and the
        // retry link; a value the server already put there wins.
        if (el.value || !draft.fields[key] || (el.name === "retry_of_log_id" && draft.switched)) return;
        el.value = draft.fields[key];
        var wrap = el.closest("[data-schedule-field]");
        var local = wrap && wrap.querySelector("[data-schedule-local]");
        var when = new Date(el.value);
        if (local && !isNaN(when.getTime())) local.value = toLocalInputValue(when);
        return;
      }
      if (el.type === "checkbox") {
        var ticked = draft.checks[key];
        if (!draft.switched && ticked && ticked.indexOf(el.value) !== -1) el.checked = true;
        return;
      }
      if (!(key in draft.fields) || (draft.switched && el.name === "group_count")) return;
      var value = draft.fields[key];
      // A server-side prefill (the "Đặt lịch" link from Báo cáo) wins over a
      // draft for free-text fields; a select only takes a value it still offers.
      if ((el.tagName === "TEXTAREA" || el.type === "text" || el.type === "url") && el.value) return;
      if (el.tagName === "SELECT" && !Array.prototype.some.call(el.options, function (o) { return o.value === value; })) return;
      if (el.type === "number" && el.max && Number(value) > Number(el.max)) value = el.max;
      el.value = value;
    });
    postForms().forEach(function (f) { f.dispatchEvent(new Event("change", { bubbles: true })); });
    document.querySelectorAll("[data-salary-period]").forEach(function (sel) { sel.dispatchEvent(new Event("change")); });
  }

  function initPostDrafts(form) {
    if (form.dataset.draftsInit) return;
    form.dataset.draftsInit = "1";
    var draft = null;
    try {
      draft = JSON.parse(sessionStorage.getItem(POST_DRAFT_KEY) || "null");
      sessionStorage.removeItem(POST_DRAFT_KEY);
    } catch (e) { draft = null; }
    var usable = draft && typeof draft === "object" && draft.fields && typeof draft.fields === "object" && draft.checks && typeof draft.checks === "object";
    if (usable && (draft.switched || new URLSearchParams(location.search).has("error"))) {
      try { applyPostDraft(draft); } catch (e) { /* a draft this page cannot read: start empty */ }
    }
    postForms().forEach(function (f) {
      f.addEventListener("submit", function () { writePostDraft(false); });
    });
  }

  // "Sẽ tạo N bài" next to the group form's submit button: one post per
  // content block x ticked group, so the admin sees the size of what they are
  // about to schedule. Counts ticked boxes; re-counted after any change and
  // after any click (add/remove block, "Chọn tất cả" set .checked in code).
  function initPostCount(form) {
    if (form.dataset.countInit) return;
    form.dataset.countInit = "1";
    var out = form.querySelector("[data-post-count]");
    if (!out) return;
    function update() {
      var n = form.querySelectorAll("[data-block-list] input[type=checkbox]:checked").length;
      out.textContent = n ? "Sẽ tạo " + n + " bài" : "Chưa chọn nhóm nào";
      out.classList.toggle("post-count-empty", !n);
    }
    form.addEventListener("change", update);
    form.addEventListener("click", function () { setTimeout(update, 0); });
    update();
  }

  // The salary hint under "Lương" follows the period (man for month/year,
  // plain yen for hour) — the same rule _build_manual_job() applies.
  function initSalaryHint(select) {
    if (select.dataset.hintInit) return;
    select.dataset.hintInit = "1";
    var hint = document.querySelector("[data-salary-hint]");
    if (!hint) return;
    function update() {
      var text = select.getAttribute("data-hint-" + select.value);
      if (text) hint.textContent = text;
    }
    select.addEventListener("change", update);
    update();
  }

  // /admin/config: every setting row that differs from its default says so (with the default and a "↺ đặt lại"),
  // a min above its max turns red, and the sticky save bar counts the rows changed since the page opened — with a
  // way to drop them (only the boxes it counts — not the AI key or the Kho nội dung text on other tabs), and a
  // warning if the page is left with unsaved changes. A blank number box is saved as "back to the default"
  // (config_save skips it and the section is replaced), so it is not shown as a change from the default.
  function initConfigForm(form) {
    if (form.dataset.configInit) return;
    form.dataset.configInit = "1";
    var rows = form.querySelectorAll("[data-field-row]");
    var note = form.querySelector("[data-dirty-note]");
    var discard = form.querySelector("[data-discard]");
    var dirtyRows = 0, submitting = false;
    function num(v) { var n = parseFloat(v); return isNaN(n) ? null : n; }
    function atDefault(el) {
      if (el.type === "checkbox") return String(el.checked) === el.getAttribute("data-default");
      if (el.value === "") return true;
      var a = num(el.value), b = num(el.getAttribute("data-default"));
      return a !== null && a === b;
    }
    function changedSinceOpen(el) {
      return el.type === "checkbox" ? el.checked !== el.defaultChecked : el.value !== el.defaultValue;
    }
    function refresh() {
      dirtyRows = 0;
      rows.forEach(function (row) {
        var inputs = Array.prototype.slice.call(row.querySelectorAll("[data-default]"));
        var allDefault = inputs.every(atDefault);
        var wrap = row.querySelector("[data-reset-wrap]");
        if (wrap) wrap.hidden = allDefault;
        row.classList.toggle("is-changed", !allDefault);
        if (inputs.some(changedSinceOpen)) dirtyRows++;
        if (inputs.length === 2 && inputs[0].type === "number") {
          var lo = num(inputs[0].value), hi = num(inputs[1].value);
          row.classList.toggle("pair-bad", lo !== null && hi !== null && lo > hi);
        }
      });
      if (note) {
        note.textContent = dirtyRows ? dirtyRows + " thay đổi chưa lưu" : "Chưa có thay đổi";
        note.classList.toggle("is-dirty", dirtyRows > 0);
      }
      if (discard) discard.hidden = dirtyRows === 0;
      var adv = form.querySelector(".cfg-adv-body");
      var badge = form.querySelector("[data-adv-changed]");
      if (adv && badge) {
        var n = adv.querySelectorAll(".field-row.is-changed").length;
        badge.hidden = n === 0;
        badge.textContent = "đã chỉnh " + n;
      }
    }
    form.addEventListener("input", refresh);
    form.addEventListener("change", refresh);
    form.addEventListener("submit", function () { submitting = true; });
    form.addEventListener("click", function (ev) {
      var reset = ev.target.closest("[data-reset]");
      if (reset) {
        reset.closest("[data-field-row]").querySelectorAll("[data-default]").forEach(function (el) {
          if (el.type === "checkbox") el.checked = el.getAttribute("data-default") === "true";
          else el.value = el.getAttribute("data-default");
        });
        refresh();
      }
      if (ev.target.closest("[data-discard]")) {
        rows.forEach(function (row) {
          row.querySelectorAll("[data-default]").forEach(function (el) {
            if (el.type === "checkbox") el.checked = el.defaultChecked; else el.value = el.defaultValue;
          });
        });
        refresh();
      }
    });
    window.addEventListener("beforeunload", function (ev) {
      if (dirtyRows > 0 && !submitting) { ev.preventDefault(); ev.returnValue = ""; }
    });
    refresh();
  }

  // An AI switch saves itself over htmx; htmx does not swap a failed (4xx/5xx) or unreachable response, so without this
  // the switch would stay flipped with nothing saved and no word about it.
  function aiSwitchFailed(ev) {
    var el = ev.detail && ev.detail.elt;
    var card = el && el.closest ? el.closest("#ai-toggle-card") : null;
    if (!card) return;
    if (el.type === "checkbox") el.checked = !el.checked;
    var note = card.querySelector("[data-save-error]");
    if (!note) {
      note = document.createElement("p");
      note.className = "error";
      note.setAttribute("data-save-error", "");
      card.insertBefore(note, card.querySelector(".field-grid"));
    }
    note.textContent = "⚠️ Chưa lưu được — công tắc đã trở về như cũ. Thử lại sau ít phút.";
  }
  document.addEventListener("htmx:responseError", aiSwitchFailed);
  document.addEventListener("htmx:sendError", aiSwitchFailed);

  // Rate-limit modal: "1800" seconds means little at a glance, so each min/max delay row says it in words ("≈ 30 phút – 37
  // phút"), live as the numbers change (the same rule as admin.py's _duration_vi).
  function duration(seconds) {
    var s = Math.max(0, Math.floor(Number(seconds) || 0));
    if (s < 60) return s + " giây";
    var m = Math.floor(s / 60), rest = s % 60;
    if (s < 3600) return m + " phút" + (rest ? " " + rest + " giây" : "");
    var h = Math.floor(m / 60); m = m % 60;
    return h + " giờ" + (m ? " " + m + " phút" : "");
  }
  function initDurationHint(row) {
    if (row.dataset.durationInit) return;
    row.dataset.durationInit = "1";
    var inputs = row.querySelectorAll("input[type=number]");
    var hint = row.querySelector("[data-duration-hint]");
    if (inputs.length !== 2 || !hint) return;
    function update() { hint.textContent = "≈ " + duration(inputs[0].value) + " – " + duration(inputs[1].value); }
    row.addEventListener("input", update);
  }

  // A search box above a list of rows: hides the rows whose data-search text does not contain what was typed, ignoring
  // case and Vietnamese tone marks ("viec lam" finds "Việc làm"; the server writes data-search folded the same way,
  // admin.py's _fold_vi), and says how many are left. Runs once at load too: a browser may restore the box's text.
  function foldVi(text) {
    return text.toLowerCase().replace(/đ/g, "d").normalize("NFD").replace(/[\u0300-\u036f]/g, "");
  }
  function initListFilter(input) {
    if (input.dataset.filterInit) return;
    input.dataset.filterInit = "1";
    var scope = input.closest(".card") || document;
    var rows = scope.querySelectorAll("[data-filter-row]");
    var count = scope.querySelector("[data-list-filter-count]");
    var empty = scope.querySelector("[data-list-filter-empty]");
    function apply() {
      var q = foldVi(input.value.trim()), shown = 0;
      rows.forEach(function (row) {
        var hit = !q || row.getAttribute("data-search").indexOf(q) !== -1;
        row.hidden = !hit;
        if (hit) shown++;
      });
      if (count) count.textContent = q ? shown + " / " + rows.length : "";
      if (empty) empty.hidden = shown !== 0;
    }
    input.addEventListener("input", apply);
    apply();
  }

  // Plain tab switcher (/admin/post's four compose tabs, the config tabs, ...) —
  // added because the page got long enough that having every section
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
        // /admin/config's generic "Lưu cấu hình" submit only ever saves
        // dataclass-backed fields (_CONFIG_SECTIONS) — meaningless (and
        // confusing next to a 2nd, different "Lưu ..." button) on the
        // "Kho nội dung" tab, which has its own dedicated htmx save
        // button and no dataclass fields of its own at all (owner-
        // reported 2026-10-01). Tab switching here is pure client-side
        // (no page reload — see the comment on this function's own
        // click handler above), so this has to be toggled here rather
        // than only once server-side at initial render. No-op (element
        // doesn't exist) on every other page sharing this helper.
        var genericSave = document.getElementById("config-generic-save-actions");
        if (genericSave) genericSave.hidden = (target === "tab-content" || target === "tab-ai");
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
    var d = parseUtc(el.getAttribute("data-utc"));
    if (!d) return;
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
  // new Date("2026-11-03T09:00:00") reads a timestamp WITHOUT an offset as browser-local time, but the
  // server (schedule_store) treats it as UTC — so add the "Z" before parsing.
  function parseUtc(iso) {
    if (!iso) return null;
    var d = new Date(/(Z|[+-]\\d\\d:?\\d\\d)$/i.test(iso) ? iso : iso + "Z");
    return isNaN(d.getTime()) ? null : d;
  }

  // "HH:MM" in the viewer's own timezone for a schedule row (the day it belongs to is the heading
  // initScheduleDays() puts above it); the full local date+time is the tooltip.
  function initLocalTime(el) {
    if (el.dataset.localTimeInit) return;
    el.dataset.localTimeInit = "1";
    var d = parseUtc(el.getAttribute("data-utc"));
    if (!d) return;
    function pad(n) { return String(n).padStart(2, "0"); }
    el.textContent = pad(d.getHours()) + ":" + pad(d.getMinutes());
    el.title = pad(d.getDate()) + "/" + pad(d.getMonth() + 1) + "/" + d.getFullYear() + " " + el.textContent;
  }

  // Puts a "Hôm nay · 02/11" style heading above the first schedule row of each LOCAL day. Rows
  // carry data-sched-when (UTC ISO); without JS the list simply has no headings.
  function initScheduleDays(list) {
    if (list.dataset.daysInit) return;
    list.dataset.daysInit = "1";
    var names = ["Chủ nhật", "Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy"];
    function pad(n) { return String(n).padStart(2, "0"); }
    var today = new Date(); today.setHours(0, 0, 0, 0);
    var lastKey = "";
    Array.prototype.slice.call(list.querySelectorAll(":scope > [data-sched-when]")).forEach(function (row) {
      var d = parseUtc(row.getAttribute("data-sched-when"));
      if (!d) return;
      var key = d.getFullYear() + "-" + d.getMonth() + "-" + d.getDate();
      if (key === lastKey) return;
      lastKey = key;
      var day = new Date(d.getFullYear(), d.getMonth(), d.getDate());
      var diff = Math.round((day - today) / 86400000);
      var label = diff === 0 ? "Hôm nay" : diff === 1 ? "Ngày mai" : diff === -1 ? "Hôm qua" : names[d.getDay()];
      var head = document.createElement("div");
      head.className = "sched-dayhead";
      head.textContent = label + " · " + pad(d.getDate()) + "/" + pad(d.getMonth() + 1);
      list.insertBefore(head, row);
    });
  }

  // Copies `text`; navigator.clipboard only exists on https/localhost, and the admin is often opened over plain
  // http on a LAN, so fall back to a temporary textarea. Reports the outcome in the menu item's own small line,
  // then closes its menu.
  function copyText(text, btn) {
    var small = btn.querySelector("small");
    var original = small ? small.textContent : "";
    function done(ok) {
      if (small) small.textContent = ok ? "✅ Đã copy" : "⚠️ Không copy được — hãy chép tay";
      setTimeout(function () {
        if (small) small.textContent = original;
        var menu = btn.closest("details"); if (menu) menu.removeAttribute("open");
      }, ok ? 900 : 2500);
    }
    if (navigator.clipboard && window.isSecureContext) {
      navigator.clipboard.writeText(text).then(function () { done(true); }, function () { done(false); });
      return;
    }
    var ta = document.createElement("textarea");
    ta.value = text; ta.style.position = "fixed"; ta.style.opacity = "0";
    document.body.appendChild(ta); ta.select();
    var ok = false;
    try { ok = document.execCommand("copy"); } catch (e) { ok = false; }
    document.body.removeChild(ta);
    done(ok);
  }
  window.copyText = copyText;

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
        if (input) { input.value = btn.dataset[key]; input.dispatchEvent(new Event("input", { bubbles: true })); }
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
    root.querySelectorAll("[data-cselect-multi]").forEach(initCSelectMulti);
    root.querySelectorAll("[data-repeatable-blocks]").forEach(initRepeatableBlocks);
    root.querySelectorAll("[data-schedule-field]").forEach(initScheduleField);
    root.querySelectorAll("[data-local-dt]").forEach(initLocalDateTime);
    root.querySelectorAll("[data-local-time]").forEach(initLocalTime);
    root.querySelectorAll("[data-sched-days]").forEach(initScheduleDays);
    root.querySelectorAll("[data-tz-offset-field]").forEach(initTzOffsetField);
    root.querySelectorAll("[data-apply-tier]").forEach(initApplyTierButton);
    root.querySelectorAll("[data-preserve-post-form]").forEach(initPreservePostForm);
    root.querySelectorAll("[data-preserve-post-form]").forEach(initPostDrafts);
    root.querySelectorAll("[data-post-count-form]").forEach(initPostCount);
    root.querySelectorAll("[data-salary-period]").forEach(initSalaryHint);
    root.querySelectorAll("[data-tabs]").forEach(initTabs);
    root.querySelectorAll("[data-config-form]").forEach(initConfigForm);
    root.querySelectorAll("[data-list-filter]").forEach(initListFilter);
    root.querySelectorAll("[data-duration-pair]").forEach(initDurationHint);
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
  // "Đã lên lịch"/"Quá hạn" tabs back and forth blanked the
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


def _vn_int(n: int) -> str:
    return f"{n:,}".replace(",", ".")


# Shown under "Lương", worded from the same constant the server converts with. `_SALARY_HINT_ANY` is what a page
# without JS keeps showing (all three periods in one line); the script swaps in the line for the chosen period.
_SALARY_HINTS = {
    "month": f"Nhập theo man (万 = {_vn_int(content_strategist.YEN_PER_MAN)} yên): 25 nghĩa là 25万 = {_vn_int(25 * content_strategist.YEN_PER_MAN)} yên mỗi tháng.",
    "year": f"Nhập theo man (万 = {_vn_int(content_strategist.YEN_PER_MAN)} yên): 300 nghĩa là 300万 = {_vn_int(300 * content_strategist.YEN_PER_MAN)} yên mỗi năm.",
    "hour": "Nhập số yên: 1500 nghĩa là 1.500 yên mỗi giờ.",
}
_SALARY_HINT_ANY = f"Theo tháng hoặc năm: nhập theo man (万 = {_vn_int(content_strategist.YEN_PER_MAN)} yên), ví dụ 25 là {_vn_int(25 * content_strategist.YEN_PER_MAN)} yên. Theo giờ: nhập số yên."


def _fg(label: str, control: str, *, span2: bool = False, hint: str = "", hint_attrs: str = "", tag: str = "label") -> str:
    """One labelled field of a compose form (.form-grid: two columns on a
    wide screen, one on a phone; span2 = the whole row). `tag="label"` wraps
    a single control so clicking the caption focuses it; use "div" when the
    control is several elements (the date picker + its preset buttons, a
    salary range) — a <label> around those would forward clicks to the
    first one only. `label` and `hint` are trusted HTML (callers pass
    literals); `control` is built by the caller, who escapes any value."""
    hint_html = f'<span class="fg-hint"{hint_attrs}>{hint}</span>' if hint else ""
    return f'<{tag} class="fg{" span-2" if span2 else ""}"><span class="fg-label">{label}</span>{control}{hint_html}</{tag}>'


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


# --- Real login (2026-09-24) — replaces the old Basic Auth (_require_auth/
# HTTPBasic, removed once every route below was confirmed working on the
# new _require_login) with a real session-based login: a styled
# /admin/login page instead of the browser's native Basic Auth popup, plus
# 2 roles (ADMIN — exactly one, still lives in .env; MOD — 0-4 accounts,
# managed by ADMIN at /admin/mod-users, stored in runtime_config.json's
# resolve_login()/get_mod_users()).

class NotLoggedIn(Exception):
    """Raised by _require_login()/_require_admin_role() below instead of
    HTTPException — a FastAPI Depends() can't itself return an arbitrary
    redirect response, so human_bot/service.py registers an
    @app.exception_handler(NotLoggedIn) that decides between a normal 303
    redirect and an htmx-aware HX-Redirect header (see that handler's own
    docstring). `next_path` (just the path, e.g. "/admin/schedule" — never
    a full URL) is where to send the user back to after they log in;
    /admin/login's own POST handler is what actually validates it's safe
    to redirect to (starts with "/admin/") before using it, since THIS
    class just carries whatever request.url.path happened to be at the
    point of failure, which is always same-origin by construction but
    still gets re-validated on the consuming end as defense in depth."""
    def __init__(self, next_path: str | None = None) -> None:
        super().__init__("not logged in")
        self.next_path = next_path


def _is_login_configured() -> bool:
    """Whether /admin login is "on" at all — the single on/off switch for
    the whole feature, identical to _require_auth's old Basic-Auth gate:
    both ADMIN_USERNAME and ADMIN_PASSWORD must be set in .env. Blank
    means every page (including /admin/mod-users) is fully open, exactly
    like today's Basic-Auth-off behavior — no partial protection when
    disabled. Every one of _require_login/_require_admin_role/the login
    routes/_build_current_user calls this FIRST, so there is exactly one
    place that decides "is login on" — never duplicated/re-derived."""
    return bool(os.environ.get("ADMIN_USERNAME", "").strip() and os.environ.get("ADMIN_PASSWORD", "").strip())


def _current_role(request: Request) -> str | None:
    """The logged-in role for THIS request, re-validated fresh every time
    rather than trusting the session cookie blindly — so an admin
    changing ADMIN_USERNAME, or deleting a MOD account, takes effect on
    that user's very NEXT request instead of only once their session
    cookie eventually expires (up to 14 days otherwise, see
    human_bot/service.py's SessionMiddleware setup). Returns None (and
    clears the now-stale session as a side effect) if the session doesn't
    correspond to a currently-valid identity."""
    role = request.session.get("role")
    username = request.session.get("username")
    if not role or not username:
        return None
    if role == "ADMIN":
        current_admin = os.environ.get("ADMIN_USERNAME", "")
        if current_admin and secrets.compare_digest(username, current_admin):
            return "ADMIN"
        request.session.clear()
        return None
    if role == "MOD":
        if get_mod_user(username) is not None:
            return "MOD"
        request.session.clear()
        return None
    request.session.clear()  # unrecognized role value — treat as not-logged-in
    return None


def _require_login(request: Request) -> None:
    """Replaces _require_auth as the dependency for every "any logged-in
    user" route (ADMIN or MOD — both have full access everywhere except
    /admin/mod-users, see _require_admin_role below)."""
    if not _is_login_configured():
        return
    if _current_role(request) is None:
        raise NotLoggedIn(next_path=request.url.path)


def _require_admin_role(request: Request) -> None:
    """Dependency for /admin/mod-users' routes ONLY — a strict superset of
    _require_login's check plus the role gate, so a route depends on this
    INSTEAD OF _require_login, never both. Not-logged-in still raises
    NotLoggedIn (same redirect-to-login behavior as everywhere else,
    since we can't know whether a not-logged-in visitor would have been
    ADMIN); logged in as MOD raises a plain 403 (they ARE logged in, just
    not allowed here — a redirect to login would be wrong/confusing)."""
    if not _is_login_configured():
        return
    role = _current_role(request)
    if role is None:
        raise NotLoggedIn(next_path=request.url.path)
    if role != "ADMIN":
        raise HTTPException(status.HTTP_403_FORBIDDEN, detail="Chỉ tài khoản ADMIN mới có quyền truy cập trang này.")


def _build_current_user(request: Request) -> dict[str, str] | None:
    """For _layout() to render "logged in as X (role)" + the logout button
    + the ADMIN-only "Quản lý MOD" nav link. Returns None whenever there's
    nothing meaningful to show: login disabled (matches _is_login_configured()'s
    "fully open, zero visual change" behavior), or no valid session."""
    if not _is_login_configured():
        return None
    role = _current_role(request)
    if role is None:
        return None
    return {"username": request.session.get("username", ""), "role": role}


def _safe_next_path(next_raw: str | None) -> str:
    """Validates a `next` redirect target came from OUR OWN /admin area
    before ever using it — the open-redirect guard for /admin/login's POST
    handler. Must start with "/admin/" (single leading slash, not "//..."
    which some browsers treat as protocol-relative to another host) and
    must not contain "://" (rules out an embedded absolute URL smuggled
    into the path, e.g. "/admin/../https://evil.example"). Falls back to
    "/admin" (the safe default) for anything that doesn't pass.

    2026-09-24: accepts the bare "/admin" path explicitly, not just
    "/admin/..." — previously a caller passing exactly "/admin" always fell
    through to the same "/admin" fallback anyway, so behavior never
    actually changed, but the check only worked by coincidence and would
    have silently broken if the fallback value ever changed."""
    if next_raw and not next_raw.startswith("//") and "://" not in next_raw and (
        next_raw == "/admin" or next_raw.startswith("/admin/")
    ):
        return next_raw
    return "/admin"


def _password_input_html(name: str, *, label: str = "Mật khẩu", autocomplete: str = "current-password", extra: str = "") -> str:
    """A password box with a "👁" button that shows / hides what was typed (login and the MOD password forms). `label` is its
    accessible name; the button's own name says what pressing it will do and follows the state."""
    return (
        f'<div class="pw-field"><input type="password" name="{html.escape(name)}" aria-label="{html.escape(label)}" autocomplete="{autocomplete}" required{extra}>'
        '<button type="button" class="pw-toggle" aria-label="Hiện mật khẩu" title="Hiện / ẩn mật khẩu" aria-pressed="false" '
        "onclick=\"var i=this.previousElementSibling; i.type = (i.type==='password' ? 'text' : 'password'); "
        "this.setAttribute('aria-pressed', String(i.type==='text')); "
        "this.setAttribute('aria-label', i.type==='text' ? 'Ẩn mật khẩu' : 'Hiện mật khẩu');\">👁</button></div>"
    )


def _login_layout(body: str) -> str:
    """Standalone minimal page shell for /admin/login — deliberately NOT
    _layout() reused: _layout()'s whole <nav> is meaningless (worse,
    misleading — links to pages the visitor can't reach yet) before
    login, and giving _layout() a "hide the nav" flag just for this one
    page would mean threading it through all 9 existing call sites for
    no benefit to them. Shares _PAGE_STYLE (same CSS/fonts/colors) so the
    login page still looks like part of the same app — the whole point
    of "a real custom page, not the browser's native popup"."""
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>Đăng nhập — human_bot admin</title>{_PAGE_STYLE}</head>
<body>
<div id="modal-root"></div>
<main style="max-width:420px; margin:72px auto 0; padding:0 16px;">
{body}
</main>
</body></html>"""


def _login_page_html(next_path: str, show_error: bool) -> str:
    error_html = (
        '<p class="error">⚠️ Tên đăng nhập hoặc mật khẩu không đúng.</p>'
        if show_error
        else ""
    )
    return f"""
<div class="card">
  <h1 style="margin-top:0;">🔒 Đăng nhập</h1>
  <p class="page-desc" style="margin-top:0;">Trang quản trị human_bot</p>
  {error_html}
  <form method="post" action="/admin/login" class="form-col">
    <input type="hidden" name="next" value="{html.escape(next_path)}">
    {_fg("Tên đăng nhập", '<input type="text" name="username" required autofocus autocomplete="username">')}
    {_fg("Mật khẩu", _password_input_html("password"), tag="div")}
    <button type="submit" style="width:100%;">Đăng nhập</button>
  </form>
</div>"""


@router.get("/login", response_class=HTMLResponse)
async def login_page(request: Request, next: str = "/admin", error: bool = False):
    """Public — must be reachable while logged out, obviously. If login
    isn't even configured (_is_login_configured() False), there's nothing
    to log into, so this just bounces straight to /admin rather than
    showing a pointless form. If a valid session already exists (e.g. the
    user hit "back" after logging in), also skip straight past the form."""
    if not _is_login_configured() or _current_role(request) is not None:
        return RedirectResponse("/admin", status_code=303)
    return _login_layout(_login_page_html(_safe_next_path(next), error))


@router.post("/login")
async def login_submit(request: Request):
    if not _is_login_configured():
        return RedirectResponse("/admin", status_code=303)
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    next_path = _safe_next_path(str(form.get("next", "")).strip() or None)
    result = resolve_login(username, password)
    if result is None:
        from urllib.parse import urlencode
        qs = urlencode({"error": "1", "next": next_path})
        return RedirectResponse(f"/admin/login?{qs}", status_code=303)
    role, canonical_username = result
    # Clear first (defensive: never carry over anything from a previous,
    # different identity's session into this one — avoids session
    # fixation across a login boundary) before setting the new identity.
    request.session.clear()
    request.session["role"] = role
    request.session["username"] = canonical_username
    return RedirectResponse(next_path, status_code=303)


@router.post("/logout")
async def logout(request: Request):
    # No auth dependency here on purpose: logging out an already-logged-out
    # (or already-expired) session is harmless and should never itself
    # bounce through the NotLoggedIn redirect machinery — just clear
    # whatever session may or may not exist and send them to the login page.
    request.session.clear()
    return RedirectResponse("/admin/login", status_code=303)


# --- /admin/mod-users (ADMIN-only) ------------------------------------------
#
# Mirrors /admin/accounts's row / modal / hx-confirm pattern (see _acct_row_html / _account_modal_html /
# accounts_add / accounts_delete above) — same htmx conventions, the same "⋯" menu and .sched-list rows, the
# same custom-confirm-modal JS (already global) for the delete item's hx-confirm.

def _mod_users_content_html(saved: bool = False, error: str | None = None) -> str:
    users = get_mod_users()
    flash = '<p class="flash">✅ Đã lưu.</p>' if saved else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""

    if not users:
        list_html = '<div class="empty-state">Chưa có tài khoản MOD nào. Bấm “➕ Thêm tài khoản MOD” để tạo tài khoản cho người cùng quản lý.</div>'
    else:
        rows = []
        for u in users:
            uname = html.escape(u["username"])
            when = _local_dt_html(u["created_at"]) if u["created_at"] else "?"
            menu = _row_menu_html([
                _menu_form(
                    f"/admin/mod-users/{uname}/delete", {}, "🗑 Xoá tài khoản", "Họ sẽ bị đăng xuất ở thao tác kế tiếp",
                    target="#mod-users-content", danger=True,
                    confirm=f"Xoá tài khoản MOD '{uname}'? Phiên đăng nhập hiện tại của tài khoản này (nếu có) sẽ bị đăng xuất ngay ở lần thao tác kế tiếp của họ.",
                ),
            ])
            rows.append(f"""
<div class="sched-item">
  <div class="grp-line">
    <div class="grp-main">
      <div class="sched-title"><span class="sched-target">{uname}</span></div>
      <div class="grp-stats">Tạo lúc {when}</div>
    </div>
    <div class="sched-actions">
      <button type="button" class="btn-small btn-secondary"
              hx-get="/admin/mod-users/{uname}/edit-password-modal" hx-target="#modal-root" hx-swap="innerHTML">🔑 Đổi mật khẩu</button>
      {menu}
    </div>
  </div>
</div>""")
        list_html = f'<div class="sched-list">{"".join(rows)}</div>'

    return f"""
<div id="mod-users-content">
  {flash}{err}
  <div class="account-filter">
    <span class="badge">{len(users)} tài khoản MOD</span>
    <button type="button" class="btn-small" style="margin-left:auto;"
            hx-get="/admin/mod-users/add-modal" hx-target="#modal-root" hx-swap="innerHTML">➕ Thêm tài khoản MOD</button>
  </div>
  {list_html}
</div>"""


def _mod_user_add_modal_html(username: str = "", error: str | None = None) -> str:
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>➕ Thêm tài khoản MOD</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    {err_html}
    <form method="post" action="/admin/mod-users/add" hx-post="/admin/mod-users/add" hx-target="#modal-root" hx-swap="innerHTML">
      <div class="form-col">
        {_fg("Tên đăng nhập", f'<input type="text" name="username" value="{html.escape(username)}" required autofocus autocomplete="off">')}
        {_fg("Mật khẩu", _password_input_html("password", autocomplete="new-password", extra=' minlength="6"'), tag="div", hint="Ít nhất 6 ký tự.")}
        {_fg("Nhập lại mật khẩu", _password_input_html("password_confirm", label="Nhập lại mật khẩu", autocomplete="new-password", extra=' minlength="6"'), tag="div")}
      </div>
      <div class="form-actions">
        <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        <button type="submit">Thêm</button>
      </div>
    </form>
  </div>
</div>"""


def _mod_user_password_modal_html(username: str, error: str | None = None) -> str:
    uname = html.escape(username)
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>🔑 Đổi mật khẩu — {uname}</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    {err_html}
    <form method="post" action="/admin/mod-users/{uname}/edit-password" hx-post="/admin/mod-users/{uname}/edit-password" hx-target="#modal-root" hx-swap="innerHTML">
      <div class="form-col">
        {_fg("Mật khẩu mới", _password_input_html("new_password", label="Mật khẩu mới", autocomplete="new-password", extra=' minlength="6" autofocus'), tag="div", hint="Ít nhất 6 ký tự.")}
        {_fg("Nhập lại mật khẩu mới", _password_input_html("new_password_confirm", label="Nhập lại mật khẩu mới", autocomplete="new-password", extra=' minlength="6"'), tag="div")}
      </div>
      <div class="form-actions">
        <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        <button type="submit">Đổi mật khẩu</button>
      </div>
    </form>
  </div>
</div>"""


@router.get("/mod-users", response_class=HTMLResponse)
async def mod_users_page(request: Request, saved: bool = False, error: str | None = None, _: None = Depends(_require_admin_role)) -> str:
    content = _mod_users_content_html(saved, error)
    if _is_htmx(request):
        return content
    return _layout(f"""
<h1>Quản lý tài khoản MOD</h1>
<p class="page-desc">Tài khoản MOD có đủ quyền như ADMIN ở mọi trang, trừ trang này — chỉ ADMIN vào được trang quản lý tài khoản đăng nhập.</p>
{content}
""", active="mod_users", current_user=_build_current_user(request))


@router.get("/mod-users/add-modal", response_class=HTMLResponse)
async def mod_users_add_modal(_: None = Depends(_require_admin_role)) -> str:
    return _mod_user_add_modal_html()


@router.post("/mod-users/add")
async def mod_users_add(request: Request, _: None = Depends(_require_admin_role)):
    form = await request.form()
    username = str(form.get("username", "")).strip()
    password = str(form.get("password", ""))
    password_confirm = str(form.get("password_confirm", ""))
    error: str | None = None
    if not password:
        error = "Mật khẩu không được để trống."
    elif password != password_confirm:
        error = "Mật khẩu nhập lại không khớp."
    if error is None:
        try:
            add_mod_user(username, password)
        except ValueError as e:
            error = str(e)
    if error:
        if _is_htmx(request):
            return HTMLResponse(_mod_user_add_modal_html(username=username, error=error))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/mod-users?{urlencode({'error': error})}", status_code=303)
    if _is_htmx(request):
        # The add form's hx-target is #modal-root (so a validation error can
        # re-render the modal in place), which means the response's primary
        # content lands INSIDE #modal-root. Returning the list card as
        # primary content put it there — above the page header — until F5.
        # Send it out-of-band instead (replaces #mod-users-content in
        # place); with no primary content left, #modal-root is emptied,
        # which also closes the modal.
        content = _mod_users_content_html(saved=True).replace(
            'id="mod-users-content"', 'id="mod-users-content" hx-swap-oob="true"', 1,
        )
        return HTMLResponse(content)
    return RedirectResponse(url="/admin/mod-users?saved=1", status_code=303)


@router.post("/mod-users/{username}/delete")
async def mod_users_delete(request: Request, username: str, _: None = Depends(_require_admin_role)):
    delete_mod_user(username)
    if _is_htmx(request):
        return HTMLResponse(_mod_users_content_html(saved=True))
    return RedirectResponse(url="/admin/mod-users?saved=1", status_code=303)


@router.get("/mod-users/{username}/edit-password-modal", response_class=HTMLResponse)
async def mod_users_edit_password_modal(username: str, _: None = Depends(_require_admin_role)) -> str:
    return _mod_user_password_modal_html(username)


@router.post("/mod-users/{username}/edit-password")
async def mod_users_edit_password(request: Request, username: str, _: None = Depends(_require_admin_role)):
    form = await request.form()
    new_password = str(form.get("new_password", ""))
    new_password_confirm = str(form.get("new_password_confirm", ""))
    error: str | None = None
    if not new_password:
        error = "Mật khẩu không được để trống."
    elif new_password != new_password_confirm:
        error = "Mật khẩu nhập lại không khớp."
    if error is None:
        try:
            update_mod_user_password(username, new_password)
        except ValueError as e:
            error = str(e)
    # 2026-09-24 fix (real bug, found via live-testing during a careful
    # re-audit of this feature): this route used to always return the bare
    # #mod-users-content fragment, regardless of _is_htmx() — every OTHER
    # mutating route added alongside it (mod_users_add, mod_users_delete)
    # already branches on this, matching the whole app's own convention
    # (see _is_htmx()'s docstring: every mutating form must still work with
    # JS disabled, just with a full page reload). Confirmed live: this
    # form's plain, non-htmx <form method="post"> fallback (present in the
    # markup, per that same convention) actually returned a naked HTML
    # fragment with no <html>/<head>/nav — a broken page, not a full reload.
    if error:
        if _is_htmx(request):
            return HTMLResponse(_mod_user_password_modal_html(username, error=error))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/mod-users?{urlencode({'error': error})}", status_code=303)
    if _is_htmx(request):
        # Same reasoning as mod_users_add(): the form targets #modal-root
        # (an error must re-render the modal, not overwrite the list), so
        # the list goes out-of-band and #modal-root is emptied (modal closes).
        content = _mod_users_content_html(saved=True).replace(
            'id="mod-users-content"', 'id="mod-users-content" hx-swap-oob="true"', 1,
        )
        return HTMLResponse(content)
    return RedirectResponse(url="/admin/mod-users?saved=1", status_code=303)


# --- "Tài khoản Telegram" (sub-tab of /admin/accounts, 2026-10-05) ----------
#
# Who receives human_bot/telegram_notify.py's alerts and can query the 2-way
# health bot — admin-managed list (owner follow-up request: "ai cũng tự dùng
# Telegram của họ... nhưng phải được cài đặt ở ADMIN"), replacing the
# original single hardcoded TELEGRAM_CHAT_ID env var. Nested as a 3rd tab
# on /admin/accounts (owner request) rather than its own top-level nav
# item/page — same "sync" sub-tab pattern accounts_page() already uses
# below, and its own mutating routes live under /accounts/telegram/...
# accordingly (see the /accounts/bootstrap-login/... nesting right above
# for precedent). The manual "add by Chat ID" form is a MODAL (owner
# follow-up, 2026-10-05) behind an explicit button — mirrors
# /admin/mod-users's add-modal pattern below exactly, down to reusing its
# "success -> oob-swap the list + leave #modal-root empty" trick (see
# _mod_user_add_modal_html()/mod_users_add()'s own comments for why that
# closes the modal with no extra JS). The pending-senders one-click "➕
# Thêm" buttons target the SAME #modal-root — on the rare error (e.g. a
# race with someone else just adding that chat_id), a small modal with
# the error pops up instead of a response landing in the wrong place.

def _telegram_bot_link_html() -> str:
    """A clickable t.me/<bot username> link, when known (cached at
    service startup by telegram_notify.refresh_bot_username() — see its
    own docstring) — falls back to plain text if the lookup never
    succeeded (e.g. the service hasn't been restarted since upgrading to
    this feature, or the token is blank/invalid)."""
    username = telegram_notify.get_cached_bot_username()
    if not username:
        return "bot Telegram của hệ thống"
    url = f"https://t.me/{username}"
    return f'<a href="{html.escape(url)}" target="_blank" rel="noopener">@{html.escape(username)}</a>'


def _telegram_recipient_add_modal_html(chat_id: str = "", label: str = "", error: str | None = None) -> str:
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>➕ Thêm người nhận Telegram</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    <p class="page-desc" style="margin-top:0;">Chỉ cần dùng form này khi đã biết sẵn Chat ID — bình thường
      cứ nhắn vào {_telegram_bot_link_html()} trước, họ sẽ tự hiện ở danh sách "chưa được thêm" để bấm 1 nút, không cần gõ tay.</p>
    {err_html}
    <form method="post" action="/admin/accounts/telegram/add" hx-post="/admin/accounts/telegram/add" hx-target="#modal-root" hx-swap="innerHTML">
      <div class="field-stack">
        <div class="field-label">Chat ID</div>
        <div class="field-input"><input type="text" name="chat_id" value="{html.escape(chat_id)}" required autofocus placeholder="VD: 931000937"></div>
      </div>
      <div class="field-stack" style="margin-top:10px;">
        <div class="field-label">Tên gợi nhớ (tuỳ chọn)</div>
        <div class="field-input"><input type="text" name="label" value="{html.escape(label)}" placeholder="VD: Tu"></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        <button type="submit">Thêm</button>
      </div>
    </form>
  </div>
</div>"""


def _telegram_recipient_edit_modal_html(chat_id: str, label: str = "", error: str | None = None) -> str:
    """Only `label` is editable here — chat_id is the identity key for
    this list (re-pointing it would really mean delete-then-add a
    different person, not "editing" this one), so it's shown as
    read-only context in the header, never as an input."""
    cid_esc = html.escape(chat_id)
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>✏️ Sửa tên gợi nhớ — {cid_esc}</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    {err_html}
    <form method="post" action="/admin/accounts/telegram/{cid_esc}/edit" hx-post="/admin/accounts/telegram/{cid_esc}/edit" hx-target="#modal-root" hx-swap="innerHTML">
      <div class="field-stack">
        <div class="field-label">Tên gợi nhớ</div>
        <div class="field-input"><input type="text" name="label" value="{html.escape(label)}" autofocus placeholder="VD: Tu"></div>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        <button type="submit">Lưu</button>
      </div>
    </form>
  </div>
</div>"""


def _telegram_recipients_content_html(flash: str | None = None, error: str | None = None) -> str:
    recipients = get_telegram_recipients()
    flash_html = f'<p class="flash">{html.escape(flash)}</p>' if flash else ""
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""

    # "Người mới nhắn bot, chưa thêm" (2026-10-05 follow-up) — owner
    # pointed out whoever only has /admin access has no way to know
    # TELEGRAM_BOT_TOKEN, so they could never hand-build a getUpdates URL
    # to find someone's chat_id. telegram_notify.record_pending_sender()
    # (called by service.py's _telegram_listen_loop() for every message
    # from an unregistered chat) means this card can instead offer a
    # one-click add — no token, no raw API response, ever shown here.
    registered_chat_ids = {r["chat_id"] for r in recipients}
    pending = {
        cid: info for cid, info in telegram_notify.get_pending_senders().items()
        if cid not in registered_chat_ids
    }
    if not pending:
        pending_html = ""
    else:
        pending_rows = []
        for cid, info in sorted(pending.items(), key=lambda kv: kv[1]["last_seen"], reverse=True):
            cid_esc = html.escape(cid)
            name_esc = html.escape(info["name"])
            pending_rows.append(f"""
<div class="tg-row">
  <div><span class="acct-name">{name_esc}</span> <span class="acct-aid">{cid_esc}</span></div>
  <form method="post" action="/admin/accounts/telegram/add" hx-post="/admin/accounts/telegram/add"
        hx-target="#modal-root" hx-swap="innerHTML" style="margin:0;">
    <input type="hidden" name="chat_id" value="{cid_esc}">
    <input type="hidden" name="label" value="{name_esc}">
    <button type="submit" class="btn-small">➕ Thêm</button>
  </form>
</div>""")
        pending_html = f"""
<div class="tg-pending">
  <div class="acct-count">🔔 {len(pending)} người mới nhắn vào bot, chưa được thêm</div>
  {"".join(pending_rows)}
</div>"""

    if not recipients:
        rows_html = '<div class="empty-state">Chưa có ai nhận báo động Telegram.</div>'
    else:
        rows = []
        for r in recipients:
            cid = html.escape(r["chat_id"])
            label = html.escape(r["label"])
            menu = _row_menu_html([
                _menu_button(
                    f'hx-get="/admin/accounts/telegram/{cid}/edit-modal" hx-target="#modal-root" hx-swap="innerHTML"',
                    "✏️ Sửa tên", "Đổi tên gợi nhớ (Chat ID giữ nguyên)",
                ),
                _menu_form(
                    f"/admin/accounts/telegram/{cid}/test", {}, "🧪 Gửi tin thử", "Gửi một tin test tới người này để kiểm tra",
                    target="#telegram-recipients-content",
                ),
                '<hr class="row-menu-sep">',
                _menu_form(
                    f"/admin/accounts/telegram/{cid}/delete", {}, "🗑 Xoá", "Người này không còn nhận báo động / trả lời từ bot",
                    target="#telegram-recipients-content", danger=True,
                    confirm=f"Xoá người nhận '{label}' (chat ID {cid})? Người này sẽ không còn nhận báo động/trả lời hỏi-đáp từ bot nữa.",
                ),
            ])
            rows.append(
                f'<div class="tg-row"><div><span class="acct-name">{label}</span> <span class="acct-aid">{cid}</span></div>{menu}</div>'
            )
        rows_html = "".join(rows)

    return f"""
<div class="card" id="telegram-recipients-content">
  {flash_html}{err_html}
  <div class="acct-head">
    <div><span class="acct-count">{len(recipients)} người nhận tin từ bot</span>
      <span class="acct-aid">· báo động, tóm tắt và các lệnh /schedule, /error…</span></div>
    <button type="button" class="btn-small" hx-get="/admin/accounts/telegram/add-modal"
            hx-target="#modal-root" hx-swap="innerHTML">➕ Thêm thủ công</button>
  </div>
  {pending_html}
  <div class="tg-list">{rows_html}</div>
  <details class="mini-help" style="margin-top:12px;"><summary>Cách thêm người nhận</summary>
    <div class="hint">Bảo họ nhắn bất kỳ gì vào {_telegram_bot_link_html()} — trong vài giây họ sẽ hiện ở mục
      "người mới nhắn vào bot", bấm "➕ Thêm" là xong, không cần gõ tay Chat ID.</div>
  </details>
</div>"""


@router.get("/accounts/telegram/add-modal", response_class=HTMLResponse)
async def telegram_recipients_add_modal(_: None = Depends(_require_login)) -> str:
    return _telegram_recipient_add_modal_html()


@router.post("/accounts/telegram/add")
async def telegram_recipients_add(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    chat_id = str(form.get("chat_id", "")).strip()
    label = str(form.get("label", "")).strip()
    error: str | None = None
    try:
        add_telegram_recipient(chat_id, label)
    except ValueError as e:
        error = str(e)
    if error:
        if _is_htmx(request):
            return HTMLResponse(_telegram_recipient_add_modal_html(chat_id=chat_id, label=label, error=error))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'tab': 'telegram', 'telegram_error': error})}", status_code=303)
    # Now a real recipient — stop offering the "➕ Thêm" one-click button
    # for them in the pending-senders list above (no-op if they were
    # added by hand instead, via the plain form, and were never pending).
    telegram_notify.clear_pending_sender(chat_id)
    if _is_htmx(request):
        # Both callers of this route (the manual-add modal AND each
        # pending-sender's one-click button) target #modal-root, not
        # #telegram-recipients-content directly — same reasoning as
        # mod_users_add() above: send the refreshed list out-of-band
        # instead, which also leaves #modal-root empty (closing a modal
        # if one was open; a no-op harmless swap if the click came from
        # a one-click button with no modal ever shown).
        content = _telegram_recipients_content_html(flash="✅ Đã thêm.").replace(
            'id="telegram-recipients-content"', 'id="telegram-recipients-content" hx-swap-oob="true"', 1,
        )
        return HTMLResponse(content)
    return RedirectResponse(url="/admin/accounts?tab=telegram&saved=1", status_code=303)


@router.get("/accounts/telegram/{chat_id}/edit-modal", response_class=HTMLResponse)
async def telegram_recipients_edit_modal(chat_id: str, _: None = Depends(_require_login)) -> str:
    match = get_telegram_recipient(chat_id)
    return _telegram_recipient_edit_modal_html(chat_id, label=match["label"] if match else "")


@router.post("/accounts/telegram/{chat_id}/edit")
async def telegram_recipients_edit(request: Request, chat_id: str, _: None = Depends(_require_login)):
    form = await request.form()
    label = str(form.get("label", "")).strip()
    error: str | None = None
    try:
        update_telegram_recipient_label(chat_id, label)
    except ValueError as e:
        error = str(e)
    if error:
        if _is_htmx(request):
            return HTMLResponse(_telegram_recipient_edit_modal_html(chat_id, label=label, error=error))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'tab': 'telegram', 'telegram_error': error})}", status_code=303)
    if _is_htmx(request):
        # Same oob-swap-the-list-plus-empty-#modal-root trick as the add
        # route above — this form also targets #modal-root.
        content = _telegram_recipients_content_html(flash="✅ Đã lưu.").replace(
            'id="telegram-recipients-content"', 'id="telegram-recipients-content" hx-swap-oob="true"', 1,
        )
        return HTMLResponse(content)
    return RedirectResponse(url="/admin/accounts?tab=telegram&saved=1", status_code=303)


@router.post("/accounts/telegram/{chat_id}/delete")
async def telegram_recipients_delete(request: Request, chat_id: str, _: None = Depends(_require_login)):
    delete_telegram_recipient(chat_id)
    if _is_htmx(request):
        return HTMLResponse(_telegram_recipients_content_html(flash="✅ Đã xoá."))
    return RedirectResponse(url="/admin/accounts?tab=telegram&saved=1", status_code=303)


@router.post("/accounts/telegram/{chat_id}/test")
async def telegram_recipients_test(request: Request, chat_id: str, _: None = Depends(_require_login)):
    # send_message_to() returns whether it ACTUALLY reached Telegram with
    # a 200, not just "didn't raise" — it's best-effort/never-raises by
    # design, so without checking this return value the button would
    # report "✅ Đã gửi" even when the switch is off, the token is
    # revoked, or this chat_id blocked the bot — defeating the whole
    # point of a button meant to verify a chat_id actually works.
    ok = await telegram_notify.send_message_to(
        chat_id, "✅ Test từ human_bot — chat_id này đang hoạt động đúng!", silent=False,
    )
    if _is_htmx(request):
        if ok:
            flash = f"✅ Đã gửi tin test tới chat ID {chat_id} — kiểm tra Telegram."
            return HTMLResponse(_telegram_recipients_content_html(flash=flash))
        error = (
            f"⚠️ Gửi tin test tới chat ID {chat_id} KHÔNG thành công — kiểm tra lại chat_id, "
            f"token, hoặc công tắc bật/tắt ở /admin/config."
        )
        return HTMLResponse(_telegram_recipients_content_html(error=error))
    from urllib.parse import urlencode
    query = {"tab": "telegram", "tested": chat_id} if ok else {"tab": "telegram", "test_failed": chat_id}
    return RedirectResponse(url=f"/admin/accounts?{urlencode(query)}", status_code=303)


def _layout(body: str, active: str = "", *, current_user: dict[str, str] | None = None) -> str:
    """`current_user` (2026-09-24, added alongside the real /admin login):
    {"username": str, "role": "ADMIN"|"MOD"} for whoever is logged in, or
    None whenever there's nothing meaningful to show — either login is
    disabled entirely (_build_current_user() returns None in that case,
    matching "fully open, zero visual change" — the nav below looks
    exactly like it did before this feature existed), or genuinely no
    valid session. Every one of this function's call sites is already
    inside a route handler with `request: Request` in scope, so each just
    passes `current_user=_build_current_user(request)`."""
    def nav_class(key: str) -> str:
        return "active" if key == active else ""

    mod_users_link = (
        f'<a href="/admin/mod-users" class="{nav_class("mod_users")}">Quản lý MOD</a>'
        if current_user is not None and current_user["role"] == "ADMIN"
        else ""
    )
    user_chip = (
        f"""<div style="display:flex; align-items:center; gap:10px; font-size:13px; color:#6b7280;">
      <span>{html.escape(current_user["username"])} ({html.escape(current_user["role"])})</span>
      <form method="post" action="/admin/logout" style="margin:0;">
        <button type="submit" class="btn-secondary btn-small">Đăng xuất</button>
      </form>
    </div>"""
        if current_user is not None
        else ""
    )

    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>human_bot admin</title>{_PAGE_STYLE}</head>
<body>
<div id="modal-root"></div>
<div class="topbar">
  <div class="topbar-inner">
    <a href="/admin" class="brand" title="Trang chủ"><span class="brand-dot"></span> human_bot</a>
    <nav class="topnav">
      <a href="/admin/accounts" class="{nav_class('accounts')}">Tài khoản</a>
      <a href="/admin/config" class="{nav_class('config')}">Cấu hình</a>
      <a href="/admin/post" class="{nav_class('post')}">Đăng bài</a>
      <a href="/admin/groups" class="{nav_class('groups')}">Nhóm đã tham gia</a>
      <a href="/admin/schedule" class="{nav_class('schedule')}">Lịch đăng</a>
      <a href="/admin/reports" class="{nav_class('reports')}">Báo cáo</a>
      {mod_users_link}
    </nav>
    {user_chip}
  </div>
</div>
<main>
{body}
</main>
</body></html>"""


_SILENCE_WARNING_HOURS = 48  # owner's threshold, 2026-10-02
_SESSION_EXPIRY_WARNING_DAYS = 14  # owner's threshold, 2026-10-02


@dataclasses.dataclass
class AccountWarningStatus:
    """Machine-readable result of _account_warning_status() below —
    `kinds` is a subset of {"silence", "session_unreadable",
    "session_expired", "session_expiring_soon"}; `days_left` is the real
    (possibly negative) days remaining on the session, or None when it
    couldn't be determined at all (session_unreadable, or the check
    itself failed) — kept alongside `kinds` so a caller that also needs
    to DISPLAY the number (not just react to the threshold) doesn't have
    to re-fetch bootstrap_login_sessions.get_session_expiry() a 2nd time."""
    kinds: set[str]
    days_left: float | None


def _account_warning_status(
    aid: str, account, last_success_map: dict[str, str],
) -> AccountWarningStatus:
    """The "im lặng"/"phiên đăng nhập" combination logic (paused/resting
    suppression, the hours_ago/days_left thresholds) as a MACHINE-
    READABLE set of named kinds — shared by _account_health_signals()
    below (for /admin's dashboard card) AND service.py's
    _telegram_health_check_loop() (for the Telegram alert), so the two
    can never silently disagree about when one of these conditions
    starts/stops being a warning (2026-10-05 self-review, round 5 — a
    prior version had the Telegram loop hand-copy this logic a 2nd
    time, and the copy was missing the "already expired" vs "expiring
    soon" distinction this one has, understating urgency in the alert
    text for an already-dead session).

    The 2 checks below (silence; session) are independent signals from
    different data sources — each is isolated in its OWN try/except so
    one's failure can never discard the other's already-computed
    result, and the caller can still reliably update its own
    transition-tracking state afterwards (this function itself never
    raises)."""
    kinds: set[str] = set()
    days_left: float | None = None
    if account.status == AccountStatus.DISABLED:
        # Switched off on purpose: silence and a stale session are expected,
        # not warnings (and must not page anyone on Telegram).
        return AccountWarningStatus(kinds=kinds, days_left=None)
    try:
        is_paused = account.status == AccountStatus.PAUSED
        is_resting = not is_paused and bool(get_resume_cooldown_info(aid))
        last_success = last_success_map.get(aid)
        if last_success and not is_paused and not is_resting:
            last_dt = datetime.fromisoformat(last_success)
            if last_dt.tzinfo is None:
                last_dt = last_dt.replace(tzinfo=timezone.utc)
            hours_ago = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
            if hours_ago > _SILENCE_WARNING_HOURS:
                kinds.add("silence")
    except Exception:  # noqa: BLE001 - must not block the independent session check below
        logger.exception("_account_warning_status: silence check failed for %s", aid)
    try:
        expiry = bootstrap_login_sessions.get_session_expiry(aid)
        if expiry is None:
            kinds.add("session_unreadable")
        else:
            days_left = (expiry - datetime.now(timezone.utc)).total_seconds() / 86400
            if days_left < 0:
                kinds.add("session_expired")
            elif days_left < _SESSION_EXPIRY_WARNING_DAYS:
                kinds.add("session_expiring_soon")
    except Exception:  # noqa: BLE001 - must not discard the silence check's already-good result
        logger.exception("_account_warning_status: session check failed for %s", aid)
    return AccountWarningStatus(kinds=kinds, days_left=days_left)


def _account_health_signals(
    aid: str, account, sync_statuses: dict, last_success_map: dict[str, str],
) -> tuple[int, list[tuple[str, str]]]:
    """The 5 "sức khoẻ tài khoản" signals (2026-10-02, admin-UI
    improvement idea #3), as PLAIN DATA — (severity, [(icon, text), ...])
    with `text` plain (no HTML markup) so this one computation is shared
    by both /admin's home page (_account_health_card_html() below wraps
    it in HTML) and the Telegram bot (_account_health_telegram_text(),
    human_bot/telegram_notify.py's 2-way health query, added 2026-10-05)
    — the 5-signal logic itself must only ever live in ONE place.
    severity: 0 = cần chú ý ngay (đỏ), 1 = theo dõi (vàng), 2 = ổn (xanh)
    — callers sort/prioritize worst-first by this, same "xấu nhất lên
    đầu" pattern RPA fleet dashboards use. Any date embedded in `text` is
    left as the RAW ISO string, not pre-formatted — each renderer below
    formats it its own way: _account_health_card_html() swaps it for a
    live viewer-local-time span (_localize_iso_timestamps_html(), the
    same mechanism every other date on this admin page already uses —
    restored 2026-10-05 after this refactor briefly hard-coded JST here
    and silently dropped that live conversion for this one card),
    _account_health_telegram_text() swaps it for fixed JST text instead
    (_fmt_jst() — Telegram can't run the browser-local-time JS)."""
    severity = 2
    rows: list[tuple[str, str]] = []

    if account.status == AccountStatus.DISABLED:
        off_info = get_disabled_info(aid) or {}
        since = f" từ {off_info['disabled_at']}" if off_info.get("disabled_at") else ""
        return 2, [("⚪", f"Đã tắt (chủ động){since} — không chạy tác vụ nào")]

    is_paused = account.status == AccountStatus.PAUSED
    is_resting = False
    if is_paused:
        severity = 0
        info = get_pause_info(aid)
        reason = (info or {}).get("reason") or "không rõ"
        rows.append(("🔴", f"Tạm dừng — {reason}"))
    else:
        cooldown = get_resume_cooldown_info(aid)
        if cooldown:
            is_resting = True
            severity = min(severity, 1)
            rows.append(("🟡", f"Đang hạ nhiệt, xong vào {cooldown.get('until') or '—'}"))
        else:
            rows.append(("🟢", "Hoạt động"))

    # Phiên trình duyệt — peek_session() (không tự tạo session mới chỉ vì
    # trang chủ được mở). None là bình thường (service mới khởi động/tài
    # khoản chưa từng chạy task nào), khác hẳn "đã có session nhưng chết".
    session = browser_pool.peek_session(aid)
    if session is None:
        rows.append(("⚪", "Chưa mở phiên trình duyệt nào"))
    elif session.is_alive():
        rows.append(("🟢", "Phiên trình duyệt đang mở"))
    else:
        severity = 0
        rows.append(("🔴", "Phiên trình duyệt đã đóng — cần xem lại"))

    sync = sync_statuses.get(aid)
    if sync is None:
        rows.append(("⚪", "Chưa đồng bộ dữ liệu lần nào"))
    elif sync.get("status") == "ok":
        rows.append(("🟢", f"Đồng bộ OK lúc {sync.get('last_run_at') or '—'}"))
    else:
        severity = min(severity, 1)
        rows.append(("🟡", f"Đồng bộ lỗi lúc {sync.get('last_run_at') or '—'}"))

    status = _account_warning_status(aid, account, last_success_map)

    # "Im lặng" chỉ có ý nghĩa cảnh báo khi tài khoản ĐANG LẼ RA phải hoạt
    # động — Tạm dừng/Hạ nhiệt đã tự giải thích lý do im lặng rồi (đã áp
    # dụng bên trong _account_warning_status() ở trên).
    last_success = last_success_map.get(aid)
    if last_success is None:
        rows.append(("⚪", "Chưa có lượt đăng/bình luận thành công nào"))
    elif "silence" in status.kinds:
        last_dt = datetime.fromisoformat(last_success)
        if last_dt.tzinfo is None:
            last_dt = last_dt.replace(tzinfo=timezone.utc)
        hours_ago = (datetime.now(timezone.utc) - last_dt).total_seconds() / 3600
        severity = min(severity, 1)
        rows.append(("🟡", f"Im lặng {int(hours_ago)} giờ — lần thành công gần nhất {last_success}"))
    else:
        rows.append(("🟢", f"Thành công gần nhất: {last_success}"))

    if "session_unreadable" in status.kinds:
        severity = 0
        rows.append(("🔴", "Không đọc được phiên đăng nhập (chưa đăng nhập/file hỏng)"))
    elif status.days_left is None:
        # _account_warning_status()'s session check itself failed (caught
        # there, logged) — fail safe to a neutral row rather than crash
        # this whole page render over it.
        rows.append(("⚪", "Không xác định được tình trạng phiên đăng nhập"))
    elif "session_expired" in status.kinds:
        severity = 0
        rows.append(("🔴", "Phiên đăng nhập đã hết hạn — cần đăng nhập lại"))
    elif "session_expiring_soon" in status.kinds:
        severity = min(severity, 1)
        rows.append(("🟡", f"Phiên đăng nhập còn {int(status.days_left)} ngày"))
    else:
        rows.append(("🟢", f"Phiên đăng nhập còn {int(status.days_left)} ngày"))

    return severity, rows


def _health_summary_text(severity: int, rows: list[tuple[str, str]]) -> str:
    """The one line an account gets on the home page: when all is well, its state and the last success; when
    not, ONLY the lines that need a person (🔴 then 🟡). Plain text — raw ISO timestamps are still in it."""
    if severity >= 2:
        picked = [rows[0][1]] if rows else []
        picked += [text for _icon, text in rows if text.startswith("Thành công gần nhất")]
        return " · ".join(picked)
    return " · ".join(text for wanted in ("🔴", "🟡") for icon, text in rows if icon == wanted)


def _account_health_card_html(
    aid: str, account, sync_statuses: dict, last_success_map: dict[str, str],
) -> tuple[int, str]:
    severity, rows = _account_health_signals(aid, account, sync_statuses, last_success_map)
    return severity, _account_health_row_html(aid, account, severity, rows)


def _account_health_row_html(aid: str, account, severity: int, rows: list[tuple[str, str]]) -> str:
    """HTML rendering of _account_health_signals() for /admin's home page (2026-11-02 redesign: one line per
    account — coloured dot, name, and the short summary — with the five signals behind a click, instead of a
    card of six emoji lines each). Every signal still pairs an icon with a text label (never color alone), and
    each row goes through _localize_iso_timestamps_html() (not a plain html.escape()) so any raw ISO timestamp
    renders as the viewer's own browser-local time, like every other date on this admin page."""
    # ⚪ only ever marks "no data yet" (never mở session/đồng bộ/đăng thành công nào) — dim those.
    muted_attr = ' class="muted"'
    rows_html = "".join(
        f"<div{muted_attr if icon == '⚪' else ''}>{icon} {_localize_iso_timestamps_html(text)}</div>"
        for icon, text in rows
    )
    tone = "gray" if account.status == AccountStatus.DISABLED else ("red", "amber", "green")[max(0, min(severity, 2))]
    card_html = f"""
<details class="health-row health-{tone}">
  <summary><span class="health-dot"></span>
    <span class="health-name">{html.escape(account.display_name)} <span class="row-url">({html.escape(aid)})</span></span>
    <span class="health-sum">{_localize_iso_timestamps_html(_health_summary_text(severity, rows))}</span></summary>
  <div class="health-rows">{rows_html}</div>
</details>"""
    return card_html


def _account_health_telegram_text(aid: str, account, sync_statuses: dict, last_success_map: dict[str, str]) -> str:
    """Plain-text rendering of _account_health_signals() for Telegram —
    human_bot/telegram_notify.py's 2-way health query (2026-10-05). Any
    raw ISO timestamp _account_health_signals() left in a row's text is
    swapped for fixed-JST text (_fmt_jst()) — Telegram can't run the
    browser-local-time JS _account_health_card_html() uses instead."""
    _severity, rows = _account_health_signals(aid, account, sync_statuses, last_success_map)
    lines = "\n".join(f"{icon} {_ISO_DT_RE.sub(lambda m: _fmt_jst(m.group(0)), text)}" for icon, text in rows)
    return f"{'📄' if getattr(account, 'page_name', '') else '👤'} {account.display_name} ({aid})\n{lines}"


_WEEKDAYS_VI = ("Thứ hai", "Thứ ba", "Thứ tư", "Thứ năm", "Thứ sáu", "Thứ bảy", "Chủ nhật")


def _stat_tile(label: str, value_html: str, href: str | None, sub: str = "", attention: bool = False) -> str:
    """A number tile: a link to where the work is, or (href=None) a plain tile."""
    tag, link = ("a", f' href="{href}"') if href else ("div", "")
    return (
        f'<{tag} class="stat{" stat-attn" if attention else ""}"{link}>'
        f'<span class="stat-label">{label}</span><span class="stat-num">{value_html}</span>'
        f'{f"<span class=stat-sub>{sub}</span>" if sub else ""}</{tag}>'
    )


@router.get("", response_class=HTMLResponse)
async def admin_home(request: Request, _: None = Depends(_require_login)) -> str:
    """"Hôm nay" (2026-11-02): what is going on today and what needs a person — five numbers that are links,
    the problems first, the next posts, then one line per account. The numbers come from human_bot/overview.py,
    the same code Telegram's /report uses."""
    from human_bot import overview, telegram_failures  # local imports: telegram_failures imports this module

    accounts = get_all_accounts()
    sync_statuses = get_all_sync_statuses()
    last_success_map = db.last_successful_action_per_account()
    now = datetime.now(timezone.utc)
    pending = schedule_store.list_pending()  # read ONCE: the numbers and the "Sắp đăng" rows both use it
    today = overview.today(now, list(accounts), pending)
    failures = telegram_failures.open_failure_count(create=False, default=None)  # read-only: a page view files nothing

    # --- the five numbers
    q = today.queue
    failures_tile = (
        _stat_tile("Lỗi chưa xử lý", str(failures), "/admin/reports?tab=failures&days=7", "xem lỗi 7 ngày qua · xử lý: gõ /error" if failures else "", attention=bool(failures))
        if failures is not None
        else _stat_tile("Lỗi chưa xử lý", "?", "/admin/reports?tab=failures&days=7", "không đọc được — xem nhật ký của service", attention=True)
    )
    tiles = "".join([
        _stat_tile("Chờ đăng hôm nay", str(q.left_today), "/admin/schedule",
                   f"⏰ {q.due} đã đến giờ" if q.due else (f"{q.later} bài các ngày sau" if q.later else ""), attention=bool(q.due)),
        _stat_tile("Kết quả hôm nay", f'<span class="ok">✅ {today.ok}</span> <span class="bad">❌ {today.failed}</span>',
                   "/admin/reports", "lượt thành công · thất bại"),
        _stat_tile("Quá hạn", str(today.missed), "/admin/schedule?tab=missed", "chờ bạn xếp lại" if today.missed else "", attention=bool(today.missed)),
        _stat_tile("Chờ duyệt", str(today.reviews), "/admin/schedule?tab=needs_review", "tin tuyển dụng" if today.reviews else "", attention=bool(today.reviews)),
        failures_tile,
    ])

    # --- problems (what the numbers above do not already say) and one line per account
    attention_items: list[str] = []
    if not get_scheduling_config().auto_fire_enabled:
        attention_items.append(
            '<li><span class="attn-text">⚠️ Tự động đăng đang <b>tắt</b> — bài đến giờ phải bấm “🚀 Đăng ngay” thủ công.</span>'
            '<a class="btn btn-secondary btn-small" href="/admin/config">Bật ở Cấu hình</a></li>'
        )
    problem_accounts: list[tuple[tuple, str]] = []  # (sort key, html): paused first, then worst health, then by name
    health_rows: list[tuple[tuple, str]] = []
    for aid, a in accounts.items():
        paused = a.status == AccountStatus.PAUSED
        reason = _account_attention_reason(a, accounts)
        if a.uses_owner_session:
            # No session of its own, so no health row (the owner's covers the login) — but being paused, or a
            # configuration that cannot run, is the Page's own business and must not go unseen.
            severity, problems = (0 if reason else 2), ([("🔴", reason)] if reason else [])
        else:
            severity, rows = _account_health_signals(aid, a, sync_statuses, last_success_map)  # ONCE per account
            health_rows.append(((0 if paused else 1, severity, a.display_name.lower()), _account_health_row_html(aid, a, severity, rows)))
            problems = [(icon, text) for wanted in ("🔴", "🟡") for icon, text in rows if icon == wanted] if severity < 2 else []
            if reason and a.page_name and not paused:  # a Page's configuration problem is not one of the five signals
                problems.append(("🔴", reason))
        if problems:
            text = " · ".join(_localize_iso_timestamps_html(t) for _i, t in problems)
            problem_accounts.append(((0 if paused else 1, severity, a.display_name.lower()), (
                f'<li><span class="attn-text">{problems[0][0]} <b>{html.escape(a.display_name)}</b>: {text}</span>'
                '<a class="btn btn-secondary btn-small" href="/admin/accounts">Mở tài khoản</a></li>'
            )))
    health_rows.sort(key=lambda r: r[0])  # paused first, then worst health, then by name
    attention_items.extend(item for _order, item in sorted(problem_accounts, key=lambda r: r[0]))
    attention_html = (
        f'<div class="card home-attn"><h2>⚠️ Cần chú ý <span class="badge">{len(attention_items)}</span></h2>'
        f'<ul class="attn-list">{"".join(attention_items)}</ul></div>'
    ) if attention_items else ""

    # --- next posts
    name_lookup = _group_name_lookup()
    next_rows = "".join(
        f'<div class="upnext-row"><span class="upnext-time">{_local_dt_html(t.scheduled_at)}</span>'
        f'<span class="upnext-main">{_action_badge_html(t.action)}{_sponsor_badge_html(t)} {_sched_target_html(t, name_lookup)} '
        f'<span class="sched-acct">{html.escape(_account_label(t.account_id, accounts))}</span></span></div>'
        for t in pending[:4]
    )
    more = f'<a href="/admin/schedule">Xem tất cả ({len(pending)}) →</a>' if len(pending) > 4 else '<a href="/admin/schedule">Mở Lịch đăng →</a>'
    empty_upnext = "<p class=muted>Chưa có bài nào chờ đăng — bấm “＋ Tin tuyển dụng” hoặc “＋ Đăng bài” ở trên.</p>"
    upnext_html = (
        f'<div class="card"><h2>📅 Sắp đăng</h2>'
        f'{f"<div class=upnext-list>{next_rows}</div>" if next_rows else empty_upnext}'
        f'<div class="home-more">{more}</div></div>'
    )

    accounts_html = "".join(r[1] for r in health_rows) or '<p class="muted">Chưa có tài khoản nào</p>'
    # the date of the BUSINESS day the numbers describe (it starts 02:00 JST), not the JST calendar date
    day_jst = today.day_start + timedelta(hours=9)
    today_label = f"{_WEEKDAYS_VI[day_jst.weekday()]} {day_jst.strftime('%d/%m')}"
    return _layout(f"""
<div class="home-head">
  <div>
    <h1>Hôm nay</h1>
    <p class="page-desc">{today_label} · ngày làm việc tính từ 02:00 đến 02:00 hôm sau, giờ Nhật.</p>
  </div>
  <div class="home-quick">
    <a class="btn btn-small" href="/admin/post?tab=job">＋ Tin tuyển dụng</a>
    <a class="btn btn-secondary btn-small" href="/admin/post?tab=group">＋ Đăng bài</a>
  </div>
</div>
<div class="stat-row">{tiles}</div>
{attention_html}
{upnext_html}
<div class="card">
  <h2>👤 Tài khoản <span class="badge">{len(health_rows)}</span> <a class="home-manage" href="/admin/accounts">Quản lý →</a></h2>
  <div class="health-list">{accounts_html}</div>
</div>
<p class="muted home-foot">🔒 Trang quản trị nội bộ — đừng đưa ra internet: nó có quyền đăng bài thật lên Facebook.</p>
""", active="home", current_user=_build_current_user(request))


def _num_text(value) -> str:
    """A setting's value as it should read in a box: 15.0 -> "15", 0.0005 -> "0.0005", 8 -> "8" (the boxes used to
    show Python's float repr, "15,0" in a Vietnamese browser, for settings that are whole numbers)."""
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, int):
        return str(value)
    if isinstance(value, float):
        text = repr(value)                                    # the shortest text that reads back as the same float
        return text[:-2] if text.endswith(".0") else text
    return str(value)


# A "min"/"max" pair of settings reads as one row: "… (ms): [150] đến [450]". Found from the labels (the same text but
# "— tối thiểu (unit)" / "— tối đa (unit)", the field names the same but min <-> max); the two that don't follow that
# wording are listed by hand.
_PAIR_MIN_RE = re.compile(r"^(?P<base>.+?)\s*—\s*tối thiểu\s*\((?P<unit>[^)]*)\)(?P<rest>.*)$")
_PAIR_MAX_RE = re.compile(r"^(?P<base>.+?)\s*—\s*tối đa\s*\((?P<unit>[^)]*)\)(?P<rest>.*)$")
_PAIR_OVERRIDES: dict[str, list[tuple[str, str, str, str]]] = {
    "mouse": [("min_steps", "max_steps", "Số bước di chuyển chuột", "bước")],
    "data_sync": [("quiet_hour_start_local", "quiet_hour_end_local", "Khung giờ yên tĩnh — không đặt lịch (giờ địa phương, 0–23)", "giờ")],
}


def _differs_from_default(value, default) -> bool:
    """Numbers compare as numbers (15 == 15.0); anything else as is."""
    try:
        return float(value) != float(default)
    except (TypeError, ValueError):
        return value != default


def _config_pairs(prefix: str, fields: list[str], labels: dict[str, str]) -> dict[str, tuple[str, str, str]]:
    """first field -> (second field, shared label, unit) for every min/max pair among `fields`."""
    pairs: dict[str, tuple[str, str, str]] = {}
    for lo, hi, label, unit in _PAIR_OVERRIDES.get(prefix, []):
        if lo in fields and hi in fields:
            pairs[lo] = (hi, label, unit)
    for lo in fields:
        if lo in pairs:
            continue
        m = _PAIR_MIN_RE.match(labels.get(lo, ""))
        hi = re.sub(r"(^|_)min(_|$)", r"\1max\2", lo, count=1)
        if not m or hi == lo or hi not in fields:
            continue
        n = _PAIR_MAX_RE.match(labels.get(hi, ""))
        if n and (n["base"], n["unit"], n["rest"]) == (m["base"], m["unit"], m["rest"]):
            pairs[lo] = (hi, f'{m["base"]} ({m["unit"]}){m["rest"]}', m["unit"])
    return pairs


def _config_rows_html(config_cls, editable_fields, labels, current, prefix, field_subset=None, *, switch_attrs=None) -> str:
    """The rows of one settings card. A number is a box with a unit in the label; a min/max pair is ONE row with two
    boxes; every row that differs from the default says so, with the default and a "↺ đặt lại" (the page script keeps
    that live as you type). The technical key is the label's tooltip, not a line of text. `switch_attrs(field)` (the AI tab):
    extra attributes for a switch that saves ITSELF the moment it is flipped — such a switch carries no reset /
    unsaved-change tracking."""
    defaults = config_cls()
    names = list(field_subset if field_subset is not None else editable_fields)
    pairs = _config_pairs(prefix, names, labels)
    second = {pair[0] for pair in pairs.values()}

    def default_and_value(field):
        default = getattr(defaults, field)
        return default, current.get(field, default)

    def differs(field) -> bool:
        default, value = default_and_value(field)
        return _differs_from_default(value, default)

    def reset_html(changed: bool, shown_default: str) -> str:
        return (
            f'<span class="reset-wrap" data-reset-wrap{"" if changed else " hidden"}>đã chỉnh · mặc định <b>{html.escape(shown_default)}</b> '
            f'<button type="button" class="reset-link" data-reset>↺ đặt lại</button></span>'
        )

    def number_box(field: str, aria: str = "") -> str:
        default, value = default_and_value(field)
        aria_attr = f' aria-label="{html.escape(aria)}"' if aria else ""
        return (
            f'<input type="number" step="any" name="{prefix}__{field}" value="{html.escape(_num_text(value))}" '
            f'data-default="{html.escape(_num_text(default))}"{aria_attr}>'
        )

    rows = []
    for field_name in names:
        if field_name in second:
            continue
        label = labels.get(field_name, field_name)
        help_text = _FIELD_HELP.get(f"{prefix}__{field_name}") or _FIELD_DESCRIPTIONS.get(field_name, "")
        help_html = f'<div class="field-help">{html.escape(help_text)}</div>' if help_text else ""
        if field_name in pairs:
            other, pair_label, unit = pairs[field_name]
            default_lo, _ = default_and_value(field_name)
            default_hi, _ = default_and_value(other)
            changed = differs(field_name) or differs(other)
            rows.append(f"""
<div class="field-row" data-field-row>
  <div class="field-label" title="{html.escape(field_name)} · {html.escape(other)}">{html.escape(pair_label)}{help_html}<div class="field-key">{reset_html(changed, f"{_num_text(default_lo)} – {_num_text(default_hi)}")}</div></div>
  <div class="field-input pair-input">{number_box(field_name, "từ")}<span class="pair-sep">đến</span>{number_box(other, "đến")}<span class="pair-unit">{html.escape(unit)}</span></div>
</div>""")
            continue
        default, value = default_and_value(field_name)
        if field_name in _BOOL_FIELDS:
            checked = "checked" if value else ""
            if switch_attrs:
                extra, track = " " + switch_attrs(field_name), ""
            else:
                extra, track = "", f' data-default="{"true" if default else "false"}"'
            input_html = (
                f'<label class="switch"><input type="checkbox" name="{prefix}__{field_name}" value="true" {checked}{track}{extra}>'
                f'<span class="switch-slider"></span></label>'
            )
            reset = "" if switch_attrs else f'<div class="field-key">{reset_html(bool(value) != bool(default), "bật" if default else "tắt")}</div>'
        else:
            input_html = number_box(field_name)
            reset = f'<div class="field-key">{reset_html(differs(field_name), _num_text(default))}</div>'
        tracked = "" if switch_attrs else " data-field-row"
        rows.append(f"""
<div class="field-row"{tracked}>
  <div class="field-label" title="{html.escape(field_name)}">{html.escape(label)}{help_html}{reset}</div>
  <div class="field-input">{input_html}</div>
</div>""")
    return "".join(rows)


def _config_card_html(icon: str, title: str, body_html: str, *, grid: bool = True) -> str:
    """A settings card; `grid=False` when `body_html` already holds its own groups of rows."""
    body = f'<div class="field-grid">{body_html}</div>' if grid else body_html
    return f"""
<div class="card">
  <h2>{icon} {html.escape(title)}</h2>
  {body}
</div>"""


def _config_changed_count(config_cls, fields, current, prefix: str, labels: dict[str, str]) -> int:
    """How many ROWS of a section differ from the default (a min/max pair is one row), like the page script counts."""
    defaults = config_cls()
    pairs = _config_pairs(prefix, list(fields), labels)
    partner = {hi: lo for lo, (hi, _l, _u) in pairs.items()}
    changed_rows = set()
    for f in fields:
        if f in current and _differs_from_default(current[f], getattr(defaults, f)):
            changed_rows.add(partner.get(f, f))
    return len(changed_rows)


# The "Đồng bộ dữ liệu" tab: the fields grouped by what they are for. Fields not listed (a future one) land in "Nâng cao".
_SYNC_GROUPS: list[tuple[str, list[str], bool]] = [
    ("", ["enabled"], False),
    ("Chu kỳ", ["poll_interval_minutes", "due_check_interval_seconds"], False),
    ("Nhịp đăng", ["post_gap_min_minutes", "post_gap_max_minutes", "comment_gap_min_minutes", "comment_gap_max_minutes",
                   "quiet_hour_start_local", "quiet_hour_end_local"], False),
    ("Chọn việc để đăng", ["candidate_min_confidence", "candidate_max_age_days", "job_min_confidence"], False),
    ("Nâng cao", ["cache_retention_days", "max_overflow_business_days", "max_cursor_holdback_days"], True),
]

# Behaviour tab: what an owner changes comes first; the typing / pacing / mouse / scroll simulation is folded away.
_BEHAVIOR_PRIMARY = ("scheduling", "media", "safety_cooldown", "telegram")
_BEHAVIOR_ADVANCED = ("human_typing", "pacing", "mouse", "scroll")


def _ai_toggle_card_html(flash: str = "") -> str:
    """The two AI on/off switches: each saves the moment it is flipped (its own tiny request — read-merge-write of the
    data_sync section, so no other setting is touched), so this tab has ONE save button, the key card's own."""
    def switch_attrs(field: str) -> str:
        # Posts ONLY {field, value} (htmx would otherwise send the whole enclosing page form; and listing the checkbox in
        # hx-params would send the literal "undefined" for an unticked one — hence an explicit `value`). The id keeps
        # keyboard focus on the switch after the card is swapped.
        return (
            f'id="ai-toggle-{field}" hx-post="/admin/config/ai-toggle" hx-trigger="change" hx-target="#ai-toggle-card" '
            f'hx-swap="outerHTML" hx-params="field,value" hx-vals=\'js:{{field: "{field}", value: event.target.checked}}\''
        )

    rows = _config_rows_html(
        DataSyncConfig, EDITABLE_DATA_SYNC_FIELDS, _DATA_SYNC_LABELS, get_data_sync_overrides(), "data_sync",
        [f for f in EDITABLE_DATA_SYNC_FIELDS if f in _AI_TOGGLE_FIELDS], switch_attrs=switch_attrs,
    )
    return f"""
<div class="card" id="ai-toggle-card">
  <h2>🤖 Bật/tắt AI</h2>
  <p class="hint" style="margin-top:-6px;">Công tắc có hiệu lực ngay khi bật hoặc tắt — không cần bấm Lưu.</p>
  {flash}
  <div class="field-grid">{rows}</div>
</div>"""


@router.get("/config", response_class=HTMLResponse)
async def config_form(request: Request, saved: bool = False, tab: str = "behavior", _: None = Depends(_require_login)) -> str:
    sections = {sec[0]: sec for sec in _CONFIG_SECTIONS}
    current_of = {key: sec[6]() for key, sec in sections.items()}

    def card_for(key: str) -> str:
        _key, prefix, title, config_cls, editable_fields, labels, _get_fn, _save_fn = sections[key]
        rows_html = _config_rows_html(config_cls, editable_fields, labels, current_of[key], prefix)
        return _config_card_html(_ICONS.get(prefix, ""), title, rows_html)

    # --- tab "Cấu hình hành vi": the settings an owner touches first, then the human-simulation ones folded away
    primary_keys = [k for k in _BEHAVIOR_PRIMARY if k in sections]
    advanced_keys = [k for k in _BEHAVIOR_ADVANCED if k in sections]
    other_keys = [k for k in sections if k not in _BEHAVIOR_PRIMARY and k not in _BEHAVIOR_ADVANCED and k != "data_sync"]
    advanced_fields = sum(len(sections[k][4]) for k in advanced_keys)
    advanced_changed = sum(_config_changed_count(sections[k][3], sections[k][4], current_of[k], sections[k][1], sections[k][5]) for k in advanced_keys)
    changed_badge = f' <span class="badge badge-warn" data-adv-changed{"" if advanced_changed else " hidden"}>đã chỉnh {advanced_changed}</span>'
    advanced_html = f"""
<details class="cfg-adv">
  <summary><span>🧑 Giả lập hành vi người</span> <span class="badge">{len(advanced_keys)} nhóm · {advanced_fields} mục</span>{changed_badge}<span class="cfg-adv-note">nâng cao — mặc định đã ổn, chỉ đổi khi hiểu rõ</span></summary>
  <div class="cfg-adv-body">
    <p class="hint">Cách bot gõ phím, chờ, di chuột và cuộn trang để giống người thật. Các giá trị mặc định đã được chọn để bot không lộ dấu hiệu tự động; đổi lung tung có thể khiến tài khoản dễ bị Facebook nhận ra.</p>
    {"".join(card_for(k) for k in advanced_keys)}
  </div>
</details>""" if advanced_keys else ""
    behavior_cards = "".join(card_for(k) for k in primary_keys + other_keys) + advanced_html

    # --- tab "Đồng bộ dữ liệu bên B": grouped, the rarely-touched ones folded under "Nâng cao"
    _k, sync_prefix, sync_title, sync_cls, sync_fields, sync_labels, _g, _s = sections["data_sync"]
    sync_fields_here = [f for f in sync_fields if f not in _AI_TOGGLE_FIELDS]
    listed = {f for _title, group_fields, _adv in _SYNC_GROUPS for f in group_fields}
    sync_body = ""
    for group_title, group_fields, advanced in _SYNC_GROUPS:
        group_fields = [f for f in group_fields if f in sync_fields_here]
        if advanced:
            group_fields += [f for f in sync_fields_here if f not in listed]
        if not group_fields:
            continue
        rows = _config_rows_html(sync_cls, sync_fields, sync_labels, current_of["data_sync"], sync_prefix, group_fields)
        if advanced:
            sync_body += f'<details class="cfg-adv cfg-adv-inline"><summary><span>{html.escape(group_title)}</span><span class="cfg-adv-note">hiếm khi cần đổi</span></summary><div class="field-grid">{rows}</div></details>'
        else:
            title_html = f'<div class="cfg-group-title">{html.escape(group_title)}</div>' if group_title else ""
            sync_body += f'{title_html}<div class="field-grid">{rows}</div>'
    sync_cards = _config_card_html(_ICONS.get("data_sync", ""), sync_title, sync_body, grid=False)

    flash = '<p class="flash">✅ Đã lưu cấu hình. Áp dụng ngay từ lần đăng bài tiếp theo.</p>' if saved else ""

    active_tab = tab if tab in ("behavior", "sync", "ai", "content") else "behavior"

    def tab_btn(key: str, label: str) -> str:
        cls = "tab-btn active" if key == active_tab else "tab-btn"
        return f'<button type="button" class="{cls}" data-tab-target="tab-{key}">{label}</button>'

    def panel_attrs(key: str) -> str:
        return "" if key == active_tab else " hidden"

    return _layout(f"""
<h1>Cấu hình</h1>
<p class="page-desc">Thay đổi có hiệu lực ngay, không cần khởi động lại.</p>
{flash}
<form method="post" action="/admin/config" data-config-form>
<div data-tabs>
  <div class="tab-bar">
    {tab_btn("behavior", "🧑 Cấu hình hành vi")}
    {tab_btn("sync", "🔄 Đồng bộ dữ liệu")}
    {tab_btn("ai", "🤖 AI")}
    {tab_btn("content", "📝 Kho nội dung")}
  </div>

  <div class="tab-panel" id="tab-behavior"{panel_attrs("behavior")}>
    {behavior_cards}
  </div>

  <div class="tab-panel" id="tab-sync"{panel_attrs("sync")}>
    <p class="page-desc">Chu kỳ lấy việc từ bên B, khoảng cách giữa các bài và ngưỡng lọc. Kết quả lần đồng bộ gần nhất của từng tài khoản: <a href="/admin/accounts?tab=sync">Tài khoản → Đồng bộ</a>.</p>
    {sync_cards}
  </div>

  <div class="tab-panel" id="tab-ai"{panel_attrs("ai")}>
    <p class="page-desc">Nhà cung cấp AI, key, model và hai công tắc: AI soạn bài tin tuyển dụng, AI viết lại câu trả lời ứng viên.</p>
    {_ai_provider_card_html()}
    {_ai_toggle_card_html()}
  </div>

  <div class="tab-panel" id="tab-content"{panel_attrs("content")}>
    {_content_library_card_html(
        get_job_post_openers(_JOB_POST_OPENERS_DEFAULT),
        get_contact_cta(_CONTACT_CTA_DEFAULT),
        get_missing_info_suffixes(_MISSING_INFO_SUFFIXES_DEFAULT),
        get_candidate_reply_templates(_CANDIDATE_REPLY_TEMPLATES_DEFAULT),
        get_visa_type_names(_VISA_TYPE_NAMES_DEFAULT),
    )}
  </div>
</div>
<div class="form-actions savebar" id="config-generic-save-actions"{' hidden' if active_tab in ("content", "ai") else ''}>
  <span class="savebar-note" data-dirty-note>Chưa có thay đổi</span>
  <span class="savebar-buttons"><button type="button" class="btn-secondary btn-small" data-discard hidden>Bỏ thay đổi</button><button type="submit">Lưu cấu hình</button></span>
</div>
</form>
""", active="config", current_user=_build_current_user(request))


@router.post("/config/ai-toggle", response_class=HTMLResponse)
async def config_ai_toggle(request: Request, _: None = Depends(_require_login)) -> str:
    """Saves ONE AI switch the moment it is flipped (the AI tab has no generic save button): `field` and `value`
    ("true" / "false"). Read-merge-write: the data_sync section is REPLACED by save_data_sync_overrides(), so every
    other setting in it is carried over."""
    form = await request.form()
    field = str(form.get("field", "")).strip()
    if field not in _AI_TOGGLE_FIELDS:
        raise HTTPException(status_code=400, detail="Unknown switch")
    merged = dict(get_data_sync_overrides())
    merged[field] = str(form["value"]).lower() == "true" if "value" in form else f"data_sync__{field}" in form
    save_data_sync_overrides(merged)
    return _ai_toggle_card_html(flash='<p class="flash">✅ Đã lưu.</p>')


@router.post("/config")
async def config_save(request: Request, _: None = Depends(_require_login)) -> RedirectResponse:
    """Blindly casting every numeric field to `float` here used to corrupt
    any field whose dataclass actually declares `int` (found 2026-09-07:
    HumanMouseConfig.min_steps/max_steps went 8 -> 8.0 the very first time
    this route was ever used to save ANY section, since one submit here
    covers every section's fields at once — then silently crashed
    human_mouse_move()'s `range(1, steps + 1)` months later, only on the
    rare click distance that clamps to exactly one of those bounds, with
    'float' object cannot be interpreted as an integer). Casts to
    whatever type each dataclass field actually declares — via
    typing.get_type_hints(config_cls), NOT dataclasses.fields(config_cls)
    [i].type (2026-10-06 fix, real incident: that raw `.type` is the
    STRING `"int"`, not the actual `int` class, for any config module
    using `from __future__ import annotations` — DataSyncConfig among
    others — silently defeating the `is int` check below for every one
    of ITS fields despite the Sep-7 fix looking correct at the time
    against HumanMouseConfig, whose module doesn't use postponed
    annotations. Confirmed live: `max_overflow_business_days` round-
    tripped through this exact form once, got stored as `2.0`, and
    crashed every data_sync.sync_all() poll for 5 days straight before
    anyone noticed — see tasks.md's 2026-10-06 entry for the full trace.
    get_type_hints() resolves postponed/string annotations correctly
    regardless of which style a given config module happens to use)."""
    form = await request.form()
    for section_key, prefix, _title, config_cls, editable_fields, _labels, _get_fn, save_fn in _CONFIG_SECTIONS:
        field_types = get_type_hints(config_cls)
        values: dict = {}
        for field_name in editable_fields:
            form_name = f"{prefix}__{field_name}"
            if section_key == "data_sync" and field_name in _AI_TOGGLE_FIELDS:
                # These save themselves when flipped (config_ai_toggle). The page may be stale (flipped in another
                # tab, or a flip that never saved), so the page-wide save keeps what is STORED instead of the page.
                stored = get_data_sync_overrides()
                if field_name in stored:
                    values[field_name] = stored[field_name]
                continue
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
async def config_ai_provider_save(request: Request, _: None = Depends(_require_login)) -> str:
    """2026-09-25 fix (real bug, found while writing tests for this route,
    owner-confirmed intended design after asking): this card only ever
    tracks ONE effective override key at a time (switching provider
    replaces the whole "secrets" section — save_secrets_overrides() is a
    REPLACE, not a merge, same rule as every other save_*_overrides() in
    this project) — owner confirmed that losing a DIFFERENT provider's
    key when you switch to and save another one is correct, intended
    behavior, not a bug. But saving the CURRENTLY SELECTED provider with
    its own key field left blank used to silently wipe that key too,
    contradicting the field hint's old promise ("để trống = giữ nguyên
    key hiện tại" — leaving it blank keeps the current key). Owner's
    actual design has no partial-edit mode at all: every save must supply
    provider + model + key together as a complete set. So a blank key for
    the active provider is now rejected outright — nothing is saved —
    rather than either silently wiping it (old bug) or trying to guess
    and preserve an old value (not the intended design either)."""
    form = await request.form()
    provider_keys = [p["key"] for p in _AI_PROVIDERS]
    provider = str(form.get("ai_provider", "anthropic")).strip().lower()
    if provider not in provider_keys:
        provider = "anthropic"
    provider_info = next(p for p in _AI_PROVIDERS if p["key"] == provider)

    active_key_raw = str(form.get(provider_info["key_field"], "")).strip()
    if not active_key_raw:
        return _ai_provider_card_html(flash=f'<p class="error">⚠️ Cần nhập API key cho {html.escape(str(provider_info["label"]))} khi lưu.</p>')

    updates: dict[str, Any] = {"ai_provider": provider}
    for p in _AI_PROVIDERS:
        for field in (p["key_field"], p["model_field"], p["base_url_field"]):
            if not field:
                continue
            raw = str(form.get(field, "")).strip()
            if raw:
                updates[field] = raw
    save_secrets_overrides(updates)
    return _ai_provider_card_html(flash='<p class="flash">✅ Đã lưu cấu hình AI.</p>')


@router.post("/config/ai-provider/clear-key", response_class=HTMLResponse)
async def config_ai_provider_clear_key(request: Request, _: None = Depends(_require_login)) -> str:
    """2026-09-25: reverts the WHOLE ai-provider bundle back to
    defaults/.env, not just the one key field — owner-confirmed design
    (after I initially misread this as a bug and "fixed" it the other
    way, then had to reverse it): provider + model + key always travel
    together as one unit. The default state (no override saved at all —
    SecretsConfig()'s own dataclass defaults) is "anthropic" provider,
    blank model (content_strategist.py's own hardcoded default applies),
    and whatever ANTHROPIC_API_KEY says in .env (if anything) — exactly
    what get_active_ai_provider_config() already treats "no override" as
    meaning. So this clears the ENTIRE "secrets" section outright, the
    same intentional-empty-dict pattern accounts_delete()'s rate-limits
    reset and accounts_rate_limits_save()'s "Khôi phục mặc định" button
    already use elsewhere — not a partial write, a deliberate full
    reset."""
    save_secrets_overrides({})
    return _ai_provider_card_html(flash='<p class="flash">✅ Đã xoá — quay lại dùng cấu hình trong .env (nếu có) hoặc không dùng AI.</p>')


@router.post("/config/content-library", response_class=HTMLResponse)
async def config_content_library_save(request: Request, _: None = Depends(_require_login)) -> str:
    form = await request.form()
    openers, cta, suffixes, reply_templates, visa_names, extra_errors = _parse_content_library_form(form)
    errors = _validate_content_library(openers, cta, suffixes, reply_templates, visa_names, extra_errors)
    if errors:
        flash = '<div class="error">' + "<br>".join(html.escape(e) for e in errors) + "</div>"
        return _content_library_card_html(openers, cta, suffixes, reply_templates, visa_names, flash=flash, expand_all=True)

    save_job_post_openers(openers)
    save_contact_cta(cta)
    save_missing_info_suffixes(suffixes)
    save_candidate_reply_templates(reply_templates)
    save_visa_type_names(visa_names)
    return _content_library_card_html(
        get_job_post_openers(_JOB_POST_OPENERS_DEFAULT),
        get_contact_cta(_CONTACT_CTA_DEFAULT),
        get_missing_info_suffixes(_MISSING_INFO_SUFFIXES_DEFAULT),
        get_candidate_reply_templates(_CANDIDATE_REPLY_TEMPLATES_DEFAULT),
        get_visa_type_names(_VISA_TYPE_NAMES_DEFAULT),
        flash='<p class="flash">✅ Đã lưu Kho nội dung.</p>',
    )


@router.post("/config/content-library/reset", response_class=HTMLResponse)
async def config_content_library_reset(request: Request, _: None = Depends(_require_login)) -> str:
    form = await request.form()
    list_name = str(form.get("list_name", "")).strip()
    resetters = {
        "openers": reset_job_post_openers,
        "cta": reset_contact_cta,
        "suffixes": reset_missing_info_suffixes,
        "reply_templates": reset_candidate_reply_templates,
        "visa_names": reset_visa_type_names,
    }
    reset_fn = resetters.get(list_name)
    if reset_fn:
        reset_fn()
    return _content_library_card_html(
        get_job_post_openers(_JOB_POST_OPENERS_DEFAULT),
        get_contact_cta(_CONTACT_CTA_DEFAULT),
        get_missing_info_suffixes(_MISSING_INFO_SUFFIXES_DEFAULT),
        get_candidate_reply_templates(_CANDIDATE_REPLY_TEMPLATES_DEFAULT),
        get_visa_type_names(_VISA_TYPE_NAMES_DEFAULT),
        flash='<p class="flash">✅ Đã khôi phục mặc định.</p>' if reset_fn else '<div class="error">Danh sách không hợp lệ.</div>',
    )


def _account_id_error(account_id: str, existing: dict) -> str | None:
    if not account_id:
        return "account_id không được để trống"
    if not re.fullmatch(r"[a-z0-9_]+", account_id):
        return "account_id chỉ được dùng chữ thường, số và dấu gạch dưới (không dấu cách, không hoa)"
    if account_id in existing:
        return f"account_id '{account_id}' đã tồn tại"
    return None


def _account_modal_html(
    account_id: str = "", display_name: str = "", error: str | None = None, page_name: str = "",
    personal_name: str = "", owner_account_id: str = "", page_session_mode: str = "",
) -> str:
    """Renders the whole #modal-root swap for the "Đăng ký tài khoản mới"
    form — same pattern as _group_modal_html(): opened via GET (button
    below), redisplayed with a validation error on a bad POST without
    losing what was typed, and a successful POST returns something else
    entirely (_accounts_content_html's oob update) which is what actually
    closes it.

    The Facebook-Page fields (2026-10-31) live in a collapsed <details> so a
    normal personal-account registration stays a 3-field form; the section
    opens by itself when it already has input (a redisplay after an error).
    Its fields are ignored server-side unless a Page name is filled in."""
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    owner_options = "".join(
        f'<option value="{html.escape(aid)}"{" selected" if aid == owner_account_id else ""}>{html.escape(a.display_name)} ({html.escape(aid)})</option>'
        for aid, a in get_all_accounts().items() if not a.page_name
    )
    tier_options = "".join(
        f'<option value="{tier_key}"{" selected" if tier_key == DEFAULT_ACCOUNT_AGE_TIER else ""}>'
        f'{html.escape(label)} ({rl.posts_per_day} bài/ngày)</option>'
        for tier_key, (label, rl) in ACCOUNT_AGE_TIERS.items()
    )
    chosen_mode = page_session_mode if page_session_mode in PAGE_SESSION_MODES else PAGE_MODE_AUTO
    mode_cards = "".join(
        f'<label class="mode-card"><input type="radio" name="page_session_mode" value="{m}"{" checked" if m == chosen_mode else ""}>'
        f'<span><span class="mode-title">{html.escape(title)}</span><span class="mode-desc" style="display:block;">{html.escape(desc)}</span></span></label>'
        for m, (title, desc) in _PAGE_MODE_TEXT.items()
    )
    page_open = " open" if (page_name or personal_name or owner_account_id) else ""
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box modal-box-wide">
    <div class="modal-header">
      <h2>➕ Đăng ký tài khoản mới</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    <p class="page-desc">Tài khoản cá nhân: chỉ đăng ký sau khi đã chạy <code>python3 human_bot/bootstrap_login.py &lt;account_id&gt;</code> trên máy này để lưu phiên đăng nhập.</p>
    {err_html}
    <form method="post" action="/admin/accounts/add" hx-post="/admin/accounts/add" hx-target="#modal-root" hx-swap="innerHTML">
      <div class="field-grid">
        <div class="field-stack"><div class="field-label">ID tài khoản</div><div class="field-input"><input type="text" name="account_id" value="{html.escape(account_id)}" placeholder="vd: my_page" required pattern="[a-z0-9_]+"></div><div class="hint">Chữ thường, số, gạch dưới. Với tài khoản cá nhân: khớp với tên đã dùng ở bootstrap_login.py.</div></div>
        <div class="field-stack"><div class="field-label">Tên hiển thị</div><div class="field-input"><input type="text" name="display_name" value="{html.escape(display_name)}" placeholder="vd: Trang của tôi"></div></div>
        <div class="field-stack"><div class="field-label">Tuổi tài khoản Facebook</div><div class="field-input"><select name="age_tier">{tier_options}</select></div><div class="hint">Đặt giới hạn tốc độ ban đầu tương ứng (với Page: tuổi của Page).</div></div>
      </div>

      <details class="page-section"{page_open}>
        <summary>📄 Đây là tài khoản chạy bằng một Facebook Page <span class="muted">(không bắt buộc)</span></summary>
        <p class="hint">Page được tạo từ một tài khoản cá nhân và đăng nhập qua tài khoản đó. Khai báo liên kết này để bot luôn kiểm tra đang đúng là Page trước khi đăng, và để truy lỗi của Page từ tài khoản cá nhân. Bỏ trống Tên Page nếu đây là tài khoản cá nhân.</p>
        <div class="field-grid">
          <div class="field-stack"><div class="field-label">Tên Page</div><div class="field-input"><input type="text" name="page_name" value="{html.escape(page_name)}" placeholder="vd: Đơn Kỹ Sư Nhật"></div><div class="hint">Đúng như chữ trong nút "Switch to …" ở menu tài khoản Facebook khi bạn đang là tài khoản cá nhân.</div></div>
          <div class="field-stack"><div class="field-label">Page thuộc tài khoản cá nhân nào?</div><div class="field-input"><select name="owner_account_id"><option value="">— chọn —</option>{owner_options}</select></div></div>
          <div class="field-stack"><div class="field-label">Tên hồ sơ cá nhân của bạn</div><div class="field-input"><input type="text" name="personal_name" value="{html.escape(personal_name)}" placeholder="vd: Tu Nguyen"></div><div class="hint">Đúng như chữ trong nút "Switch to …" khi bạn đang ở Page. Gõ sai ở đây hoặc ở Tên Page thì bot sẽ từ chối đăng (không bao giờ đăng nhầm danh tính).</div></div>
          <div class="field-stack"><div class="field-label">Cách chạy tác vụ của Page</div><div class="field-input">{mode_cards}</div></div>
        </div>
      </details>

      <div class="form-actions" style="margin-top:16px;">
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
async def accounts_bootstrap_login_modal(account_id: str, _: None = Depends(_require_login)) -> str:
    return _bootstrap_login_modal_html(account_id)


@router.post("/accounts/bootstrap-login/start", response_class=HTMLResponse)
async def accounts_bootstrap_login_start(request: Request, _: None = Depends(_require_login)) -> str:
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
async def accounts_bootstrap_login_status(account_id: str, _: None = Depends(_require_login)) -> str:
    return _bootstrap_login_status_html(account_id)


@router.post("/accounts/bootstrap-login/confirm", response_class=HTMLResponse)
async def accounts_bootstrap_login_confirm(request: Request, _: None = Depends(_require_login)) -> str:
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
async def accounts_bootstrap_login_cancel(request: Request, _: None = Depends(_require_login)) -> str:
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    await bootstrap_login_sessions.cancel(account_id)
    return '<div id="bootstrap-login-status"><p class="page-desc">Đã đóng trình duyệt, chưa lưu phiên đăng nhập.</p></div>'


def _duration_vi(seconds) -> str:
    """1800 -> "30 phút", 45 -> "45 giây", 3900 -> "1 giờ 5 phút" (the page script has the same rule, for live typing)."""
    s = int(seconds)
    if s < 60:
        return f"{s} giây"
    minutes, rest = divmod(s, 60)
    if s < 3600:
        return f"{minutes} phút" + (f" {rest} giây" if rest else "")
    hours, minutes = divmod(s // 60, 60)
    return f"{hours} giờ" + (f" {minutes} phút" if minutes else "")


def _duration_range_vi(low, high) -> str:
    return f"≈ {_duration_vi(low)} – {_duration_vi(high)}"


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

    def box(field: str, aria: str = "") -> str:
        aria_attr = f' aria-label="{html.escape(aria)}"' if aria else ""
        return f'<input type="number" step="1" min="0" name="{field}" value="{getattr(limits, field)}" required{aria_attr}>'

    def count_row(field: str) -> str:
        return f'''<div class="field-row">
  <div class="field-label" title="{field}">{html.escape(_RATE_LIMITS_LABELS[field])}</div>
  <div class="field-input">{box(field)}</div>
</div>'''

    def delay_row(label: str, lo: str, hi: str) -> str:
        tip = f"{_RATE_LIMITS_LABELS[lo]} · {_RATE_LIMITS_LABELS[hi]}"
        return f'''<div class="field-row" data-duration-pair>
  <div class="field-label" title="{html.escape(tip)}">{html.escape(label)}<div class="field-help" data-duration-hint>{_duration_range_vi(getattr(limits, lo), getattr(limits, hi))}</div></div>
  <div class="field-input pair-input">{box(lo, f"{label}: tối thiểu (giây)")}<span class="pair-sep">đến</span>{box(hi, f"{label}: tối đa (giây)")}<span class="pair-unit">giây</span></div>
</div>'''

    delay_pairs = [("Giữa 2 bài đăng", "post_min_delay_seconds", "post_max_delay_seconds"),
                   ("Giữa 2 comment", "comment_min_delay_seconds", "comment_max_delay_seconds")]
    count_fields = ["posts_per_day", "comments_per_hour", "comments_per_day", "likes_per_hour", "max_groups_per_post"]
    known = set(count_fields) | {f for _l, lo, hi in delay_pairs for f in (lo, hi)}
    count_fields += [f for f in _RATE_LIMITS_LABELS if f not in known]       # a field added later still gets its box
    rows = (
        '<div class="cfg-group-title">Số lượng tối đa</div>'
        + "".join(count_row(f) for f in count_fields)
        + '<div class="cfg-group-title">Khoảng chờ giữa 2 hành động</div>'
        + "".join(delay_row(*pair) for pair in delay_pairs)
    )
    reset_note = (
        '<p class="page-desc">Tài khoản này đang dùng giá trị tuỳ chỉnh riêng — bấm "Khôi phục mặc định" để quay lại giá trị chuẩn.</p>'
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
        f'''<button type="button" class="btn-small btn-secondary" data-apply-tier
        data-tier_key="{tier_key}"
        {" ".join(f'data-{field}="{getattr(rl, field)}"' for field in _RATE_LIMITS_LABELS if field != "max_groups_per_post")}
        >{html.escape(label)} ({rl.posts_per_day} bài/ngày)</button>'''
        for tier_key, (label, rl) in ACCOUNT_AGE_TIERS.items()
    )
    return f"""<div id="rate-limits-body">
    {reset_note}
    {err_html}
    <div class="rl-tiers"><span class="fg-label">Áp nhanh theo tuổi tài khoản Facebook</span><div class="rl-tier-buttons">{tier_buttons}</div></div>
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
      <!-- DOM order = Lưu first: pressing Enter in a number box submits with the FIRST submit button, and that must be
           Lưu, never "Khôi phục mặc định" (which throws the typed values away). CSS row-reverse puts them back in the
           order people expect: reset on the left, Huỷ then Lưu on the right. -->
      <div class="form-actions rl-actions">
        <span class="rl-actions-main">
          <button type="submit">Lưu</button>
          <button type="button" class="btn-secondary" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        </span>
        <button type="submit" name="reset" value="1" class="btn-secondary">Khôi phục mặc định</button>
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
    sponsored_only_ids = get_sponsored_only_account_ids()
    flash = '<p class="flash">✅ Đã lưu.</p>' if saved else ""

    def _toggle_switch(*, aid: str, checked: bool, enable_url: str, disable_url: str,
                        title: str, confirm_on_check: str | None = None,
                        confirm_on_uncheck: str | None = None) -> str:
        """One checkbox-styled switch that fires the right hx-post the
        instant it's flipped — replaces the old badge + separate button
        pair. Which URL to hit is already known at RENDER time (this
        row's current `checked` state), so the checkbox always posts to
        whichever endpoint flips it to the OTHER state; no client-side
        JS needed to compute that. `title` doubles as the tooltip and
        the accessible name (aria-label) — the column header next to it
        carries the same explanation for anyone just glancing at the
        table rather than hovering. `confirm_on_check`/`confirm_on_uncheck`
        fire hx-confirm only for whichever direction is actually the
        consequential one for that particular switch (e.g. turning sync
        OFF matters more than turning it back on; turning sponsored-only
        ON matters more than turning it back off) — pass only the one
        that applies, leave the other None."""
        url = disable_url if checked else enable_url
        confirm_text = confirm_on_uncheck if checked else confirm_on_check
        confirm_attr = f' hx-confirm="{html.escape(confirm_text)}"' if confirm_text else ""
        checked_attr = "checked" if checked else ""
        return (
            f'<label class="switch" title="{html.escape(title)}">'
            f'<input type="checkbox" {checked_attr} aria-label="{html.escape(title)}" '
            f'hx-post="{url}" hx-vals=\'{{"account_id": "{html.escape(aid)}"}}\' '
            f'hx-target="#sync-content" hx-swap="outerHTML" hx-trigger="change"{confirm_attr}>'
            f'<span class="switch-slider"></span></label>'
        )

    rows = []
    for aid, account, child in _account_rows_in_order(accounts):
        is_paused = account.status == AccountStatus.PAUSED
        # Paused blocks EVERY action (agent.py's run_task() rejects any
        # status != ACTIVE), sync included — so it already can't run
        # regardless of this override, and the toggle is replaced with a
        # plain note instead of an actionable switch.
        if account.status == AccountStatus.DISABLED:
            sync_cell = '<span class="acct-note">đã tắt — không sync</span>'
        elif is_paused:
            sync_cell = '<span class="acct-note">tạm dừng — đã chặn sync</span>'
        else:
            sync_cell = _toggle_switch(
                aid=aid, checked=aid not in sync_disabled_ids,
                enable_url="/admin/accounts/sync-enable", disable_url="/admin/accounts/sync-disable",
                title="Tự động lấy job/ứng viên mới từ bên B cho tài khoản này",
                confirm_on_uncheck=(
                    f"Tắt đồng bộ dữ liệu bên B cho tài khoản {aid}? Tài khoản vẫn hoạt động bình thường "
                    "(đăng tay, comment...) — chỉ riêng việc tự lấy job/ứng viên mới từ bên B bị bỏ qua."
                ),
            )

        # sponsored_only (2026-09-16): a dedicated switch, independent of
        # the sync on/off toggle above — even a paused account can keep
        # its sponsored_only flag (it just has no effect while paused,
        # same as every other setting), so this doesn't need the
        # is_paused branch above.
        sponsored_cell = _toggle_switch(
            aid=aid, checked=aid in sponsored_only_ids,
            enable_url="/admin/accounts/sponsored-only-enable", disable_url="/admin/accounts/sponsored-only-disable",
            title="Chỉ nhận job sponsored_by từ bên B — không bao giờ nhận job thường",
            confirm_on_check=(
                f"Tài khoản {aid} sẽ CHỈ nhận job sponsored_by từ bên B — không nhận job thường nữa, "
                "kể cả khi còn dư hạn mức ngày. Dùng để luôn chừa chỗ phản ứng nhanh khi có job sponsored gấp."
            ),
        )

        entry = statuses.get(aid)
        if entry is None:
            last_run_cell = '<span class="acct-note">chưa chạy lần nào</span>'
        elif entry.get("status") == "ok":
            last_run_cell = (
                f'<span class="st st-ok">✅ OK</span> <span class="acct-aid">{_local_dt_html(entry.get("last_run_at"))}</span>'
                f'<div class="acct-note">{entry.get("jobs_fetched", 0)} job · {entry.get("candidates_fetched", 0)} ứng viên lấy về · '
                f'{entry.get("scheduled_posts", 0)} bài + {entry.get("scheduled_comments", 0)} bình luận mới lên lịch</div>'
            )
        else:
            last_run_cell = (
                f'<span class="st st-paused">⚠️ Lỗi</span> <span class="acct-aid">{_local_dt_html(entry.get("last_run_at"))}</span>'
                f'<div class="acct-note acct-sess-bad">{html.escape(str(entry.get("error", "")))}</div>'
            )

        name = f'{"📄 " if account.page_name else ""}{html.escape(account.display_name)}'
        rows.append(f"""
<tr class="{'sync-child' if child else ''}">
  <td><span class="acct-name">{name}</span> <span class="acct-aid">{html.escape(aid)}</span></td>
  <td>{sync_cell}</td>
  <td>{sponsored_cell}</td>
  <td>{last_run_cell}</td>
</tr>""")

    table = f"""
<div class="table-scroll">
  <table class="data-table sync-table">
    <thead><tr>
      <th>Tài khoản</th>
      <th title="Tắt thì tài khoản này ngừng tự lấy job/ứng viên mới từ bên B — vẫn đăng/bình luận bình thường qua /admin/post.">Đồng bộ ⓘ</th>
      <th title="Bật thì tài khoản này CHỈ nhận job có sponsored_by (tin trả tiền), không bao giờ nhận job thường.">Chỉ sponsored ⓘ</th>
      <th>Lần đồng bộ gần nhất</th>
    </tr></thead>
    <tbody>{"".join(rows) or '<tr><td colspan="4" class="empty-state">Chưa có tài khoản nào</td></tr>'}</tbody>
  </table>
</div>"""

    oob_attr = ' hx-swap-oob="true"' if oob else ""
    count = f'<span class="acct-count">{len(accounts)} tài khoản</span>' if accounts else ""
    return f"""<div id="sync-content"{oob_attr}>
{flash}
<div class="card">
  <div class="acct-head">
    <div>{count} <span class="acct-aid">· tự nhận job / ứng viên mới từ bên B</span></div>
    <a class="btn btn-secondary btn-small" href="/admin/config?tab=sync">⚙️ Cấu hình chu kỳ &amp; ngưỡng lọc</a>
  </div>
  <details class="mini-help" style="margin:0 0 10px;"><summary>Hai công tắc này làm gì?</summary>
    <div class="hint"><strong>Đồng bộ</strong>: tắt thì tài khoản ngừng tự lấy job/ứng viên mới từ bên B — vẫn đăng/bình luận bình thường qua /admin/post.<br>
    <strong>Chỉ sponsored</strong>: bật thì tài khoản CHỈ nhận job có <code>sponsored_by</code> (tin trả tiền), không bao giờ nhận job thường dù còn dư hạn mức ngày — để luôn chừa sẵn chỗ cho job sponsored đến gấp.</div>
  </details>
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


_PAGE_MODE_TEXT: dict[str, tuple[str, str]] = {
    PAGE_MODE_AUTO: (
        "Tự động (khuyên dùng)",
        "Dùng phiên riêng của Page; nếu phiên đó lỗi thì tự dùng phiên của tài khoản cá nhân.",
    ),
    PAGE_MODE_OWN_SESSION: (
        "Chỉ phiên của Page",
        "Chỉ dùng phiên riêng của Page (file phiên đã ở sẵn danh tính Page). Lỗi thì dừng, không dự phòng.",
    ),
    PAGE_MODE_OWNER_SESSION: (
        "Chỉ phiên cá nhân",
        "Mượn phiên của tài khoản cá nhân: chuyển sang Page, làm xong chuyển về. Không cần file phiên riêng.",
    ),
}


def _row_menu_html(items: list[str]) -> str:
    """The "⋯" menu at the end of a row (a <details>: no JS to open it; the page's small script closes it on an outside click)."""
    return (
        '<details class="row-menu"><summary aria-label="Thêm thao tác" title="Thêm thao tác">⋯</summary>'
        f'<div class="row-menu-pop">{"".join(items)}</div></details>'
    )


def _menu_form(
    url: str, hidden: dict[str, str], label: str, small: str, *, target: str = "#accounts-content",
    confirm: str = "", danger: bool = False, title: str = "", swap: str = "outerHTML", close_menu: bool | None = None,
) -> str:
    """One item of a "⋯" menu: a POST (htmx swaps `target`), optionally confirmed first. `url`, `label`,
    `small` and `confirm` are HTML the CALLER built — html.escape() every name or user-supplied text you put in
    them; `title` and the hidden inputs are escaped here."""
    attrs = f' hx-confirm="{confirm}"' if confirm else ""
    tip = f' title="{html.escape(title)}"' if title else ""
    inputs = "".join(f'<input type="hidden" name="{html.escape(k)}" value="{html.escape(v)}">' for k, v in hidden.items())
    # a menu item that opens a modal must not leave its menu open behind it (default: exactly when it targets the
    # modal slot; the other targets replace the whole list, menu included)
    if close_menu is None:
        close_menu = target == "#modal-root"
    close = ' onclick="this.closest(\'details\').removeAttribute(\'open\')"' if close_menu else ""
    return (
        f'<form method="post" action="{url}" hx-post="{url}" hx-target="{target}" hx-swap="{swap}"{attrs}>{inputs}'
        f'<button type="submit" class="menu-item{" danger" if danger else ""}"{tip}{close}>{label}<small>{small}</small></button></form>'
    )


def _menu_button(attrs: str, label: str, small: str) -> str:
    """A "⋯" menu item that opens something (a modal) instead of posting; closes the menu behind it.
    `attrs`, `label` and `small` are HTML the CALLER built (escape any name you put in them)."""
    return (
        f'<button type="button" class="menu-item" {attrs} onclick="this.closest(\'details\').removeAttribute(\'open\')">'
        f'{label}<small>{small}</small></button>'
    )


def _account_rows_in_order(accounts: dict) -> list[tuple[str, Any, bool]]:
    """(account_id, account, nested?) — a Page sits right under the personal account that owns it; a Page
    without a usable owner (missing, or itself a Page) comes last, on its own. Shared by every
    per-account list on the Tài khoản page so they read the same."""
    out: list[tuple[str, Any, bool]] = []
    nested: set[str] = set()
    for aid, a in accounts.items():
        if a.page_name:
            continue
        out.append((aid, a, False))
        for page in pages_of(aid, accounts):
            nested.add(page.account_id)
            out.append((page.account_id, page, True))
    out.extend((aid, a, False) for aid, a in accounts.items() if a.page_name and aid not in nested)
    return out


def _session_note(tone: str, text_html: str) -> str:
    """`text_html` is already HTML-safe (static text, or built with html.escape'd names)."""
    return f'<span class="acct-sess acct-sess-{tone}">{text_html}</span>'


def _page_session_note(a, accounts: dict) -> tuple[str, bool]:
    """What a Page's login state means for the chosen mode, as (one short line, whether it needs
    attention). The identity guard refuses every action without an owner / personal name, so that
    is said here too, not only in the name cell."""
    has_session = a.storage_state_path.exists()
    owner = accounts.get(a.owner_account_id)
    owner_name = html.escape(owner.display_name) if owner else "tài khoản cá nhân"
    if owner is None or owner.page_name or not a.personal_name:
        return _session_note("bad", "thiếu tài khoản cá nhân sở hữu / tên hồ sơ cá nhân — bot sẽ từ chối đăng"), True
    if a.page_session_mode == PAGE_MODE_OWNER_SESSION and owner.status != AccountStatus.ACTIVE:
        word = "đang tắt" if owner.status == AccountStatus.DISABLED else "đang tạm dừng"
        return _session_note("warn", f"{owner_name} {word} — không dùng được phiên của tài khoản đó"), True
    if a.page_session_mode == PAGE_MODE_AUTO and not has_session and owner.status != AccountStatus.ACTIVE:
        word = "đang tắt" if owner.status == AccountStatus.DISABLED else "đang tạm dừng"
        return _session_note("bad", f"chưa có phiên riêng và {owner_name} {word} — Page chưa chạy được"), True
    if a.page_session_mode == PAGE_MODE_OWNER_SESSION:
        if has_session:
            return _session_note("ok", f"dùng phiên của {owner_name}"), False
        return _session_note("bad", f"{owner_name} chưa có phiên đăng nhập"), True
    if has_session:
        return _session_note("ok", "phiên riêng OK"), False
    if a.page_session_mode == PAGE_MODE_AUTO:
        return _session_note("warn", f"chưa có phiên riêng — đang dùng phiên của {owner_name}"), False
    return _session_note("bad", "chưa có phiên riêng"), True


def _account_attention_reason(a, accounts: dict) -> str | None:
    """Why a person has to look at this account's SET-UP (None = nothing to do): paused, not logged in, a Page that
    cannot run. The accounts list counts exactly these ("N cần chú ý"); the home page adds the runtime health
    signals (browser died, silent for days, sync errors...) on top. An account switched off on purpose never
    needs attention."""
    if a.status == AccountStatus.DISABLED:
        return None
    if a.status == AccountStatus.PAUSED:
        return "đang tạm dừng"
    if a.page_name:
        return "Page chưa cấu hình đủ hoặc chưa chạy được" if _page_session_note(a, accounts)[1] else None
    if not a.storage_state_path.exists():
        return "chưa đăng nhập"
    return None


def _page_howto_html(aid: str, a) -> str:
    """How to create the Page's OWN session — only while it is missing and the mode could use one."""
    if a.storage_state_path.exists() or a.page_session_mode == PAGE_MODE_OWNER_SESSION or not a.owner_account_id:
        return ""
    # shlex.quote: page_name is free text and these lines are meant to be
    # copy-pasted into a terminal (ids are pattern-restricted, quoted anyway).
    q_owner, q_aid, q_page = shlex.quote(a.owner_account_id), shlex.quote(aid), shlex.quote(a.page_name)
    return (
        '<details class="mini-help"><summary>Cách tạo phiên riêng cho Page</summary>'
        f'<code>{html.escape(f"python3 -m human_bot.smoke_test.check_page_identity switch --account {q_owner} --page {q_page}")}</code>'
        f'<code>{html.escape(f"mkdir -p accounts/{q_aid} && cp accounts/{q_owner}/_page_probe_state.json accounts/{q_aid}/storage_state.json")}</code>'
        '</details>'
    )


def _page_mode_picker_html(aid: str, a) -> str:
    options = "".join(
        f'<option value="{m}"{" selected" if m == a.page_session_mode else ""} title="{html.escape(desc)}">{html.escape(title)}</option>'
        for m, (title, desc) in _PAGE_MODE_TEXT.items()
    )
    return (
        f'<form method="post" action="/admin/accounts/page-mode" class="acct-mode">'
        f'<input type="hidden" name="account_id" value="{html.escape(aid)}">'
        f'<label class="acct-aid" for="mode-{html.escape(aid)}">Cách chạy</label>'
        f'<select class="mode-select" id="mode-{html.escape(aid)}" name="mode" aria-label="Cách chạy" onchange="this.form.submit()">{options}</select></form>'
    )


def _status_cell(aid: str, a) -> str:
    """The status badge plus the one note a person needs before acting: why it is paused / since
    when it is off / the cooldown window after a resume (docs/skills/anomaly-detection.md and
    human_bot/safety_cooldown_config.py for why a resume must not jump straight back to full speed)."""
    if a.status == AccountStatus.PAUSED:
        badge = '<span class="st st-paused">⏸ Tạm dừng</span>'
        info = get_pause_info(aid)
        note = ""
        if info:
            reason_txt = html.escape(info["reason"] or "không rõ (tạm dừng thủ công)")
            note = f'<div class="acct-note">từ {_local_dt_html(info["paused_at"])} — {reason_txt}</div>'
        return badge + note
    if a.status == AccountStatus.DISABLED:
        off_info = get_disabled_info(aid) or {}
        since = f" từ {_local_dt_html(off_info['disabled_at'])}" if off_info.get("disabled_at") else ""
        return f'<span class="st st-off">⏻ Đã tắt</span><div class="acct-note">Tắt chủ động{since}</div>'
    badge = '<span class="st st-ok">● Hoạt động</span>'
    cooldown = get_resume_cooldown_info(aid)
    if not cooldown:
        return badge
    week = cooldown.get("week")
    base_tier_label = ACCOUNT_AGE_TIERS.get(cooldown.get("base_tier"), (cooldown.get("base_tier") or "?", None))[0]
    week_txt = f"tuần {week}/2 — mức sàn thấp nhất" if week == 1 else f"tuần {week}/2 — đã nhích lên 1 bậc"
    return badge + (
        f'<div class="acct-note">🧊 Đang hạ nhiệt ({html.escape(str(week_txt))}), xong vào {_local_dt_html(cooldown.get("until"))}, '
        f'sẽ quay về mức "{html.escape(base_tier_label)}" — lần trước bị dừng vì: {html.escape(cooldown.get("reason") or "không rõ")}</div>'
    )


def _acct_row_html(aid: str, a, accounts: dict, registered_ids: set, *, child: bool) -> tuple[str, bool]:
    """One account = one row: who (name, id, and for a Page how it runs), how it is doing (status +
    one note), and what to do (ONE contextual button when something needs doing, plus a "⋯"
    menu for the rest). Returns (html, needs attention)."""
    esc = html.escape
    is_page = bool(a.page_name)

    # --- who
    title_tip = f"Xem báo cáo của {a.display_name}"
    if is_page:
        title_tip = f"Page: {a.page_name}" + (f" · hồ sơ cá nhân: {a.personal_name}" if a.personal_name else "") + " — xem báo cáo"
    meta = ""
    if is_page:
        owner = accounts.get(a.owner_account_id)
        warn = []
        if owner is None or owner.page_name:
            warn.append("⚠ chưa liên kết tài khoản cá nhân")
        if not a.personal_name:
            warn.append("⚠ chưa khai báo tên hồ sơ cá nhân — bot sẽ từ chối đăng")
        meta = f'<div class="acct-meta">{_page_mode_picker_html(aid, a)}</div>'
        if warn:
            meta += f'<div class="acct-meta warn">{esc(" · ".join(warn))}</div>'
    who = (
        f'<div class="acct-title">{"📄 " if is_page else ""}'
        f'<a class="acct-name" href="/admin/reports?account_id={esc(aid)}" title="{esc(title_tip)}">{esc(a.display_name)}</a>'
        f'<span class="acct-aid">{esc(aid)}</span></div>{meta}'
    )

    # --- how it is doing
    status = _status_cell(aid, a)
    howto = ""
    needs_login = False
    if is_page:
        note, _page_attn = _page_session_note(a, accounts)
        howto = _page_howto_html(aid, a)
    elif a.storage_state_path.exists():
        note = _session_note("ok", "phiên đăng nhập OK")
    else:
        note = _session_note("bad", "chưa đăng nhập")
        needs_login = True
    attention = _account_attention_reason(a, accounts) is not None  # one definition, shared with the home page
    session_line = f'<div class="acct-note">{note}</div>'

    # --- what to do
    login_get = (
        f'hx-get="/admin/accounts/bootstrap-login-modal?account_id={esc(aid)}" hx-target="#modal-root" hx-swap="innerHTML"'
    )
    if a.status == AccountStatus.PAUSED:
        # Resuming goes through resume_account() so the post-resume cooldown applies.
        primary = (
            f'<form method="post" action="/admin/accounts/resume" hx-post="/admin/accounts/resume" hx-target="#accounts-content" '
            f'hx-swap="outerHTML" style="margin:0;" title="Bật lại sau khi tạm dừng vì nghi vi phạm: tài khoản sẽ chạy giới hạn thấp '
            f'vài ngày (hạ nhiệt) trước khi về mức bình thường."><input type="hidden" name="account_id" value="{esc(aid)}">'
            f'<button type="submit" class="btn-small">▶ Kích hoạt lại</button></form>'
        )
    elif a.status == AccountStatus.DISABLED:
        primary = (
            f'<form method="post" action="/admin/accounts/enable" hx-post="/admin/accounts/enable" hx-target="#accounts-content" '
            f'hx-swap="outerHTML" style="margin:0;" title="Bật lại ngay, chạy đủ giới hạn bình thường (không hạ nhiệt vì tài khoản '
            f'không có vấn đề gì)."><input type="hidden" name="account_id" value="{esc(aid)}">'
            f'<button type="submit" class="btn-small">▶ Bật lại</button></form>'
        )
    elif needs_login:
        primary = f'<button type="button" class="btn-small" {login_get}>🌐 Đăng nhập</button>'
    else:
        primary = ""

    items = [_menu_button(
        f'hx-get="/admin/accounts/rate-limits-modal?account_id={esc(aid)}" hx-target="#modal-root" hx-swap="innerHTML"',
        "⏱ Giới hạn tốc độ", "Số bài / bình luận tối đa mỗi ngày và khoảng nghỉ",
    )]
    if not is_page and not (needs_login and a.status == AccountStatus.ACTIVE):
        # Reachable for every personal account — including one that is off / paused and has no session (its
        # button shows Resume / Enable instead). Only skipped when the row's own button already is "Đăng nhập".
        items.append(_menu_button(
            login_get,
            "🌐 Đăng nhập &amp; lưu phiên" if needs_login else "🌐 Đăng nhập lại &amp; lưu phiên",
            "Chưa có phiên đăng nhập — cần để bot dùng tài khoản này" if needs_login else "Khi phiên hết hạn hoặc muốn đổi tài khoản Facebook",
        ))
    if a.status == AccountStatus.ACTIVE:
        items.append(_menu_form(
            "/admin/accounts/disable", {"account_id": aid}, "⏻ Tắt", "Nghỉ có chủ đích · bật lại là chạy ngay, không hạ nhiệt",
            confirm=(
                f"Tắt tài khoản {esc(aid)}? Sẽ không chạy tác vụ nào cho tới khi bạn bật lại; bài đến giờ trong lúc tắt sẽ "
                "chuyển sang mục &quot;Quá hạn&quot; của Lịch đăng để bạn xếp lại. Bật lại là chạy ngay, không bị hạ nhiệt."
            ),
            title="Tắt chủ động (không có vấn đề gì). Bật lại là chạy ngay đủ giới hạn.",
        ))
        items.append(_menu_form(
            "/admin/accounts/pause", {"account_id": aid}, "⚠ Tạm dừng", "Nghi bị Facebook hạn chế · kích hoạt lại phải hạ nhiệt vài ngày",
            confirm=(
                f"Tạm dừng tài khoản {esc(aid)} vì nghi bị Facebook hạn chế/vi phạm? Dùng khi có sự cố thật: khi kích hoạt lại, "
                "tài khoản sẽ phải chạy giới hạn thấp vài ngày (hạ nhiệt). Nếu chỉ muốn nghỉ thì dùng nút Tắt."
            ),
            title="Dùng khi nghi tài khoản có vấn đề (checkpoint, bị hạn chế). Kích hoạt lại sẽ phải hạ nhiệt vài ngày.",
        ))
    # "Xoá" works on EVERY account, code-level ones included (see human_bot/runtime_config.py's
    # set_account_removed) — a code-level entry can't actually be deleted from a running process,
    # but this hides it from every list/lookup the same way, undoable by registering the same
    # account_id again.
    is_runtime = aid in registered_ids
    delete_confirm = (
        f"Xoá tài khoản {esc(aid)} khỏi danh sách? Sẽ huỷ mọi bài đang chờ lịch của tài khoản này "
        "và xoá danh sách nhóm đã lưu. File storage_state.json (phiên đăng nhập) sẽ KHÔNG bị xoá."
        if is_runtime
        else f"Ẩn tài khoản {esc(aid)} (khai báo trong human_bot/config.py) khỏi human_bot? "
        "Sẽ huỷ mọi bài đang chờ lịch và xoá danh sách nhóm đã lưu. Muốn dùng lại: đăng ký lại đúng "
        "account_id này ở đây. File storage_state.json sẽ KHÔNG bị xoá."
    )
    items.append('<hr class="row-menu-sep">')
    items.append(_menu_form(
        "/admin/accounts/delete", {"account_id": aid}, "🗑 Xoá", "Bỏ khỏi danh sách (không xoá file phiên đăng nhập)",
        confirm=delete_confirm, danger=True,
    ))
    source = "đăng ký ở /admin/accounts" if is_runtime else "khai báo trong human_bot/config.py"
    items.append(f'<div class="row-menu-info">Mức giới hạn: {esc(_account_age_tier_label(a.rate_limits))} · {esc(source)}</div>')
    menu = _row_menu_html(items)

    row = (
        f'<li class="acct-row{" acct-child" if child else ""}" data-account="{esc(aid)}">'
        f'<div class="acct-who">{who}</div>'
        f'<div class="acct-state">{status}{session_line}{howto}</div>'
        f'<div class="acct-actions">{primary}{menu}</div></li>'
    )
    return row, attention


def _accounts_content_html(saved: bool = False, error: str | None = None, oob: bool = False) -> str:
    accounts = get_all_accounts()
    registered_ids = {a["account_id"] for a in get_registered_accounts()}
    flash = '<p class="flash">✅ Đã lưu.</p>' if saved else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""

    rows, attention = [], 0
    for aid, a, child in _account_rows_in_order(accounts):
        row, attn = _acct_row_html(aid, a, accounts, registered_ids, child=child)
        rows.append(row)
        attention += int(attn)

    count = f'<span class="acct-count">{len(accounts)} tài khoản</span>' if accounts else ""
    attn = f' · <span class="acct-attn">{attention} cần chú ý</span>' if attention else ""
    body = (
        f'<ul class="acct-list">{"".join(rows)}</ul>' if rows
        else '<div class="empty-state">Chưa có tài khoản nào — bấm “Đăng ký tài khoản mới” để thêm.</div>'
    )
    oob_attr = ' hx-swap-oob="true"' if oob else ""
    return f"""<div id="accounts-content"{oob_attr}>
{flash}{err}

<div class="card">
  <div class="acct-head">
    <div>{count}{attn}</div>
    <button type="button" class="btn-small"
            hx-get="/admin/accounts/add-modal" hx-target="#modal-root" hx-swap="innerHTML">➕ Đăng ký tài khoản mới</button>
  </div>
  {body}
</div>
</div>"""


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(
    request: Request, saved: bool = False, error: str | None = None, tab: str = "accounts",
    tested: str | None = None, test_failed: str | None = None, telegram_error: str | None = None,
    _: None = Depends(_require_login),
) -> str:
    active_tab = tab if tab in ("accounts", "sync", "telegram") else "accounts"
    # Gated on active_tab=="accounts" (self-review follow-up) — same
    # reasoning as the telegram tab's own telegram_flash/telegram_err
    # below: a save/error from the SYNC or TELEGRAM tab's own mutating
    # routes still passes `saved`/`error` as generic query params on its
    # redirect, and since tab-switching is pure client-side (no refetch
    # — see initTabs()), an ungated flash here would bake a stale
    # "✅ Đã lưu." into the accounts panel even while it's hidden, only
    # to surface the moment someone later clicks back to that tab.
    content = _accounts_content_html(
        saved and active_tab == "accounts", error if active_tab == "accounts" else None,
    )
    if _is_htmx(request):
        return content

    def tab_btn(key: str, label: str) -> str:
        cls = "tab-btn active" if key == active_tab else "tab-btn"
        return f'<button type="button" class="{cls}" data-tab-target="tab-{key}">{label}</button>'

    def panel_attrs(key: str) -> str:
        return "" if key == active_tab else " hidden"

    # "saved"/"tested"/"test_failed"/"telegram_error" are only meaningful
    # for the telegram tab's own non-htmx redirect fallback (its mutating
    # routes always also pass tab=telegram) — gated on active_tab=="telegram"
    # same as the "sync" tab's own `saved` below, so a flash/error from one
    # tab's action never renders into the wrong (possibly hidden) panel.
    telegram_flash = None
    telegram_err = None
    if active_tab == "telegram":
        if tested:
            telegram_flash = f"✅ Đã gửi tin test tới chat ID {tested} — kiểm tra Telegram."
        elif saved:
            telegram_flash = "✅ Đã lưu."
        if telegram_error:
            telegram_err = telegram_error
        elif test_failed:
            telegram_err = (
                f"⚠️ Gửi tin test tới chat ID {test_failed} KHÔNG thành công — kiểm tra lại chat_id, "
                f"token, hoặc công tắc bật/tắt ở /admin/config."
            )

    return _layout(f"""
<h1>Tài khoản</h1>
<p class="page-desc">Các tài khoản Facebook mà bot dùng để đăng bài và bình luận.</p>

<div data-tabs>
  <div class="tab-bar">
    {tab_btn("accounts", "👤 Tài khoản")}
    {tab_btn("sync", "🔄 Đồng bộ")}
    {tab_btn("telegram", "📨 Tài khoản Telegram")}
  </div>

  <div class="tab-panel" id="tab-accounts"{panel_attrs("accounts")}>
    {content}
  </div>

  <div class="tab-panel" id="tab-sync"{panel_attrs("sync")}>
    {_sync_content_html(saved=(saved and active_tab == "sync"))}
  </div>

  <div class="tab-panel" id="tab-telegram"{panel_attrs("telegram")}>
    {_telegram_recipients_content_html(flash=telegram_flash, error=telegram_err)}
  </div>
</div>
<script>
  /* close an open "⋯" menu when clicking anywhere else */
  if (!window.__rowMenuCloser) {{
    window.__rowMenuCloser = true;
    document.addEventListener("click", function (e) {{
      document.querySelectorAll("details.row-menu[open]").forEach(function (d) {{ if (!d.contains(e.target)) d.removeAttribute("open"); }});
    }});
  }}
</script>
""", active="accounts", current_user=_build_current_user(request))


def _page_account_error(
    page_name: str, personal_name: str, accounts: dict,
    owner_account_id: str = "", page_session_mode: str = PAGE_MODE_AUTO,
) -> str | None:
    """Validation for registering an account that acts as a Facebook Page."""
    owner = accounts.get(owner_account_id)
    if owner is None:
        return "Chọn tài khoản cá nhân mà Page này thuộc về"
    if owner.page_name:
        return "Tài khoản sở hữu phải là tài khoản cá nhân, không phải một Page khác"
    if page_session_mode not in PAGE_SESSION_MODES:
        return "Cách chạy không hợp lệ"
    if not personal_name:
        return "Tài khoản chạy bằng Page cần khai báo thêm tên hồ sơ cá nhân của bạn (để bot kiểm chắc chắn đang là Page)"
    if normalize_name(page_name) == normalize_name(personal_name):
        return "Tên Page và tên hồ sơ cá nhân không được trùng nhau"
    if any(normalize_name(a.page_name) == normalize_name(page_name) for a in accounts.values() if a.page_name):
        return "Đã có một tài khoản khác chạy bằng Page này"
    return None


@router.get("/accounts/add-modal", response_class=HTMLResponse)
async def accounts_add_modal(_: None = Depends(_require_login)) -> str:
    return _account_modal_html()


@router.post("/accounts/add")
async def accounts_add(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip().lower()
    display_name = str(form.get("display_name", "")).strip()
    page_name = str(form.get("page_name", "")).strip()[:200]
    personal_name = str(form.get("personal_name", "")).strip()[:200]
    owner_account_id = str(form.get("owner_account_id", "")).strip()
    page_session_mode = str(form.get("page_session_mode", "")).strip() or PAGE_MODE_AUTO
    if not page_name:
        # Not a Page: the Page-only fields are meaningless — ignore them rather than
        # let a stale/crafted value reach save_registered_account().
        owner_account_id, page_session_mode, personal_name = "", PAGE_MODE_AUTO, ""
    error = _account_id_error(account_id, get_all_accounts())
    if not error and page_name:
        error = _page_account_error(page_name, personal_name, get_all_accounts(), owner_account_id, page_session_mode)
    if error:
        if _is_htmx(request):
            return HTMLResponse(_account_modal_html(
                account_id=account_id, display_name=display_name, error=error,
                page_name=page_name, personal_name=personal_name,
                owner_account_id=owner_account_id, page_session_mode=page_session_mode,
            ))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': error})}", status_code=303)
    save_registered_account(account_id, display_name or account_id, page_name, personal_name, owner_account_id, page_session_mode)
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


@router.post("/accounts/page-mode")
async def accounts_page_mode(request: Request, _: None = Depends(_require_login)):
    """Switches a Page account between running on its own session and running
    on its owner's session (switching to the Page and back)."""
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    mode = str(form.get("mode", "")).strip()
    error = None
    if mode not in PAGE_SESSION_MODES:
        error = "Cách chạy không hợp lệ"
    elif not set_page_session_mode(account_id, mode):
        error = "Không phải tài khoản Page đã đăng ký"
    if _is_htmx(request):
        return HTMLResponse(_accounts_content_html(saved=error is None, error=error))
    if error:
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': error})}", status_code=303)
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.post("/accounts/pause")
async def accounts_pause(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    set_account_paused(account_id, True)
    if _is_htmx(request):
        return HTMLResponse(_accounts_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.post("/accounts/disable")
async def accounts_disable(request: Request, _: None = Depends(_require_login)):
    """"⏻ Tắt" — the operator switches an account off, no fault involved (see
    runtime_config.set_account_disabled()). Also closes its idle browser so it
    stops holding a Chrome window."""
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    error = None
    account = get_all_accounts().get(account_id)
    if account is None:
        error = "Không tìm thấy tài khoản"
    elif account.status == AccountStatus.PAUSED:
        error = "Tài khoản đang Tạm dừng — hãy Kích hoạt lại trước, hoặc để nguyên"
    else:
        set_account_disabled(account_id, True)
        try:
            await browser_pool.close_idle_session(account_id)
        except Exception:  # noqa: BLE001 — switching off must never fail because a browser would not close
            logger.exception("accounts_disable: could not close the browser of %s", account_id)
    if _is_htmx(request):
        return HTMLResponse(_accounts_content_html(saved=error is None, error=error))
    if error:
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': error})}", status_code=303)
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.post("/accounts/enable")
async def accounts_enable(request: Request, _: None = Depends(_require_login)):
    """"▶ Bật lại" for a switched-off account: immediate, full limits — unlike
    "Kích hoạt lại" (resume_account()) there is no cooldown, because nothing
    was wrong with the account."""
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    account = get_all_accounts().get(account_id)
    error = None
    if account is None:
        error = "Không tìm thấy tài khoản"
    elif account.status != AccountStatus.DISABLED:
        error = "Tài khoản này không ở trạng thái tắt"
    else:
        set_account_disabled(account_id, False)
    if _is_htmx(request):
        return HTMLResponse(_accounts_content_html(saved=error is None, error=error))
    if error:
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': error})}", status_code=303)
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.post("/accounts/resume")
async def accounts_resume(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    resume_account(account_id)  # clears the pause AND starts the reduced-limit cooldown
    if _is_htmx(request):
        return HTMLResponse(_accounts_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.post("/accounts/sync-disable")
async def accounts_sync_disable(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    set_account_sync_enabled(account_id, False)
    if _is_htmx(request):
        return HTMLResponse(_sync_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?tab=sync&saved=1", status_code=303)


@router.post("/accounts/sync-enable")
async def accounts_sync_enable(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    set_account_sync_enabled(account_id, True)
    if _is_htmx(request):
        return HTMLResponse(_sync_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?tab=sync&saved=1", status_code=303)


@router.post("/accounts/sponsored-only-enable")
async def accounts_sponsored_only_enable(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    set_account_sponsored_only(account_id, True)
    if _is_htmx(request):
        return HTMLResponse(_sync_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?tab=sync&saved=1", status_code=303)


@router.post("/accounts/sponsored-only-disable")
async def accounts_sponsored_only_disable(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    set_account_sponsored_only(account_id, False)
    if _is_htmx(request):
        return HTMLResponse(_sync_content_html(saved=True))
    return RedirectResponse(url="/admin/accounts?tab=sync&saved=1", status_code=303)


@router.post("/accounts/delete")
async def accounts_delete(request: Request, _: None = Depends(_require_login)):
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
    - any sponsored_only flag (set_account_sponsored_only) — same
      "don't silently inherit stale state" reasoning as the sync opt-out
      just above
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
    children = pages_of(account_id)
    if children:
        error = (
            "Không xoá được: tài khoản này còn Page đang dùng nó ("
            + ", ".join(p.account_id for p in children) + ") — xoá các Page trước"
        )
        if _is_htmx(request):
            return HTMLResponse(_accounts_content_html(error=error))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': error})}", status_code=303)
    delete_registered_account(account_id)
    set_account_removed(account_id, True)
    set_account_paused(account_id, False)  # drop any stale pause override too
    set_account_disabled(account_id, False)  # ...and a stale "switched off" flag
    set_account_sync_enabled(account_id, True)  # drop any stale sync opt-out too
    set_account_sponsored_only(account_id, False)  # drop any stale sponsored_only flag too
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
async def accounts_rate_limits_modal(account_id: str, _: None = Depends(_require_login)) -> str:
    accounts = get_all_accounts()
    if account_id not in accounts:
        return _rate_limits_modal_html(account_id, RateLimits(), is_override=False, error="Không tìm thấy tài khoản này")
    is_override = bool(get_rate_limits_overrides(account_id))
    return _rate_limits_modal_html(account_id, accounts[account_id].rate_limits, is_override=is_override)


@router.post("/accounts/rate-limits")
async def accounts_rate_limits_save(request: Request, _: None = Depends(_require_login)):
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
    request: Request,
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
    _: None = Depends(_require_login),
) -> str:
    accounts = get_all_accounts()
    account_ids = list(accounts)
    if not account_ids:
        return _layout(
            '<h1>Đăng bài</h1><div class="empty-state">Chưa có tài khoản nào — '
            'đăng ký ở <a href="/admin/accounts">/admin/accounts</a> trước.</div>',
            active="post",
            current_user=_build_current_user(request),
        )
    if account_id not in accounts:
        account_id = account_ids[0]
    account_labels = {aid: _account_label(aid, accounts) for aid in account_ids}

    open_schedule = '<a href="/admin/schedule">Mở Lịch đăng →</a>'
    if scheduled:
        flash = f'<div class="flash">✅ Đã lên lịch. {open_schedule} để xem, sửa hoặc đăng ngay.</div>'
    elif posted:
        flash = f'<div class="flash">✅ {html.escape(posted)}. {open_schedule}</div>'
    else:
        flash = ""
    err = f'<div class="error">⚠️ {html.escape(error)}</div>' if error else ""

    # Doesn't block composing/scheduling for a paused account — a task
    # created now is still safely staged behind /admin/schedule's own
    # review step — just warns up front instead of letting it silently
    # fail with "account_paused" whenever something later tries to fire
    # it (found in the admin UI review that asked for this).
    pause_warning = ""
    if accounts[account_id].status == AccountStatus.DISABLED:
        pause_warning = (
            '<div class="warning">⏻ Tài khoản này đang <strong>tắt</strong> — bài lên lịch ở đây sẽ chuyển sang '
            '"Quá hạn" khi đến giờ, cho tới khi bạn <a href="/admin/accounts">bật lại</a>.</div>'
        )
    elif accounts[account_id].status == AccountStatus.PAUSED:
        pause_warning = (
            '<div class="error">⚠️ Tài khoản này đang <strong>Tạm dừng</strong> — bài lên lịch ở đây sẽ '
            'không tự đăng cho tới khi bạn <a href="/admin/accounts">kích hoạt lại</a>.</div>'
        )

    auto_fire_notice = _auto_fire_status_html()

    # Choosing the account fully reloads this page (plain GET form) rather
    # than trying to keep an account-scoped group checkbox list in sync
    # via JS/htmx — same "still-full-reload page" simplicity already used
    # elsewhere on this page. To stop that reload from silently wiping
    # whatever was already typed, initPreservePostForm (this
    # module's page script) copies the "Đăng lên tường cá nhân" card's
    # content/time into hidden fields on THIS form before it submits —
    # post_form() below reads them back (profile_content/
    # profile_scheduled_at) — and stashes every other compose field in
    # sessionStorage, which initPostDrafts puts back after the reload (also
    # after a validation error sends the admin back here). The hidden `tab`
    # keeps the admin on the tab they were using.
    account_picker = f"""
<form method="get" action="/admin/post" class="account-filter" id="post-account-form" data-preserve-post-form>
  <label for="post-account-select">Đăng bằng tài khoản</label>
  <select name="account_id" id="post-account-select">
    {"".join(f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(account_labels[aid])}</option>' for aid in account_ids)}
  </select>
</form>"""
    post_as = f'<span class="post-as">Đăng bằng <b>{html.escape(account_labels[account_id])}</b></span>'

    groups = get_joined_groups(account_id)
    if groups:
        group_checkboxes = "".join(
            f"""<label class="group-pill">
  <input type="checkbox" name="groups_0" value="{html.escape(g.url)}"{" checked" if prefill_target_url and g.url == prefill_target_url else ""}> <span>{html.escape(g.name or g.url)}</span>
</label>"""
            for g in groups
        )
        group_post_card = f"""
<div class="card">
  <h2>👥 Đăng vào nhóm</h2>
  <p class="page-desc">Viết nội dung, tick các nhóm sẽ đăng. Muốn mỗi nhóm một nội dung khác nhau thì thêm khối mới (ví dụ nội dung A cho 3 nhóm đầu, nội dung B cho nhóm còn lại). Giờ đăng được rải đều giữa tất cả các bài — không đăng dồn một lúc — theo khoảng cách đặt ở <a href="/admin/config?tab=sync">Cấu hình → Đồng bộ dữ liệu</a>.</p>
  <form method="post" action="/admin/post/schedule-groups" data-post-count-form>
    <input type="hidden" name="account_id" value="{html.escape(account_id)}">
    <input type="hidden" name="retry_of_log_id" value="{prefill_retry_of_log_id or ""}">
    <div data-repeatable-blocks>
      <div data-block-list>
        <div class="content-block post-block" data-block>
          <textarea name="content_0" placeholder="Nội dung cho các nhóm được chọn bên dưới..." required>{html.escape(prefill_content or "")}</textarea>
          <div class="block-groups-head">
            <span class="fg-label">Đăng vào nhóm</span>
            <button type="button" class="btn-secondary btn-small" data-select-all-groups>Chọn tất cả</button>
          </div>
          <div class="group-pills">{group_checkboxes}</div>
          <button type="button" class="btn-secondary btn-small block-remove" data-remove-block>Xoá khối này</button>
        </div>
      </div>
      <button type="button" class="btn-secondary btn-small" data-add-block>+ Thêm nội dung khác</button>
    </div>
    <div class="form-grid" style="margin-top:16px;">
      {_fg("Bắt đầu đăng lúc", _datetime_picker_html("start_at"), span2=True, tag="div")}
    </div>
    <div class="post-actions">
      {post_as}
      <div class="post-btns">
        <span class="post-count" data-post-count aria-live="polite"></span>
        <button type="submit">Lên lịch tất cả</button>
      </div>
    </div>
  </form>
</div>"""
    else:
        group_post_card = f"""
<div class="card">
  <h2>👥 Đăng vào nhóm</h2>
  <div class="empty-state">Tài khoản này chưa tham gia nhóm nào — <a href="/admin/groups?account_id={html.escape(account_id)}">thêm ở “Nhóm đã tham gia”</a> trước.</div>
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
  <h2>💬 Bình luận</h2>
  <p class="page-desc">Bình luận vào MỘT bài Facebook có sẵn (dán URL bài đó bên dưới). Muốn đăng bài mới thì dùng “Đăng vào nhóm”.</p>
  <form method="post" action="/admin/post/schedule-comment">
    <input type="hidden" name="account_id" value="{html.escape(account_id)}">
    <input type="hidden" name="retry_of_log_id" value="{prefill_retry_of_log_id or ""}">
    <div class="form-grid">
      {_fg("URL bài đăng/hồ sơ cần bình luận", f'<input type="url" name="target_url" placeholder="https://facebook.com/groups/.../posts/..." required value="{html.escape(prefill_target_url or "")}">', span2=True)}
      {_fg("Nội dung bình luận", f'<textarea name="content" placeholder="Nội dung bình luận..." required>{html.escape(prefill_content or "")}</textarea>', span2=True)}
      {_fg("Đăng lúc", _datetime_picker_html("scheduled_at"), span2=True, tag="div")}
    </div>
    <div class="post-actions">{post_as}<div class="post-btns"><button type="submit">Lên lịch</button></div></div>
  </form>
</div>"""

    # "📋 Tin tuyển dụng" tab (2026-10-30, owner request): type a job the way
    # side B would send it (+ "thông tin thêm"), pick AI or template, and the
    # server drafts one post per group, picks the groups and slots, and
    # schedules everything in one click — for jobs that come from somewhere
    # other than side B (e.g. a message in a Zalo group).
    visa_options = "".join(
        f'<option value="{html.escape(code)}">{html.escape(code.capitalize())}</option>'
        for code in get_visa_type_names(_VISA_TYPE_NAMES_DEFAULT)
    )
    salary_hint_attrs = " ".join(f'data-hint-{k}="{html.escape(v)}"' for k, v in _SALARY_HINTS.items())
    jlpt_options = "".join(f'<option value="{n}">{n}</option>' for n in ("N1", "N2", "N3", "N4", "N5"))
    max_group_count = max(1, min(accounts[account_id].rate_limits.max_groups_per_post, max(len(groups), 1)))
    default_group_count = max_group_count
    # What each button does, said next to it — and, when no AI key is set,
    # said BEFORE the click (post_schedule_job() falls back to the template
    # either way, but only told the admin afterwards).
    if content_strategist.ai_provider_configured():
        ai_hint = "mỗi nhóm một bài viết khác nhau (mất vài giây)"
    else:
        ai_hint = 'chưa có khoá AI ở <a href="/admin/config?tab=ai">Cấu hình → AI</a> — nút này sẽ dùng template'
    job_card = f"""
<div class="card">
  <h2>📋 Tin tuyển dụng</h2>
  <p class="page-desc">Nhập thông tin của tin tuyển dụng như dữ liệu bên B gửi sang. Bot soạn mỗi nhóm một bài khác nhau, <b>tự chọn nhóm và xếp giờ</b> theo giới hạn của tài khoản rồi lên lịch (xem, sửa, huỷ ở <a href="/admin/schedule">Lịch đăng</a>). Chỉ cần Tiêu đề; ô nào để trống thì bài mời nhắn tin để trao đổi thêm.</p>
  <form method="post" action="/admin/post/schedule-job">
    <input type="hidden" name="account_id" value="{html.escape(account_id)}">
    <div class="form-grid">
      {_fg('Tiêu đề / vị trí <span class="req">*</span>', '<input type="text" name="title" required maxlength="200" placeholder="VD: Vận hành máy">', span2=True)}
      {_fg("Công ty", '<input type="text" name="company" maxlength="200">')}
      {_fg("Địa điểm", '<input type="text" name="location" maxlength="200" placeholder="VD: Ibaraki">')}
      {_fg("Visa", f'<select name="visa"><option value="">— không rõ —</option>{visa_options}</select>')}
      {_fg("JLPT", f'<select name="jlpt"><option value="">— không yêu cầu / không rõ —</option>{jlpt_options}</select>')}
      {_fg("Lương", f'<div class="salary-row"><input type="number" name="salary_min" min="0" step="any" placeholder="từ" aria-label="Lương từ"><span class="muted">–</span><input type="number" name="salary_max" min="0" step="any" placeholder="đến" aria-label="Lương đến"><select name="salary_period" aria-label="Tính theo" data-salary-period {salary_hint_attrs}><option value="month">/ tháng</option><option value="year">/ năm</option><option value="hour">/ giờ</option></select></div>', span2=True, tag="div", hint=_SALARY_HINT_ANY, hint_attrs=" data-salary-hint")}
      {_fg("Thông tin thêm", '<textarea name="extra_info" rows="4" maxlength="1000" class="compact" placeholder="VD: Trợ cấp vợ con 2m8, trợ cấp nhà, tăng ca 30h/tháng"></textarea>', span2=True)}
      {_fg("Số nhóm sẽ đăng", f'<input type="number" name="group_count" min="1" max="{max_group_count}" value="{default_group_count}" class="narrow">', span2=True, hint=f"Tối đa {max_group_count} (giới hạn của tài khoản; đã tham gia {len(groups)} nhóm). Hệ thống tự chọn nhóm, ưu tiên nhóm lâu chưa đăng.")}
    </div>
    <div class="post-actions">
      {post_as}
      <div class="post-btns">
        <div class="mode-opt"><button type="submit" name="mode" value="ai">✨ Tạo bằng AI & lên lịch</button><span class="fg-hint">{ai_hint}</span></div>
        <div class="mode-opt"><button type="submit" name="mode" value="template" class="btn-secondary">📄 Tạo bằng template & lên lịch</button><span class="fg-hint">khung mẫu có sẵn, nhanh, không dùng AI</span></div>
      </div>
    </div>
  </form>
</div>"""

    # Most posts here are job posts into groups, so those tabs come first
    # (and "Tường cá nhân" last). `tab` may arrive as the tab BUTTON's
    # target id ("tab-job") — older links and the account-switch form sent
    # that, which used to fall through to the default tab.
    tab = (tab or "").removeprefix("tab-")
    active_tab = tab if tab in ("job", "group", "comment", "profile") else "job"

    def tab_btn(key: str, label: str) -> str:
        cls = "tab-btn active" if key == active_tab else "tab-btn"
        return f'<button type="button" class="{cls}" data-tab-target="tab-{key}">{label}</button>'

    def panel_attrs(key: str) -> str:
        return "" if key == active_tab else " hidden"

    return _layout(f"""
<h1>Đăng bài</h1>
<p class="page-desc">Soạn bài và chọn giờ đăng. Bài nào cũng qua <a href="/admin/schedule">Lịch đăng</a> trước khi chạy — muốn đăng ngay thì để trống giờ rồi bấm “🚀 Đăng ngay” ở đó.</p>
{flash}{err}
{account_picker}
{pause_warning}
{auto_fire_notice}

<div data-tabs>
  <div class="tab-bar">
    {tab_btn("job", "📋 Tin tuyển dụng")}
    {tab_btn("group", "👥 Đăng vào nhóm")}
    {tab_btn("comment", "💬 Bình luận")}
    {tab_btn("profile", "👤 Tường cá nhân")}
  </div>

  <div class="tab-panel" id="tab-job"{panel_attrs("job")}>
    {job_card}
  </div>

  <div class="tab-panel" id="tab-group"{panel_attrs("group")}>
    {group_post_card}
  </div>

  <div class="tab-panel" id="tab-comment"{panel_attrs("comment")}>
    {comment_post_card}
  </div>

  <div class="tab-panel" id="tab-profile"{panel_attrs("profile")}>
    <div class="card">
      <h2>👤 Tường cá nhân</h2>
      <p class="page-desc">Đăng một bài lên trang cá nhân của tài khoản.</p>
      <form method="post" action="/admin/post/schedule-profile">
        <input type="hidden" name="account_id" value="{html.escape(account_id)}">
        <input type="hidden" name="retry_of_log_id" value="{prefill_retry_of_log_id or ""}">
        <div class="form-grid">
          {_fg("Nội dung bài đăng", f'<textarea name="content" placeholder="Nội dung bài đăng..." required data-preserve-profile-content>{html.escape(profile_content or "")}</textarea>', span2=True)}
          {_fg("Đối tượng xem", '<select name="audience"><option value="public" selected>🌍 Công khai (Public)</option><option value="friends">👥 Bạn bè (Friends)</option><option value="only_me">🔒 Chỉ mình tôi (Only me)</option></select>', span2=True)}
          {_fg("Đăng lúc", f'<div data-preserve-profile-schedule>{_datetime_picker_html("scheduled_at", current_value=profile_scheduled_at or "")}</div>', span2=True, tag="div")}
        </div>
        <div class="post-actions">{post_as}<div class="post-btns"><button type="submit">Lên lịch</button></div></div>
      </form>
    </div>
  </div>
</div>
""", active="post", current_user=_build_current_user(request))


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
async def post_schedule_profile(request: Request, _: None = Depends(_require_login)) -> RedirectResponse:
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
async def post_schedule_groups(request: Request, _: None = Depends(_require_login)) -> RedirectResponse:
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


def _parse_job_number(raw: str, *, comma_is_thousands: bool = False) -> int | float | None:
    """A non-negative number from the job form; whole numbers come back as
    int (a float 1400.0 would print as "1400.0" in the post). A comma is a
    decimal mark for man amounts ("2,5") but a thousands separator for plain
    yên ("1,400") — the caller says which."""
    raw = (raw or "").strip()
    if not raw:
        return None
    raw = raw.replace(",", "") if comma_is_thousands else raw.replace(",", ".")
    try:
        value = float(raw)
    except ValueError:
        raise ValueError(f"Số không hợp lệ: {raw}")
    if value < 0 or value != value or value == float("inf"):
        raise ValueError(f"Số không hợp lệ: {raw}")
    return int(value) if value == int(value) else value


def _build_manual_job(form) -> dict:
    """The job dict (same shape side B sends: title + attributes) from the
    /admin/post "Tin tuyển dụng" form. Raises ValueError with a message
    meant for the admin."""
    title = str(form.get("title", "")).strip()
    if not title:
        raise ValueError("Cần nhập Tiêu đề")
    attrs: dict[str, Any] = {}
    for key in ("company", "location", "extra_info"):
        value = str(form.get(key, "")).strip()
        if value:
            attrs[key] = value
    visa = str(form.get("visa", "")).strip().lower()
    if visa:
        if visa not in get_visa_type_names(_VISA_TYPE_NAMES_DEFAULT):
            raise ValueError("Loại visa không hợp lệ")
        attrs["visaType"] = visa
    jlpt = str(form.get("jlpt", "")).strip().upper()
    if jlpt:
        if jlpt not in ("N1", "N2", "N3", "N4", "N5"):
            raise ValueError("JLPT không hợp lệ")
        attrs["jlpt"] = jlpt
    period = str(form.get("salary_period", "month")).strip()
    if period not in ("month", "year", "hour"):
        raise ValueError("Kỳ tính lương không hợp lệ")
    lo = _parse_job_number(str(form.get("salary_min", "")), comma_is_thousands=period == "hour")
    hi = _parse_job_number(str(form.get("salary_max", "")), comma_is_thousands=period == "hour")
    if lo or hi:
        if lo and hi and lo > hi:
            raise ValueError("Lương \"từ\" không được lớn hơn \"đến\"")
        # Month/year amounts are typed in man (万 = 10.000 yên) but side B —
        # and content_strategist._salary_line() — work in plain yên.
        factor = content_strategist.YEN_PER_MAN if period in content_strategist.MAN_PERIOD_KEYS else 1

        def to_yen(v):
            if not v:
                return None
            v = v * factor
            return int(round(v))

        attrs["salary"] = {
            "min": to_yen(lo), "max": to_yen(hi),
            "currency": "JPY", "period": period,
        }
    job = content_strategist.sanitize_job({"title": title, "attributes": attrs})
    if not job.get("title"):  # e.g. typed "unknown"/"n/a" — a sentinel, not a real title
        raise ValueError("Tiêu đề không hợp lệ")
    return job


@router.post("/post/schedule-job")
async def post_schedule_job(request: Request, _: None = Depends(_require_login)) -> RedirectResponse:
    """"📋 Tin tuyển dụng" — a job typed by hand (e.g. copied from a Zalo
    group message): drafts one post per group (AI or template, by which
    button was pressed), picks the groups and a slot for each exactly like
    the side-B pipeline / the "Duyệt & lên lịch" flow do
    (_pick_groups_for_job + _suggest_reschedule_at), and schedules them all.
    Tasks are marked ai_redraft=False so fire_due_tasks() posts the text
    chosen here instead of re-drafting it with AI."""
    from urllib.parse import quote
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()

    def back(**params: str) -> RedirectResponse:
        qs = "&".join(f"{k}={quote(str(v), safe='')}" for k, v in params.items())
        return RedirectResponse(url=f"/admin/post?account_id={quote(account_id, safe='')}&tab=job&{qs}", status_code=303)

    account = get_all_accounts().get(account_id)
    if account is None:
        return back(error="Không tìm thấy tài khoản")
    mode = str(form.get("mode", "")).strip()
    if mode not in ("ai", "template"):
        return back(error="Chưa chọn cách tạo bài (AI hay template)")
    try:
        job = _build_manual_job(form)
    except ValueError as exc:
        return back(error=str(exc))

    joined = get_joined_groups(account_id)
    if not joined:
        return back(error="Tài khoản này chưa tham gia nhóm nào — thêm ở “Nhóm đã tham gia” trước")
    # Never more groups per job than the account's own limit (the same one
    # the side-B pipeline enforces) — a crafted POST can't lift it.
    limit = max(1, account.rate_limits.max_groups_per_post)
    try:
        wanted = int(str(form.get("group_count", "")).strip() or limit)
    except ValueError:
        wanted = limit
    wanted = max(1, min(wanted, limit, len(joined)))

    job_data = {"title": job.get("title"), "attributes": job.get("attributes") or {}, "sponsored_by": None}
    # Double-submit / refresh guard: the same job already waiting for this
    # account would be posted twice into the same groups.
    if any(
        t.account_id == account_id and str(t.source_id).startswith("manual-") and t.job_data == job_data
        for t in schedule_store.list_pending()
    ):
        return back(error="Tin này đã được lên lịch rồi và còn bài đang chờ đăng — xem ở Lịch đăng")

    groups = _pick_groups_for_job(joined, _last_scheduled_time_per_group(account_id), needed=wanted)

    notes: list[str] = []
    contents: list[str] | None = None
    used_ai = False
    if mode == "ai":
        if not content_strategist.ai_provider_configured():
            notes.append("AI chưa có key nên đã dùng template")
        else:
            try:
                contents = await content_strategist.draft_ai_variants(job, groups)
                used_ai = True
            except Exception:  # noqa: BLE001 - fall back, but tell the admin
                logger.exception("post_schedule_job: AI draft failed")
                notes.append("AI soạn lỗi nên đã dùng template")
    if contents is None:
        contents = content_strategist.template_variants(job, groups)
    how = "AI" if used_ai else "template"

    source_id = f"manual-{secrets.token_hex(4)}"
    created: list[str] = []
    try:
        for group, content in zip(groups, contents):
            scheduled_at = _suggest_reschedule_at(account, "post_to_group")
            task = schedule_store.ScheduledTask(
                task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
                action="post_to_group",
                account_id=account_id,
                scheduled_at=scheduled_at.isoformat(),
                content=content,
                target_url=group.url,
                reasoning=f"manual job form ({how})",
                source_kind="job",
                source_id=source_id,
                job_data=job_data,
                ai_redraft=False,
            )
            schedule_store.add(task)
            created.append(task.task_id)
    except Exception:  # noqa: BLE001 - undo the partial batch so a retry can't double-post
        logger.exception("post_schedule_job: scheduling failed midway")
        for task_id in created:
            schedule_store.cancel(task_id)
        return back(error="Lỗi khi lên lịch — đã hoàn tác, chưa có bài nào được tạo")
    message = f"Đã tạo {len(created)} bài ({how}) và lên lịch vào {len(created)} nhóm"
    if notes:
        message += " — " + "; ".join(notes)
    return back(posted=message)


@router.post("/post/schedule-comment")
async def post_schedule_comment(request: Request, _: None = Depends(_require_login)) -> RedirectResponse:
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


def _local_time_html(iso: str | None) -> str:
    """"HH:MM" in the VIEWER's own timezone (initLocalTime() in the page script rewrites it); the
    server-rendered fallback is JST, same as _local_dt_html()."""
    if not iso:
        return "—"
    try:
        fallback = (datetime.fromisoformat(iso.replace("Z", "+00:00")) + timedelta(hours=9)).strftime("%H:%M")
    except ValueError:
        fallback = iso
    return f'<span data-local-time data-utc="{html.escape(iso)}">{html.escape(fallback)}</span>'


def _group_name_lookup():
    """lookup(account_id, url) -> the group's saved name or None. Reads each account's group list ONCE
    (a schedule page names dozens of tasks) and matches by group id/slug, not exact URL, like
    agent.resolve_group_name()."""
    from human_bot.actions import _group_id_from_url
    cache: dict[str, list[tuple[str, str | None, str]]] = {}

    def lookup(account_id: str, url: str | None) -> str | None:
        if not url:
            return None
        if account_id not in cache:
            try:
                cache[account_id] = [(g.url, _group_id_from_url(g.url), g.name) for g in get_joined_groups(account_id)]
            except Exception:  # noqa: BLE001 — a label is never worth failing the page
                cache[account_id] = []
        wanted = _group_id_from_url(url)
        for group_url, group_id, name in cache[account_id]:
            if group_url == url or (wanted and group_id == wanted):
                return name or None
        return None

    return lookup


def _sched_target_html(t, name_lookup) -> str:
    """The row's target: a group's NAME (the URL is the link and the tooltip), or for a comment the
    post it goes to. Raw URLs never take the line."""
    if not t.target_url:
        return '<span class="sched-target">Tường cá nhân</span>'
    return _target_link_html(t.action, t.target_url, name_lookup(t.account_id, t.target_url))


def _target_link_html(action: str, url: str, group_name: str | None) -> str:
    """The link for a target URL, named: a group post -> the group's name (else the last part of its URL); a comment ->
    "bài trong <group>" when the group is known, else "bài viết …<last 6 characters of the post id>". Shared by
    /admin/schedule and /admin/reports so one target is never called two different things."""
    href = html.escape(url)
    tail = url.split("?")[0].rstrip("/").rsplit("/", 1)[-1]
    if action == "post_to_group":
        label = group_name or tail
    else:
        label = f"bài trong {group_name}" if group_name else (f"bài viết …{tail[-6:]}" if tail and "." not in tail else "bài viết")
    return f'<a class="sched-target" href="{href}" target="_blank" rel="noopener" title="{href}">{html.escape(label)}</a>'


def _copy_url_button(url: str) -> str:
    """A "⋯" menu item that copies `url` to the clipboard (copyText() in the page script, which also works over
    plain http, where navigator.clipboard does not exist) and says whether it worked."""
    url_js = html.escape(json.dumps(url), quote=True)
    return (
        f'<button type="button" class="menu-item" onclick="copyText({url_js}, this)">'
        '📋 Copy URL<small>Chép đường dẫn vào bộ nhớ tạm</small></button>'
    )


_EDIT_TOGGLE = (
    "var p=this.closest('.sched-item').querySelector('.sched-edit'); p.hidden=!p.hidden; "
    "this.setAttribute('aria-expanded', String(!p.hidden));"
)
_EDIT_CLOSE = "var it=this.closest('.sched-item'); it.querySelector('.sched-edit').hidden=true;"


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


def _missed_page_link(
    account_id: str | None, target_page: int, label: str, enabled: bool, page_size: int,
    missed_min_days: int | None = None,
) -> str:
    if not enabled:
        return f'<span class="btn-secondary btn-small" style="opacity:.45; pointer-events:none;">{label}</span>'
    from urllib.parse import urlencode
    qs = urlencode({k: v for k, v in {
        "account_id": account_id, "tab": "missed", "missed_page": target_page,
        "page_size": page_size if page_size != _SCHEDULE_PAGE_SIZE else None,
        "missed_min_days": missed_min_days,
    }.items() if v})
    return (
        f'<a class="btn-secondary btn-small" href="/admin/schedule?{qs}" '
        f'hx-get="/admin/schedule?{qs}" hx-target="#schedule-content" hx-swap="outerHTML" hx-push-url="true">{label}</a>'
    )


_MISSED_MIN_DAYS_CHOICES = (3, 5, 7, 30)


def _missed_tasks_section_html(
    account_id: str | None, page: int, page_size: int, accounts: dict, missed_page: int = 1,
    missed_min_days: int | None = None,
) -> str:
    """"⚠️ Task quá hạn" tab content (2026-09-14, split into its own tab
    per owner request — was a conditionally-shown callout card before;
    pagination added same day, same owner request). schedule_store.
    MISSED_DIR holds tasks the one-time startup sweep pulled out of
    pending/ because their scheduled_at was already in the past the
    moment the service came back up (see data_sync.
    sweep_overdue_on_startup()'s docstring). Every action here re-renders
    the WHOLE #schedule-content (same as pending-task actions already
    do), so both tabs always stay in sync with each other.

    `missed_min_days` (2026-09-24, owner request — went through 2 rounds
    of direction with the owner before landing here: first built as "≥ N
    ngày", corrected to "≤ N ngày" as a "still-fresh" triage bucket, then
    reverted BACK to "≥ N ngày" after the owner pointed out the real
    reason it matters: this list has a bulk "chọn tất cả" + "🗑️ Xoá đã
    chọn" action right on it — filtering "≤ N ngày" puts fresh 1-3-ngày
    tasks in the SAME visible/selectable set as old ones, so a bulk
    delete meant for the stale tail could wipe out fresh tasks too;
    filtering "≥ N ngày" never shows anything fresher than N days old,
    so selecting everything visible and deleting it is always safe):
    "quá hạn ≥ N ngày" filter, N in _MISSED_MIN_DAYS_CHOICES — measured
    from each task's ORIGINAL scheduled_at via
    schedule_store.missed_overdue_days(), same basis
    schedule_store.cancel_stale_missed()'s "≥ 30 ngày" auto-cleanup
    threshold uses, so "≥ 30 ngày" here shows exactly what the daily
    auto-cleanup would sweep next. Applied BEFORE pagination, same
    order as the pending tab's action/date
    filters.

    `missed_page` is a SEPARATE page counter from the pending tab's own
    `page` — the two tabs have unrelated item counts, so sharing one
    "page" query param would desync whichever tab isn't currently active
    (same "job_page"/"candidate_page" reasoning as /admin/reports' own
    multi-tab pagination)."""
    all_missed = schedule_store.list_missed()
    if not all_missed:
        return '<div class="empty-state">Không có bài nào quá hạn — mọi thứ đúng lịch.</div>'

    now = datetime.now(timezone.utc)
    overdue_days_by_id = {t.task_id: schedule_store.missed_overdue_days(t, now) for t in all_missed}
    filtered = all_missed
    if missed_min_days is not None:
        filtered = [t for t in all_missed if overdue_days_by_id[t.task_id] >= missed_min_days]

    # 2026-09-24 fix (real bug, owner-reported): a filter value with ZERO
    # matches used to `return` an empty-state div right here, which
    # replaces the ENTIRE tab body — the "Quá hạn" <select> below (and
    # its "Chọn tất cả"/"Xoá đã chọn" row) never renders at all, so
    # there is no more control on screen to pick a DIFFERENT filter
    # value; only an F5 (which drops back to the unfiltered default)
    # gets the admin unstuck. The filter/bulk-controls row must always
    # render whenever there's ANY missed task at all (all_missed
    # non-empty) — only the item LIST below it becomes empty-state text
    # when the current filter matches nothing.
    total = len(filtered)
    total_pages = max(1, -(-total // page_size)) if filtered else 1
    missed_page = min(max(missed_page, 1), total_pages)
    start = (missed_page - 1) * page_size
    missed = filtered[start:start + page_size] if filtered else []

    _missed_days_options = '<option value="">— Tất cả —</option>' + "".join(
        f'<option value="{n}"{" selected" if n == missed_min_days else ""}>≥ {n} ngày</option>'
        for n in _MISSED_MIN_DAYS_CHOICES
    )
    _missed_filter_hx_vals = html.escape(
        json.dumps({"tab": "missed", "account_id": account_id or "", "page_size": page_size}),
        quote=True,
    )
    toolbar_html = f"""
<div class="sched-toolbar">
  <label for="schedule-missed-mindays-select">Quá hạn</label>
  <select name="missed_min_days" id="schedule-missed-mindays-select"
          hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-trigger="change" hx-push-url="true"
          hx-vals="{_missed_filter_hx_vals}">{_missed_days_options}</select>
  <span class="sched-count">{total} bài{f" (trong tổng {len(all_missed)})" if missed_min_days is not None else ""}</span>
  <label style="display:flex; align-items:center; gap:4px; cursor:pointer; white-space:nowrap;">
    <input type="checkbox" onclick="document.querySelectorAll('input[name=task_ids]').forEach(function(cb){{cb.checked=this.checked}}.bind(this))">
    Chọn tất cả
  </label>
  <button type="submit" form="missed-bulk-form" class="btn-secondary btn-small">🗑 Xoá đã chọn</button>
</div>"""
    items_html = []
    empty_note_html = ""
    if missed_min_days is not None and not filtered:
        empty_note_html = (
            f'<div class="empty-state">Không có bài nào quá hạn ≥ {missed_min_days} ngày '
            f'(tổng {len(all_missed)} bài quá hạn ở mọi mức) — đổi bộ lọc ở trên để xem lại.</div>'
        )
    name_lookup = _group_name_lookup()
    # the hidden fields every per-row form (and the bulk form) carries back, built ONCE
    filter_values = {
        "account_id": account_id or "", "page": str(page), "page_size": str(page_size), "tab": "missed",
        "missed_page": str(missed_page), "missed_min_days": str(missed_min_days) if missed_min_days is not None else "",
    }
    filter_fields = "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in filter_values.items())
    for t in missed:
        content_full = html.escape(t.content or "")
        reason = schedule_store.get_missed_reason(t.task_id)
        why_html = f'<div class="sched-why">{_localize_iso_timestamps_html(reason)}</div>' if reason else ""
        reschedule_qs = (
            f"task_id={html.escape(t.task_id, quote=True)}&account_id={html.escape(account_id or '', quote=True)}"
            f"&page={page}&page_size={page_size}&missed_page={missed_page}"
            + (f"&missed_min_days={missed_min_days}" if missed_min_days is not None else "")
        )
        tid = html.escape(t.task_id)
        menu_items = [_menu_button(
            f'hx-get="/admin/schedule/missed/borrow?{reschedule_qs}" hx-target="#modal-root" hx-swap="innerHTML"',
            "↩️ Mượn giờ của bài khác", "Dùng giờ của một bài đang chờ; bài đó dời sang sau",
        )]
        if t.target_url:
            menu_items.append(_copy_url_button(t.target_url))
        menu_items.append('<hr class="row-menu-sep">')
        menu_items.append(_menu_form(
            "/admin/schedule/missed/cancel", {"task_id": t.task_id, **filter_values}, "🗑 Xoá",
            "Bỏ hẳn bài này, không đăng nữa", target="#schedule-content", confirm="Xoá mục quá hạn này?", danger=True,
        ))
        menu_items.append(f'<div class="row-menu-info">Mã: {tid}</div>')
        items_html.append(f"""
<div class="sched-item sched-missed" data-sched-when="{html.escape(t.scheduled_at or '')}">
  <div class="sched-line">
    <label class="sched-check" title="Chọn để xoá hàng loạt"><input type="checkbox" name="task_ids" value="{tid}" form="missed-bulk-form"></label>
    <div class="sched-time">{_local_time_html(t.scheduled_at)}<small>quá {overdue_days_by_id[t.task_id]} ngày</small></div>
    <div class="sched-main">
      <div class="sched-title">{_action_badge_html(t.action)}{_sponsor_badge_html(t)}{_sched_target_html(t, name_lookup)}
        <span class="sched-acct">{html.escape(_account_label(t.account_id, accounts))} · hẹn {_local_dt_html(t.scheduled_at)}</span></div>
      <div class="sched-preview">{content_full}</div>
      {why_html}
    </div>
    <div class="sched-actions">
      <button type="button" class="btn-small"
              hx-get="/admin/schedule/missed/suggest?{reschedule_qs}" hx-target="#modal-root" hx-swap="innerHTML">🔄 Lên lịch lại</button>
      <form method="post" action="/admin/schedule/missed/fire-now"
            hx-post="/admin/schedule/missed/fire-now" hx-target="#schedule-content" hx-swap="outerHTML">
        <input type="hidden" name="task_id" value="{tid}">
        {filter_fields}
        <button type="submit" class="btn-secondary btn-small">🚀 Đăng ngay</button>
      </form>
      <button type="button" class="btn-secondary btn-small" aria-expanded="false" onclick="{_EDIT_TOGGLE}">📅 Đặt giờ khác</button>
      {_row_menu_html(menu_items)}
    </div>
  </div>
  <div class="sched-edit" hidden>
    <form method="post" action="/admin/schedule/missed/reschedule"
          hx-post="/admin/schedule/missed/reschedule" hx-target="#schedule-content" hx-swap="outerHTML">
      <input type="hidden" name="task_id" value="{tid}">
      {filter_fields}
      <textarea name="content" aria-label="Nội dung bài">{content_full}</textarea>
      <div class="sched-edit-row">
        {_datetime_picker_html("scheduled_at", current_value=t.scheduled_at, required=True, blank_hint=False)}
        <button type="submit" class="btn-small">📅 Đặt lịch</button>
        <button type="button" class="btn-secondary btn-small" onclick="{_EDIT_CLOSE}">Đóng</button>
      </div>
    </form>
  </div>
</div>""")

    return f"""
<form id="missed-bulk-form" method="post" action="/admin/schedule/missed/bulk-cancel"
      hx-post="/admin/schedule/missed/bulk-cancel" hx-target="#schedule-content" hx-swap="outerHTML"
      hx-confirm="Xoá tất cả mục đã chọn?">
  {filter_fields}
</form>
<p class="sched-help">Bài đến giờ đăng nhưng không chạy được (mất mạng, service tắt, tài khoản tắt hoặc tạm dừng…) được giữ lại ở đây chờ bạn xếp lại.
  Bài quá hạn hơn {schedule_store.STALE_MISSED_MAX_AGE_DAYS} ngày mà chưa xử lý sẽ tự bị huỷ (vẫn giữ lịch sử).</p>
<details class="mini-help" style="margin:-4px 0 12px;"><summary>Các nút làm gì?</summary>
  <div class="hint"><strong>🔄 Lên lịch lại</strong>: hệ thống gợi ý giờ trống gần nhất ·
    <strong>📅 Đặt giờ khác</strong>: tự chọn giờ và sửa nội dung ·
    <strong>↩️ Mượn giờ</strong> (menu ⋯): dùng giờ của một bài đang chờ, bài đó dời sang sau ·
    <strong>🚀 Đăng ngay</strong>: đăng lập tức.</div>
</details>
{toolbar_html}
{empty_note_html}
{f'<div class="sched-list">{"".join(items_html)}</div>' if items_html else ""}
{_missed_pagination_html(account_id, missed_page, total_pages, total, page_size, missed_min_days)}
"""


def _missed_pagination_html(
    account_id: str | None, missed_page: int, total_pages: int, total: int, page_size: int,
    missed_min_days: int | None = None,
) -> str:
    if total_pages <= 1:
        return ""
    jump_hidden_fields = (
        (f'<input type="hidden" name="account_id" value="{html.escape(account_id)}">' if account_id else "")
        + '<input type="hidden" name="tab" value="missed">'
        + (f'<input type="hidden" name="missed_min_days" value="{missed_min_days}">' if missed_min_days is not None else "")
        + f'<input type="hidden" name="page_size" value="{page_size}">'
    )
    return f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-top:14px; flex-wrap:wrap; gap:8px;">
  <div style="display:flex; gap:8px; align-items:center;">
    {_missed_page_link(account_id, 1, "«« Đầu", missed_page > 1, page_size, missed_min_days)}
    {_missed_page_link(account_id, missed_page - 1, "← Trang trước", missed_page > 1, page_size, missed_min_days)}
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
    {_missed_page_link(account_id, missed_page + 1, "Trang sau →", missed_page < total_pages, page_size, missed_min_days)}
    {_missed_page_link(account_id, total_pages, "Cuối »»", missed_page < total_pages, page_size, missed_min_days)}
  </div>
</div>"""


def _needs_review_section_html(accounts: dict) -> str:
    """"🔍 Chờ duyệt" tab (2026-10-08, owner request — data_sync.py's
    job_min_confidence gate, see sync_all()'s confidence split and
    _draft_needs_review_jobs()'s docstring). One row per NeedsReviewJob,
    NOT per group — a job's groups/contents are approved or rejected
    together as one unit, same granularity the draft was made at. Mirrors
    _missed_tasks_section_html()'s editable-textarea-per-item pattern;
    no pagination yet since this queue is expected to stay small (owner
    manually clears it), unlike the pending/missed tabs."""
    reviews = schedule_store.list_needs_review()
    if not reviews:
        return '<div class="empty-state">Không có tin tuyển dụng nào chờ duyệt.</div>'

    cfg = get_data_sync_config()
    items_html = []
    for r in reviews:
        title = _join_list_or_str((r.job_data or {}).get("title")) or "(không có tiêu đề)"
        # isinstance check, not `is not None` — defends the `:.2f` format below against a non-numeric value on
        # disk (a hand-edited needs_review/*.json, or a future caller that bypasses data_sync.py's own
        # _safe_job_confidence() guard at write time): ValueError there would otherwise crash this whole
        # tab's render, not just the one malformed row.
        confidence_html = (
            f"⚠️ Độ tin cậy: {r.confidence:.2f} (dưới mốc {cfg.job_min_confidence:.2f})"
            if isinstance(r.confidence, (int, float)) and not isinstance(r.confidence, bool)
            else f"⚠️ Thiếu trường độ tin cậy (confidence) — coi như chưa đủ tin cậy (mốc hiện tại: {cfg.job_min_confidence:.2f})"
        )
        # One textarea per group, side by side (they wrap on a narrow screen): a job's groups/contents are
        # approved or rejected together as one unit, but each group's text can be edited first.
        group_fields = []
        for i, (g, content) in enumerate(zip(r.groups, r.contents)):
            group_name = html.escape(g.get("name") or g.get("url") or f"nhóm {i + 1}")
            content_full = html.escape(content or "")
            group_fields.append(f"""
  <div class="sched-group">
    <div class="field-key">Nhóm: {group_name}</div>
    <textarea name="content_{i}" aria-label="Nội dung cho {group_name}">{content_full}</textarea>
  </div>""")
        first_content = html.escape((r.contents[0] if r.contents else "") or "")
        approve_form_id = f"needs-review-approve-{r.review_id}"
        reject_form_id = f"needs-review-reject-{r.review_id}"
        items_html.append(f"""
<div class="sched-item sched-review">
  <div class="sched-line">
    <div class="sched-main">
      <div class="sched-title">{_action_badge_html("post_to_group")}{_sponsor_badge_html(r)}<span class="sched-target">{html.escape(title)}</span>
        <span class="sched-acct">{html.escape(_account_label(r.account_id, accounts))} · {len(r.groups)} nhóm</span></div>
      <div class="sched-preview">{first_content}</div>
      <div class="sched-why">{confidence_html}</div>
    </div>
    <div class="sched-actions">
      <button type="submit" form="{approve_form_id}" class="btn-small">✅ Duyệt &amp; lên lịch</button>
      <button type="submit" form="{reject_form_id}" class="btn-secondary btn-small">🗑 Bỏ qua</button>
      <button type="button" class="btn-secondary btn-small" aria-expanded="false" onclick="{_EDIT_TOGGLE}">✎ Xem / sửa nội dung</button>
    </div>
  </div>
  <div class="sched-edit" hidden>
    <form id="{approve_form_id}" method="post" action="/admin/schedule/needs-review/{r.review_id}/confirm-modal"
          hx-post="/admin/schedule/needs-review/{r.review_id}/confirm-modal" hx-target="#modal-root" hx-swap="innerHTML">
      <div class="sched-groups">{"".join(group_fields)}</div>
    </form>
    <form id="{reject_form_id}" method="post" action="/admin/schedule/needs-review/{r.review_id}/reject"
          hx-post="/admin/schedule/needs-review/{r.review_id}/reject" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-confirm="Bỏ qua tin này? Nó sẽ không được đăng."></form>
  </div>
</div>""")

    return f"""
<p class="sched-help">Tin tuyển dụng có độ tin cậy dưới mốc hiện tại (hoặc thiếu hẳn) — đã soạn sẵn nội dung nhưng chưa được tự lên lịch.
  “✅ Duyệt &amp; lên lịch” tự tính giờ đăng hợp lệ gần nhất (đúng hạn mức và giờ yên tĩnh) ngay lúc bấm. Muốn đổi mốc:
  <a href="/admin/config?tab=sync">Cấu hình → Đồng bộ dữ liệu</a> (“Độ tin cậy tối thiểu để TỰ lên lịch đăng job”).</p>
<div class="sched-list">{"".join(items_html)}</div>"""


_SCHEDULE_TABS = ("pending", "missed", "needs_review")

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


def _clamp_missed_min_days(raw: int | None) -> int | None:
    return raw if raw in _MISSED_MIN_DAYS_CHOICES else None


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
    missed_min_days: int | None = None,
) -> str:
    page_size = _clamp_schedule_page_size(page_size)
    tab = _clamp_schedule_tab(tab)
    action_filter = _clamp_schedule_action(action_filter)
    date_filter = date_filter.strip() if date_filter else None
    missed_min_days = _clamp_missed_min_days(missed_min_days)
    accounts = get_all_accounts()
    if account_id and account_id not in accounts:
        account_id = None  # unknown/stale filter falls back to "all", never a hard error
    all_tasks = schedule_store.list_pending()
    missed_count = len(schedule_store.list_missed())
    needs_review_count = len(schedule_store.list_needs_review())
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
        f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(_account_label(aid, accounts))}</option>'
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
<div class="sched-toolbar">
  <label for="schedule-account-select">Tài khoản</label>
  <select name="account_id" id="schedule-account-select" hx-include="{_sched_filter_ids}"
          hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-trigger="change" hx-push-url="true">{account_options}</select>
  <label for="schedule-action-select">Việc</label>
  <select name="action" id="schedule-action-select" hx-include="{_sched_filter_ids}"
          hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-trigger="change" hx-push-url="true">{action_options}</select>
  <label for="schedule-date-input">Ngày</label>
  <input type="date" name="date" id="schedule-date-input" value="{html.escape(date_filter or "")}"
         hx-include="{_sched_filter_ids}"
         hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML"
         hx-trigger="change" hx-push-url="true">
  <input type="hidden" name="tz_offset" id="schedule-tz-offset" data-tz-offset-field value="{tz_offset}">
  {clear_filter_html}
  <select name="page_size" id="schedule-pagesize-select" aria-label="Số bài mỗi trang" hx-include="{_sched_filter_ids}"
          hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-trigger="change" hx-push-url="true">{page_size_options}</select>
  <span class="sched-count">{total} bài đang chờ</span>
</div>"""

    if page_tasks:
        items_html = []
        name_lookup = _group_name_lookup()
        now_utc = datetime.now(timezone.utc)
        # Every mutating form carries the current filter/page back so update / fire-now / cancel re-render the
        # SAME view instead of resetting to "all accounts, page 1" — the same for every row, so built once.
        filter_values = {
            "account_id": account_id or "", "page": str(page), "page_size": str(page_size),
            "action": action_filter or "", "date": date_filter or "", "tz_offset": str(tz_offset),
        }
        filter_fields = "".join(f'<input type="hidden" name="{k}" value="{html.escape(v)}">' for k, v in filter_values.items())
        for t in page_tasks:
            # The edit textarea's value is NOT truncated: opening "Sửa" and clicking "Lưu" on a long post
            # must not silently chop it (found in an admin UI review).
            content_full = html.escape(t.content or "")
            tid = html.escape(t.task_id)
            due_at = None
            try:
                due_at = datetime.fromisoformat(t.scheduled_at.replace("Z", "+00:00"))
                if due_at.tzinfo is None:
                    due_at = due_at.replace(tzinfo=timezone.utc)  # like schedule_store: a naive time is UTC
            except (ValueError, AttributeError):
                pass
            is_due = due_at is not None and due_at <= now_utc
            warning_html = f'<div class="sched-why">{html.escape(t.last_warning)}</div>' if t.last_warning else ""
            menu_items = [_menu_form(
                "/admin/schedule/swap-modal", {"task_id": t.task_id, **filter_values}, "⇄ Đổi giờ với bài khác",
                "Hoán đổi giờ đăng với một bài đang chờ", target="#modal-root", swap="innerHTML",
            )]
            if t.target_url:
                menu_items.append(_copy_url_button(t.target_url))
            menu_items.append('<hr class="row-menu-sep">')
            menu_items.append(_menu_form(
                "/admin/schedule/cancel", {"task_id": t.task_id, **filter_values}, "🗑 Huỷ lịch đăng",
                "Bài này sẽ không được đăng", target="#schedule-content", confirm="Huỷ lịch đăng này?", danger=True,
            ))
            menu_items.append(f'<div class="row-menu-info">Mã: {tid}</div>')
            items_html.append(f"""
<div class="sched-item{' sched-due' if is_due else ''}" data-sched-when="{html.escape(t.scheduled_at or '')}">
  <div class="sched-line">
    <div class="sched-time">{_local_time_html(t.scheduled_at)}{'<small>⏰ đến giờ</small>' if is_due else ''}</div>
    <div class="sched-main">
      <div class="sched-title">{_action_badge_html(t.action)}{_sponsor_badge_html(t)}{_sched_target_html(t, name_lookup)}
        <span class="sched-acct">{html.escape(_account_label(t.account_id, accounts))}</span></div>
      <div class="sched-preview">{content_full}</div>
      {warning_html}
    </div>
    <div class="sched-actions">
      <form method="post" action="/admin/schedule/fire-now"
            hx-post="/admin/schedule/fire-now" hx-target="#schedule-content" hx-swap="outerHTML"
            hx-confirm="Đăng bài này lên Facebook ngay bây giờ?">
        <input type="hidden" name="task_id" value="{tid}">
        {filter_fields}
        <button type="submit" class="btn-small{'' if is_due else ' btn-secondary'}">🚀 Đăng ngay</button>
      </form>
      <button type="button" class="btn-secondary btn-small" aria-expanded="false" onclick="{_EDIT_TOGGLE}">✎ Sửa</button>
      {_row_menu_html(menu_items)}
    </div>
  </div>
  <div class="sched-edit" hidden>
    <form method="post" action="/admin/schedule/update" hx-post="/admin/schedule/update" hx-target="#schedule-content" hx-swap="outerHTML">
      <input type="hidden" name="task_id" value="{tid}">
      {filter_fields}
      <textarea name="content" aria-label="Nội dung bài">{content_full}</textarea>
      <div class="sched-edit-row">
        {_datetime_picker_html("scheduled_at", current_value=t.scheduled_at, required=True, blank_hint=False)}
        <button type="submit" class="btn-small">Lưu</button>
        <button type="button" class="btn-secondary btn-small" onclick="{_EDIT_CLOSE}">Đóng</button>
      </div>
    </form>
  </div>
</div>""")
        list_html = f'<div class="sched-list" data-sched-days>{"".join(items_html)}</div>'
    elif total == 0:
        list_html = '<div class="empty-state">Chưa có bài nào đang chờ lịch. Khi bên B có dữ liệu mới, bot sẽ tự điền vào đây — hoặc bạn soạn tay ở <a href="/admin/post">Đăng bài</a>.</div>'
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
        qs = _urlencode_tab({k: v for k, v in {
            "account_id": account_id, "tab": tab_key,
            "page_size": page_size if page_size != _SCHEDULE_PAGE_SIZE else None,
        }.items() if v})
        return (
            f'<a href="/admin/schedule?{qs}" hx-get="/admin/schedule?{qs}" '
            f'hx-target="#schedule-content" hx-swap="outerHTML" hx-push-url="true" '
            f'class="sched-tab{" active" if tab_key == tab else ""}">{label}</a>'
        )

    tab_nav_html = f"""
<div class="sched-tabs">
  {_schedule_tab_link("pending", f"📋 Đã lên lịch ({total})")}
  {_schedule_tab_link("missed", f"⚠️ Quá hạn ({missed_count})")}
  {_schedule_tab_link("needs_review", f"🔍 Chờ duyệt ({needs_review_count})")}
</div>"""

    if tab == "missed":
        tab_body_html = _missed_tasks_section_html(account_id, page, page_size, accounts, missed_page, missed_min_days)
    elif tab == "needs_review":
        tab_body_html = _needs_review_section_html(accounts)
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
    missed_min_days: str | None = None,
    _: None = Depends(_require_login),
) -> str:
    # missed_min_days arrives as a STRING query param (not int | None)
    # because the "— Tất cả —" filter option's value is "" — FastAPI
    # would 422 trying to coerce an empty string straight to int before
    # this function body even runs (confirmed live 2026-09-24: picking
    # "Tất cả" sent `missed_min_days=`, htmx got a 422 JSON error back
    # instead of the updated list, so the filter never visibly cleared).
    # Parse leniently here instead, same try/int()/except pattern
    # _schedule_form_filter() already uses for the POST-form version of
    # this same field.
    try:
        missed_min_days_int = int(missed_min_days) if missed_min_days else None
    except ValueError:
        missed_min_days_int = None
    content = _schedule_content_html(account_id=account_id, page=page, page_size=page_size, saved=saved, error=error, tab=tab, missed_page=missed_page, action_filter=action, date_filter=date, tz_offset=tz_offset, missed_min_days=missed_min_days_int)
    if _is_htmx(request):
        return content
    return _layout(f"""
<h1>Lịch đăng</h1>
<p class="page-desc">Mọi bài chờ đăng, tự động hay soạn tay, đều nằm ở đây trước khi chạy.</p>
{_auto_fire_status_html()}
{content}
""", active="schedule", current_user=_build_current_user(request))


def _schedule_redirect(account_id: str | None, page: int, **params) -> RedirectResponse:
    from urllib.parse import urlencode
    query = {"account_id": account_id, "page": page, **params}
    query = {k: v for k, v in query.items() if v not in (None, "", 0)}
    return RedirectResponse(url=f"/admin/schedule?{urlencode(query)}", status_code=303)


def _schedule_form_filter(form) -> tuple[str | None, int, int, int, str | None, str | None, int, int | None]:
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
    # missed_min_days (2026-09-24, owner request) — mirror image of
    # action_filter/date_filter above: only meaningful for the missed
    # tab's own filter, unpacked-but-unused by the pending-tab handlers.
    try:
        missed_min_days = _clamp_missed_min_days(int(str(form.get("missed_min_days", ""))))
    except ValueError:
        missed_min_days = None
    return account_id, page, page_size, missed_page, action_filter, date_filter, tz_offset, missed_min_days


@router.post("/schedule/update")
async def schedule_update(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id, page, page_size, missed_page, action_filter, date_filter, tz_offset, _missed_min_days = _schedule_form_filter(form)
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
async def schedule_cancel(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id, page, page_size, missed_page, action_filter, date_filter, tz_offset, _missed_min_days = _schedule_form_filter(form)
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
async def schedule_missed_reschedule(request: Request, _: None = Depends(_require_login)):
    """"📅 Đặt lịch" on a missed task — admin picks the content/time by
    hand, same edit form shape as schedule_update() above, but the SOURCE
    is missed/ instead of pending/ (schedule_store.restore_to_pending())."""
    form = await request.form()
    account_id, page, page_size, missed_page, _action_filter, _date_filter, _tz_offset, missed_min_days = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    content = str(form.get("content", ""))
    scheduled_at = str(form.get("scheduled_at", ""))
    restored = schedule_store.restore_to_pending(task_id, content=content, scheduled_at=scheduled_at)
    if restored is None:
        err = "Không tìm thấy mục này (có thể đã được xử lý ở tab khác)"
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=err))
        return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=err)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=True))
    return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=1)


@router.get("/schedule/missed/suggest", response_class=HTMLResponse)
async def schedule_missed_suggest(
    task_id: str, account_id: str | None = None, page: int = 1, page_size: int = _SCHEDULE_PAGE_SIZE,
    missed_page: int = 1, missed_min_days: int | None = None,
    _: None = Depends(_require_login),
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
        f'<input type="hidden" name="missed_min_days" value="{missed_min_days if missed_min_days is not None else ""}">'
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
async def schedule_missed_reschedule_confirm(request: Request, _: None = Depends(_require_login)):
    """"🔄 Lên lịch lại" step 2 — admin confirmed the suggested slot."""
    form = await request.form()
    account_id, page, page_size, missed_page, _action_filter, _date_filter, _tz_offset, missed_min_days = _schedule_form_filter(form)
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
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=err) + _MODAL_CLOSE_OOB)
    return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=True) + _MODAL_CLOSE_OOB)


def _borrow_modal_html(
    task: schedule_store.ScheduledTask, account,
    account_id: str | None, page: int, page_size: int, missed_page: int, missed_min_days: int | None,
    error: str | None = None,
) -> str:
    """"↩️ Mượn giờ" modal (owner request 2026-09-29, "đổi giờ" giai đoạn 2
    — task quá hạn LẤY giờ của 1 task đang chờ (pending), task đang chờ đó
    bị dời sang giờ mới do _suggest_reschedule_at() tìm — KHÔNG phải hoán
    đổi 2 chiều như "⇄ Đổi giờ" (schedule_swap ở trên), vì scheduled_at
    của task quá hạn đã ở quá khứ, gán ngược lại cho task pending sẽ biến
    nó thành quá hạn ngay lập tức.

    Same eligibility rule as _swap_candidates() (same account_id + same
    RateLimiter bucket) — reused as-is rather than duplicated, since
    "which slot is safe to hand to this task" doesn't depend on which
    directory the task making the request currently sits in.

    Shows each candidate's OWN current time AND the time it would be
    displaced TO if picked (computed with `exclude_task_id` so the
    candidate's own still-there old slot doesn't block its own new
    suggestion — see _suggest_reschedule_at()'s docstring) — the admin
    sees the real consequence before confirming, same "preview before
    commit" spirit as "🔄 Lên lịch lại"."""
    filter_fields = (
        f'<input type="hidden" name="account_id" value="{html.escape(account_id or "")}">'
        f'<input type="hidden" name="page" value="{page}">'
        f'<input type="hidden" name="page_size" value="{page_size}">'
        f'<input type="hidden" name="missed_page" value="{missed_page}">'
        f'<input type="hidden" name="missed_min_days" value="{missed_min_days if missed_min_days is not None else ""}">'
        f'<input type="hidden" name="task_id_a" value="{html.escape(task.task_id)}">'
    )
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    candidates = _swap_candidates(task) if account else []
    if not candidates:
        body = '<p class="muted">Không có bài nào đang chờ đăng cùng tài khoản + cùng loại hành động (đăng bài / bình luận) để mượn giờ.</p>'
    else:
        rows = []
        for c in candidates:
            # Deliberately NO exclude_task_id here (owner-caught bug
            # 2026-09-29, same root cause as schedule_missed_borrow_
            # confirm()'s own fix — see that route's comment): the missed
            # task A will take over EXACTLY this candidate's current
            # slot, so that slot stays "occupied" either way — counting
            # `c` itself (not excluding it) is what correctly models
            # that for THIS preview, matching what confirm will actually
            # compute once A is inserted there for real. Excluding it
            # here (the original, wrong version) undercounted the day by
            # 1 and could show a slot that's actually already full.
            new_time = _suggest_reschedule_at(account, c.action)
            rows.append(f"""
    <label style="display:flex; gap:8px; align-items:baseline; padding:6px 0; border-bottom:1px solid #eee;">
      <input type="radio" name="task_id_b" value="{html.escape(c.task_id)}" required>
      <span>{_local_dt_html(c.scheduled_at)} — {html.escape((c.content or "")[:80])}<br>
        <span class="muted">→ nếu chọn, bài này dời sang: {_local_dt_html(new_time.isoformat())}</span></span>
    </label>""")
        body = f'<div style="max-height:320px; overflow-y:auto;">{"".join(rows)}</div>'
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>↩️ Mượn giờ đăng</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    {err_html}
    <p class="page-desc" style="margin-top:0;">Bài quá hạn: {_local_dt_html(task.scheduled_at)} — {html.escape((task.content or "")[:80])}</p>
    <p class="muted">Chọn 1 bài đang chờ đăng, cùng tài khoản + cùng loại hành động — bài quá hạn ở trên sẽ đăng vào đúng giờ của bài đó, còn bài đó dời sang giờ mới như xem trước bên dưới.</p>
    <form method="post" action="/admin/schedule/missed/borrow-confirm"
          hx-post="/admin/schedule/missed/borrow-confirm" hx-target="#schedule-content" hx-swap="outerHTML">
      {filter_fields}
      {body}
      <div class="form-actions">
        <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        <button type="submit"{" disabled" if not candidates else ""}>Mượn giờ</button>
      </div>
    </form>
  </div>
</div>"""


@router.get("/schedule/missed/borrow", response_class=HTMLResponse)
async def schedule_missed_borrow(
    task_id: str, account_id: str | None = None, page: int = 1, page_size: int = _SCHEDULE_PAGE_SIZE,
    missed_page: int = 1, missed_min_days: int | None = None,
    _: None = Depends(_require_login),
) -> str:
    task = schedule_store.get_missed(task_id)
    if task is None:
        return ""
    account = get_all_accounts().get(task.account_id)
    page_size = _clamp_schedule_page_size(page_size)
    if account is None:
        return _borrow_modal_html(task, None, account_id, page, page_size, missed_page, missed_min_days, error="Không tìm thấy tài khoản này.")
    return _borrow_modal_html(task, account, account_id, page, page_size, missed_page, missed_min_days)


@router.post("/schedule/missed/borrow-confirm")
async def schedule_missed_borrow_confirm(request: Request, _: None = Depends(_require_login)):
    """"↩️ Mượn giờ" step 2 — re-validates the pairing server-side (same
    reasoning as schedule_swap() above: a plain POST an admin could hand-
    edit) and RE-COMPUTES the displaced task's new slot rather than
    trusting whatever the preview modal last rendered, in case something
    else changed the account's schedule in between."""
    form = await request.form()
    account_id, page, page_size, missed_page, _action_filter, _date_filter, _tz_offset, missed_min_days = _schedule_form_filter(form)
    task_id_a = str(form.get("task_id_a", ""))
    task_id_b = str(form.get("task_id_b", ""))
    task_a = schedule_store.get_missed(task_id_a)
    task_b = schedule_store.get(task_id_b)
    error: str | None = None
    account = None
    if task_a is None or task_b is None:
        error = "Không tìm thấy 1 trong 2 mục này — có thể đã bị đổi/huỷ ở nơi khác."
    else:
        from human_bot.agent import rate_limit_bucket_for
        if task_a.account_id != task_b.account_id or rate_limit_bucket_for(task_a.action) != rate_limit_bucket_for(task_b.action):
            error = "2 bài phải cùng tài khoản và cùng loại hành động (đăng bài / bình luận) mới mượn giờ được."
        else:
            account = get_all_accounts().get(task_a.account_id)
            if account is None:
                error = "Không tìm thấy tài khoản này."
    if error:
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=error) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=error)

    # Order matters (owner-caught bug 2026-09-29, before this ever shipped):
    # A must be INSERTED into pending FIRST, then B's new slot computed —
    # not the other way around. Computing B's new slot before A lands
    # means the day-cap check below only sees {other 4 tasks} on B's old
    # day (B itself excluded, A not inserted yet) → looks like room for
    # one more → often suggests B right back onto that SAME day, which,
    # once A actually takes B's old slot afterward, leaves that day at
    # 6 tasks (5 others + relocated B, PLUS A) instead of 5. Inserting A
    # first means the day-cap check correctly sees "A + other 4" already
    # there when it decides whether B can still fit that day too.
    old_b_time = task_b.scheduled_at
    schedule_store.restore_to_pending(task_id_a, scheduled_at=old_b_time)
    new_b_time = _suggest_reschedule_at(account, task_b.action, exclude_task_id=task_b.task_id)
    schedule_store.update(task_id_b, scheduled_at=new_b_time.isoformat())
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=True) + _MODAL_CLOSE_OOB)
    return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=1)


@router.post("/schedule/missed/cancel")
async def schedule_missed_cancel(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id, page, page_size, missed_page, _action_filter, _date_filter, _tz_offset, missed_min_days = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    schedule_store.cancel_missed(task_id)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=True))
    return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=1)


@router.post("/schedule/missed/bulk-cancel")
async def schedule_missed_bulk_cancel(request: Request, _: None = Depends(_require_login)):
    """"🗑️ Xoá đã chọn" — the "chọn nhiều/chọn tất cả rồi xoá một lúc"
    owner asked for. `task_ids` arrives as a repeated form field (each
    checked checkbox); every id gets cancel_missed()'d independently —
    an id that's already gone (someone else resolved it, or a double
    submit) is simply a no-op, never an error for the whole batch."""
    form = await request.form()
    account_id, page, page_size, missed_page, _action_filter, _date_filter, _tz_offset, missed_min_days = _schedule_form_filter(form)
    task_ids = [str(v) for v in form.getlist("task_ids") if str(v).strip()]
    for task_id in task_ids:
        schedule_store.cancel_missed(task_id)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=True))
    return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=1)


def _needs_review_eligible_accounts(review: schedule_store.NeedsReviewJob) -> dict[str, AccountConfig]:
    """Accounts the admin may pick at the "✅ Duyệt & lên lịch" confirm
    step (2026-10-08, owner request) — must have at least 1 joined group
    to post to, and (same constraint data_sync.py's
    _draft_needs_review_jobs() already enforces at draft time) a
    sponsored_only account is only offered for a job that actually
    carries a sponsored_by value."""
    sponsored_by = (review.job_data or {}).get("sponsored_by")
    return {
        aid: acc for aid, acc in get_all_accounts().items()
        if get_joined_groups(aid) and (sponsored_by or not acc.sponsored_only)
    }


@router.post("/schedule/needs-review/{review_id}/confirm-modal", response_class=HTMLResponse)
async def schedule_needs_review_confirm_modal(review_id: str, request: Request, _: None = Depends(_require_login)) -> str:
    """"✅ Duyệt & lên lịch" step 1 (2026-10-08, owner request: a
    confirmation step, plus letting the admin override which account
    performs the post instead of always the one
    _draft_needs_review_jobs() picked at draft time). POST, not GET like
    most other confirm-modal first steps in this file — this one needs
    the CURRENTLY EDITED content_{i} values from the main card's own
    form, carried forward here as hidden inputs so an edit the admin just
    made isn't lost between opening this modal and the real approve
    step below."""
    form = await request.form()
    review = schedule_store.get_needs_review(review_id)
    if review is None:
        return (
            '<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">'
            '<div class="modal-box"><p class="error">⚠️ Không tìm thấy job chờ duyệt này (có thể đã được xử lý).</p></div></div>'
        )
    eligible = _needs_review_eligible_accounts(review)
    if not eligible:
        return (
            '<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">'
            '<div class="modal-box"><p class="error">⚠️ Không có tài khoản hợp lệ nào (đã tham gia nhóm) để đăng job này.</p></div></div>'
        )
    hidden_content_fields = "".join(
        f'<input type="hidden" name="content_{i}" value="{html.escape(str(form.get(f"content_{i}", "")))}">'
        for i in range(len(review.groups))
    )
    options_html = "".join(
        f'<option value="{html.escape(aid)}"{" selected" if aid == review.account_id else ""}>{html.escape(acc.display_name)} ({html.escape(aid)})</option>'
        for aid, acc in sorted(eligible.items())
    )
    title = _join_list_or_str((review.job_data or {}).get("title")) or "(không có tiêu đề)"
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>✅ Duyệt &amp; lên lịch</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    <p>{html.escape(title)}</p>
    <p class="muted">Giờ đăng sẽ được tự tính ngay sau khi xác nhận (tôn trọng hạn mức/khoảng cách tối thiểu/giờ yên tĩnh của tài khoản được chọn).</p>
    <form method="post" action="/admin/schedule/needs-review/{review_id}/approve"
          hx-post="/admin/schedule/needs-review/{review_id}/approve" hx-target="#schedule-content" hx-swap="outerHTML">
      {hidden_content_fields}
      <div class="field-input">
        <label for="needs-review-account-select">Tài khoản đăng</label>
        <select name="account_id" id="needs-review-account-select">{options_html}</select>
      </div>
      <div class="form-actions">
        <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        <button type="submit">✅ Xác nhận</button>
      </div>
    </form>
  </div>
</div>"""


_REVIEW_MISSING_ERR = "Không tìm thấy job chờ duyệt này (có thể đã được xử lý)"
_REVIEW_ACCOUNT_GONE_ERR = "Tài khoản dự kiến đăng không còn tồn tại — không thể duyệt"
_REVIEW_RACE_ERR = "Job này vừa được xử lý ở nơi khác (có thể do bấm 2 lần)"
# The two "somebody else already handled it" outcomes — callers that need to
# treat those differently from a real failure compare against THIS set, not
# against individual message strings.
REVIEW_ALREADY_HANDLED_ERRS = frozenset({_REVIEW_MISSING_ERR, _REVIEW_RACE_ERR})


def approve_needs_review_core(review_id: str, submitted_account_id: str = "", form=None) -> tuple[str | None, int]:
    """The whole "✅ Duyệt & lên lịch" step 2, shared by the /admin route
    below and by the Telegram "✅ Duyệt" button (2026-10-16) so both go
    through exactly the same claim → re-pick groups → slot-per-group logic.
    Returns (error_message_or_None, number_of_tasks_created). `form` is the
    admin page's submitted form (its edited content_{i} fields); Telegram
    passes None and gets the drafted contents as-is.

    Original notes ("✅ Duyệt & lên lịch" step 2 (2026-10-08, owner request — see
    data_sync.py's _draft_needs_review_jobs() for how this row was
    drafted, and schedule_needs_review_confirm_modal() right above for
    step 1's confirmation + account-choice modal). The review is claimed
    (approve_needs_review(), removing its file) as soon as it's confirmed
    to exist and its account is valid — BEFORE the per-group loop runs,
    not after: a double-click/retry that reached this route a second
    time while the first request was still looping would otherwise find
    the SAME review still present and re-create ScheduledTasks for
    groups the first request already scheduled, duplicate-posting the
    same content. Once claimed, for each group: compute a real slot via
    _suggest_reschedule_at() (same engine "🔄 Lên lịch lại" uses for a
    missed task — re-checks capacity/gap/quiet-hours FRESH right now, not
    trusting the draft-time pick, and already accounts for pending tasks
    this same loop just added) and write a real ScheduledTask into
    pending/ immediately, so the NEXT group's own suggestion call sees it
    and lands after it.

    If the admin picked a DIFFERENT account than the one drafted at
    _draft_needs_review_jobs() time, `review.groups` (chosen for the
    ORIGINAL account) cannot be reused as-is — the new account may not
    even be a member of those groups. Groups are re-picked fresh for the
    NEW account instead (same _pick_groups_for_job() the draft step
    itself uses, asking for the same COUNT of groups as the draft had),
    paired with the already-edited content list by position — the
    content itself doesn't need to change, only the opener line varies
    by position (template_variants()'s own docstring), so re-pairing by
    index is still meaningful even though the groups themselves are new."""
    review = schedule_store.get_needs_review(review_id)
    if review is None:
        return _REVIEW_MISSING_ERR, 0
    eligible = _needs_review_eligible_accounts(review)
    submitted_account_id = (submitted_account_id or "").strip()
    # Only an account still ELIGIBLE right now may be chosen — a stale/
    # tampered value (or one that lost its only joined group since the
    # confirm modal was opened) falls back to the review's own drafted
    # account_id, same as if the admin had never touched the dropdown.
    chosen_account_id = submitted_account_id if submitted_account_id in eligible else review.account_id
    account = eligible.get(chosen_account_id) or get_all_accounts().get(chosen_account_id)
    if account is None:
        return _REVIEW_ACCOUNT_GONE_ERR, 0
    if not schedule_store.approve_needs_review(review_id):
        # Lost the race to a concurrent approve/reject on the SAME review
        # between our get_needs_review() above and now — graceful no-op,
        # same "already resolved" framing as the review-missing case above.
        return _REVIEW_RACE_ERR, 0
    created_ids: list[str] = []
    try:
        if chosen_account_id != review.account_id:
            groups = [
                dataclasses.asdict(g) for g in
                _pick_groups_for_job(get_joined_groups(chosen_account_id), {}, needed=len(review.groups))
            ]
        else:
            groups = review.groups
        if not groups:
            # Nothing to schedule: don't leave the claimed review gone with
            # "0 tasks created" — put it back and say why.
            schedule_store.add_needs_review(review)
            return "Không chọn được nhóm nào để đăng cho job này — kiểm tra nhóm của tài khoản", 0
        for i, group in enumerate(groups):
            _schedule_one_review_group(review, i, group, chosen_account_id, account, form, created_ids)
    except Exception:
        # The review was already claimed (file removed) above, so a failure
        # midway would otherwise lose it with only SOME groups scheduled
        # (code review 2026-10-16). Undo: cancel what was created and put
        # the review back so it can be approved again.
        all_undone = True
        for task_id in created_ids:
            all_undone = schedule_store.cancel(task_id) and all_undone
        if all_undone:
            schedule_store.add_needs_review(review)
        # else: a task was already picked up for firing and can't be undone —
        # restoring the review too would make a re-approval post it twice.
        raise
    return None, len(created_ids)


def _schedule_one_review_group(review, i, group, chosen_account_id, account, form, created_ids: list[str]) -> None:
    # A SUBMITTED (even blank) field is honored as-is — an admin who
    # deliberately clears a group's textarea before approving must
    # not have that edit silently discarded. Falling back to the
    # original draft only when the field is entirely ABSENT (a
    # malformed/manual request, never the real form).
    content = str(form[f"content_{i}"]).strip() if form is not None and f"content_{i}" in form else (
        review.contents[i] if i < len(review.contents) else ""
    )
    scheduled_at = _suggest_reschedule_at(account, "post_to_group")
    task = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
        action="post_to_group",
        account_id=chosen_account_id,
        scheduled_at=scheduled_at.isoformat(),
        content=content,
        target_url=group.get("url"),
        reasoning=f"admin-approved from review: {review.reasoning}",
        source_kind=review.source_kind,
        source_id=review.source_id,
        job_data=review.job_data,
    )
    schedule_store.add(task)
    created_ids.append(task.task_id)


@router.post("/schedule/needs-review/{review_id}/approve")
async def schedule_needs_review_approve(review_id: str, request: Request, _: None = Depends(_require_login)):
    """"✅ Duyệt & lên lịch" step 2 — see approve_needs_review_core()'s
    docstring for the full logic; this only adapts it to the web form."""
    form = await request.form()
    err, _created = approve_needs_review_core(review_id, str(form.get("account_id") or ""), form)
    if err:
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(tab="needs_review", error=err) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(None, 1, tab="needs_review", error=err)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(tab="needs_review", saved=True) + _MODAL_CLOSE_OOB)
    return _schedule_redirect(None, 1, tab="needs_review", saved=1)


@router.post("/schedule/needs-review/{review_id}/reject")
async def schedule_needs_review_reject(review_id: str, request: Request, _: None = Depends(_require_login)):
    """"🗑️ Bỏ qua" — moves the review file to schedule_store.
    REJECTED_REVIEW_DIR (never deleted outright, same audit-trail
    reasoning as cancel()/cancel_missed()). The job itself was already
    _mark_seen()'d when drafted, so it will not be re-fetched/re-drafted
    on a later poll."""
    schedule_store.reject_needs_review(review_id)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(tab="needs_review", saved=True))
    return _schedule_redirect(None, 1, tab="needs_review", saved=1)


# Closes the "Vẫn đăng ngay?" rate-limit modal (see
# _fire_now_confirm_modal_html()) via an out-of-band swap tacked onto
# every htmx response from schedule_fire_now() — harmless when no modal
# is open (an empty #modal-root swapped for an empty #modal-root).
_MODAL_CLOSE_OOB = '<div id="modal-root" hx-swap-oob="true"></div>'


def _swap_candidates(task: schedule_store.ScheduledTask) -> list[schedule_store.ScheduledTask]:
    """Other PENDING tasks eligible to trade `scheduled_at` with `task`
    (owner request 2026-09-29, "đổi giờ đăng giữa 2 bài viết" — pending↔
    pending only for now, missed↔pending is a later piece). Same
    account_id AND same RateLimiter bucket (agent.py's
    rate_limit_bucket_for() — "post" covers post_to_group/
    post_to_own_profile, "comment" covers comment_on_group_post/
    comment_on_friend_post) — owner's own reasoning (2026-09-29): each
    slot was already validated for that exact account+bucket combination
    when its own task was scheduled, so only another task of the SAME
    account+bucket can safely inherit it without re-checking daily caps/
    gaps/quiet-hours. Sorted by time so the modal reads like the pending
    list itself."""
    from human_bot.agent import rate_limit_bucket_for
    bucket = rate_limit_bucket_for(task.action)
    if bucket is None:
        return []
    others = [
        t for t in schedule_store.list_pending()
        if t.task_id != task.task_id
        and t.account_id == task.account_id
        and rate_limit_bucket_for(t.action) == bucket
    ]
    others.sort(key=lambda t: t.scheduled_at)
    return others


def _swap_modal_html(
    task: schedule_store.ScheduledTask, candidates: list[schedule_store.ScheduledTask],
    account_id: str | None, page: int, page_size: int,
    action_filter: str | None, date_filter: str | None, tz_offset: int,
    error: str | None = None,
) -> str:
    filter_fields = (
        f'<input type="hidden" name="account_id" value="{html.escape(account_id or "")}">'
        f'<input type="hidden" name="page" value="{page}">'
        f'<input type="hidden" name="page_size" value="{page_size}">'
        f'<input type="hidden" name="action" value="{html.escape(action_filter or "")}">'
        f'<input type="hidden" name="date" value="{html.escape(date_filter or "")}">'
        f'<input type="hidden" name="tz_offset" value="{tz_offset}">'
    )
    err_html = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    if not candidates:
        body = '<p class="muted">Không có bài nào khác cùng tài khoản + cùng loại hành động (đăng bài / bình luận) để đổi giờ.</p>'
    else:
        rows = "".join(f"""
    <label style="display:flex; gap:8px; align-items:baseline; padding:6px 0; border-bottom:1px solid #eee;">
      <input type="radio" name="task_id_b" value="{html.escape(c.task_id)}" required>
      <span>{_local_dt_html(c.scheduled_at)} — {html.escape((c.content or "")[:80])}</span>
    </label>""" for c in candidates)
        body = f'<div style="max-height:320px; overflow-y:auto;">{rows}</div>'
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>⇄ Đổi giờ đăng</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    {err_html}
    <p class="page-desc" style="margin-top:0;">Bài đang chọn: {_local_dt_html(task.scheduled_at)} — {html.escape((task.content or "")[:80])}</p>
    <p class="muted">Chọn 1 bài khác cùng tài khoản, cùng loại hành động để đổi giờ đăng cho nhau.</p>
    <form method="post" action="/admin/schedule/swap"
          hx-post="/admin/schedule/swap" hx-target="#schedule-content" hx-swap="outerHTML">
      <input type="hidden" name="task_id_a" value="{html.escape(task.task_id)}">
      {filter_fields}
      {body}
      <div class="form-actions">
        <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
        <button type="submit"{" disabled" if not candidates else ""}>Đổi giờ</button>
      </div>
    </form>
  </div>
</div>"""


@router.post("/schedule/swap-modal")
async def schedule_swap_modal(request: Request, _: None = Depends(_require_login)):
    form = await request.form()
    account_id, page, page_size, _missed_page, action_filter, date_filter, tz_offset, _missed_min_days = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    task = schedule_store.get(task_id)
    if task is None:
        return HTMLResponse('<div class="modal-backdrop" onclick="if(event.target===this) this.remove()"><div class="modal-box"><p class="error">⚠️ Không tìm thấy mục này — có thể đã bị đổi/huỷ ở nơi khác.</p></div></div>')
    candidates = _swap_candidates(task)
    return HTMLResponse(_swap_modal_html(task, candidates, account_id, page, page_size, action_filter, date_filter, tz_offset))


@router.post("/schedule/swap")
async def schedule_swap(request: Request, _: None = Depends(_require_login)):
    """Trade `scheduled_at` between two pending tasks — see
    schedule_store.swap_scheduled_at()'s docstring for why no daily-cap/
    gap/quiet-hours re-check happens here: it's guaranteed by only ever
    offering same-account+same-bucket candidates in the modal above.
    Re-validates that pairing here too (not just trusting the modal's own
    filtering) since the form is a plain POST an admin could otherwise
    hand-edit."""
    form = await request.form()
    account_id, page, page_size, _missed_page, action_filter, date_filter, tz_offset, _missed_min_days = _schedule_form_filter(form)
    task_id_a = str(form.get("task_id_a", ""))
    task_id_b = str(form.get("task_id_b", ""))
    task_a = schedule_store.get(task_id_a)
    task_b = schedule_store.get(task_id_b)
    error: str | None = None
    if task_a is None or task_b is None:
        error = "Không tìm thấy 1 trong 2 mục này — có thể đã bị đổi/huỷ ở nơi khác."
    else:
        from human_bot.agent import rate_limit_bucket_for
        if task_a.account_id != task_b.account_id or rate_limit_bucket_for(task_a.action) != rate_limit_bucket_for(task_b.action):
            error = "2 bài phải cùng tài khoản và cùng loại hành động (đăng bài / bình luận) mới đổi giờ được."
    if error:
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset, error=error) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, error=error)
    schedule_store.swap_scheduled_at(task_id_a, task_id_b)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, action_filter=action_filter, date_filter=date_filter, tz_offset=tz_offset, saved=True) + _MODAL_CLOSE_OOB)
    return _schedule_redirect(account_id, page, page_size=page_size, action=action_filter, date=date_filter, tz_offset=tz_offset, saved=1)


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
async def schedule_fire_now(request: Request, _: None = Depends(_require_login)):
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
    account_id, page, page_size, missed_page, action_filter, date_filter, tz_offset, _missed_min_days = _schedule_form_filter(form)
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
    if account and bucket:
        # daily_limits.can_proceed() (2026-09-11), not RateLimiter.can_proceed()
        # directly — see human_bot/daily_limits.py's module docstring.
        #
        # 2026-09-25 fix (found while writing tests/test_admin_schedule.py
        # for this route's copy, schedule_missed_fire_now() — see that
        # function's own fix note from the same day for the full story):
        # calling can_proceed(..., ignore_gap=force) UNCONDITIONALLY,
        # rather than skipping this whole call when force is set, is what
        # guarantees the hard per-day/per-hour cap is still checked on a
        # forced resubmit — ignore_gap=True only ever skips can_proceed()'s
        # OWN internal soft-gap check, never the hard-cap branches below
        # it. The old `and not force` guard let a forced resubmit skip
        # BOTH checks, not just the gap one — never surfaced in normal
        # use (force=1 is only ever sent from the gap-only confirmation
        # modal below), but a stale/direct force=1 after the day's slot
        # filled up in between would have wrongly gone through.
        allowed, reason = daily_limits.can_proceed(account, bucket, ignore_gap=force)
        if not allowed and not force and is_gap_reason(reason):
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
        scheduled_task_id=task.task_id,
        retries=task.retries,
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
    if db.is_rate_limited(result.message):
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


def _missed_fire_now_confirm_modal_html(
    task_id: str, account_id: str | None, page: int, page_size: int, missed_page: int,
    missed_min_days: int | None, warning: str,
) -> str:
    """"⚠️ Task quá hạn"'s own "🚀 Đăng ngay" rate-limit confirmation —
    same idea and same restriction as _fire_now_confirm_modal_html() right
    above (only ever offered for the soft min-gap pacing check, never a
    hard per-day/per-hour count cap — see that function's docstring for
    why), just carrying this tab's own filter fields (tab=missed,
    missed_page, missed_min_days) instead of the "Chờ đăng" tab's
    (action/date/tz_offset) so re-rendering after either choice lands
    back on the missed list, not the pending one."""
    filter_fields = (
        f'<input type="hidden" name="account_id" value="{html.escape(account_id or "")}">'
        f'<input type="hidden" name="page" value="{page}">'
        f'<input type="hidden" name="page_size" value="{page_size}">'
        f'<input type="hidden" name="tab" value="missed">'
        f'<input type="hidden" name="missed_page" value="{missed_page}">'
        f'<input type="hidden" name="missed_min_days" value="{missed_min_days if missed_min_days is not None else ""}">'
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
      <form method="post" action="/admin/schedule/missed/fire-now"
            hx-post="/admin/schedule/missed/fire-now" hx-target="#schedule-content" hx-swap="outerHTML"
            style="display:inline;">
        <input type="hidden" name="task_id" value="{html.escape(task_id)}">
        {filter_fields}
        <input type="hidden" name="force" value="1">
        <button type="submit">🚀 Vẫn đăng ngay</button>
      </form>
    </div>
  </div>
</div>"""


@router.post("/schedule/missed/fire-now")
async def schedule_missed_fire_now(request: Request, _: None = Depends(_require_login)):
    """"🚀 Đăng ngay" directly on a MISSED_DIR item (owner request
    2026-09-25) — post it right now without first going through "📅 Đặt
    lịch"/"🔄 Lên lịch lại" to move it back to pending/ first. Exactly the
    same two-layer check as schedule_fire_now() above, just sourced from
    get_missed() instead of get(): a hard per-day/per-hour count cap
    ("đủ slot hôm nay không") is never overridable and blocks outright
    with a plain error; the soft min-gap pacing check offers the same
    "Vẫn đăng ngay" confirmation modal. See daily_limits.can_proceed()'s
    module docstring for why the two are treated differently — reusing
    that exact function is what makes the slot check here automatically
    agree with every other place capacity is enforced (data_sync.py's
    fire_due_tasks() pre-check, schedule_fire_now() above), rather than a
    second, possibly-drifting copy of the same rule."""
    form = await request.form()
    account_id, page, page_size, missed_page, _action_filter, _date_filter, _tz_offset, missed_min_days = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    force = str(form.get("force", "")) == "1"
    task = schedule_store.get_missed(task_id)
    if task is None:
        err = "Không tìm thấy mục này (có thể đã được xử lý ở tab khác)"
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=err) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=err)

    from human_bot import daily_limits
    from human_bot.agent import rate_limit_bucket_for
    from human_bot.safety import is_gap_reason, rate_limit_wait_message
    account = get_all_accounts().get(task.account_id)
    bucket = rate_limit_bucket_for(task.action)
    if account and bucket:
        # ignore_gap=force (NOT skipping this whole can_proceed() call when
        # force is set) — 2026-09-25, caught live while testing this route:
        # can_proceed(account, bucket, ignore_gap=True) only ever skips its
        # OWN internal soft min-gap check, the hard posts_per_day/
        # comments_per_day/etc. count cap below it always still runs
        # regardless of ignore_gap (see that function's own body). Calling
        # it unconditionally like this is what guarantees the hard cap
        # ("đủ slot hôm nay không") is checked on EVERY submit, including a
        # forced retry sent straight from "Vẫn đăng ngay" — a state change
        # between the first check and that resubmit (a slot filling up
        # in between) must still be caught, not just skipped past because
        # `force=1` was set on the form.
        allowed, reason = daily_limits.can_proceed(account, bucket, ignore_gap=force)
        if not allowed and not force and is_gap_reason(reason):
            warning = rate_limit_wait_message(account, bucket) or reason
            if _is_htmx(request):
                modal_oob = f'<div id="modal-root" hx-swap-oob="true">{_missed_fire_now_confirm_modal_html(task_id, account_id, page, page_size, missed_page, missed_min_days, warning)}</div>'
                return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days) + modal_oob)
            return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=warning)
        if not allowed:
            # Hard count cap — "không đủ slot hôm nay", never overridable
            # even by `force` — no modal, just a flat refusal, task stays
            # in missed/ exactly where it was.
            warning = daily_limits.hard_cap_message(account, bucket) or reason
            if _is_htmx(request):
                return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=warning) + _MODAL_CLOSE_OOB)
            return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=warning)

    result = await run_task(TaskRequest(
        action=task.action,
        account_id=task.account_id,
        target_url=task.target_url,
        content=task.content,
        media_path=task.media_path,
        audience=task.audience,
        reasoning=task.reasoning,
        source="schedule_missed_manual",
        scheduled_task_id=task.task_id,
        retries=task.retries,
        source_kind=task.source_kind,
        source_id=task.source_id,
        job_data=task.job_data or task.candidate_data,
        retry_of_log_id=task.retry_of_log_id,
        force_ignore_gap=force,
    ))
    if result.success:
        schedule_store.mark_posted(task_id, result.message, source_dir=schedule_store.MISSED_DIR)
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=True) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, saved=1)
    if db.is_rate_limited(result.message):
        # Race condition only (we already checked can_proceed() above) —
        # e.g. another admin/action fired in between. Leave the task in
        # missed/ untouched (schedule_store.update() only knows how to
        # edit a PENDING task) and just surface the message; admin can
        # click again.
        warning = None
        if account and bucket:
            warning = rate_limit_wait_message(account, bucket) or daily_limits.hard_cap_message(account, bucket)
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=warning or result.message) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=warning or result.message)
    schedule_store.mark_failed(task_id, result.message, source_dir=schedule_store.MISSED_DIR)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=f"Đăng thất bại: {result.message}") + _MODAL_CLOSE_OOB)
    return _schedule_redirect(account_id, page, page_size=page_size, tab="missed", missed_page=missed_page, missed_min_days=missed_min_days, error=f"Đăng thất bại: {result.message}")


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


def _ago_vi(iso: str | None, now: datetime | None = None) -> str:
    """"vừa xong" / "5 phút trước" / "3 giờ trước" for the last 24 hours; after that by CALENDAR day in Japan (the
    business timezone, like the Telegram bot): "hôm qua" / "6 ngày trước". A timestamp without an offset is UTC."""
    if not iso:
        return ""
    try:
        then = datetime.fromisoformat(iso.replace("Z", "+00:00"))
    except ValueError:
        return ""
    if then.tzinfo is None:
        then = then.replace(tzinfo=timezone.utc)
    now = now or datetime.now(timezone.utc)
    seconds = (now - then).total_seconds()
    if seconds < 60:
        return "vừa xong"
    if seconds < 3600:
        return f"{int(seconds // 60)} phút trước"
    if seconds < 86400:
        return f"{int(seconds // 3600)} giờ trước"
    days = ((now + timedelta(hours=9)).date() - (then + timedelta(hours=9)).date()).days
    return "hôm qua" if days <= 1 else f"{days} ngày trước"


def _group_key(url: str) -> str:
    """What identifies a group in a URL: its numeric id or vanity slug (a slug is case-insensitive on Facebook), else the URL."""
    from human_bot.actions import _group_id_from_url
    return (_group_id_from_url(url) or url).casefold()


def _fold_vi(text: str) -> str:
    """Lower-case with the Vietnamese tone marks and the đ stripped: "Việc làm" -> "viec lam" (what the search box matches on,
    so "viec lam" finds it; the page script folds what is typed the same way)."""
    import unicodedata
    decomposed = unicodedata.normalize("NFD", text.casefold().replace("đ", "d"))
    return "".join(c for c in decomposed if not unicodedata.combining(c))


def _group_stats_text(stats: dict | None, now: datetime | None = None) -> str:
    """"Đã đăng 7 bài · gần nhất 3 ngày trước · 2 lần lỗi" for one group, or "chưa đăng lần nào"."""
    if not stats or not (stats["ok"] or stats["failed"]):
        return "chưa đăng lần nào"
    parts = [f"Đã đăng {stats['ok']} bài" if stats["ok"] else "Chưa đăng được bài nào"]
    ago = _ago_vi(stats["last_ok"], now) if stats["last_ok"] else ""
    if ago:                                                                      # (unreadable timestamp -> no dangling "gần nhất")
        parts.append(f"gần nhất {ago}")
    if stats["failed"]:
        parts.append(f"{stats['failed']} lần lỗi")
    return " · ".join(parts)


def _groups_content_html(
    account_id: str | None, saved: bool = False, error: str | None = None, oob: bool = False
) -> str:
    from human_bot.actions import _group_id_from_url

    accounts = get_all_accounts()
    account_ids = list(accounts)
    if not account_ids:
        return '<div id="groups-content"><div class="empty-state">Chưa có tài khoản nào — đăng ký ở <a href="/admin/accounts">Tài khoản</a> trước.</div></div>'
    if account_id not in accounts:
        account_id = account_ids[0]
    account = accounts[account_id]
    groups = get_joined_groups(account_id)

    flash = '<p class="flash">✅ Đã lưu.</p>' if saved else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""

    account_options = "".join(
        f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(_account_label(aid, accounts))}</option>'
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
        # What each group got so far, matched by the group's id/slug (the log may hold either URL form of it).
        activity: dict[str, dict] = {}
        try:
            activity_rows = db.group_activity(account_id)
        except Exception:  # noqa: BLE001 — a statistic is never worth failing the page (a locked / unreadable log)
            logger.exception("groups: could not read the action log")
            activity_rows = []
        for r in activity_rows:
            key = _group_key(r["target_url"])
            entry = activity.setdefault(key, {"ok": 0, "failed": 0, "last_ok": None})
            entry["ok"] += r["ok"] or 0
            entry["failed"] += r["failed"] or 0
            if r["last_ok"] and (entry["last_ok"] is None or r["last_ok"] > entry["last_ok"]):
                entry["last_ok"] = r["last_ok"]
        now = datetime.now(timezone.utc)
        rows = []
        for g in groups:
            esc_id, esc_account = html.escape(g.id), html.escape(account_id)
            url_e = html.escape(g.url)
            group_key = _group_id_from_url(g.url)
            name_html = html.escape(g.name) if g.name else "(chưa đặt tên)"
            muted = "" if g.name else " muted"
            vanity = (
                ' <span class="grp-flag" title="URL dạng tên tuỳ chỉnh. Dạng ID số (…/groups/1234567) bền hơn: tên có thể bị admin nhóm đổi.">tên tuỳ chỉnh</span>'
                if group_key and not group_key.isdigit() else ""
            )
            stats = _group_stats_text(activity.get(_group_key(g.url)), now)
            menu = _row_menu_html([
                _copy_url_button(g.url),
                '<hr class="row-menu-sep">',
                _menu_form(
                    "/admin/groups/delete", {"account_id": account_id, "group_id": g.id}, "🗑 Xoá khỏi danh sách",
                    "Bot sẽ không chọn nhóm này nữa", target="#groups-content", danger=True,
                    confirm=f"Xoá nhóm {html.escape(g.name or g.url)} khỏi danh sách?",
                ),
            ])
            search = html.escape(_fold_vi(f"{g.name} {g.url}"), quote=True)
            rows.append(f"""
<div class="sched-item" data-filter-row data-search="{search}">
  <div class="grp-line">
    <div class="grp-main">
      <div class="sched-title"><a class="sched-target{muted}" href="{url_e}" target="_blank" rel="noopener" title="Mở nhóm trên Facebook">{name_html}</a>{vanity}</div>
      <div class="grp-url">{url_e}</div>
      <div class="grp-stats">{html.escape(stats)}</div>
    </div>
    <div class="sched-actions">
      <button type="button" class="btn-small btn-secondary"
              hx-get="/admin/groups/edit-modal?account_id={esc_account}&group_id={esc_id}"
              hx-target="#modal-root" hx-swap="innerHTML">✎ Sửa</button>
      {menu}
    </div>
  </div>
</div>""")
        search_html = (
            '<div class="grp-search"><input type="search" placeholder="Tìm nhóm theo tên hoặc URL…" data-list-filter aria-label="Tìm nhóm">'
            '<span class="muted" data-list-filter-count></span></div>'
            if len(groups) > 8 else ""
        )
        table_html = f"""
<div class="card">
  <h2>👥 Nhóm của {html.escape(account.display_name)}</h2>
  {search_html}
  <div class="sched-list">{''.join(rows)}</div>
  <div class="empty-state" data-list-filter-empty hidden>Không có nhóm nào khớp.</div>
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
    _: None = Depends(_require_login),
) -> str:
    content = _groups_content_html(account_id, saved, error)
    if _is_htmx(request):
        return content
    return _layout(f"""
<h1>Nhóm đã tham gia</h1>
<p class="page-desc">Các nhóm Facebook mỗi tài khoản đã tham gia — bot chọn nhóm để đăng từ danh sách này. Lưu xong là dùng ngay. Nên dán URL dạng ID số (…/groups/1234567) thay vì tên tuỳ chỉnh để bot tìm đúng nhóm.</p>
{content}
""", active="groups", current_user=_build_current_user(request))


@router.get("/groups/add-modal", response_class=HTMLResponse)
async def groups_add_modal(account_id: str | None = None, _: None = Depends(_require_login)) -> str:
    accounts = get_all_accounts()
    account_ids = list(accounts)
    if account_id not in accounts:
        account_id = account_ids[0] if account_ids else ""
    return _group_modal_html("add", account_id)


def _find_group(groups: list[GroupRef], group_id: str) -> GroupRef | None:
    return next((g for g in groups if g.id == group_id), None)


@router.get("/groups/edit-modal", response_class=HTMLResponse)
async def groups_edit_modal(account_id: str, group_id: str, _: None = Depends(_require_login)) -> str:
    g = _find_group(get_joined_groups(account_id), group_id)
    if g is None:
        return _group_modal_html("edit", account_id, group_id=group_id, error="Mục không còn tồn tại — có thể đã bị xoá.")
    return _group_modal_html("edit", account_id, group_id=group_id, name=g.name, url=g.url)


@router.post("/groups/add")
async def groups_add(request: Request, _: None = Depends(_require_login)):
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
async def groups_update(request: Request, _: None = Depends(_require_login)):
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
async def groups_delete(request: Request, _: None = Depends(_require_login)):
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
    "manual": "Đăng tay",
    "queue": "Từ hàng đợi",
    "schedule_manual": "Đăng ngay từ Lịch đăng",
    "schedule_missed_manual": "Đăng ngay từ mục Quá hạn",
    "schedule_auto": "Tự động",
    "api": "Gọi API (n8n)",
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
    "": "Tất cả dữ liệu đang lưu",
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
_REPORTS_TABS = ("tables", "jobs", "candidates", "recent", "failures", "settings")
_REPORTS_TAB_LABELS = {
    "tables": "📊 Tổng quan",
    "jobs": "📮 Bài đăng",
    "candidates": "💬 Bình luận",
    "recent": "🕒 Hoạt động",
    "failures": "⚠️ Lỗi",
    "settings": "⚙️ Thời hạn lưu",
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


_RESCHEDULE_SEARCH_DAYS = 30


def _suggest_reschedule_at(account, action: str, exclude_task_id: str | None = None) -> datetime:
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
      2. Gap check — floored by RateLimiter.next_allowed_at() (last
         REAL action), and kept at least this account's min_delay_seconds
         for this bucket away from EVERY pending task, before and after
         (2026-10-09; it used to only look after the LATEST pending
         task, so it never found a free slot earlier in the day — owner
         saw "Lên lịch lại" suggest tomorrow with hours free today). So
         the earliest hole that fits is used, and 2 reschedules in a row
         still can't land back-to-back.

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
    is just what the admin sees before clicking "Xác nhận".

    `exclude_task_id` (2026-09-29, "↩️ Mượn giờ" — /admin/schedule's
    missed-task borrow-a-pending-slot flow): when suggesting a NEW slot
    for a task that is ITSELF still sitting in pending/ at its old time
    (the displaced task, whose slot is about to be handed to a missed
    task), that old slot must not count against the search below — it's
    the account's own leftover capacity, not real competition. Without
    this, the gap floor and day-cap count would both see the task's own
    still-there old entry and could refuse to land on a slot the account
    actually has room for, once that task ITSELF vacates it. None
    (default) for every other caller — a reschedule from action_log has
    no matching pending row to exclude."""
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
            and p.task_id != exclude_task_id
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

    cfg = get_data_sync_config()
    candidate = now
    # 30 real days of search depth (project owner's call 2026-09-15 —
    # 30 consecutive fully-capped business days is already a config
    # problem worth surfacing, not something to keep searching past),
    # at up to 3 iterations/day per this function's own docstring above.
    # + len(pending_times): the gap-conflict jump below can cost one
    # iteration per pending task it has to hop over.
    for _ in range(_RESCHEDULE_SEARCH_DAYS * 3 + len(pending_times) + 5):
        moved = False

        if floors:
            raised = max(candidate, *floors)
            if raised != candidate:
                candidate, moved = raised, True

        clamped = apply_quiet_hours(candidate, cfg)
        if clamped != candidate:
            candidate, moved = clamped, True

        # Gap vs EVERY pending task, on both sides (2026-10-09): a task
        # before `candidate` needs `gap` of rest first, one after it
        # needs `gap` of rest following `candidate`. Replaces the old
        # single floor "latest pending + gap", which could only ever
        # append to the end of the queue and never saw free slots earlier
        # in the day. Forward-only jump past the latest conflicting
        # task, so it always converges.
        conflicts = [
            t for t in pending_times
            if abs((candidate - t).total_seconds()) < gap_seconds
        ]
        if conflicts:
            candidate, moved = max(conflicts) + timedelta(seconds=gap_seconds), True

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


def _already_posted_error(row) -> str | None:
    """A message when this failed row's post has meanwhile gone out by another route (a Telegram retry, the scheduler,
    a re-draft...): reposting it would post it twice. Checked again on the server — a page left open can be stale."""
    done = db.success_logged_after(
        row["account_id"], row["target_url"], row["content"], row["created_at"],
        source_id=row["source_id"], source_kind=row["source_kind"],
    )
    if done is None:
        return None
    return f"Bài này đã được đăng thành công lúc {_fmt_jst(done['created_at'])} (giờ Nhật) — không đăng lại để khỏi trùng."


def _failure_caution(row) -> tuple[str, str]:
    """(banner HTML, confirm question) for the retry dialogs of a failed row: what failure_info knows BEFORE anything is
    posted again. A failure that may already be live on Facebook, or one a retry cannot fix, says so and asks first
    ("" , "" for a safe failure or a rate-limit deferral, which attempted nothing)."""
    if db.is_rate_limited(row["message"]):
        return "", ""
    info = failure_info.classify(row["message"])
    if info.safety == failure_info.UNCERTAIN:
        return (
            '<div class="warning">⚠️ Lần này <b>chưa rõ bài đã lên Facebook chưa</b> — hãy xem trên Facebook trước. '
            'Đăng lại có thể thành bài trùng.</div>',
            "Bài này có thể đã lên Facebook rồi. Vẫn tiếp tục?",
        )
    if info.safety == failure_info.NO_RETRY:
        return (
            f'<div class="error">⛔ {html.escape(info.cause)} — cần xử lý nguyên nhân trước, đăng lại nhiều khả năng sẽ lỗi tiếp.</div>',
            "Lỗi này cần xử lý nguyên nhân trước. Vẫn tiếp tục?",
        )
    return "", ""


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
    caution, confirm = _failure_caution(row)
    confirm_attr = f' hx-confirm="{html.escape(confirm)}"' if confirm else ""
    return f"""
<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">
  <div class="modal-box">
    <div class="modal-header">
      <h2>↻ Đăng lại {label}</h2>
      <button type="button" class="modal-close" onclick="this.closest('.modal-backdrop').remove()">✕</button>
    </div>
    <p class="muted">Bản ghi này đã thất bại — chọn cách xử lý:</p>
    {caution}
    <ul style="font-size:13px; color:#6b7280; margin:0 0 16px; padding-left:18px; line-height:1.7;">
      <li><b>Đăng ngay</b> — thử lại ngay bây giờ, vẫn kiểm tra đủ giới hạn số lượng/ngày và /giờ như bình thường.</li>
      <li><b>Đặt lịch</b> — mở trang soạn bài với nội dung điền sẵn, bạn tự chọn ngày giờ.</li>
      <li><b>Lên lịch lại</b> — hệ thống tự tìm giờ trống gần nhất còn đủ hạn mức, bạn xác nhận trước khi thêm vào lịch.</li>
    </ul>
    <div style="display:flex; flex-direction:column; gap:8px;">
      <form method="post" action="/admin/reports/repost" hx-post="/admin/reports/repost" hx-target="#reports-content" hx-swap="outerHTML"{confirm_attr}>
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



def _salary_text(salary) -> str:
    """{'min': 220000, 'max': 280000, 'currency': 'JPY', 'period': 'month'} -> "22–28 man / tháng": the same rules the
    posts use (content_strategist._salary_line — currency defaults to JPY, a 0 is "missing", month/year pay is shown in
    man, an hourly wage in plain yên). Anything that is not that shape — or that cannot be read as one — is shown as
    "k: v" pairs instead, never dropped and never an error (this runs for every row of a report page)."""
    if not isinstance(salary, dict):
        return _format_attr(salary)
    try:
        lo, hi = salary.get("min"), salary.get("max")
        if not lo and not hi:
            return _pairs_text(salary)
        currency, period = salary.get("currency") or "JPY", salary.get("period") or ""
        if not isinstance(currency, str) or not isinstance(period, str):
            raise ValueError("currency/period must be text")
        currency = currency.upper()
        in_man = currency == "JPY" and period in content_strategist.MAN_PERIOD_KEYS

        def amount(value) -> str:
            if not value:
                return ""
            n = float(value)
            if n != n or n in (float("inf"), float("-inf")):
                raise ValueError(value)
            if in_man:
                return content_strategist._format_man(n)
            return _vn_int(int(n)) if n == int(n) else str(n)

        lo_s, hi_s = amount(lo), amount(hi)
        text = f"{lo_s}–{hi_s}" if lo_s and hi_s and lo_s != hi_s else (lo_s or hi_s)
        unit = "man" if in_man else ("yên" if currency == "JPY" else currency)
        period_label = content_strategist._SALARY_PERIOD_LABELS.get(period, period)
        return f"{text} {unit}" + (f" / {period_label}" if period_label else "")
    except (TypeError, ValueError, OverflowError):
        return _pairs_text(salary)


def _pairs_text(value: dict) -> str:
    """A dict as "k: v, k: v" (non-empty values only) — never Python's repr."""
    return ", ".join(f"{k}: {_format_attr(v)}" for k, v in value.items() if v not in (None, "") and _format_attr(v))


def _attr_text(key: str, value) -> str:
    """One side-B attribute as readable text: the salary as "22–28 man / tháng", a list joined with commas,
    any other nested dict as "k: v" pairs (never Python's repr)."""
    if key == "salary":
        return _salary_text(value)
    if isinstance(value, dict):
        return _pairs_text(value)
    return _format_attr(value)


def _attr_parts(title, attrs) -> list[str]:
    """Every non-empty key in `attrs` (plus `title` if given) as one "Nhãn: giá trị" HTML fragment each — dynamic,
    not a fixed allowlist, so a field side B adds later (or one this project just hasn't named yet) still shows up,
    using its own key name as the label until _ATTR_LABELS above is taught a nicer one. `confidence` (a 0-1 ML score)
    is formatted as a percentage; the salary is spelled out (_salary_text). `attrs` that is not a dict is ignored."""
    parts = []
    if title:
        parts.append(f"<b>{html.escape('Tiêu đề')}:</b> {html.escape(_format_attr(title))}")
    for key, value in (attrs.items() if isinstance(attrs, dict) else ()):
        if not value and value != 0:
            continue
        if key == "confidence":
            try:
                value = f"{float(value) * 100:.0f}%"
            except (TypeError, ValueError):
                pass
        text = _attr_text(key, value)
        if text:
            parts.append(f"<b>{html.escape(_ATTR_LABELS.get(key, key))}:</b> {html.escape(text)}")
    return parts


def _attrs_summary_html(title, attrs) -> str:
    parts = _attr_parts(title, attrs)
    return " &nbsp;·&nbsp; ".join(parts) if parts else '<span class="muted">—</span>'


def _week_range_label(week: str, today) -> tuple[str, bool]:
    """db.weekly_post_counts()'s week key — the Monday's date, "2026-10-26" — -> ("26/10 – 01/11", is_this_week)."""
    try:
        monday = datetime.strptime(week, "%Y-%m-%d").date()
    except ValueError:
        return week, False
    sunday = monday + timedelta(days=6)
    return f"{monday:%d/%m} – {sunday:%d/%m}", monday <= today <= sunday


def _bar_html(value: int, maximum: int) -> str:
    """A bar with its value at the tip. One colour (the page accent), 4px rounded data end, square at the baseline;
    the width is a share of the largest value, leaving room at the end for the number."""
    ratio = (value / maximum) if maximum else 0
    return (
        f'<div class="bar-track"><span class="bar-fill" style="--w:{ratio:.4f}"></span>'
        f'<span class="bar-val">{value}</span></div>'
    )


def _bar_row_html(label_html: str, value: int, maximum: int, *, sub_html: str = "") -> str:
    sub = f'<span class="bar-sub">{sub_html}</span>' if sub_html else ""
    return f'<div class="bar-row"><div class="bar-label">{label_html}{sub}</div>{_bar_html(value, maximum)}</div>'


def _split_bar_html(ok: int, bad: int) -> str:
    """Share of successes vs failures in one bar (two fills, a 2px surface gap between them)."""
    total = ok + bad
    if not total:
        return '<div class="split-bar"></div>'
    parts = []
    if ok:
        parts.append(f'<span class="split-ok" style="flex:{ok}"></span>')
    if bad:
        parts.append(f'<span class="split-bad" style="flex:{bad}"></span>')
    return f'<div class="split-bar">{"".join(parts)}</div>'


def _failure_note_html(message: str | None, *, with_hint: bool = True) -> str:
    """Why a row failed, in words: failure_info's cause + whether the post may already be live, with the raw error
    one click away (it is a Playwright dump, not something to read first). `with_hint=False` leaves the "can I retry"
    line out (the row was posted by something else since)."""
    msg = message or ""
    if db.is_rate_limited(msg):
        # the reason after the prefix is a gap, or an hourly / daily cap: the raw text (one click away) says which
        cause, hint = "Chưa chạy: bị giới hạn tốc độ của tài khoản (khoảng cách giữa hai lần, hoặc hạn mức giờ/ngày)", ""
    else:
        info = failure_info.classify(msg)
        cause, hint = info.cause, failure_info.hint(info) if with_hint else ""
    tech = f'<details class="rep-tech"><summary>Chi tiết kỹ thuật</summary><pre>{html.escape(msg)}</pre></details>' if msg else ""
    hint_html = f' <span class="rep-hint">· {html.escape(hint)}</span>' if hint else ""
    return f'<div class="rep-note">{html.escape(cause)}{hint_html}{tech}</div>'


def _log_target_html(r, name_lookup) -> str:
    """Where an action_log row went (_target_link_html's naming; the recorded group name wins over the saved list's)."""
    url = r["target_url"]
    if not url:
        return '<span class="sched-target">Tường cá nhân</span>' if r["action"] == "post_to_own_profile" else '<span class="muted">—</span>'
    return _target_link_html(r["action"], url, r["target_group_name"] or name_lookup(r["account_id"], url))


def _reports_content_html(
    account_id: str | None = None, days: str | None = None, page: int = 1,
    page_size: int = _REPORTS_RECENT_PAGE_SIZE, job_page: int = 1, candidate_page: int = 1,
    tab: str | None = None,
    posted: str | None = None, error: str | None = None, warning: str | None = None,
) -> str:
    from urllib.parse import urlencode

    page_size = _clamp_reports_page_size(page_size)
    tab = _clamp_reports_tab(tab)
    accounts = get_all_accounts()
    since = _reports_since(days)
    name_lookup = _group_name_lookup()
    flash = f'<p class="flash">✅ {html.escape(posted)}</p>' if posted else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    # Separate from `error` (2026-09-11, owner request): "Đăng lại" hitting
    # the account's own rate-limit gap isn't a real failure — the repost
    # just fired too soon, exactly like /admin/schedule's "Đăng ngay" hitting
    # the same gap (see reports_repost() below) — so it gets the neutral
    # `.warning` style (amber) instead of `.error` (red), same distinction
    # schedule_fire_now() already makes with rate_limit_wait_message().
    warn = f'<p class="warning">⏳ {html.escape(warning)}</p>' if warning else ""

    # The list tabs ("Hoạt động" = everything, "Lỗi" = only what failed) share the page-size select and the pager.
    list_tab = tab if tab in ("recent", "failures") else "recent"

    account_options = '<option value="">— Tất cả tài khoản —</option>' + "".join(
        f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(_account_label(aid, accounts))}</option>'
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
    # The page-size <select> itself renders inside the list card's own
    # header row, next to that card's title (owner request 2026-09-11,
    # twice: first moved out of the page-wide account/days filter row since
    # it only affects this one card, then out of the card's footer too —
    # "xấu quá" — up next to the title instead) — but its markup and
    # hx-include wiring live together right here since both selects need
    # each other's id, and this is where account_options/days_options are
    # already in scope. #reports-pagesize-select still gets found by
    # hx-include regardless of where in the DOM it ends up.
    page_size_select_html = f"""<label for="reports-pagesize-select" class="muted">Hiển thị</label>
  <select name="page_size" id="reports-pagesize-select"
          hx-get="/admin/reports" hx-target="#reports-content" hx-swap="outerHTML"
          hx-trigger="change" hx-include="#reports-account-select, #reports-days-select"
          hx-vals='{{"tab": "{list_tab}"}}' hx-push-url="true">{page_size_options}</select>"""
    # The 2 page-wide selects include the page-size one via hx-include so
    # switching account/days never silently resets it back to default.
    # hx-vals carries the currently active tab through (2026-09-12) — these
    # selects render above every tab, so without it, changing the account/
    # days filter would silently snap back to the default tab.
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

    # --- KPI summary — glance-and-go health check before the detail tabs. The "Cấu hình" tab is global
    # settings, not report data: the filters and the numbers (both scoped to those filters) would only confuse
    # there, so it skips them and every query below.
    stats = db.summary_stats(account_id=account_id, since=since)
    failed_count = stats["failed"]

    def _tab_qs(tab_key: str) -> str:
        return urlencode({k: v for k, v in {
            "account_id": account_id, "days": days, "tab": tab_key,
            "page_size": page_size if page_size != _REPORTS_RECENT_PAGE_SIZE else None,
        }.items() if v})

    def _reports_tab_link(tab_key: str) -> str:
        qs = _tab_qs(tab_key)
        label = _REPORTS_TAB_LABELS[tab_key]
        if tab_key == "failures" and failed_count:
            label += f' <span class="badge badge-bad">{failed_count}</span>'
        return (
            f'<a href="/admin/reports?{qs}" hx-get="/admin/reports?{qs}" hx-target="#reports-content" hx-swap="outerHTML" '
            f'hx-push-url="true" class="sched-tab{" active" if tab_key == tab else ""}">{label}</a>'
        )

    tab_nav_html = f'<div class="sched-tabs">{"".join(_reports_tab_link(k) for k in _REPORTS_TABS)}</div>'

    if tab == "settings":
        return f"""<div id="reports-content">
{flash}
{err}
{warn}
{tab_nav_html}
{_retention_settings_card_html()}
</div>"""

    rate_display = f"{stats['success_rate']}%" if stats["success_rate"] is not None else "—"
    period_label = _REPORTS_DAYS_LABELS.get(days or "", "")
    failed_tile = _stat_tile(
        "Thất bại", f'<span class="bad">{stats["failed"]}</span>' if stats["failed"] else "0",
        f"/admin/reports?{_tab_qs('failures')}", sub="xem các lần lỗi →" if stats["failed"] else "không có lỗi",
        attention=bool(stats["failed"]),
    )
    summary_html = '<div class="stat-row">' + "".join([
        _stat_tile("Tổng số lần chạy", str(stats["total"]), None, sub=html.escape(period_label)),
        _stat_tile("Thành công", f'<span class="ok">{stats["succeeded"]}</span>', None),
        failed_tile,
        _stat_tile("Tỉ lệ thành công", rate_display, None),
        _stat_tile("Tài khoản có hoạt động", str(stats["active_accounts"]), None),
    ]) + "</div>"

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

    def _handled_status(rows) -> dict[int, str]:
        """For the failed, repostable rows among `rows`: "retried" (a retry of it succeeded) or "later" (the same post
        went out afterwards by some other route) — either way "Đăng lại" would post it twice."""
        eligible = [r for r in rows if r["action"] in _REPOSTABLE_ACTIONS and not r["success"] and (r["content"] or "").strip()]
        status = {i: "retried" for i in db.successful_retry_log_ids([r["id"] for r in eligible])}
        rest = [r for r in eligible if r["id"] not in status]
        status.update({i: "later" for i in db.failed_rows_posted_later(rest)})
        return status

    def _repost_action_cell_html(r: sqlite3.Row, handled: dict[int, str]) -> str:
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
        if handled.get(r["id"]) == "retried":
            return '<span class="muted" style="font-size:12px; white-space:nowrap;">✅ Đã đăng lại</span>'
        if handled.get(r["id"]) == "later":
            return '<span class="muted" style="font-size:12px; white-space:nowrap;">✅ Đã đăng thành công sau đó</span>'
        return _repost_choice_button_html(
            r, account_id=account_id, days=days, page=page, page_size=page_size,
            job_page=job_page, candidate_page=candidate_page, tab=tab,
        )

    def _row_html(r: sqlite3.Row, handled: dict[int, str], *, show_account: bool = True, show_action: bool = True,
                  show_source: bool = False, extra_html: str = "") -> str:
        """One attempt as a row (the same look as the /admin/schedule list): when · outcome + what + where · the text
        that went out · why it failed in words · screenshot / retry. Shared by "Hoạt động", "Lỗi", "Bài đăng", "Bình luận"."""
        msg = r["message"] or ""
        rate_limited = db.is_rate_limited(msg)
        if r["success"]:
            state, chip = "rep-ok", '<span class="rep-tick" title="Thành công">✅</span>'      # most rows succeed: a tick, not a badge
        elif rate_limited:
            state, chip = "rep-wait", '<span class="badge badge-warn">⏳ Chưa chạy</span>'
        else:
            state, chip = "rep-bad", '<span class="badge badge-bad">⚠️ Thất bại</span>'
        title = [chip]
        if show_action:
            title.append(_action_badge_html(r["action"]))
        title.append(_log_target_html(r, name_lookup))
        if show_account:
            title.append(f'<span class="sched-acct">{html.escape(_account_label(r["account_id"], accounts))}</span>')
        if show_source:
            title.append(f'<span class="sched-acct">· {html.escape(_SOURCE_LABELS.get(r["source"], r["source"]))}</span>')
        if r["success"]:
            note = f'<div class="rep-note rep-note-ok">{_expandable_text(msg, 60)}</div>' if msg.strip() and msg.strip().lower() != "ok" else ""
        else:
            note = _failure_note_html(msg, with_hint=handled.get(r["id"]) != "later")
        shot_path = r["screenshot_path"] if "screenshot_path" in r.keys() else None
        shot = _screenshot_link_html(shot_path) if shot_path else ""
        content = f'<div class="rep-content">{_expandable_text(r["content"], 110)}</div>' if (r["content"] or "").strip() else ""
        return f"""<div class="sched-item {state}">
  <div class="rep-line">
    <div class="rep-time">{_local_dt_html(r['created_at'])}</div>
    <div class="rep-main">
      <div class="sched-title">{"".join(title)}</div>
      {extra_html}{content}{note}
    </div>
    <div class="sched-actions">{shot}{_repost_action_cell_html(r, handled)}</div>
  </div>
</div>"""

    def _pager_link(target_page: int, label: str, enabled: bool, *, page_key: str, tab_key: str) -> str:
        if not enabled:
            return f'<span class="btn-secondary btn-small" style="opacity:.45; pointer-events:none;">{label}</span>'
        qs = urlencode({k: v for k, v in {
            "account_id": account_id, "days": days, "tab": tab_key,
            "page_size": page_size if page_size != _REPORTS_RECENT_PAGE_SIZE else None,
            page_key: target_page if (target_page != 1 or page_key == "page") else None,
        }.items() if v})
        return (
            f'<a class="btn-secondary btn-small" href="/admin/reports?{qs}" '
            f'hx-get="/admin/reports?{qs}" hx-target="#reports-content" hx-swap="outerHTML" hx-push-url="true">{label}</a>'
        )

    def _simple_pager_html(current: int, total_pages: int, total: int, noun: str, *, page_key: str, tab_key: str) -> str:
        if total_pages <= 1:
            return ""
        return f"""
<div class="rep-pager">
  {_pager_link(current - 1, "← Trang trước", current > 1, page_key=page_key, tab_key=tab_key)}
  <span class="muted">Trang {current} / {total_pages} — {total} {noun}</span>
  {_pager_link(current + 1, "Trang sau →", current < total_pages, page_key=page_key, tab_key=tab_key)}
</div>"""

    tab_content_html = ""

    # ------------------------------------------------------------------ "Tổng quan"
    if tab == "tables":
        today_jst = (datetime.now(timezone.utc) + timedelta(hours=9)).date()      # the weeks are Japan's (see db.weekly_post_counts)

        # Weekly: one row per week, a column per account, the total as a bar. (The old table repeated the week on
        # every account's row and wrote it as "2026-W43".)
        weekly_rows = db.weekly_post_counts(account_id=account_id, since=since)
        if weekly_rows:
            per_week: dict[str, dict[str, int]] = {}
            account_totals: dict[str, int] = {}
            for r in weekly_rows:
                per_week.setdefault(r["week"], {})[r["account_id"]] = r["total"]
                account_totals[r["account_id"]] = account_totals.get(r["account_id"], 0) + r["total"]
            columns = sorted(account_totals, key=lambda a: -account_totals[a]) if len(account_totals) > 1 else []
            biggest = max(sum(v.values()) for v in per_week.values())
            head = "<th>Tuần</th>" + "".join(f'<th class="num">{html.escape(_account_label(a, accounts))}</th>' for a in columns) + "<th>Tổng số bài</th>"
            body = ""
            for week, by_account in per_week.items():
                label, this_week = _week_range_label(week, today_jst)
                cells = "".join(f'<td class="num">{by_account.get(a) or "—"}</td>' for a in columns)
                now_tag = '<div class="muted">đang diễn ra</div>' if this_week else ""
                # on a phone the per-account columns fold into a line under the bar (a 4-column table would scroll sideways)
                split = " · ".join(f"{html.escape(_account_label(a, accounts))} {by_account[a]}" for a in columns if by_account.get(a))
                split_html = f'<div class="wk-split">{split}</div>' if split else ""
                body += f'<tr><td class="nowrap"><b>{html.escape(label)}</b>{now_tag}</td>{cells}<td class="bar-cell">{_bar_html(sum(by_account.values()), biggest)}{split_html}</td></tr>'
            weekly_card = f"""
<div class="card">
  <h2>📅 Bài đăng thành công theo tuần</h2>
  <p class="hint" style="margin-top:-8px;">Tuần tính từ thứ Hai đến Chủ nhật, theo giờ Nhật.</p>
  <div class="table-scroll"><table class="data-table rep-weekly">
    <thead><tr>{head}</tr></thead>
    <tbody>{body}</tbody>
  </table></div>
</div>"""
        else:
            weekly_card = '<div class="card"><h2>📅 Bài đăng thành công theo tuần</h2><div class="empty-state">Chưa có bài đăng thành công nào được ghi nhận.</div></div>'

        # Why things failed (failure_info turns the raw errors into causes) — the first thing to read when the
        # "Thất bại" number above is not zero.
        causes_card = ""
        if stats["failed"]:                                                                     # (an empty ranking still renders, just bare)
            counts: dict[str, list] = {}
            for message, n in db.failure_message_counts(account_id=account_id, since=since):
                info = failure_info.classify(message)
                entry = counts.setdefault(info.code, [info, 0])
                entry[1] += n
            ranked = sorted(counts.values(), key=lambda e: -e[1])
            counted = sum(n for _info, n in ranked)
            top = ranked[0][1] if ranked else 0
            cause_rows = "".join(
                _bar_row_html(html.escape(info.cause), n, top, sub_html=html.escape(failure_info.hint(info)))
                for info, n in ranked
            )
            sample_note = (
                f'<p class="hint">Chỉ phân loại được {counted} trong tổng số {stats["failed"]} lần lỗi.</p>' if counted < stats["failed"] else ""
            )
            causes_card = f"""
<div class="card">
  <h2>⚠️ Lỗi theo nguyên nhân</h2>
  <div class="bars">{cause_rows}</div>
  {sample_note}
  <p class="hint"><a href="/admin/reports?{_tab_qs('failures')}" hx-get="/admin/reports?{_tab_qs('failures')}" hx-target="#reports-content" hx-swap="outerHTML" hx-push-url="true">Xem từng lần lỗi và đăng lại →</a></p>
</div>"""

        # Success vs failure per action: one split bar each.
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
            action_html = ""
            for action, c in pivoted.items():
                total = c["succeeded"] + c["failed"]
                rate = round(100 * c["succeeded"] / total) if total else 0
                action_html += (
                    f'<div class="act-row"><div class="bar-label">{html.escape(_ACTION_LABELS.get(action, action))}</div>'
                    f'{_split_bar_html(c["succeeded"], c["failed"])}'
                    f'<div class="act-num"><span class="dot dot-ok"></span>{c["succeeded"]} <span class="dot dot-bad"></span>{c["failed"]} · {rate}%</div></div>'
                )
            actions_card = (
                '<div class="card"><h2>📈 Thành công / thất bại theo hành động</h2>'
                '<div class="bar-legend"><span><span class="dot dot-ok"></span>Thành công</span><span><span class="dot dot-bad"></span>Thất bại</span></div>'
                f'<div class="bars">{action_html}</div></div>'
            )
        else:
            actions_card = '<div class="card"><h2>📈 Thành công / thất bại theo hành động</h2><div class="empty-state">Chưa có dữ liệu.</div></div>'

        # Posts per group: the NAME (the saved one when the log has none), top 10, the rest one click away.
        group_rows = db.group_post_counts(account_id=account_id, since=since)
        if group_rows:
            several = len({r["account_id"] for r in group_rows}) > 1

            def group_row(r) -> str:
                url = r["target_url"] or ""
                name = r["target_group_name"] or name_lookup(r["account_id"], url) or url.rstrip("/").rsplit("/", 1)[-1] or "(chưa rõ tên)"
                label = f'<a href="{html.escape(url)}" target="_blank" rel="noopener" title="{html.escape(url)}">{html.escape(name)}</a>' if url else html.escape(name)
                if several:
                    label += f' <span class="sched-acct">· {html.escape(_account_label(r["account_id"], accounts))}</span>'
                return _bar_row_html(label, r["total"], group_rows[0]["total"])

            shown, rest = group_rows[:10], group_rows[10:]
            more = (
                f'<details class="rep-more"><summary>Xem thêm {len(rest)} nhóm</summary><div class="bars">{"".join(group_row(r) for r in rest)}</div></details>'
                if rest else ""
            )
            groups_card = f'<div class="card"><h2>👥 Bài đăng theo nhóm</h2><div class="bars">{"".join(group_row(r) for r in shown)}</div>{more}</div>'
        else:
            groups_card = '<div class="card"><h2>👥 Bài đăng theo nhóm</h2><div class="empty-state">Chưa có bài đăng nhóm nào được ghi nhận.</div></div>'

        tab_content_html = f"""
{weekly_card}
<div class="rep-grid">{causes_card}{actions_card}</div>
{groups_card}"""

    # ------------------------------------------------------------------ "Bài đăng": one job = one card
    # (2026-09-12) — target groups, per-group content actually posted, per-group time and result, and the raw
    # side-B job data it came from. Grouped server-side by db.job_post_groups() (source_kind='job' rows only —
    # candidates have no per-group fan-out to gather), rendered as one <details> per job so the (potentially long)
    # per-group list only takes space once opened.
    elif tab == "jobs":
        job_total = db.job_post_groups_count(account_id=account_id, since=since)
        job_total_pages = max(1, -(-job_total // _JOB_REPORT_PAGE_SIZE))
        job_page = min(max(job_page, 1), job_total_pages)
        job_rows = db.job_post_groups(
            account_id=account_id, since=since,
            limit=_JOB_REPORT_PAGE_SIZE, offset=(job_page - 1) * _JOB_REPORT_PAGE_SIZE,
        )

        def _job_data(raw: str | None) -> dict:
            try:
                data = json.loads(raw) if raw else {}
            except (TypeError, ValueError):
                return {}
            return data if isinstance(data, dict) else {}

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
            handled = _handled_status([d for rows in job_detail_by_source.values() for d in rows])
            for jr in job_rows:
                detail_rows = job_detail_by_source[(jr["source_id"], jr["account_id"])]
                data = _job_data(jr["job_data"])
                raw_present = bool(jr["job_data"])
                if data:
                    summary_line = _attrs_summary_html(data.get("title"), data.get("attributes"))
                else:
                    summary_line = '<span class="muted">(không có dữ liệu gốc)</span>' if not raw_present else '<span class="muted">(dữ liệu gốc không đọc được)</span>'
                title_text = _format_attr(data.get("title")) or "(không có tiêu đề)"
                succeeded = sum(1 for d in detail_rows if d["success"])
                waiting = sum(1 for d in detail_rows if not d["success"] and db.is_rate_limited(d["message"]))
                failed = len(detail_rows) - succeeded - waiting
                result_summary = f'<span class="badge badge-ok">{succeeded} thành công</span>'
                if failed:
                    result_summary += f' <span class="badge badge-bad">{failed} thất bại</span>'
                if waiting:
                    result_summary += f' <span class="badge badge-warn">{waiting} chưa chạy</span>'
                rows_html = "".join(_row_html(d, handled, show_account=False, show_action=False) for d in detail_rows)
                job_cards_html += f"""
<details class="rep-job">
  <summary>
    <span class="rep-job-title">{html.escape(title_text)}</span>
    <span class="sched-acct">{html.escape(_account_label(jr['account_id'], accounts))} · {len(detail_rows)} nhóm</span>
    <span class="rep-job-result">{result_summary}</span>
    <span class="muted rep-job-when">{_local_dt_html(jr['first_posted_at'])} → {_local_dt_html(jr['last_posted_at'])}</span>
  </summary>
  <div class="rep-job-data">{summary_line}</div>
  <div class="sched-list rep-job-rows">{rows_html}</div>
</details>"""
        else:
            job_cards_html = '<div class="empty-state">Chưa có bài đăng job nào được ghi nhận.</div>'

        tab_content_html = f"""
<div class="card">
  <h2>📮 Bài đăng</h2>
  {job_cards_html}
  {_simple_pager_html(job_page, job_total_pages, job_total, "job", page_key="job_page", tab_key="jobs")}
</div>"""

    # ------------------------------------------------------------------ "Bình luận" (2026-09-12, flattened same
    # day per owner request) — for candidate replies (source_kind='candidate'): which post/friend a comment went to,
    # the candidate's own raw attributes (desiredJobField/preferredRegion — see content_strategist.
    # rewrite_candidate_reply()'s docstring), and the actual comment text posted. FLAT list, one row per action_log
    # row — a candidate only ever gets ONE comment (no per-group fan-out like a job), so grouping just added a
    # pointless extra click per row.
    elif tab == "candidates":
        candidate_total = db.candidate_comments_count(account_id=account_id, since=since)
        candidate_total_pages = max(1, -(-candidate_total // _CANDIDATE_REPORT_PAGE_SIZE))
        candidate_page = min(max(candidate_page, 1), candidate_total_pages)
        candidate_rows = db.candidate_comments(
            account_id=account_id, since=since,
            limit=_CANDIDATE_REPORT_PAGE_SIZE, offset=(candidate_page - 1) * _CANDIDATE_REPORT_PAGE_SIZE,
        )

        def _candidate_extra(raw: str | None) -> str:
            if not raw:
                return ""
            try:
                data = json.loads(raw)
            except (TypeError, ValueError):
                return '<div class="rep-extra muted">(dữ liệu gốc không đọc được)</div>'
            parts = _attr_parts(None, data.get("attributes") if isinstance(data, dict) else None)
            return f'<div class="rep-extra">{" &nbsp;·&nbsp; ".join(parts)}</div>' if parts else ""

        if candidate_rows:
            handled = _handled_status(candidate_rows)
            candidate_html = "".join(
                _row_html(r, handled, show_action=False, extra_html=_candidate_extra(r["job_data"]))
                for r in candidate_rows
            )
            candidate_cards_html = f'<div class="sched-list">{candidate_html}</div>'
        else:
            candidate_cards_html = '<div class="empty-state">Chưa có bình luận nào được ghi nhận.</div>'

        tab_content_html = f"""
<div class="card">
  <h2>💬 Bình luận</h2>
  {candidate_cards_html}
  {_simple_pager_html(candidate_page, candidate_total_pages, candidate_total, "bình luận", page_key="candidate_page", tab_key="candidates")}
</div>"""

    # ------------------------------------------------------------------ "Hoạt động" / "Lỗi": paginated list
    # (the same rows; "Lỗi" keeps only what failed, rate-limited deferrals excluded exactly like the number above)
    else:
        only_failed = tab == "failures"
        recent_total = db.recent_activity_count(account_id=account_id, since=since, only_failed=only_failed)
        recent_total_pages = max(1, -(-recent_total // page_size))
        page = min(max(page, 1), recent_total_pages)
        recent_rows = db.recent_activity(
            limit=page_size, offset=(page - 1) * page_size, account_id=account_id, since=since, only_failed=only_failed,
        )
        if recent_rows:
            handled = _handled_status(recent_rows)
            recent_table = f'<div class="sched-list">{"".join(_row_html(r, handled, show_source=True) for r in recent_rows)}</div>'
        elif only_failed:
            recent_table = '<div class="empty-state">Không có lần nào thất bại trong khoảng thời gian này. 🎉</div>'
        else:
            recent_table = '<div class="empty-state">Chưa có hoạt động nào được ghi nhận.</div>'

        recent_pagination_html = ""
        if recent_total_pages > 1:
            # First/last buttons + a pretty single-pill "go to page" jump —
            # same pattern (and same owner request) as /admin/schedule's
            # pagination; page_size threads through so navigating never
            # silently resets it back to the default.
            jump_hidden_fields = (
                (f'<input type="hidden" name="account_id" value="{html.escape(account_id)}">' if account_id else "")
                + (f'<input type="hidden" name="days" value="{html.escape(days)}">' if days else "")
                + f'<input type="hidden" name="page_size" value="{page_size}">'
                + f'<input type="hidden" name="tab" value="{tab}">'
            )
            recent_pagination_html = f"""
<div class="rep-pager">
  <div style="display:flex; gap:8px; align-items:center;">
    {_pager_link(1, "«« Đầu", page > 1, page_key="page", tab_key=tab)}
    {_pager_link(page - 1, "← Trang trước", page > 1, page_key="page", tab_key=tab)}
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
    {_pager_link(page + 1, "Trang sau →", page < recent_total_pages, page_key="page", tab_key=tab)}
    {_pager_link(recent_total_pages, "Cuối »»", page < recent_total_pages, page_key="page", tab_key=tab)}
  </div>
</div>"""

        title, intro = (
            ("⚠️ Các lần thất bại", '<p class="page-desc">Bấm ↻ để đăng lại, đặt lịch hoặc lên lịch lại. Với lỗi “chưa rõ bài đã lên chưa”, hãy xem trên Facebook trước — đăng lại có thể thành bài trùng.</p>')
            if only_failed else ("🕒 Hoạt động gần đây", "")
        )
        tab_content_html = f"""
<div class="card">
  <div style="display:flex; justify-content:space-between; align-items:center; gap:16px; flex-wrap:wrap;">
    <h2 style="margin:0; white-space:nowrap;">{title}</h2>
    <div style="display:flex; gap:10px; align-items:center; white-space:nowrap; flex-shrink:0;">
      {page_size_select_html}
      <span class="muted">{recent_total} mục</span>
    </div>
  </div>
  {intro}
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


_RETENTION_FIELDS: list[tuple[str, str, str, str]] = [
    ("screenshot_days", "Ảnh chụp bằng chứng",
     "Ảnh chụp lại mỗi lần đăng hoặc bình luận.",
     "Hết hạn: lần đó mất link \"📷 Xem\", chữ và số liệu vẫn còn."),
    ("schedule_days", "Bản lưu bài đã đăng / lỗi / huỷ",
     "Bản lưu của các bài đã đăng, đã lỗi hoặc đã huỷ, gồm cả ghi chú lý do quá hạn còn sót lại.",
     "Hết hạn: chỉ mất bản lưu này, báo cáo không ảnh hưởng. Bài đang chờ đăng không bao giờ bị xoá."),
    ("action_log_days", "Lịch sử báo cáo",
     "Mỗi lần bot thử đăng hoặc bình luận, thành công hay thất bại.",
     "⚠️ Hết hạn: lần đó BIẾN MẤT khỏi mọi báo cáo ở trang này — đây là mục duy nhất xoá lịch sử báo cáo."),
]

_RETENTION_MAX_DAYS = 3650  # 10 years — keeps timedelta() far from overflow


def _retention_settings_card_html() -> str:
    cfg = get_retention_config()
    rows = []
    for field, title, what, effect in _RETENTION_FIELDS:
        rows.append(f"""
<div class="field-row">
  <div class="field-label">{html.escape(title)}
    <div class="field-key">{html.escape(what)}<br>{html.escape(effect)}</div>
  </div>
  <div class="field-input" style="display:flex; align-items:center; gap:8px;"><input type="number" name="{field}" min="0" max="{_RETENTION_MAX_DAYS}" step="1"
       value="{getattr(cfg, field)}" required style="flex:1; min-width:0;"><span class="muted">ngày</span></div>
</div>""")
    return f"""
<div class="card" id="retention-settings">
  <h2>⚙️ Thời hạn lưu dữ liệu</h2>
  <p class="page-desc">Sau bao nhiêu ngày thì từng loại dữ liệu cũ tự động bị xoá. Nhập <b>0</b> = không bao giờ tự xoá loại đó.
  Việc dọn chạy lúc hệ thống khởi động rồi mỗi 24 giờ — thay đổi ở đây áp dụng từ lần dọn kế tiếp, không cần khởi động lại, và không xoá gì ngay lập tức.</p>
  <form method="post" action="/admin/reports/retention"
        hx-post="/admin/reports/retention" hx-target="#reports-content" hx-swap="outerHTML">
    <div class="field-grid">{"".join(rows)}</div>
    <p class="muted" style="margin-top:12px;">Bộ nhớ chống trùng tin bên B (mặc định 45 ngày) có cấu hình riêng ở <a href="/admin/config?tab=sync">Cấu hình → Đồng bộ dữ liệu</a>.</p>
    <div class="form-actions"><button type="submit">Lưu thời hạn</button></div>
  </form>
</div>"""


@router.post("/reports/retention")
async def reports_retention_save(request: Request, _: None = Depends(_require_login)):
    """Saves the 3 data-retention windows (human_bot/retention_config.py) —
    all three together, since save_retention_overrides() replaces the whole
    section. 0 is valid (= never auto-delete); blank/non-integer/negative/
    absurdly large is rejected with nothing saved, rather than silently
    coerced — a mistyped retention value is exactly the kind of input that
    could delete history the owner meant to keep."""
    form = await request.form()
    values: dict[str, int] = {}
    error: str | None = None
    for field, title, _what, _effect in _RETENTION_FIELDS:
        try:
            n = int(str(form.get(field, "")).strip())
        except ValueError:
            error = f"\"{title}\": cần nhập một số nguyên."
            break
        if not 0 <= n <= _RETENTION_MAX_DAYS:
            error = f"\"{title}\": phải từ 0 đến {_RETENTION_MAX_DAYS} ngày."
            break
        values[field] = n
    if error is None:
        save_retention_overrides(values)
    posted = None if error else "Đã lưu thời hạn lưu dữ liệu — áp dụng từ lần dọn kế tiếp."
    if _is_htmx(request):
        return HTMLResponse(_reports_content_html(tab="settings", posted=posted, error=error))
    return _reports_redirect(None, None, 1, tab="settings", posted=posted, error=error)


@router.get("/screenshot")
async def admin_screenshot(path: str, _: None = Depends(_require_login)):
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
    _: None = Depends(_require_login),
) -> str:
    content = _reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, posted=posted, error=error, warning=warning)
    if _is_htmx(request):
        return content
    return _layout(f"""
<h1>Báo cáo</h1>
<p class="page-desc">Các lần bot đã thử đăng hoặc bình luận trong {_retention_note()}, cả thành công lẫn thất bại, bất kể đăng tay, theo lịch hay tự động.</p>
{content}
""", active="reports", current_user=_build_current_user(request))


def _retention_note() -> str:
    """"180 ngày gần nhất" for /admin/reports' description — the real
    action_log window (RetentionConfig.action_log_days), or a plain
    statement that nothing is being pruned when it is set to 0."""
    days = get_retention_config().action_log_days
    return f"{days} ngày gần nhất" if days > 0 else "toàn bộ thời gian (đang tắt tự xoá)"


def _reports_redirect(account_id: str | None, days: str | None, page: int, **params) -> RedirectResponse:
    from urllib.parse import urlencode
    query = {"account_id": account_id, "days": days, "page": page, **params}
    query = {k: v for k, v in query.items() if v not in (None, "", 0)}
    return RedirectResponse(url=f"/admin/reports?{urlencode(query)}", status_code=303)


@router.post("/reports/repost")
async def reports_repost(request: Request, _: None = Depends(_require_login)):
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
    err = _already_posted_error(row)
    if err:
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
    if db.is_rate_limited(result.message):
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
    _: None = Depends(_require_login),
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
    _: None = Depends(_require_login),
) -> str:
    """Step 1 of "Lên lịch lại" — computes and shows the suggested slot
    (_suggest_reschedule_at()); admin confirms via
    reports_reschedule_confirm() below before anything is actually added
    to the schedule."""
    row = db.get_action_log(log_id)
    if row is None or row["action"] not in _REPOSTABLE_ACTIONS or row["success"] or not (row["content"] or "").strip():
        return ""
    already = _already_posted_error(row)
    if already:
        return (
            '<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">'
            f'<div class="modal-box"><p class="warning">✅ {html.escape(already)}</p></div></div>'
        )
    account = get_all_accounts().get(row["account_id"])
    if account is None:
        return (
            '<div class="modal-backdrop" onclick="if(event.target===this) this.remove()">'
            '<div class="modal-box"><p class="error">⚠️ Không tìm thấy tài khoản này.</p></div></div>'
        )
    caution, confirm = _failure_caution(row)
    confirm_attr = f' hx-confirm="{html.escape(confirm)}"' if confirm else ""
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
    {caution}
    <p>Giờ đăng gợi ý: <b>{_local_dt_html(suggested.isoformat())}</b></p>
    <p class="muted">Đã tính theo giới hạn số lượng/ngày, khoảng cách tối thiểu với lần đăng gần nhất, và giờ yên tĩnh đang cấu hình. Bấm Xác nhận để thêm vào lịch (xem/sửa lại ở /admin/schedule), hoặc Huỷ để tự chọn giờ khác qua "Đặt lịch".</p>
    <div class="form-actions">
      <button type="button" class="btn-secondary" style="margin-right:8px;" onclick="this.closest('.modal-backdrop').remove()">Huỷ</button>
      <form method="post" action="/admin/reports/reschedule-confirm"
            hx-post="/admin/reports/reschedule-confirm" hx-target="#reports-content" hx-swap="outerHTML" style="display:inline;"{confirm_attr}>
        {filter_fields}
        <button type="submit">✅ Xác nhận</button>
      </form>
    </div>
  </div>
</div>"""


@router.post("/reports/reschedule-confirm")
async def reports_reschedule_confirm(request: Request, _: None = Depends(_require_login)):
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
    err = _already_posted_error(row)
    if err:
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
        # A job typed at /admin/post keeps the AI/template text the admin
        # chose; side-B jobs keep their usual fire-time AI re-draft.
        ai_redraft=not str(source_id).startswith("manual-"),
    )
    schedule_store.add(task)
    msg = "Đã thêm vào lịch — xem/sửa ở /admin/schedule."
    return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, page_size=page_size, job_page=job_page, candidate_page=candidate_page, tab=tab, posted=msg) + _MODAL_CLOSE_OOB)
