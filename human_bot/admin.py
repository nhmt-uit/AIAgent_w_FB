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
import html
import os
import re
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from human_bot import content_queue, db, schedule_store
from human_bot.agent import TaskRequest, run_task
from human_bot.config import GroupRef, get_all_accounts
from human_bot.data_sync_config import DataSyncConfig
from human_bot.media import MediaConfig
from human_bot.humanize import HumanMouseConfig, HumanPacingConfig, HumanTypingConfig
from human_bot.runtime_config import (
    EDITABLE_HUMAN_TYPING_FIELDS,
    EDITABLE_PACING_FIELDS,
    EDITABLE_MOUSE_FIELDS,
    EDITABLE_DATA_SYNC_FIELDS,
    EDITABLE_MEDIA_FIELDS,
    get_human_typing_overrides,
    get_pacing_overrides,
    get_mouse_overrides,
    get_data_sync_overrides,
    get_media_overrides,
    get_joined_groups,
    get_registered_accounts,
    save_human_typing_overrides,
    save_pacing_overrides,
    save_mouse_overrides,
    save_data_sync_overrides,
    save_media_overrides,
    save_joined_groups,
    save_registered_account,
    delete_registered_account,
)

router = APIRouter(prefix="/admin", tags=["admin"])
_security = HTTPBasic(auto_error=False)

_POSTABLE_ACTIONS = ["post_to_own_profile"]
# Separate from _POSTABLE_ACTIONS (used by content_queue items, which have
# no per-item target-group field in the UI — that queue was designed for
# plain own-profile text posts). The "Đăng trực tiếp" manual form gets its
# own action list plus a target-group selector, added 2026-09-04 once
# post_to_group's full 4-tier chain was merged into actions.py.
_MANUAL_POST_ACTIONS = ["post_to_own_profile", "post_to_group"]

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
}

_ICONS: dict[str, str] = {
    "typing": "⌨️",
    "pacing": "⏱️",
    "mouse": "🖱️",
}

_BOOL_FIELDS = {"enabled", "auto_fire_enabled", "attach_random_meme_default"}

_CONFIG_SECTIONS = [
    ("human_typing", "typing", "Gõ phím", HumanTypingConfig, EDITABLE_HUMAN_TYPING_FIELDS, _TYPING_LABELS,
     get_human_typing_overrides, save_human_typing_overrides),
    ("pacing", "pacing", "Khoảng chờ theo ngữ cảnh", HumanPacingConfig, EDITABLE_PACING_FIELDS, _PACING_LABELS,
     get_pacing_overrides, save_pacing_overrides),
    ("mouse", "mouse", "Di chuyển chuột", HumanMouseConfig, EDITABLE_MOUSE_FIELDS, _MOUSE_LABELS,
     get_mouse_overrides, save_mouse_overrides),
]

