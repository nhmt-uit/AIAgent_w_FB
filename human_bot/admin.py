"""
Purpose of this file / Muc dich cua file nay:
EN: Local-only web admin UI, mounted into human_bot/service.py's FastAPI
app under /admin. Two things it replaces: (1) editing HUMAN_TYPING_* values
in .env and restarting the process — now a form that writes
runtime_config.json and takes effect on the very next post; (2) typing
post content as a terminal command-line argument — now a textarea, or a
.txt file dropped into content_queue/pending/. This page has real
Facebook-posting power (it calls the exact same run_task() as the /tasks
API n8n uses), so it is protected with HTTP Basic Auth when ADMIN_USERNAME
and ADMIN_PASSWORD are set in .env, and should never be exposed to the
public internet — see docs/architecture.md.
VI: Giao dien quan tri web, chi dung noi bo, duoc gan vao ung dung FastAPI
cua human_bot/service.py duoi duong dan /admin. No thay the hai viec:
(1) sua cac gia tri HUMAN_TYPING_* trong .env roi khoi dong lai tien
trinh — gio la mot form ghi vao runtime_config.json va co hieu luc ngay
tu lan dang bai tiep theo; (2) go noi dung bai dang truc tiep trong tham
so dong lenh terminal — gio la mot o textarea, hoac tha mot file .txt vao
content_queue/pending/. Trang nay co quyen dang bai that len Facebook (no
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
import dataclasses
import html
import json
import os
import random
import re
import secrets
import sqlite3
from datetime import datetime, timedelta, timezone

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import FileResponse, HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials
from pathlib import Path

from human_bot import content_queue, db, schedule_store, screenshots
from human_bot.agent import TaskRequest, run_task
from human_bot.config import (
    ACCOUNT_AGE_TIERS,
    AccountStatus,
    GroupRef,
    RateLimits,
    get_all_accounts,
    new_group_id,
)
from human_bot.data_sync import apply_quiet_hours, get_all_sync_statuses
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
    get_rate_limits_overrides,
    save_rate_limits_overrides,
    EDITABLE_RATE_LIMITS_FIELDS,
    get_sync_disabled_account_ids,
    set_account_sync_enabled,
)
from human_bot.safety_cooldown_config import SafetyCooldownConfig

router = APIRouter(prefix="/admin", tags=["admin"])
_security = HTTPBasic(auto_error=False)

_POSTABLE_ACTIONS = ["post_to_own_profile"]

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

_BOOL_FIELDS = {"enabled", "auto_fire_enabled", "attach_random_meme_default"}

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
}

_ICONS["data_sync"] = "🔄"

_CONFIG_SECTIONS.append(
    ("data_sync", "data_sync", "Đồng bộ dữ liệu bên B", DataSyncConfig, EDITABLE_DATA_SYNC_FIELDS, _DATA_SYNC_LABELS,
     get_data_sync_overrides, save_data_sync_overrides)
)

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
    "cooldown_days": "Số ngày áp giới hạn thấp sau khi kích hoạt lại, trước khi tự trở về giới hạn cũ",
    "posts_per_day": "Số bài đăng tối đa/ngày trong lúc hạ nhiệt",
    "comments_per_hour": "Số comment tối đa/giờ trong lúc hạ nhiệt",
    "comments_per_day": "Số comment tối đa/ngày trong lúc hạ nhiệt",
    "likes_per_hour": "Số lượt thích tối đa/giờ trong lúc hạ nhiệt",
    "min_delay_seconds": "Khoảng chờ giữa 2 hành động — tối thiểu (giây) trong lúc hạ nhiệt",
    "max_delay_seconds": "Khoảng chờ giữa 2 hành động — tối đa (giây) trong lúc hạ nhiệt",
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

  input[type=text], input[type=number], input[type=datetime-local], textarea, select {
    @apply w-full box-border px-2.5 py-2 text-sm border border-gray-200 rounded-lg bg-white text-gray-900 font-sans;
  }
  input[type=text]:focus, input[type=number]:focus, input[type=datetime-local]:focus, textarea:focus, select:focus {
    @apply outline-none border-indigo-600 ring-4 ring-indigo-50;
  }
  input[type=checkbox] { @apply w-[18px] h-[18px] accent-indigo-600 cursor-pointer; }
  textarea { @apply min-h-[160px] resize-y; }

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
  function initScheduleField(wrap) {
    if (wrap.dataset.scheduleInit) return;
    wrap.dataset.scheduleInit = "1";
    var localInput = wrap.querySelector("[data-schedule-local]");
    var utcInput = wrap.querySelector("[data-schedule-utc]");
    if (!localInput || !utcInput) return;

    function pad(n) { return String(n).padStart(2, "0"); }
    function toLocalInputValue(date) {
      return date.getFullYear() + "-" + pad(date.getMonth() + 1) + "-" + pad(date.getDate())
        + "T" + pad(date.getHours()) + ":" + pad(date.getMinutes());
    }

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

  // Plain tab switcher for /admin/post's Tường cá nhân / Đăng vào nhóm /
  // Hàng đợi sections — added because the page got long enough that
  // having all 3 always visible at once was more scrolling than
  // scanning. No routing/state beyond which panel is showing; the
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
    root.querySelectorAll("[data-preserve-post-form]").forEach(initPreservePostForm);
    root.querySelectorAll("[data-tabs]").forEach(initTabs);
  }

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
  document.body.addEventListener("htmx:afterSwap", function () { initDynamicScope(document); });
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
    sections_html = []
    for section_key, prefix, title, config_cls, editable_fields, labels, get_overrides, _save_fn in _CONFIG_SECTIONS:
        current = get_overrides()
        defaults = config_cls()
        rows = []
        for field_name in editable_fields:
            label = labels.get(field_name, field_name)
            default_val = getattr(defaults, field_name)
            value = current.get(field_name, default_val)
            form_name = f"{prefix}__{field_name}"
            if field_name in _BOOL_FIELDS:
                checked = "checked" if value else ""
                input_html = f'<input type="checkbox" name="{form_name}" value="true" {checked}>'
            else:
                input_html = f'<input type="number" step="any" name="{form_name}" value="{html.escape(str(value))}">'
            rows.append(f"""
