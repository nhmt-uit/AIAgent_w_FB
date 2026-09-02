"""
Purpose of this file / Muc dich cua file nay:
EN: File-based content queue for the manual "post from a file" workflow in
the /admin web UI. Lets the operator drop a .txt file (containing the post
text) into content_queue/pending/ instead of typing content into a
terminal command — this is also what caused the shell dquote> incident on
2026-09-02, since a long Vietnamese sentence with smart quotes broke shell
quoting. Files move to content_queue/posted/ or content_queue/failed/ once
processed; nothing is ever silently deleted.
VI: Hang doi noi dung dang bai dua tren file, dung cho quy trinh "dang tu
file" thu cong trong giao dien web /admin. Nguoi van hanh chi can tha mot
file .txt (chua noi dung bai dang) vao content_queue/pending/ thay vi go
truc tiep vao lenh terminal — day cung la nguyen nhan gay loi shell
dquote> ngay 2026-09-02, vi mot cau tieng Viet dai co dau ngoac kieu chu
lam hong cu phap terminal. File se duoc chuyen sang content_queue/posted/
hoac content_queue/failed/ sau khi xu ly xong; khong file nao bi xoa am
tham.
"""
from datetime import datetime, timezone
from pathlib import Path

QUEUE_ROOT = Path(__file__).resolve().parent.parent / "content_queue"
PENDING_DIR = QUEUE_ROOT / "pending"
POSTED_DIR = QUEUE_ROOT / "posted"
FAILED_DIR = QUEUE_ROOT / "failed"


def ensure_dirs() -> None:
    for d in (PENDING_DIR, POSTED_DIR, FAILED_DIR):
        d.mkdir(parents=True, exist_ok=True)


def _safe_pending_path(filename: str) -> Path:
    """Resolve `filename` strictly inside PENDING_DIR — strips any path
    components an admin-page caller might (accidentally or not) supply, so
    this can never be tricked into reading/moving a file outside the
    queue directory."""
    ensure_dirs()
    safe_name = Path(filename).name
    return PENDING_DIR / safe_name


def list_pending() -> list[dict]:
    """Pending items, oldest first (by filename, which we expect to sort
    chronologically if named with a date/time prefix — otherwise just
    alphabetical, which is still a stable, predictable order)."""
    ensure_dirs()
    items = []
    for path in sorted(PENDING_DIR.glob("*.txt")):
        try:
            text = path.read_text(encoding="utf-8")
        except OSError:
            text = ""
        items.append({
            "filename": path.name,
            "content": text,
            "preview": (text[:120] + "…") if len(text) > 120 else text,
        })
    return items


def read_pending(filename: str) -> str:
    path = _safe_pending_path(filename)
    if not path.is_file():
        raise FileNotFoundError(filename)
    return path.read_text(encoding="utf-8")


def add_pending(filename: str, content: str) -> str:
    """Save `content` as a new pending item. Returns the actual filename
    used (a UTC timestamp prefix is added so uploads never collide)."""
    ensure_dirs()
    safe_name = Path(filename).name or "post.txt"
    if not safe_name.endswith(".txt"):
        safe_name += ".txt"
    stamped_name = f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%SZ')}_{safe_name}"
    (PENDING_DIR / stamped_name).write_text(content, encoding="utf-8")
    return stamped_name


def mark_posted(filename: str) -> None:
    _move_to(filename, POSTED_DIR)


def mark_failed(filename: str, reason: str) -> None:
    dest = _move_to(filename, FAILED_DIR)
    if dest is not None:
        dest.with_suffix(".reason.txt").write_text(reason, encoding="utf-8")


def _move_to(filename: str, target_dir: Path) -> Path | None:
    ensure_dirs()
    src = _safe_pending_path(filename)
    if not src.is_file():
        return None
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    dest = target_dir / f"{stamp}_{src.name}"
    src.rename(dest)
    return dest
