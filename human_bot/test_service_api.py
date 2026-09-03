"""
Manual test client for human_bot/service.py's HTTP layer — the FastAPI
service itself, not the action logic (human_bot/test_run_task.py already
covers that by calling run_task() directly). Use this to confirm the
*service* works the way any external caller (n8n, or another team's
service — see docs/architecture.md and the "who can call /tasks" note in
service.py) will actually use it: real HTTP requests over the network,
JSON in, JSON out.

Uses only the Python standard library (urllib) on purpose — no `requests`
dependency needed just for a manual smoke test.

IMPORTANT — run the service first, in a separate Terminal tab:

    uvicorn human_bot.service:app --host 127.0.0.1 --port 8000

Then, in a second Terminal tab, run this script (also directly in your own
Terminal, not through any Claude sandbox/bridge — it needs to reach
127.0.0.1:8000 on this machine):

    # 1) Safe first check — no Facebook interaction, just confirms the
    #    service started, pre-warmed its accounts, and /health responds:
    python3 human_bot/test_service_api.py health

    # 2) Safe error-path check — confirms /tasks round-trips JSON and
    #    handles a bad request correctly, still no Facebook interaction:
    python3 human_bot/test_service_api.py bad-task

    # 3) Real task — THIS ACTUALLY POSTS ON FACEBOOK if the action is
    #    implemented (only post_to_own_profile is, as of 2026-09-03):
    python3 human_bot/test_service_api.py task post_to_own_profile tu_iizuki "Noi dung test"
"""
import json
import sys
import urllib.error
import urllib.request

BASE_URL = "http://127.0.0.1:8000"

# A /tasks call that actually posts is slow ON PURPOSE (see
# human_bot/humanize.py) — the whole point is pacing that looks human, not
# a fast API. Fixed timeouts break on longer content because typing time
# scales with character count, so this estimates a generous ceiling instead
# of guessing one flat number. Any real caller of /tasks (n8n, another
# team's service — see the "who can call /tasks" note in service.py) needs
# the same generous, content-aware timeout on their side, not a typical
# API's few-seconds default.
_FIXED_PACING_OVERHEAD_S = (
    10  # page_load_pause, worst case (see HumanPacingConfig defaults)
    + 5  # composer_open_pause, worst case
    + 3 * 3  # 3x pause_between_ui_steps, worst case each
    + 20  # reading_pause, worst case (capped regardless of content length)
    + 2  # final wait_for_timeout after clicking Post
)
_MS_PER_CHAR_WORST_CASE = 400  # generous per-character typing estimate, incl. occasional word-retype
_SAFETY_BUFFER_S = 15  # network latency, browser/page slack, etc.


def _estimate_timeout_seconds(content: str | None) -> float:
    typing_s = (len(content) * _MS_PER_CHAR_WORST_CASE / 1000) if content else 0
    return _FIXED_PACING_OVERHEAD_S + typing_s + _SAFETY_BUFFER_S


def _request(method: str, path: str, body: dict | None = None, timeout: float = 30) -> tuple[int, dict]:
    data = json.dumps(body).encode("utf-8") if body is not None else None
    req = urllib.request.Request(
        f"{BASE_URL}{path}",
        data=data,
        method=method,
        headers={"Content-Type": "application/json"} if data else {},
    )
    try:
        with urllib.request.urlopen(req, timeout=timeout) as resp:
            return resp.status, json.loads(resp.read().decode("utf-8"))
    except urllib.error.HTTPError as e:
        return e.code, json.loads(e.read().decode("utf-8"))
    except TimeoutError:
        print(
            f"Client gave up waiting after {timeout:.0f}s — this does NOT mean the task failed:\n"
            "the service has no timeout of its own and keeps running the action in the\n"
            "background. Check accounts/<account_id>/action_log.jsonl or Facebook itself to\n"
            "see whether it actually completed."
        )
        sys.exit(1)
    except urllib.error.URLError as e:
        print(
            f"Could not reach {BASE_URL} — is the service running?\n"
            f"  uvicorn human_bot.service:app --host 127.0.0.1 --port 8000\n"
            f"Underlying error: {e}"
        )
        sys.exit(1)


def cmd_health() -> None:
    status, body = _request("GET", "/health")
    print(f"GET /health -> {status}")
    print(json.dumps(body, indent=2, ensure_ascii=False))


def cmd_bad_task() -> None:
    # Deliberately unimplemented action — should come back as a clean
    # success=False TaskResult, never a 500 or an unhandled crash. This
    # is what an unexpected/malformed request from another team's service
    # should also degrade to, not a stack trace. Fails fast (short timeout)
    # since an invalid action never reaches the slow human-pacing code.
    status, body = _request(
        "POST",
        "/tasks",
        {"action": "not_a_real_action", "account_id": "tu_iizuki", "content": "test"},
        timeout=30,
    )
    print(f"POST /tasks (intentionally invalid action) -> {status}")
    print(json.dumps(body, indent=2, ensure_ascii=False))


def cmd_task(argv: list[str]) -> None:
    if len(argv) < 2:
        print(
            "Usage: python3 human_bot/test_service_api.py task <action> <account_id> [content_or_url ...]\n"
            "  python3 human_bot/test_service_api.py task post_to_own_profile tu_iizuki \"Noi dung test\""
        )
        sys.exit(1)
    action, account_id, *rest = argv
    task_body: dict = {"action": action, "account_id": account_id}
    if action == "post_to_own_profile" and rest:
        task_body["content"] = rest[0]
    elif action in ("post_to_group", "comment_on_friend_post", "comment_on_group_post") and len(rest) >= 2:
        task_body["target_url"] = rest[0]
        task_body["content"] = rest[1]
    elif action == "like_post" and rest:
        task_body["target_url"] = rest[0]

    timeout = _estimate_timeout_seconds(task_body.get("content"))
    print(f"POST /tasks -> {json.dumps(task_body, ensure_ascii=False)}")
    print(f"(waiting up to ~{timeout:.0f}s — real posting is deliberately slow, see human_bot/humanize.py)\n")
    status, body = _request("POST", "/tasks", task_body, timeout=timeout)
    print(f"Response: {status}")
    print(json.dumps(body, indent=2, ensure_ascii=False))


def main() -> None:
    if len(sys.argv) < 2:
        print(__doc__)
        sys.exit(1)
    command, rest = sys.argv[1], sys.argv[2:]
    if command == "health":
        cmd_health()
    elif command == "bad-task":
        cmd_bad_task()
    elif command == "task":
        cmd_task(rest)
    else:
        print(f"Unknown command: {command}\n")
        print(__doc__)
        sys.exit(1)


if __name__ == "__main__":
    main()
