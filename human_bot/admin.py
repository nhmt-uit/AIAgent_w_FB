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

# Actions that make sense to trigger from the admin "post content" page —
# a deliberate subset of everything in human_bot/agent.py's dispatch
# table: only actions that take free-text `content` and don't strictly
# require a target_url (group/friend-post actions need a URL the operator
# would have to paste too, which is fine but out of scope for this first
# version — see docs/research/human-behavior-simulation.md open questions).
_POSTABLE_ACTIONS = ["post_to_own_profile"]

# Human-readable label + short note shown next to each field on the config
# form — kept in sync with docs/skills/human-like-interaction.md and
# docs/research/human-behavior-simulation.md.
_TYPING_LABELS: dict[str, str] = {
    "enabled": "Bật giả lập gõ phím kiểu người (enabled)",
    "wpm": "Tốc độ gõ trung bình, đơn vị WPM (words/phút, quy ước 5 ký tự = 1 từ)",
    "char_delay_stdev_ratio": "Độ lệch ngẫu nhiên giữa các phím, tỉ lệ so với trung bình (0.35 = ±35%)",
    "min_char_delay_ms": "Khoảng cách tối thiểu giữa 2 phím (ms)",
    "word_pause_min_ms": "Ngừng thêm sau mỗi từ — tối thiểu (ms)",
    "word_pause_max_ms": "Ngừng thêm sau mỗi từ — tối đa (ms)",
    "punctuation_pause_min_ms": "Ngừng thêm sau dấu câu — tối thiểu (ms)",
    "punctuation_pause_max_ms": "Ngừng thêm sau dấu câu — tối đa (ms)",
    "typo_probability": "Xác suất gõ sai mỗi ký tự ASCII (0.03 = 3%)",
    "typo_notice_delay_min_ms": "Thời gian 'nhận ra lỗi' trước khi xoá — tối thiểu (ms)",
    "typo_notice_delay_max_ms": "Thời gian 'nhận ra lỗi' trước khi xoá — tối đa (ms)",
    "word_typo_probability": "Xác suất gõ sai cả từ có dấu tiếng Việt rồi xoá gõ lại (0.04 = 4%)",
    "fatigue_factor_per_char": "Hệ số 'mỏi tay' — chậm dần theo mỗi ký tự đã gõ",
}

_PACING_LABELS: dict[str, str] = {
    "enabled": "Bật các khoảng chờ theo ngữ cảnh (enabled)",
    "page_load_pause_min_ms": "Chờ sau khi vào trang — tối thiểu (ms)",
    "page_load_pause_max_ms": "Chờ sau khi vào trang — tối đa (ms)",
    "composer_open_pause_min_ms": "Chờ sau khi mở ô đăng bài — tối thiểu (ms)",
    "composer_open_pause_max_ms": "Chờ sau khi mở ô đăng bài — tối đa (ms)",
    "ui_step_pause_min_ms": "Chờ giữa mỗi bước trong luồng chọn (VD: chọn đối tượng) — tối thiểu (ms)",
    "ui_step_pause_max_ms": "Chờ giữa mỗi bước trong luồng chọn (VD: chọn đối tượng) — tối đa (ms)",
    "reading_wpm": "Tốc độ đọc thầm ước tính (từ/phút) — dùng để tính thời gian đọc lại trước khi Đăng",
    "reading_pause_min_ms": "Giới hạn thời gian đọc lại trước khi Đăng — tối thiểu (ms)",
    "reading_pause_max_ms": "Giới hạn thời gian đọc lại trước khi Đăng — tối đa (ms)",
    "reading_buffer_min_ms": "Khoảng đệm ngẫu nhiên cộng thêm vào thời gian đọc — tối thiểu (ms)",
    "reading_buffer_max_ms": "Khoảng đệm ngẫu nhiên cộng thêm vào thời gian đọc — tối đa (ms)",
}

_MOUSE_LABELS: dict[str, str] = {
    "enabled": "Bật di chuyển chuột kiểu đường cong trước khi click (enabled)",
    "min_steps": "Số bước di chuyển chuột tối thiểu",
    "max_steps": "Số bước di chuyển chuột tối đa",
    "step_delay_min_ms": "Độ trễ giữa mỗi bước di chuyển chuột — tối thiểu (ms)",
    "step_delay_max_ms": "Độ trễ giữa mỗi bước di chuyển chuột — tối đa (ms)",
    "curve_offset_ratio": "Độ cong của đường di chuyển, tỉ lệ theo khoảng cách (0.18 = 18%)",
    "overshoot_probability": "Xác suất di chuyển vọt quá đích rồi kéo lại (0.15 = 15%)",
    "overshoot_ratio": "Mức vọt quá đích, tỉ lệ theo khoảng cách",
    "min_distance_for_curve_px": "Khoảng cách tối thiểu (px) mới áp dụng đường cong — dưới mức này di chuyển thẳng",
}