_DATA_SYNC_LABELS: dict[str, str] = {
    "enabled": "Bật bộ đồng bộ dữ liệu từ bên B (lấy + chống trùng + đặt lịch)",
    "auto_fire_enabled": "⚠️ Tự động đăng khi đến giờ (tắt = chỉ đặt lịch, phải bấm 'Đăng ngay' thủ công)",
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
  .topbar-inner { @apply max-w-5xl mx-auto flex items-center gap-4 sm:gap-7 h-14 flex-wrap; }
  .brand { @apply font-bold text-base tracking-tight flex items-center gap-2; }
  .brand-dot { @apply w-2.5 h-2.5 rounded-full bg-indigo-600 inline-block; }
  nav.topnav { @apply flex gap-1 flex-wrap; }
  nav.topnav a { @apply text-gray-500 text-sm font-medium px-3 py-1.5 rounded-md hover:bg-indigo-50 hover:text-indigo-600 hover:no-underline transition-colors; }
  nav.topnav a.active { @apply bg-indigo-50 text-indigo-600; }

  main { @apply max-w-5xl mx-auto px-4 sm:px-6 py-8 pb-16; }

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

  input[type=text], input[type=number], textarea, select {
    @apply w-full box-border px-2.5 py-2 text-sm border border-gray-200 rounded-lg bg-white text-gray-900 font-sans;
  }
  input[type=text]:focus, input[type=number]:focus, textarea:focus, select:focus {
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

  .muted { @apply text-gray-500 text-sm; }

  .flash, .error { @apply rounded-2xl px-4 py-3 mb-5 text-sm flex items-center gap-2; }
  .flash { @apply bg-emerald-50 border border-emerald-200 text-emerald-700; }
  .error { @apply bg-red-50 border border-red-200 text-red-700; }

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
  document.addEventListener("DOMContentLoaded", function () {
    document.querySelectorAll("[data-cselect]").forEach(initCSelect);
  });

  // Modal: Escape closes whichever .modal-backdrop is currently open
  // (opening/closing the backdrop itself is plain DOM — see
  // .modal-backdrop's onclick and .modal-close's onclick inline in the
  // markup — this only adds the keyboard shortcut on top of those).
  document.addEventListener("keydown", function (e) {
    if (e.key !== "Escape") return;
    var backdrop = document.querySelector(".modal-backdrop");
    if (backdrop) backdrop.remove();
  });
})();
</script>
"""


def _custom_select(name: str, options: list[str], selected: str | None = None) -> str:
    """Render a styled dropdown (trigger button + panel opening below it)
    backed by a real <select name="..."> so existing form handlers and
    field names keep working unchanged."""
    if selected is None:
        selected = options[0] if options else ""
    native_opts = "".join(
        f'<option value="{html.escape(opt)}"{" selected" if opt == selected else ""}>{html.escape(opt)}</option>'
        for opt in options
    )
    return f"""<div class="cselect" data-cselect>
  <select name="{html.escape(name)}" class="cselect-native">{native_opts}</select>
  <button type="button" class="cselect-trigger"><span class="cselect-trigger-label">{html.escape(selected)}</span><span class="chevron">▾</span></button>
  <div class="cselect-panel"></div>
