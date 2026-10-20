"""presence 部位探针：awake。"""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from agent.soul.heartbeat.probe.base import SoulProbe

if TYPE_CHECKING:
    from agent.soul.service import SoulService


class PresenceProbe(SoulProbe):
    name = "presence"

    def __init__(self, soul: "SoulService | None") -> None:
        self._soul = soul

    def _sample(self) -> dict[str, Any]:
        presence = getattr(self._soul, "presence", None) if self._soul is not None else None
        if presence is None:
            raise RuntimeError("presence 未接线")
        return {"awake": bool(presence.is_awake())}
