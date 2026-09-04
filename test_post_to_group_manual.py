"""
One-off manual test for post_to_group — now also exercising the
media-attach step (2026-09-04): media_path is left unset below on
purpose, so run_task() auto-picks a random image from media/memes/
per the "Ảnh đính kèm" toggle in /admin/config (default: on) — same
as any real post would get.

Purpose / Mục đích:
EN: Runs post_to_group through the FULL human_bot pipeline
(human_bot/agent.py's run_task() — rate limiting, safety check, and
DB logging into human_bot.db's action_log), not a raw standalone
Codegen script. This is what actually exercises the tier-1->2->3->4
fallback chain and the id-based group matching just merged into
human_bot/actions.py.

Run this yourself in your own terminal (NOT via the cloud session's
device_bash) — it needs a real Chromium browser, the same one your
Codegen recordings use. The cloud session's Linux VM has no browser
installed and no network access to download one.

VI: Chạy post_to_group qua ĐÚNG luồng thật của human_bot
(run_task() trong human_bot/agent.py — có rate limit, safety check,
và ghi log vào action_log trong human_bot.db), không phải script
Codegen độc lập. Đây mới là thứ thật sự chạy qua chuỗi fallback
4 lớp và cách khớp nhóm theo ID vừa merge vào human_bot/actions.py.

Tự chạy file này trên terminal của bạn (KHÔNG chạy qua device_bash
của phiên cloud) — vì cần trình duyệt Chromium thật, giống lúc ghi
Codegen. VM Linux của phiên cloud không có trình duyệt và không có
mạng để tải về.

Usage:
    cd /path/to/AIAgent_w_FB
    python3 test_post_to_group_manual.py

    # To watch it happen visually instead of headless:
    HEADLESS=false python3 test_post_to_group_manual.py
"""
import asyncio

from human_bot.agent import TaskRequest, run_task


async def main() -> None:
    request = TaskRequest(
        action="post_to_group",
        account_id="tu_iizuki",
        target_url="https://www.facebook.com/groups/1383875949915495/",
        content=(
            "Công ty mình đang tuyển thêm thành viên mới, "
            "nội dung công việc các bạn đọc kĩ bên dưới nha. Welcome cả nhà!"
        ),
        source="manual",
    )
    result = await run_task(request)
    print("success:", result.success)
    print("message:", result.message)
    print("timestamp:", result.timestamp)


if __name__ == "__main__":
    asyncio.run(main())