</div>"""


def _manual_post_group_select_html(selected_url: str = "") -> str:
    """Plain <select name="target_url"> listing every saved group across
    every account (from /admin/groups' saved list), for the "Đăng trực
    tiếp" form's post_to_group option. Not built with _custom_select()
    since that helper only supports value == display label, and here the
    displayed label ("<account> — <group name>") needs to differ from the
    submitted value (the group's URL) — same raw-<select> approach
    /admin/groups' account filter already uses. Only relevant when the
    accompanying "Hành động" field is set to post_to_group; ignored by the
    post_to_own_profile handler path (see post_manual() below), so it's
    safe to always render regardless of which action is selected — no
    JS toggle needed on this still-full-reload page (see the module
    docstring's note on which /admin pages did NOT move to htmx)."""
    options = ['<option value="">— (không cần cho đăng tường cá nhân) —</option>']
    for account_id, account in get_all_accounts().items():
        for g in get_joined_groups(account_id):
            label = f"{account.display_name} — {g.name or g.url}"
            is_selected = " selected" if g.url == selected_url else ""
            options.append(
                f'<option value="{html.escape(g.url)}"{is_selected}>{html.escape(label)}</option>'
            )
    # Plain <select> (not wrapped in the .cselect custom-dropdown
    # component) — the base `select { ... }` Tailwind rule already styles
    # any bare <select> consistently with the rest of the form, no extra
    # class needed. Using .cselect-native's own class here would do
    # nothing outside a .cselect wrapper (that hidden rule is scoped to
    # ".cselect select.cselect-native"), so it's correctly left off.
    return f'<select name="target_url">{"".join(options)}</select>'


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
      <a href="/admin/config" class="{nav_class('config')}">Cấu hình hành vi</a>
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
    return _layout(f"""
<h1>Bảng điều khiển</h1>
<p class="page-desc">Trang quản trị nội bộ. Không public trang này ra internet — nó có quyền đăng bài thật lên Facebook.</p>

<div class="card">
  <h2>👤 Tài khoản đã đăng ký <span class="badge">{len(accounts)}</span></h2>
  <ul class="account-list">{accounts_html}</ul>
</div>

<div class="home-links">
  <a class="home-link-card" href="/admin/accounts">
    <div class="title">👤 Tài khoản</div>
    <div class="desc">Đăng ký tài khoản mới sau khi chạy bootstrap_login.py — không cần sửa code.</div>
  </a>
  <a class="home-link-card" href="/admin/config">
    <div class="title">⚙️ Cấu hình hành vi</div>
    <div class="desc">Chỉnh tốc độ gõ, khoảng chờ, di chuyển chuột — áp dụng ngay, không cần khởi động lại.</div>
  </a>
  <a class="home-link-card" href="/admin/post">
    <div class="title">📝 Đăng bài</div>
    <div class="desc">Đăng trực tiếp hoặc quản lý hàng đợi nội dung (content_queue).</div>
  </a>
  <a class="home-link-card" href="/admin/groups">
    <div class="title">👥 Nhóm đã tham gia</div>
    <div class="desc">Danh sách URL nhóm Facebook mỗi tài khoản đã tham gia — bộ đồng bộ bên B dùng để broadcast bài đăng nhóm.</div>
  </a>
  <a class="home-link-card" href="/admin/schedule">
    <div class="title">🔄 Lịch đăng</div>
    <div class="desc">Xem, sửa, huỷ các bài đã được bộ đồng bộ bên B lên lịch — hoặc đăng ngay thủ công.</div>
  </a>
  <a class="home-link-card" href="/admin/reports">
    <div class="title">📊 Báo cáo</div>
    <div class="desc">Tài khoản nào đăng bao nhiêu bài mỗi tuần, đăng vào nhóm nào, tỉ lệ thành công/thất bại.</div>
  </a>
</div>
""", active="home")


@router.get("/config", response_class=HTMLResponse)
async def config_form(saved: bool = False, _: None = Depends(_require_auth)) -> str:
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
        sections_html.append(f"""
<div class="card">
  <h2>{icon} {html.escape(title)}</h2>
  <div class="field-grid">{''.join(rows)}</div>
</div>""")
    flash = '<p class="flash">✅ Đã lưu cấu hình. Áp dụng ngay từ lần đăng bài tiếp theo.</p>' if saved else ""
    return _layout(f"""
<h1>Cấu hình hành vi giống người</h1>
<p class="page-desc">Ghi vào runtime_config.json (không đụng tới .env), có hiệu lực ngay, không cần khởi động lại service.</p>
{flash}
<form method="post" action="/admin/config">
{''.join(sections_html)}
<div class="form-actions"><button type="submit">Lưu cấu hình</button></div>
</form>
""", active="config")


@router.post("/config")
async def config_save(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    form = await request.form()
    for section_key, prefix, _title, _config_cls, editable_fields, _labels, _get_fn, save_fn in _CONFIG_SECTIONS:
        values: dict = {}
        for field_name in editable_fields:
            form_name = f"{prefix}__{field_name}"
            if field_name in _BOOL_FIELDS:
                values[field_name] = form_name in form
                continue
            raw = form.get(form_name)
            if raw in (None, ""):
                continue
            try:
                values[field_name] = float(raw)
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


@router.get("/accounts", response_class=HTMLResponse)
async def accounts_page(saved: bool = False, error: str | None = None, _: None = Depends(_require_auth)) -> str:
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
        is_runtime = aid in registered_ids
        source = "/admin/accounts" if is_runtime else "human_bot/config.py"
        delete_btn = (
            f"""<form method="post" action="/admin/accounts/delete" onsubmit="return confirm('Xoá tài khoản {html.escape(aid)} khỏi danh sách? File storage_state.json sẽ không bị xoá.');">
  <input type="hidden" name="account_id" value="{html.escape(aid)}">
  <button type="submit" class="btn-secondary btn-small">Xoá</button>
</form>"""
            if is_runtime
            else '<span class="muted">—</span>'
        )
        rows.append(f"""
<tr>
  <td>{html.escape(a.display_name)}<div class="row-url">{html.escape(aid)}</div></td>
  <td>{session_badge}</td>
  <td class="row-url">{html.escape(source)}</td>
  <td class="col-actions">{delete_btn}</td>
</tr>""")

    table = f"""
<div class="table-scroll">
  <table class="data-table">
    <thead><tr><th>Tài khoản</th><th>Phiên đăng nhập</th><th>Nguồn</th><th></th></tr></thead>
    <tbody>{"".join(rows) or '<tr><td colspan="4" class="empty-state">Chưa có tài khoản nào</td></tr>'}</tbody>
  </table>
</div>"""

    return _layout(f"""
<h1>Tài khoản</h1>
<p class="page-desc">Đăng ký tài khoản mới ở đây sau khi đã chạy <code>python3 human_bot/bootstrap_login.py &lt;account_id&gt;</code> trên máy này — không cần sửa human_bot/config.py hay khởi động lại service. Tài khoản đăng ký ở đây dùng rate limit / nhóm mặc định, chỉnh thêm ở /admin/config và /admin/groups nếu cần.</p>
{flash}{err}

<div class="card">
  <h2>➕ Đăng ký tài khoản mới</h2>
  <form method="post" action="/admin/accounts/add">
  <div class="field-grid">
    <div class="field-stack"><div class="field-label">account_id (khớp với tên đã dùng ở bootstrap_login.py)</div><div class="field-input"><input type="text" name="account_id" placeholder="vd: my_page" required pattern="[a-z0-9_]+"></div></div>
    <div class="field-stack"><div class="field-label">Tên hiển thị</div><div class="field-input"><input type="text" name="display_name" placeholder="vd: Trang của tôi"></div></div>
  </div>
  <div class="form-actions"><button type="submit">Đăng ký</button></div>
  </form>
</div>

<div class="card">
  <h2>👤 Tài khoản hiện có <span class="badge">{len(accounts)}</span></h2>
  {table}
</div>
""", active="accounts")


@router.post("/accounts/add")
async def accounts_add(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip().lower()
    display_name = str(form.get("display_name", "")).strip()
    error = _account_id_error(account_id, get_all_accounts())
    if error:
        from urllib.parse import urlencode
        return RedirectResponse(url=f"/admin/accounts?{urlencode({'error': error})}", status_code=303)
    save_registered_account(account_id, display_name or account_id)
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.post("/accounts/delete")
async def accounts_delete(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    form = await request.form()
    account_id = str(form.get("account_id", "")).strip()
    delete_registered_account(account_id)
    return RedirectResponse(url="/admin/accounts?saved=1", status_code=303)


@router.get("/post", response_class=HTMLResponse)
async def post_form(posted: str | None = None, error: str | None = None, _: None = Depends(_require_auth)) -> str:
    account_ids = list(get_all_accounts())
    flash = f'<p class="flash">✅ {html.escape(posted)}</p>' if posted else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    queue_items = content_queue.list_pending()
    if queue_items:
        queue_html = "".join(f"""
<div class="queue-item">
  <div class="queue-filename">{html.escape(item['filename'])}</div>
  <div class="queue-preview">{html.escape(item['preview'])}</div>
  <form method="post" action="/admin/post/queue">
    <input type="hidden" name="filename" value="{html.escape(item['filename'])}">
    {_custom_select("account_id", account_ids)}
    {_custom_select("action", _POSTABLE_ACTIONS)}
    <button type="submit" class="btn-small">Đăng mục này</button>
  </form>
</div>""" for item in queue_items)
    else:
        queue_html = '<div class="empty-state">Hàng đợi trống. Thả file .txt vào content_queue/pending/, hoặc tải lên bên dưới.</div>'
    return _layout(f"""
<h1>Đăng bài</h1>
{flash}{err}

<div class="card">
  <h2>✍️ Đăng trực tiếp</h2>
  <form method="post" action="/admin/post/manual">
  <div class="field-grid">
    <div class="field-stack"><div class="field-label">Tài khoản</div><div class="field-input">{_custom_select("account_id", account_ids)}</div></div>
    <div class="field-stack"><div class="field-label">Hành động</div><div class="field-input">{_custom_select("action", _MANUAL_POST_ACTIONS)}</div></div>
    <div class="field-stack"><div class="field-label">Nhóm mục tiêu (chỉ dùng khi Hành động = post_to_group)</div><div class="field-input">{_manual_post_group_select_html()}</div></div>
  </div>
  <div style="margin-top:14px"><textarea name="content" placeholder="Nội dung bài đăng..." required></textarea></div>
  <div class="form-actions"><button type="submit">Đăng ngay</button></div>
  </form>
</div>

<div class="section-divider">Hàng đợi nội dung (content_queue/pending/)</div>
{queue_html}

<div class="card">
  <h2>⬆️ Tải lên file .txt mới vào hàng đợi</h2>
  <form method="post" action="/admin/post/upload" enctype="multipart/form-data" style="display:flex; gap:10px; align-items:center;">
    <input type="file" name="file" accept=".txt" required style="width:auto; flex:1;">
    <button type="submit" class="btn-secondary">Thêm vào hàng đợi</button>
  </form>
</div>
""", active="post")


@router.post("/post/manual")
async def post_manual(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    form = await request.form()
    account_id = str(form.get("account_id", ""))
    action = str(form.get("action", ""))
    content = str(form.get("content", ""))
    target_url = str(form.get("target_url", "")).strip() or None
    if not content.strip():
        return RedirectResponse(url="/admin/post?error=Nội+dung+trống", status_code=303)
    if action == "post_to_group" and not target_url:
        return RedirectResponse(url="/admin/post?error=Chưa+chọn+nhóm+mục+tiêu", status_code=303)
    result = await run_task(TaskRequest(
        action=action, account_id=account_id, content=content, target_url=target_url, source="manual",
    ))
    if result.success:
        return RedirectResponse(url=f"/admin/post?posted=Đã đăng thành công: {result.message}", status_code=303)
    return RedirectResponse(url=f"/admin/post?error={result.message}", status_code=303)


@router.post("/post/queue")
async def post_from_queue(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    form = await request.form()
    filename = str(form.get("filename", ""))
    account_id = str(form.get("account_id", ""))
    action = str(form.get("action", ""))
    try:
        content = content_queue.read_pending(filename)
    except FileNotFoundError:
        return RedirectResponse(url="/admin/post?error=File+không+còn+trong+hàng+đợi", status_code=303)
    result = await run_task(TaskRequest(action=action, account_id=account_id, content=content, source="queue"))
    if result.success:
        content_queue.mark_posted(filename)
        return RedirectResponse(url=f"/admin/post?posted=Đã đăng {filename}: {result.message}", status_code=303)
    content_queue.mark_failed(filename, result.message)
    return RedirectResponse(url=f"/admin/post?error=Đăng {filename} thất bại: {result.message}", status_code=303)


@router.post("/post/upload")
async def post_upload(file: UploadFile, _: None = Depends(_require_auth)) -> RedirectResponse:
    raw = await file.read()
    text = raw.decode("utf-8", errors="replace")
    saved_name = content_queue.add_pending(file.filename or "post.txt", text)
    return RedirectResponse(url=f"/admin/post?posted=Đã thêm vào hàng đợi: {saved_name}", status_code=303)


# --- Schedule (side-B data-sync poller output) ------------------------------

def _fmt_dt(iso: str) -> str:
    """Best-effort human-friendly display of an ISO 8601 UTC timestamp;
    falls back to the raw string if it doesn't parse cleanly."""
    try:
        from datetime import datetime
        dt = datetime.fromisoformat(iso.replace("Z", "+00:00"))
        return dt.strftime("%Y-%m-%d %H:%M UTC")
    except (ValueError, AttributeError):
        return iso


def _schedule_content_html(saved: bool = False, error: str | None = None) -> str:
    tasks = schedule_store.list_pending()
    flash = '<p class="flash">✅ Đã cập nhật.</p>' if saved else ""
    err = f'<p class="error">⚠️ {html.escape(error)}</p>' if error else ""
    if tasks:
        items_html = []
        for t in tasks:
            content_preview = html.escape((t.content or "")[:400])
            target = html.escape(t.target_url or "—")
            source = f"{html.escape(t.source_kind or '?')} · {html.escape(t.source_id or '?')}" if t.source_kind else "thủ công"
            items_html.append(f"""
<div class="queue-item">
  <div class="queue-filename">{html.escape(t.action)} · {html.escape(t.account_id)} · {_fmt_dt(t.scheduled_at)}</div>
  <div class="queue-preview">{content_preview}</div>
  <div class="field-key">Đích: {target} · Nguồn: {source} · id: {html.escape(t.task_id)}</div>
  <form method="post" action="/admin/schedule/update"
        hx-post="/admin/schedule/update" hx-target="#schedule-content" hx-swap="outerHTML"
        style="margin-top:8px; display:flex; gap:8px; align-items:flex-start; flex-wrap:wrap;">
    <input type="hidden" name="task_id" value="{html.escape(t.task_id)}">
    <textarea name="content" style="flex:1; min-width:240px; min-height:60px;">{content_preview}</textarea>
    <input type="text" name="scheduled_at" value="{html.escape(t.scheduled_at)}" style="width:220px;" title="ISO 8601 UTC, vd 2026-09-05T03:00:00Z">
    <button type="submit" class="btn-small">Lưu</button>
  </form>
  <div style="margin-top:8px; display:flex; gap:8px;">
    <form method="post" action="/admin/schedule/fire-now"
          hx-post="/admin/schedule/fire-now" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-confirm="Đăng bài này lên Facebook ngay bây giờ?">
      <input type="hidden" name="task_id" value="{html.escape(t.task_id)}">
      <button type="submit" class="btn-small">🚀 Đăng ngay</button>
    </form>
    <form method="post" action="/admin/schedule/cancel"
          hx-post="/admin/schedule/cancel" hx-target="#schedule-content" hx-swap="outerHTML"
          hx-confirm="Huỷ lịch đăng này?">
      <input type="hidden" name="task_id" value="{html.escape(t.task_id)}">
      <button type="submit" class="btn-secondary btn-small">Huỷ</button>
    </form>
  </div>
</div>""")
        list_html = "".join(items_html)
    else:
        list_html = '<div class="empty-state">Chưa có bài nào đang chờ lịch. Bộ đồng bộ bên B sẽ tự điền vào đây khi có dữ liệu mới.</div>'
    return f"""<div id="schedule-content">
{flash}{err}
{list_html}
</div>"""


@router.get("/schedule", response_class=HTMLResponse)
async def schedule_list(request: Request, saved: bool = False, error: str | None = None, _: None = Depends(_require_auth)) -> str:
    content = _schedule_content_html(saved, error)
    if _is_htmx(request):
        return content
    return _layout(f"""
<h1>Lịch đăng</h1>
<p class="page-desc">Các bài do bộ đồng bộ dữ liệu bên B (human_bot/data_sync.py) lấy về và lên lịch. Khi "Tự động đăng khi đến giờ" đang TẮT (mặc định), các bài này chỉ được đăng khi bạn bấm "Đăng ngay" thủ công.</p>
{content}
""", active="schedule")


@router.post("/schedule/update")
async def schedule_update(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    task_id = str(form.get("task_id", ""))
    content = str(form.get("content", ""))
    scheduled_at = str(form.get("scheduled_at", ""))
    updated = schedule_store.update(task_id, content=content, scheduled_at=scheduled_at)
    if updated is None:
        err = "Không tìm thấy mục này (có thể đã được đăng hoặc huỷ)"
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(error=err))
        return RedirectResponse(url=f"/admin/schedule?error={err}", status_code=303)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(saved=True))
    return RedirectResponse(url="/admin/schedule?saved=1", status_code=303)


@router.post("/schedule/cancel")
async def schedule_cancel(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    task_id = str(form.get("task_id", ""))
    schedule_store.cancel(task_id)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(saved=True))
    return RedirectResponse(url="/admin/schedule?saved=1", status_code=303)


@router.post("/schedule/fire-now")
async def schedule_fire_now(request: Request, _: None = Depends(_require_auth)):
    """Post a scheduled task immediately, bypassing auto_fire_enabled — this
    button is the manual override for when that safety gate is (correctly)
    left off. See docs/architecture.md section 3c."""
    form = await request.form()
    task_id = str(form.get("task_id", ""))
    task = schedule_store.get(task_id)
    if task is None:
        err = "Không tìm thấy mục này"
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(error=err))
        return RedirectResponse(url=f"/admin/schedule?error={err}", status_code=303)
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
    ))
    if result.success:
        schedule_store.mark_posted(task_id, result.message)
        if _is_htmx(request):
            return HTMLResponse(_schedule_content_html(saved=True))
        return RedirectResponse(url="/admin/schedule?saved=1", status_code=303)
    schedule_store.mark_failed(task_id, result.message)
    if _is_htmx(request):
        return HTMLResponse(_schedule_content_html(error=f"Đăng thất bại: {result.message}"))
    return RedirectResponse(url=f"/admin/schedule?error=Đăng+thất+bại:+{result.message}", status_code=303)


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
        for i, g in enumerate(groups):
            name_display = html.escape(g.name) if g.name else '<span class="muted">(chưa đặt tên)</span>'
            url_display = html.escape(g.url)
            rows.append(f"""
<tr>
  <td>{name_display}</td>
  <td class="row-url"><a href="{url_display}" target="_blank" rel="noopener">{url_display}</a></td>
  <td class="col-actions">
    <button type="button" class="btn-small btn-secondary"
            hx-get="/admin/groups/edit-modal?account_id={html.escape(account_id)}&index={i}"
            hx-target="#modal-root" hx-swap="innerHTML">Sửa</button>
    <form method="post" action="/admin/groups/delete"
          hx-post="/admin/groups/delete" hx-target="#groups-content" hx-swap="outerHTML"
          hx-confirm="Xoá nhóm này khỏi danh sách?">
      <input type="hidden" name="account_id" value="{html.escape(account_id)}">
      <input type="hidden" name="index" value="{i}">
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
    index: int | None = None,
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
    _groups_content_html()'s `oob` param."""
    is_edit = mode == "edit"
    title = "✏️ Sửa nhóm" if is_edit else "➕ Thêm nhóm mới"
    action_url = "/admin/groups/update" if is_edit else "/admin/groups/add"
    submit_label = "Lưu thay đổi" if is_edit else "Thêm vào danh sách"
    index_field = f'<input type="hidden" name="index" value="{index}">' if is_edit and index is not None else ""
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
      {index_field}
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


@router.get("/groups/edit-modal", response_class=HTMLResponse)
async def groups_edit_modal(account_id: str, index: int, _: None = Depends(_require_auth)) -> str:
    groups = get_joined_groups(account_id)
    if not (0 <= index < len(groups)):
        return _group_modal_html("edit", account_id, index=index, error="Mục không còn tồn tại — có thể đã bị xoá.")
    g = groups[index]
    return _group_modal_html("edit", account_id, index=index, name=g.name, url=g.url)


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
    groups.append(GroupRef(name=name, url=url))
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
    try:
        index = int(str(form.get("index", "")))
    except ValueError:
        if _is_htmx(request):
            return HTMLResponse(_groups_content_html(account_id, error="Mục không hợp lệ", oob=True))
        return _groups_redirect(account_id, error="Mục không hợp lệ")
    name = str(form.get("name", "")).strip()
    url = str(form.get("url", "")).strip()
    if not url:
        if _is_htmx(request):
            return HTMLResponse(_group_modal_html("edit", account_id, index=index, name=name, url=url, error="URL nhóm không được để trống"))
        return _groups_redirect(account_id, error="URL nhóm không được để trống")
    groups = get_joined_groups(account_id)
    if not (0 <= index < len(groups)):
        if _is_htmx(request):
            return HTMLResponse(_groups_content_html(account_id, error="Mục không còn tồn tại", oob=True))
        return _groups_redirect(account_id, error="Mục không còn tồn tại")
    groups[index] = GroupRef(name=name, url=url)
    save_joined_groups(account_id, groups)
    if _is_htmx(request):
        return HTMLResponse(_groups_content_html(account_id, saved=True, oob=True))
    return _groups_redirect(account_id, saved=1)


@router.post("/groups/delete")
async def groups_delete(request: Request, _: None = Depends(_require_auth)):
    form = await request.form()
    account_id = str(form.get("account_id", ""))
    try:
        index = int(str(form.get("index", "")))
    except ValueError:
        if _is_htmx(request):
            return HTMLResponse(_groups_content_html(account_id, error="Mục không hợp lệ"))
        return _groups_redirect(account_id, error="Mục không hợp lệ")
    groups = get_joined_groups(account_id)
    if 0 <= index < len(groups):
        groups.pop(index)
        save_joined_groups(account_id, groups)
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


def _reports_content_html(account_id: str | None) -> str:
    account_options = '<option value="">— Tất cả tài khoản —</option>' + "".join(
        f'<option value="{html.escape(aid)}"{" selected" if aid == account_id else ""}>{html.escape(a.display_name)} ({html.escape(aid)})</option>'
        for aid, a in get_all_accounts().items()
    )
    filter_html = f"""
<div class="account-filter">
  <label for="reports-account-select">Tài khoản</label>
  <select name="account_id" id="reports-account-select"
          hx-get="/admin/reports" hx-target="#reports-content" hx-swap="outerHTML"
          hx-trigger="change" hx-push-url="true">{account_options}</select>
</div>"""

    weekly_rows = db.weekly_post_counts(account_id=account_id)
    if weekly_rows:
        weekly_html = "".join(
            f"<tr><td>{html.escape(r['week'])}</td><td>{html.escape(r['account_id'])}</td><td>{r['total']}</td></tr>"
            for r in weekly_rows
        )
        weekly_table = f"""
<div class="table-scroll"><table class="data-table">
  <thead><tr><th>Tuần</th><th>Tài khoản</th><th>Số bài đăng thành công</th></tr></thead>
  <tbody>{weekly_html}</tbody>
</table></div>"""
    else:
        weekly_table = '<div class="empty-state">Chưa có bài đăng thành công nào được ghi nhận.</div>'

    group_rows = db.group_post_counts(account_id=account_id)
    if group_rows:
        group_html = "".join(
            f"""<tr>
  <td>{html.escape(r['account_id'])}</td>
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

    action_rows = db.action_type_counts(account_id=account_id)
    if action_rows:
        action_html = "".join(
            f"""<tr>
  <td>{html.escape(r['action'])}</td>
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

    recent_rows = db.recent_activity(limit=50, account_id=account_id)
    if recent_rows:
        recent_html = "".join(
            f"""<tr>
  <td>{html.escape(r['created_at'])}</td>
  <td>{html.escape(r['account_id'])}</td>
  <td>{html.escape(r['action'])}</td>
  <td class="row-url">{html.escape((r['target_group_name'] or r['target_url'] or '—'))}</td>
  <td>{'✅' if r['success'] else '⚠️'}</td>
  <td>{html.escape(_SOURCE_LABELS.get(r['source'], r['source']))}</td>
  <td class="muted">{html.escape((r['message'] or '')[:80])}</td>
</tr>""" for r in recent_rows
        )
        recent_table = f"""
<div class="table-scroll"><table class="data-table">
  <thead><tr><th>Thời gian (UTC)</th><th>Tài khoản</th><th>Hành động</th><th>Đích</th><th>KQ</th><th>Nguồn</th><th>Ghi chú</th></tr></thead>
  <tbody>{recent_html}</tbody>
</table></div>"""
    else:
        recent_table = '<div class="empty-state">Chưa có hoạt động nào được ghi nhận.</div>'

    return f"""<div id="reports-content">
{filter_html}

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
  <h2>🕒 Hoạt động gần đây (50 mục mới nhất)</h2>
  {recent_table}
</div>
</div>"""


@router.get("/reports", response_class=HTMLResponse)
async def reports_page(request: Request, account_id: str | None = None, _: None = Depends(_require_auth)) -> str:
    content = _reports_content_html(account_id)
    if _is_htmx(request):
        return content
    return _layout(f"""
<h1>Báo cáo</h1>
<p class="page-desc">Thống kê từ toàn bộ hành động human_bot đã thử thực hiện (thành công lẫn thất bại) — ghi tự động mỗi lần qua human_bot/agent.py's run_task(), không phân biệt đăng thủ công, từ hàng đợi, đặt lịch, hay tự động từ bộ đồng bộ bên B.</p>
{content}
""", active="reports")
