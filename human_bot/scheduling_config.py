"""
Purpose of this file / Muc dich cua file nay:
EN: Config for the schedule "fire" safety gate — deliberately its own
module, separate from human_bot/data_sync_config.py's DataSyncConfig.
`auto_fire_enabled` used to live inside DataSyncConfig (it was built for
the side-B poller first), but human_bot/data_sync.py's fire_due_tasks()
actually fires EVERY due task in human_bot/schedule_store.py regardless
of source — including ones composed by hand at /admin/post — so keeping
the gate under a "data sync" name/section made it easy to miss while
debugging why a manually-scheduled post never fired (see the conversation
that asked for this move, 2026-09-07: a post scheduled from /admin/post
sat in /admin/schedule past its time because this flag, buried in
"Đồng bộ dữ liệu bên B", was off). Same env-override + /admin-editable
pattern as the other config dataclasses here — see
human_bot/runtime_config.py.
VI: Cau hinh cho cong an toan "no lich" — co chu dich tach thanh module
rieng, khong con nam trong DataSyncConfig (human_bot/data_sync_config.py).
`auto_fire_enabled` truoc day nam trong DataSyncConfig (vi ban dau chi
lam cho bo dong bo ben B), nhung fire_due_tasks() trong human_bot/
data_sync.py thuc ra no MOI bai den gio trong human_bot/schedule_store.py
bat ke nguon goc — ke ca bai soan tay o /admin/post — nen de co nay duoi
ten/muc "dong bo du lieu" rat de bi bo sot khi debug vi sao mot bai len
lich thu cong khong tu dang (xem hoi thoai yeu cau doi cho nay,
2026-09-07: mot bai len lich tu /admin/post nam cho mai o /admin/schedule
qua gio dang vi co nay, chon trong muc "Dong bo du lieu ben B", dang tat).
Cung kieu env-override + chinh duoc qua /admin nhu cac dataclass cau hinh
khac o day — xem human_bot/runtime_config.py.
"""
from __future__ import annotations

import os
from dataclasses import dataclass, field


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None or raw.strip() == "":
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass
class SchedulingConfig:
    # Master safety gate for schedule_store.py's due-task loop
    # (human_bot/data_sync.py's fire_due_tasks()) — applies to EVERY
    # scheduled task, auto-sourced from side B or composed by hand at
    # /admin/post. When False, due tasks are left pending in
    # /admin/schedule for a human to fire manually ("🚀 Đăng ngay" always
    # works regardless of this gate — it's an explicit human click, same
    # trust level as any other /admin action).
    #
    # Reads the new env var name first; falls back to the old
    # DATA_SYNC_AUTO_FIRE_ENABLED name so an existing .env doesn't
    # silently stop working after this rename.
    auto_fire_enabled: bool = field(
        default_factory=lambda: _env_bool(
            "SCHEDULING_AUTO_FIRE_ENABLED",
            _env_bool("DATA_SYNC_AUTO_FIRE_ENABLED", False),
        )
    )