<div class="field-row">
  <div class="field-label">{html.escape(label)}<div class="field-key">mặc định: {html.escape(str(default_val))} · key: {field_name}</div></div>
  <div class="field-input">{input_html}</div>
</div>""")
        icon = _ICONS.get(prefix, "")
        sections_html.append((section_key, f"""
<div class="card">
  <h2>{icon} {html.escape(title)}</h2>
  <div class="field-grid">{''.join(rows)}</div>
</div>"""))
    flash = '<p class="flash">✅ Đã lưu cấu hình. Áp dụng ngay từ lần đăng bài tiếp theo.</p>' if saved else ""

    behavior_cards = "".join(card for key, card in sections_html if key != "data_sync")
    sync_cards = "".join(card for key, card in sections_html if key == "data_sync")

    active_tab = tab if tab in ("behavior", "sync") else "behavior"

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
  </div>

  <div class="tab-panel" id="tab-behavior"{panel_attrs("behavior")}>
    {behavior_cards}
  </div>

  <div class="tab-panel" id="tab-sync"{panel_attrs("sync")}>
    <p class="page-desc">Cấu hình cho bộ đồng bộ dữ liệu bên B (human_bot/data_sync.py). Lần sync gần nhất theo từng tài khoản: xem <a href="/admin/accounts?tab=sync">Tài khoản → Đồng bộ</a>.</p>
    {sync_cards}
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
        f'<option value="{tier_key}"{" selected" if tier_key == "under_1_month" else ""}>'
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


_RATE_LIMITS_LABELS: dict[str, str] = {
    "posts_per_day": "Số bài đăng tối đa / ngày",
    "comments_per_hour": "Số comment tối đa / giờ",
    "comments_per_day": "Số comment tối đa / ngày",
    "likes_per_hour": "Số like tối đa / giờ",
    "min_delay_seconds": "Khoảng chờ tối thiểu giữa 2 hành động (giây)",
    "max_delay_seconds": "Khoảng chờ tối đa giữa 2 hành động (giây)",
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
    # bit, without typing 6 numbers by hand each time. Each posts straight
    # to a dedicated route rather than filling the form client-side, so
    # the numbers applied always match ACCOUNT_AGE_TIERS exactly. Targets
    # just #rate-limits-body (this function's own wrapper below), not the
    # whole modal — see this function's docstring.
    tier_buttons = "".join(
        f'''<form method="post" action="/admin/accounts/rate-limits/apply-tier" style="display:inline;"
        hx-post="/admin/accounts/rate-limits/apply-tier" hx-target="#rate-limits-body" hx-swap="innerHTML">
  <input type="hidden" name="account_id" value="{html.escape(account_id)}">
  <input type="hidden" name="age_tier" value="{tier_key}">
  <button type="submit" class="btn-small btn-secondary" style="margin:2px;">{html.escape(label)} ({rl.posts_per_day} bài/ngày)</button>
</form>'''
        for tier_key, (label, rl) in ACCOUNT_AGE_TIERS.items()
    )
    return f"""<div id="rate-limits-body">
    {reset_note}
    {err_html}
    <p class="page-desc">Áp nhanh theo tuổi tài khoản Facebook:</p>
    <div>{tier_buttons}</div>
    <form method="post" action="/admin/accounts/rate-limits" hx-post="/admin/accounts/rate-limits" hx-target="#modal-root" hx-swap="innerHTML">
      <input type="hidden" name="account_id" value="{html.escape(account_id)}">
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
                f'{_fmt_jst(entry.get("last_run_at"))} — '
                f'{entry.get("jobs_fetched", 0)} job, {entry.get("candidates_fetched", 0)} candidate lấy về, '
                f'{entry.get("scheduled_posts", 0)} bài + {entry.get("scheduled_comments", 0)} comment mới lên lịch'
            )
        else:
            last_run_cell = (
                f'<span class="badge" style="background:#fef2f2;color:#dc2626;">⚠️ Lỗi</span> '
                f'{_fmt_jst(entry.get("last_run_at"))} — {html.escape(str(entry.get("error", "")))}'
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
            else '<span class="badge" style="background:#fef2f2;color:#dc2626;">chưa có storage_state.json</span>'
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
                when_txt = _fmt_jst(info["paused_at"])
                status_detail = f'<div class="row-url">từ {when_txt} — {reason_txt}</div>'
        else:
            cooldown = get_resume_cooldown_info(aid)
            if cooldown:
                until_txt = _fmt_jst(cooldown.get("until"))
                reason_txt = html.escape(cooldown.get("reason") or "không rõ")
                status_detail = (
                    f'<div class="row-url">🧊 Hạ nhiệt tới {until_txt} (giới hạn thấp) '
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
        rows.append(f"""
<tr>
  <td>{html.escape(a.display_name)}<div class="row-url">{html.escape(aid)}</div></td>
  <td>{status_badge}{status_detail}</td>
  <td>{session_badge}</td>
  <td class="row-url">{html.escape(source)}</td>
  <td class="col-actions">{status_action} {rate_limits_btn} {delete_btn}</td>
</tr>""")

    table = f"""
<div class="table-scroll">
  <table class="data-table">
    <thead><tr><th>Tài khoản</th><th>Trạng thái</th><th>Phiên đăng nhập</th><th>Nguồn</th><th></th></tr></thead>
    <tbody>{"".join(rows) or '<tr><td colspan="5" class="empty-state">Chưa có tài khoản nào</td></tr>'}</tbody>
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
    age_tier = str(form.get("age_tier", "")).strip()
    if age_tier in ACCOUNT_AGE_TIERS:
        _, preset = ACCOUNT_AGE_TIERS[age_tier]
        save_rate_limits_overrides(account_id, dataclasses.asdict(preset))
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
      runtime_config.json and could later overwrite a freshly
      re-registered account's rate limits once its `until` naturally
      passed, reaching back from before the account even existed again

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
    if values["min_delay_seconds"] > values["max_delay_seconds"]:
        return _fail("Khoảng chờ tối thiểu phải nhỏ hơn hoặc bằng khoảng chờ tối đa", RateLimits(**values))

    save_rate_limits_overrides(account_id, values)
    if _is_htmx(request):
        return HTMLResponse(_accounts_content_html(saved=True, oob=True))
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.post("/accounts/rate-limits/apply-tier")
async def accounts_rate_limits_apply_tier(request: Request, _: None = Depends(_require_auth)):
    """One of the quick-apply buttons in _rate_limits_modal_body_html() —
    sets the account's rate-limit override to exactly one of
    ACCOUNT_AGE_TIERS' presets (human_bot/config.py), for when an account
    ages into the next tier and its limits should loosen a bit without
    hand-typing 6 numbers. The htmx branch returns just the BODY partial
    (targets #rate-limits-body, not #modal-root) so repeated clicks don't
    unmount/remount the whole modal — see
    _rate_limits_modal_body_html()'s docstring."""
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    age_tier = str(form.get("age_tier", "")).strip()
    accounts = get_all_accounts()
    if account_id not in accounts:
        err = "Không tìm thấy tài khoản này"
        if _is_htmx(request):
            return HTMLResponse(_rate_limits_modal_body_html(account_id, RateLimits(), is_override=False, error=err))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': err})}", status_code=303)
    if age_tier not in ACCOUNT_AGE_TIERS:
        err = "Tuổi tài khoản không hợp lệ"
        if _is_htmx(request):
            return HTMLResponse(_rate_limits_modal_body_html(account_id, accounts[account_id].rate_limits, is_override=True, error=err))
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': err})}", status_code=303)
    _, preset = ACCOUNT_AGE_TIERS[age_tier]
    save_rate_limits_overrides(account_id, dataclasses.asdict(preset))
    if _is_htmx(request):
        return HTMLResponse(_rate_limits_modal_body_html(account_id, preset, is_override=True))
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
  <input type="checkbox" name="groups_0" value="{html.escape(g.url)}"> {html.escape(g.name or g.url)}
</label>'''
            for g in groups
        )
        group_post_card = f"""
<div class="card">
  <h2>👥 Đăng vào nhóm — {html.escape(account_labels[account_id])}</h2>
  <p class="page-desc">Có thể tạo nhiều khối nội dung khác nhau, mỗi khối đăng vào một tập nhóm riêng — ví dụ nội dung A cho 3 nhóm đầu, nội dung B cho nhóm còn lại. Hệ thống tự rải giờ đăng giữa TẤT CẢ các bài (kể cả giữa các khối khác nhau) theo khoảng cách đang cấu hình ở <a href="/admin/config?tab=sync">Cấu hình → Đồng bộ dữ liệu</a> — không đăng dồn một lúc dù chọn nhiều nhóm.</p>
  <form method="post" action="/admin/post/schedule-groups">
    <input type="hidden" name="account_id" value="{html.escape(account_id)}">
    <div data-repeatable-blocks>
      <div data-block-list>
        <div class="content-block" data-block style="border:1px solid #e5e7eb; border-radius:12px; padding:14px; margin-bottom:10px;">
          <textarea name="content_0" placeholder="Nội dung cho các nhóm được chọn bên dưới..." required></textarea>
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

    queue_items = content_queue.list_pending()
    if queue_items:
        queue_html = "".join(f"""
<div class="queue-item">
  <div class="queue-filename">{html.escape(item['filename'])}</div>
  <div class="queue-preview">{html.escape(item['preview'])}</div>
  <form method="post" action="/admin/post/queue">
    <input type="hidden" name="filename" value="{html.escape(item['filename'])}">
    {_custom_select("account_id", account_ids, labels=account_labels)}
    {_custom_select("action", _POSTABLE_ACTIONS, labels=_ACTION_LABELS)}
    <button type="submit" class="btn-small">Đăng mục này</button>
  </form>
</div>""" for item in queue_items)
    else:
        queue_html = '<div class="empty-state">Hàng đợi trống. Thả file .txt vào content_queue/pending/, hoặc tải lên bên dưới.</div>'

    active_tab = tab if tab in ("profile", "group", "queue") else "profile"

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
    {tab_btn("queue", "📥 Hàng đợi nội dung")}
  </div>

  <div class="tab-panel" id="tab-profile"{panel_attrs("profile")}>
    <div class="card">
      <h2>👤 Đăng lên tường cá nhân — {html.escape(account_labels[account_id])}</h2>
      <form method="post" action="/admin/post/schedule-profile">
        <input type="hidden" name="account_id" value="{html.escape(account_id)}">
        <textarea name="content" placeholder="Nội dung bài đăng..." required data-preserve-profile-content>{html.escape(profile_content or "")}</textarea>
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

  <div class="tab-panel" id="tab-queue"{panel_attrs("queue")}>
    <div class="card">
      <h2>📥 Hàng đợi nội dung (content_queue/pending/)</h2>
      {queue_html}
    </div>
    <div class="card">
      <h2>⬆️ Tải lên file .txt mới vào hàng đợi</h2>
      <form method="post" action="/admin/post/upload" enctype="multipart/form-data" style="display:flex; gap:10px; align-items:center;">
        <input type="file" name="file" accept=".txt" required style="width:auto; flex:1;">
        <button type="submit" class="btn-secondary">Thêm vào hàng đợi</button>
      </form>
    </div>
  </div>
</div>
""", active="post")


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
    task = schedule_store.ScheduledTask(
        task_id=schedule_store.new_task_id(scheduled_at.isoformat()),
        action="post_to_own_profile",
        account_id=account_id,
        scheduled_at=scheduled_at.isoformat(),
        content=content,
        reasoning="manual: composed at /admin/post",
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
            )
            schedule_store.add(task)
            scheduled_count += 1
            next_time = next_time + timedelta(
                minutes=random.uniform(cfg.post_gap_min_minutes, cfg.post_gap_max_minutes)
            )

    return RedirectResponse(url=f"/admin/post?account_id={account_id}&tab=group&scheduled={scheduled_count}", status_code=303)


@router.post("/post/queue")
async def post_from_queue(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    form = await request.form()
    filename = str(form.get("filename", ""))
    account_id = str(form.get("account_id", ""))
    action = str(form.get("action", ""))
    try:
        content = content_queue.read_pending(filename)
    except FileNotFoundError:
        return RedirectResponse(url="/admin/post?tab=queue&error=File+không+còn+trong+hàng+đợi", status_code=303)
    result = await run_task(TaskRequest(action=action, account_id=account_id, content=content, source="queue"))
    if result.success:
        content_queue.mark_posted(filename)
        return RedirectResponse(url=f"/admin/post?tab=queue&posted=Đã đăng {filename}: {result.message}", status_code=303)
    content_queue.mark_failed(filename, result.message)
    return RedirectResponse(url=f"/admin/post?tab=queue&error=Đăng {filename} thất bại: {result.message}", status_code=303)


@router.post("/post/upload")
async def post_upload(file: UploadFile, _: None = Depends(_require_auth)) -> RedirectResponse:
    raw = await file.read()
    text = raw.decode("utf-8", errors="replace")
    saved_name = content_queue.add_pending(file.filename or "post.txt", text)
    return RedirectResponse(url=f"/admin/post?tab=queue&posted=Đã thêm vào hàng đợi: {saved_name}", status_code=303)


# --- Schedule (side-B data-sync poller output) ------------------------------

def _fmt_dt(iso: str | None) -> str:
    """Human-friendly display of an ISO 8601 UTC timestamp — HH:MM:SS
    DD-MM-YYYY, used everywhere a raw created_at/scheduled_at would
    otherwise leak into the UI as-is (e.g. "2026-09-04T08:37:54.787563
    +00:00"). Falls back to the raw string if it doesn't parse cleanly
    rather than hiding a value the caller might still need to debug."""
    if not iso:
        return "—"
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%H:%M:%S %d-%m-%Y") + " UTC"
    except (ValueError, AttributeError):
        return iso


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


_SCHEDULE_PAGE_SIZE = 20


def _schedule_page_link(account_id: str | None, target_page: int, label: str, enabled: bool) -> str:
    if not enabled:
        return f'<span class="btn-secondary btn-small" style="opacity:.45; pointer-events:none;">{label}</span>'
    from urllib.parse import urlencode
    qs = urlencode({k: v for k, v in {"account_id": account_id, "page": target_page}.items() if v})
    return (
        f'<a class="btn-secondary btn-small" href="/admin/schedule?{qs}" '
        f'hx-get="/admin/schedule?{qs}" hx-target="#schedule-content" hx-swap="outerHTML" hx-push-url="true">{label}</a>'
    )


def _schedule_content_html(
    account_id: str | None = None, page: int = 1, saved: bool = False, error: str | None = None
) -> str:
    accounts = get_all_accounts()
    if account_id and account_id not in accounts:
        account_id = None  # unknown/stale filter falls back to "all", never a hard error
    all_tasks = schedule_store.list_pending()
    tasks = [t for t in all_tasks if not account_id or t.account_id == account_id]

    total = len(tasks)
    total_pages = max(1, -(-total // _SCHEDULE_PAGE_SIZE))  # ceil division
    page = min(max(page, 1), total_pages)
    start = (page - 1) * _SCHEDULE_PAGE_SIZE
    page_tasks = tasks[start:start + _SCHEDULE_PAGE_SIZE]

    flash = '<p class="flash">✅ Đã cập nhật.</p>' if saved else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""

    # Filtering by account is what keeps this page workable once the
    # schedule gets busy (many accounts/groups) — switching accounts
    # always jumps back to page 1 (this <select> never sends a `page`
    # param), so a filter change never lands on a now-out-of-range page.
    account_options = '<option value="">— Tất cả tài khoản —</option>' + "".join(
        f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(a.display_name)} ({html.escape(aid)})</option>'
        for aid, a in accounts.items()
    )
    filter_html = f"""
<div class="account-filter">
  <label for="schedule-account-select">Tài khoản</label>
  <select name="account_id" id="schedule-account-select"
          hx-get="/admin/schedule" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-trigger="change" hx-push-url="true">{account_options}</select>
  <span class="badge">{total} bài đang chờ</span>
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
        pagination_html = f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-top:14px;">
  {_schedule_page_link(account_id, page - 1, "← Trang trước", page > 1)}
  <span class="muted">Trang {page}/{total_pages}</span>
  {_schedule_page_link(account_id, page + 1, "Trang sau →", page < total_pages)}
</div>"""

    return f"""<div id="schedule-content">
{filter_html}
{flash}{err}
{list_html}
{pagination_html}
</div>"""


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_list(
    request: Request,
    account_id: str | None = None,
    page: int = 1,
    saved: bool = False,
    error: str | None = None,
    _: None = Depends(_require_auth),
) -> str:
    content = _schedule_content_html(account_id=account_id, page=page, saved=saved, error=error)
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


def _schedule_form_filter(form) -> tuple[str | None, int]:
    account_id = str(form.get("account_id", "")).strip() or None
    try:
        page = int(str(form.get("page", "1")))
    except ValueError:
        page = 1
    return account_id, page


@router.post("/schedule/update")
async def schedule_update(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id, page = _schedule_form_filter(form)
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
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, error=err))
        return _schedule_redirect(account_id, page, error=err)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, saved=True))
    return _schedule_redirect(account_id, page, saved=1)


@router.post("/schedule/cancel")
async def schedule_cancel(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id, page = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    schedule_store.cancel(task_id)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, saved=True))
    return _schedule_redirect(account_id, page, saved=1)


# Closes the "Vẫn đăng ngay?" rate-limit modal (see
# _fire_now_confirm_modal_html()) via an out-of-band swap tacked onto
# every htmx response from schedule_fire_now() — harmless when no modal
# is open (an empty #modal-root swapped for an empty #modal-root).
_MODAL_CLOSE_OOB = '<div id="modal-root" hx-swap-oob="true"></div>'


def _fire_now_confirm_modal_html(task_id: str, account_id: str | None, page: int, warning: str) -> str:
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
    account_id, page = _schedule_form_filter(form)
    task_id = str(form.get("task_id", ""))
    force = str(form.get("force", "")) == "1"
    task = schedule_store.get(task_id)
    if task is None:
        err = "Không tìm thấy mục này"
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, error=err) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, error=err)

    from human_bot.agent import rate_limit_bucket_for
    from human_bot.safety import RateLimiter, is_gap_reason, rate_limit_wait_message
    account = get_all_accounts().get(task.account_id)
    bucket = rate_limit_bucket_for(task.action)
    if account and bucket and not force:
        allowed, reason = RateLimiter(account).can_proceed(bucket)
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
                modal_oob = f'<div id="modal-root" hx-swap-oob="true">{_fire_now_confirm_modal_html(task_id, account_id, page, warning)}</div>'
                return HTMLResponse(_schedule_content_html(account_id=account_id, page=page) + modal_oob)
            return _schedule_redirect(account_id, page, error=warning)

    result = await run_task(TaskRequest(
        action=task.action,
        account_id=task.account_id,
        target_url=task.target_url,
        content=task.content,
        media_path=task.media_path,
        reasoning=task.reasoning,
        source="schedule_manual",
        source_kind=task.source_kind,
        source_id=task.source_id,
        force_ignore_gap=force,
    ))
    if result.success:
        schedule_store.mark_posted(task_id, result.message)
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, saved=True) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, saved=1)
    if result.message.startswith("rate_limited:"):
        # Same reasoning as data_sync.py's fire_due_tasks(): this isn't a
        # real failure of the post, it just fired too soon after the
        # account's last action (or hit a hard count cap — never
        # overridable) — keep it in pending/ with a warning instead of
        # failed/.
        warning = rate_limit_wait_message(account, bucket) if account and bucket else None
        schedule_store.update(task_id, last_warning=warning or result.message)
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, error=warning or result.message) + _MODAL_CLOSE_OOB)
        return _schedule_redirect(account_id, page, error=warning or result.message)
    schedule_store.mark_failed(task_id, result.message)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(account_id=account_id, page=page, error=f"Đăng thất bại: {result.message}") + _MODAL_CLOSE_OOB)
    return _schedule_redirect(account_id, page, error=f"Đăng thất bại: {result.message}")


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
    """Show `text` truncated to `limit` chars, with a native <details>
    disclosure (no JS needed) to expand and read the full thing — for
    /admin/reports' "Ghi chú" column, where a Playwright error message can
    run well past a single line (see the conversation that raised this:
    truncating to 80 chars with no way to see the rest loses real debug
    info). Only wraps in <details> when actually truncated; a short
    message renders as plain text, no disclosure triangle for nothing."""
    text = text or ""
    if not text:
        return '<span class="muted">—</span>'
    if len(text) <= limit:
        return html.escape(text)
    short = html.escape(text[:limit])
    full = html.escape(text)
    return (
        f'<details><summary style="cursor:pointer; display:inline;">{short}…</summary>'
        f'<div style="white-space:pre-wrap; margin-top:4px; max-width:480px;">{full}</div></details>'
    )


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
    posted: str | None = None, error: str | None = None,
) -> str:
    accounts = get_all_accounts()
    since = _reports_since(days)
    flash = f'<p class="flash">✅ {html.escape(posted)}</p>' if posted else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""

    account_options = '<option value="">— Tất cả tài khoản —</option>' + "".join(
        f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(a.display_name)} ({html.escape(aid)})</option>'
        for aid, a in accounts.items()
    )
    days_options = "".join(
        f'<option value="{html.escape(key)}"{" selected" if (days or "") == key else ""}>{html.escape(label)}</option>'
        for key, label in _REPORTS_DAYS_LABELS.items()
    )
    filter_html = f"""
<div class="account-filter">
  <label for="reports-account-select">Tài khoản</label>
  <select name="account_id" id="reports-account-select"
          hx-get="/admin/reports" hx-target="#reports-content" hx-swap="outerHTML"
          hx-trigger="change" hx-include="#reports-days-select" hx-push-url="true">{account_options}</select>
  <label for="reports-days-select">Khoảng thời gian</label>
  <select name="days" id="reports-days-select"
          hx-get="/admin/reports" hx-target="#reports-content" hx-swap="outerHTML"
          hx-trigger="change" hx-include="#reports-account-select" hx-push-url="true">{days_options}</select>
</div>"""

    # --- KPI summary — glance-and-go health check before the detail tables ---
    stats = db.summary_stats(account_id=account_id, since=since)
    rate_display = f"{stats['success_rate']}%" if stats["success_rate"] is not None else "—"
    summary_html = f"""
<div class="card">
  <div style="display:flex; gap:24px; flex-wrap:wrap;">
    <div><div class="muted" style="font-size:12px;">Tổng số hành động</div><div style="font-size:22px; font-weight:700;">{stats['total']}</div></div>
    <div><div class="muted" style="font-size:12px;">Thành công</div><div style="font-size:22px; font-weight:700; color:#059669;">{stats['succeeded']}</div></div>
    <div><div class="muted" style="font-size:12px;">Thất bại</div><div style="font-size:22px; font-weight:700; color:#dc2626;">{stats['failed']}</div></div>
    <div><div class="muted" style="font-size:12px;">Tỉ lệ thành công</div><div style="font-size:22px; font-weight:700;">{rate_display}</div></div>
    <div><div class="muted" style="font-size:12px;">Tài khoản có hoạt động</div><div style="font-size:22px; font-weight:700;">{stats['active_accounts']}</div></div>
  </div>
</div>"""

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
        action_html = "".join(
            f"""<tr>
  <td>{html.escape(_ACTION_LABELS.get(r['action'], r['action']))}</td>
  <td>{'✅ Thành công' if r['success'] else '⚠️ Thất bại'}</td>
  <td>{r['total']}</td>
</tr>""" for r in action_rows
        )
        action_table = f"""
<div class="table-scroll"><table class="data-table">
  <thead><tr><th>Hành động</th><th>Kết quả</th><th>Số lần</th></tr></thead>
  <tbody>{action_html}</tbody>
</table></div>"""
    else:
        action_table = '<div class="empty-state">Chưa có dữ liệu.</div>'

    # --- Recent activity: paginated + height-capped, so this block (by far
    # the longest one) never dominates the page regardless of how much
    # history exists — see the conversation that raised "4 khối khá dài,
    # nhất là Hoạt động gần đây".
    recent_total = db.recent_activity_count(account_id=account_id, since=since)
    recent_total_pages = max(1, -(-recent_total // _REPORTS_RECENT_PAGE_SIZE))
    page = min(max(page, 1), recent_total_pages)
    recent_rows = db.recent_activity(
        limit=_REPORTS_RECENT_PAGE_SIZE,
        offset=(page - 1) * _REPORTS_RECENT_PAGE_SIZE,
        account_id=account_id,
        since=since,
    )
    def _repost_button_html(r: sqlite3.Row) -> str:
        # Only offer "Đăng lại" for actions that post free-form `content`
        # somewhere, only when that content survived into the log row, and
        # only for FAILED attempts — a successful one doesn't need
        # retrying, and resubmitting it would just post/comment a
        # duplicate (per-project decision, 2026-09-09). A repost resubmits
        # via run_task() exactly like /admin/schedule's "Đăng ngay", but
        # built from action_log instead of a pending schedule_store task.
        # media_path is never in action_log (not captured by agent.py's
        # _log_result()), so a repost is always text-only even if the
        # original attempt had an image attached.
        if r['action'] not in _REPOSTABLE_ACTIONS or r['success'] or not (r['content'] or '').strip():
            return ""
        is_comment = r['action'] in ("comment_on_group_post", "comment_on_friend_post")
        confirm_msg = "Đăng lại comment này ngay bây giờ?" if is_comment else "Đăng lại bài viết này ngay bây giờ?"
        filter_fields = (
            f'<input type="hidden" name="account_id" value="{html.escape(account_id or "")}">'
            f'<input type="hidden" name="days" value="{html.escape(days or "")}">'
            f'<input type="hidden" name="page" value="{page}">'
            f'<input type="hidden" name="log_id" value="{r["id"]}">'
        )
        return f"""<form method="post" action="/admin/reports/repost" style="display:inline;"
        hx-post="/admin/reports/repost" hx-target="#reports-content" hx-swap="outerHTML"
        hx-confirm="{confirm_msg}">
  {filter_fields}
  <button type="submit" class="btn-secondary btn-small" title="Đăng lại">↻</button>
</form>"""

    if recent_rows:
        recent_html = "".join(
            f"""<tr>
  <td>{_fmt_dt(r['created_at'])}</td>
  <td>{html.escape(_account_label(r['account_id'], accounts))}</td>
  <td>{html.escape(_ACTION_LABELS.get(r['action'], r['action']))}</td>
  <td class="row-url">{html.escape((r['target_group_name'] or r['target_url'] or '—'))}</td>
  <td>{'✅' if r['success'] else '⚠️'}</td>
  <td>{html.escape(_SOURCE_LABELS.get(r['source'], r['source']))}</td>
  <td>{_screenshot_link_html(r['screenshot_path'] if 'screenshot_path' in r.keys() else None)}</td>
  <td class="muted">{_expandable_text(r['message'])}</td>
  <td>{_repost_button_html(r)}</td>
</tr>""" for r in recent_rows
        )
        recent_table = f"""
<div class="table-scroll" style="max-height:420px; overflow-y:auto;"><table class="data-table">
  <thead><tr><th>Thời gian (UTC)</th><th>Tài khoản</th><th>Hành động</th><th>Đích</th><th>KQ</th><th>Nguồn</th><th>Ảnh</th><th>Ghi chú</th><th>Thao tác</th></tr></thead>
  <tbody>{recent_html}</tbody>
</table></div>"""
    else:
        recent_table = '<div class="empty-state">Chưa có hoạt động nào được ghi nhận.</div>'

    recent_pagination_html = ""
    if recent_total_pages > 1:
        from urllib.parse import urlencode

        def _recent_page_link(target_page: int, label: str, enabled: bool) -> str:
            if not enabled:
                return f'<span class="btn-secondary btn-small" style="opacity:.45; pointer-events:none;">{label}</span>'
            qs = urlencode({k: v for k, v in {"account_id": account_id, "days": days, "page": target_page}.items() if v})
            return (
                f'<a class="btn-secondary btn-small" href="/admin/reports?{qs}" '
                f'hx-get="/admin/reports?{qs}" hx-target="#reports-content" hx-swap="outerHTML" hx-push-url="true">{label}</a>'
            )

        recent_pagination_html = f"""
<div style="display:flex; justify-content:space-between; align-items:center; margin-top:10px;">
  {_recent_page_link(page - 1, "← Trang trước", page > 1)}
  <span class="muted">Trang {page}/{recent_total_pages} · {recent_total} mục</span>
  {_recent_page_link(page + 1, "Trang sau →", page < recent_total_pages)}
</div>"""

    return f"""<div id="reports-content">
{flash}
{err}
{filter_html}
{summary_html}

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
</div>

<div class="card">
  <h2>🕒 Hoạt động gần đây</h2>
  {recent_table}
  {recent_pagination_html}
</div>
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
    posted: str | None = None,
    error: str | None = None,
    _: None = Depends(_require_auth),
) -> str:
    content = _reports_content_html(account_id=account_id, days=days, page=page, posted=posted, error=error)
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
        log_id = int(str(form.get("log_id", "")))
    except ValueError:
        return _reports_redirect(account_id, days, page, error="Thiếu id bản ghi")

    row = db.get_action_log(log_id)
    if row is None:
        err = "Không tìm thấy bản ghi này"
        if _is_htmx(request):
            return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, error=err))
        return _reports_redirect(account_id, days, page, error=err)
    if row["action"] not in _REPOSTABLE_ACTIONS or row["success"] or not (row["content"] or "").strip():
        err = "Hành động này không thể đăng lại"
        if _is_htmx(request):
            return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, error=err))
        return _reports_redirect(account_id, days, page, error=err)

    try:
        result = await run_task(TaskRequest(
            action=row["action"],
            account_id=row["account_id"],
            target_url=row["target_url"],
            content=row["content"],
            reasoning=f"repost: từ báo cáo (bản ghi #{log_id})",
            source="manual",
        ))
    except ValueError as exc:
        err = str(exc)
        if _is_htmx(request):
            return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, error=err))
        return _reports_redirect(account_id, days, page, error=err)

    if result.success:
        msg = "Đã đăng lại."
        if _is_htmx(request):
            return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, posted=msg))
        return _reports_redirect(account_id, days, page, posted=msg)
    err = f"Đăng lại thất bại: {result.message}"
    if _is_htmx(request):
        return HTMLResponse(_reports_content_html(account_id=account_id, days=days, page=page, error=err))
    return _reports_redirect(account_id, days, page, error=err)
