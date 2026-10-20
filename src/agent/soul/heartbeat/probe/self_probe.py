"""心跳自身探针：线体健康（失败计数/线程存活/信箱积压）。"""

from __future__ import annotations

from typing import Any

from agent.soul.heartbeat.probe.base import SoulProbe


class HeartbeatSelfProbe(SoulProbe):
    name = "heartbeat"

    def __init__(self, core) -> None:
        self._core = core  # HeartbeatCoreService | None

    def _sample(self) -> dict[str, Any]:
        if self._core is None:
            raise RuntimeError("core service 未启动")
        mailbox = self._core.mailbox
        return {
            "consecutive_failures": int(self._core.consecutive_failures),
            "thread_alive": bool(self._core.is_running),
            "inject_pending": bool(mailbox.has_pending()),
            "deferred_pending": bool(self._core.deferred_pending),
        }
