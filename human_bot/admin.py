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
"""
import html
import os
import secrets

from fastapi import APIRouter, Depends, HTTPException, Request, UploadFile, status
from fastapi.responses import HTMLResponse, RedirectResponse
from fastapi.security import HTTPBasic, HTTPBasicCredentials

from human_bot import content_queue
from human_bot.agent import TaskRequest, run_task
from human_bot.config import ACCOUNTS
from human_bot.humanize import HumanMouseConfig, HumanPacingConfig, HumanTypingConfig
from human_bot.runtime_config import (
    EDITABLE_HUMAN_TYPING_FIELDS,
    EDITABLE_PACING_FIELDS,
    EDITABLE_MOUSE_FIELDS,
    get_human_typing_overrides,
    get_pacing_overrides,
    get_mouse_overrides,
    save_human_typing_overrides,
    save_pacing_overrides,
    save_mouse_overrides,
)

router = APIRouter(prefix="/admin", tags=["admin"])
_security = HTTPBasic(auto_error=False)

_POSTABLE_ACTIONS = ["post_to_own_profile"]

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

_BOOL_FIELDS = {"enabled"}

_CONFIG_SECTIONS = [
    ("human_typing", "typing", "Gõ phím", HumanTypingConfig, EDITABLE_HUMAN_TYPING_FIELDS, _TYPING_LABELS,
     get_human_typing_overrides, save_human_typing_overrides),
    ("pacing", "pacing", "Khoảng chờ theo ngữ cảnh", HumanPacingConfig, EDITABLE_PACING_FIELDS, _PACING_LABELS,
     get_pacing_overrides, save_pacing_overrides),
    ("mouse", "mouse", "Di chuyển chuột", HumanMouseConfig, EDITABLE_MOUSE_FIELDS, _MOUSE_LABELS,
     get_mouse_overrides, save_mouse_overrides),
]

_PAGE_STYLE = """
<style>
  :root {
    --bg: #f4f5f7;
    --surface: #ffffff;
    --border: #e4e7ec;
    --text: #1a1d23;
    --text-muted: #6b7280;
    --primary: #4f46e5;
    --primary-hover: #4338ca;
    --primary-soft: #eef2ff;
    --success-bg: #ecfdf3;
    --success-border: #abefc6;
    --success-text: #087443;
    --error-bg: #fef3f2;
    --error-border: #fda29b;
    --error-text: #b42318;
    --radius: 10px;
    --shadow: 0 1px 2px rgba(16, 24, 40, 0.05);
  }
  * { box-sizing: border-box; }
  body {
    font-family: -apple-system, BlinkMacSystemFont, "Segoe UI", Roboto, sans-serif;
    background: var(--bg);
    color: var(--text);
    margin: 0;
    padding: 0;
    line-height: 1.5;
  }
  a { color: var(--primary); text-decoration: none; }
  a:hover { text-decoration: underline; }

  .topbar {
    background: var(--surface);
    border-bottom: 1px solid var(--border);
    padding: 0 24px;
    position: sticky;
    top: 0;
    z-index: 10;
  }
  .topbar-inner {
    max-width: 960px;
    margin: 0 auto;
    display: flex;
    align-items: center;
    gap: 28px;
    height: 56px;
  }
  .brand { font-weight: 700; font-size: 1rem; letter-spacing: -0.01em; display: flex; align-items: center; gap: 8px; }
  .brand-dot { width: 9px; height: 9px; border-radius: 50%; background: var(--primary); display: inline-block; }
  nav.topnav { display: flex; gap: 4px; }
  nav.topnav a {
    color: var(--text-muted);
    font-size: 0.9rem;
    font-weight: 500;
    padding: 6px 12px;
    border-radius: 6px;
  }
  nav.topnav a:hover { background: var(--primary-soft); color: var(--primary); text-decoration: none; }
  nav.topnav a.active { background: var(--primary-soft); color: var(--primary); }

  main {
    max-width: 960px;
    margin: 0 auto;
    padding: 32px 24px 64px;
  }

  h1 { font-size: 1.5rem; margin: 0 0 6px; letter-spacing: -0.01em; }
  h2 { font-size: 1.05rem; margin: 0 0 14px; display: flex; align-items: center; gap: 8px; }
  .page-desc { color: var(--text-muted); font-size: 0.92rem; margin: 0 0 24px; }

  .card {
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    box-shadow: var(--shadow);
    padding: 20px 22px;
    margin-bottom: 20px;
  }

  .field-grid {
    display: grid;
    grid-template-columns: 1fr;
    gap: 14px;
  }
  .field-row {
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 20px;
    padding: 10px 0;
    border-bottom: 1px solid var(--border);
  }
  .field-row:last-child { border-bottom: none; padding-bottom: 0; }
  .field-label { flex: 1; font-size: 0.88rem; }
  .field-key { color: var(--text-muted); font-size: 0.76rem; margin-top: 2px; }
  .field-input { width: 150px; flex-shrink: 0; }

  input[type=text], input[type=number], textarea, select {
    width: 100%;
    box-sizing: border-box;
    padding: 8px 10px;
    font-size: 0.9rem;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: var(--surface);
    color: var(--text);
    font-family: inherit;
  }
  input[type=text]:focus, input[type=number]:focus, textarea:focus, select:focus {
    outline: none;
    border-color: var(--primary);
    box-shadow: 0 0 0 3px var(--primary-soft);
  }
  input[type=checkbox] { width: 18px; height: 18px; accent-color: var(--primary); cursor: pointer; }
  textarea { min-height: 160px; resize: vertical; }

  button, .btn {
    padding: 9px 18px;
    font-size: 0.9rem;
    font-weight: 600;
    border: none;
    border-radius: 7px;
    background: var(--primary);
    color: #fff;
    cursor: pointer;
    transition: background 0.15s ease;
  }
  button:hover, .btn:hover { background: var(--primary-hover); text-decoration: none; }
  button.btn-secondary {
    background: var(--surface);
    color: var(--text);
    border: 1px solid var(--border);
  }
  button.btn-secondary:hover { background: var(--bg); }
  .btn-small { padding: 6px 12px; font-size: 0.82rem; }

  .muted { color: var(--text-muted); font-size: 0.85rem; }

  .flash, .error {
    border-radius: var(--radius);
    padding: 12px 16px;
    margin-bottom: 20px;
    font-size: 0.88rem;
    display: flex;
    align-items: center;
    gap: 8px;
  }
  .flash { background: var(--success-bg); border: 1px solid var(--success-border); color: var(--success-text); }
  .error { background: var(--error-bg); border: 1px solid var(--error-border); color: var(--error-text); }

  .form-actions { margin-top: 8px; display: flex; justify-content: flex-end; }

  .badge {
    display: inline-block;
    font-size: 0.72rem;
    font-weight: 600;
    padding: 2px 9px;
    border-radius: 999px;
    background: var(--primary-soft);
    color: var(--primary);
  }

  .account-list { list-style: none; padding: 0; margin: 0; display: flex; flex-wrap: wrap; gap: 8px; }
  .account-list li {
    background: var(--primary-soft);
    color: var(--primary);
    font-size: 0.85rem;
    font-weight: 600;
    padding: 6px 12px;
    border-radius: 999px;
  }

  .home-links { display: grid; grid-template-columns: 1fr 1fr; gap: 16px; margin-top: 8px; }
  .home-link-card {
    display: block;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 18px 20px;
    box-shadow: var(--shadow);
  }
  .home-link-card:hover { border-color: var(--primary); text-decoration: none; }
  .home-link-card .title { font-weight: 700; font-size: 0.95rem; color: var(--text); margin-bottom: 4px; }
  .home-link-card .desc { color: var(--text-muted); font-size: 0.83rem; }

  .queue-item {
    border: 1px solid var(--border);
    border-radius: var(--radius);
    padding: 14px 16px;
    margin-bottom: 12px;
    background: var(--surface);
  }
  .queue-item .queue-filename { font-size: 0.78rem; color: var(--text-muted); margin-bottom: 6px; }
  .queue-item .queue-preview { font-size: 0.9rem; margin-bottom: 10px; white-space: pre-wrap; }
  .queue-item form { display: flex; gap: 8px; align-items: center; flex-wrap: wrap; }
  .queue-item select { width: auto; min-width: 140px; }

  .empty-state {
    text-align: center;
    color: var(--text-muted);
    padding: 28px 16px;
    font-size: 0.88rem;
    border: 1px dashed var(--border);
    border-radius: var(--radius);
  }

  .section-divider { margin: 32px 0 18px; font-size: 0.78rem; text-transform: uppercase; letter-spacing: 0.04em; color: var(--text-muted); font-weight: 700; }

  /* Custom select — styled trigger + dropdown panel that opens below it,
     backed by a real <select> (kept in the DOM, visually hidden) so form
     submission and the existing name="..." fields need no changes. */
  .cselect { position: relative; }
  .cselect select.cselect-native { display: none; }
  .cselect-trigger {
    width: 100%;
    display: flex;
    align-items: center;
    justify-content: space-between;
    gap: 8px;
    padding: 8px 10px;
    border: 1px solid var(--border);
    border-radius: 7px;
    background: var(--surface);
    color: var(--text);
    font-size: 0.9rem;
    font-family: inherit;
    cursor: pointer;
  }
  .cselect-trigger:hover { border-color: var(--primary); }
  .cselect-trigger.open { border-color: var(--primary); box-shadow: 0 0 0 3px var(--primary-soft); }
  .cselect-trigger .chevron { color: var(--text-muted); font-size: 0.7rem; transition: transform 0.15s ease; flex-shrink: 0; }
  .cselect-trigger.open .chevron { transform: rotate(180deg); }
  .cselect-panel {
    position: absolute;
    top: calc(100% + 6px);
    left: 0;
    right: 0;
    background: var(--surface);
    border: 1px solid var(--border);
    border-radius: 9px;
    box-shadow: 0 10px 28px rgba(16, 24, 40, 0.14);
    padding: 6px;
    max-height: 240px;
    overflow-y: auto;
    z-index: 50;
    display: none;
  }
  .cselect-panel.open { display: block; }
  .cselect-option {
    padding: 8px 10px;
    border-radius: 6px;
    font-size: 0.88rem;
    cursor: pointer;
  }
  .cselect-option:hover { background: var(--primary-soft); color: var(--primary); }
  .cselect-option.selected { background: var(--primary-soft); color: var(--primary); font-weight: 600; }
  .queue-item .cselect { min-width: 150px; }

  @media (max-width: 640px) {
    .home-links { grid-template-columns: 1fr; }
    .field-row { flex-direction: column; align-items: stretch; }
    .field-input { width: 100%; }
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
<div class="topbar">
  <div class="topbar-inner">
    <div class="brand"><span class="brand-dot"></span> human_bot</div>
    <nav class="topnav">
      <a href="/admin" class="{nav_class('home')}">Trang chủ</a>
      <a href="/admin/config" class="{nav_class('config')}">Cấu hình hành vi</a>
      <a href="/admin/post" class="{nav_class('post')}">Đăng bài</a>
    </nav>
  </div>
</div>
<main>
{body}
</main>
</body></html>"""


@router.get("", response_class=HTMLResponse)
async def admin_home(_: None = Depends(_require_auth)) -> str:
    accounts = "".join(f"<li>{html.escape(a)}</li>" for a in ACCOUNTS) or '<span class="muted">Chưa có tài khoản nào</span>'
    return _layout(f"""
<h1>Bảng điều khiển</h1>
<p class="page-desc">Trang quản trị nội bộ. Không public trang này ra internet — nó có quyền đăng bài thật lên Facebook.</p>

<div class="card">
  <h2>👤 Tài khoản đã đăng ký <span class="badge">{len(ACCOUNTS)}</span></h2>
  <ul class="account-list">{accounts}</ul>
</div>

<div class="home-links">
  <a class="home-link-card" href="/admin/config">
    <div class="title">⚙️ Cấu hình hành vi</div>
    <div class="desc">Chỉnh tốc độ gõ, khoảng chờ, di chuyển chuột — áp dụng ngay, không cần khởi động lại.</div>
  </a>
  <a class="home-link-card" href="/admin/post">
    <div class="title">📝 Đăng bài</div>
    <div class="desc">Đăng trực tiếp hoặc quản lý hàng đợi nội dung (content_queue).</div>
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


@router.get("/post", response_class=HTMLResponse)
async def post_form(posted: str | None = None, error: str | None = None, _: None = Depends(_require_auth)) -> str:
    account_ids = list(ACCOUNTS)
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
    <div class="field-row"><div class="field-label">Tài khoản</div><div class="field-input">{_custom_select("account_id", account_ids)}</div></div>
    <div class="field-row"><div class="field-label">Hành động</div><div class="field-input">{_custom_select("action", _POSTABLE_ACTIONS)}</div></div>
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
    if not content.strip():
        return RedirectResponse(url="/admin/post?error=Nội+dung+trống", status_code=303)
    result = await run_task(TaskRequest(action=action, account_id=account_id, content=content))
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
    result = await run_task(TaskRequest(action=action, account_id=account_id, content=content))
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
