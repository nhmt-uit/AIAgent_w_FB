"""
One-off manual test: does _attach_media actually attach an image when
posting to OWN PROFILE (composer scoped to a real [role=dialog], unlike
post_to_group's unscoped page-wide search) — isolating whether the
"posted successfully but no image showed up" report from post_to_group
is a scoping bug specific to that function.

Run in your own terminal (needs a real Chromium browser):
    cd /path/to/AIAgent_w_FB
    HEADLESS=false python3 test_post_own_profile_media.py
"""
import asyncio

from human_bot.agent import TaskRequest, run_task


async def main() -> None:
    request = TaskRequest(
        action="post_to_own_profile",
        account_id="tu_iizuki",
        content="[Test đính kèm ảnh - đăng tường cá nhân]",
        source="manual",
    )
    result = await run_task(request)
    print("success:", result.success)
    print("message:", result.message)
    print("timestamp:", result.timestamp)


if __name__ == "__main__":
    asyncio.run(main())
