"""
Purpose of this file / Muc dich cua file nay:
EN: Turns a raw action failure message (human_bot/agent.py's TaskResult.message
— a Playwright error dump, or one of the actions' own codes) into a short
Vietnamese cause plus the one fact the operator needs before retrying: HAS
ANYTHING ALREADY BEEN POSTED? (2026-11-01, Telegram failure tickets.)

  "safe"      — the failure KNOWN to happen before anything was submitted
                (navigation, waiting for a field/button, attaching media, or a
                refusal before the browser was even used) → retrying cannot
                double-post. Only explicitly recognised causes are "safe".
  "uncertain" — it happened AFTER the submit click (Facebook never confirmed),
                the browser died mid-action, OR the message is not recognised
                (the DEFAULT: an unknown error could just as well come after
                the click) → the post MAY be live already.
  "no"        — retrying would not help (checkpoint, wrong identity, target
                post gone, a code bug) — something else must be fixed first.

Built from the real failures in action_log (55 genuine failures, Sep–Oct
2026): 56% navigation/network, 29% element timeouts, 7% "still visible after
click". One place, with tests — the Telegram text and the buttons both read it.
VI: Chuyen thong bao loi tho thanh nguyen nhan tieng Viet + muc an toan thu lai.
"""
from __future__ import annotations

from dataclasses import dataclass

SAFE = "safe"
UNCERTAIN = "uncertain"
NO_RETRY = "no"


@dataclass(frozen=True)
class FailureInfo:
    code: str
    cause: str  # short Vietnamese cause, shown to the operator
    safety: str  # SAFE | UNCERTAIN | NO_RETRY
    repeats_likely: bool = False  # a retry tends to fail the same way (e.g. Facebook UI changed)

    @property
    def retryable(self) -> bool:
        return self.safety != NO_RETRY


# Causes that say nothing about the TARGET (the machine's network, Facebook being slow, the browser dying):
# a group that "fails" for these reasons is not a bad group.
INFRASTRUCTURE_CODES = frozenset({"network", "network_mid", "slow_load", "browser_closed", "browser_closed_mid"})


def is_infrastructure(message: str | None) -> bool:
    return classify(message).code in INFRASTRUCTURE_CODES


def technical_line(message: str, limit: int = 110) -> str:
    """First line of the raw message, trimmed — kept as a small footnote, not the headline."""
    first = (message or "").strip().splitlines()[0] if (message or "").strip() else ""
    return first if len(first) <= limit else first[:limit] + "…"


def classify(message: str | None) -> FailureInfo:
    m = message or ""
    low = m.lower()
    if any(k in m for k in ("ERR_INTERNET_DISCONNECTED", "ERR_NETWORK_CHANGED", "ERR_NAME_NOT_RESOLVED", "ERR_CONNECTION")):
        if "Page.goto" in m:  # failed while OPENING a page — nothing was done yet
            return FailureInfo("network", "Máy mất mạng khi vào Facebook", SAFE)
        return FailureInfo("network_mid", "Máy mất mạng giữa chừng — bài có thể đã đăng", UNCERTAIN)
    if m.startswith("wrong_identity"):
        return FailureInfo("wrong_identity", "Phiên đăng nhập không phải danh tính Page cần dùng", NO_RETRY)
    if m.startswith("identity_check_error"):
        return FailureInfo("identity_check", "Chưa kiểm tra được danh tính Page (lỗi thoáng qua)", SAFE)
    if m.startswith("identity_unverified"):
        return FailureInfo("identity_unverified", "Không xác nhận được đang là danh tính Page", NO_RETRY)
    if m.startswith(("anomaly_detected", "anomaly")):
        return FailureInfo("anomaly", "Facebook yêu cầu xác minh (checkpoint) — tài khoản đã bị tạm dừng", NO_RETRY)
    if "target_content_unavailable" in m:
        return FailureInfo("target_gone", "Bài đích không còn xem được (đã xoá hoặc bị ẩn)", NO_RETRY)
    if "still_visible_after_click" in m or "still_has_content_after_click" in m:
        return FailureInfo("not_confirmed", "Facebook không xác nhận sau khi bấm Đăng", UNCERTAIN)
    # Refusals BEFORE the browser was used: nothing was posted, and the retry
    # button handles the actual blocker (switch the account on / resume it).
    if m.startswith("account_paused"):
        return FailureInfo("account_paused", "Tài khoản đang tạm dừng", SAFE)
    if m.startswith("account_disabled"):
        return FailureInfo("account_disabled", "Tài khoản đang tắt", SAFE)
    if m.startswith("page_owner_off"):
        return FailureInfo("page_owner_off", "Tài khoản cá nhân sở hữu Page đang tắt", SAFE)
    if m.startswith("page_owner_missing"):
        return FailureInfo("page_owner_missing", "Page chưa gắn với tài khoản cá nhân nào", NO_RETRY)
    if "InvalidSelectorError" in m:
        return FailureInfo("code_bug", "Lỗi trong code (bộ chọn không hợp lệ) — cần sửa code", NO_RETRY)
    if "strict mode violation" in low:
        return FailureInfo("ui_changed", "Giao diện Facebook có nhiều phần tử trùng nhau", SAFE, repeats_likely=True)
    if "media_attach_failed" in m:
        return FailureInfo("media", "Không đính kèm được ảnh", SAFE)
    if "closed" in low and ("target page" in low or "browser has been closed" in low):
        if "Page.goto" in m:
            return FailureInfo("browser_closed", "Trình duyệt bị đóng khi đang mở trang", SAFE)
        return FailureInfo("browser_closed_mid", "Trình duyệt bị đóng giữa chừng — bài có thể đã đăng", UNCERTAIN)
    if "Page.goto" in m and ("Timeout" in m or "ERR_ABORTED" in m):
        return FailureInfo("slow_load", "Facebook tải quá chậm (hết thời gian chờ)", SAFE)
    # Every click goes through human_click(), which first wait_for()s the element
    # to be visible — so a Locator.wait_for timeout means that click never
    # happened, and the Post/Comment click is the last one of an action.
    if "Timeout" in m and "Locator.wait_for" in m:
        return FailureInfo("ui_timeout", "Không thấy ô/nút cần bấm (hết thời gian chờ)", SAFE, repeats_likely=True)
    # Anything else could just as well have happened AFTER the submit click.
    if m.startswith("error:"):
        return FailureInfo("unknown_error", "Lỗi không xác định — chưa rõ bài đã lên chưa", UNCERTAIN)
    return FailureInfo("other", "Lỗi khác — chưa rõ bài đã lên chưa", UNCERTAIN)