_BOOL_FIELDS = {"enabled"}

# Each entry: (section_key used in runtime_config.json, form-field prefix,
# section title shown on the page, default-config class, editable field
# list, label dict, get_overrides fn, save_overrides fn).
_CONFIG_SECTIONS = [
    (
        "human_typing", "typing", "Gõ phím",
        HumanTypingConfig, EDITABLE_HUMAN_TYPING_FIELDS, _TYPING_LABELS,
        get_human_typing_overrides, save_human_typing_overrides,
    ),
    (
        "pacing", "pacing", "Khoảng chờ theo ngữ cảnh",
        HumanPacingConfig, EDITABLE_PACING_FIELDS, _PACING_LABELS,
        get_pacing_overrides, save_pacing_overrides,
    ),
    (
        "mouse", "mouse", "Di chuyển chuột",
        HumanMouseConfig, EDITABLE_MOUSE_FIELDS, _MOUSE_LABELS,
        get_mouse_overrides, save_mouse_overrides,
    ),
]

_PAGE_STYLE = """
<style>
  body { font-family: -apple-system, sans-serif; max-width: 860px; margin: 32px auto; padding: 0 16px; color: #1a1a1a; }
  nav a { margin-right: 16px; }
  h1 { font-size: 1.4rem; } h2 { font-size: 1.1rem; margin-top: 2rem; }
  table { border-collapse: collapse; width: 100%; }
  td, th { padding: 6px 8px; text-align: left; border-bottom: 1px solid #eee; vertical-align: top; }
  input[type=text], input[type=number], textarea, select { width: 100%; box-sizing: border-box; padding: 6px; font-size: 0.95rem; }
  textarea { min-height: 140px; font-family: inherit; }
  button { padding: 8px 16px; margin-top: 12px; cursor: pointer; }
  .muted { color: #666; font-size: 0.85rem; }
  .flash { background: #eef8ee; border: 1px solid #bfe3bf; padding: 8px 12px; border-radius: 4px; margin-bottom: 16px; }
  .error { background: #fdeeee; border: 1px solid #e3bfbf; padding: 8px 12px; border-radius: 4px; margin-bottom: 16px; }
  .queue-item { border: 1px solid #ddd; border-radius: 6px; padding: 10px; margin-bottom: 10px; }
</style>
"""


def _require_auth(credentials: HTTPBasicCredentials | None = Depends(_security)) -> None:
    """No-op (no auth) if ADMIN_USERNAME/ADMIN_PASSWORD are unset — but that
    means this page has real posting power on an unprotected route. Set
    both in .env before running this service anywhere but your own laptop."""
    expected_user = os.environ.get("ADMIN_USERNAME")
    expected_pass = os.environ.get("ADMIN_PASSWORD")
    if not expected_user or not expected_pass:
        return
    valid = (
        credentials is not None
        and secrets.compare_digest(credentials.username, expected_user)
        and secrets.compare_digest(credentials.password, expected_pass)
    )
    if not valid:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Unauthorized",
            headers={"WWW-Authenticate": "Basic"},
        )


def _layout(body: str) -> str:
    return f"""<!doctype html>
<html lang="vi"><head><meta charset="utf-8">
<title>human_bot admin</title>{_PAGE_STYLE}</head>
<body>
<nav>
  <a href="/admin">Trang chủ</a>
  <a href="/admin/config">Cấu hình hành vi</a>
  <a href="/admin/post">Đăng bài</a>
</nav>
{body}
</body></html>"""


@router.get("", response_class=HTMLResponse)
async def admin_home(_: None = Depends(_require_auth)) -> str:
    accounts = "".join(f"<li>{html.escape(a)}</li>" for a in ACCOUNTS)
    return _layout(f"""
<h1>human_bot — Bảng điều khiển</h1>
<p class="muted">Trang quản trị nội bộ. Không public trang này ra internet — nó có quyền đăng bài thật.</p>
<h2>Tài khoản đã đăng ký</h2>
<ul>{accounts}</ul>
<p><a href="/admin/config">→ Chỉnh cấu hình hành vi (gõ phím, khoảng chờ, chuột)</a> &nbsp;|&nbsp; <a href="/admin/post">→ Đăng bài / hàng đợi nội dung</a></p>
""")


