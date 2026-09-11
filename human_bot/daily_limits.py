"""
Kiem tra gioi han posts_per_day/comments_per_day theo "ngay nghiep vu"
(2h sang JST hom nay -> 2h sang JST hom sau) thay vi cua so truot 24h.

EN: The daily-count half of what human_bot/safety.py's RateLimiter.
can_proceed() used to decide (posts_per_day/comments_per_day) — moved
here 2026-09-11, project owner's decision, after a real investigation
found the rolling-24h window that can_proceed() enforces doesn't match
the calendar-day bookkeeping human_bot/data_sync.py's scheduler reasons
about: a backlog fired in a burst (e.g. while auto_fire_enabled was off
for a while) could land several calendar days' worth of scheduled
activity inside the same rolling window, blocking things the scheduler
thought were fine. See the conversation that requested this for the full
back-and-forth (a watermark, then a rolling-window-simulation, were both
considered and rejected as more complex than this for no real benefit).

Reset boundary is 2:00 AM JST — not midnight — specifically because that
sits INSIDE the quiet-hours dead zone (DataSyncConfig.quiet_hour_start_local/
quiet_hour_end_local, default 2-6 AM JST, where nothing is ever scheduled)
rather than during active hours. A midnight (or any active-hours) reset
would be exploitable — post right up to the boundary, then again right
after — exactly the "burst around a fixed reset point" pattern a rolling
window exists to prevent in the first place. Resetting inside a window
where posting is already impossible, combined with the existing
multi-hour randomized gap between any two same-type actions (RateLimits.
post_min/max_delay_seconds, comment_min/max_delay_seconds — see
safety.py's RateLimiter.record()), makes that specific exploit
impossible here: an account physically cannot have fired 7 comments in
the hour before 2 AM AND 7 more right after 6 AM, because the gap alone
already spaces same-type actions hours apart.

VI: Nua giua "so luong" cua nhung gi safety.py's RateLimiter.can_proceed()
truoc day tu quyet dinh (posts_per_day/comments_per_day) — doi sang day
2026-09-11 theo quyet dinh chu du an, sau khi dieu tra thuc te phat hien
cua so truot 24h ma can_proceed() dung khong khop voi cach tinh theo
ngay duong lich cua bo len lich (human_bot/data_sync.py) — mot dot bai
dang don ve don cuc (VD trong luc auto_fire_enabled dang tat) co the
khien hoat dong cua nhieu ngay duong lich khac nhau roi vao chung 1 cua
so truot 24h khi cuoi cung duoc dang that, gay chan nham nhung gi lich
tuong da on.

Chi doi phan dem theo NGAY (posts_per_day/comments_per_day) — gioi han
theo GIO (comments_per_hour/likes_per_hour) va khoang nghi toi thieu
giua 2 hanh dong (min_delay_seconds/max_delay_seconds, qua
RateLimiter.gap_ok()/record()) GIU NGUYEN, van di qua safety.py nhu cu,
khong lien quan toi thay doi nay.

human_bot/safety.py van giu nguyen KHONG XOA (RateLimiter.can_proceed(),
rate_limit_hard_cap_message() — ca 2 deu con nguyen trong file, chi
khong con duoc goi o dau nua, xem docstring cua tung ham do) — de doc
lai hoac quay ve neu can, khong phai vi con dung.
"""
from __future__ import annotations

import json
from datetime import date, datetime, timedelta, timezone

from human_bot.config import AccountConfig
from human_bot.safety import RateLimiter, is_gap_reason

_JST_OFFSET = timedelta(hours=9)
# Phai khop dung DataSyncConfig.quiet_hour_start_local's mac dinh (2.0) —
# day khong doc gia tri do truc tiep (tranh vong lap import voi
# data_sync.py, module do da import tu day_limits ve sau) nen ghi co
# dinh tai day; neu sau nay quiet_hour_start_local doi khac 2h, sua ca 2
# noi cho khop.
_BUSINESS_DAY_START_HOUR_JST = 2


def _business_day_start(now_utc: datetime) -> datetime:
    """Moc UTC cua lan 2:00 sang JST gan nhat, TRUOC HOAC BANG `now_utc`."""
    jst_now = now_utc + _JST_OFFSET
    boundary_jst = jst_now.replace(
        hour=_BUSINESS_DAY_START_HOUR_JST, minute=0, second=0, microsecond=0
    )
    if boundary_jst > jst_now:
        boundary_jst -= timedelta(days=1)
    return boundary_jst - _JST_OFFSET


