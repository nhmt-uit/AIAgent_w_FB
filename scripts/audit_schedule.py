"""Audit script (2026-09-15): kiểm tra lịch đăng/comment THẬT trong
scheduled/pending + scheduled/posted có còn tuân đúng 3 luật đã sửa hôm
nay không — không đụng Facebook, không đụng file cấu hình, chỉ ĐỌC.

Chạy: python3 -m scripts.audit_schedule [--account tu_iizuki] [--days 14]

Kiểm tra:
  1. Cap/ngày — mỗi ngày nghiệp vụ (2h sáng JST), số post/comment đã lên
     lịch cho 1 account không được vượt posts_per_day/comments_per_day.
  2. Giãn cách tối thiểu — 2 task CÙNG loại (post/comment), CÙNG account,
     liên tiếp theo giờ, phải cách nhau >= post/comment_min_delay_seconds.
  3. Chọn nhóm không dồn cục — trong cửa sổ N ngày, không nhóm nào chiếm
     quá nhiều lần đăng so với nhóm ít được đăng nhất của cùng account
     (chỉ cảnh báo, không phải luật cứng — post_to_group only).

Chỉ đọc 2 trạng thái pending + posted (đã/sắp thật sự chạy) — failed/
cancelled/missed không tính vào việc "đã chiếm slot".
"""
from __future__ import annotations

import argparse
from collections import defaultdict
from datetime import date, datetime, timedelta, timezone

from human_bot import daily_limits, schedule_store
from human_bot.config import get_all_accounts
from human_bot.data_sync import _COMMENT_ACTIONS, _POST_ACTIONS, _parse_scheduled_at


def _load_tasks(account_id: str | None) -> list[schedule_store.ScheduledTask]:
    tasks = schedule_store.list_pending() + schedule_store.list_posted()
    if account_id:
        tasks = [t for t in tasks if t.account_id == account_id]
    return tasks


def _within_window(dt: datetime, days: int) -> bool:
    now = datetime.now(timezone.utc)
    return now - timedelta(days=days) <= dt <= now + timedelta(days=days)


def audit(account_id: str | None, days: int) -> int:
    accounts = get_all_accounts()
    tasks = _load_tasks(account_id)
    violations = 0

    by_account: dict[str, list[schedule_store.ScheduledTask]] = defaultdict(list)
    for t in tasks:
        by_account[t.account_id].append(t)

    for aid, acc_tasks in sorted(by_account.items()):
        account = accounts.get(aid)
        if account is None:
            print(f"⚠️  Bỏ qua account '{aid}' — không còn trong get_all_accounts() (đã xoá?)")
            continue
        limits = account.rate_limits
        print(f"\n=== {aid} (posts_per_day={limits.posts_per_day}, "
              f"comments_per_day={limits.comments_per_day}, "
              f"post_gap={limits.post_min_delay_seconds}-{limits.post_max_delay_seconds}s, "
              f"comment_gap={limits.comment_min_delay_seconds}-{limits.comment_max_delay_seconds}s) ===")

        parsed: list[tuple[datetime, schedule_store.ScheduledTask]] = []
        for t in acc_tasks:
            dt = _parse_scheduled_at(t.scheduled_at)
            if dt is None:
                print(f"  ⚠️  task {t.task_id}: scheduled_at không parse được ({t.scheduled_at!r})")
                continue
            if _within_window(dt, days):
                parsed.append((dt, t))
        parsed.sort(key=lambda pair: pair[0])

        # --- 1. Cap/ngày ---
        day_counts: dict[tuple[date, str], int] = defaultdict(int)
        for dt, t in parsed:
            if t.action in _POST_ACTIONS:
                day_counts[(daily_limits.business_day_key(dt), "post")] += 1
            elif t.action in _COMMENT_ACTIONS:
                day_counts[(daily_limits.business_day_key(dt), "comment")] += 1
        for (day, kind), count in sorted(day_counts.items()):
            cap = limits.posts_per_day if kind == "post" else limits.comments_per_day
            status = "❌ VƯỢT" if count > cap else "✅"
            if count > cap:
                violations += 1
            print(f"  [cap/ngày] {day} — {kind}: {count}/{cap} {status}")

        # --- 2. Giãn cách tối thiểu (cùng loại, liên tiếp theo giờ) ---
        for bucket, actions, gap_min in (
            ("post", _POST_ACTIONS, limits.post_min_delay_seconds),
            ("comment", _COMMENT_ACTIONS, limits.comment_min_delay_seconds),
        ):
            same_bucket = [(dt, t) for dt, t in parsed if t.action in actions]
            for (dt1, t1), (dt2, t2) in zip(same_bucket, same_bucket[1:]):
                gap = (dt2 - dt1).total_seconds()
                if gap < gap_min:
                    violations += 1
                    print(f"  [giãn cách {bucket}] ❌ {t1.task_id} → {t2.task_id}: "
                          f"chỉ cách {gap/60:.1f} phút (cần >= {gap_min/60:.0f} phút)")

        # --- 3. Chọn nhóm không dồn cục (chỉ cảnh báo) ---
        group_counts: dict[str, int] = defaultdict(int)
        for dt, t in parsed:
            if t.action == "post_to_group" and t.target_url:
                group_counts[t.target_url] += 1
        if group_counts:
            joined = {g.url for g in account.joined_groups} if account.joined_groups else set()
            never_posted = joined - set(group_counts)
            counts = list(group_counts.values())
            max_count, min_count = max(counts), min(counts)
            print(f"  [chọn nhóm] {len(group_counts)} nhóm có bài trong cửa sổ "
                  f"{days} ngày, đăng nhiều nhất {max_count} lần, ít nhất {min_count} lần"
                  + (f" — {len(never_posted)} nhóm ĐÃ THAM GIA nhưng chưa có bài nào" if never_posted else ""))
            if max_count - min_count >= 3:
                print(f"  [chọn nhóm] ⚠️  chênh lệch {max_count - min_count} lần giữa nhóm nhiều/ít nhất "
                      f"— đáng xem lại nếu owner mong đợi phân bố đều hơn")

    print(f"\n{'='*50}\nTổng: {violations} vi phạm luật cứng (cap/ngày + giãn cách tối thiểu).")
    return violations


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--account", default=None, help="Chỉ audit 1 account_id (mặc định: tất cả)")
    parser.add_argument("--days", type=int, default=14, help="Cửa sổ xem trước/sau 'now' (ngày, mặc định 14)")
    args = parser.parse_args()
    exit_code = 1 if audit(args.account, args.days) > 0 else 0
    raise SystemExit(exit_code)