# --- Config page -------------------------------------------------------

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
                input_html = (
                    f'<input type="number" step="any" name="{form_name}" '
                    f'value="{html.escape(str(value))}">'
                )
            rows.append(
                f"<tr><td>{html.escape(label)}<br>"
                f'<span class="muted">mặc định: {html.escape(str(default_val))} — key: {field_name}</span></td>'
                f"<td>{input_html}</td></tr>"
            )
        sections_html.append(f"<h2>{html.escape(title)}</h2><table>{''.join(rows)}</table>")

    flash = '<p class="flash">Đã lưu cấu hình. Áp dụng ngay từ lần đăng bài tiếp theo.</p>' if saved else ""
    return _layout(f"""
<h1>Cấu hình hành vi giống người</h1>
<p class="muted">Ghi vào runtime_config.json (không đụng tới .env), có hiệu lực ngay, không cần khởi động lại service.</p>
{flash}
<form method="post" action="/admin/config">
{''.join(sections_html)}
<button type="submit">Lưu cấu hình</button>
</form>
""")


@router.post("/config")
async def config_save(request: Request, _: None = Depends(_require_auth)) -> RedirectResponse:
    form = await request.form()
    for section_key, prefix, _title, _config_cls, editable_fields, _labels, _get_fn, save_fn in _CONFIG_SECTIONS:
        values: dict = {}
        for field_name in editable_fields:
            form_name = f"{prefix}__{field_name}"
            if field_name in _BOOL_FIELDS:
                values[field_name] = form_name in form  # checkbox present => true
                continue
            raw = form.get(form_name)
            if raw in (None, ""):
                continue
            try:
                values[field_name] = float(raw)
            except (TypeError, ValueError):
                # Ignore an unparseable value rather than 500ing the whole
                # form — the field just falls back to its previous/default
                # value, and the operator can fix it and resubmit.
                continue
        save_fn(values)
    return RedirectResponse(url="/admin/config?saved=1", status_code=303)


# --- Post-content page ---------------------------------------------------

@router.get("/post", response_class=HTMLResponse)
async def post_form(
    posted: str | None = None,
    error: str | None = None,
    _: None = Depends(_require_auth),
) -> str:
    account_options = "".join(
        f'<option value="{html.escape(a)}">{html.escape(a)}</option>' for a in ACCOUNTS
    )
    action_options = "".join(
        f'<option value="{html.escape(a)}">{html.escape(a)}</option>' for a in _POSTABLE_ACTIONS
    )
    flash = f'<p class="flash">{html.escape(posted)}</p>' if posted else ""
    err = f'<p class="error">{html.escape(error)}</p>' if error else ""

    queue_items = content_queue.list_pending()
    if queue_items:
        queue_html = "".join(f"""
<div class="queue-item">
  <div class="muted">{html.escape(item['filename'])}</div>
  <div>{html.escape(item['preview'])}</div>
  <form method="post" action="/admin/post/queue" style="display:inline">
    <input type="hidden" name="filename" value="{html.escape(item['filename'])}">
    <select name="account_id">{account_options}</select>
    <select name="action">{action_options}</select>
    <button type="submit">Đăng mục này</button>
  </form>
</div>""" for item in queue_items)
    else:
        queue_html = '<p class="muted">Hàng đợi trống. Thả file .txt vào content_queue/pending/, hoặc tải lên bên dưới.</p>'

    return _layout(f"""
<h1>Đăng bài</h1>
{flash}{err}
<h2>Đăng trực tiếp (gõ nội dung)</h2>
<form method="post" action="/admin/post/manual">
<table>
<tr><td>Tài khoản</td><td><select name="account_id">{account_options}</select></td></tr>
<tr><td>Hành động</td><td><select name="action">{action_options}</select></td></tr>
<tr><td>Nội dung</td><td><textarea name="content" required></textarea></td></tr>
</table>
<button type="submit">Đăng ngay</button>
</form>

<h2>Hàng đợi nội dung (content_queue/pending/)</h2>
{queue_html}

<h3>Tải lên một file .txt mới vào hàng đợi</h3>
<form method="post" action="/admin/post/upload" enctype="multipart/form-data">
  <input type="file" name="file" accept=".txt" required>
  <button type="submit">Thêm vào hàng đợi</button>
</form>
""")


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
        return RedirectResponse(
            url=f"/admin/post?posted=Đã đăng thành công: {result.message}", status_code=303
        )
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
        return RedirectResponse(
            url=f"/admin/post?posted=Đã đăng {filename}: {result.message}", status_code=303
        )
    content_queue.mark_failed(filename, result.message)
    return RedirectResponse(
        url=f"/admin/post?error=Đăng {filename} thất bại: {result.message}", status_code=303
    )


@router.post("/post/upload")
async def post_upload(file: UploadFile, _: None = Depends(_require_auth)) -> RedirectResponse:
    raw = await file.read()
    text = raw.decode("utf-8", errors="replace")
    saved_name = content_queue.add_pending(file.filename or "post.txt", text)
    return RedirectResponse(
        url=f"/admin/post?posted=Đã thêm vào hàng đợi: {saved_name}", status_code=303
    )
