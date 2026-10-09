"""Internet reachability check run before auto-firing scheduled tasks.

Owner-reported 2026-10-09: recent tasks kept failing because the machine
had no internet, and each failure burned a task (and an action_log row)
for a reason that has nothing to do with the task itself. data_sync's
fire_due_tasks() now calls wait_for_internet() once per cycle, before
touching any due task: online -> proceed as usual; still offline after
all retries -> the due tasks go to "Task quá hạn" (schedule_store.
mark_missed) with a "mất mạng" reason, for an admin to reschedule.

Probe = plain TCP connect (no HTTP, no browser). Any ONE target
connecting counts as online, so a single provider blip isn't mistaken
for an outage; www.facebook.com is included since it's the destination
that matters (and catches DNS-only failures)."""
from __future__ import annotations

import asyncio
import logging

logger = logging.getLogger(__name__)

PROBE_TARGETS = (("www.facebook.com", 443), ("1.1.1.1", 443), ("8.8.8.8", 443))
PROBE_TIMEOUT_SECONDS = 5.0
MAX_ATTEMPTS = 3
RETRY_DELAY_SECONDS = 10.0  # 3 attempts ≈ 3*5s probe + 2*10s waits ≈ 30s worst case


async def _can_connect(host: str, port: int, timeout: float) -> bool:
    try:
        _, writer = await asyncio.wait_for(asyncio.open_connection(host, port), timeout)
    except (OSError, asyncio.TimeoutError):
        return False
    writer.close()
    return True


async def is_online(timeout: float = PROBE_TIMEOUT_SECONDS) -> bool:
    results = await asyncio.gather(*(_can_connect(h, p, timeout) for h, p in PROBE_TARGETS))
    return any(results)


async def wait_for_internet(
    attempts: int = MAX_ATTEMPTS, retry_delay: float = RETRY_DELAY_SECONDS,
) -> bool:
    """True as soon as one probe succeeds; False after `attempts` failures."""
    for i in range(1, attempts + 1):
        if await is_online():
            return True
        logger.warning("no internet (attempt %d/%d)", i, attempts)
        if i < attempts:
            await asyncio.sleep(retry_delay)
    return False
