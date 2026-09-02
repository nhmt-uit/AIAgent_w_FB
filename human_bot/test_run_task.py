"""
Manual test runner — sends one sample TaskRequest straight into
human_bot/agent.py's run_task(), without n8n or the FastAPI service in the
way. Use this to verify a single action works end-to-end before wiring up
the real HTTP service.

IMPORTANT: only meaningful once human_bot/actions.py's TODOs are filled in
with real Facebook steps (see docs/skills/facebook-custom-actions.md) —
before that, this will "succeed" without actually posting anything, since
the action functions are still empty stubs.

Run directly in your own Terminal (not through any Claude sandbox/bridge):

    python3 human_bot/test_run_task.py post_to_own_profile troy "Test status tu human_bot"
    python3 human_bot/test_run_task.py post_to_group troy "https://facebook.com/groups/xxx" "Noi dung test"
    python3 human_bot/test_run_task.py like_post troy "https://facebook.com/..."
"""
import asyncio
import sys
from pathlib import Path

from dotenv import load_dotenv

load_dotenv(Path(__file__).resolve().parent.parent / ".env")

from human_bot.agent import TaskRequest, run_task  # noqa: E402
from human_bot.browser_pool import close_all  # noqa: E402


async def main() -> None:
    if len(sys.argv) < 3:
        print(
            "Usage:\n"
            "  python3 human_bot/test_run_task.py post_to_own_profile <account_id> <content>\n"
            "  python3 human_bot/test_run_task.py post_to_group <account_id> <group_url> <content>\n"
            "  python3 human_bot/test_run_task.py comment_on_friend_post <account_id> <post_url> <content>\n"
            "  python3 human_bot/test_run_task.py comment_on_group_post <account_id> <post_url> <content>\n"
            "  python3 human_bot/test_run_task.py like_post <account_id> <post_url>\n"
        )
        sys.exit(1)

    action = sys.argv[1]
    account_id = sys.argv[2]
    rest = sys.argv[3:]

    if action == "post_to_own_profile":
        request = TaskRequest(action=action, account_id=account_id, content=rest[0])
    elif action in ("post_to_group", "comment_on_friend_post", "comment_on_group_post"):
        request = TaskRequest(action=action, account_id=account_id, target_url=rest[0], content=rest[1])
    elif action == "like_post":
        request = TaskRequest(action=action, account_id=account_id, target_url=rest[0])
    else:
        print(f"Unknown action: {action}")
        sys.exit(1)

    print(f"Running: {request}\n")
    try:
        result = await run_task(request)
        print("\n--- Result ---")
        print(result)
    finally:
        # This script is a one-off test, not the long-running service — close
        # the browser it opened so it doesn't linger as an orphaned process.
        # The real service (human_bot/service.py) keeps it open on purpose.
        await close_all()


if __name__ == "__main__":
    asyncio.run(main())