def business_day_start(now_utc: datetime) -> datetime:
    """Public wrapper around _business_day_start() (2026-09-11) — mốc UTC
    của lần 2h sáng JST gần nhất, trước hoặc bằng `now_utc`. Dùng cho
    human_bot/data_sync.py's scheduler khi cần TỰ nhảy sang "ngày nghiệp
    vụ kế tiếp" (mang lại cơ chế tràn-ngày, giờ an toàn để làm lại vì
    lớp lên lịch và lớp enforcement (can_proceed() ở trên) cùng thống
    nhất định nghĩa "1 ngày" — không còn lệch pha như hồi còn dùng cửa
    sổ trượt 24h, nên khoá 1 job vào "ngày nghiệp vụ mai" không còn rủi
    ro đảo thứ tự/đói slot đã phân tích kỹ trong cuộc trao đổi trước đó."""
    return _business_day_start(now_utc)


def business_day_key(dt_utc: datetime) -> date:
    """Ngày dương lịch JST của mốc bắt đầu "ngày nghiệp vụ" mà `dt_utc`
    (UTC) rơi vào — dùng làm KEY để nhóm các task/hoạt động theo đúng
    "ngày nghiệp vụ" (không phải ngày dương lịch UTC thô như
    data_sync.py's _utc_today() cũ) — mọi mốc thời gian từ 2h sáng JST
    ngày X tới 1h59 JST ngày X+1 đều trả về cùng 1 key (ngày X)."""
    return (business_day_start(dt_utc) + _JST_OFFSET).date()


def count_since_business_day_start(account: AccountConfig, action_type: str) -> int:
    """So lan `action_type` DA THUC SU chay (thanh cong lan that bai —
    cung quy uoc voi RateLimiter.recent_count(), khong loc theo success)
    ke tu moc 2h sang JST gan nhat. Doc thang tu cung file log
    RateLimiter dang dung (account.action_log_path) — khong tao nguon du
    lieu moi."""
    since = _business_day_start(datetime.now(timezone.utc))
    path = account.action_log_path
    if not path.exists():
        return 0
    count = 0
    with path.open() as f:
        for line in f:
            try:
                row = json.loads(line)
            except ValueError:
                continue
            if row.get("action") != action_type:
                continue
            try:
                ts = datetime.fromisoformat(row["timestamp"])
            except (KeyError, ValueError):
                continue
            if ts.tzinfo is None:
                ts = ts.replace(tzinfo=timezone.utc)
            if ts >= since:
                count += 1
    return count


def can_proceed(account: AccountConfig, action_type: str, ignore_gap: bool = False) -> tuple[bool, str]:
    """Thay the truc tiep cho safety.py's RateLimiter.can_proceed() — cung
    chu ky, cung y nghia tra ve (allowed, reason) — chi khac o cho
    posts_per_day/comments_per_day dem theo NGAY NGHIEP VU thay vi cua so
    truot 24h. Phan gap (min_delay_seconds) va gioi han theo GIO
    (comments_per_hour/likes_per_hour) tai su dung nguyen RateLimiter,
    khong doi gi."""
    limiter = RateLimiter(account)
    if not ignore_gap:
        gap_ok, gap_reason = limiter.gap_ok(action_type)
        if not gap_ok:
            return False, gap_reason
    limits = account.rate_limits
    if action_type == "post":
        count = count_since_business_day_start(account, "post")
        if count >= limits.posts_per_day:
            return False, "posts_per_day limit reached"
    elif action_type == "comment":
        hourly = limiter.recent_count("comment", timedelta(hours=1))
        if hourly >= limits.comments_per_hour:
            return False, "comments_per_hour limit reached"
        daily = count_since_business_day_start(account, "comment")
        if daily >= limits.comments_per_day:
            return False, "comments_per_day limit reached"
    elif action_type == "like":
        hourly = limiter.recent_count("like", timedelta(hours=1))
        if hourly >= limits.likes_per_hour:
            return False, "likes_per_hour limit reached"
    return True, "ok"


def hard_cap_message(account: AccountConfig, action_type: str) -> str | None:
    """Thay the safety.py's rate_limit_hard_cap_message() — cung noi
    dung/y nghia, chi doi nguon can_proceed() sang ham o file nay. Tra
    None neu tai khoan khong bi chan, hoac chi bi chan boi soft gap (xem
    is_gap_reason() — truong hop do van la viec cua
    safety.rate_limit_wait_message(), khong doi)."""
    allowed, reason = can_proceed(account, action_type)
    if allowed or is_gap_reason(reason):
        return None
    label = {"post": "bài đăng", "comment": "comment", "like": "lượt thích"}.get(action_type, action_type)
    return (
        f"⛔ Tài khoản này đã đạt giới hạn số lượng {label} tối đa (theo giờ hoặc theo ngày) — "
        f"KHÔNG phải lỗi tạm thời, sẽ còn bị chặn cho tới khi hoạt động cũ đủ 24h/1h trôi qua "
        f"hoặc sang ngày nghiệp vụ mới (2h sáng giờ Nhật). "
        f"Gợi ý: dời lịch bài này sang một thời điểm khác (VD ngày mai) ở trang Lịch đăng, "
        f"hoặc huỷ nếu không còn cần thiết."
    )
